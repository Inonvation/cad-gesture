"""SolidWorks 中文输入法助手 - 按焦点自动切换键盘布局(HKL)

为什么是键盘布局而不是 IME 转换模式：
用户常用第三方中文输入法（微信/搜狗/百度等）的"中/英"状态活在各自的
TSF 服务里，WM_IME_CONTROL / IMC_SETCONVERSIONMODE 只能改到 IMM 兼容层，
对这些输入法经常无效（现象：任务栏图标不动、字母键照样被吞）。
而"键盘布局/输入语言"是 Windows 键盘层概念，与输入法品牌无关：
- 绘图/非文本控件 → 切到英文布局(00000409)：该线程根本没有中文输入法参与，
  字母/空格原样到达 SW 加速键，S/F/空格等快捷键 100% 可用（等价于手动
  Win+Space 切英文，但全自动）；
- 焦点进入 SW 文本输入框 → 切回最初记住的中文布局(通常 00000804，微信等
  挂在该布局下)：照常打中文。

作用域与安全约束：
1. 只在 SLDWORKS.exe 前台窗口所在线程操作；其他软件与本进程窗口一律不动；
2. 正在输入法组合（打拼音）时绝不动布局，不打断输入；
3. 用户手动 Win+Space 切过（与上次我们设置的不一致）→ 自动尊重，不再抢，
   直到布局与我们再次一致或焦点语境切换；
4. 不改变 AutoCAD/中望的任何手势/命令逻辑（本模块与手势链路完全解耦）。
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import threading
import time

WM_INPUTLANGCHANGEREQUEST = 0x0050
KLF_ACTIVATE = 0x00000001
EN_LANG = 0x0409  # 英文（美国）语言 id（语言标识低 16 位）

# 文本输入控件类名识别（精确/后缀匹配；避免误伤含 editor 的视口类）
_TEXT_EDIT_EXACT = {"edit", "richedit20w", "richedit50w", "richedit"}
_TEXT_EDIT_HINTS = ("combobox", "editbox", "textbox", "inputbox",
                    "autocomplete")

# 助手的适用范围：目标应用可执行文件名包含该片段（小写匹配）
_TARGET_EXE_HINT = "sldworks"

# 状态锁与 per-pid 记忆（跨轮询保留：最初的中文布局、上次应用/override）
_LOCK = threading.Lock()
_PID_STATE = {}  # pid -> {"orig": int|None, "applied": int|None, "override": bool}


# ========== Win32 原语（自包含，不与 command_executor 耦合） ==========

def _window_pid(hwnd) -> int:
    """窗口所属进程 PID；失败返回 0"""
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        pid = wintypes.DWORD()
        user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        return int(pid.value)
    except Exception:
        return 0


def get_foreground_hwnd() -> int:
    """前台顶层窗口 HWND；失败返回 0（64 位需显式 restype）"""
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        h = user32.GetForegroundWindow()
        return int(h) if h else 0
    except Exception:
        return 0


def _thread_layout_low(hwnd) -> int:
    """目标窗口线程当前输入语言低 16 位；取不到返回 0。

    仅当该线程持有键盘焦点时可读（SW 前台时成立）；读不到时返回 0，
    调用方据此跳过，不做任何盲切。
    """
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        pid = wintypes.DWORD()
        tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not tid:
            return 0
        user32.GetKeyboardLayout.restype = ctypes.c_ulonglong
        user32.GetKeyboardLayout.argtypes = [wintypes.DWORD]
        hkl = user32.GetKeyboardLayout(tid)
        return int(hkl) & 0xFFFF if hkl else 0
    except Exception:
        return 0


def _set_layout_low(hwnd, lang_low: int) -> bool:
    """把目标窗口线程输入语言切到 lang_low（如 0x0409 / 0x0804）。

    先 LoadKeyboardLayout 确保布局已装载并拿到完整 HKL，再向目标窗口发
    WM_INPUTLANGCHANGEREQUEST（带超时，目标繁忙不阻塞）。实际是否生效由
    下一轮轮询读回布局验证，这里只保证请求已投递。
    """
    try:
        user32 = ctypes.windll.user32
        user32.LoadKeyboardLayoutW.restype = wintypes.HANDLE
        user32.LoadKeyboardLayoutW.argtypes = [
            wintypes.LPCWSTR, wintypes.DWORD]
        user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t)]
        hkl = user32.LoadKeyboardLayoutW("%04x" % (lang_low & 0xFFFF),
                                         KLF_ACTIVATE)
        if not hkl:
            return False
        result = ctypes.c_size_t()
        ok = user32.SendMessageTimeoutW(
            hwnd, WM_INPUTLANGCHANGEREQUEST, 0, hkl,
            0x0002, 300, ctypes.byref(result))  # SMTO_ABORTIFHUNG
        return bool(ok)
    except Exception:
        return False


def _ime_composing(hwnd) -> bool:
    """目标线程是否正在输入法组合中（候选窗开着等），命中绝不动布局"""
    try:
        imm32 = ctypes.windll.imm32
        imm32.ImmGetContext.restype = wintypes.HANDLE
        imm32.ImmGetContext.argtypes = [wintypes.HWND]
        hc = imm32.ImmGetContext(hwnd)
        if not hc:
            return False
        try:
            imm32.ImmGetOpenStatus.argtypes = [wintypes.HANDLE]
            imm32.ImmGetOpenStatus.restype = wintypes.BOOL
            if not imm32.ImmGetOpenStatus(hc):
                return False
            GCS_COMPSTR = 0x0008
            imm32.ImmGetCompositionStringW.restype = ctypes.c_long
            imm32.ImmGetCompositionStringW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD,
                ctypes.c_void_p, wintypes.DWORD]
            n = imm32.ImmGetCompositionStringW(hc, GCS_COMPSTR, None, 0)
            return n > 0
        finally:
            imm32.ImmReleaseContext.argtypes = [
                wintypes.HWND, wintypes.HANDLE]
            imm32.ImmReleaseContext(hwnd, hc)
    except Exception:
        return False


class _GUIThreadInfo(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def _focus_control_class(hwnd) -> str:
    """目标窗口线程当前聚焦控件类名；失败返回空串"""
    try:
        user32 = ctypes.windll.user32
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        pid = wintypes.DWORD()
        tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
        if not tid:
            return ""
        gui = _GUIThreadInfo()
        gui.cbSize = ctypes.sizeof(_GUIThreadInfo)
        user32.GetGUIThreadInfo.argtypes = [
            wintypes.DWORD, ctypes.POINTER(_GUIThreadInfo)]
        user32.GetGUIThreadInfo.restype = wintypes.BOOL
        if not user32.GetGUIThreadInfo(tid, ctypes.byref(gui)):
            return ""
        if not gui.hwndFocus:
            return ""
        buf = ctypes.create_unicode_buffer(256)
        user32.GetClassNameW.argtypes = [
            wintypes.HWND, wintypes.LPWSTR, ctypes.c_int]
        user32.GetClassNameW(gui.hwndFocus, buf, 256)
        return buf.value
    except Exception:
        return ""


def _is_edit_control_class(class_name: str) -> bool:
    """文本输入控件类名判断（精确/后缀，避免误伤含 editor 的视口类）"""
    n = (class_name or "").strip().lower()
    if not n:
        return False
    if n in _TEXT_EDIT_EXACT:
        return True
    for hint in _TEXT_EDIT_HINTS:
        if hint in n:
            return True
    return n.endswith("edit") or n.endswith("_edit")


def is_target_exe(exe_path: str) -> bool:
    """是否属于助手目标应用（按 exe 文件名判断，不跨进程发消息）"""
    return bool(exe_path) and _TARGET_EXE_HINT in (exe_path or "").lower()


def _exe_of_pid(pid: int) -> str:
    """进程可执行文件路径；失败返回空串"""
    try:
        kernel32 = ctypes.windll.kernel32
        PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
        if not h:
            return ""
        try:
            buf = ctypes.create_unicode_buffer(1024)
            size = wintypes.DWORD(1024)
            kernel32.QueryFullProcessImageNameW.argtypes = [
                wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
                ctypes.POINTER(wintypes.DWORD)]
            kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
            if kernel32.QueryFullProcessImageNameW(
                    h, 0, buf, ctypes.byref(size)):
                return buf.value or ""
            return ""
        finally:
            kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
            kernel32.CloseHandle(h)
    except Exception:
        return ""


# ========== 决策核心（纯函数，可单测） ==========

def _plan(cur_low: int, want_cn: bool, state: dict, en_low: int = EN_LANG):
    """根据当前布局/目标语境决定要切到的语言低 16 位。

    state: {"orig": int|None, "applied": int|None, "override": bool}
        orig    —— 第一次从中文布局切走前记住的中文布局（文本框恢复用）
        applied —— 上次由我们写入的语言低 16 位（None=从未写过）
    cur_low==0 表示读不到，调用方不应进入本函数。

    Returns (target_low|None, new_state)
    """
    cur = cur_low & 0xFFFF
    orig = state.get("orig")
    applied = state.get("applied")
    override = bool(state.get("override"))

    if want_cn:
        if orig is None:
            # 从未由我们切走（用户本就英文/无中文布局记录）：不发明中文
            return None, {"orig": orig, "applied": applied,
                          "override": False}
        desired = orig & 0xFFFF
    else:
        desired = en_low

    if cur == desired:
        return None, {"orig": orig, "applied": cur, "override": False}

    # 实际布局与我们上次写入的不一致 → 用户手动 Win+Space 切过，尊重用户
    if applied is not None and cur != (applied & 0xFFFF):
        override = True
    if override:
        return None, {"orig": orig, "applied": applied, "override": True}

    if not want_cn and orig is None:
        orig = cur  # 记住离开前的中文布局，供切回文本框时恢复

    return desired, {"orig": orig, "applied": desired, "override": False}


# ========== 轮询执行 ==========

def run_cycle() -> bool:
    """执行一轮助手判定；返回是否对键盘布局做了切换。

    由主线程低频定时器调用（~100ms）。未命中 SW 前台/组合态/布局未变等
    情况快速返回，不做任何 Win32 写入。
    """
    try:
        hwnd = get_foreground_hwnd()
        if not hwnd:
            return False
        pid = _window_pid(hwnd)
        if not pid or pid == os.getpid():
            return False  # 本进程窗口（圆盘/提示等）：不动作
        exe = _exe_of_pid(pid)
        if not is_target_exe(exe):
            return False  # 只管理 SLDWORKS，其他软件一律不管
        if _ime_composing(hwnd):
            return False  # 正在打拼音：绝不打断
        cur = _thread_layout_low(hwnd)
        if not cur:
            return False  # 该线程当前未持有键盘焦点，读不到 → 不盲切
        focus_class = _focus_control_class(hwnd)
        want_cn = _is_edit_control_class(focus_class)
        with _LOCK:
            state = dict(_PID_STATE.get(pid) or {
                "orig": None, "applied": None, "override": False})
        last_fail = state.get("last_fail") or 0
        if time.monotonic() - last_fail < 2.0:
            return False  # 上次切换失败：退避 2s 再试，别每 100ms 空转
        target, new_state = _plan(cur, want_cn, state)

        def _core(d):
            return (d.get("orig"), d.get("applied"),
                    bool(d.get("override")))

        if target is None:
            if _core(state) != _core(new_state):
                with _LOCK:
                    _PID_STATE[pid] = new_state
            return False
        ok = _set_layout_low(hwnd, target)
        with _LOCK:
            if ok:
                _PID_STATE[pid] = new_state
            else:
                _PID_STATE[pid] = dict(new_state, last_fail=time.monotonic())
        return ok
    except Exception:
        return False
