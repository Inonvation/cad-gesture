"""主应用模块 - Qt6 版（PySide6）"""

import os
import sys
import math
import queue
import threading

from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import QApplication, QMenu, QSystemTrayIcon

from src.config_manager import (
    load_config, save_config, get_active_profile,
    get_profile_for_window, get_profile_names, set_active_profile, CONFIG_FILE
)
from src.gesture_engine import GestureEngine
from src.qt_radial_menu import QRadialMenu
from src.qt_config_gui import open_config_gui
from src.command_executor import execute_with_cancel
from src.single_instance import is_exit_requested
from src.logger import get_logger


class CADGestureApp:
    """CAD鼠标手势应用主类（Qt 版）"""

    def __init__(self):
        self._is_first_run = not os.path.exists(CONFIG_FILE)
        self.config = load_config()
        self.log = get_logger()

        self.app = QApplication.instance()
        if self.app is None:
            self.app = QApplication(sys.argv)
        self.app.setQuitOnLastWindowClosed(False)

        # 圆盘菜单（Qt 透明悬浮窗）
        self.menu = QRadialMenu(self.config)
        self.profile = get_active_profile(self.config)

        self.event_queue = queue.Queue()
        self.gesture_engine = GestureEngine(
            config=self.config,
            on_gesture=self._queue_gesture,
            on_menu_show=self._queue_show,
            on_menu_hide=self._queue_hide,
            on_extension_hint=self._queue_extension_hint
        )
        # 菜单被 Esc/左键取消时复位引擎手势状态，阻止松键补发命令
        self.menu._on_cancel = self.gesture_engine.cancel_gesture

        self._menu_center_x = 0
        self._menu_center_y = 0
        self._exit_poll_count = 0
        self._quitting = False

        self._setup_tray()

        # 主循环定时器（菜单可见时 16ms 高频跟踪，不可见时 100ms 低频空转）
        self._timer = QTimer()
        self._timer.timeout.connect(self._process_queue)
        self._timer.start(16)

    # ========== 事件入队 ==========

    def _queue_gesture(self, sector: int, ring_type: str, window_type: str):
        self.event_queue.put(("gesture", (sector, ring_type, window_type)))

    def _queue_show(self, x: int, y: int, window_type: str):
        self.event_queue.put(("show", (x, y, window_type)))

    def _queue_hide(self):
        self.event_queue.put(("hide", None))

    def _queue_extension_hint(self, is_in_zone: bool):
        self.event_queue.put(("extension_hint", is_in_zone))

    # ========== 主循环 ==========

    def _process_queue(self):
        """处理事件队列（QTimer 驱动）"""
        try:
            try:
                while True:
                    event_type, data = self.event_queue.get_nowait()
                    try:
                        if event_type == "show":
                            x, y, window_type = data
                            self._menu_center_x, self._menu_center_y = x, y
                            self.profile = get_profile_for_window(self.config, window_type)
                            if self.profile is None:
                                self.profile = get_active_profile(self.config)
                            self.menu.show(x, y, self.profile)
                        elif event_type == "hide":
                            self.menu.hide()
                        elif event_type == "extension_hint":
                            self.menu.set_extension_hint(data)
                        elif event_type == "gesture":
                            try:
                                sector, ring_type, window_type = data
                                profile = get_profile_for_window(self.config, window_type)
                                if profile is None:
                                    profile = self.profile
                                if ring_type == "extension":
                                    sectors_key = "extension_sectors"
                                elif ring_type == "outer":
                                    sectors_key = "outer_sectors"
                                else:
                                    sectors_key = "sectors"
                                sector_cfg = profile.get(sectors_key, {}).get(str(sector), {})
                                if ring_type in ("outer", "extension") and not sector_cfg:
                                    sector_cfg = profile.get("sectors", {}).get(str(sector), {})
                                key = sector_cfg.get("key", "")
                                desc = sector_cfg.get("description", "")
                                target = profile.get("target", "autocad")
                                if key:
                                    execute_with_cancel(key, desc, target, menu_was_shown=True)
                            except Exception as e:
                                self.log.error("命令执行错误: %s", e, exc_info=True)
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
            if self._exit_poll_count % 32 == 0:
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
                delay = 16 if self.menu.is_visible() else 100
                self._timer.setInterval(delay)

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
        profile_names = get_profile_names(self.config)
        autocad_profiles = [n for n in profile_names
                            if self.config["profiles"][n].get("target") == "autocad"]
        zwcad_profiles = [n for n in profile_names
                          if self.config["profiles"][n].get("target") == "zwcad"]
        other_profiles = [n for n in profile_names
                          if self.config["profiles"][n].get("target") not in ("autocad", "zwcad")]

        menu = QMenu()

        def add_profile_actions(names, parent_menu=None):
            target = parent_menu or menu
            for name in names:
                act = QAction(self.config["profiles"][name].get("name", name), target)
                act.triggered.connect(lambda _=False, n=name: self._switch_profile(n))
                target.addAction(act)

        if autocad_profiles:
            sub = menu.addMenu("AutoCAD")
            add_profile_actions(autocad_profiles, sub)
        if zwcad_profiles:
            sub = menu.addMenu("中望CAD")
            add_profile_actions(zwcad_profiles, sub)
        add_profile_actions(other_profiles)

        menu.addSeparator()
        act_cfg = QAction("配置", menu)
        act_cfg.triggered.connect(lambda _=False: self._open_config())
        menu.addAction(act_cfg)
        act_exit = QAction("退出", menu)
        act_exit.triggered.connect(lambda _=False: self._quit())
        menu.addAction(act_exit)

        self._tray_menu = menu  # 保持引用防 GC

        self.tray = QSystemTrayIcon(self._create_tray_icon())
        self.tray.setToolTip("CAD鼠标手势")
        self.tray.setContextMenu(menu)
        self.tray.show()

    def _switch_profile(self, profile_name: str):
        """切换方案（Qt 信号槽运行在主线程，无需跨线程投递）"""
        try:
            set_active_profile(self.config, profile_name)
            self.profile = get_active_profile(self.config)
            self.gesture_engine.update_config(self.config)
            self.menu.update_config(self.config)
            display = self.config["profiles"].get(profile_name, {}).get("name", profile_name)
            try:
                self.tray.showMessage("CAD鼠标手势", f"已切换到: {display}",
                                      QSystemTrayIcon.Information, 2000)
            except Exception:
                pass
        except Exception as e:
            self.log.error("切换方案失败: %s", e, exc_info=True)

    def _open_config(self):
        """打开配置界面（Qt 版，独立窗口）"""
        try:
            self._config_win = open_config_gui(on_save=self._reload_config)
        except Exception as e:
            self.log.error("打开配置界面失败: %s", e, exc_info=True)

    def _reload_config(self):
        """配置保存后重载（主线程，Qt 信号槽安全）"""
        try:
            self.config = load_config()
            self.profile = get_active_profile(self.config)
            self.gesture_engine.update_config(self.config)
            self.menu.update_config(self.config)
        except Exception as e:
            self.log.error("重载配置失败: %s", e, exc_info=True)

    # ========== 退出 ==========

    def _quit(self):
        if self._quitting:
            return
        self._quitting = True
        try:
            self.gesture_engine.stop()
        except Exception as e:
            self.log.error("停止手势引擎失败: %s", e, exc_info=True)
        try:
            self.menu.destroy()
        except Exception as e:
            self.log.error("销毁菜单窗口失败: %s", e, exc_info=True)
        try:
            self.tray.hide()
        except Exception as e:
            self.log.error("隐藏托盘失败: %s", e, exc_info=True)
        self.app.quit()

    def run(self):
        """运行应用"""
        if not self.gesture_engine.start():
            self.log.error("鼠标钩子安装失败，手势将不可用")
            try:
                self.tray.showMessage("CAD鼠标手势", "鼠标钩子安装失败，手势将不可用",
                                      QSystemTrayIcon.Warning, 3000)
            except Exception:
                pass
        # 首次运行或配置了"启动时打开此界面"则自动打开配置
        if self._is_first_run or self.config.get("settings", {}).get("open_config_on_start", False):
            QTimer.singleShot(500, self._open_config)
        sys.exit(self.app.exec())
