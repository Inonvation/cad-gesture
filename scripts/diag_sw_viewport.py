# -*- coding: utf-8 -*-
"""诊断 SW 绘图区视口 hwnd。"""
import ctypes
import ctypes.wintypes as wintypes

user32 = ctypes.windll.user32


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


def is_visible(hwnd):
    return bool(user32.IsWindowVisible(hwnd))


def find_sw_frame():
    result = []

    def cb(hwnd, _):
        if not is_visible(hwnd):
            return True
        cls = class_name(hwnd)
        if cls.startswith("Afx:") and not user32.GetParent(hwnd):
            txt = window_text(hwnd)
            if "SOLIDWORKS" in txt:
                result.append(hwnd)
        return True

    WNDENUMPROC = ctypes.WINFUNCTYPE(wintypes.BOOL, wintypes.HWND,
                                     wintypes.LPARAM)
    user32.EnumWindows(WNDENUMPROC(cb), 0)
    return result[0] if result else 0


def find_child_by_class(parent, cls_substr):
    child = user32.GetWindow(parent, 5)
    while child:
        if cls_substr.lower() in class_name(child).lower():
            return child
        child = user32.GetWindow(child, 2)
    return 0


def dump_children(hwnd, label="", depth=0, max_depth=3):
    if depth > max_depth:
        return
    child = user32.GetWindow(hwnd, 5)
    while child:
        cls = class_name(child)
        txt = window_text(child)[:40]
        vis = is_visible(child)
        wr = window_rect(child)
        w = wr[2] - wr[0]
        h = wr[3] - wr[1]
        prefix = "  " * (depth + 1)
        if vis and w > 100 and h > 100:
            print(f"{prefix}0x{child:X} class='{cls}' text='{txt}' "
                  f"size={w}x{h}")
            dump_children(child, depth=depth + 1, max_depth=max_depth)
        child = user32.GetWindow(child, 2)


def main():
    frame = find_sw_frame()
    if not frame:
        print("未找到 SW 窗口")
        return
    print(f"SW 框架: 0x{frame:X} class='{class_name(frame)}' "
          f"text='{window_text(frame)}'")

    # 找 swMdiClient
    mdi = find_child_by_class(frame, "swMdiClient")
    print(f"\nswMdiClient: 0x{mdi:X}" if mdi else "\n未找到 swMdiClient")

    if mdi:
        print("swMdiClient 的子窗口（>100x100）:")
        dump_children(mdi, max_depth=3)

    # 直接在框架下找视口类
    print("\n框架下匹配视口类名的窗口:")
    child = user32.GetWindow(frame, 5)
    while child:
        cls = class_name(child).lower()
        if any(h in cls for h in ("afxframeorview", "gxwnd", "swview")):
            vis = is_visible(child)
            wr = window_rect(child)
            w = wr[2] - wr[0]
            h = wr[3] - wr[1]
            print(f"  0x{child:X} class='{class_name(child)}' "
                  f"text='{window_text(child)[:40]}' "
                  f"visible={vis} size={w}x{h}")
        child = user32.GetWindow(child, 2)


if __name__ == "__main__":
    main()
