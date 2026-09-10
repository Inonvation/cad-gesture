"""SolidWorks 中文输入法单键快捷键直通 — P0 真机探针

为什么必须先跑这个脚本（根因）：
    中文输入法在**消息队列层**（TSF/IMM）截获字母键用于开启拼音组合，键根本到不了
    SW 的窗口过程，所以 SW 侧怎么设置都没用；`SendInput` 的注入点在「布局映射之前」，
    同样绕不过输入法。剩下两条路：
      ① 把键盘消息**直接投给 SW 窗口**（PostMessage / SendMessage）——消息在队列层入队，
         不过「硬件输入 → IME 预处理」这条链路；
      ② 临时**解绑 IME 上下文**（ImmAssociateContext(hwnd, NULL)）后走真实按键，再还原。
    这两条路「SW 到底吃不吃」无法靠推理确定，只能在本机实测 —— 这就是本脚本的全部目的。

交互设计（第一版踩的坑，勿回退）：
    被测应用必须占有前台，而判定结果只有人能看出来 —— 若把「读提示 / 敲回车」放在命令行，
    就要求用户在 SW 和控制台之间反复手动切换，实际操作时根本读不到提示。
    因此本版把问答通道移出控制台：
      * 每步先打印说明，然后 5 秒倒计时（这 5 秒内切到 SW、聚焦图形区，只切这一次）；
      * 倒计时结束先校验前台是不是 SW，不是就记为「未判定」而不是产出垃圾数据；
      * 投递后等 2.5 秒，弹一个**置顶对话框**问结果，鼠标点一下即可（不用切窗口、
        不用键盘 —— 因为 Windows Terminal 下 GetConsoleWindow 拿到的是隐藏窗口，
        「抢回控制台」并不可靠）。
      * `--ask console` 可切回命令行问答（独立 cmd 窗口下也够用）。

用法：
    python scripts/sw_key_probe.py                # 依次跑 5 个核心步骤
    python scripts/sw_key_probe.py --extended     # 追加 2 个对照步骤
    python scripts/sw_key_probe.py --method post_focus   # 只跑一个方法
    python scripts/sw_key_probe.py --list         # 列出所有方法
    python scripts/sw_key_probe.py --diag         # 只读诊断，不投递
    python scripts/sw_key_probe.py --watch --seconds 60  # 焦点特征观察（免交互，写日志）

测试键默认 S（SW 快捷工具栏，视觉可判定且无副作用）；若 S 未绑定，先在
SW【工具 → 自定义 → 键盘】给某个可见命令绑一个单键，再用 --key 指定它。
"""

import argparse
import ctypes
import ctypes.wintypes as wt
import os
import sys
import tempfile
import time

user32 = ctypes.windll.user32
kernel32 = ctypes.windll.kernel32
imm32 = ctypes.windll.imm32

WM_KEYDOWN = 0x0100
WM_KEYUP = 0x0101
WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001
IME_CMODE_NATIVE = 0x0001
SMTO_BLOCK = 0x0001
SMTO_ABORTIFHUNG = 0x0002
MAPVK_VK_TO_VSC = 0

INPUT_KEYBOARD = 1
KEYEVENTF_KEYUP = 0x0002

TOKEN_QUERY = 0x0008
TokenElevation = 20
PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

SW_RESTORE = 9

MB_YESNOCANCEL = 0x00000003
MB_ICONQUESTION = 0x00000020
MB_TOPMOST = 0x00040000
MB_SETFOREGROUND = 0x00010000
MB_OK = 0x00000000
_IDYES, _IDNO, _IDCANCEL = 6, 7, 2

_ULONG_PTR = ctypes.c_ulonglong if ctypes.sizeof(ctypes.c_void_p) == 8 \
    else ctypes.c_ulong

# 目标应用：SW 的可执行文件名片段（小写匹配），与 src/sw_ime_assist.py 保持一致
TARGET_EXE_HINT = "sldworks"


# ========== Win32 结构体 ==========

class MOUSEINPUT(ctypes.Structure):
    _fields_ = [("dx", wt.LONG), ("dy", wt.LONG), ("mouseData", wt.DWORD),
                ("dwFlags", wt.DWORD), ("time", wt.DWORD),
                ("dwExtraInfo", _ULONG_PTR)]


class KEYBDINPUT(ctypes.Structure):
    _fields_ = [("wVk", wt.WORD), ("wScan", wt.WORD), ("dwFlags", wt.DWORD),
                ("time", wt.DWORD), ("dwExtraInfo", _ULONG_PTR)]


class HARDWAREINPUT(ctypes.Structure):
    _fields_ = [("uMsg", wt.DWORD), ("wParamL", wt.WORD),
                ("wParamH", wt.WORD)]


class _INPUTUNION(ctypes.Union):
    _fields_ = [("mi", MOUSEINPUT), ("ki", KEYBDINPUT), ("hi", HARDWAREINPUT)]


class INPUT(ctypes.Structure):
    _fields_ = [("type", wt.DWORD), ("u", _INPUTUNION)]


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [("cbSize", wt.DWORD), ("flags", wt.DWORD),
                ("hwndActive", wt.HWND), ("hwndFocus", wt.HWND),
                ("hwndCapture", wt.HWND), ("hwndMenuOwner", wt.HWND),
                ("hwndMoveSize", wt.HWND), ("hwndCaret", wt.HWND),
                ("rcCaret", wt.RECT)]


# ========== 基础查询 ==========

def get_foreground_hwnd() -> int:
    user32.GetForegroundWindow.restype = wt.HWND
    h = user32.GetForegroundWindow()
    return int(h) if h else 0


def window_pid(hwnd: int) -> int:
    user32.GetWindowThreadProcessId.argtypes = [
        wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    pid = wt.DWORD()
    user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return int(pid.value)


def window_tid(hwnd: int) -> int:
    user32.GetWindowThreadProcessId.argtypes = [
        wt.HWND, ctypes.POINTER(wt.DWORD)]
    user32.GetWindowThreadProcessId.restype = wt.DWORD
    pid = wt.DWORD()
    return int(user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))) or 0


def exe_of_pid(pid: int) -> str:
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wt.DWORD(1024)
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wt.HANDLE, wt.DWORD, wt.LPWSTR, ctypes.POINTER(wt.DWORD)]
        kernel32.QueryFullProcessImageNameW.restype = wt.BOOL
        if kernel32.QueryFullProcessImageNameW(h, 0, buf,
                                               ctypes.byref(size)):
            return buf.value or ""
        return ""
    finally:
        kernel32.CloseHandle.argtypes = [wt.HANDLE]
        kernel32.CloseHandle(h)


def is_elevated(pid: int) -> bool:
    """进程是否以提升（管理员）权限运行；查询失败返回 False"""
    advapi32 = ctypes.windll.advapi32
    kernel32.OpenProcess.restype = wt.HANDLE
    kernel32.OpenProcess.argtypes = [wt.DWORD, wt.BOOL, wt.DWORD]
    proc = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not proc:
        return False
    try:
        advapi32.OpenProcessToken.argtypes = [
            wt.HANDLE, wt.DWORD, ctypes.POINTER(wt.HANDLE)]
        advapi32.OpenProcessToken.restype = wt.BOOL
        token = wt.HANDLE()
        if not advapi32.OpenProcessToken(proc, TOKEN_QUERY,
                                         ctypes.byref(token)):
            return False
        try:
            advapi32.GetTokenInformation.argtypes = [
                wt.HANDLE, ctypes.c_int, ctypes.c_void_p, wt.DWORD,
                ctypes.POINTER(wt.DWORD)]
            advapi32.GetTokenInformation.restype = wt.BOOL
            info = wt.DWORD(0)
            ret = wt.DWORD(0)
            if not advapi32.GetTokenInformation(
                    token, TokenElevation, ctypes.byref(info),
                    ctypes.sizeof(info), ctypes.byref(ret)):
                return False
            return bool(info.value)
        finally:
            kernel32.CloseHandle(token)
    finally:
        kernel32.CloseHandle(proc)


def class_name(hwnd: int) -> str:
    if not hwnd:
        return ""
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW.argtypes = [wt.HWND, wt.LPWSTR, ctypes.c_int]
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def gui_thread_info(tid: int) -> GUITHREADINFO:
    gui = GUITHREADINFO()
    gui.cbSize = ctypes.sizeof(GUITHREADINFO)
    user32.GetGUIThreadInfo.argtypes = [wt.DWORD, ctypes.POINTER(GUITHREADINFO)]
    user32.GetGUIThreadInfo.restype = wt.BOOL
    user32.GetGUIThreadInfo(tid, ctypes.byref(gui))
    return gui


def thread_layout_low(hwnd: int) -> int:
    tid = window_tid(hwnd)
    if not tid:
        return 0
    user32.GetKeyboardLayout.restype = ctypes.c_ulonglong
    user32.GetKeyboardLayout.argtypes = [wt.DWORD]
    hkl = user32.GetKeyboardLayout(tid)
    return int(hkl) & 0xFFFF if hkl else 0


def ime_conversion_mode(hwnd: int):
    """IMM 兼容层的转换模式；None 表示读不到（TSF 输入法常读不到，属预期）"""
    imm32.ImmGetDefaultIMEWnd.restype = wt.HWND
    imm32.ImmGetDefaultIMEWnd.argtypes = [wt.HWND]
    ime_wnd = imm32.ImmGetDefaultIMEWnd(hwnd)
    if not ime_wnd:
        return None
    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    user32.SendMessageTimeoutW.argtypes = [
        wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
        ctypes.POINTER(ctypes.c_size_t)]
    out = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(
        ime_wnd, WM_IME_CONTROL, IMC_GETCONVERSIONMODE, 0,
        SMTO_BLOCK | SMTO_ABORTIFHUNG, 500, ctypes.byref(out))
    if not ok:
        return None
    return int(out.value)


def ime_state(hwnd: int, attach: bool = False):
    """(是否取到上下文, 是否打开, 组合串长度) —— 组合串非空即"正在打拼音"

    attach=True 时先 AttachThreadInput 借用目标线程输入队列再取上下文。
    ImmGetContext 本质按「当前线程的 IME 状态」工作，跨进程调用通常返回 0
    （本机实测：裸调用与 attach 后都取不到）。这是实现期"组合态守卫"能否成立的
    前提，所以要量出来 —— 已知结论是不可依赖，见 README 式注释与方案文档第五节。
    """
    tid = window_tid(hwnd) if attach else 0
    self_tid = int(kernel32.GetCurrentThreadId())
    attached = False
    if tid:
        user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
        user32.AttachThreadInput.restype = wt.BOOL
        attached = bool(user32.AttachThreadInput(self_tid, tid, True))
    try:
        return _ime_state_inner(hwnd)
    finally:
        if attached:
            user32.AttachThreadInput(self_tid, tid, False)


def _ime_state_inner(hwnd: int):
    imm32.ImmGetContext.restype = wt.HANDLE
    imm32.ImmGetContext.argtypes = [wt.HWND]
    hc = imm32.ImmGetContext(hwnd)
    if not hc:
        return (False, False, 0)
    try:
        imm32.ImmGetOpenStatus.argtypes = [wt.HANDLE]
        imm32.ImmGetOpenStatus.restype = wt.BOOL
        opened = bool(imm32.ImmGetOpenStatus(hc))
        imm32.ImmGetCompositionStringW.restype = ctypes.c_long
        imm32.ImmGetCompositionStringW.argtypes = [
            wt.HANDLE, wt.DWORD, ctypes.c_void_p, wt.DWORD]
        n = int(imm32.ImmGetCompositionStringW(hc, 0x0008, None, 0))
        return (True, opened, max(0, n) // 2)
    finally:
        imm32.ImmReleaseContext.argtypes = [wt.HWND, wt.HANDLE]
        imm32.ImmReleaseContext(hwnd, hc)


def diagnose(light: bool = False) -> dict:
    fg = get_foreground_hwnd()
    pid = window_pid(fg)
    exe = exe_of_pid(pid)
    tid = window_tid(fg)
    gui = gui_thread_info(tid) if tid else GUITHREADINFO()
    focus = int(gui.hwndFocus) if gui.hwndFocus else 0
    got, opened, clen = ime_state(fg)
    got_att = None
    if not light and not got and fg:
        got_att = ime_state(fg, attach=True)
    return {
        "fg_hwnd": fg,
        "fg_pid": pid,
        "fg_exe": os.path.basename(exe),
        "is_target": TARGET_EXE_HINT in exe.lower(),
        "fg_elevated": (not light) and is_elevated(pid) if pid else False,
        "self_elevated": (not light) and is_elevated(os.getpid()),
        "tid": tid,
        "layout_low": thread_layout_low(fg),
        "focus_hwnd": focus,
        "focus_class": class_name(focus),
        "caret_hwnd": int(gui.hwndCaret) if gui.hwndCaret else 0,
        "ime_ctx": got,
        "ime_open": opened,
        "composing_len": clen,
        "ime_ctx_attached": got_att,
        "conv_mode": ime_conversion_mode(fg) if (fg and not light) else None,
    }


def print_diag(d: dict):
    conv = d["conv_mode"]
    if conv is None:
        conv_txt = "读不到（TSF 输入法常见，属预期）"
    else:
        conv_txt = "0x%04X（中文态=%s）" % (
            conv, "是" if conv & IME_CMODE_NATIVE else "否")
    print("  ------------------------------------------------")
    print("  前台窗口      : hwnd=0x%X pid=%s exe=%s"
          % (d["fg_hwnd"], d["fg_pid"], d["fg_exe"] or "?"))
    print("  是否目标应用  : %s" % ("是" if d["is_target"] else "否（SW 不在前台）"))
    print("  焦点控件      : hwnd=0x%X class=%s"
          % (d["focus_hwnd"], d["focus_class"] or "?"))
    print("  插入符(caret) : %s"
          % ("有（像文本框）" if d["caret_hwnd"] else "无（像绘图区）"))
    print("  线程布局 HKL  : %s" % ("0x%04X" % d["layout_low"]
                                    if d["layout_low"] else "读不到"))
    line = "  IME 上下文    : %s，打开=%s，组合中长度=%d" % (
        "取到" if d["ime_ctx"] else "取不到（裸调用）", d["ime_open"],
        d["composing_len"])
    att = d.get("ime_ctx_attached")
    if att is not None:
        line += " ｜ AttachThreadInput 后=%s" % ("取到" if att[0] else "仍取不到")
    print(line)
    print("  IME 转换模式  : %s" % conv_txt)
    print("  提权对比      : SW=%s / 本脚本=%s%s"
          % ("管理员" if d["fg_elevated"] else "普通",
             "管理员" if d["self_elevated"] else "普通",
             "（SW 更高 → 投递会被 UIPI 拦，属预期失效）"
             if d["fg_elevated"] and not d["self_elevated"] else ""))
    print("  ------------------------------------------------")


# ========== 控制台交互：倒计时 + 自动抢回前台 ==========

def console_hwnd() -> int:
    kernel32.GetConsoleWindow.restype = wt.HWND
    return int(kernel32.GetConsoleWindow() or 0)


def bring_console_front():
    """把本脚本的控制台窗口拉回前台。

    为什么要 AttachThreadInput：SetForegroundWindow 对「不是当前前台、也刚没收到
    输入」的进程只会闪烁任务栏。借前台线程的输入队列（attach→设置→detach）是
    Win32 下公认的可行做法，让用户不必手动 Alt+Tab。
    """
    hwnd = console_hwnd()
    if not hwnd:
        return False
    fg = get_foreground_hwnd()
    fg_tid = window_tid(fg) if fg else 0
    self_tid = int(kernel32.GetCurrentThreadId())
    attached = False
    if fg_tid and fg_tid != self_tid:
        user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
        user32.AttachThreadInput.restype = wt.BOOL
        attached = bool(user32.AttachThreadInput(self_tid, fg_tid, True))
    try:
        user32.ShowWindow.argtypes = [wt.HWND, ctypes.c_int]
        user32.ShowWindow(hwnd, SW_RESTORE)
        user32.SetForegroundWindow.argtypes = [wt.HWND]
        user32.SetForegroundWindow.restype = wt.BOOL
        ok = bool(user32.SetForegroundWindow(hwnd))
        user32.BringWindowToTop.argtypes = [wt.HWND]
        user32.BringWindowToTop(hwnd)
        return ok
    finally:
        if attached:
            user32.AttachThreadInput(self_tid, fg_tid, False)


def countdown(seconds: int, hint: str):
    print(hint)
    for i in range(seconds, 0, -1):
        sys.stdout.write("\r    还有 %d 秒…  " % i)
        sys.stdout.flush()
        time.sleep(1)
    sys.stdout.write("\r" + " " * 24 + "\r")
    sys.stdout.flush()


def _msgbox(text: str, title: str, flags: int) -> int:
    user32.MessageBoxW.restype = ctypes.c_int
    user32.MessageBoxW.argtypes = [wt.HWND, wt.LPCWSTR, wt.LPCWSTR, wt.UINT]
    return int(user32.MessageBoxW(None, text, title, flags))


def ask_dialog(question: str) -> str:
    """置顶对话框问答：鼠标点一下即可，不要求用户切回控制台。

    用对话框而不是命令行，是因为 Windows Terminal 下 GetConsoleWindow() 返回的是
    隐藏的 pseudoconsole 窗口，「把控制台抢回前台」并不可靠；而置顶对话框天然可见、
    可点，且点击即获得焦点。
    """
    flags = MB_YESNOCANCEL | MB_ICONQUESTION | MB_TOPMOST | MB_SETFOREGROUND
    r = _msgbox("%s\n\n是 = 有响应    否 = 没响应    取消 = 跳过/未判定"
                % question, "SW 探针 — 请判定", flags)
    return {_IDYES: "y", _IDNO: "n", _IDCANCEL: "s"}.get(r, "s")


def info_dialog(text: str, title: str = "SW 探针"):
    _msgbox(text, title, MB_OK | MB_TOPMOST | MB_SETFOREGROUND | MB_ICONQUESTION)


# ========== 投递方式 ==========

def build_lparam(vk: int, keyup: bool, use_scan: bool = True) -> int:
    """拼 WM_KEYDOWN/WM_KEYUP 的 lParam。

    位域：0-15 重复次数(1)、16-23 扫描码、24 扩展键、29 上下文、
    30 前一次按键状态、31 过渡位（按下 0 / 抬起 1）。
    扫描码必须来自 MapVirtualKey，裸填 1 是"发一次收两次 / F1 变 t"这类经典坑。
    """
    sc = (user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFF) if use_scan else 0
    lp = 1 | (sc << 16)
    if keyup:
        lp |= (1 << 30) | (1 << 31)
    return lp


def _post(hwnd: int, msg: int, vk: int, lp: int) -> bool:
    user32.PostMessageW.restype = wt.BOOL
    user32.PostMessageW.argtypes = [wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM]
    return bool(user32.PostMessageW(hwnd, msg, vk, lp))


def post_key(hwnd: int, vk: int, use_scan: bool = True) -> tuple:
    """PostMessage 投递按下+抬起；返回 (按下是否入队, 抬起是否入队)"""
    d = _post(hwnd, WM_KEYDOWN, vk, build_lparam(vk, False, use_scan))
    u = _post(hwnd, WM_KEYUP, vk, build_lparam(vk, True, use_scan))
    return (d, u)


def sendmsg_key(hwnd: int, vk: int, timeout_ms: int = 500) -> bool:
    """SendMessageTimeout 投递（同步但不阻塞过久）"""
    user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
    user32.SendMessageTimeoutW.argtypes = [
        wt.HWND, wt.UINT, wt.WPARAM, wt.LPARAM, wt.UINT, wt.UINT,
        ctypes.POINTER(ctypes.c_size_t)]
    out = ctypes.c_size_t()
    ok = user32.SendMessageTimeoutW(
        hwnd, WM_KEYDOWN, vk, build_lparam(vk, False),
        SMTO_BLOCK | SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(out))
    user32.SendMessageTimeoutW(
        hwnd, WM_KEYUP, vk, build_lparam(vk, True),
        SMTO_BLOCK | SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(out))
    return bool(ok)


def send_input_key(vk: int) -> bool:
    """SendInput 注入真实按键（预期：中文态下会被输入法吞掉）"""
    user32.SendInput.restype = wt.UINT
    user32.SendInput.argtypes = [wt.UINT, ctypes.POINTER(INPUT), ctypes.c_int]
    arr = (INPUT * 2)()
    for i, up in enumerate((False, True)):
        arr[i].type = INPUT_KEYBOARD
        arr[i].u.ki.wVk = vk
        arr[i].u.ki.wScan = user32.MapVirtualKeyW(vk, MAPVK_VK_TO_VSC) & 0xFF
        arr[i].u.ki.dwFlags = KEYEVENTF_KEYUP if up else 0
        arr[i].u.ki.dwExtraInfo = 0
    return int(user32.SendInput(2, arr, ctypes.sizeof(INPUT))) == 2


def detach_ime_and_send(hwnd: int, focus_hwnd: int, vk: int) -> dict:
    """M2：临时解绑 IME 上下文 → SendInput → 还原。

    跨线程操作 IME 需要先 AttachThreadInput 借用目标线程的输入队列；本函数把每步
    返回值都记下来，便于判断是哪一环无效（尤其 ImmGetContext 跨进程拿不到上下文时）。
    """
    result = {"attach": False, "get_ctx": False, "assoc_null": False,
              "sendinput": False, "restore": False}
    target_tid = window_tid(hwnd)
    self_tid = int(kernel32.GetCurrentThreadId())
    if not target_tid:
        return result
    user32.AttachThreadInput.argtypes = [wt.DWORD, wt.DWORD, wt.BOOL]
    user32.AttachThreadInput.restype = wt.BOOL
    result["attach"] = bool(user32.AttachThreadInput(self_tid, target_tid,
                                                     True))
    win = focus_hwnd or hwnd
    try:
        imm32.ImmGetContext.restype = wt.HANDLE
        imm32.ImmGetContext.argtypes = [wt.HWND]
        prev = imm32.ImmGetContext(win)
        result["get_ctx"] = bool(prev)
        imm32.ImmAssociateContext.restype = wt.HANDLE
        imm32.ImmAssociateContext.argtypes = [wt.HWND, wt.HANDLE]
        old = imm32.ImmAssociateContext(win, None)
        result["assoc_null"] = True
        result["prev_ctx"] = int(old or 0)
        time.sleep(0.05)
        result["sendinput"] = send_input_key(vk)
        time.sleep(0.05)
        imm32.ImmAssociateContext(win, old or prev)
        result["restore"] = True
    finally:
        user32.AttachThreadInput(self_tid, target_tid, False)
    return result


# ========== 方法表 ==========

CORE_METHODS = [
    {"id": "manual", "kind": "manual",
     "title": "基线：你手动按一次测试键",
     "criterion": "确认这个键在 SW 里**确实绑定了命令**（基线不生效的话，"
                  "后面所有「没响应」都是假阴性，先换一个绑定可见命令的键再测）"},
    {"id": "post_focus", "kind": "inject",
     "title": "M1a PostMessage → 焦点窗口",
     "criterion": "SW 是否执行了该命令"},
    {"id": "post_frame", "kind": "inject",
     "title": "M1b PostMessage → 前台顶层窗口",
     "criterion": "SW 是否执行了该命令"},
    {"id": "sendmsg", "kind": "inject",
     "title": "M1d SendMessageTimeout → 焦点窗口",
     "criterion": "SW 是否执行了该命令"},
    {"id": "detach", "kind": "inject",
     "title": "M2 解绑 IME 上下文 + SendInput",
     "criterion": "SW 是否执行了该命令"},
]

EXTENDED_METHODS = [
    {"id": "sendinput", "kind": "inject",
     "title": "对照组 SendInput（不解绑 IME）",
     "criterion": "预期【没响应】—— 这一条用来证明输入法确实在吞键"},
    {"id": "post_noscan", "kind": "inject",
     "title": "对照组 PostMessage + lParam 无扫描码",
     "criterion": "用于对照扫描码位域是否正确（发一次却响应两次，就是这里错了）"},
]

ALL_METHODS = CORE_METHODS + EXTENDED_METHODS


# ========== 主流程 ==========

class Probe:
    def __init__(self, vk: int, key_name: str, log_path: str,
                 ask_channel: str = "dialog"):
        self.vk = vk
        self.key_name = key_name
        self.log_path = log_path
        self.ask_channel = ask_channel
        self.records = []

    def log(self, text: str):
        print(text)
        try:
            with open(self.log_path, "a", encoding="utf-8") as f:
                f.write(text + "\n")
        except Exception:
            pass

    def countdown_and_inject(self, step: dict, idx: int, total: int) -> dict:
        """倒计时 → 校验前台 → 投递 → 抢回控制台。返回本步诊断与投递说明。"""
        print()
        print("=" * 66)
        print("步骤 %d/%d：%s" % (idx, total, step["title"]))
        print("=" * 66)
        print("判定标准：%s" % step["criterion"])
        print()
        countdown(5, "→ 请在这 5 秒内把 SolidWorks 切到前台，点一下【图形区】"
                     "获得焦点，输入法保持【中文】；这 5 秒过后自动投递。")

        pre = diagnose()
        extra = ""
        if step["kind"] == "manual":
            print("现在请**手动**按一次 [%s]（这里不用按键，直接观察 SW）。"
                  % self.key_name)
        elif not pre["is_target"]:
            # 关键护栏：前台不是 SW 时投递毫无意义，记「未判定」而不是产出垃圾结论
            extra = "未投递：投递前前台是 %s，不是 SolidWorks" % (
                pre["fg_exe"] or "?")
            print("!! " + extra)
        else:
            time.sleep(0.3)
            extra = self._fire(step["id"], pre)
            print("   " + extra)
            self.log("    [投递] %s" % extra)

        time.sleep(2.5)
        title = step["title"]
        question = "【第 %d/%d 步】%s\n已投递测试键 [%s]。" % (
            idx, total, title, self.key_name)
        if step["kind"] == "manual":
            question = "【第 %d/%d 步】%s\n你手动按的 [%s] 生效了吗？" % (
                idx, total, title, self.key_name)
        if extra.startswith("未投递"):
            question += "\n（本次未真正投递：%s）" % extra
        question += "\nSolidWorks 有响应吗？"
        ans = self._ask(question)
        self.records.append({"step": step, "ans": ans, "extra": extra,
                             "pre": pre, "post": diagnose()})
        self.log("    [记录] %s -> %s %s" % (step["id"], ans, extra))
        return pre

    def _fire(self, method: str, pre: dict) -> str:
        vk = self.vk
        focus = pre["focus_hwnd"] or pre["fg_hwnd"]
        frame = pre["fg_hwnd"]
        if method == "post_focus":
            down, up = post_key(focus, vk)
            return "投递 hwnd=0x%X class=%s 返回(%s,%s)" % (
                focus, class_name(focus) or "?", down, up)
        if method == "post_frame":
            down, up = post_key(frame, vk)
            return "投递顶层 hwnd=0x%X class=%s 返回(%s,%s)" % (
                frame, class_name(frame) or "?", down, up)
        if method == "sendmsg":
            ok = sendmsg_key(focus, vk)
            return "SendMessageTimeout hwnd=0x%X 返回=%s" % (focus, ok)
        if method == "sendinput":
            return "SendInput(不解绑 IME) 返回=%s" % send_input_key(vk)
        if method == "post_noscan":
            d1 = _post(focus, WM_KEYDOWN, vk, build_lparam(vk, False, False))
            d2 = _post(focus, WM_KEYUP, vk, build_lparam(vk, True, False))
            return "lParam 无扫描码 返回(%s,%s)" % (d1, d2)
        if method == "detach":
            r = detach_ime_and_send(frame, pre["focus_hwnd"], vk)
            return ("attach=%s 取上下文=%s 解绑=%s 注入=%s 还原=%s"
                    % (r["attach"], r["get_ctx"], r["assoc_null"],
                       r["sendinput"], r["restore"]))
        return "未知方法"

    def _ask(self, question: str) -> str:
        if self.ask_channel == "console":
            bring_console_front()
            time.sleep(0.15)
            print()
            print(">>> %s" % question.replace("\n", "\n    "))
            while True:
                ans = input("    y=有响应 / n=没响应 / s=跳过 : ").strip().lower()
                if ans in ("y", "n", "s"):
                    return ans
                if not ans:
                    return "s"
                print("    请输入 y / n / s")
        return ask_dialog(question)

    def summary(self):
        print()
        self.log("")
        self.log("=== 结果汇总（测试键=%s）===" % self.key_name)
        worked = []
        for rec in self.records:
            step = rec["step"]
            mark = {"y": "生效", "n": "无响应", "s": "跳过/未判定"}[rec["ans"]]
            self.log("  %-40s %s" % (step["title"], mark))
            if rec["extra"].startswith("未投递"):
                self.log("      ↳ %s" % rec["extra"])
            if rec["ans"] == "y" and "对照" not in step["title"] \
                    and step["kind"] != "manual":
                worked.append(step["title"])
        self.log("")
        if worked:
            self.log("结论：可用投递方式 → %s" % "；".join(worked))
            self.log("下一步：按排在最前的可用方式落地 src/sw_key_assist.py。")
        else:
            base = [r for r in self.records if r["step"]["kind"] == "manual"]
            self.log("结论：没有投递方式生效。按顺序排查：")
            if base and base[0]["ans"] != "y":
                self.log("  1) 基线就没响应 → 测试键 [%s] 在 SW 里没绑定，"
                         "换一个绑定到可见命令的键重测。" % self.key_name)
            else:
                self.log("  1) 基线正常但没有方式生效 → 看汇总里每条投递的返回值，"
                         "全为 False 说明被拦截（提权/UIPI）。")
            self.log("  2) SW 是否以管理员运行 → 是则改用管理员身份重跑本脚本。")
            self.log("  3) 焦点是否真在图形区 → 用 --watch 量一下特征。")
        self.log("")
        self.log("日志文件：%s" % self.log_path)
        print()
        print("把上面的汇总（或日志文件）发回给我即可，不必截图。")
        info_dialog("测试结束，共 %d 步。\n\n结论已打印在控制台，"
                    "日志文件：\n%s" % (len(self.records), self.log_path))


def watch(seconds: int, log_path: str, key_name: str):
    """焦点特征观察（免交互）：在 SW 里依次点各处，脚本把特征变化写进日志。

    为什么需要它：A2（中文输入不掉字）的地基是「能否认出焦点是文本控件」，
    而跨进程的输入法组合态读不到，只能靠「控件类名 + 是否有插入符(caret)」这类
    跨进程可观测特征。本模式把 SW 内部各处的特征差异量出来，实现期照此写守卫。
    """
    lines = []
    print("观察模式（%d 秒，无需任何按键）：请在 SolidWorks 里依次点击——" % seconds)
    print("  1) 图形区空白处          期望：class 为视口类，caret=无")
    print("  2) 双击尺寸进数值输入框  期望：出现 caret / class 变化")
    print("  3) 新建注释并进入文字编辑 期望：出现 caret")
    print("  4) 左侧特征树里重命名特征 期望：出现 caret")
    print("结束时把日志文件发回给我即可：%s" % log_path)
    end = time.monotonic() + seconds
    last = None
    while time.monotonic() < end:
        d = diagnose(light=True)
        sig = (d["fg_exe"], d["focus_hwnd"], d["focus_class"], d["caret_hwnd"])
        if sig != last:
            line = "[%s] %-16s focus=0x%-8X class=%-22s caret=%s" % (
                time.strftime("%H:%M:%S"), d["fg_exe"] or "?",
                d["focus_hwnd"], d["focus_class"] or "?",
                "有" if d["caret_hwnd"] else "无")
            print(line)
            lines.append(line)
            last = sig
        time.sleep(0.3)
    try:
        with open(log_path, "a", encoding="utf-8") as f:
            f.write("=== 焦点特征观察 %s ===\n" % time.strftime("%Y-%m-%d %H:%M"))
            f.write("\n".join(lines) + "\n")
    except Exception as e:
        print("写日志失败：%s" % e)
    print("观察结束，共记录 %d 条特征行。" % len(lines))


def self_test() -> int:
    """自检交互链路：倒计时 + 置顶问答弹窗（不投递任何按键）。

    这一层正是第一版翻车的地方（问答通道放在命令行 → 用户看不见），所以单独留一个
    可随时重跑的自检，确认弹窗能在 SW 前台时正常出现、按钮映射正确。
    """
    print("自检：验证「倒计时 + 置顶问答弹窗」这条交互链路（不投递按键）。")
    countdown(3, "→ 现在可以故意切到别的窗口，3 秒后应弹出置顶对话框。")
    ans = ask_dialog("这是自检对话框。\n点任意按钮，脚本会打印它对应的含义。")
    print("你点了：%s（%s）" % (ans, {"y": "有响应", "n": "没响应",
                                     "s": "跳过/未判定"}[ans]))
    info_dialog("自检完成：弹窗可见、映射正确。\n接下来直接运行不带参数的本脚本做正式测试。")
    return 0


def main():
    ap = argparse.ArgumentParser(description="SW 中文输入法快捷键投递探针")
    ap.add_argument("--key", default="S", help="测试键（单个字母/数字），默认 S")
    ap.add_argument("--diag", action="store_true", help="只打印现场诊断，不投递")
    ap.add_argument("--watch", action="store_true",
                    help="焦点观察（免交互，写日志）")
    ap.add_argument("--seconds", type=int, default=60,
                    help="观察模式时长，默认 60 秒")
    ap.add_argument("--extended", action="store_true", help="追加两个对照步骤")
    ap.add_argument("--method", default="", help="只跑指定方法（见 --list）")
    ap.add_argument("--list", action="store_true", help="列出所有方法后退出")
    ap.add_argument("--self-test", action="store_true",
                    help="自检交互链路（倒计时 + 置顶弹窗），不投递按键")
    ap.add_argument("--ask", default="dialog", choices=["dialog", "console"],
                    help="判定问答通道：dialog=置顶弹窗（默认，不用切窗口）/"
                         "console=命令行")
    ap.add_argument("--log", default=os.path.join(tempfile.gettempdir(),
                                                 "cad-gesture-probe.log"),
                    help="日志路径")
    args = ap.parse_args()

    key = (args.key or "S").strip().upper()[:1] or "S"
    vk = ord(key)

    if args.list:
        for m in ALL_METHODS:
            print("%-14s %s" % (m["id"], m["title"]))
        return 0

    if args.diag:
        print("现场诊断（不投递任何按键）：")
        print_diag(diagnose())
        return 0

    if args.watch:
        watch(args.seconds, args.log, key)
        return 0

    if args.self_test:
        return self_test()

    if args.method:
        picked = [m for m in ALL_METHODS if m["id"] == args.method]
        if not picked:
            print("未知方法 %s，用 --list 查看可用方法。" % args.method)
            return 2
        methods = picked
    else:
        methods = CORE_METHODS + (EXTENDED_METHODS if args.extended else [])

    print("=" * 66)
    print("SolidWorks 中文输入法单键快捷键直通 — P0 真机探针")
    print("=" * 66)
    print("测试键：%s    共 %d 步    日志：%s" % (key, len(methods), args.log))
    print("每步流程：打印说明 → 5 秒倒计时（切到 SW、点图形区）→ 自动投递 →")
    print("          弹出置顶对话框，鼠标点「是/否/取消」即可（无需切回本窗口）")
    print("本脚本不装钩子、不吞键、不改配置。SW 若以管理员运行，请用管理员重跑。")
    input("准备好后按回车开始… ")

    probe = Probe(vk, key, args.log, ask_channel=args.ask)
    for i, step in enumerate(methods, 1):
        probe.countdown_and_inject(step, i, len(methods))
    probe.summary()
    return 0


if __name__ == "__main__":
    try:
        sys.exit(main())
    except KeyboardInterrupt:
        print("\n已中断。")
        sys.exit(130)
