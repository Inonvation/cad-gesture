"""圆盘菜单模块 — Fluent 风格三层径向圆盘"""

import math
import time
import tkinter as tk
from typing import Dict, Any, Optional

from src.gesture_engine import calc_sector
from src.theme import get_menu_theme, MenuTheme
from src.renderer import draw_ring, ring_state_normal, _fit_font


class RadialMenu:
    """径向圆盘菜单——Fluent 风格三层扇形选择面板"""

    def __init__(self, config: dict, parent=None, on_cancel=None):
        self.config = config
        self._parent = parent
        self.on_cancel = on_cancel  # 菜单被 Esc/左键取消时回调（引擎复位手势状态）
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
        self._shown_at: float = 0.0  # 本次显示时刻（幽灵菜单超时防护）
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
        self._root.bind("<Escape>", self._handle_cancel)
        self._root.bind("<Button-1>", self._handle_cancel)
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
        self._shown_at = time.monotonic()
        self._fade_in(0)

    def _fade_in(self, step: int):
        """淡入动画（快速呼出）"""
        if not self._visible:
            return
        alpha = min(step / 5, 1.0)
        self._root.attributes("-alpha", alpha)
        if step < 5:
            self._root.after(8, lambda: self._fade_in(step + 1))

    def hide(self):
        if self._root and self._visible:
            if self._highlight_throttle_id:
                self._root.after_cancel(self._highlight_throttle_id)
                self._highlight_throttle_id = None
            self._root.withdraw()
            self._visible = False
            self._shown_at = 0.0

    def _handle_cancel(self, event=None):
        """Esc / 左键取消：隐藏菜单并回传引擎复位手势状态，阻止松键补发命令"""
        was_visible = self._visible
        self.hide()
        if was_visible and self.on_cancel:
            self.on_cancel()

    def is_visible(self) -> bool:
        return self._visible

    def update_highlight(self, mouse_x: int, mouse_y: int):
        if not self._visible or self._canvas is None:
            return
        # 幽灵菜单防护：钩子被系统摘除等异常导致引擎状态失同步时，
        # 菜单显示超过 15s 自动隐藏并复位引擎，避免残留圆盘挡住 CAD
        if self._shown_at and time.monotonic() - self._shown_at > 15.0:
            self.hide()
            if self.on_cancel:
                self.on_cancel()
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

        # 中心文字：只显示扇区命令名(label)，字号自动适配中心不超出
        center_base = ("Microsoft YaHei", 12, "bold")
        label = ""
        if self._highlighted_sector >= 0:
            if self._in_extension_zone:
                cfg = self._profile.get("extension_sectors", {}).get(
                    str(self._highlighted_sector), {})
            elif self._highlighted_outer:
                cfg = self._profile.get("outer_sectors", {}).get(
                    str(self._highlighted_sector), {})
                if not cfg:
                    cfg = self._profile.get("sectors", {}).get(
                        str(self._highlighted_sector), {})
            else:
                cfg = self._profile.get("sectors", {}).get(
                    str(self._highlighted_sector), {})
            label = cfg.get("label", "")

        if label:
            max_w = dead_r * 2 * 0.85
            font = _fit_font(label, center_base, max_w)
            color = t.extension.highlight if self._in_extension_zone else t.center_text
            self._canvas.create_text(cx, cy, text=label, fill=color, font=font)
        else:
            self._canvas.create_text(cx, cy, text="释放", fill=t.center_text,
                                     font=("Microsoft YaHei", 10))

    def update_config(self, config: dict):
        self.config = config
        self._theme = get_menu_theme(
            config.get("settings", {}).get("menu_theme", "azure"))

    def destroy(self):
        if self._root:
            self._root.destroy()
            self._root = None
            self._canvas = None