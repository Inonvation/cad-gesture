"""手势引擎模块 - 窗口类型检测 + 双层圆盘支持"""

import os
import math
import time
import threading
import ctypes
import ctypes.wintypes as wintypes
from typing import Callable, Optional, Tuple

from src.logger import get_logger

# Win32 API常量
WH_MOUSE_LL = 14
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MOUSEMOVE = 0x0200
HC_ACTION = 0

# 64位Windows上LRESULT是64位指针大小
HOOKPROC = ctypes.WINFUNCTYPE(ctypes.c_ssize_t, ctypes.c_int,
                               wintypes.WPARAM, wintypes.LPARAM)


class MSLLHOOKEX(ctypes.Structure):
    _fields_ = [
        ("pt", wintypes.POINT),
        ("mouseData", wintypes.DWORD),
        ("flags", wintypes.DWORD),
        ("time", wintypes.DWORD),
        ("dwExtraInfo", ctypes.c_size_t),
    ]


def calc_sector(dx: int, dy: int, sector_count: int) -> int:
    """计算鼠标拖动方向对应的扇区索引（0 ~ sector_count-1）"""
    angle = math.atan2(-dy, dx)
    if angle < 0:
        angle += 2 * math.pi
    sec_angle = 2 * math.pi / sector_count
    adjusted = (angle + math.pi / 2 + sec_angle / 2) % (2 * math.pi)
    return int(adjusted / sec_angle) % sector_count


class GestureEngine:
    """鼠标手势引擎——监听右键拖拽，触发圆盘菜单和命令"""

    def __init__(
        self,
        config: dict,
        on_gesture: Callable[[int, str, str], None],
        on_menu_show: Callable[[int, int, str], None],
        on_menu_hide: Callable[[], None],
        on_extension_hint: Callable[[bool], None]
    ):
        self.config = config
        self.on_gesture = on_gesture       # (sector, ring_type, window_type)
        self.on_menu_show = on_menu_show   # (x, y, window_type)
        self.on_menu_hide = on_menu_hide
        self.on_extension_hint = on_extension_hint  # (is_in_extension_zone)

        self._press_pos: Tuple[int, int] = (0, 0)
        self._press_time: float = 0.0
        self._is_pressed: bool = False
        self._menu_shown: bool = False
        self._in_extension_zone: bool = False
        self._window_type: str = "autocad"
        self._window_cache: Tuple[str, float] = ("", 0.0)
        self._lock = threading.Lock()
        self._hook = None
        self._hook_thread = None
        self._callback = None
        self._starting = False  # 防止 start() 重入
        self._hook_ready = threading.Event()  # 钩子安装完成信号
        # 调试日志默认关闭；环境变量 CAD_GESTURE_DEBUG=1 开启
        self._debug = os.environ.get("CAD_GESTURE_DEBUG", "") in ("1", "true", "yes")
        # 钩子线程内不直接写磁盘（低级钩子回调必须极快），日志先进内存队列，
        # 由主线程定期 flush_logs() 落盘
        self._pending_logs: list = []
        self._pending_logs_lock = threading.Lock()

        # 设置 CallNextHookEx 参数类型（64位兼容）
        user32 = ctypes.windll.user32
        user32.CallNextHookEx.argtypes = [
            wintypes.HHOOK, ctypes.c_int, wintypes.WPARAM, wintypes.LPARAM
        ]
        user32.CallNextHookEx.restype = ctypes.c_ssize_t

    @property
    def dead_zone(self) -> int:
        return self.config.get("settings", {}).get("dead_zone_radius", 30)

    @property
    def trigger_distance(self) -> int:
        """弹出圆盘所需的拖动距离（px），独立于死区，可自定义"""
        return self.config.get("settings", {}).get("trigger_distance", 15)

    @property
    def ring_radius(self) -> int:
        return self.config.get("settings", {}).get("ring_radius", 100)

    @property
    def outer_ring_radius(self) -> int:
        return self.config.get("settings", {}).get("outer_ring_radius", 180)

    @property
    def hold_threshold_ms(self) -> int:
        return self.config.get("settings", {}).get("hold_threshold_ms", 100)

    @property
    def sector_count(self) -> int:
        return self.config.get("settings", {}).get("sector_count", 8)

    def _log(self, msg: str):
        """记录调试日志。

        低级钩子回调线程内不做磁盘 I/O（回调过慢会被系统摘除钩子），
        日志先进内存队列，由主线程 flush_logs() 统一落盘。
        """
        if not self._debug:
            return
        if self._hook_thread is not None and threading.current_thread() is self._hook_thread:
            with self._pending_logs_lock:
                if len(self._pending_logs) < 500:
                    self._pending_logs.append(msg)
            return
        get_logger().info(msg)

    def flush_logs(self):
        """将钩子线程累积的调试日志批量落盘（由主线程定期调用）"""
        if not self._debug:
            return
        logs = None
        with self._pending_logs_lock:
            if self._pending_logs:
                logs = self._pending_logs
                self._pending_logs = []
        if logs:
            logger = get_logger()
            for msg in logs:
                logger.info(msg)

    def _detect_cad_window(self) -> str:
        now = time.monotonic()
        if now - self._window_cache[1] < 0.5:
            return self._window_cache[0]
        try:
            user32 = ctypes.windll.user32
            hwnd = user32.GetForegroundWindow()
            class_name = ctypes.create_unicode_buffer(256)
            user32.GetClassNameW(hwnd, class_name, 256)
            title = ctypes.create_unicode_buffer(256)
            user32.GetWindowTextW(hwnd, title, 256)
            cs, ts = class_name.value.lower(), title.value.lower()
            self._log(f"前台窗口: title=[{ts[:60]}] class=[{cs[:40]}]")
            
            if "zwcad" in ts or "中望" in ts or "zwcad" in cs:
                self._window_cache = ("zwcad", now)
                return "zwcad"
            
            if "autocad" in ts:
                self._window_cache = ("autocad", now)
                return "autocad"
            
            if "afx" in cs and "zwcad" not in cs:
                self._window_cache = ("autocad", now)
                return "autocad"
        except Exception as e:
            if self._debug:
                self._log(f"窗口检测异常: {e}")
        self._window_cache = ("", now)
        return ""

    def _hook_proc(self, nCode: int, wParam: wintypes.WPARAM,
                   lParam: wintypes.LPARAM) -> ctypes.c_ssize_t:
        """低级鼠标钩子回调（对外包装）

        任何异常都不允许传播到 ctypes 回调机制：若异常逃逸，ctypes 会
        返回默认值 0 而非 CallNextHookEx 的结果，导致整个鼠标钩子链断裂。
        """
        try:
            return self._hook_proc_impl(nCode, wParam, lParam)
        except Exception as e:
            if self._debug:
                self._log(f"钩子回调异常: {e}")
            # 异常时也必须继续传递，保证钩子链不断
            return ctypes.windll.user32.CallNextHookEx(
                self._hook, nCode, wParam, lParam)

    def _hook_proc_impl(self, nCode: int, wParam: wintypes.WPARAM,
                        lParam: wintypes.LPARAM) -> ctypes.c_ssize_t:
        """钩子回调主体逻辑"""
        if nCode != HC_ACTION:
            return ctypes.windll.user32.CallNextHookEx(
                self._hook, nCode, wParam, lParam)

        msll = ctypes.cast(lParam, ctypes.POINTER(MSLLHOOKEX)).contents
        x, y = msll.pt.x, msll.pt.y

        # 在锁外收集要执行的回调（避免死锁）
        callback = None
        callback_args = None
        ext_hint_cb = None
        ext_hint_args = None
        should_hide = False

        if wParam == WM_RBUTTONDOWN:
            win_type = self._detect_cad_window()
            if win_type:
                with self._lock:
                    self._press_pos = (x, y)
                    self._press_time = time.monotonic()
                    self._is_pressed = True
                    self._menu_shown = False
                    self._window_type = win_type

        elif wParam == WM_MOUSEMOVE:
            with self._lock:
                if self._is_pressed and not self._menu_shown:
                    dx, dy = x - self._press_pos[0], y - self._press_pos[1]
                    dist = math.sqrt(dx * dx + dy * dy)
                    held_ms = (time.monotonic() - self._press_time) * 1000
                    if dist >= self.trigger_distance and held_ms >= self.hold_threshold_ms:
                        self._menu_shown = True
                        callback = self.on_menu_show
                        callback_args = (self._press_pos[0], self._press_pos[1],
                                         self._window_type)
                elif self._is_pressed and self._menu_shown:
                    dx, dy = x - self._press_pos[0], y - self._press_pos[1]
                    dist = math.sqrt(dx * dx + dy * dy)
                    is_ext = dist > self.outer_ring_radius
                    if is_ext != self._in_extension_zone:
                        self._in_extension_zone = is_ext
                        ext_hint_cb = self.on_extension_hint
                        ext_hint_args = (is_ext,)

        elif wParam == WM_RBUTTONUP:
            ext_hint_cb = None
            ext_hint_args = None
            with self._lock:
                if self._is_pressed:
                    self._is_pressed = False
                    dx, dy = x - self._press_pos[0], y - self._press_pos[1]
                    dist = math.sqrt(dx * dx + dy * dy)
                    held_ms = (time.monotonic() - self._press_time) * 1000
                    if self._menu_shown:
                        # 长按弹菜单路径：拖出触发距离才结算
                        if dist >= self.trigger_distance:
                            callback = self.on_gesture
                            callback_args = self._resolve_gesture(dx, dy, dist)
                    elif dist >= self.trigger_distance and held_ms >= self.hold_threshold_ms:
                        # 快速甩动兜底：菜单来不及弹出（按住时长不足或移动后静止）
                        # 但已拖出死区且按住够久，直接按当前方向触发，避免手势整条丢失
                        callback = self.on_gesture
                        callback_args = self._resolve_gesture(dx, dy, dist)
                    should_hide = True
                    if self._in_extension_zone:
                        ext_hint_cb = self.on_extension_hint
                        ext_hint_args = (False,)
                        self._in_extension_zone = False

        # 在锁外执行回调（避免死锁）
        if should_hide:
            self.on_menu_hide()
        if callback and callback_args:
            callback(*callback_args)
        if ext_hint_cb and ext_hint_args:
            ext_hint_cb(*ext_hint_args)

        return ctypes.windll.user32.CallNextHookEx(
            self._hook, nCode, wParam, lParam)

    def _resolve_gesture(self, dx: int, dy: int, dist: float):
        """根据拖动向量结算扇区与圈层（菜单路径与快速甩动路径共用）"""
        sec = calc_sector(dx, dy, self.sector_count)
        if dist > self.outer_ring_radius:
            ring_type, layer = "extension", "扩展圈"
        elif dist > self.ring_radius:
            ring_type, layer = "outer", "外层"
        else:
            ring_type, layer = "inner", "内层"
        self._log(f"触发手势: {layer} 扇区{sec} (窗口={self._window_type})")
        return (sec, ring_type, self._window_type)

    def cancel_gesture(self):
        """菜单被取消（Esc/左键）时复位手势状态，阻止松键补发命令"""
        with self._lock:
            self._is_pressed = False
            self._menu_shown = False
            self._in_extension_zone = False

    def start(self) -> bool:
        """启动鼠标钩子，返回钩子是否安装成功"""
        with self._lock:
            if self._hook is not None:
                return True
            if self._starting:
                return self._hook is not None
            self._starting = True
            self._hook_ready.clear()

        self._log("启动手势引擎...")
        self._callback = HOOKPROC(self._hook_proc)
        self._hook_thread = threading.Thread(
            target=self._run_hook, daemon=True)
        self._hook_thread.start()
        # 等待钩子安装完成（最多 2 秒）
        if not self._hook_ready.wait(timeout=2.0):
            self._log("钩子安装超时")
            with self._lock:
                self._starting = False
            return False
        with self._lock:
            ok = self._hook is not None
            self._starting = False
        return ok

    def _run_hook(self):
        """运行钩子消息循环"""
        user32 = ctypes.windll.user32
        self._hook = user32.SetWindowsHookExW(
            WH_MOUSE_LL, self._callback, None, 0)
        if not self._hook:
            self._log(f"安装鼠标钩子失败! 错误码: {ctypes.get_last_error()}")
            self._starting = False
            self._hook_ready.set()  # 通知 start() 钩子安装失败
            return
        self._log("鼠标钩子安装成功")
        self._hook_ready.set()  # 通知 start() 钩子安装成功
        msg = wintypes.MSG()
        while user32.GetMessageW(ctypes.byref(msg), None, 0, 0) != 0:
            user32.TranslateMessage(ctypes.byref(msg))
            user32.DispatchMessageW(ctypes.byref(msg))

    def stop(self):
        """停止鼠标钩子"""
        # 在锁内快照并清除状态
        with self._lock:
            if self._hook is None or self._hook_thread is None:
                return
            hook = self._hook
            hook_thread = self._hook_thread
            self._hook = None
            self._hook_thread = None
            self._starting = False
            self._hook_ready.clear()

        # 在锁外执行可能阻塞的 API 调用（避免死锁）
        self._log("停止手势引擎")
        ctypes.windll.user32.UnhookWindowsHookEx(hook)
        ctypes.windll.user32.PostThreadMessageW(
            hook_thread.ident, 0x0012, 0, 0)  # WM_QUIT
        hook_thread.join(timeout=2.0)

    def update_config(self, config: dict):
        self.config = config
