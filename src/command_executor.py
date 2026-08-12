"""命令执行模块 - 高速 COM 发送，最小延迟"""

import ctypes
import ctypes.wintypes as wintypes
import time
import threading
import pythoncom
import win32com.client

# pyautogui 延迟加载：仅在首次需要按键模拟（ESC 取消 /
# COM 回退）时才 import，避免启动时加载 pyautogui+PIL。
# 首次调用后缓存，全局只设置一次。
_pyautogui_mod = None
_pyautogui_lock = threading.Lock()


def _get_pyautogui():
    """首次调用时加载 pyautogui 并设置全局参数（线程安全）"""
    global _pyautogui_mod
    if _pyautogui_mod is None:
        with _pyautogui_lock:
            if _pyautogui_mod is None:
                import pyautogui
                pyautogui.FAILSAFE = False
                pyautogui.PAUSE = 0  # 移除全局暂停，手动控制
                _pyautogui_mod = pyautogui
    return _pyautogui_mod

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

# 支持 COM SendCommand 的目标：其他自定义应用只能按键模拟（pyautogui）
_CAD_TARGETS = ("autocad", "zwcad")

# IME 控制消息常量（WM_IME_CONTROL 相关）
WM_IME_CONTROL = 0x0283
IMC_GETCONVERSIONMODE = 0x0001
IMC_SETCONVERSIONMODE = 0x0002
IME_CMODE_NATIVE = 0x0001

# SendInput 全局串行锁：ESC 取消（主线程）与 pyautogui 回退（命令 worker）
# 可能并发触发，用锁保证按键不交错
_input_lock = threading.Lock()

# 线程本地存储，确保每个线程独立初始化 COM
_thread_local = threading.local()
# 模块级缓存，按 target 分别缓存（autocad / zwcad）
_com_cache = {}
_cache_lock = threading.Lock()


def _ime_wnd_send(ime_wnd, wparam, lparam, timeout_ms=200):
    """带超时地向 IME 窗口发送 WM_IME_CONTROL 消息

    SendMessageW 会同步阻塞等待目标进程（CAD）处理完消息，
    若 CAD 繁忙或挂死主线程会无限卡住。改用 SendMessageTimeoutW
    保证最多等待 timeout_ms 就返回，避免 Qt 主线程被拖死。

    Returns:
        消息结果（无符号），失败或超时返回 None。
    """
    try:
        user32 = ctypes.windll.user32
        user32.SendMessageTimeoutW.restype = ctypes.c_ssize_t
        user32.SendMessageTimeoutW.argtypes = [
            wintypes.HWND, wintypes.UINT, wintypes.WPARAM, wintypes.LPARAM,
            wintypes.UINT, wintypes.UINT, ctypes.POINTER(ctypes.c_size_t),
        ]
        SMTO_ABORTIFHUNG = 0x0002
        result = ctypes.c_size_t()
        ok = user32.SendMessageTimeoutW(
            ime_wnd, WM_IME_CONTROL, wparam, lparam,
            SMTO_ABORTIFHUNG, timeout_ms, ctypes.byref(result),
        )
        if not ok:
            return None
        return result.value & 0xFFFFFFFF
    except Exception:
        return None


def _switch_to_english_ime():
    """让 CAD 窗口所在线程的输入法切换到英文模式（不换键盘布局）

    通过向前台窗口的默认 IME 窗口发送 WM_IME_CONTROL / IMC_SETCONVERSIONMODE，
    直接把输入法的转换模式设为英文（清除 IME_CMODE_NATIVE 标志）。该方案：
    1. 保留当前输入法本身（微软拼音等），任务栏仍是输入法图标，Shift 可切回中文；
    2. 不模拟按键、不切换键盘布局，避免误触和抢焦点；
    3. 设置后读取验证，失败才回退到整体切换英文键盘布局。

    必须显式声明 restype/argtypes：GetForegroundWindow 返回 64 位 HWND、
    LoadKeyboardLayoutW 返回 64 位 HKL，默认 c_int 会截断高 32 位，
    导致 PostMessage 发到错误窗口或无效 HKL，输入法切换静默失败。
    """
    try:
        user32 = ctypes.windll.user32
        user32.GetForegroundWindow.restype = wintypes.HWND
        imm32 = ctypes.windll.imm32
        imm32.ImmGetDefaultIMEWnd.restype = wintypes.HWND
        imm32.ImmGetDefaultIMEWnd.argtypes = [wintypes.HWND]

        hwnd = user32.GetForegroundWindow()
        if not hwnd:
            return
        ime_wnd = imm32.ImmGetDefaultIMEWnd(hwnd)
        if not ime_wnd:
            raise RuntimeError("no default IME window")

        conv = _ime_wnd_send(ime_wnd, IMC_GETCONVERSIONMODE, 0)
        if conv is not None and not (conv & IME_CMODE_NATIVE):
            return  # 输入法已在英文模式
        _ime_wnd_send(ime_wnd, IMC_SETCONVERSIONMODE, 0)
        time.sleep(0.05)
        conv = _ime_wnd_send(ime_wnd, IMC_GETCONVERSIONMODE, 0)
        if conv is not None and not (conv & IME_CMODE_NATIVE):
            return  # 切换成功
        raise RuntimeError("IME switch failed")
    except Exception:
        pass

    # 回退：无 IME 窗口或切换验证失败 → 整体切到英文键盘布局
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
        if en_hkl and hwnd:
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
    if target not in _CAD_TARGETS:
        return False  # 非 CAD：直接走 pyautogui 按键回退
    if cmd_name:
        return _send_com_command(f"_.{cmd_name.upper()}\n", target)
    parts = [k.strip().lower() for k in key.split("+")]
    if len(parts) >= 2 and parts[0] in ("ctrl", "alt", "shift", "win"):
        combo = "+".join(parts)
        if combo in COMBO_TO_COMMAND:
            return _send_com_command(COMBO_TO_COMMAND[combo] + "\n", target)
        return False
    return _send_com_command(f"{key}\n", target)


def cancel_context_menu():
    """连发两次 ESC 取消 CAD 的右键上下文菜单。

    钩子不拦截右键，CAD 收到右键释放会弹菜单。仅在发生了手势交互
    （圆盘已弹出或有手势触发）时由 app 的 hide 事件处理调用；无滑动的
    普通右键不取消，保留 CAD 原生右键菜单。
    与命令回退的按键模拟共用 _input_lock，防止并发 SendInput 交错。
    """
    with _input_lock:
        _get_pyautogui().press('esc', _pause=False)
        time.sleep(0.02)
        _get_pyautogui().press('esc', _pause=False)
        time.sleep(0.02)


def execute_with_cancel(key: str, cmd_name: str = "", target: str = "autocad") -> str:
    """执行 CAD 命令 — 优先 COM，失败回退 pyautogui

    右键菜单的 ESC 取消由调用方在松手时刻统一处理（cancel_context_menu），
    这里不再重复发送，避免连发两次 ESC 误伤其他对话框。

    Returns:
        "ok": 通过 COM 成功发送
        "fallback": COM 不可用，已改用按键模拟发送
        "failed": 执行失败（无命令或按键模拟异常）
    """
    if not key:
        return "failed"

    # COM 路径（最快，不干扰鼠标）
    if _send_via_com(key, cmd_name, target):
        return "ok"

    # 回退：pyautogui 模拟按键
    try:
        # 输入法切英文，否则按键会被 IME 吞成中文
        _switch_to_english_ime()

        # 与 cancel_context_menu 共用锁：worker 回退与主线程 ESC 的
        # SendInput 按键不能交错，整个按键序列都在锁内
        with _input_lock:
            parts = [k.strip().lower() for k in key.split("+")]
            pa = _get_pyautogui()
            if len(parts) == 1:
                single = parts[0]
                if len(single) > 1 and single in pa.KEYBOARD_KEYS:
                    pa.press(single, _pause=False)
                else:
                    for ch in single:
                        pa.press(ch, _pause=False)
                    time.sleep(0.01)
                    pa.press('enter', _pause=False)
            elif len(parts) >= 2 and parts[0] in ("ctrl", "alt", "shift", "win"):
                pa.hotkey(*parts, _pause=False)
            else:
                for k in parts:
                    pa.press(k, _pause=False)
                time.sleep(0.01)
                pa.press('enter', _pause=False)
        return "fallback"
    except Exception:
        return "failed"
