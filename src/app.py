"""主应用模块 - Qt6 版（PySide6）"""

import os
import sys
import math
import queue
import threading
import tempfile
from datetime import datetime

from PySide6.QtCore import Qt, QPointF, QTimer
from PySide6.QtGui import QAction, QColor, QCursor, QIcon, QPainter, QPen, QPixmap
from PySide6.QtWidgets import (QApplication, QMenu, QMessageBox,
                               QProgressDialog, QSystemTrayIcon)

from src.config_manager import (
    load_config, save_config, get_active_profile,
    get_profile_for_window, get_profile_names, set_active_profile,
    get_config_path
)
from src.gesture_engine import GestureEngine
from src.qt_radial_menu import QRadialMenu
from src.qt_config_gui import open_config_gui
from src.command_executor import execute_with_cancel
from src.single_instance import is_exit_requested
from src.logger import get_logger
from src.updater import (check_for_update, download_update, run_installer,
                         UpdateCancelled, UpdateError)
from src.version import __version__

_CHECK_INTERVAL_SEC = 24 * 3600  # 启动自动检查的最小间隔
_UPDATE_NOTES_MAX = 800


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

        # 更新流程状态
        self._update_info = None
        self._update_cancel = False
        self._update_progress = None

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
        act_update = QAction("检查更新", menu)
        act_update.triggered.connect(lambda _=False: self._check_update(manual=True))
        menu.addAction(act_update)
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
            self._config_win = open_config_gui(
                on_save=self._reload_config,
                on_check_update=lambda: self._check_update(manual=True))
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
                        None, "检查更新", f"已是最新版本（v{__version__}）")
                except Exception as e:
                    self.log.error("提示弹窗失败: %s", e, exc_info=True)
        else:
            if manual:
                try:
                    QMessageBox.warning(
                        None, "检查更新",
                        data.get("error", "检查更新失败") +
                        "\n\n提示：GitHub 接口有限频（约 60 次/小时），如提示 403 请稍后再试")
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
        box.setWindowTitle("发现新版本")
        box.setText(f"CAD鼠标手势 v{info.get('version', '')} 已发布"
                    f"（当前 v{__version__}）")
        notes = (info.get("notes") or "").strip() or "（无更新说明）"
        if len(notes) > _UPDATE_NOTES_MAX:
            notes = notes[:_UPDATE_NOTES_MAX] + "..."
        box.setInformativeText(notes)
        btn_now = box.addButton("立即更新", QMessageBox.AcceptRole)
        box.addButton("稍后再说", QMessageBox.RejectRole)
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
            f"正在下载 v{info.get('version', '')} 更新包...", "取消", 0,
            100 if total > 0 else 0)
        self._update_progress.setWindowTitle("CAD鼠标手势 - 更新")
        self._update_progress.setWindowModality(Qt.WindowModal)
        self._update_progress.setMinimumDuration(0)
        self._update_progress.canceled.connect(
            lambda: setattr(self, "_update_cancel", True))
        self._update_progress.show()
        threading.Thread(target=self._download_worker, args=(info, dest),
                         daemon=True).start()

    def _download_worker(self, info: dict, dest: str):
        ok = download_update(info.get("download_url", ""), dest,
                             info.get("size") or 0,
                             progress_cb=self._download_progress)
        self.event_queue.put(("update_download_done", (ok, dest)))

    def _download_progress(self, downloaded: int, total: int):
        """下载线程回调：检查取消 + 进度入队"""
        if self._update_cancel:
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
                    f"正在下载更新包... {downloaded // 1024} KB / "
                    f"{total // 1024} KB")
            else:
                self._update_progress.setValue(0)
        except Exception as e:
            self.log.error("更新进度更新失败: %s", e, exc_info=True)

    def _on_update_download_done(self, data: tuple):
        """下载完成：确认后静默安装并退出"""
        ok, dest = data
        if self._update_progress is not None:
            self._update_progress.close()
            self._update_progress = None
        if self._update_cancel:
            self._tray_message("CAD鼠标手势", "更新已取消")
            return
        if not ok:
            self._tray_message("CAD鼠标手势", "下载失败，请检查网络后重试",
                               QSystemTrayIcon.Warning)
            return
        box = QMessageBox()
        box.setIcon(QMessageBox.Question)
        box.setWindowTitle("更新就绪")
        box.setText("更新包已下载完成。")
        box.setInformativeText("将退出程序并自动完成更新，更新完成后会重新启动。")
        btn_now = box.addButton("立即更新", QMessageBox.AcceptRole)
        box.addButton("取消", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is not btn_now:
            self._tray_message("CAD鼠标手势", "已取消更新")
            return
        if not run_installer(dest):
            self._tray_message("CAD鼠标手势", "启动安装程序失败，请手动运行更新包",
                               QSystemTrayIcon.Warning)
            return
        self.log.info("更新流程启动，即将退出当前实例")
        self._quit()

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
        # 启动后延迟自动检查更新（后台线程，不阻塞启动；24h 内不重复）
        QTimer.singleShot(8000, lambda: self._check_update(manual=False))
        sys.exit(self.app.exec())
