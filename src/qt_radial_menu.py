"""Qt 版径向圆盘菜单 — PySide6 实现（透明无边框悬浮窗 + QPainter 绘制）

视觉特性：柔和投影、高亮平滑过渡动画、高亮扇区光晕、中心渐变与文字阴影。
接口与旧 Tk 版一致：show / hide / is_visible / update_highlight /
set_extension_hint / update_config / destroy / on_cancel
"""

import os
import sys

if __package__ in (None, ""):
    # 直接运行本文件（python src/qt_radial_menu.py）时，把项目根加入模块搜索路径
    sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math

from PySide6.QtCore import (QEasingCurve, QPoint, QPropertyAnimation, QRectF,
                            Qt, QTimer)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QGuiApplication,
                           QPainter, QPen, QRadialGradient, QCursor)
from PySide6.QtWidgets import QWidget

from src.gesture_engine import calc_sector
from src.theme import theme_from_settings
from src.qt_renderer import (INNER, OUTER, EXTENSION, draw_shadow, draw_ring,
                             draw_center, draw_label)


class QRadialMenu(QWidget):
    """径向圆盘菜单——Fluent 风格三层扇形选择面板（Qt 实现，含动画）"""

    def __init__(self, config: dict, on_cancel=None):
        super().__init__()
        self.setWindowFlags(
            Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setFocusPolicy(Qt.StrongFocus)
        # 覆盖应用级 QSS：圆盘菜单保持全透明背景，只由 paintEvent 自绘
        self.setStyleSheet("QWidget { background: transparent; }")

        self.config = config
        self._on_cancel = on_cancel
        self._profile = None
        self._visible = False
        self._center_x = 0
        self._center_y = 0
        self._highlighted_sector = -1
        self._highlighted_outer = False
        self._in_extension_zone = False
        self._theme = theme_from_settings(
            config.get("settings", {}))

        # 窗口尺寸覆盖到扩展圈判定范围（第三圈区域透明）
        self._apply_size()

        # 窗口淡入动画
        self._fade_anim = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade_anim.setDuration(70)
        self._fade_anim.setEasingCurve(QEasingCurve.InOutQuad)

        # 高亮淡入动画（颜色平滑过渡，约 120ms）
        self._hl_fade = 1.0
        self._hl_fade_timer = QTimer(self)
        self._hl_fade_timer.setInterval(8)
        self._hl_fade_timer.timeout.connect(self._on_hl_fade_tick)

    # ========== 配置属性 ==========

    def _apply_size(self):
        """按当前扩展圈半径重算窗口尺寸。

        设置里改大圆盘后窗口必须跟着变大，否则第三圈会被窗口边缘裁切。
        """
        self._size = self.ext_ring_radius * 2 + 120
        self.setFixedSize(self._size, self._size)

    @property
    def ring_radius(self) -> int:
        return self.config.get("settings", {}).get("ring_radius", 70)

    @property
    def outer_ring_radius(self) -> int:
        return self.config.get("settings", {}).get("outer_ring_radius", 135)

    @property
    def ext_ring_radius(self) -> int:
        return self.config.get("settings", {}).get("ext_ring_radius", 185)

    @property
    def sector_count(self) -> int:
        return self.config.get("settings", {}).get("sector_count", 8)

    @property
    def dead_zone(self) -> int:
        return self.config.get("settings", {}).get("dead_zone_radius", 24)

    @property
    def menu_opacity(self) -> float:
        """圆盘整体透明度（0.3 ~ 1.0）"""
        return max(0.3, min(1.0, self.config.get("settings", {}).get("menu_opacity", 0.95)))

    # ========== 对外接口 ==========

    def show(self, x: int, y: int, profile: dict):
        self._profile = profile
        # 钩子回调给的是物理像素，Qt 窗口坐标是逻辑像素（高 DPI 下需换算）
        lx, ly = self._to_logical(x, y)
        self._center_x, self._center_y = lx, ly
        self._highlighted_sector = -1
        self._highlighted_outer = False
        self._in_extension_zone = False
        # 屏幕边缘自适应：圆盘窗口不超出屏幕可用区域（贴近边缘时整体内移）
        left = int(lx - self._size // 2)
        top = int(ly - self._size // 2)
        try:
            scr = QGuiApplication.screenAt(QPoint(x, y))
            if scr is None:
                scr = QGuiApplication.primaryScreen()
            geo = scr.availableGeometry()
            left = max(geo.left(), min(geo.right() - self._size + 1, left))
            top = max(geo.top(), min(geo.bottom() - self._size + 1, top))
        except Exception:
            pass
        self.move(left, top)
        super().show()
        self._visible = True
        self.update()
        self._fade_in()

    @staticmethod
    def _to_logical(px: int, py: int):
        """物理像素 -> Qt 逻辑像素（按所在屏幕 DPI 缩放）"""
        try:
            scr = QGuiApplication.screenAt(QPoint(px, py))
            if scr is None:
                scr = QGuiApplication.primaryScreen()
            dpr = scr.devicePixelRatio()
            return px / dpr, py / dpr
        except Exception:
            return float(px), float(py)

    def hide(self):
        if self._visible:
            self._fade_anim.stop()
            self._hl_fade_timer.stop()
            self.setWindowOpacity(1.0)
            super().hide()
            self._visible = False

    def is_visible(self) -> bool:
        return self._visible

    def destroy(self):
        try:
            super().close()
        except Exception:
            pass

    def update_config(self, config: dict):
        self.config = config
        self._theme = theme_from_settings(config.get("settings", {}))
        self._apply_size()   # 圆盘尺寸设置改变时同步窗口大小，防止裁切

    def update_highlight(self, mouse_x: int, mouse_y: int):
        if not self._visible:
            return
        dx, dy = mouse_x - self._center_x, mouse_y - self._center_y
        dist = math.sqrt(dx * dx + dy * dy)
        if dist < self.dead_zone:
            new_sec, new_outer, new_ext = -1, False, False
        else:
            new_sec = calc_sector(dx, dy, self.sector_count)
            new_ext = dist > self.outer_ring_radius
            new_outer = (not new_ext) and dist > self.ring_radius
        if (new_sec != self._highlighted_sector or
                new_outer != self._highlighted_outer or
                new_ext != self._in_extension_zone):
            self._highlighted_sector = new_sec
            self._highlighted_outer = new_outer
            self._in_extension_zone = new_ext
            self._start_hl_fade()
            self.update()

    def set_extension_hint(self, is_in_zone: bool):
        if is_in_zone != self._in_extension_zone:
            self._in_extension_zone = is_in_zone
            self._start_hl_fade()
            self.update()

    # ========== 事件 ==========

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            self._handle_cancel()
        else:
            super().keyPressEvent(event)

    def mousePressEvent(self, event):
        if event.button() == Qt.LeftButton:
            self._handle_cancel()
        else:
            super().mousePressEvent(event)

    def _handle_cancel(self):
        was_visible = self._visible
        self.hide()
        if was_visible and self._on_cancel:
            self._on_cancel()

    # ========== 动画 ==========

    def _fade_in(self):
        self._fade_anim.stop()
        self.setWindowOpacity(0.0)
        self._fade_anim.setStartValue(0.0)
        self._fade_anim.setEndValue(1.0)
        self._fade_anim.start()

    def _start_hl_fade(self):
        self._hl_fade = 0.0
        self._hl_fade_timer.start()

    def _on_hl_fade_tick(self):
        self._hl_fade += 0.09
        if self._hl_fade >= 1.0:
            self._hl_fade = 1.0
            self._hl_fade_timer.stop()
        self.update()

    # ========== 绘制 ==========

    def paintEvent(self, event):
        if self._profile is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        p.setOpacity(self.menu_opacity)
        cx = cy = self._size // 2
        t = self._theme
        n = self.sector_count

        if self._in_extension_zone:
            hl_layer = EXTENSION
        elif self._highlighted_outer:
            hl_layer = OUTER
        else:
            hl_layer = INNER

        draw_shadow(p, cx, cy, self.ext_ring_radius, light=t.light)

        draw_ring(p, cx, cy, self.outer_ring_radius, self.ext_ring_radius,
                  n, self._profile.get("extension_sectors", {}), t.extension,
                  layer=EXTENSION, hl_idx=self._highlighted_sector,
                  hl_layer=hl_layer, hl_fade=self._hl_fade, light=t.light)
        draw_ring(p, cx, cy, self.ring_radius, self.outer_ring_radius,
                  n, self._profile.get("outer_sectors", {}), t.outer,
                  layer=OUTER, hl_idx=self._highlighted_sector,
                  hl_layer=hl_layer, hl_fade=self._hl_fade, light=t.light)
        draw_ring(p, cx, cy, self.dead_zone, self.ring_radius,
                  n, self._profile.get("sectors", {}), t.inner,
                  layer=INNER, hl_idx=self._highlighted_sector,
                  hl_layer=hl_layer, hl_fade=self._hl_fade, light=t.light)

        draw_center(p, cx, cy, self.dead_zone, t, self._size,
                    *self._center_texts())
        p.end()

    def _center_texts(self) -> tuple[str, str]:
        """中心两行文字：有悬停显示 (命令名, 快捷键)，否则淡显方案名"""
        if self._highlighted_sector >= 0:
            idx = self._highlighted_sector
            if self._in_extension_zone:
                cfg = self._profile.get("extension_sectors", {}).get(str(idx), {})
            elif self._highlighted_outer:
                cfg = self._profile.get("outer_sectors", {}).get(str(idx), {})
                if not cfg:
                    cfg = self._profile.get("sectors", {}).get(str(idx), {})
            else:
                cfg = self._profile.get("sectors", {}).get(str(idx), {})
            label = cfg.get("label", "")
            sub = cfg.get("key", "").upper() if cfg.get("key") else ""
            return label, sub
        return "", self._profile.get("name", "") if self._profile else ""


def _demo():
    """独立演示：屏幕中央显示圆盘，移动鼠标看高亮跟随"""
    from PySide6.QtCore import QTimer
    from PySide6.QtGui import QCursor
    from PySide6.QtWidgets import QApplication
    from src.config_manager import load_config

    app = QApplication(sys.argv)
    config = load_config()
    menu = QRadialMenu(config)

    profile = config["profiles"].get(
        config.get("settings", {}).get("active_profile", "AutoCAD-常用"))
    screen = app.primaryScreen().availableGeometry()
    menu.show(screen.center().x(), screen.center().y(), profile)

    def tick():
        pos = QCursor.pos()
        menu.update_highlight(pos.x(), pos.y())

    timer = QTimer()
    timer.timeout.connect(tick)
    timer.start(16)
    sys.exit(app.exec())


if __name__ == "__main__":
    _demo()
