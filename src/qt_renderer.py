"""Qt 共享圆盘绘制 — 运行时圆盘(QRadialMenu)与配置预览(QRadialPreview)共用，保证视觉一致"""

import math

from PySide6.QtCore import QPointF, QRectF, Qt
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPainterPath,
                           QPen, QRadialGradient)

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


def draw_shadow(p: QPainter, cx: float, cy: float, ext_r: float,
                light: bool = False) -> None:
    """圆盘底座柔和投影（多层半透明圆环模拟模糊）。

    用环形而非实心圆：实心圆会把半透明黑罩叠加到整个圆盘（含中心死区），
    导致中心透明度异常（131 vs 预期 102）、整体发暗。环形只在外圈
    形成柔和光晕，中心保持干净。
    light：浅色主题用淡灰投影，避免深色投影在浅色界面显脏。
    """
    color = (80, 90, 110) if light else (0, 0, 0)
    for k in range(10, 0, -1):
        alpha = 24 - k * 2
        if alpha <= 0:
            continue
        if light:
            alpha //= 3
        rr = ext_r + 6 + k * 2
        inner_rr = max(0.0, rr - 5)
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(color[0], color[1], color[2], alpha))
        ring = QPainterPath()
        ring.setFillRule(Qt.OddEvenFill)
        ring.addEllipse(QPointF(cx, cy), rr, rr)
        ring.addEllipse(QPointF(cx, cy), inner_rr, inner_rr)
        p.drawPath(ring)


def draw_pie(p: QPainter, cx: float, cy: float, inner_r: float,
             outer_r: float, n: int, i: int, fill: QColor,
             outline: QColor, width: int = 1,
             stroke_inner: bool = True, gap: float = 0.0,
             soft_outline: bool = False) -> None:
    """画环形扇区（内弧 + 外弧 + 两条半径），填充与描边分离。

    不用 drawPie 从圆心画：否则内层 8 个扇形会在中心死区区域反复
    覆盖，半透明绘制逐层累加导致中心不透明，且扇区分割线穿透到圆心。
    环形画法每层只覆盖自己的环带；内层扇区可关闭内弧描边
    （stroke_inner=False），让死区圆自身描边形成干净边界。

    gap：扇区间隙（径向收缩量）。浅色主题用间隙替代彩色描边分割
    （Quicker 风格），深色主题 gap=0 保持细线分割。
    soft_outline：白色模糊分割线（浅色主题）——同一路径先宽线低透明
    再细线高透明两次描边，模拟柔和的白色扇区边界。
    """
    sec_deg = 360.0 / n
    start = i * sec_deg - 90 - sec_deg / 2
    if gap > 0:
        inner_r += gap
        outer_r -= gap
    inner_rect = QRectF(cx - inner_r, cy - inner_r, inner_r * 2, inner_r * 2)
    outer_rect = QRectF(cx - outer_r, cy - outer_r, outer_r * 2, outer_r * 2)
    # Qt 椭圆角度：0°=正右，正 sweep=逆时针（数学角，y 向上）
    def pt(r, deg):
        a = math.radians(deg)
        return cx + r * math.cos(a), cy - r * math.sin(a)

    # 填充：完整环形（OddEvenFill 防自交）
    fpath = QPainterPath()
    fpath.setFillRule(Qt.OddEvenFill)
    fpath.arcMoveTo(outer_rect, start)
    fpath.arcTo(outer_rect, start, sec_deg)              # 外弧 逆时针
    fpath.arcTo(inner_rect, start + sec_deg, -sec_deg)   # 内弧 反向
    fpath.closeSubpath()
    p.setPen(Qt.NoPen)
    p.setBrush(fill)
    p.drawPath(fpath)

    # 描边：外弧 + 右半径 + 左半径（内弧描边可选）
    if width <= 0 or not outline.isValid():
        return
    spath = QPainterPath()
    x0, y0 = pt(outer_r, start)
    spath.moveTo(x0, y0)
    spath.arcTo(outer_rect, start, sec_deg)              # 外弧
    x1, y1 = pt(inner_r, start + sec_deg)
    spath.lineTo(x1, y1)                                 # 右半径
    if stroke_inner:
        x2, y2 = pt(inner_r, start)
        spath.moveTo(x2, y2)
        spath.lineTo(x0, y0)                             # 左半径
    if soft_outline:
        # 白色模糊分割线：宽线低透明 + 细线纯白，两次描边模拟柔和边界。
        # 细线必须不透明：圆盘窗口是透明悬浮窗，半透明白在深色 CAD
        # 背景上会透出背景色（显得是黑/灰线），纯白才清晰。
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(255, 255, 255, 90), width + 3))
        p.drawPath(spath)
        p.setPen(QPen(QColor(255, 255, 255, 255), width))
        p.drawPath(spath)
        return
    p.setPen(QPen(outline, width))
    p.setBrush(Qt.NoBrush)
    p.drawPath(spath)


def draw_glow(p: QPainter, cx: float, cy: float, inner_r: float,
              outer_r: float, n: int, i: int, intensity: float = 1.0,
              color: str = "#ffffff") -> None:
    """高亮扇区的柔和光晕（克制：低透明度、收窄范围）"""
    if intensity <= 0:
        return
    mid = math.radians(i * 360 / n - 90)
    tr = inner_r + (outer_r - inner_r) * 0.5
    hx = cx + tr * math.cos(mid)
    hy = cy - tr * math.sin(mid)
    glow_r = max((outer_r - inner_r) * 0.75, 8.0)
    grad = QRadialGradient(QPointF(hx, hy), glow_r)
    alpha = int(42 * intensity)
    base = QColor(color)
    grad.setColorAt(0, QColor(base.red(), base.green(), base.blue(), alpha))
    grad.setColorAt(1, QColor(base.red(), base.green(), base.blue(), 0))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawEllipse(QPointF(hx, hy), glow_r, glow_r)


def _fit_font(text: str, base_px: int, max_px: float,
              bold: bool = False) -> QFont:
    """根据可用宽度自动缩小字号，避免长标签溢出扇区"""
    font = QFont("Microsoft YaHei")
    font.setBold(bold)
    size = base_px
    # 取整后再设置：字号缩放后是浮点（如 11*1.08=11.88），setPixelSize 传浮点
    # 会被截断回原值导致"调了没变化"，必须 round
    font.setPixelSize(int(round(size)))
    fm = QFontMetrics(font)
    while size > 8 and fm.horizontalAdvance(text) > max_px:
        size -= 1
        font.setPixelSize(int(round(size)))
        fm = QFontMetrics(font)
    return font


def _shadow_for(color: QColor, alpha: int = 120) -> QColor:
    """文字投影颜色：亮字配暗影，暗字配亮影，避免浅色主题下重影"""
    return QColor(255, 255, 255, alpha) if color.lightness() < 128 \
        else QColor(0, 0, 0, alpha)


def draw_label(p: QPainter, cx: float, cy: float, inner_r: float,
               outer_r: float, n: int, i: int, text: str, color: QColor,
               bold: bool = False, label_offset: float = 0.5,
               light: bool = False, font_scale: float = 1.0) -> None:
    """扇区环上的文字标签（沿角度方向居中，带投影提升对比）。

    light：浅色主题。浅底深字 / 主题色底白字对比已足够，去掉投影
    （Quicker 风格干净无重影），字号略大。
    """
    saved_opacity = p.opacity()
    p.setOpacity(1.0)  # 文字不随圆盘透明度变淡
    mid = math.radians(i * 360 / n - 90)
    tr = inner_r + (outer_r - inner_r) * label_offset
    tx = cx + tr * math.cos(mid)
    ty = cy - tr * math.sin(mid)
    avail = tr * (2 * math.pi / n) * 0.85
    font = _fit_font(text, (12 if light else 11) * font_scale, avail, bold)
    rect = QRectF(tx - avail / 2, ty - 10, avail, 20)
    if not light:
        p.setPen(_shadow_for(color))
        p.setFont(font)
        p.drawText(rect.translated(0.5, 1), Qt.AlignCenter, text)
    p.setPen(color)
    p.setFont(font)
    p.drawText(rect, Qt.AlignCenter, text)
    p.setOpacity(saved_opacity)


def draw_ring(p: QPainter, cx: float, cy: float, inner_r: float,
              outer_r: float, n: int, sectors: dict, rc,
              layer: str = INNER, hl_idx: int = -1, hl_layer=None,
              hl_fade: float = 1.0, sel=None, hov=None,
              label_offset: float = 0.5, light: bool = False,
              placeholder: bool = False, font_scale: float = 1.0) -> None:
    """画一层扇区环。

    高亮优先级：selected > hovered > 高亮层。
    - runtime: 传 hl_idx / hl_layer / hl_fade（sel、hov 为 None）
    - preview: 传 sel / hov（均为 (layer, idx) 或 None）
    - light: 浅色主题分支——白扇面 + 主题色高亮白字 + 扇区间隙（Quicker 风）

    深色（light=False）：高亮不刷亮扇面（文字始终在深底上，任何主题都
    清晰可读），表达选中靠 深底过渡 + 亮描边 + 柔光晕 + 加粗文字。
    """
    gap = 0.0
    # 浅色主题不用 gap 缝隙分割：缝隙是窗口透明区域，会透出 CAD 深色
    # 背景变成黑缝；统一用白色描边线条分割
    glow_color = rc.outline_hl if light else "#ffffff"
    for i in range(n):
        cfg = sectors.get(str(i), {})
        label = cfg.get("label", "")
        is_hl = (hl_idx >= 0 and hl_layer == layer and i == hl_idx)
        is_sel = sel is not None and sel[0] == layer and sel[1] == i
        is_hov = hov is not None and hov[0] == layer and hov[1] == i
        if light:
            # 浅色：普通近白扇面，高亮直接填主题色 + 白字（对比反转）；
            # 扇区边界用白色模糊线条（soft_outline），高亮扇区用深主题色
            # 描边（白色线条在主题色底上不可见）
            if is_hl:
                fill = blend(rc.hover, rc.highlight, hl_fade)
                pen, w, bold = QColor(rc.outline_hl), 2, True
            elif is_sel:
                fill, pen, w, bold = QColor(rc.highlight), QColor(rc.outline_hl), 2, True
            elif is_hov:
                fill = blend(rc.normal, rc.hover, 0.6)
                pen, w, bold = QColor(255, 255, 255, 170), 1, False
            elif label:
                fill, pen, w, bold = QColor(rc.normal), QColor(255, 255, 255, 170), 1, False
            else:
                fill, pen, w, bold = QColor(rc.empty), QColor(255, 255, 255, 170), 1, False
        else:
            if is_hl:
                fill = blend(rc.normal, rc.hover, hl_fade)
                pen, w, bold = QColor(rc.outline_hl), 2, True
            elif is_sel:
                fill, pen, w, bold = QColor(rc.hover), QColor(rc.outline_hl), 2, True
            elif is_hov:
                fill = blend(rc.normal, rc.hover, 0.55)
                pen, w, bold = QColor(rc.outline_hl), 1, False
            elif label:
                fill, pen, w, bold = QColor(rc.normal), QColor(rc.outline), 1, False
            else:
                fill, pen, w, bold = QColor(rc.empty), QColor(rc.outline), 1, False
        # 内层扇区不画内弧描边：死区圆自身描边提供干净边界，不留分割线痕迹
        draw_pie(p, cx, cy, inner_r, outer_r, n, i, fill, pen, w,
                 stroke_inner=(layer != INNER), gap=gap,
                 soft_outline=(light and not is_hl and not is_sel))
        if is_hl or is_sel or is_hov:
            draw_glow(p, cx, cy, inner_r, outer_r, n, i,
                      hl_fade if is_hl else 1.0, glow_color)
        if label:
            if light:
                # 浅色主题：高亮扇区是淡主题色底，一律用深字（淡底深字对比高，
                # 且高亮不"变深"——之前白字方案在绿色/紫色主题对比不足）
                color = QColor(rc.text)
            else:
                color = QColor(rc.text if (is_hl or is_sel or is_hov)
                               else rc.text_dim)
            draw_label(p, cx, cy, inner_r, outer_r, n, i, label, color,
                       bold, label_offset, light, font_scale)
        elif placeholder and not is_hl and not is_sel and not is_hov:
            # 空扇区占位：径向中点一个小圆点，提示该位置可放置命令（仅编辑/尺寸预览）
            mid = math.radians(i * 360 / n - 90)
            pr = inner_r + (outer_r - inner_r) * 0.5
            dot_r = max(2.0, (outer_r - inner_r) * 0.10)
            dot = QColor(rc.outline)
            dot.setAlpha(90)
            p.setPen(Qt.NoPen)
            p.setBrush(dot)
            p.drawEllipse(QPointF(cx + pr * math.cos(mid),
                                  cy - pr * math.sin(mid)), dot_r, dot_r)


def _center_line(p: QPainter, rect: QRectF, text: str, font: QFont,
                 color, shadow: int = 0) -> None:
    """中心区一行带投影的文字"""
    saved_opacity = p.opacity()
    p.setOpacity(1.0)  # 中心文字不随圆盘透明度变淡
    if shadow:
        p.setFont(font)
        p.setPen(_shadow_for(color, shadow))
        p.drawText(rect.translated(1, 2), Qt.AlignCenter, text)
    p.setFont(font)
    p.setPen(color)
    p.drawText(rect, Qt.AlignCenter, text)
    p.setOpacity(saved_opacity)


def draw_center(p: QPainter, cx: float, cy: float, dead_r: float,
                theme, size: float, label: str = "",
                sub_label: str = "", font_scale: float = 1.0) -> None:
    """中心死区（径向渐变）+ 中心文字。

    两行布局：主标签（命令名，加粗）+ 副标签（快捷键 / 方案名，小字暗色）。
    只有副标签时（无悬停显示方案名）居中单行小字，保持低调。
    """
    grad = QRadialGradient(QPointF(cx, cy), dead_r)
    base = QColor(theme.dead_zone)
    grad.setColorAt(0, base.lighter(118))
    grad.setColorAt(1, base)
    p.setPen(QPen(QColor(theme.dead_zone_outline), 1))
    p.setBrush(grad)
    p.drawEllipse(QPointF(cx, cy), dead_r, dead_r)
    if not (label or sub_label):
        return
    # 浅色主题深字浅底对比足够，去掉投影（Quicker 风）
    light = getattr(theme, "light", False)
    shadow = 0 if light else 150
    sub_shadow = 0 if light else 120
    # 文字以圆盘中心 (cx, cy) 为基准居中，避免非正方形控件（配置预览）中偏左
    half = size / 2
    if label and sub_label:
        # 两行布局以 cy 为中心定位（避免误减 half 把文字画到窗口外）
        main_rect = QRectF(cx - half, cy - 20, size, 22)
        sub_rect = QRectF(cx - half, cy + 4, size, 18)
        sub_color = QColor(theme.center_text)
        sub_color.setAlpha(160)
        _center_line(p, main_rect, label,
                     _fit_font(label, 12 * font_scale, dead_r * 2 * 0.85, bold=True),
                     QColor(theme.center_text), shadow=shadow)
        _center_line(p, sub_rect, sub_label,
                     _fit_font(sub_label, 10 * font_scale, dead_r * 2 * 0.72),
                     sub_color, shadow=sub_shadow)
    elif label:
        rect = QRectF(cx - half, cy - half, size, size)
        _center_line(p, rect, label,
                     _fit_font(label, 12 * font_scale, dead_r * 2 * 0.85, bold=True),
                     QColor(theme.center_text), shadow=shadow)
    else:
        rect = QRectF(cx - half, cy - half, size, size)
        sub_color = QColor(theme.center_text)
        sub_color.setAlpha(120)
        _center_line(p, rect, sub_label,
                     _fit_font(sub_label, 10 * font_scale, dead_r * 2 * 0.72),
                     sub_color, shadow=sub_shadow)
