"""圆盘编辑页组件 — 命令库树、折叠按钮、可交互圆盘预览

从 qt_config_gui 拆出的独立组件：命令库拖拽放置、扇区点击/拖拽交换、
悬停提示均在此实现。QConfigGUI 只负责数据读写与布局组装。
"""

import json
import math

from PySide6.QtCore import QMimeData, QPoint, QSize, Qt
from PySide6.QtGui import (QColor, QDrag, QFont, QPainter, QPen, QPixmap,
                           QPolygon)
from PySide6.QtWidgets import (QAbstractItemView, QLabel, QPushButton,
                               QToolTip, QTreeWidget, QWidget)

from src.gesture_engine import calc_sector
from src.menu_geometry import scaled_radii
from src.i18n import T
from src.theme import get_ui, theme_from_settings
from src.qt_renderer import (INNER, OUTER, EXTENSION, draw_shadow, draw_ring,
                             draw_center)


def _layer_key(layer: str) -> str:
    if layer == "outer":
        return "outer_sectors"
    if layer == "extension":
        return "extension_sectors"
    return "sectors"


def _layer_name(layer: str) -> str:
    return {"outer": "外层", "extension": "扩展圈"}.get(layer, "内层")


_COMMAND_MIME = "application/x-cad-gesture-command"


class CommandTree(QTreeWidget):
    """命令库树：节点可拖拽（携带命令 JSON），拖到圆盘直接放置"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None or item.parent() is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        md = QMimeData()
        md.setData(_COMMAND_MIME, json.dumps(data, ensure_ascii=False).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(md)
        label = data.get("label", "")
        pm = QPixmap(max(56, len(label) * 14 + 16), 30)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        ui = get_ui()
        p.setPen(QColor(ui.accent_text))
        p.setBrush(QColor(ui.accent_dim))
        p.drawRoundedRect(1, 1, pm.width() - 2, pm.height() - 2, 6, 6)
        p.setPen(QColor("#ffffff"))
        f = QFont("Microsoft YaHei")
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, label)
        p.end()
        drag.setPixmap(pm)
        drag.setHotSpot(pm.rect().center())
        drag.exec(Qt.CopyAction)


class _PanelToggleButton(QPushButton):
    """命令库折叠按钮：短把手，与面板同色无缝衔接在面板左缘，chevron 指示方向"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self._collapsed = False
        self.setCursor(Qt.PointingHandCursor)
        self.setFixedSize(26, 60)
        self.setToolTip(T("折叠命令库，圆盘全宽显示"))

    def set_collapsed(self, collapsed: bool):
        if collapsed != self._collapsed:
            self._collapsed = collapsed
            self.setToolTip(T("展开命令库") if collapsed
                            else T("折叠命令库，圆盘全宽显示"))
            self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        active = self.underMouse() or self.isDown()
        w, h = self.width(), self.height()
        ui = get_ui()

        # 背景与命令库面板完全同色（不透明、直角），骑跨处与面板融为一体，
        # 只有露出预览区的那半形成一个短把手
        p.setPen(Qt.NoPen)
        p.fillRect(0, 0, w, h, QColor(ui.bg_hover if active else ui.bg_raised))

        # 双线 chevron：展开态朝右（指向面板），折叠态朝左（指向展开方向）
        color = QColor(ui.accent if active else ui.text_secondary)
        p.setPen(QPen(color, 2, Qt.SolidLine, Qt.RoundCap, Qt.RoundJoin))
        p.setBrush(Qt.NoBrush)
        cx, cy = w / 2, h / 2
        if self._collapsed:
            pts = (QPoint(cx + 4, cy - 7), QPoint(cx - 4, cy), QPoint(cx + 4, cy + 7))
        else:
            pts = (QPoint(cx - 4, cy - 7), QPoint(cx + 4, cy), QPoint(cx - 4, cy + 7))
        p.drawPolyline(QPolygon(pts))
        p.end()


class QRadialPreview(QWidget):
    """可交互圆盘预览：hover 高亮 + 点击选扇区 + 拖放放置 + 扇区拖拽交换"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = None
        self.profile = None
        self.theme = None
        self.selected: tuple | None = None   # (layer, idx)
        self.hovered: tuple | None = None
        self.pending: dict | None = None     # 待放置的命令（右键命令后进入放置模式）
        self.on_select = None                # 回调 (layer, idx)
        self.on_drop = None                  # 回调 (layer, idx, data)
        self.on_swap = None                  # 回调 (f_layer, f_idx, t_layer, t_idx)
        self.on_clear = None                 # 回调 () 点击圆盘外取消选择
        self._press_pos = None               # 按下位置（判断是否进入拖拽）
        self._drag_pending = None            # 按下命中的扇区（未超过拖拽阈值）
        self._drag_from = None               # 正在拖拽的源扇区
        self._drag_hover = None              # 拖拽悬停的目标扇区
        self._drag_threshold = 8
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(360, 360)
        # 限制高度：圆盘不随窗口膨胀到占满全高，为下方固定浮层（扇区编辑窗）
        # 留出空间，保证浮层永远显示在圆盘正下方、不盖住扇区。
        # 575 高度下圆盘直径约 493px，矮屏（864px 高度）也能放得下浮层。
        self.setMaximumHeight(575)

    def set_data(self, config, profile):
        self.config = config
        self.profile = profile
        self.theme = theme_from_settings(config.get("settings", {}))
        self.update()

    def sizeHint(self) -> QSize:
        # 顶对齐布局按 sizeHint 定高：圆盘不占满窗口，为下方浮层留空间
        return QSize(660, 575)

    def update_config(self, config):
        self.config = config
        self.theme = theme_from_settings(config.get("settings", {}))
        self.update()

    # ---- 几何 ----
    def _geo(self):
        """返回 (cx, cy, fit)：fit 按实际最外圈半径自适应，防 150% 缩放下裁切"""
        w, h = self.width(), self.height()
        cx, cy = w / 2, h / 2
        ext = self._radii()["ext_ring_radius"] or 1
        avail = min(w, h) / 2 - 24
        return cx, cy, max(0.01, avail / ext)

    def _radii(self) -> dict:
        """实际生效半径（配置值 × menu_scale），与运行时圆盘完全一致"""
        return scaled_radii(self.config.get("settings", {}))

    def outermost_radius_px(self) -> float:
        """预览中实际最外圈半径（像素），供浮层定位使用"""
        _, _, fit = self._geo()
        return self._radii()["ext_ring_radius"] * fit

    def _sector_at(self, x, y):
        if self.profile is None:
            return None
        cx, cy, scale = self._geo()
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy) / scale
        r = self._radii()
        dead, inner, outer, ext = (r["dead_zone_radius"], r["ring_radius"],
                                   r["outer_ring_radius"], r["ext_ring_radius"])
        n = self.config.get("settings", {}).get("sector_count", 8)
        if dist < dead:
            return None
        sec = calc_sector(dx, dy, n)
        if dist < inner:
            return ("inner", sec)
        if dist < outer:
            return ("outer", sec)
        if dist < ext:
            return ("extension", sec)
        return None

    # ---- 事件 ----
    def mouseMoveEvent(self, e):
        pos = e.position()
        # 按下扇区后移动超过阈值：进入扇区拖拽（交换/移动命令）
        if self._drag_pending is not None and self._press_pos is not None:
            if (pos - self._press_pos).manhattanLength() > self._drag_threshold:
                self._drag_from = self._drag_pending
                self._drag_pending = None
                self._press_pos = None
                self.setCursor(Qt.ClosedHandCursor)
                QToolTip.hideText()
        if self._drag_from is not None:
            s = self._sector_at(pos.x(), pos.y())
            tgt = None if s == self._drag_from else s
            if tgt != self._drag_hover:
                self._drag_hover = tgt
                self.update()
            return
        s = self._sector_at(pos.x(), pos.y())
        if s != self.hovered:
            self.hovered = s
            self.update()
            self._update_sector_tip(s, e.globalPosition().toPoint())

    def _update_sector_tip(self, s, gpos):
        """鼠标悬停扇区时显示命令名/快捷键/命令详情"""
        if s is None or self.profile is None:
            QToolTip.hideText()
            return
        layer, idx = s
        cfg = self.profile.get(_layer_key(layer), {}).get(str(idx), {})
        if not cfg:
            QToolTip.hideText()
            return
        line = cfg.get("label", "")
        if cfg.get("key"):
            line += f"  [{cfg['key'].upper()}]"
        lines = [line]
        if cfg.get("description"):
            lines.append(cfg["description"])
        QToolTip.showText(gpos + QPoint(14, 18), "\n".join(lines), self)

    def mouseReleaseEvent(self, e):
        if self._drag_from is not None:
            from_s = self._drag_from
            s = self._sector_at(e.position().x(), e.position().y())
            if s is not None and s != from_s and self.on_swap:
                self.on_swap(*from_s, *s)
            elif s == from_s:
                # 拖回原位：视为普通点击
                self.selected = from_s
                self.update()
                if self.on_select:
                    self.on_select(*from_s)
            self._drag_from = None
            self._drag_hover = None
            self._press_pos = None
            self._drag_pending = None
            self.setCursor(Qt.ArrowCursor)
            self.update()
            return
        if self._drag_pending is not None:
            # 按下后原地释放：普通点击，弹出编辑浮层
            s = self._drag_pending
            self._drag_pending = None
            self._press_pos = None
            self.selected = s
            self.update()
            if self.on_select:
                self.on_select(*s)
            return
        super().mouseReleaseEvent(e)

    def leaveEvent(self, e):
        self.hovered = None
        self._drag_hover = None
        QToolTip.hideText()
        self.update()

    # ---- 拖放（命令库拖拽到圆盘） ----
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(_COMMAND_MIME):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(_COMMAND_MIME):
            s = self._sector_at(e.position().x(), e.position().y())
            if s != self.hovered:
                self.hovered = s
                self.update()
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self.hovered = None
        self.update()

    def dropEvent(self, e):
        md = e.mimeData()
        if not md.hasFormat(_COMMAND_MIME):
            e.ignore()
            return
        try:
            data = json.loads(bytes(md.data(_COMMAND_MIME)).decode("utf-8"))
        except Exception:
            data = None
        s = self._sector_at(e.position().x(), e.position().y())
        self.hovered = None
        self.update()
        if s and data and self.on_drop:
            self.on_drop(*s, data)
        e.acceptProposedAction()

    def mousePressEvent(self, e):
        if e.button() in (Qt.LeftButton, Qt.RightButton):
            s = self._sector_at(e.position().x(), e.position().y())
            if s:
                if self.pending is not None:
                    # 放置模式：点击扇区放置命令
                    if self.on_drop:
                        self.on_drop(*s, self.pending)
                    self.pending = None
                    self.setCursor(Qt.ArrowCursor)
                    self.update()
                    return
                # 记录按下位置与扇区：拖动则交换，原地释放则弹出编辑浮层
                self._press_pos = e.position()
                self._drag_pending = s
                self.selected = s
                self.update()
            else:
                # 点击圆盘外：取消放置模式或清除选中
                if self.pending is not None:
                    self.pending = None
                    self.setCursor(Qt.ArrowCursor)
                if e.button() == Qt.LeftButton:
                    self._clear_selection()
        elif e.button() == Qt.RightButton:
            if self.pending is not None:
                self.pending = None
                self.setCursor(Qt.ArrowCursor)
                self.update()

    def _clear_selection(self):
        """清除选中高亮（点击圆盘外触发）"""
        if self.selected is not None or self._drag_pending is not None:
            self.selected = None
            self.hovered = None
            self._drag_pending = None
            self._press_pos = None
            self._drag_from = None
            self._drag_hover = None
            self.update()
            if self.on_clear:
                self.on_clear()

    # ---- 绘制 ----
    def paintEvent(self, event):
        if self.profile is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        op = self.config.get("settings", {}).get("menu_opacity", 0.95)
        p.setOpacity(max(0.3, min(1.0, op)))
        cx, cy, scale = self._geo()
        t = self.theme
        n = self.config.get("settings", {}).get("sector_count", 8)
        r = self._radii()
        dead, inner, outer, ext = (r["dead_zone_radius"] * scale,
                                   r["ring_radius"] * scale,
                                   r["outer_ring_radius"] * scale,
                                   r["ext_ring_radius"] * scale)

        draw_shadow(p, cx, cy, ext, light=t.light)
        sel = self._drag_from if self._drag_from is not None else self.selected
        hov = self._drag_hover if self._drag_from is not None else self.hovered
        draw_ring(p, cx, cy, outer, ext, n,
                  self.profile.get("extension_sectors", {}), t.extension,
                  layer=EXTENSION, sel=sel, hov=hov, light=t.light,
                  placeholder=True)
        draw_ring(p, cx, cy, inner, outer, n,
                  self.profile.get("outer_sectors", {}), t.outer,
                  layer=OUTER, sel=sel, hov=hov, light=t.light,
                  placeholder=True)
        draw_ring(p, cx, cy, dead, inner, n,
                  self.profile.get("sectors", {}), t.inner,
                  layer=INNER, sel=sel, hov=hov, light=t.light,
                  placeholder=True)

        label, sub = self._center_texts()
        draw_center(p, cx, cy, dead, t, min(self.width(), self.height()),
                    label, sub)
        p.end()

    def _center_texts(self):
        if self.pending:
            return f"{T('放置')}: {self.pending.get('label', '')}", \
                T("点击扇区放置 · 右键取消")
        if not self.selected:
            return "", self.profile.get("name", "") if self.profile else ""
        layer, idx = self.selected
        key = _layer_key(layer)
        cfg = self.profile.get(key, {}).get(str(idx), {})
        sub = cfg.get("key", "").upper() if cfg.get("key") else T(_layer_name(layer))
        return cfg.get("label", ""), sub
