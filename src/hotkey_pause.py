"""全局暂停快捷键 — Win32 RegisterHotKey 实现

设置里配置快捷键（如 Ctrl+Alt+P）后，在任意程序内按下即可切换
「暂停手势」状态（与托盘菜单的暂停开关一致）。默认留空 = 不注册、
功能关闭，不占用任何按键。

为什么用 RegisterHotKey 而不是再挂一个低级键盘钩子：
- 系统级注册一次即可，无需常驻回调，不给全局键盘输入链增加负担；
- 命中后按键被系统消费（不传给其他程序），符合"全局热键"预期；
- 注册失败（快捷键已被其他程序占用）有明确错误，便于提示用户换键。

线程模型：start() 起守护线程跑 GetMessage 循环（RegisterHotKey 绑定
调用线程，WM_HOTKEY 投递到该线程队列）。set_hotkey() 任意线程可调：
把新键值放入待注册槽并 PostThreadMessage 唤醒工作线程换键，同步等待
结果（最多 2 秒）。_current 仅在工作线程写、其他线程只在锁内读，
GIL 下读写安全。
"""

import ctypes
import ctypes.wintypes as wintypes
import threading

WM_HOTKEY = 0x0312
WM_QUIT = 0x0012
WM_APP_RELOAD = 0x8000 + 1  # WM_APP+1：让工作线程应用待注册槽里的新键值

MOD_ALT = 0x0001
MOD_CONTROL = 0x0002
MOD_SHIFT = 0x0004
MOD_WIN = 0x0008
MOD_NOREPEAT = 0x4000  # 按住不重复触发（Win7+）

# 本进程内唯一的热键 id（同一进程可注册多个热键，这里只有一个）
_HOTKEY_ID = 0x9C61

# 快捷键字符串（QKeySequence PortableText，统一小写匹配）→ Win32 VK 码
_VK_MAP = {
    "space": 0x20, "tab": 0x09, "enter": 0x0D, "return": 0x0D,
    "esc": 0x1B, "escape": 0x1B, "backspace": 0x08,
    "delete": 0x2E, "del": 0x2E, "insert": 0x2D, "ins": 0x2D,
    "home": 0x24, "end": 0x23,
    "pageup": 0x21, "pgup": 0x21, "pagedown": 0x22, "pgdown": 0x22,
    "left": 0x25, "up": 0x26, "right": 0x27, "down": 0x28,
    # 常用标点（QKeySequence PortableText 用原字符表示）
    ";": 0xBA, "=": 0xBB, ",": 0xBC, "-": 0xBD, ".": 0xBE, "/": 0xBF,
    "`": 0xC0, "[": 0xDB, "\\": 0xDC, "]": 0xDD, "'": 0xDE,
}
for _i in range(26):
    _VK_MAP[chr(ord("a") + _i)] = 0x41 + _i      # A~Z
for _i in range(10):
    _VK_MAP[str(_i)] = 0x30 + _i                  # 0~9
for _i in range(24):
    _VK_MAP[f"f{_i + 1}"] = 0x70 + _i             # F1~F24

_MOD_NAMES = {
    "ctrl": MOD_CONTROL, "control": MOD_CONTROL,
    "alt": MOD_ALT,
    "shift": MOD_SHIFT,
    "win": MOD_WIN, "meta": MOD_WIN, "windows": MOD_WIN,
}


def parse_hotkey(text: str):
    """解析快捷键字符串 → (modifiers, vk)；无法解析返回 None。

    接受 "Ctrl+Alt+P" / "Ctrl+Shift+F5" / "F9" 风格（QKeySequence
    PortableText；"Meta" 视作 Win 键）。允许多个修饰键 + 恰好一个主键；
    多段组合（"Ctrl+X, Ctrl+C"）与未识别键名返回 None。
    """
    if not text:
        return None
    mod = 0
    vk = 0
    for part in str(text).split("+"):
        p = part.strip().lower()
        if not p:
            continue
        m = _MOD_NAMES.get(p)
        if m:
            mod |= m
        elif vk == 0:
            vk = _VK_MAP.get(p, 0)
            if vk == 0:
                return None
        else:
            return None  # 出现第二个主键（多段组合），RegisterHotKey 不支持
    if vk == 0:
        return None
    return mod, vk


def is_valid_hotkey(text: str) -> bool:
    """是否为可安全注册为全局热键的组合。

    全局热键会被系统级吞掉：无 Ctrl/Alt/Win 修饰的字母/数字/标点
    （打字即触发）与 Shift+字母（大写字母）一律拒绝；F1~F24 单键
    不与输入冲突，允许不带修饰键。
    """
    parsed = parse_hotkey(text)
    if parsed is None:
        return False
    mod, vk = parsed
    if mod & (MOD_CONTROL | MOD_ALT | MOD_WIN):
        return True
    return mod == 0 and 0x70 <= vk <= 0x87  # VK_F1..VK_F24


class PauseHotkey:
    """全局热键管理：注册/更换/注销 + WM_HOTKEY → on_toggle 回调

    on_toggle 在热键线程被调用，线程安全由调用方保证（app 端经
    event_queue 转主线程）。
    """

    def __init__(self, on_toggle, log=None):
        self._on_toggle = on_toggle
        self._log = log
        self._thread = None
        self._thread_id = 0
        self._ready = threading.Event()
        self._lock = threading.Lock()
        self._pending = None          # 待应用：(mod, vk)；None = 仅注销
        self._current = None          # 当前已注册：(mod, vk)
        self._result = None           # 最近一次换键结果 (ok, err)
        self._done = threading.Event()

    def start(self) -> bool:
        """启动工作线程（消息循环就绪后返回 True）"""
        if self._thread is not None and self._thread.is_alive():
            return True
        self._thread = threading.Thread(
            target=self._run, name="PauseHotkey", daemon=True)
        self._thread.start()
        return self._ready.wait(timeout=2.0)

    def stop(self):
        """退出工作线程并注销热键（进程退出前调用）"""
        thread = self._thread
        if thread is None:
            return
        self._thread = None
        try:
            ctypes.windll.user32.PostThreadMessageW(
                thread.ident, WM_QUIT, 0, 0)
        except Exception:
            pass
        thread.join(timeout=2.0)

    def set_hotkey(self, text: str):
        """注册/更换/注销快捷键（任意线程可调，同步等待结果）。

        返回 (ok, err)。err 取值：
        ""        成功（含注销成功）
        "invalid" 格式无法解析，或是不安全组合（会干扰打字）
        "occupied" 系统拒绝注册（快捷键已被其他程序占用）
        "timeout" 工作线程未响应
        空字符串 = 注销当前快捷键（功能关闭）。键值未变化时直接返回成功，
        不重复注册（配置重载会反复调用这里）。
        """
        text = (text or "").strip()
        parsed = parse_hotkey(text)
        if text and not is_valid_hotkey(text):
            return False, "invalid"
        if self._thread is None or not self._thread.is_alive():
            return (False, "timeout") if text else (True, "")
        with self._lock:
            if parsed == self._current:
                return True, ""
            self._pending = parsed
            self._result = None
            self._done.clear()
        try:
            posted = ctypes.windll.user32.PostThreadMessageW(
                self._thread_id, WM_APP_RELOAD, 0, 0)
        except Exception:
            posted = False
        if not posted:
            return False, "timeout"
        if not self._done.wait(timeout=2.0):
            return False, "timeout"
        with self._lock:
            return self._result if self._result is not None else (False, "timeout")

    # ---- 工作线程 ----

    def _run(self):
        try:
            self._run_loop()
        except Exception as e:
            if self._log is not None:
                try:
                    self._log.error("暂停快捷键线程异常: %s", e, exc_info=True)
                except Exception:
                    pass
        finally:
            # 线程退出前注销：热键绑定本线程，线程死亡即失效
            if self._current is not None:
                try:
                    ctypes.windll.user32.UnregisterHotKey(None, _HOTKEY_ID)
                except Exception:
                    pass
                self._current = None

    def _run_loop(self):
        user32 = ctypes.windll.user32
        self._thread_id = ctypes.windll.kernel32.GetCurrentThreadId()
        msg = wintypes.MSG()
        # 先创建本线程消息队列：PeekMessage(PM_NOREMOVE) 只探测不取消息，
        # 但会创建队列——否则 ready 之后 set_hotkey 立即 PostThreadMessage
        # 可能因队列尚不存在而投递失败（表现为注册超时，偶发竞态）
        user32.PeekMessageW(ctypes.byref(msg), None, 0, 0, 0)
        self._ready.set()
        while True:
            ret = user32.GetMessageW(ctypes.byref(msg), None, 0, 0)
            if ret <= 0:  # 0 = WM_QUIT，-1 = 错误
                break
            if msg.message == WM_HOTKEY and msg.wParam == _HOTKEY_ID:
                try:
                    self._on_toggle()
                except Exception:
                    pass
            elif msg.message == WM_APP_RELOAD:
                self._apply_pending(user32)

    def _apply_pending(self, user32):
        """先注销旧键再注册新键，结果写回 _result 并唤醒等待方"""
        with self._lock:
            pending = self._pending
            self._pending = None
        ok, err = True, ""
        if self._current is not None:
            user32.UnregisterHotKey(None, _HOTKEY_ID)
            self._current = None
        if pending is not None:
            mod, vk = pending
            if not user32.RegisterHotKey(
                    None, _HOTKEY_ID, mod | MOD_NOREPEAT, vk):
                ok, err = False, "occupied"
                if self._log is not None:
                    try:
                        self._log.warning(
                            "暂停快捷键注册失败（可能被占用）: mod=0x%X vk=0x%X",
                            mod, vk)
                    except Exception:
                        pass
            else:
                self._current = pending
        with self._lock:
            self._result = (ok, err)
            self._done.set()
