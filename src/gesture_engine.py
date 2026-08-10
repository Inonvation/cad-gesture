"""手势引擎模块 - 窗口类型检测 + 双层圆盘支持"""

import os
import math
import time
import threading
import ctypes
import ctypes.wintypes as wintypes
from typing import Callable, Tuple

from src.logger import get_logger
from src.menu_geometry import menu_scale, scaled_radius

# Win32 API常量
WH_MOUSE_LL = 14
WM_RBUTTONDOWN = 0x0204
WM_RBUTTONUP = 0x0205
WM_MBUTTONDOWN = 0x0207
WM_MBUTTONUP = 0x0208
WM_XBUTTONDOWN = 0x020B
WM_XBUTTONUP = 0x020C
WM_MOUSEMOVE = 0x0200
HC_ACTION = 0
XBUTTON1 = 0x0001
XBUTTON2 = 0x0002

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



# 长按触发所需的最小位移（px）：去手抖，按住不动不算长按
_LONG_PRESS_MIN_DIST = 3


def should_trigger_now(dist: float, held_ms: float,
                       trigger_distance: float,
                       hold_threshold_ms: float) -> bool:
    """按住期间是否立即弹出圆盘（轮询判定用）。

    对齐 Quicker：滑动超过触发距离立即弹出，不等长按时间；
    或按住超过长按延迟且有轻微位移（去手抖）时也弹出。
    """
    if dist >= trigger_distance:
        return True
    return held_ms >= hold_threshold_ms and dist >= _LONG_PRESS_MIN_DIST
def should_trigger_on_release(menu_shown: bool, dist: float, dead_zone: float,
                              trigger_distance: float, held_ms: float,
                              hold_threshold_ms: float) -> bool:
    """松手时是否结算手势命令。

    规则（与圆盘 hover 的中心区判定一致）：
    - 菜单已弹出：松手位置在中心死区内 → 取消，不触发（防止"滑到扇区后
      滑回中心松手"仍触发旧扇区 / 停在中心区松手误触发命令）；
      死区外按最终位置结算（松手在哪就触发哪）。
    - 菜单未弹出（快速甩动兜底）：拖出触发距离且按住够久才触发。
    """
    if menu_shown:
        return dist >= dead_zone
    return dist >= trigger_distance and held_ms >= hold_threshold_ms


class GestureEngine:
    """鼠标手势引擎——监听右键拖拽，触发圆盘菜单和命令"""

    def __init__(
        self,
        config: dict,
        on_gesture: Callable[[int, str, str], None],
        on_gesture_feedback: Callable[[int, str, str], None],
        on_menu_show: Callable[[int, int, str], None],
        on_menu_hide: Callable[[], None],
        on_extension_hint: Callable[[bool], None]
    ):
        self.config = config
        self.on_gesture = on_gesture       # (sector, ring_type, window_type)
        self.on_gesture_feedback = on_gesture_feedback  # 松手即弹：反馈事件先于 hide 入队
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
        self._latest_pos: Tuple[int, int] = (0, 0)  # 最新鼠标位置（轮询判定用）
        self._trigger_thread = None  # 触发判定轮询线程（按住期间运行）
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
        # 进程名查询 API（_detect_cad_window 用）：必须显式声明 64 位句柄类型
        user32.GetWindowThreadProcessId.argtypes = [
            wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
        user32.GetWindowThreadProcessId.restype = wintypes.DWORD
        kernel32 = ctypes.windll.kernel32
        kernel32.OpenProcess.argtypes = [
            wintypes.DWORD, wintypes.BOOL, wintypes.DWORD]
        kernel32.OpenProcess.restype = wintypes.HANDLE
        kernel32.QueryFullProcessImageNameW.argtypes = [
            wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
            ctypes.POINTER(wintypes.DWORD)]
        kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
        kernel32.CloseHandle.argtypes = [wintypes.HANDLE]


    @property
    def menu_scale(self) -> float:
        """整体圆盘缩放比例（50% ~ 150%，默认 100%）"""
        return menu_scale(self.config.get("settings", {}))

    @property
    def dead_zone(self) -> int:
        return scaled_radius(self.config.get("settings", {}), "dead_zone_radius")

    @property
    def trigger_distance(self) -> int:
        """弹出圆盘所需的拖动距离（px），独立于死区，可自定义"""
        return self.config.get("settings", {}).get("trigger_distance", 10)

    @property
    def trigger_button(self) -> str:
        """触发按键：right / middle / x1（后退侧键）/ x2（前进侧键）"""
        return self.config.get("settings", {}).get("trigger_button", "right")

    @property
    def ring_radius(self) -> int:
        return scaled_radius(self.config.get("settings", {}), "ring_radius")

    @property
    def outer_ring_radius(self) -> int:
        return scaled_radius(self.config.get("settings", {}), "outer_ring_radius")

    @property
    def hold_threshold_ms(self) -> int:
        return self.config.get("settings", {}).get("hold_threshold_ms", 80)

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
            # 进程名判断最可靠且不跨进程发消息：GetWindowTextW 是跨进程
            # WM_GETTEXT 同步调用，CAD 繁忙时可能阻塞整个鼠标钩子链，
            # 因此进程名命中就直接返回，标题/类名仅作兜底
            exe = self._foreground_exe(hwnd)
            if exe:
                if "zwcad" in exe:
                    self._window_cache = ("zwcad", now)
                    return "zwcad"
                if "acad" in exe:
                    self._window_cache = ("autocad", now)
                    return "autocad"
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

    def _foreground_exe(self, hwnd) -> str:
        """前台窗口所属进程的可执行文件名（小写）；失败返回空串。"""
        try:
            pid = wintypes.DWORD()
            ctypes.windll.user32.GetWindowThreadProcessId(
                hwnd, ctypes.byref(pid))
            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            kernel32 = ctypes.windll.kernel32
            h = kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION,
                                     False, pid.value)
            if not h:
                return ""
            try:
                buf = ctypes.create_unicode_buffer(1024)
                size = wintypes.DWORD(1024)
                if kernel32.QueryFullProcessImageNameW(
                        h, 0, buf, ctypes.byref(size)):
                    return buf.value.lower()
                return ""
            finally:
                kernel32.CloseHandle(h)
        except Exception:
            return ""

    def _trigger_down(self, wParam, mouse_data) -> bool:
        """当前事件是否为所选触发键的按下"""
        btn = self.trigger_button
        if btn == "middle":
            return wParam == WM_MBUTTONDOWN
        if btn == "x1":
            return wParam == WM_XBUTTONDOWN and (mouse_data >> 16) == XBUTTON1
        if btn == "x2":
            return wParam == WM_XBUTTONDOWN and (mouse_data >> 16) == XBUTTON2
        return wParam == WM_RBUTTONDOWN

    def _trigger_up(self, wParam, mouse_data) -> bool:
        """当前事件是否为所选触发键的松开"""
        btn = self.trigger_button
        if btn == "middle":
            return wParam == WM_MBUTTONUP
        if btn == "x1":
            return wParam == WM_XBUTTONUP and (mouse_data >> 16) == XBUTTON1
        if btn == "x2":
            return wParam == WM_XBUTTONUP and (mouse_data >> 16) == XBUTTON2
        return wParam == WM_RBUTTONUP

    def _start_trigger_monitor(self):
        """右键按下后启动触发判定轮询线程（幂等）"""
        with self._lock:
            if self._trigger_thread is not None:
                return
            self._trigger_thread = threading.Thread(
                target=self._trigger_loop, daemon=True)
            self._trigger_thread.start()

    def _trigger_loop(self):
        """每 15ms 检查一次是否弹出圆盘：滑动达标立即触发，或长按轻微位移触发。

        用独立线程轮询而不是在 mousemove 回调里判定：鼠标停住后
        mousemove 不再产生，原实现会永远等不到触发（快速甩动后停住
        必须继续滑动才出菜单）。"""
        while True:
            time.sleep(0.015)
            cb = None
            cb_args = None
            with self._lock:
                if not self._is_pressed or self._menu_shown:
                    break
                dx = self._latest_pos[0] - self._press_pos[0]
                dy = self._latest_pos[1] - self._press_pos[1]
                dist = math.sqrt(dx * dx + dy * dy)
                held_ms = (time.monotonic() - self._press_time) * 1000
                if should_trigger_now(dist, held_ms,
                                      self.trigger_distance,
                                      self.hold_threshold_ms):
                    self._menu_shown = True
                    cb = self.on_menu_show
                    cb_args = (self._press_pos[0], self._press_pos[1],
                               self._window_type)
            if cb:
                cb(*cb_args)
                break
        with self._lock:
            self._trigger_thread = None

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

        # 触发键判断（右键/中键/侧键，由 settings.trigger_button 决定）
        btn_down = self._trigger_down(wParam, msll.mouseData)
        btn_up = self._trigger_up(wParam, msll.mouseData)

        if btn_down:
            win_type = self._detect_cad_window()
            if win_type:
                with self._lock:
                    self._press_pos = (x, y)
                    self._press_time = time.monotonic()
                    self._latest_pos = (x, y)
                    self._is_pressed = True
                    self._menu_shown = False
                    self._window_type = win_type
                self._start_trigger_monitor()

        elif wParam == WM_MOUSEMOVE:
            with self._lock:
                if self._is_pressed:
                    # 只记录最新位置；触发判定由 _trigger_loop 轮询（不再受
                    # mousemove 事件频率影响，鼠标停住也能按时触发）
                    self._latest_pos = (x, y)
                    if self._menu_shown:
                        dx, dy = x - self._press_pos[0], y - self._press_pos[1]
                        dist = math.sqrt(dx * dx + dy * dy)
                        is_ext = dist > self.outer_ring_radius
                        if is_ext != self._in_extension_zone:
                            self._in_extension_zone = is_ext
                            ext_hint_cb = self.on_extension_hint
                            ext_hint_args = (is_ext,)

        elif btn_up:
            ext_hint_cb = None
            ext_hint_args = None
            with self._lock:
                if self._is_pressed:
                    self._is_pressed = False
                    dx, dy = x - self._press_pos[0], y - self._press_pos[1]
                    dist = math.sqrt(dx * dx + dy * dy)
                    held_ms = (time.monotonic() - self._press_time) * 1000
                    if should_trigger_on_release(
                            self._menu_shown, dist, self.dead_zone,
                            self.trigger_distance, held_ms,
                            self.hold_threshold_ms):
                        callback = self.on_gesture
                        callback_args = self._resolve_gesture(dx, dy, dist)
                    should_hide = True
                    if self._in_extension_zone:
                        ext_hint_cb = self.on_extension_hint
                        ext_hint_args = (False,)
                        self._in_extension_zone = False

        # 在锁外执行回调（避免死锁）
        if callback and callback_args:
            # 弹窗提示最先入队：松手那一刻就弹，不等菜单隐藏 / ESC 取消 / 命令执行
            self.on_gesture_feedback(*callback_args)
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

    def set_gesture_center(self, x: int, y: int):
        """屏幕边缘自适应偏移圆盘中心后，同步手势判定原点（物理坐标），
        保证高亮与松手结算以实际显示中心为准。"""
        with self._lock:
            self._press_pos = (x, y)
            self._latest_pos = (x, y)

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
            # 复位按压状态，让触发判定线程在下一轮立即退出（用户按住右键时退出程序）
            self._is_pressed = False

        # 在锁外执行可能阻塞的 API 调用（避免死锁）
        self._log("停止手势引擎")
        ctypes.windll.user32.UnhookWindowsHookEx(hook)
        ctypes.windll.user32.PostThreadMessageW(
            hook_thread.ident, 0x0012, 0, 0)  # WM_QUIT
        hook_thread.join(timeout=2.0)

    def update_config(self, config: dict):
        self.config = config
