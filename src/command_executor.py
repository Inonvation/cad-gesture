"""命令执行模块 - 高速 COM 发送，最小延迟"""

import ctypes
import ctypes.wintypes as wintypes
import time
import threading
import pythoncom
import win32com.client
import pyautogui

pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0  # 移除全局暂停，手动控制

# COM 命令映射表
COMBO_TO_COMMAND = {
    "ctrl+z": "_.U",
    "ctrl+y": "_.REDO",
    "ctrl+s": "_.QSAVE",
    "ctrl+o": "_.OPEN",
    "ctrl+n": "_.NEW",
    "ctrl+p": "_.PLOT",
    "ctrl+a": "_.AI_SELALL",
    "ctrl+x": "_.CUTCLIP",
    "ctrl+c": "_.COPYCLIP",
    "ctrl+shift+s": "_.SAVEAS",
    "ctrl+shift+c": "_.COPYBASE",
    "ctrl+shift+v": "_.PASTEBLOCK",
}

# 线程本地存储，确保每个线程独立初始化 COM
_thread_local = threading.local()
# 模块级缓存，按 target 分别缓存（autocad / zwcad）
_com_cache = {}
_cache_lock = threading.Lock()


def _switch_to_english_ime():
    """通过 PostMessage 让 CAD 窗口切换到英文输入法

    必须显式声明 restype/argtypes：GetForegroundWindow 返回 64 位 HWND、
    LoadKeyboardLayoutW 返回 64 位 HKL，默认 c_int 会截断高 32 位，
    导致 PostMessage 发到错误窗口或无效 HKL，输入法切换静默失败。
    """
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        user32.LoadKeyboardLayoutW.restype = wintypes.HANDLE
        user32.LoadKeyboardLayoutW.argtypes = [wintypes.LPCWSTR, wintypes.DWORD]
        user32.PostMessageW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM
        ]
        en_hkl = user32.LoadKeyboardLayoutW("00000409", 0x00000001)
        hwnd = user32.GetForegroundWindow()
        user32.PostMessageW(hwnd, 0x0050, 0, en_hkl)
    except Exception:
        pass


def _get_com_app(target: str = "autocad"):
    """获取缓存的 COM 应用对象（线程安全）"""
    now = time.monotonic()
    prog_id = "AutoCAD.Application" if target == "autocad" else "ZWCAD.Application"

    # 快速路径：检查缓存是否有效
    with _cache_lock:
        cache = _com_cache.get(target)
        if cache is not None and cache["app"] is not None and (now - cache["last_try"]) < 5:
            return cache["app"]

    # 每个线程仅初始化一次 COM
    if not getattr(_thread_local, 'com_initialized', False):
        try:
            pythoncom.CoInitialize()
            _thread_local.com_initialized = True
        except Exception:
            pass

    try:
        app = win32com.client.GetActiveObject(prog_id)
        with _cache_lock:
            _com_cache[target] = {"app": app, "last_try": now}
        return app
    except Exception:
        with _cache_lock:
            _com_cache[target] = {"app": None, "last_try": now}
        return None


def _send_com_command(cmd_text: str, target: str = "autocad") -> bool:
    """通过 COM SendCommand 发送命令（单次尝试，无重试延迟）"""
    _switch_to_english_ime()
    app = _get_com_app(target)
    if app is None:
        return False
    try:
        app.ActiveDocument.SendCommand(cmd_text)
        return True
    except Exception:
        # COM 对象可能失效，清除对应 target 缓存
        with _cache_lock:
            cache = _com_cache.get(target)
            if cache is not None:
                cache["app"] = None
                cache["last_try"] = time.monotonic()
        return False


def _send_via_com(key: str, cmd_name: str = "", target: str = "autocad") -> bool:
    """通过 COM 发送命令，优先完整命令名"""
    if cmd_name:
        return _send_com_command(f"_.{cmd_name.upper()}\n", target)
    parts = [k.strip().lower() for k in key.split("+")]
    if len(parts) >= 2 and parts[0] in ("ctrl", "alt", "shift", "win"):
        combo = "+".join(parts)
        if combo in COMBO_TO_COMMAND:
            return _send_com_command(COMBO_TO_COMMAND[combo] + "\n", target)
        return False
    return _send_com_command(f"{key}\n", target)


def execute_with_cancel(key: str, cmd_name: str = "", target: str = "autocad", menu_was_shown: bool = False):
    """执行 CAD 命令 — 优先 COM，失败回退 pyautogui"""
    if not key:
        return

    # COM 路径（最快，不干扰鼠标）
    if _send_via_com(key, cmd_name, target):
        return

    # 回退：pyautogui 模拟按键
    # 仅在显示过圆盘菜单时才先 ESC 取消右键菜单
    if menu_was_shown:
        pyautogui.press('esc', _pause=False)
        time.sleep(0.02)
        pyautogui.press('esc', _pause=False)
        time.sleep(0.02)

    parts = [k.strip().lower() for k in key.split("+")]
    if len(parts) == 1:
        single = parts[0]
        if len(single) > 1 and single in pyautogui.KEYBOARD_KEYS:
            pyautogui.press(single, _pause=False)
        else:
            for ch in single:
                pyautogui.press(ch, _pause=False)
            time.sleep(0.01)
            pyautogui.press('enter', _pause=False)
    elif len(parts) >= 2 and parts[0] in ("ctrl", "alt", "shift", "win"):
        pyautogui.hotkey(*parts, _pause=False)
    else:
        for k in parts:
            pyautogui.press(k, _pause=False)
        time.sleep(0.01)
        pyautogui.press('enter', _pause=False)
