"""主应用模块 - Qt6 版（PySide6）"""

import os
import sys
import math
import queue
import threading
import tempfile
import time
from datetime import datetime

from PySide6.QtCore import (Qt, QPointF, QTimer, QEvent, QObject,
                           QCoreApplication)
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QMenu, QMessageBox, QWidget,
                               QSystemTrayIcon)

from src.config_manager import (
    load_config, save_config, get_active_profile,
    get_profile_for_window, get_profile_names, set_active_profile,
    set_profile_for_target, get_target_order, get_target_label,
    get_config_path, get_sector_command
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
# 更新标记文件：更新流程退出前写入"期望安装的新版本号"，新版启动时读取并
# 与自身版本比对——达到期望 = 更新成功弹确认；仍低于期望 = 上次静默安装中途
# 失败（旧版已退出，用户无感知），弹提示引导手动处理。随后删除标记。
# 写在 %TEMP%（与下载的安装包同目录），不落在用户配置里。
# 注：该机制是 Inno 时代产物，仅保留用于老用户经桥接升级后首次启动的兼容
# 提示；Velopack 时代更新成功提示改由 _RESTART_FLAG（on_restarted 钩子置位）。
_UPDATE_SUCCESS_MARKER = os.path.join(
    tempfile.gettempdir(), "CADGesture-updated.txt")

# 更新重启标志（环境变量）：Velopack on_restarted 钩子在 Qt 就绪前触发，
# 置此标志，由 _show_update_success_if_any 在启动后读取并弹"已更新到 vX"。
_RESTART_FLAG = "CADGESTURE_UPDATED_RESTART"


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
        # 界面字号生效值：_apply_ui_mode 中记录，__init__ 先置 None，
        # 避免配置窗口在 _init_late 完成前触发保存时 _reload_config 报
        # AttributeError（日志出现过）
        self._applied_font_scale = None

        # 更新流程状态
        self._update_cancel = False
        self._update_dialog = None
        # 更新信息缓存：_start_and_finish 写"期望版本"更新标记时使用（主线程访问）
        self._update_info = None
        # 更新源 (url, token)：_check_update 记录，后台下载/主线程应用时重建 manager
        self._update_source = None
        # github=安装版下载 Setup.exe；velopack=绿色版/Velopack 布局
        self._update_mode = "github"
        # 安装版下载目标路径（%TEMP%\CADGesture-Setup.exe）
        self._update_dest = None

    def _init_late(self):
        """事件循环启动后的异步初始化：构建 QSS / 圆盘 / 引擎 / 钩子。

        由 run() 在 exec() 前用 singleShot(0) 排队；主 QTimer 与钩子都在这里
        才启动，事件队列在钩子安装前没有事件源，不会访问未初始化对象。
        """
        try:
            s = self.config.get("settings", {})
            self._apply_ui_mode(s.get("ui_mode", "light"))

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
            if s.get("ui_mode", "light") == "system":
                self._theme_poll_timer.start()

            # SolidWorks 输入法助手：SW 前台时按焦点自动管输入法，与手势无关
            self._sync_ime_assist_timer()

            self._init_late_done = True

            # 更新成功反馈：走更新流程后新版启动，弹窗确认“已更新”（比气泡可靠）
            QTimer.singleShot(800, self._show_update_success_if_any)

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

    def _queue_hide(self, cancel_ctx_menu: bool = False):
        """圆盘隐藏事件：cancel_ctx_menu 表示是否需取消 CAD 右键上下文菜单"""
        self.event_queue.put(("hide", cancel_ctx_menu))

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
                                # 配置了命令（快捷键或 CAD 命令任一非空）就显示反馈；
                                # 完全空扇区返回 {}，不显示也不执行
                                if sector_cfg.get("key") or sector_cfg.get("description"):
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
                            # 钩子不拦截右键：松手时 CAD 会弹右键菜单。仅在
                            # 实际手势交互（圆盘弹出或有手势触发）时发 ESC 取消，
                            # 无滑动的普通右键不拦截，保留 CAD 原生右键菜单。
                            if data:
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
                                # 快捷键或 CAD 命令任一非空即执行；只填 CAD 命令时
                                # 由 command_executor 的 _send_via_com 用 cmd_name 走
                                # COM。完全空扇区返回 {}，不触发命令
                                if key or desc:
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
                        elif event_type == "update_progress_pct":
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
            _menu = getattr(self, "menu", None)
            if _menu is not None and _menu.is_visible():
                try:
                    pos = QCursor.pos()
                    _menu.update_highlight(pos.x(), pos.y())
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
                menu = getattr(self, "menu", None)
                # 异步初始化失败且未走到创建 QTimer 时（如 _apply_ui_mode /
                # 圆盘构造早期抛异常），timer 不存在；这里判空避免 finally 里
                # 抛 AttributeError 逃逸出 Qt 事件处理器导致应用被 abort
                timer = getattr(self, "_timer", None)
                if timer is not None:
                    delay = 16 if (menu is not None and menu.is_visible()) else 250
                    timer.setInterval(delay)

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
        if self.config.get("settings", {}).get("ui_mode", "light") != "system":
            return
        # 必须主动读注册表：current_ui_mode() 是缓存值，只在 set_ui_mode 时
        # 更新，无法反映用户改系统主题后的变化
        if system_ui_mode() != self._applied_mode:
            self._apply_ui_mode("system")

    # ========== SolidWorks 输入法助手 ==========

    def _sync_ime_assist_timer(self):
        """按设置启停 SW 输入法助手（100ms 轮询 + 按键直通拦截器）

        两种模式共用一个 100ms 定时器，按 settings.ime_assist_mode 分发：
          key    —— 定时器只发布上下文快照；拦截器负责吞键 + 直投（默认）
          layout —— 沿用原「按焦点切键盘布局」实现（回退路径）
        """
        try:
            timer = getattr(self, "_ime_assist_timer", None)
            if timer is None:
                from PySide6.QtCore import QTimer
                timer = QTimer()
                timer.timeout.connect(self._ime_assist_tick)
                timer.setInterval(100)
                self._ime_assist_timer = timer
            s = self.config.get("settings", {})
            enabled = bool(s.get("ime_assist_sw", True))
            mode = s.get("ime_assist_mode", "key") or "key"
            if enabled:
                timer.start()
            else:
                timer.stop()
            self._sync_sw_interceptor(enabled and mode == "key")
        except Exception as e:
            self.log.error("同步输入法助手定时器失败: %s", e, exc_info=True)

    def _sync_sw_interceptor(self, want: bool):
        """按键直通拦截器的启停（负责装卸全局键盘钩子）"""
        inter = getattr(self, "_sw_interceptor", None)
        if want and inter is None:
            try:
                from src.sw_key_assist import get_interceptor
                inter = get_interceptor(log=self.log)
                if not inter.start():
                    self.log.error("SolidWorks 按键直通：键盘钩子安装失败")
                    return
                self._sw_interceptor = inter
            except Exception as e:
                self.log.error("启动按键直通失败: %s", e, exc_info=True)
        elif not want and inter is not None:
            try:
                inter.stop()
            except Exception as e:
                self.log.error("停止按键直通失败: %s", e, exc_info=True)
            self._sw_interceptor = None

    def _ime_assist_tick(self):
        """每 100ms：key 模式发布上下文快照；layout 模式按焦点切键盘布局"""
        s = self.config.get("settings", {})
        if not bool(s.get("ime_assist_sw", True)):
            return
        try:
            if (s.get("ime_assist_mode", "key") or "key") == "layout":
                from src.sw_ime_assist import run_cycle
                if run_cycle():
                    # 只在确实发生翻转时记录（最多每 5 秒一条），方便确认助手在工作
                    now = time.monotonic()
                    if now - getattr(self, "_last_assist_log", 0.0) >= 5.0:
                        self._last_assist_log = now
                        self.log.info("SolidWorks 输入法助手: 已自动切换输入法状态")
                return
            inter = getattr(self, "_sw_interceptor", None)
            if inter is None:
                return
            # 重活（进程识别/焦点控件/提权查询）都在这里做，钩子回调只读快照
            from src.sw_key_assist import probe_context
            inter.update(probe_context(s))
        except Exception:
            pass

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
            self.tray.setToolTip(T("CAD鼠标手势"))
            return
        self.tray = QSystemTrayIcon(self._create_tray_icon())
        self.tray.setToolTip(T("CAD鼠标手势"))
        # 不设置 contextMenu：Qt 在 Windows 上对设置了 contextMenu 的托盘，
        # 单击也会自动弹出菜单，还会干扰双击信号的送达（第一次单击弹菜单
        # 抢焦点，第二次单击不再触发 DoubleClick）。改为右键手动弹菜单。
        self.tray.activated.connect(self._on_tray_activated)
        self.tray.show()


    def _on_tray_activated(self, reason):
        """托盘图标激活：左键单击/双击都打开配置，右键弹菜单。

        Windows 下双击信号并不总是可靠送达（第一次单击常被系统当作
        Trigger 处理），所以单击也直接打开配置；右键走 Context 手动弹菜单。
        """
        try:
            if reason == QSystemTrayIcon.Context:
                self._show_tray_menu()
            elif reason in (QSystemTrayIcon.Trigger,
                            QSystemTrayIcon.DoubleClick):
                self._open_config()
        except Exception as e:
            self.log.error("托盘事件处理失败: %s", e, exc_info=True)

    def _show_tray_menu(self):
        """右键托盘：手动弹出托盘菜单（不依赖 Qt 自动 contextMenu）"""
        try:
            menu = getattr(self, "_tray_menu", None)
            if menu is None:
                menu = self._build_tray_menu()
                self._tray_menu = menu
            menu.popup(QCursor.pos())
        except Exception as e:
            self.log.error("弹出托盘菜单失败: %s", e, exc_info=True)

    def _rebuild_tray(self):
        """语言切换后重建托盘菜单文本（保留图标与显示状态）"""
        try:
            self._tray_menu = self._build_tray_menu()
            if hasattr(self, "tray"):
                self.tray.setToolTip(T("CAD鼠标手势"))
        except Exception as e:
            self.log.error("重建托盘菜单失败: %s", e, exc_info=True)

    def _build_tray_menu(self) -> QMenu:
        """构建托盘菜单（当前语言）"""
        profile_names = get_profile_names(self.config)
        profiles = self.config.get("profiles", {})

        menu = QMenu()

        # 当前各 target 生效方案（勾选标记用），与运行时规则一致
        targets = get_target_order(self.config)
        active_by_target = {}
        for tgt in targets:
            p = get_profile_for_window(self.config, tgt)
            if p is not None:
                active_by_target[tgt] = p.get("name", "")

        def add_profile_actions(names, parent_menu=None, target=None):
            tgt_menu = parent_menu or menu
            for name in names:
                act = QAction(profiles[name].get("name", name), tgt_menu)
                act.setCheckable(True)
                act.setChecked(
                    target is not None
                    and active_by_target.get(target) == profiles[name].get("name", name))
                act.triggered.connect(lambda _=False, n=name: self._switch_profile(n))
                tgt_menu.addAction(act)

        # 按卡片顺序分组：AutoCAD / 中望CAD / 自定义应用
        for tgt in targets:
            names = [n for n in profile_names if profiles[n].get("target") == tgt]
            if not names:
                continue
            label = get_target_label(self.config, tgt)
            if tgt in ("autocad", "zwcad"):
                label = T(label)
            sub = menu.addMenu(label)
            add_profile_actions(names, sub, tgt)

        # 未归入任何 target 的方案直接列在根菜单
        other_profiles = [n for n in profile_names
                          if profiles[n].get("target") not in targets]
        add_profile_actions(other_profiles)

        menu.addSeparator()
        act_pause = QAction(T("暂停手势"), menu)
        act_pause.setCheckable(True)
        act_pause.setChecked(bool(
            self.config.get("settings", {}).get("gesture_paused", False)))
        act_pause.setToolTip(T("暂停后 CAD 内长按右键恢复原生菜单，手势不触发"))
        act_pause.triggered.connect(self._toggle_pause)
        menu.addAction(act_pause)
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
            if target:
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

    def _toggle_pause(self, checked: bool):
        """托盘切换"暂停手势"：同步引擎与配置（状态持久化，重启仍生效）"""
        try:
            s = self.config.setdefault("settings", {})
            s["gesture_paused"] = bool(checked)
            engine = getattr(self, "gesture_engine", None)
            if engine is not None:
                engine.set_paused(bool(checked))
            save_config(self.config)
            self._tray_message(
                "CAD鼠标手势",
                T("手势已暂停，长按右键恢复原生菜单") if checked
                else T("手势已恢复"))
            # 语言/状态变化后重建菜单，保证勾选状态与引擎一致
            self._rebuild_tray()
        except Exception as e:
            self.log.error("切换暂停手势失败: %s", e, exc_info=True)

    def _open_config(self):
        """打开配置界面（Qt 版，独立窗口；延迟 import 避免启动加载整个界面链）

        已有窗口且真正可见时复用并强制恢复到前台（含最小化恢复）；
        窗口已关闭/隐藏/几何无效时强制新建，避免复用一个看不见的残留窗口
        导致点击无反应。
        """
        try:
            win = getattr(self, "_config_win", None)
            if win is not None and self._config_win_usable(win):
                self._restore_config_win(win)
                return
            # 窗口不可用（已关闭/隐藏/残留）：关闭并新建
            if win is not None:
                try:
                    win.close()
                    win.deleteLater()
                except Exception:
                    pass
            from src.qt_config_gui import open_config_gui
            self._config_win = open_config_gui(
                on_save=self._reload_config,
                on_check_update=lambda: self._check_update(manual=True))
            try:
                w = getattr(self, "_config_win", None)
                if w is not None:
                    self.log.info("_open_config: 新建窗口 visible=%s geo=%s", w.isVisible(), w.frameGeometry().getRect())
            except Exception:
                pass
        except Exception as e:
            self.log.error("打开配置界面失败: %s", e, exc_info=True)

    @staticmethod
    def _config_win_usable(win) -> bool:
        """配置窗口是否真正可用：Qt 可见 + Win32 已映射 + 几何在屏幕内。

        Qt 的 isVisible() 在窗口未真正映射时仍可能返回 True（如隐藏/残留的
        窗口对象），单看 isVisible 会把"看不见的残留窗口"当成可用，导致点击
        无反应。这里额外校验 Win32 WS_VISIBLE 与几何有效性。
        """
        try:
            if not win.isVisible():
                return False
            # Win32 层必须真的映射（WS_VISIBLE）：Qt 状态可能滞后于实际显示
            try:
                import ctypes
                hwnd = int(win.winId())
                if hwnd and not ctypes.windll.user32.IsWindowVisible(hwnd):
                    return False
            except Exception:
                pass
            g = win.frameGeometry()
            if g.width() <= 0 or g.height() <= 0:
                return False
            from PySide6.QtWidgets import QApplication
            for scr in QApplication.screens():
                if g.intersects(scr.availableGeometry()):
                    return True
            return False
        except Exception:
            return False

    def _restore_config_win(self, win):
        """把已打开的配置窗口恢复到前台：最小化恢复 + 显示 + 置顶激活。

        Windows 下 Qt 的 activateWindow() 在应用处于后台时可能被系统阻止，
        这里再用 Win32 ShowWindow/SetForegroundWindow 兜底，确保从托盘
        点击后窗口真正回到前台（含最小化后恢复）。
        """
        try:
            if win.isMinimized():
                win.setWindowState(win.windowState() & ~Qt.WindowMinimized)
                win.showNormal()
            win.show()
            win.raise_()
            win.activateWindow()
            try:
                import ctypes
                hwnd = int(win.winId())
                if hwnd:
                    user32 = ctypes.windll.user32
                    user32.ShowWindow(hwnd, 9)      # SW_RESTORE
                    user32.SetForegroundWindow(hwnd)
                    # 短暂置顶再取消，确保窗口浮到最上层后恢复普通层级
                    user32.SetWindowPos(hwnd, -1, 0, 0, 0, 0,
                                        0x0001 | 0x0002 | 0x0010)
                    user32.SetWindowPos(hwnd, -2, 0, 0, 0, 0,
                                        0x0001 | 0x0002)
            except Exception:
                pass
            self.log.info("_open_config: 复用窗口 visible=%s minimized=%s",
                          win.isVisible(), win.isMinimized())
        except Exception as e:
            self.log.error("恢复配置窗口失败: %s", e, exc_info=True)


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
            mode = s.get("ui_mode", "light")
            font = s.get("ui_font_scale", 100)
            # 界面模式（含 system 解析后）或字号变化才重建 QSS，其余设置跳过
            if (effective_ui_mode(mode) != current_ui_mode()
                    or font != self._applied_font_scale):
                self._apply_ui_mode(mode)
            # SW 输入法助手开关可能变了：启停轮询定时器
            self._sync_ime_assist_timer()
        except Exception as e:
            self.log.error("重载配置失败: %s", e, exc_info=True)

    # ========== 自动更新 ==========

    def _check_update(self, manual: bool):
        """检查更新（后台线程执行网络请求，结果经事件队列回主线程）

        按运行布局分流（与 GitHub 主流一致）：
        - 安装版（Inno 直装，无 Velopack 布局）→ Releases 查新版 →
          下载 Setup-CADGesture-vX.exe → 静默覆盖安装；
        - 绿色版 / Velopack 布局 → Velopack feed 检查 + delta 更新。
        """
        if manual is False and not self._should_auto_check():
            return
        from src.updater import is_velopack_layout
        s = self.config.get("settings", {})
        url = s.get("update_source_url",
                    "https://github.com/Inonvation/cad-gesture")
        token = s.get("update_token") or None
        self._update_source = (url, token)
        self._update_mode = "velopack" if is_velopack_layout() else "github"
        if self._update_mode == "github":
            threading.Thread(target=self._check_worker_github,
                             args=(url, manual), daemon=True).start()
        else:
            threading.Thread(target=self._check_worker,
                             args=(url, token, manual), daemon=True).start()

    def _check_worker(self, url: str, token: str | None, manual: bool):
        from src.updater import build_manager, check_for_update, UpdateError
        try:
            manager = build_manager(url, token)
            info = check_for_update(manager)
            result = {"ok": True, "info": info, "error": None, "manual": manual}
        except UpdateError as e:
            result = {"ok": False, "info": None, "error": str(e), "manual": manual}
        except Exception as e:
            result = {"ok": False, "info": None,
                      "error": f"检查更新异常: {e}", "manual": manual}
        self.event_queue.put(("update_check_result", result))

    def _check_worker_github(self, url: str, manual: bool):
        """安装版：解析 GitHub Releases HTML 页检查新版本（不限流）"""
        from src.updater import check_for_update_github, UpdateError
        try:
            info = check_for_update_github(__version__, url)
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
        if not s.get("check_update_on_start", False):
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
                        data.get("error") or T("检查更新失败"))
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
            win = getattr(self, "_config_win", None)
            if win is not None:
                try:
                    win.refresh_about_page(self.config)
                except Exception:
                    pass
        except Exception as e:
            self.log.error("记录检查时间失败: %s", e, exc_info=True)

    def _tray_message(self, title: str, msg: str, icon=None, ms: int = 3000):
        try:
            self.tray.showMessage(title, msg, icon or QSystemTrayIcon.Information, ms)
        except Exception:
            pass

    def _show_update_dialog(self, info: dict):
        """有新版本：自定义更新弹窗（说明 + 立即更新/稍后，非模态）"""
        from src.qt_update_dialog import UpdateDialog
        dialog = UpdateDialog()
        self._update_dialog = dialog
        dialog.show_update_info(
            info.get("version", ""), __version__,
            (info.get("notes") or "").strip(),
            on_update=lambda: self._start_update_download(info, dialog),
            on_later=dialog.close)
        dialog.show()

    def _start_update_download(self, info: dict, dialog=None):
        """开始后台下载，弹窗切换到下载进度模式

        - github：下载 Setup-CADGesture-vX.exe 到 %TEMP%，字节进度转百分比
        - velopack：Velopack 自管理 packages，百分比回调
        """
        self._update_cancel = False
        self._update_info = info
        mode = info.get("mode") or getattr(self, "_update_mode", "github")
        self._update_mode = mode
        if mode == "github":
            dest = os.path.join(tempfile.gettempdir(), "CADGesture-Setup.exe")
            try:
                os.remove(dest)
            except OSError:
                pass
            self._update_dest = dest
        if dialog is None:
            from src.qt_update_dialog import UpdateDialog
            dialog = UpdateDialog()
        self._update_dialog = dialog
        dialog.show_download(
            info.get("version", ""),
            on_cancel=lambda: setattr(self, "_update_cancel", True))
        dialog.show()
        threading.Thread(target=self._download_worker, args=(info,),
                         daemon=True).start()

    def _download_worker(self, info: dict):
        """后台下载线程：按 mode 走 GitHub 直链或 Velopack"""
        from src.updater import UpdateError
        mode = info.get("mode") or getattr(self, "_update_mode", "github")
        ok, reason = False, ""
        try:
            if mode == "github":
                from src.updater import download_installer
                dest = getattr(self, "_update_dest", None)
                if not dest:
                    raise UpdateError("缺少下载目标路径")
                ok = download_installer(
                    info.get("download_url", ""), dest,
                    info.get("size") or 0,
                    progress_cb=self._download_progress_bytes)
                if not ok:
                    reason = "下载失败"
            else:
                from src.updater import build_manager, download_update
                url, token = self._update_source or (None, None)
                manager = build_manager(url or "", token)
                download_update(manager, info, progress_cb=self._download_progress)
                ok, reason = True, ""
        except UpdateError as e:
            ok, reason = False, str(e)
        except Exception as e:
            self.log.error("下载更新异常: %s", e, exc_info=True)
            ok, reason = False, str(e)
        self.event_queue.put(("update_download_done", (ok, reason)))

    def _download_progress_bytes(self, downloaded: int, total: int):
        """安装版下载回调：取消则抛异常中断；字节进度转百分比推 UI"""
        if self._update_cancel:
            from src.updater import UpdateCancelled
            raise UpdateCancelled("下载被取消")
        if total > 0:
            pct = int(downloaded * 100 / total)
            self.event_queue.put(("update_progress_pct", min(pct, 100)))
        else:
            # 未知总大小：按已下载 MB 粗略推进（保持进度条在动）
            self.event_queue.put(("update_progress_pct",
                                  min(99, int(downloaded / (10 * 1024 * 1024)))))

    def _download_progress(self, pct: int):
        """Velopack 下载进度回调（其内部线程调用，约每 5%，实参 0-100）。"""
        if self._update_cancel:
            return
        self.event_queue.put(("update_progress_pct", int(pct)))

    def _on_update_progress(self, data):
        try:
            pct = int(data)
            dialog = getattr(self, "_update_dialog", None)
            if dialog is None:
                return
            dialog.set_progress_percent(pct)
        except Exception as e:
            self.log.error("更新进度更新失败: %s", e, exc_info=True)

    def _on_update_download_done(self, data: tuple):
        """下载完成：切到"开始安装"确认，用户确认后应用更新并退出。"""
        ok, reason = data
        dialog = getattr(self, "_update_dialog", None)
        if self._update_cancel:
            self._update_dialog = None
            try:
                if dialog is not None:
                    dialog.close()
            except Exception:
                pass
            self._tray_message("CAD鼠标手势", T("更新已取消"))
            return
        if not ok:
            self._update_dialog = None
            try:
                if dialog is not None:
                    dialog.close()
            except Exception:
                pass
            try:
                QMessageBox.warning(
                    None, T("更新失败"),
                    T("下载失败，请检查网络后重试") +
                    (("\n" + reason) if reason and reason != "下载失败" else ""))
            except Exception:
                pass
            return
        self._show_confirm_install(dialog)
        self.log.info("更新包已就绪，等待用户确认后应用")

    def _show_confirm_install(self, dialog):
        """切到"开始安装"确认模式：点「开始安装」→ 应用更新并退出主进程。"""
        try:
            dialog.show_installing(
                on_done=self._start_and_finish)
        except Exception as e:
            self.log.error("切换安装确认模式失败: %s", e, exc_info=True)
            self._start_and_finish()
            return
        dialog.show()

    def _start_and_finish(self):
        """用户点「开始安装」：按 mode 应用更新并退出主进程。

        - github：静默启动 Inno 安装包 → 写更新标记 → _quit()（安装器接管）
        - velopack：拉起 Update.exe → _quit()（原子替换 + 重启）
        """
        info = self._update_info
        if not info:
            self.log.error("开始安装但缺少更新信息，中止")
            return
        mode = info.get("mode") or getattr(self, "_update_mode", "github")
        dialog = getattr(self, "_update_dialog", None)
        self._update_dialog = None
        try:
            if dialog is not None:
                dialog.close()
        except Exception:
            pass

        if mode == "github":
            installer_path = getattr(self, "_update_dest", None)
            if not installer_path or not os.path.exists(installer_path):
                self.log.error("开始安装但安装包不存在，中止: %s", installer_path)
                return
            from src.updater import run_installer
            try:
                ok, reason = run_installer(installer_path)
            except Exception as e:
                self.log.error("启动安装程序异常: %s", e, exc_info=True)
                ok, reason = False, str(e)
            if not ok:
                try:
                    QMessageBox.warning(
                        None, T("更新失败"),
                        T("启动安装程序失败，请手动运行更新包") +
                        "\n\n" + installer_path +
                        (("\n" + reason) if reason else ""))
                except Exception:
                    pass
                return
            self._write_update_success_marker(installer_path)
            self.log.info("安装器已启动，退出当前实例以完成更新")
            self._quit()
            return

        from src.updater import build_manager, apply_update
        url, token = self._update_source or (None, None)
        try:
            manager = build_manager(url or "", token)
            apply_update(manager, info, silent=True, restart=True)
        except Exception as e:
            self.log.error("启动更新程序异常: %s", e, exc_info=True)
            try:
                QMessageBox.warning(
                    None, T("更新失败"),
                    T("启动更新程序失败，请稍后重试或手动下载最新安装包。") +
                    (("\n" + str(e)) if str(e) else ""))
            except Exception:
                pass
            return
        self.log.info("Update.exe 已接管，退出当前实例以完成更新")
        self._quit()

    def _write_update_success_marker(self, installer_path: str):
        """记录"本次退出是为安装更新"，供新版启动时弹成功确认。"""
        try:
            if not os.path.exists(installer_path):
                return
            with open(_UPDATE_SUCCESS_MARKER, "w", encoding="utf-8") as f:
                f.write(__version__)
        except Exception as e:
            self.log.error("写入更新标记失败: %s", e, exc_info=True)

    def _show_update_success_if_any(self):
        """启动后检测"本次启动由更新而来"，有则弹窗确认已更新。

        两个来源：
        1. Velopack 时代（主）：on_restarted 钩子置位的环境变量 _RESTART_FLAG，
           更新成功重启后的首次启动必触发，直接弹"已更新到 v{当前版本}"；
        2. Inno 时代遗留（兼容）：%TEMP% 更新标记，供老用户经桥接升级后
           首次启动消费一次（标记语义 = 期望版本，见常量注释）。

        比托盘气泡可靠（Windows 可能屏蔽气泡），且只有走更新流程才提示。
        """
        try:
            # 来源 1：Velopack on_restarted 标志（先消费再弹窗，防重复）
            if os.environ.pop(_RESTART_FLAG, None):
                QMessageBox.information(
                    None, T("软件更新"),
                    T("已更新到 v{ver}，当前已运行新版本。")
                    .format(ver=__version__))
                return
            # 来源 2：Inno 桥接期遗留标记（兼容逻辑，可随大版本退役）
            if not os.path.exists(_UPDATE_SUCCESS_MARKER):
                return
            try:
                with open(_UPDATE_SUCCESS_MARKER, "r", encoding="utf-8") as f:
                    marker_ver = (f.read() or "").strip()
            except Exception:
                marker_ver = ""
            # 先删标记，再弹窗：即使用户长时间不点，下次启动也不会重复提示
            try:
                os.remove(_UPDATE_SUCCESS_MARKER)
            except OSError:
                pass
            if not marker_ver:
                return
            from src.updater import compare_versions
            if compare_versions(__version__, marker_ver) >= 0:
                QMessageBox.information(
                    None, T("软件更新"),
                    T("已更新到 v{ver}，当前已运行新版本。")
                    .format(ver=__version__))
            else:
                QMessageBox.warning(
                    None, T("更新失败"),
                    T("上次自动更新未完成：目标 v{target}，当前仍为 v{cur}。"
                      "请重新检查更新，或手动下载安装包。")
                    .format(target=marker_ver, cur=__version__))
        except Exception as e:
            self.log.error("更新成功提示失败: %s", e, exc_info=True)

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
            # 键盘钩子必须显式卸载：进程退出虽会回收，但先卸干净更稳妥
            inter = getattr(self, "_sw_interceptor", None)
            if inter is not None:
                inter.stop()
                self._sw_interceptor = None
        except Exception as e:
            self.log.error("停止 SolidWorks 按键直通失败: %s", e, exc_info=True)
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
