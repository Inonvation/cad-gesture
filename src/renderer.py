"""共享圆盘绘制逻辑 — 被 radial_menu 和 config_editor 共用"""

import math
import tkinter as tk
import tkinter.font as tkfont
from typing import Dict, Any, Callable

from src.theme import ThemeColors, RingColors

DEFAULT_FONT = ("Microsoft YaHei", 10)


def blend_color(c1: str, c2: str, t: float) -> str:
    """线性插值两个十六进制颜色。t=0 返回 c1，t=1 返回 c2"""
    try:
        r1, g1, b1 = int(c1[1:3], 16), int(c1[3:5], 16), int(c1[5:7], 16)
        r2, g2, b2 = int(c2[1:3], 16), int(c2[3:5], 16), int(c2[5:7], 16)
        r = int(r1 + (r2 - r1) * t)
        g = int(g1 + (g2 - g1) * t)
        b = int(b1 + (b2 - b1) * t)
        return f"#{r:02x}{g:02x}{b:02x}"
    except Exception:
        return c1


def _fit_font(label: str, base_font: tuple, max_px: float) -> tuple:
    """根据可用宽度自动缩小字号，避免长标签溢出扇区"""
    try:
        f = tkfont.Font(font=base_font)
        size = f.cget("size")
        while size > 7 and f.measure(label) > max_px:
            size -= 1
            f.configure(size=size)
        if len(base_font) > 2 and "bold" in base_font:
            return (base_font[0], size, "bold")
        return (base_font[0], size)
    except Exception:
        return base_font


def sector_angles(n: int, i: int):
    """计算扇区 i（共 n 个）的起始角度和展角"""
    sec_deg = 360 / n
    start = i * sec_deg - 90 - sec_deg / 2
    return start, sec_deg


def draw_ring(
    canvas: tk.Canvas,
    cx: int,
    cy: int,
    inner_r: int,
    outer_r: int,
    n: int,
    sectors: Dict[str, Dict[str, str]],
    get_state: Callable[[int, dict], dict],
    label_offset: float = 0.5,
    edge_outline: bool = True,
):
    """绘制一层扇区环。

    Args:
        get_state: (sector_index, sector_config) -> dict
           返回 {fill, outline, width, text_color, font}
        label_offset: 标签在环中的径向位置（0=内边缘，1=外边缘，默认 0.5=居中）
        edge_outline: 是否绘制完整的扇区轮廓线。
           为 False 时不画圆周轮廓（消除外缘硬边），仅保留径向分隔线。
    """
    states = []
    for i in range(n):
        start, extent = sector_angles(n, i)
        cfg = sectors.get(str(i), {})
        label = cfg.get("label", "")
        state = get_state(i, cfg)
        states.append(state)

        if edge_outline:
            canvas.create_arc(
                cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
                start=start, extent=extent,
                fill=state["fill"], outline=state["outline"],
                width=state["width"], style="pieslice",
            )
        else:
            canvas.create_arc(
                cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
                start=start, extent=extent,
                fill=state["fill"], outline="",
                width=0, style="pieslice",
            )

        if label:
            mid = math.radians(i * 360 / n - 90)
            tr = inner_r + (outer_r - inner_r) * label_offset
            tx, ty = cx + tr * math.cos(mid), cy - tr * math.sin(mid)
            font = state.get("font", DEFAULT_FONT)
            avail = tr * (2 * math.pi / n) * 0.85
            font = _fit_font(label, font, avail)
            canvas.create_text(
                tx, ty, text=label, fill=state["text_color"],
                font=font, anchor=tk.CENTER,
            )

    # 无圆周轮廓时，单独绘制径向分隔线（保持扇区间的区分）
    if not edge_outline and states:
        sep = states[0].get("outline", "#0f1319")
        for i in range(n):
            ang = math.radians(i * 360 / n - 90)
            x1 = cx + inner_r * math.cos(ang)
            y1 = cy - inner_r * math.sin(ang)
            x2 = cx + outer_r * math.cos(ang)
            y2 = cy - outer_r * math.sin(ang)
            canvas.create_line(x1, y1, x2, y2, fill=sep, width=1)


def ring_state_normal(ring_colors: RingColors, has_label: bool, is_hl: bool):
    """运行时菜单用的状态：高亮 或 正常 或 空"""
    if is_hl:
        return dict(
            fill=ring_colors.highlight, outline=ring_colors.outline_hl,
            width=2, text_color=ring_colors.text,
            font=("Microsoft YaHei", 10, "bold"),
        )
    if has_label:
        return dict(
            fill=ring_colors.normal, outline=ring_colors.outline,
            width=1, text_color=ring_colors.text_dim,
            font=("Microsoft YaHei", 10),
        )
    return dict(
        fill=ring_colors.empty, outline=ring_colors.outline,
        width=1, text_color=ring_colors.text_dim,
        font=("Microsoft YaHei", 10),
    )


def ring_state_preview(
    ring_colors: RingColors,
    has_label: bool,
    is_selected: bool,
    is_hovered: bool,
    border_color: str,
    accent_dim: str,
):
    """配置预览用的状态：选中 > hover > 正常 > 空"""
    if is_selected:
        return dict(
            fill=ring_colors.highlight, outline=ring_colors.outline_hl,
            width=2, text_color="#ffffff",
            font=("Microsoft YaHei", 10, "bold"),
        )
    if is_hovered:
        return dict(
            fill=ring_colors.hover, outline=ring_colors.outline_hl,
            width=2, text_color="#ffffff",
            font=("Microsoft YaHei", 10, "bold"),
        )
    if has_label:
        return dict(
            fill=ring_colors.normal, outline=ring_colors.outline,
            width=1, text_color=ring_colors.text,
            font=("Microsoft YaHei", 10),
        )
    return dict(
        fill=ring_colors.empty, outline=ring_colors.outline,
        width=1, text_color=ring_colors.text_dim,
        font=("Microsoft YaHei", 10),
    )