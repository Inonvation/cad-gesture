# -*- coding: utf-8 -*-
"""诊断 SolidWorks 焦点控件结构。

用法：先在 SW 里点选一个图形（让 PropertyManager 打开并聚焦输入框），
然后运行本脚本。输出焦点窗口的类名、层次路径、位置等信息。
不要求 SW 在前台——按进程名找窗口。
"""
import ctypes
import ctypes.wintypes as wintypes
import sys
import time

user32 = ctypes.windll.user32


class GUITHREADINFO(ctypes.Structure):
    _fields_ = [
        ("cbSize", wintypes.DWORD), ("flags", wintypes.DWORD),
        ("hwndActive", wintypes.HWND), ("hwndFocus", wintypes.HWND),
        ("hwndCapture", wintypes.HWND), ("hwndMenuOwner", wintypes.HWND),
        ("hwndMoveSize", wintypes.HWND), ("hwndCaret", wintypes.HWND),
        ("rcCaret", wintypes.RECT),
    ]


def class_name(hwnd):
    buf = ctypes.create_unicode_buffer(256)
    user32.GetClassNameW(hwnd, buf, 256)
    return buf.value


def window_text(hwnd):
    buf = ctypes.create_unicode_buffer(512)
    user32.GetWindowTextW(hwnd, buf, 512)
    return buf.value


def window_rect(hwnd):
    r = wintypes.RECT()
    user32.GetWindowRect(hwnd, ctypes.byref(r))
    return (r.left, r.top, r.right, r.bottom)


def pid_of(hwnd):
    pid = wintypes.DWORD()
    tid = user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return tid, pid.value


def exe_path(pid):
    k32 = ctypes.windll.kernel32
    h = k32.OpenProcess(0x1000, False, pid)
    if not h:
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        ctypes.windll.kernel32.QueryFullProcessImageNameW(
            h, 0, buf, ctypes.byref(size))
        return buf.value
    finally:
        k32.CloseHandle(h)


def find_sldworks_window():
    """按进程名找 SLDWORKS 顶层窗口。"""
    result = []

    def cb(hwnd, _):
        if not user32.IsWindowVisible(hwnd):
            return True
        _, pid = pid_of(hwnd)
        exe = exe_path(pid).lower()
        if "sldworks" in exe and not user32.GetParent(hwnd):
            result.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result[0] if result else 0


def main():
    print("=" * 60)
    print("SW 焦点诊断")
    print("=" * 60)

    fg = user32.GetForegroundWindow()
    if fg:
        _, pid = pid_of(fg)
        print(f"当前前台: 0x{fg:X} exe={exe_path(pid)}")
    print()

    sw = find_sldworks_window()
    if not sw:
        print("未找到 SLDWORKS 窗口！请先打开 SolidWorks。")
        return
    tid, pid = pid_of(sw)
    print(f"SW 窗口: hwnd=0x{sw:X}")
    print(f"进程: pid={pid} exe={exe_path(pid)}")
    print(f"类名: {class_name(sw)}")
    print(f"标题: {window_text(sw)}")
    print(f"是否前台: {sw == fg}")
    print()

    # 用 SW 的线程 ID 查 GUIThreadInfo
    gui = GUITHREADINFO()
    gui.cbSize = ctypes.sizeof(GUITHREADINFO)
    ok = user32.GetGUIThreadInfo(tid, ctypes.byref(gui))
    if not ok:
        print("GetGUIThreadInfo 失败")
        return
    focus = int(gui.hwndFocus) if gui.hwndFocus else 0
    caret = int(gui.hwndCaret) if gui.hwndCaret else 0
    active = int(gui.hwndActive) if gui.hwndActive else 0

    print(f"active 窗口: 0x{active:X} class='{class_name(active)}'")
    print(f"焦点控件: hwnd=0x{focus:X}" if focus else "焦点控件: 无")
    if focus:
        fcls = class_name(focus)
        ftxt = window_text(focus)
        fr = window_rect(focus)
        print(f"  类名: '{fcls}'")
        print(f"  标题: '{ftxt}'")
        print(f"  位置: {fr}")
        print(f"  是否框架本身: {focus == sw}")

        print("  父窗口链:")
        p = user32.GetParent(focus)
        while p:
            pcls = class_name(p)
            ptxt = window_text(p)[:60]
            print(f"    parent=0x{p:X} class='{pcls}' text='{ptxt}' "
                  f"visible={bool(user32.IsWindowVisible(p))}")
            p = user32.GetParent(p)

    print(f"caret 窗口: 0x{caret:X}" if caret else "caret 窗口: 无")
    if caret:
        print(f"  类名: '{class_name(caret)}'")
    print()

    if focus:
        r1, r2 = wintypes.RECT(), wintypes.RECT()
        user32.GetClientRect(focus, ctypes.byref(r1))
        user32.GetClientRect(sw, ctypes.byref(r2))
        a1 = max(0, r1.right - r1.left) * max(0, r1.bottom - r1.top)
        a2 = max(0, r2.right - r2.left) * max(0, r2.bottom - r2.top)
        cov = (a1 / a2) if a2 else 0
        print(f"焦点控件覆盖率: {cov:.1%} "
              f"({r1.right}x{r1.bottom} / {r2.right}x{r2.bottom})")
    print()

    print("SW 框架的直接子窗口:")
    child = user32.GetWindow(sw, 5)  # GW_CHILD
    while child:
        ccls = class_name(child)
        ctxt = window_text(child)[:50]
        cvis = bool(user32.IsWindowVisible(child))
        cr = window_rect(child)
        is_focus = " <-- FOCUS" if child == focus else ""
        print(f"  0x{child:X} class='{ccls}' text='{ctxt}' "
              f"visible={cvis} rect={cr}{is_focus}")
        child = user32.GetWindow(child, 2)  # GW_HWNDNEXT

    print()
    print("完成。")


if __name__ == "__main__":
    if "--now" not in sys.argv:
        print("3 秒后采集...")
        for i in range(3, 0, -1):
            print(f"  {i}...", flush=True)
            time.sleep(1)
    main()
