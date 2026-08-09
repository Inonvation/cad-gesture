"""Qt 共享圆盘绘制 — 运行时圆盘(QRadialMenu)与配置预览(QRadialPreview)共用，保证视觉一致"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen,
                           QRadialGradient)

INNER = "inner"
OUTER = "outer"
EXTENSION = "extension"

_SECTOR_KEYS = {"sectors": INNER, "outer_sectors": OUTER,
                "extension_sectors": EXTENSION}


def layer_from_key(key: str) -> str:
    """配置 sector 字段名 -> 层名"""
    return _SECTOR_KEYS.get(key, INNER)


def blend(c1: str, c2: str, t: float) -> QColor:
    """两个十六进制颜色线性插值，t=0 返回 c1，t=1 返回 c2"""
    a = QColor(c1)
    b = QColor(c2)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def draw_shadow(p: QPainter, cx: float, cy: float, ext_r: float) -> None:
    """圆盘底座柔和投影（多层半透明同心圆模拟模糊）"""
    for k in range(10, 0, -1):
        alpha = 24 - k * 2
        if alpha <= 0:
            continue
        rr = ext_r + 6 + k * 2
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(0, 0, 0, alpha))
        p.drawEllipse(QPointF(cx, cy), rr, rr)


def draw_pie(p: QPainter, cx: float, cy: float, outer_r: float, n: int,
             i: int, fill: QColor, outline: QColor, width: int = 1) -> None:
    """画单个扇形（pieslice，圆心起、外弧止；内层由后画覆盖）"""
    sec_deg = 360.0 / n
    start = i * sec_deg - 90 - sec_deg / 2
    p.setPen(QPen(outline, width))
    p.setBrush(fill)
    p.drawPie(QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2),
              int(start * 16), int(sec_deg * 16))


def draw_glow(p: QPainter, cx: float, cy: float, inner_r: float,
              outer_r: float, n: int, i: int, intensity: float = 1.0) -> None:
    """高亮扇区的柔和光晕"""
    if intensity <= 0:
        return
    mid = math.radians(i * 360 / n - 90)
    tr = inner_r + (outer_r - inner_r) * 0.5
    hx = cx + tr * math.cos(mid)
    hy = cy - tr * math.sin(mid)
    glow_r = max((outer_r - inner_r) * 0.9, 8.0)
    grad = QRadialGradient(QPointF(hx, hy), glow_r)
    alpha = int(70 * intensity)
    grad.setColorAt(0, QColor(255, 255, 255, alpha))
    grad.setColorAt(1, QColor(255, 255, 255, 0))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawEllipse(QPointF(hx, hy), glow_r, glow_r)


def _fit_font(text: str, base_px: int, max_px: float,
              bold: bool = False) -> QFont:
    """根据可用宽度自动缩小字号，避免长标签溢出扇区"""
    font = QFont("Microsoft YaHei")
    font.setBold(bold)
    size = base_px
    font.setPixelSize(size)
    fm = QFontMetrics(font)
    while size > 7 and fm.horizontalAdvance(text) > max_px:
        size -= 1
        font.setPixelSize(size)
        fm = QFontMetrics(font)
    return font


def draw_label(p: QPainter, cx: float, cy: float, inner_r: float,
               outer_r: float, n: int, i: int, text: str, color: QColor,
               bold: bool = False, label_offset: float = 0.5) -> None:
    """扇区环上的文字标签（沿角度方向居中）"""
    mid = math.radians(i * 360 / n - 90)
    tr = inner_r + (outer_r - inner_r) * label_offset
    tx = cx + tr * math.cos(mid)
    ty = cy - tr * math.sin(mid)
    avail = tr * (2 * math.pi / n) * 0.85
    font = _fit_font(text, 10, avail, bold)
    p.setPen(color)
    p.setFont(font)
    p.drawText(QRectF(tx - avail / 2, ty - 10, avail, 20), Qt.AlignCenter, text)


def draw_ring(p: QPainter, cx: float, cy: float, inner_r: float,
              outer_r: float, n: int, sectors: dict, rc,
              layer: str = INNER, hl_idx: int = -1, hl_layer=None,
              hl_fade: float = 1.0, sel=None, hov=None,
              label_offset: float = 0.5) -> None:
    """画一层扇区环。

    高亮优先级：selected > hovered > 高亮层。
    - runtime: 传 hl_idx / hl_layer / hl_fade（sel、hov 为 None）
    - preview: 传 sel / hov（均为 (layer, idx) 或 None）
    """
    for i in range(n):
        cfg = sectors.get(str(i), {})
        label = cfg.get("label", "")
        is_hl = (hl_idx >= 0 and hl_layer == layer and i == hl_idx)
        is_sel = sel is not None and sel[0] == layer and sel[1] == i
        is_hov = hov is not None and hov[0] == layer and hov[1] == i
        if is_hl:
            fill = blend(rc.normal, rc.highlight, hl_fade)
            pen, w, bold = QColor(rc.outline_hl), 2, True
        elif is_sel:
            fill, pen, w, bold = QColor(rc.highlight), QColor(rc.outline_hl), 2, True
        elif is_hov:
            fill, pen, w, bold = QColor(rc.hover), QColor(rc.outline_hl), 2, True
        elif label:
            fill, pen, w, bold = QColor(rc.normal), QColor(rc.outline), 1, False
        else:
            fill, pen, w, bold = QColor(rc.empty), QColor(rc.outline), 1, False
        draw_pie(p, cx, cy, outer_r, n, i, fill, pen, w)
        if is_hl or is_sel or is_hov:
            draw_glow(p, cx, cy, inner_r, outer_r, n, i,
                      hl_fade if is_hl else 1.0)
        if label:
            color = QColor(rc.text if (is_hl or is_sel or is_hov)
                           else rc.text_dim)
            draw_label(p, cx, cy, inner_r, outer_r, n, i, label, color,
                       bold, label_offset)


def draw_center(p: QPainter, cx: float, cy: float, dead_r: float,
                theme, size: float, label: str = "") -> None:
    """中心死区（径向渐变）+ 中心文字（带投影）"""
    grad = QRadialGradient(QPointF(cx, cy), dead_r)
    base = QColor(theme.dead_zone)
    grad.setColorAt(0, base.lighter(118))
    grad.setColorAt(1, base)
    p.setPen(QPen(QColor(theme.dead_zone_outline), 1))
    p.setBrush(grad)
    p.drawEllipse(QPointF(cx, cy), dead_r, dead_r)
    if label:
        # 文字以圆盘中心 (cx, cy) 为基准居中，避免非正方形控件（配置预览）中偏左
        half = size / 2
        rect = QRectF(cx - half, cy - half, size, size)
        font = _fit_font(label, 12, dead_r * 2 * 0.85, bold=True)
        p.setFont(font)
        p.setPen(QColor(0, 0, 0, 150))
        p.drawText(rect.translated(1, 2), Qt.AlignCenter, label)
        p.setPen(QColor(theme.center_text))
        p.drawText(rect, Qt.AlignCenter, label)
