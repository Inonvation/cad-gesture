"""主应用模块 - Qt6 版（PySide6）"""

import os
import sys
import math
import queue
import threading
import tempfile
from datetime import datetime

from PySide6.QtCore import (Qt, QPointF, QTimer, QEvent, QObject,
                           QCoreApplication)
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QMenu, QMessageBox, QWidget,
                               QProgressDialog, QSystemTrayIcon)

from src.config_manager import (
    load_config, save_config, get_active_profile,
    get_profile_for_window, get_profile_names, set_active_profile,
    set_profile_for_target, get_config_path, get_sector_command
)
from src.gesture_engine import GestureEngine
from src.qt_radial_menu import QRadialMenu
from src.qt_feedback import QFeedbackTip
from src.command_executor import execute_with_cancel, cancel_context_menu
from src.single_instance import is_exit_requested
from src.logger import get_logger
from src.i18n import T, set_language, add_listener, remove_listener
from src.theme import (build_app_qss, set_ui_mode, current_ui_mode,
                       effective_ui_mode, set_title_bar_theme,
                       system_ui_mode, set_ui_font_scale)
from src.version import __version__

_CHECK_INTERVAL_SEC = 24 * 3600  # 启动自动检查的最小间隔
_UPDATE_NOTES_MAX = 800


def _preload_pyautogui():
    """后台预热 pyautogui（含 PIL）：首次手势松手发 ESC 时才 import 会
    卡约 0.17s，启动后提前加载，消除第一个手势的瞬间卡顿"""
    try:
        from src.command_executor import _get_pyautogui
        _get_pyautogui()
    except Exception:
        pass

# 跨线程唤醒事件类型：钩子线程入队后 postEvent 到主线程，立即处理。
# 必须包成 QEvent.Type：PySide6 的 QEvent(int) 不接受裸 int，否则抛 TypeError
# 被 _wake 吞掉后唤醒永远不生效（事件只能等定时器轮询，呼出延迟不稳定）
_WAKE_EVENT_TYPE = QEvent.Type(QEvent.registerEventType())


class _WakeQueue(queue.Queue):
    """事件队列：put 后立即调用 wake_cb 唤醒主线程，
    菜单呼出/命令执行不再受定时器轮询间隔限制"""

    def __init__(self, wake_cb):
        super().__init__()
        self._wake = wake_cb

    def put(self, item, *args, **kwargs):
        super().put(item, *args, **kwargs)
        try:
            self._wake()
        except Exception:
            pass


class _WakeReceiver(QObject):
    """接收跨线程唤醒事件，回调主线程处理事件队列"""

    def __init__(self, cb):
        super().__init__()
        self._cb = cb

    def event(self, e):
        if e.type() == _WAKE_EVENT_TYPE:
            self._cb()
            return True
        return super().event(e)


class _TitleBarFilter(QObject):
    """全局事件过滤器：任何带原生标题栏的顶层窗口显示/激活时自动应用深色标题栏。

    无边框窗口（QRadialMenu、扇区编辑浮层）跳过——它们没有系统标题栏，
    DWM 属性对其无效。只在 Show / WindowActivate 时动作，其余事件零开销放行。
    """

    def eventFilter(self, obj, event):
        et = event.type()
        if et == QEvent.Show or et == QEvent.WindowActivate:
            if isinstance(obj, QWidget) and obj.isWindow():
                if not (obj.windowFlags() & Qt.FramelessWindowHint):
                    try:
                        set_title_bar_theme(obj, current_ui_mode() == "dark")
                    except Exception:
                        pass
        return False


class CADGestureApp:
    """CAD鼠标手势应用主类（Qt 版）"""

    def __init__(self):
        self._is_first_run = not os.path.exists(get_config_path())
        self.config = load_config()
        self.log = get_logger()

        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # 界面语言（QSS / 圆盘 / 引擎等重初始化延后到事件循环启动后的
        # _init_late，让托盘图标先出现，缩短启动“无反应”等待）
        s = self.config.get("settings", {})
        set_language(s.get("language", "zh"))
        # 全局事件过滤器：新建的原生标题栏窗口（弹窗/进度框/取色器）自动跟随深色主题
        self._titlebar_filter = _TitleBarFilter()
        self.app.installEventFilter(self._titlebar_filter)

        # 语言切换时重建托盘菜单文本
        self._lang_listener = self._rebuild_tray
        add_listener(self._lang_listener)

        # 事件队列：put 后立即唤醒主线程（postEvent 线程安全），
        # 菜单呼出不再受定时器轮询间隔限制；钩子安装前无事件源，空转安全
        self._wake_receiver = _WakeReceiver(self._process_queue)
        self.event_queue = _WakeQueue(self._wake)

        self._exit_poll_count = 0
        self._quitting = False
        self._init_late_done = False

        # 更新流程状态
        self._update_info = None
        self._update_cancel = False
        self._update_progress = None

    def _init_late(self):
        """事件循环启动后的异步初始化：构建 QSS / 圆盘 / 引擎 / 钩子。

        由 run() 在 exec() 前用 singleShot(0) 排队；主 QTimer 与钩子都在这里
        才启动，事件队列在钩子安装前没有事件源，不会访问未初始化对象。
        """
        try:
            s = self.config.get("settings", {})
            self._apply_ui_mode(s.get("ui_mode", "dark"))

            # 圆盘菜单（Qt 透明悬浮窗）
            self.menu = QRadialMenu(self.config)
            # 命令执行反馈提示（屏幕角落两行文字，短暂淡出）
            self._feedback = QFeedbackTip()
            self.profile = get_active_profile(self.config)

            self.gesture_engine = GestureEngine(
                config=self.config,
                on_gesture=self._queue_gesture,
                on_gesture_feedback=self._queue_gesture_feedback,
                on_menu_show=self._queue_show,
                on_menu_hide=self._queue_hide,
                on_extension_hint=self._queue_extension_hint
            )
            # 菜单被 Esc/左键取消时复位引擎手势状态，阻止松键补发命令
            self.menu._on_cancel = self.gesture_engine.cancel_gesture

            # 命令执行 worker：COM SendCommand 在 CAD 忙时可能阻塞数秒，
            # 放后台线程串行执行，主线程只做入队——弹窗/菜单/下一次手势即时响应
            self._cmd_queue = queue.Queue()
            self._cmd_worker = threading.Thread(
                target=self._cmd_worker_loop, daemon=True)
            self._cmd_worker.start()

            # 主循环定时器：菜单可见时 16ms 高频跟踪光标；隐藏时 250ms 低频空转
            # （事件入队由 _wake 即时唤醒，定时器仅作日志落盘与退出轮询的兜底）
            self._timer = QTimer()
            self._timer.timeout.connect(self._process_queue)
            self._timer.start(16)

            # 跟随系统：轮询系统主题变化（仅 system 模式运行，5 秒一次注册表读，
            # 非 system 模式不启动，避免后台空转）
            self._theme_poll_timer = QTimer()
            self._theme_poll_timer.timeout.connect(self._poll_system_theme)
            self._theme_poll_timer.setInterval(5000)
            if s.get("ui_mode", "dark") == "system":
                self._theme_poll_timer.start()

            self._init_late_done = True

            # 预热 pyautogui：第一个手势的 ESC 取消/命令回退不卡顿
            try:
                threading.Thread(target=_preload_pyautogui,
                                 daemon=True).start()
            except Exception:
                pass

            # 钩子安装（失败仅提示，不阻塞托盘）
            if not self.gesture_engine.start():
                self.log.error("鼠标钩子安装失败，手势将不可用")
                try:
                    self.tray.showMessage(
                        "CAD鼠标手势",
                        T("鼠标钩子安装失败，手势将不可用"),
                        QSystemTrayIcon.Warning, 3000)
                except Exception:
                    pass
            # 升级提示：版本变化时托盘提示一次（记录上次运行版本）
            s2 = self.config.get("settings", {})
            last_run = s2.get("last_run_version", "")
            if last_run and last_run != __version__:
                try:
                    self.tray.showMessage(
                        "CAD鼠标手势",
                        T("已更新到 v{ver}").format(ver=__version__),
                        QSystemTrayIcon.Information, 4000)
                except Exception:
                    pass
            s2["last_run_version"] = __version__
            save_config(self.config)

            # 首次运行或配置了"启动时打开此界面"则自动打开配置
            if self._is_first_run or self.config.get("settings", {}).get(
                    "open_config_on_start", False):
                QTimer.singleShot(500, self._open_config)
        except Exception as e:
            self.log.error("异步初始化失败: %s", e, exc_info=True)
            # 标记初始化流程已尝试完成：让更新检查等事件仍可处理，
            # 并托盘提示，避免部分功能不可用时无声无息
            self._init_late_done = True
            try:
                self.tray.showMessage(
                    "CAD鼠标手势",
                    T("初始化失败，部分功能不可用"),
                    QSystemTrayIcon.Warning, 4000)
            except Exception:
                pass

    # ========== 事件入队 ==========

    def _queue_gesture(self, sector: int, ring_type: str, window_type: str):
        self.event_queue.put(("gesture", (sector, ring_type, window_type)))

    def _queue_gesture_feedback(self, sector: int, ring_type: str, window_type: str):
        """松手即弹反馈事件：先于 hide 入队，弹窗不等待菜单关闭/命令执行"""
        self.event_queue.put(("feedback", (sector, ring_type, window_type)))

    def _queue_show(self, x: int, y: int, window_type: str):
        self.event_queue.put(("show", (x, y, window_type)))

    def _queue_hide(self):
        self.event_queue.put(("hide", None))

    def _queue_extension_hint(self, is_in_zone: bool):
        self.event_queue.put(("extension_hint", is_in_zone))

    def _cmd_worker_loop(self):
        """后台串行执行 CAD 命令（COM SendCommand 可能阻塞，不能占用主线程）"""
        while True:
            key, desc, target = self._cmd_queue.get()
            try:
                result = execute_with_cancel(key, desc, target)
                if result != "ok":
                    self.log.warning("命令执行结果: %s（%s）", result, key)
            except Exception as e:
                self.log.error("命令执行错误: %s", e, exc_info=True)

    def _show_feedback(self, cfg: dict):
        """松手触发命令后立即显示反馈提示（位置/内容/时长均由设置控制）"""
        try:
            s = self.config.get("settings", {})
            if not s.get("command_feedback", True):
                return
            line1 = (cfg.get("label", "") or cfg.get("description", ""))
            if not s.get("feedback_show_name", True):
                line1 = ""
            line2 = ""
            if s.get("feedback_show_key", True) and cfg.get("key"):
                line2 = cfg.get("key", "").upper()
            if not (line1 or line2):
                return
            self._feedback.show_feedback(line1, line2, s)
        except Exception as e:
            self.log.error("显示命令反馈失败: %s", e, exc_info=True)

    def _wake(self):
        """跨线程唤醒主线程立即处理事件队列（postEvent 线程安全）"""
        try:
            QCoreApplication.postEvent(
                self._wake_receiver, QEvent(_WAKE_EVENT_TYPE))
        except Exception:
            pass

    # ========== 主循环 ==========

    def _process_queue(self):
        """处理事件队列（QTimer 驱动）"""
        # 异步初始化完成前不处理（主 QTimer 尚未启动，正常不会触发；防御性保护）
        if not getattr(self, "_init_late_done", False):
            return
        try:
            try:
                while True:
                    event_type, data = self.event_queue.get_nowait()
                    try:
                        if event_type == "show":
                            # 新一次手势开始：清掉上一条残留弹窗，避免提示串台
                            menu = getattr(self, "menu", None)
                            feedback = getattr(self, "_feedback", None)
                            engine = getattr(self, "gesture_engine", None)
                            if menu is None or feedback is None or engine is None:
                                continue  # 初始化失败时无圆盘/反馈对象，跳过该事件
                            feedback.hide_tip()
                            x, y, window_type = data
                            self.profile = get_profile_for_window(self.config, window_type)
                            if self.profile is None:
                                self.profile = get_active_profile(self.config)
                            menu.show(x, y, self.profile)
                            # 圆盘显示中心（屏幕边缘自适应后可能偏移）同步为
                            # 手势判定原点：高亮与松手结算都以圆盘中心为准
                            try:
                                pcx, pcy = menu.display_center_physical()
                                engine.set_gesture_center(
                                    pcx, pcy)
                            except Exception as e:
                                self.log.error("同步手势中心失败: %s", e,
                                               exc_info=True)
                        elif event_type == "feedback":
                            try:
                                if getattr(self, "_feedback", None) is None:
                                    continue
                                sector, ring_type, window_type = data
                                profile = get_profile_for_window(self.config, window_type)
                                if profile is None:
                                    profile = self.profile
                                sector_cfg = get_sector_command(profile, ring_type, sector)
                                if sector_cfg.get("key"):
                                    self._show_feedback(sector_cfg)
                                    self.log.info(
                                        "反馈: %s/%s扇区%d -> %s [%s]", window_type,
                                        ring_type, sector,
                                        sector_cfg.get("label", "") or sector_cfg.get("description", ""),
                                        sector_cfg.get("key", "").upper())
                                else:
                                    # 空扇区不触发命令：同时清掉残留弹窗，避免显示上一条命令
                                    self._feedback.hide_tip()
                            except Exception as e:
                                self.log.error("命令反馈错误: %s", e, exc_info=True)
                        elif event_type == "hide":
                            menu = getattr(self, "menu", None)
                            if menu is not None:
                                menu.hide()
                            # 钩子不拦截右键：松手时 CAD 会弹右键菜单，
                            # 无论是否触发命令都发 ESC 取消（触发路径不再重复发）
                            try:
                                cancel_context_menu()
                            except Exception as e:
                                self.log.error("取消右键菜单失败: %s", e, exc_info=True)
                        elif event_type == "extension_hint":
                            menu = getattr(self, "menu", None)
                            if menu is not None:
                                menu.set_extension_hint(data)
                        elif event_type == "gesture":
                            try:
                                sector, ring_type, window_type = data
                                profile = get_profile_for_window(self.config, window_type)
                                if profile is None:
                                    profile = self.profile
                                # 空扇区返回 {}，不触发命令（不回退内层同方向）
                                sector_cfg = get_sector_command(profile, ring_type, sector)
                                key = sector_cfg.get("key", "")
                                desc = sector_cfg.get("description", "")
                                target = profile.get("target", "autocad")
                                if key:
                                    self.log.info(
                                        "执行: %s/%s扇区%d -> %s [%s]", window_type,
                                        ring_type, sector,
                                        sector_cfg.get("label", "") or desc, key.upper())
                                    # 后台执行，主线程不被 COM SendCommand 阻塞
                                    cmd_queue = getattr(self, "_cmd_queue", None)
                                    if cmd_queue is not None:
                                        cmd_queue.put((key, desc, target))
                            except Exception as e:
                                self.log.error("命令执行错误: %s", e, exc_info=True)
                        elif event_type == "update_check_result":
                            self._on_update_check_result(data)
                        elif event_type == "update_progress":
                            self._on_update_progress(data)
                        elif event_type == "update_download_done":
                            self._on_update_download_done(data)
                    except Exception as e:
                        self.log.error("事件处理错误 (%s): %s", event_type, e, exc_info=True)
            except queue.Empty:
                pass
            except Exception as e:
                self.log.error("事件队列异常: %s", e, exc_info=True)

            # 仅在菜单可见时更新鼠标位置（QCursor 比 pyautogui 更轻量）
            if self.menu.is_visible():
                try:
                    pos = QCursor.pos()
                    self.menu.update_highlight(pos.x(), pos.y())
                except Exception as e:
                    self.log.error("鼠标位置更新失败: %s", e, exc_info=True)

            # 钩子线程累积的调试日志统一落盘
            try:
                self.gesture_engine.flush_logs()
            except Exception as e:
                self.log.error("日志落盘失败: %s", e)

            # 低频检查：被新实例请求覆盖退出时优雅退出
            self._exit_poll_count += 1
            if self._exit_poll_count % 8 == 0:
                try:
                    if is_exit_requested():
                        self.log.info("收到新实例覆盖请求，正在退出当前实例")
                        self._quit()
                        return
                except Exception as e:
                    self.log.error("退出请求检查异常: %s", e, exc_info=True)
        except Exception as e:
            self.log.error("主循环异常: %s", e, exc_info=True)
        finally:
            if not self._quitting:
                delay = 16 if self.menu.is_visible() else 250
                self._timer.setInterval(delay)

    # ========== 界面模式 ==========

    def _apply_ui_mode(self, mode: str):
        """应用界面模式：更新全局 QSS + 所有已存在顶层窗口标题栏 + 记录生效值"""
        self._ui_mode = mode
        set_ui_mode(mode)
        set_ui_font_scale(self.config.get("settings", {}).get(
            "ui_font_scale", 100) / 100.0)
        self._applied_mode = current_ui_mode()
        self._applied_font_scale = self.config.get("settings", {}).get(
            "ui_font_scale", 100)
        self.app.setStyleSheet(build_app_qss(mode))
        for w in self.app.topLevelWidgets():
            try:
                if w.isWindow() and not (w.windowFlags() & Qt.FramelessWindowHint):
                    set_title_bar_theme(w, self._applied_mode == "dark")
            except Exception:
                pass
        # 主题轮询仅在 system 模式运行，其余模式停止空转
        timer = getattr(self, "_theme_poll_timer", None)
        if timer is not None:
            if mode == "system":
                timer.start()
            else:
                timer.stop()
        # 同步运行时圆盘主题（system 模式下系统深浅色切换时，圆盘 hover/配色
        # 必须跟着变；__init__ 早期调用时 menu 尚未创建，需判空）
        menu = getattr(self, "menu", None)
        if menu is not None:
            try:
                menu.update_config(self.config)
            except Exception as e:
                self.log.error("刷新圆盘主题失败: %s", e, exc_info=True)

    def _poll_system_theme(self):
        """system 模式下系统主题变化时自动刷新界面 + 顶栏（5 秒轮询）"""
        if self.config.get("settings", {}).get("ui_mode", "dark") != "system":
            return
        # 必须主动读注册表：current_ui_mode() 是缓存值，只在 set_ui_mode 时
        # 更新，无法反映用户改系统主题后的变化
        if system_ui_mode() != self._applied_mode:
            self._apply_ui_mode("system")

    # ========== 托盘 ==========

    def _create_tray_icon(self) -> QIcon:
        """创建托盘图标（优先加载 assets/icon.ico，失败则代码绘制）"""
        icon_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "assets", "icon.ico")
        if os.path.exists(icon_path):
            return QIcon(icon_path)
        return self._draw_tray_icon()

    def _draw_tray_icon(self) -> QIcon:
        """代码绘制托盘图标（兜底，8 方向径向圆盘）"""
        size = 64
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        cx = cy = size / 2
        r = size / 2 - 4

        p.setPen(QPen(QColor("#0078D4"), 2))
        p.setBrush(QColor("#2b5278"))
        p.drawEllipse(QPointF(cx, cy), r, r)

        for i in range(8):
            angle = -math.pi / 2 + i * math.pi / 4
            mid_angle = angle + math.pi / 8
            mid_r = r * 0.62
            mx = cx + mid_r * math.cos(mid_angle)
            my = cy + mid_r * math.sin(mid_angle)
            p.setPen(Qt.NoPen)
            p.setBrush(QColor("#0078D4" if i % 2 == 0 else "#4a90d9"))
            p.drawEllipse(QPointF(mx, my), 3, 3)

        p.setPen(Qt.NoPen)
        p.setBrush(QColor("#ffffff"))
        p.drawEllipse(QPointF(cx, cy), 3, 3)
        p.end()
        return QIcon(pm)

    def _setup_tray(self):
        """设置系统托盘"""
        self._tray_menu = self._build_tray_menu()  # 保持引用防 GC
        if hasattr(self, "tray"):
            self.tray.setContextMenu(self._tray_menu)
            self.tray.setToolTip(T("CAD鼠标手势"))
            return
        self.tray = QSystemTrayIcon(self._create_tray_icon())
        self.tray.setToolTip(T("CAD鼠标手势"))
        self.tray.setContextMenu(self._tray_menu)
        self.tray.show()

    def _rebuild_tray(self):
        """语言切换后重建托盘菜单文本（保留图标与显示状态）"""
        try:
            self._tray_menu = self._build_tray_menu()
            if hasattr(self, "tray"):
                self.tray.setContextMenu(self._tray_menu)
        except Exception as e:
            self.log.error("重建托盘菜单失败: %s", e, exc_info=True)

    def _build_tray_menu(self) -> QMenu:
        """构建托盘菜单（当前语言）"""
        profile_names = get_profile_names(self.config)
        autocad_profiles = [n for n in profile_names
                            if self.config["profiles"][n].get("target") == "autocad"]
        zwcad_profiles = [n for n in profile_names
                          if self.config["profiles"][n].get("target") == "zwcad"]
        other_profiles = [n for n in profile_names
                          if self.config["profiles"][n].get("target") not in ("autocad", "zwcad")]

        menu = QMenu()

        # 当前各 CAD 生效方案（勾选标记用），与运行时规则一致
        active_by_target = {}
        for tgt in ("autocad", "zwcad"):
            p = get_profile_for_window(self.config, tgt)
            if p is not None:
                active_by_target[tgt] = p.get("name", "")

        def add_profile_actions(names, parent_menu=None, target=None):
            tgt_menu = parent_menu or menu
            for name in names:
                act = QAction(self.config["profiles"][name].get("name", name), tgt_menu)
                act.setCheckable(True)
                act.setChecked(
                    target is not None
                    and active_by_target.get(target) == self.config["profiles"][name].get("name", name))
                act.triggered.connect(lambda _=False, n=name: self._switch_profile(n))
                tgt_menu.addAction(act)

        if autocad_profiles:
            sub = menu.addMenu("AutoCAD")
            add_profile_actions(autocad_profiles, sub, "autocad")
        if zwcad_profiles:
            sub = menu.addMenu(T("中望CAD"))
            add_profile_actions(zwcad_profiles, sub, "zwcad")
        add_profile_actions(other_profiles)

        menu.addSeparator()
        act_cfg = QAction(T("配置"), menu)
        act_cfg.triggered.connect(lambda _=False: self._open_config())
        menu.addAction(act_cfg)
        act_update = QAction(T("检查更新"), menu)
        act_update.triggered.connect(lambda _=False: self._check_update(manual=True))
        menu.addAction(act_update)
        act_exit = QAction(T("退出"), menu)
        act_exit.triggered.connect(lambda _=False: self._quit())
        menu.addAction(act_exit)
        return menu

    def _switch_profile(self, profile_name: str):
        """切换方案（Qt 信号槽运行在主线程，无需跨线程投递）"""
        try:
            set_active_profile(self.config, profile_name)
            # 托盘点选即表示"该方案用于对应 CAD"：同步显式绑定
            prof = self.config["profiles"].get(profile_name, {})
            target = prof.get("target", "")
            if target in ("autocad", "zwcad"):
                set_profile_for_target(self.config, target, profile_name)
            self.profile = get_active_profile(self.config)
            self.gesture_engine.update_config(self.config)
            self.menu.update_config(self.config)
            display = self.config["profiles"].get(profile_name, {}).get("name", profile_name)
            try:
                self.tray.showMessage("CAD鼠标手势",
                                      T("已切换到: {name}").format(name=display),
                                      QSystemTrayIcon.Information, 2000)
            except Exception:
                pass
        except Exception as e:
            self.log.error("切换方案失败: %s", e, exc_info=True)

    def _open_config(self):
        """打开配置界面（Qt 版，独立窗口；延迟 import 避免启动加载整个界面链）"""
        try:
            from src.qt_config_gui import open_config_gui
            self._config_win = open_config_gui(
                on_save=self._reload_config,
                on_check_update=lambda: self._check_update(manual=True))
        except Exception as e:
            self.log.error("打开配置界面失败: %s", e, exc_info=True)

    def _reload_config(self, cfg=None):
        """配置保存后重载（主线程，Qt 信号槽安全）

        配置窗口把内存里的 config 对象直接传入，避免写盘后又从磁盘重读；
        只有界面模式/字号真正变化时才重建全应用 QSS，普通设置（圆盘半径/
        主题/触发阈值）只更新引擎与圆盘，不再触发全控件重刷。
        """
        try:
            self.config = cfg if cfg is not None else load_config()
            self.profile = get_active_profile(self.config)
            engine = getattr(self, "gesture_engine", None)
            if engine is not None:
                engine.update_config(self.config)
            menu = getattr(self, "menu", None)
            if menu is not None:
                menu.update_config(self.config)
            s = self.config.get("settings", {})
            mode = s.get("ui_mode", "dark")
            font = s.get("ui_font_scale", 100)
            # 界面模式（含 system 解析后）或字号变化才重建 QSS，其余设置跳过
            if (effective_ui_mode(mode) != current_ui_mode()
                    or font != self._applied_font_scale):
                self._apply_ui_mode(mode)
        except Exception as e:
            self.log.error("重载配置失败: %s", e, exc_info=True)

    # ========== 自动更新 ==========

    def _check_update(self, manual: bool):
        """检查更新（后台线程执行网络请求，结果经事件队列回主线程）"""
        if manual is False and not self._should_auto_check():
            return
        url = self.config.get("settings", {}).get(
            "update_source_url",
            "https://api.github.com/repos/Inonvation/cad-gesture/releases/latest")
        threading.Thread(target=self._check_worker, args=(url, manual),
                         daemon=True).start()

    def _check_worker(self, url: str, manual: bool):
        from src.updater import check_for_update, UpdateError
        try:
            info = check_for_update(__version__, url)
            result = {"ok": True, "info": info, "error": None, "manual": manual}
        except UpdateError as e:
            result = {"ok": False, "info": None, "error": str(e), "manual": manual}
        except Exception as e:
            result = {"ok": False, "info": None,
                      "error": f"检查更新异常: {e}", "manual": manual}
        self.event_queue.put(("update_check_result", result))

    def _should_auto_check(self) -> bool:
        """启动自动检查：开关开启 + 距上次检查超过 24h"""
        s = self.config.get("settings", {})
        if not s.get("check_update_on_start", True):
            return False
        last = s.get("last_update_check", "")
        if not last:
            return True
        try:
            t = datetime.fromisoformat(last)
            return (datetime.now() - t).total_seconds() >= _CHECK_INTERVAL_SEC
        except Exception:
            return True

    def _on_update_check_result(self, data: dict):
        """主线程处理检查结果（弹窗/气泡都在主线程安全操作）"""
        ok = data.get("ok")
        manual = data.get("manual", False)
        if ok and data.get("info"):
            self._set_last_update_check()
            self._show_update_dialog(data["info"])
        elif ok:
            self._set_last_update_check()
            if manual:
                # 托盘气泡在 Windows 上可能被通知设置屏蔽，手动检查用弹窗确保可见
                try:
                    QMessageBox.information(
                        None, T("检查更新"),
                        T("已是最新版本（v{ver}）").format(ver=__version__))
                except Exception as e:
                    self.log.error("提示弹窗失败: %s", e, exc_info=True)
        else:
            if manual:
                try:
                    QMessageBox.warning(
                        None, T("检查更新"),
                        data.get("error", T("检查更新")) +
                        "\n\n" + T("提示：GitHub 接口有限频（约 60 次/小时），"
                                  "如提示 403 请稍后再试"))
                except Exception as e:
                    self.log.error("提示弹窗失败: %s", e, exc_info=True)
            else:
                self.log.warning("启动时自动检查更新失败: %s",
                                 data.get("error", "未知错误"))

    def _set_last_update_check(self):
        try:
            s = self.config.setdefault("settings", {})
            s["last_update_check"] = datetime.now().isoformat(timespec="seconds")
            save_config(self.config)
        except Exception as e:
            self.log.error("记录检查时间失败: %s", e, exc_info=True)

    def _tray_message(self, title: str, msg: str, icon=None, ms: int = 3000):
        try:
            self.tray.showMessage(title, msg, icon or QSystemTrayIcon.Information, ms)
        except Exception:
            pass

    def _show_update_dialog(self, info: dict):
        """有新版本：弹出更新说明对话框"""
        self._update_info = info
        box = QMessageBox()
        box.setIcon(QMessageBox.Information)
        box.setWindowTitle(T("发现新版本"))
        box.setText(T("CAD鼠标手势 v{new} 已发布（当前 v{cur}）")
                    .format(new=info.get("version", ""), cur=__version__))
        notes = (info.get("notes") or "").strip() or T("（无更新说明）")
        if len(notes) > _UPDATE_NOTES_MAX:
            notes = notes[:_UPDATE_NOTES_MAX] + "..."
        box.setInformativeText(notes)
        btn_now = box.addButton(T("立即更新"), QMessageBox.AcceptRole)
        box.addButton(T("稍后再说"), QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is btn_now:
            self._start_update_download(info)

    def _start_update_download(self, info: dict):
        """开始后台下载安装包，主线程显示进度条"""
        self._update_cancel = False
        dest = os.path.join(tempfile.gettempdir(), "CADGesture-Setup.exe")
        try:
            os.remove(dest)
        except OSError:
            pass
        total = info.get("size") or 0
        self._update_progress = QProgressDialog(
            T("正在下载 v{ver} 更新包...").format(ver=info.get("version", "")),
            T("取消"), 0, 100 if total > 0 else 0)
        self._update_progress.setWindowTitle(T("CAD鼠标手势 - 更新"))
        self._update_progress.setWindowModality(Qt.WindowModal)
        self._update_progress.setMinimumDuration(0)
        self._update_progress.canceled.connect(
            lambda: setattr(self, "_update_cancel", True))
        self._update_progress.show()
        threading.Thread(target=self._download_worker, args=(info, dest),
                         daemon=True).start()

    def _download_worker(self, info: dict, dest: str):
        from src.updater import download_update
        ok = download_update(info.get("download_url", ""), dest,
                             info.get("size") or 0,
                             progress_cb=self._download_progress)
        self.event_queue.put(("update_download_done", (ok, dest)))

    def _download_progress(self, downloaded: int, total: int):
        """下载线程回调：检查取消 + 进度入队"""
        if self._update_cancel:
            from src.updater import UpdateCancelled
            raise UpdateCancelled("下载被取消")
        self.event_queue.put(("update_progress", (downloaded, total)))

    def _on_update_progress(self, data: tuple):
        try:
            downloaded, total = data
            if self._update_progress is None:
                return
            if total > 0:
                pct = int(downloaded * 100 / total)
                self._update_progress.setValue(min(pct, 100))
                self._update_progress.setLabelText(
                    T("正在下载更新包... {got} KB / {total} KB")
                    .format(got=downloaded // 1024, total=total // 1024))
            else:
                self._update_progress.setValue(0)
        except Exception as e:
            self.log.error("更新进度更新失败: %s", e, exc_info=True)

    def _on_update_download_done(self, data: tuple):
        """下载完成：直接静默安装并退出（用户已在“发现新版本”确认过，不再二次确认）"""
        ok, dest = data
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress = None
        if self._update_cancel:
            self._tray_message("CAD鼠标手势", T("更新已取消"))
            return
        if not ok:
            # 下载失败用弹窗（托盘气泡可能被系统屏蔽），确保用户看到
            try:
                QMessageBox.warning(
                    None, T("更新失败"),
                    T("下载失败，请检查网络后重试"))
            except Exception:
                pass
            return
        from src.updater import run_installer
        if not run_installer(dest):
            try:
                QMessageBox.warning(
                    None, T("更新失败"),
                    T("启动安装程序失败，请手动运行更新包"))
            except Exception:
                pass
            return
        # 安装前提示：程序即将退出，静默安装后自动启动新版
        self._tray_message("CAD鼠标手势",
                           T("正在安装更新，完成后自动启动"))
        self.log.info("更新流程启动，即将退出当前实例")
        self._quit()

    # ========== 退出 ==========

    def _quit(self):
        if self._quitting:
            return
        self._quitting = True
        remove_listener(self._lang_listener)
        try:
            engine = getattr(self, "gesture_engine", None)
            if engine is not None:
                engine.stop()
        except Exception as e:
            self.log.error("停止手势引擎失败: %s", e, exc_info=True)
        try:
            menu = getattr(self, "menu", None)
            if menu is not None:
                menu.destroy()
        except Exception as e:
            self.log.error("销毁菜单窗口失败: %s", e, exc_info=True)
        try:
            tray = getattr(self, "tray", None)
            if tray is not None:
                tray.hide()
        except Exception as e:
            self.log.error("隐藏托盘失败: %s", e, exc_info=True)
        self.app.quit()

    def run(self):
        """运行应用：先出托盘图标，重初始化与钩子在事件循环内异步完成"""
        self._setup_tray()
        QTimer.singleShot(0, self._init_late)
        # 启动后延迟自动检查更新（后台线程，不阻塞启动；24h 内不重复）
        QTimer.singleShot(8000, lambda: self._check_update(manual=False))
        sys.exit(self.app.exec())
