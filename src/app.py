"""主应用模块 - 应用程序核心逻辑和系统托盘"""

import os
import threading
import queue
import tkinter as tk
import pyautogui
from PIL import Image, ImageDraw
from pystray import MenuItem, Icon, Menu
import customtkinter as ctk

from src.config_manager import (
    load_config, save_config, get_active_profile,
    get_profile_for_window, get_profile_names, set_active_profile, CONFIG_FILE
)
from src.gesture_engine import GestureEngine
from src.radial_menu import RadialMenu
from src.command_executor import execute_with_cancel
from src.config_gui import open_config_gui
from src.single_instance import is_exit_requested
from src.logger import get_logger


class CADGestureApp:
    """CAD鼠标手势应用主类"""

    def __init__(self):
        self._is_first_run = not os.path.exists(CONFIG_FILE)
        self.config = load_config()
        self.log = get_logger()
        self.root = ctk.CTk()
        self.root.withdraw()
        self.root.attributes("-topmost", True)

        self.menu = RadialMenu(self.config, parent=self.root)
        self.profile = get_active_profile(self.config)

        self.event_queue = queue.Queue()
        self.gesture_engine = GestureEngine(
            config=self.config,
            on_gesture=self._queue_gesture,
            on_menu_show=self._queue_show,
            on_menu_hide=self._queue_hide,
            on_extension_hint=self._queue_extension_hint
        )

        self._menu_center_x = 0
        self._menu_center_y = 0
        self._exit_poll_count = 0

        self._setup_tray()
        self._process_queue()

    def _queue_gesture(self, sector: int, ring_type: str, window_type: str):
        """将手势事件放入队列"""
        self.event_queue.put(("gesture", (sector, ring_type, window_type)))

    def _queue_show(self, x: int, y: int, window_type: str):
        """将显示菜单事件放入队列"""
        self.event_queue.put(("show", (x, y, window_type)))

    def _queue_hide(self):
        """将隐藏菜单事件放入队列"""
        self.event_queue.put(("hide", None))

    def _queue_extension_hint(self, is_in_zone: bool):
        """将扩展圈提示事件放入队列"""
        self.event_queue.put(("extension_hint", is_in_zone))

    def _process_queue(self):
        """处理事件队列（在主线程中执行）"""
        try:
            while True:
                event_type, data = self.event_queue.get_nowait()
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
                        self.log.error("命令执行错误: %s", e)
        except queue.Empty:
            pass

        # 仅在菜单可见时更新鼠标位置
        if self.menu.is_visible():
            pos = pyautogui.position()
            self.menu.update_highlight(pos[0], pos[1])

        # 低频检查：被新实例请求覆盖退出时优雅退出（卸载钩子、停托盘）
        self._exit_poll_count += 1
        if self._exit_poll_count % 32 == 0 and is_exit_requested():
            self.log.info("收到新实例覆盖请求，正在退出当前实例")
            self._quit()
            return
        self.root.after(16, self._process_queue)

    def _create_tray_icon(self) -> Image.Image:
        """创建托盘图标 (8 方向径向圆盘)"""
        import math
        size = 64
        img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
        draw = ImageDraw.Draw(img)
        cx, cy = size / 2, size / 2
        margin = 4
        r = size / 2 - margin

        # 外圈
        draw.ellipse(
            [cx - r, cy - r, cx + r, cy + r],
            fill="#2b5278", outline="#0078D4", width=2,
        )
        # 8 方向指示点
        for i in range(8):
            angle = -math.pi / 2 + i * math.pi / 4
            mid_angle = angle + math.pi / 8
            mid_r = r * 0.62
            mx = cx + mid_r * math.cos(mid_angle)
            my = cy + mid_r * math.sin(mid_angle)
            dot_r = 3
            color = "#0078D4" if i % 2 == 0 else "#4a90d9"
            draw.ellipse(
                [mx - dot_r, my - dot_r, mx + dot_r, my + dot_r],
                fill=color,
            )
        # 中心点
        draw.ellipse([cx - 3, cy - 3, cx + 3, cy + 3], fill="#ffffff")
        return img

    def _setup_tray(self):
        """设置系统托盘"""
        profile_names = get_profile_names(self.config)
        
        # 按 CAD 软件分组
        autocad_profiles = [n for n in profile_names 
                           if self.config["profiles"][n].get("target") == "autocad"]
        zwcad_profiles = [n for n in profile_names 
                         if self.config["profiles"][n].get("target") == "zwcad"]
        other_profiles = [n for n in profile_names 
                         if self.config["profiles"][n].get("target") not in ("autocad", "zwcad")]

        menu_items = []
        
        if autocad_profiles:
            autocad_menu = []
            for name in autocad_profiles:
                display = self.config["profiles"][name].get("name", name)
                autocad_menu.append(
                    MenuItem(
                        display,
                        lambda _, n=name: self._switch_profile(n),
                        checked=lambda _, n=name: self.config.get("settings", {}).get("active_profile") == n
                    )
                )
            menu_items.append(MenuItem("AutoCAD", Menu(*autocad_menu)))

        if zwcad_profiles:
            zwcad_menu = []
            for name in zwcad_profiles:
                display = self.config["profiles"][name].get("name", name)
                zwcad_menu.append(
                    MenuItem(
                        display,
                        lambda _, n=name: self._switch_profile(n),
                        checked=lambda _, n=name: self.config.get("settings", {}).get("active_profile") == n
                    )
                )
            menu_items.append(MenuItem("中望CAD", Menu(*zwcad_menu)))

        for name in other_profiles:
            menu_items.append(
                MenuItem(
                    name,
                    lambda _, n=name: self._switch_profile(n),
                    checked=lambda _, n=name: self.config.get("settings", {}).get("active_profile") == n
                )
            )

        menu_items.append(MenuItem("配置", self._open_config))
        menu_items.append(MenuItem("退出", self._quit))

        self.tray_icon = Icon(
            "CAD Gesture",
            self._create_tray_icon(),
            "CAD鼠标手势",
            Menu(*menu_items)
        )
        threading.Thread(target=self.tray_icon.run, daemon=True).start()

    def _switch_profile(self, profile_name: str):
        """切换Profile"""
        set_active_profile(self.config, profile_name)
        self.profile = get_active_profile(self.config)
        self.gesture_engine.update_config(self.config)
        self.menu.update_config(self.config)
        display = self.config["profiles"].get(profile_name, {}).get("name", profile_name)
        self.tray_icon.notify(f"已切换到: {display}")

    def _open_config(self):
        """打开配置界面（在主线程挂载，避免多线程双 Tk 冲突导致卡死）"""
        def on_config_save():
            # 通过 root.after 将配置重载投递到主线程（tkinter 线程安全）
            def _reload():
                self.config = load_config()
                self.profile = get_active_profile(self.config)
                self.gesture_engine.update_config(self.config)
                self.menu.update_config(self.config)
            self.root.after(0, _reload)

        # 投递到主线程，以 CTkToplevel 形式打开（非阻塞）
        self.root.after(0, lambda: open_config_gui(
            on_save=on_config_save, master=self.root))

    def _quit(self):
        """退出应用"""
        self.gesture_engine.stop()
        self.menu.destroy()
        self.tray_icon.stop()
        self.root.quit()

    def run(self):
        """运行应用"""
        self.gesture_engine.start()
        # 首次运行或配置了"启动时打开此界面"则自动打开配置
        if self._is_first_run or self.config.get("settings", {}).get("open_config_on_start", False):
            self.root.after(500, self._open_config)
        self.root.mainloop()
