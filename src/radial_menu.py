"""圆盘菜单模块 — Fluent 风格三层径向圆盘"""

import math
import tkinter as tk
from typing import Dict, Any, Optional

from src.gesture_engine import calc_sector
from src.theme import get_menu_theme, MenuTheme
from src.renderer import draw_ring, ring_state_normal


class RadialMenu:
    """径向圆盘菜单——Fluent 风格三层扇形选择面板"""

    def __init__(self, config: dict, parent=None):
        self.config = config
        self._parent = parent
        self._root: Optional[tk.Toplevel] = None
        self._canvas: Optional[tk.Canvas] = None
        self._visible: bool = False
        self._center_x: int = 0
        self._center_y: int = 0
        self._highlighted_sector: int = -1
        self._highlighted_outer: bool = False
        self._in_extension_zone: bool = False
        self._profile: Optional[Dict[str, Any]] = None
        self._highlight_throttle_id: Optional[str] = None
        self._theme: MenuTheme = get_menu_theme(
            config.get("settings", {}).get("menu_theme", "azure"))

    def _ensure_window(self):
        if self._root is not None:
            return
        self._root = tk.Toplevel(self._parent)
        self._root.overrideredirect(True)
        self._root.attributes("-topmost", True)
        self._root.attributes("-transparentcolor", self._theme.menu_bg)
        self._root.configure(bg=self._theme.menu_bg)
        self._root.withdraw()

        # 窗口覆盖到扩展圈判定范围（第三圈区域为透明，只显示两圈），
        # 保证鼠标拖入第三圈时事件被本窗口吸收，CAD 无感知
        self._size = self.ext_ring_radius * 2 + 120
        self._center = self._size // 2
        self._canvas = tk.Canvas(
            self._root, width=self._size, height=self._size,
            bg=self._theme.menu_bg, highlightthickness=0)
        self._canvas.pack()
        self._root.bind("<Escape>", lambda e: self.hide())
        self._root.bind("<Button-1>", lambda e: self.hide())
        self._root.focus_set()

    @property
    def ring_radius(self) -> int:
        return self.config.get("settings", {}).get("ring_radius", 100)

    @property
    def outer_ring_radius(self) -> int:
        return self.config.get("settings", {}).get("outer_ring_radius", 180)

    @property
    def ext_ring_radius(self) -> int:
        return self.config.get("settings", {}).get("ext_ring_radius", 240)

    @property
    def sector_count(self) -> int:
        return self.config.get("settings", {}).get("sector_count", 8)

    @property
    def dead_zone(self) -> int:
        return self.config.get("settings", {}).get("dead_zone_radius", 30)

    def show(self, x: int, y: int, profile: Dict[str, Any]):
        self._ensure_window()
        self._profile = profile
        self._center_x, self._center_y = x, y
        self._highlighted_sector = -1
        self._highlighted_outer = False
        self._in_extension_zone = False
        off = self._size // 2
        self._root.geometry(f"{self._size}x{self._size}+{x - off}+{y - off}")
        self._draw()
        self._root.attributes("-alpha", 0.0)
        self._root.deiconify()
        self._visible = True
        self._fade_in(0)

    def _fade_in(self, step: int):
        """淡入动画（加速呼出）"""
        if not self._visible:
            return
        alpha = min(step / 7, 1.0)
        self._root.attributes("-alpha", alpha)
        if step < 7:
            self._root.after(12, lambda: self._fade_in(step + 1))

    def hide(self):
        if self._root and self._visible:
            if self._highlight_throttle_id:
                self._root.after_cancel(self._highlight_throttle_id)
                self._highlight_throttle_id = None
            self._root.withdraw()
            self._visible = False

    def is_visible(self) -> bool:
        return self._visible

    def update_highlight(self, mouse_x: int, mouse_y: int):
        if not self._visible or self._canvas is None:
            return
        dx, dy = mouse_x - self._center_x, mouse_y - self._center_y
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < self.dead_zone:
            new_sec = -1
            new_outer = False
            new_ext = False
        else:
            new_sec = calc_sector(dx, dy, self.sector_count)
            new_ext = dist > self.outer_ring_radius
            if new_ext:
                new_outer = False
            else:
                new_outer = dist > self.ring_radius

        if (new_sec != self._highlighted_sector or
            new_outer != self._highlighted_outer or
            new_ext != self._in_extension_zone):
            self._highlighted_sector = new_sec
            self._highlighted_outer = new_outer
            self._in_extension_zone = new_ext
            if self._highlight_throttle_id is None:
                def apply():
                    self._highlight_throttle_id = None
                    self._draw()
                self._highlight_throttle_id = self._root.after(50, apply)

    def set_extension_hint(self, is_in_zone: bool):
        if is_in_zone != self._in_extension_zone:
            self._in_extension_zone = is_in_zone
            if self._highlight_throttle_id is None:
                def apply():
                    self._highlight_throttle_id = None
                    self._draw()
                self._highlight_throttle_id = self._root.after(50, apply)

    def _draw(self):
        if self._canvas is None or self._profile is None:
            return
        self._canvas.delete("all")
        t = self._theme
        cx = cy = self._center
        inner_r = self.ring_radius
        outer_r = self.outer_ring_radius
        ext_r = self.ext_ring_radius
        dead_r = self.dead_zone
        n = self.sector_count

        # 底座阴影（扩展圈大小）
        self._canvas.create_oval(
            cx - ext_r - 6, cy - ext_r - 6,
            cx + ext_r + 6, cy + ext_r + 6,
            fill="#0b0d11", outline="#1a2029", width=1)

        # 扩展圈（第三圈）
        draw_ring(self._canvas, cx, cy, outer_r, ext_r, n,
                  self._profile.get("extension_sectors", {}),
                  lambda i, cfg: ring_state_normal(
                      t.extension, bool(cfg.get("label")),
                      i == self._highlighted_sector and self._in_extension_zone),
                  label_offset=0.5)

        # 外层（第二圈）
        draw_ring(self._canvas, cx, cy, inner_r, outer_r, n,
                  self._profile.get("outer_sectors", {}),
                  lambda i, cfg: ring_state_normal(
                      t.outer, bool(cfg.get("label")),
                      i == self._highlighted_sector and self._highlighted_outer),
                  label_offset=0.5)

        # 内层（第一圈）
        draw_ring(self._canvas, cx, cy, dead_r, inner_r, n,
                  self._profile.get("sectors", {}),
                  lambda i, cfg: ring_state_normal(
                      t.inner, bool(cfg.get("label")),
                      i == self._highlighted_sector and not self._highlighted_outer and not self._in_extension_zone),
                  label_offset=0.5)

        # 中心死区
        self._canvas.create_oval(
            cx - dead_r, cy - dead_r, cx + dead_r, cy + dead_r,
            fill=t.dead_zone, outline=t.dead_zone_outline, width=1)
        self._canvas.create_oval(
            cx - dead_r - 3, cy - dead_r - 3,
            cx + dead_r + 3, cy + dead_r + 3,
            outline=t.dead_zone_outline, width=1)

        # 中心描述文字（鼠标拖出第二圈边界时显示第三圈扩展命令）
        center_font = ("Microsoft YaHei", 10, "bold")
        if self._in_extension_zone and self._highlighted_sector >= 0:
            cfg = self._profile.get("extension_sectors", {}).get(
                str(self._highlighted_sector), {})
            label = cfg.get("label", "")
            desc = cfg.get("description", "")
            text = f"扩展 {label}\n{desc}" if label and desc else f"扩展 {desc or label}"
            self._canvas.create_text(
                cx, cy, text=text,
                fill=t.extension.highlight, font=center_font)
        elif self._highlighted_sector >= 0:
            if self._highlighted_outer:
                cfg = self._profile.get("outer_sectors", {}).get(
                    str(self._highlighted_sector), {})
            else:
                cfg = self._profile.get("sectors", {}).get(
                    str(self._highlighted_sector), {})
            if self._highlighted_outer and not cfg:
                cfg = self._profile.get("sectors", {}).get(
                    str(self._highlighted_sector), {})
            desc = cfg.get("description", "")
            label = cfg.get("label", "")
            text = f"{label}\n{desc}" if label and desc else (desc or label)
            self._canvas.create_text(
                cx, cy, text=text,
                fill=t.center_text, font=center_font)

    def update_config(self, config: dict):
        self.config = config
        self._theme = get_menu_theme(
            config.get("settings", {}).get("menu_theme", "azure"))

    def destroy(self):
        if self._root:
            self._root.destroy()
            self._root = None
            self._canvas = None