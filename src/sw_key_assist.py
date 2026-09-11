"""SolidWorks 中文输入法快捷键直通 —— 按键拦截 + 直投（方案 M1）

根因（为什么必须这么绕）：
    中文输入法在**消息队列层**（TSF/IMM）截获字母键用于开启拼音组合，键根本到不了 SW 的
    窗口过程，所以 SW 侧怎么设置都没用；`SendInput` 的注入点在「布局映射之前」，同样绕不过。
    本模块改在「按键入队之前」用低级键盘钩子判定：命中条件就把按键吞掉，改为把
    WM_KEYDOWN / WM_KEYUP **直接投给 SW 的窗口**（PostMessage）—— 消息在队列层入队，
    不经过 IME 预处理，因此输入法全程不被触碰，语言栏保持中文。

线程模型（三个角色，职责严格分离）：
    1) 轮询（主线程，app 的 100ms QTimer 驱动）—— `probe_context()` 采集现场 + `update()`
       发布快照。所有重活（OpenProcess / 取 exe / GetGUIThreadInfo / 提权查询）都在这里做。
    2) 钩子线程 —— WH_KEYBOARD_LL 回调只做「读快照 + 廉价判定 + 入队」，**绝不 IPC /
       SendMessage**：低级钩子回调超时会拖慢全局输入，Windows 还会静默移除超时的钩子。
    3) 投递线程 —— 从队列取任务，构造 lParam 后 PostMessage；连续失败达阈值即自动降级
       （彻底停用拦截），宁可不生效也绝不吞键。

安全边界（对应需求里的三条「不影响」）：
    * 非 SLDWORKS 前台一律放行 → 不影响其他软件。且每键都重查 GetForegroundWindow，
      封死 100ms 快照的竞态窗口（否则切换窗口的瞬间可能在别的软件里吞键）。
    * 焦点不是绘图区一律放行 → 不影响 SW 中文输入。用**正向白名单**判定而不是反向排除：
      认不出就不吞，代价只是快捷键不生效（等于现状）；误吞会让用户打不出拼音。
      两种失败的代价不对称，所以默认偏保守，并把认不出的类名节流记进日志便于补白名单。
    * 回调首行判 `LLKHF_INJECTED` 直接放行 → 绝不吃掉注入的按键。这是「不改动既有 CAD
      逻辑」的技术保证：CAD 的 pyautogui 回退正是注入键。
    * SW 以更高完整性级别运行（UIPI 会拦下 PostMessage）时关闭直通 → 不吞注定无效的键。

与 CAD 手势链路的关系：**零耦合**。本模块不 import gesture_engine / command_executor，
自建独立钩子线程；两者互不可见。
"""

import ctypes
import ctypes.wintypes as wintypes
import os
import queue
import re
import threading
import time
from typing import Iterable
from typing import NamedTuple

# ========== Win32 常量 ==========

WH_KEYBOARD_LL = 13
HC_ACTION = 0

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_SYSKEYDOWN = 0x0104
WM_SYSKEYUP = 0x0105

LLKHF_INJECTED = 0x00000010  # KBDLLHOOKSTRUCT.flags 位：事件来自注入

MAPVK_VK_TO_VSC = 0

VK_SHIFT = 0x10
VK_CONTROL = 0x11
VK_MENU = 0x12
VK_LWIN = 0x5B
VK_RWIN = 0x5C

TOKEN_QUERY = 0x0008
TokenElevation = 20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

# 目标应用：可执行文件名片段（小写匹配），与 sw_ime_assist 保持一致
TARGET_EXE_HINT = "sldworks"

# 默认拦截键集：字母 + 数字 + 空格。空格在中文输入法下同样会被吞（SW 里是视图定向），
# 所以默认包含；数字一般不被吞，但放进键集也无害。
DEFAULT_KEY_LIST = "A-Z,0-9,SPACE"

# 控件类名识别（文本输入 vs 绘图区）
_TEXT_EDIT_EXACT = {"edit", "richedit", "richedit20a", "richedit20w",
                    "richedit50w"}
_TEXT_EDIT_HINTS = ("combobox", "editbox", "textbox", "inputbox",
                    "autocomplete", "spin")
# 绘图区视口类名线索（来自 SW 2024 真机实录：AfxFrameOrView140u / GXWND）
_VIEW_CLASS_HINTS = ("afxframeorview", "gxwnd", "sldworksview", "swview")

# IME 组合窗口类名线索（各输入法实现略有差异，取交集）
_IME_CLASS_HINTS = ("ime", "ctfime", "msctfime", "TextInputHost",
                    "imm32")

# MFC 自定义窗口需覆盖框架客户区多大比例才认定为「视口」而不是对话框里的控件
VIEW_COVERAGE_MIN = 0.5

# 投递连续失败多少次后自动降级（放弃拦截）
FAIL_LIMIT = 5

# 64 位 LRESULT 是指针宽度，钩子回调必须返回 c_ssize_t（否则 64 位下崩溃）
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                              wintypes.WPARAM, wintypes.LPARAM)

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32


class KBDLLHOOKSTRUCT(ctypes.Structure):
    _fields_ = [
        ("vkCode", wintypes.DWORD),
        ("scanCode", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


# ========== 纯函数（可单测，不含 Win32 调用） ==========

_KEY_NAME_TO_VK = {"SPACE": 0x20, "空格": 0x20, "ENTER": 0x0D, "TAB": 0x09}


def parse_key_list(text: str) -> frozenset:
    """解析键集文本 → 虚拟键码集合。

    支持 `A-Z`（区间）、`0-9`、单个字母/数字、`SPACE`（也接受中文"空格"），
    用逗号/分号/空格分隔。无法识别的 token 直接忽略（不抛异常，配置容错）。
    """
    out = set()
    for token in re.split(r"[,，;；\s]+", (text or "").upper()):
        token = token.strip()
        if not token:
            continue
        if token in _KEY_NAME_TO_VK:
            out.add(_KEY_NAME_TO_VK[token])
            continue
        m = re.fullmatch(r"([A-Z0-9])\s*-\s*([A-Z0-9])", token)
        if m:
            lo, hi = ord(m.group(1)), ord(m.group(2))
            if lo <= hi:
                out.update(range(lo, hi + 1))
            continue
        if re.fullmatch(r"[A-Z0-9]", token):
            out.add(ord(token))
    return frozenset(out)


def build_key_lparam(vk: int, is_keyup: bool, use_scan: bool = True) -> int:
    """拼 WM_KEYDOWN / WM_KEYUP 的 lParam 位域。

    0-15 重复次数(1)、16-23 扫描码、24 扩展键、29 上下文、30 前一次状态、
    31 过渡位（按下 0 / 抬起 1）。扫描码必须来自 MapVirtualKey；裸填 1 是
    「发一次却响应两次 / F1 变 t」这类经典坑。
    """
    sc = 0
    if use_scan:
        sc = int(user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC)) & 0xFF
    lp = 1 | (sc << 16)
    if is_keyup:
        lp |= (1 << 30) | (1 << 31)
    return lp


def classify_focus(class_name: str, caret_present: bool = False,
                   focus_is_frame: bool = False, coverage: float = 0.0,
                   extra_hints: Iterable[str] = (),
                   ime_focus: bool = False) -> str:
    """把当前焦点分类为 "text" / "view" / "unknown"。

    判定顺序即优先级：先认「文本输入」，再认「绘图区视口」，最后兜底 unknown。
    unknown 的语义是**放行**（保守），由调用方决定是否记录待补白名单。

    `ime_focus=True` 表示焦点实际落在 IME 组合窗口上（中文输入法抢走了
    hwndFocus）；此时不应因 caret 误判为文本输入，转入视口/兜底判定。
    """
    if caret_present and not ime_focus:
        return "text"
    if ime_focus:
        # 焦点在 IME 组合窗口上：跳过全部文本类判定（类名/词干可能巧合匹配），
        # 直接走视口/兜底 —— 避免"快捷键变拼音"。
        n_ime = (class_name or "").strip().lower()
        for hint in _VIEW_CLASS_HINTS:
            if hint in n_ime:
                return "view"
        for hint in extra_hints:
            h = (hint or "").strip().lower()
            if h and h in n_ime:
                return "view"
        return "unknown"
    n = (class_name or "").strip().lower()
    if not n:
        return "unknown"
    if n in _TEXT_EDIT_EXACT or n.endswith("edit"):
        return "text"
    for hint in _TEXT_EDIT_HINTS:
        if hint in n:
            return "text"
    for hint in _VIEW_CLASS_HINTS:
        if hint in n:
            return "view"
    for hint in extra_hints:
        h = (hint or "").strip().lower()
        if h and h in n:
            return "view"
    # MFC 自定义窗口（SW 主框架与部分视口都是 Afx: 开头）：
    # 只有覆盖住框架客户区大半，才认定是视口 —— 对话框里的自定义控件不会这么大。
    if coverage >= VIEW_COVERAGE_MIN and (n.startswith("afx:")
                                          or focus_is_frame):
        return "view"
    return "unknown"


class Snap(NamedTuple):
    """上下文快照（不可变，主线程写 / 钩子线程读，靠 GIL 原子换引用）。

    `enabled` 的语义是「本快照允许拦截」，即：功能已开 + 目标在前台 + 未被禁用
    （提权/降级）。SW 不在前台时它就是 False —— 钩子回调据此直接放行。
    """
    enabled: bool = False
    sw_hwnd: int = 0          # SLDWORKS 顶层窗口；0 = 非目标前台
    focus_hwnd: int = 0       # 目标线程当前焦点控件
    focus_kind: str = "unknown"
    focus_class: str = ""
    composing: bool = False   # 正在拼音组合（best-effort：跨进程常读不到）
    ime_focus: bool = False   # 焦点实际在 IME 组合窗口上（caret 被 IME 抢走）
    pm_edit: bool = False     # 焦点在 PropertyManager 的参数输入框上
    elevated_blocked: bool = False
    delivery_broken: bool = False
    keyset: frozenset = frozenset()


def should_intercept(vk: int, is_keyup: bool, snap: Snap, fg_hwnd: int,
                     injected: bool, modifier_down: bool) -> bool:
    """唯一决策函数：True = 吞键并直投。

    任何一条守卫命中即放行 —— 顺序无关，因为全部是「否决」语义。
    """
    if injected:                       # 注入事件：CAD 的 pyautogui 回退靠它不被吃
        return False
    if is_keyup:                       # 抬起由 _held 集合单独决定（见钩子回调）
        return False
    if not snap.enabled:
        return False
    if snap.delivery_broken:           # 投递已经坏了：不再吞键
        return False
    if snap.elevated_blocked:          # SW 提权：PostMessage 必被 UIPI 拦
        return False
    if not snap.sw_hwnd or fg_hwnd != snap.sw_hwnd:
        return False                   # 非目标前台 / 快照过期：放行
    if modifier_down:                  # Ctrl/Shift/Alt/Win 组合键不进 IME，无需干预
        return False
    if vk not in snap.keyset:
        return False
    if snap.focus_kind != "view":      # 文本控件与未知控件都放行（保守）
        # 例外：焦点在 PropertyManager 参数输入框上时，单字母键仍需拦截并转发到
        # 绘图区视口 —— 否则快捷键（E/S/D...）会被输入框吃掉或被 IME 拼成拼音。
        # 数字/空格放行给输入框（用户可能在输入尺寸值）。
        if not (snap.pm_edit and ord("A") <= vk <= ord("Z")):
            return False
    if snap.ime_focus:
        # 焦点在 IME 组合窗口上：composition 已在进行（跳过 composing 守卫），
        # 但视口语境仍然成立 → 继续拦截（吞键 + 直投主窗口）。
        return True
    if snap.composing:                 # 正在打拼音：绝不打断
        return False
    return True


# ========== Win32 查询（真机调用） ==========

_EXE_CACHE = {}   # hwnd -> (pid, is_target)
_ELEV_CACHE = {}  # pid -> bool（进程提权状态）
_CACHE_LIMIT = 64


def _foreground_hwnd() -> int:
    user32.GetForegroundWindow.restype = wintypes.HWND
    h = user32.GetForegroundWindow()
    return int(h) if h else 0


def _window_pid(hwnd: int) -> int:
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    pid = wintypes.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def _window_tid(hwnd: int) -> int:
    user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    pid = wintypes.DWORD()
    return int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))) or 0


def _exe_of_pid(pid: int) -> str:
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                     wintypes.DWORD]
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
        if kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return buf.value or ""
        return ""
    finally:
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
        kernel32.CloseHandle(h)


def _is_target_window(hwnd: int, pid: int) -> bool:
    """是否 SLDWORKS 窗口；按 hwnd 缓存，避免每键都 OpenProcess。"""
    cached = _EXE_CACHE.get(hwnd)
    if cached and cached[0] == pid:
        return cached[1]
    exe = _exe_of_pid(pid)
    is_target = TARGET_EXE_HINT in (exe or "").lower()
    if len(_EXE_CACHE) > _CACHE_LIMIT:
        _EXE_CACHE.clear()
    _EXE_CACHE[hwnd] = (pid, is_target)
    return is_target


def _is_elevated(pid: int) -> bool:
    if pid in _ELEV_CACHE:
        return _ELEV_CACHE[pid]
    advapi32 = ctypes.windll.advapi32
    kernel32.OpenProcess.restype = wintypes.HANDLE
    kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                     wintypes.DWORD]
    proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    result = False
    if proc:
        try:
            advapi32.OpenProcessToken.argtypes = [
                wintypes.HANDLE, wintypes.DWORD,
                ctypes.POINTER(wintypes.HANDLE)]
            advapi32.OpenProcessToken.restype = wintypes.BOOL
            token = wintypes.HANDLE()
            if advapi32.OpenProcessToken(proc, TOKEN_QUERY,
                                         ctypes.byref(token)):
                try:
                    advapi32.GetTokenInformation.argtypes = [
                        wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                        wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
                    advapi32.GetTokenInformation.restype = wintypes.BOOL
                    info = wintypes.DWORD(0)
                    ret = wintypes.DWORD(0)
                    if advapi32.GetTokenInformation(
                            token, TokenElevation, ctypes.byref(info),
                            ctypes.sizeof(info), ctypes.byref(ret)):
                        result = bool(info.value)
                finally:
                    kernel32.CloseHandle(token)
        finally:
            kernel32.CloseHandle(proc)
    _ELEV_CACHE[pid] = result
    return result


def _gui_thread_info(tid: int) -> GUITHREADINFO:
    gui = GUITHREADINFO()
    gui.cbSize = ctypes.sizeof(GUITHREADINFO)
    user32.GetGUIThreadInfo.argtypes = [
        wintypes.DWORD, ctypes.POINTER(GUITHREADINFO)]
    user32.GetGUIThreadInfo.restype = wintypes.BOOL
    user32.GetGUIThreadInfo(tid, ctypes.byref(gui))
    return gui


def _class_name(hwnd: int) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW.argtypes = [wintypes.HWND, wintypes.LPWSTR,
                                     ctypes.c_int]
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def _is_pm_edit_control(focus_hwnd: int, depth: int = 2) -> bool:
    """判断焦点是否在 PropertyManager 的输入框上。

    SW 2024 真机实录：PropertyManager 参数输入框是标准 Edit 控件，
    父窗口是 #32770（标准对话框），深度 2 以内可达。
    用 parent 链而非递归 EnumChildWindows —— 每次 probe 只走 ≤2 步，开销极低。
    """
    if not focus_hwnd:
        return False
    p = user32.GetParent(focus_hwnd)
    for _ in range(depth):
        if not p:
            return False
        if _class_name(p) == "#32770":
            return True
        p = user32.GetParent(p)
    return False


def _find_viewport(frame_hwnd: int, max_depth: int = 6) -> int:
    """在 SW 框架下找绘图区视口 hwnd。

    SW 2024 真机实录：视口是 swMdiClient → 文档窗口 → AfxMDIFrame140u 链
    末端最大的可见子窗口。取客户区面积最大的 AfxMDIFrame140u 作为视口。
    """
    best, best_area = 0, 0

    def walk(parent, depth):
        nonlocal best, best_area
        if depth > max_depth:
            return
        child = user32.GetWindow(parent, 5)  # GW_CHILD
        while child:
            if user32.IsWindowVisible(child):
                cls = _class_name(child).lower()
                if "afxmdiframe" in cls:
                    r = wintypes.RECT()
                    user32.GetClientRect(child, ctypes.byref(r))
                    area = max(0, r.right - r.left) * max(0, r.bottom - r.top)
                    if area > best_area:
                        best_area = area
                        best = child
                walk(child, depth + 1)
            child = user32.GetWindow(child, 2)  # GW_HWNDNEXT

    walk(frame_hwnd, 0)
    return best


def _is_ime_focus_window(focus_hwnd: int, frame_hwnd: int) -> bool:
    """判断当前焦点是否落在 IME 组合窗口上（而非目标应用自己的控件）。

    中文 IME 弹出拼音组合窗口时会抢走 hwndFocus；此时 classify_focus 会因
    caret 判成 "text"，导致按键被放行给 IME —— 这正是"快捷键变拼音"的根因。
    本函数在 probe 阶段调用（100ms 轮询，开销可接受），结果写入快照供钩子
    回调读取。
    """
    if not focus_hwnd or focus_hwnd == frame_hwnd:
        return False
    # 焦点窗口与目标主窗口不同线程 → 多半是 IME 注入的组合窗口
    ftid = _window_tid(focus_hwnd)
    ptid = _window_tid(frame_hwnd)
    if ftid and ptid and ftid != ptid:
        return True
    # 兜底：类名匹配 IME 线索（部分输入法与目标同线程）
    n = (_class_name(focus_hwnd) or "").lower()
    return any(h in n for h in _IME_CLASS_HINTS)


def _client_coverage(focus_hwnd: int, frame_hwnd: int) -> float:
    """焦点控件客户区占框架客户区的面积比（识别"视口 vs 对话框小控件"）。"""
    if not focus_hwnd or not frame_hwnd:
        return 0.0
    r1, r2 = wintypes.RECT(), wintypes.RECT()
    user32.GetClientRect.argtypes = [wintypes.HWND, ctypes.POINTER(wintypes.RECT)]
    user32.GetClientRect.restype = wintypes.BOOL
    if not user32.GetClientRect(focus_hwnd, ctypes.byref(r1)):
        return 0.0
    if not user32.GetClientRect(frame_hwnd, ctypes.byref(r2)):
        return 0.0
    a1 = max(0, r1.right - r1.left) * max(0, r1.bottom - r1.top)
    a2 = max(0, r2.right - r2.left) * max(0, r2.bottom - r2.top)
    return (a1 / a2) if a2 else 0.0


def _ime_composing(hwnd: int) -> bool:
    """是否正在拼音组合（best-effort）。

    实测：跨进程 `ImmGetContext` 基本取不到上下文（裸调用与 AttachThreadInput 后都取不到），
    所以这个守卫经常返回 False。它只作为「文本控件白名单」之外的额外保险，不能当唯一依赖。
    """
    imm32 = ctypes.windll.imm32
    imm32.ImmGetContext.restype = wintypes.HANDLE
    imm32.ImmGetContext.argtypes = [wintypes.HWND]
    try:
        hc = imm32.ImmGetContext(hwnd)
    except Exception:
        return False
    if not hc:
        return False
    try:
        imm32.ImmGetCompositionStringW.restype = ctypes.c_long
        imm32.ImmGetCompositionStringW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        return int(imm32.ImmGetCompositionStringW(hc, 0x0008, None, 0)) > 0
    except Exception:
        return False
    finally:
        try:
            imm32.ImmReleaseContext.argtypes = [wintypes.HWND,
                                                wintypes.HANDLE]
            imm32.ImmReleaseContext(hwnd, hc)
        except Exception:
            pass


def _any_modifier_down() -> bool:
    """Ctrl / Shift / Alt / Win 是否按住（廉价本地调用，可在钩子回调里用）。"""
    user32.GetAsyncKeyState.restype = ctypes.c_short
    user32.GetAsyncKeyState.argtypes = [ctypes.c_int]
    for vk in (VK_SHIFT, VK_CONTROL, VK_MENU, VK_LWIN, VK_RWIN):
        if user32.GetAsyncKeyState(vk) & 0x8000:
            return True
    return False


def _extra_class_hints(settings: dict) -> tuple:
    raw = (settings or {}).get("sw_key_extra_classes", "") or ""
    return tuple(x.strip().lower() for x in re.split(r"[,，;；\s]+", raw)
                 if x.strip())


def probe_context(settings: dict = None) -> Snap:
    """采集上下文快照（主线程轮询调用；SW 不在前台时只做 1~2 次廉价调用）。"""
    settings = settings or {}
    enabled = bool(settings.get("ime_assist_sw", True))
    if (settings.get("ime_assist_mode", "key") or "key") != "key":
        enabled = False
    keyset = parse_key_list(settings.get("sw_key_list", DEFAULT_KEY_LIST))
    base = Snap(enabled=False, keyset=keyset)
    if not enabled:
        return base

    fg = _foreground_hwnd()
    if not fg:
        return base
    pid = _window_pid(fg)
    if not pid or pid == os.getpid():
        return base  # 本进程窗口（圆盘/提示）不是目标
    if not _is_target_window(fg, pid):
        return base

    blocked = _is_elevated(pid) and not _is_elevated(os.getpid())
    tid = _window_tid(fg)
    focus = 0
    caret = False
    if tid:
        gui = _gui_thread_info(tid)
        focus = int(gui.hwndFocus) if gui.hwndFocus else 0
        caret = bool(gui.hwndCaret)
    cls = _class_name(focus) if focus else ""
    coverage = _client_coverage(focus, fg)
    ime_focus = bool(focus) and focus != fg and _is_ime_focus_window(focus, fg)
    # PropertyManager 输入框检测：只在焦点是 Edit 类控件时查 parent 链（省调用）
    pm_edit = bool(focus) and cls.lower() == "edit" and _is_pm_edit_control(focus)
    kind = classify_focus(cls, caret, focus == fg, coverage,
                          _extra_class_hints(settings),
                          ime_focus=ime_focus)
    # 只有可能吞键（视口）时才去查组合态，省掉每 100ms 一次无用的跨进程调用
    composing = _ime_composing(fg) if kind == "view" else False
    return Snap(enabled=not blocked, sw_hwnd=fg, focus_hwnd=focus or fg,
                focus_kind=kind, focus_class=cls, composing=composing,
                ime_focus=ime_focus, pm_edit=pm_edit,
                elevated_blocked=blocked, delivery_broken=False,
                keyset=keyset)


# ========== 投递 ==========

def _call_next(hook, nCode, wParam, lParam):
    user32.CallNextHookEx.restype = ctypes.c_ssize_t
    user32.CallNextHookEx.argtypes = [
        wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM]
    return user32.CallNextHookEx(hook, nCode, wParam, lParam)


def _post(hwnd: int, msg: int, vk: int, lp: int) -> bool:
    user32.PostMessageW.restype = wintypes.BOOL
    user32.PostMessageW.argtypes = [wintypes.HWND, wintypes.UINT,
                                    wintypes.WPARAM, wintypes.LPARAM]
    return bool(user32.PostMessageW(hwnd, msg, vk, lp))


def post_key_pair(hwnd: int, vk: int) -> bool:
    """把一次完整的按下+抬起直投给目标窗口；两次都入队才算成功。"""
    if not hwnd:
        return False
    down = _post(hwnd, WM_KEYDOWN, vk, build_key_lparam(vk, False))
    up = _post(hwnd, WM_KEYUP, vk, build_key_lparam(vk, True))
    return down and up


# ========== 拦截器 ==========

_UNKNOWN_LOG_INTERVAL = 5.0  # 同类名"未识别"日志的最小间隔（秒）


class Interceptor:
    """键盘拦截 + 直投。生命周期由 app 控制：start() / update() / stop()。"""

    def __init__(self, log=None):
        self._log_fn = log
        self._lock = threading.Lock()
        self._snap = Snap()
        self._hook = None
        self._callback = None
        self._hook_thread = None
        self._deliver_thread = None
        self._queue = queue.Queue(maxsize=64)
        self._ready = threading.Event()
        self._running = False
        self._held = set()          # 已吞下的按键（用于吞掉对应抬起、抑制自动重复）
        self._fail_streak = 0
        self._delivery_broken = False
        self._unknown_logged = {}
        self._logged_classes = set()   # 已记录过"直通生效"的焦点类（去重，不刷屏）
        self.stats = {"swallowed": 0, "delivered": 0, "failed": 0,
                      "unknown_focus": 0}

    # ---------- 日志 ----------

    def _log(self, msg: str, level: str = "info"):
        try:
            fn = getattr(self._log_fn, level, None) if self._log_fn else None
            if callable(fn):
                fn("[SWKey] %s" % msg)
        except Exception:
            pass

    # ---------- 生命周期 ----------

    def start(self) -> bool:
        with self._lock:
            if self._hook is not None:
                return True
            self._ready.clear()
        self._callback = HOOKPROC(self._hook_proc)
        self._running = True
        self._deliver_thread = threading.Thread(
            target=self._deliver_loop, daemon=True, name="sw-key-deliver")
        self._deliver_thread.start()
        self._hook_thread = threading.Thread(
            target=self._run_hook, daemon=True, name="sw-key-hook")
        self._hook_thread.start()
        if not self._ready.wait(timeout=2.0):
            self._log("键盘钩子安装超时", "error")
            self._running = False
            return False
        ok = self._hook is not None
        if ok:
            self._log("键盘钩子已安装（SolidWorks 按键直通启用）")
        return ok

    def stop(self):
        with self._lock:
            hook = self._hook
            hook_thread = self._hook_thread
            self._hook = None
            self._hook_thread = None
            self._running = False
            self._ready.clear()
            self._held.clear()
        try:
            if hook:
                user32.UnhookWindowsHookEx.argtypes = [wintypes.HHOOK]
                user32.UnhookWindowsHookEx(hook)
            if hook_thread and hook_thread.ident:
                user32.PostThreadMessageW.argtypes = [
                    wintypes.DWORD, wintypes.UINT, wintypes.WPARAM,
                    wintypes.LPARAM]
                user32.PostThreadMessageW(hook_thread.ident, 0x0012, 0, 0)
                hook_thread.join(timeout=2.0)
        except Exception as e:
            self._log("卸载键盘钩子失败: %s" % e, "error")
        try:
            self._queue.put_nowait(None)
        except queue.Full:
            pass
        self._log("键盘钩子已卸载（按键直通关闭）")

    def update(self, snap: Snap):
        """发布新快照（主线程调用）。"""
        self._snap = snap

    def snapshot(self) -> Snap:
        return self._snap

    # ---------- 钩子线程 ----------

    def _run_hook(self):
        user32.SetWindowsHookExW.restype = wintypes.HHOOK
        user32.SetWindowsHookExW.argtypes = [
            ctypes.c_int, HOOKPROC, wintypes.HINSTANCE, wintypes.DWORD]
        try:
            # THREAD_PRIORITY_ABOVE_NORMAL：减少与进程内其它线程争用
            ctypes.windll.kernel32.SetThreadPriority(
                ctypes.windll.kernel32.GetCurrentThread(), 1)
        except Exception:
            pass
        self._hook = user32.SetWindowsHookExW(
            WH_KEYBOARD_LL, self._callback, None, 0)
        if not self._hook:
            self._log("安装键盘钩子失败，错误码 %s" % ctypes.get_last_error(),
                      "error")
            self._ready.set()
            return
        self._ready.set()
        msg = wintypes.MSG()
        user32.GetMessageW.argtypes = [ctypes.POINTER(wintypes.MSG),
                                       wintypes.HWND, wintypes.UINT,
                                       wintypes.UINT]
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def _hook_proc(self, nCode, wParam, lParam):
        """钩子回调对外包装：任何异常都必须继续传递，否则整条键盘钩子链断裂。"""
        try:
            return self._hook_impl(nCode, wParam, lParam)
        except Exception:
            return _call_next(self._hook, nCode, wParam, lParam)

    def _hook_impl(self, nCode, wParam, lParam):
        if nCode != HC_ACTION:
            return _call_next(self._hook, nCode, wParam, lParam)
        msg = int(wParam)
        if msg in (WM_KEYDOWN, WM_SYSKEYDOWN):
            is_keyup = False
        elif msg in (WM_KEYUP, WM_SYSKEYUP):
            is_keyup = True
        else:
            return _call_next(self._hook, nCode, wParam, lParam)

        kbs = ctypes.cast(lParam, ctypes.POINTER(KBDLLHOOKSTRUCT)).contents
        vk = int(kbs.vkCode)
        injected = bool(kbs.flags & LLKHF_INJECTED)

        if is_keyup:
            # 我们吞过的按下，对应的抬起也要吞，避免目标收到不成对的 key-up
            if vk in self._held:
                self._held.discard(vk)
                return 1
            return _call_next(self._hook, nCode, wParam, lParam)

        snap = self._snap
        if not should_intercept(vk, False, snap, _foreground_hwnd(),
                                injected, _any_modifier_down()):
            self._maybe_log_unknown(vk, snap)
            return _call_next(self._hook, nCode, wParam, lParam)

        if vk in self._held:
            return 1  # 自动重复帧：吞掉但不重复投递（长按不该反复触发命令）
        if len(self._held) > 32:
            self._held.clear()
        self._held.add(vk)
        self.stats["swallowed"] += 1
        self._note_class_once(snap.focus_class)
        try:
            self._queue.put_nowait(vk)
        except queue.Full:
            pass
        return 1

    def _note_class_once(self, cls: str):
        """首次对某个焦点控件类生效时记一条日志。

        作用：一眼看出白名单有没有覆盖到绘图区（日志里出现"按键已直通 class=xxx"
        说明这类控件被认成绘图区了）；每个类只记一次，不刷屏。
        """
        key = cls or "(空)"
        if key in self._logged_classes:
            return
        self._logged_classes.add(key)
        self._log("按键已直通（class=%s）" % key)

    def _maybe_log_unknown(self, vk: int, snap: Snap):
        """认不出的焦点控件被放行时记一条（节流）——用于事后补白名单。"""
        if not snap.enabled or snap.focus_kind != "unknown":
            return
        if snap.sw_hwnd == 0 or vk not in snap.keyset:
            return
        cls = snap.focus_class or "(空)"
        now = time.monotonic()
        if now - self._unknown_logged.get(cls, 0.0) < _UNKNOWN_LOG_INTERVAL:
            return
        self._unknown_logged[cls] = now
        self.stats["unknown_focus"] += 1
        self._log("焦点控件未识别，已放行（class=%s）—— 若此处该走快捷键，"
                  "可在设置里把它加进额外类名" % cls)

    # ---------- 投递线程 ----------

    def _deliver_loop(self):
        while True:
            item = self._queue.get()
            if item is None:
                return
            if self._delivery_broken:
                continue
            snap = self._snap
            # PM 输入框 / IME 焦点：投给绘图区视口（SW 的命令循环在视口层处理）。
            # 不能投给框架窗口 —— SW 不处理框架的 PostMessage 键。
            if snap.ime_focus or snap.pm_edit:
                target = _find_viewport(snap.sw_hwnd) or snap.sw_hwnd
            else:
                target = snap.focus_hwnd or snap.sw_hwnd
            ok = post_key_pair(target, item)
            if not ok and target != snap.sw_hwnd:
                ok = post_key_pair(snap.sw_hwnd, item)
            if ok:
                self._fail_streak = 0
                self.stats["delivered"] += 1
                continue
            self._fail_streak += 1
            self.stats["failed"] += 1
            if self._fail_streak >= FAIL_LIMIT:
                # 投递不通（提权/UIPI/窗口句柄失效）→ 立即停用拦截，
                # 否则就变成"键被吞了但什么都没发生"，比不生效更糟。
                self._delivery_broken = True
                self._snap = self._snap._replace(delivery_broken=True,
                                                 enabled=False)
                self._log("按键直通连续投递失败 %d 次，已自动停用（恢复原始按键行为）"
                          % FAIL_LIMIT, "error")


_singleton_lock = threading.Lock()
_singleton = None


def get_interceptor(log=None) -> Interceptor:
    """进程内单例（避免重复装钩子）。"""
    global _singleton
    with _singleton_lock:
        if _singleton is None:
            _singleton = Interceptor(log=log)
        elif log is not None:
            _singleton._log_fn = log
        return _singleton


def stop_interceptor():
    global _singleton
    with _singleton_lock:
        inst = _singleton
    if inst is not None:
        inst.stop()
