# -*- coding: utf-8 -*-
"""生成 CAD Gesture 图标 (assets/icon.ico)

设计定稿：C6c —— 展开的圆规（CAD 绘图动作）
浅灰圆角底 + 深色针脚 / 品牌蓝笔脚 + 铰点 + 下方轨迹弧。
配色与安装向导一致：#EEF2F7 / #1E2A3A / #2B4C7E / #9AABC4。

高清要点：每个尺寸按 4 倍超采样绘制再 LANCZOS 缩小，消除锯齿。
用法：Python312 python scripts/generate_icon.py
"""
import io
import math
import os
import struct

from PIL import Image, ImageDraw

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT_ICO = os.path.join(ROOT, "assets", "icon.ico")
OUT_PNG = os.path.join(ROOT, "assets", "icon_preview.png")

# 与 C6c SVG 一致（128 坐标系）
BG = (238, 242, 247, 255)       # #EEF2F7
NEEDLE = (30, 42, 58, 255)      # #1E2A3A
PEN = (43, 76, 126, 255)        # #2B4C7E
ARC = (154, 171, 196, 255)      # #9AABC4
CLEAR = (0, 0, 0, 0)

SIZES = [16, 20, 24, 32, 48, 64, 128, 256]
SS = 4  # supersample factor


def _build_ico(imgs, path):
    """手动构造多尺寸 ICO（PNG 压缩条目）。"""
    entries = b""
    data = b""
    offset = 6 + 16 * len(imgs)
    for img in imgs:
        buf = io.BytesIO()
        img.save(buf, format="PNG")
        png = buf.getvalue()
        w, h = img.size
        entries += struct.pack(
            "<BBBBHHII",
            w if w < 256 else 0,
            h if h < 256 else 0,
            0, 0, 1, 32, len(png), offset)
        data += png
        offset += len(png)
    with open(path, "wb") as f:
        f.write(struct.pack("<HHH", 0, 1, len(imgs)) + entries + data)


def _draw_arc_points(x0, y0, x1, y1, r, steps=96):
    """SVG 弧近似：返回 128 坐标系上的采样点。"""
    mx, my = (x0 + x1) / 2.0, (y0 + y1) / 2.0
    dx, dy = x1 - x0, y1 - y0
    chord = math.hypot(dx, dy)
    if chord < 1e-6 or chord > 2 * r:
        return []
    h = math.sqrt(max(0.0, r * r - (chord / 2.0) ** 2))
    nx, ny = -dy / chord, dx / chord
    cx, cy = mx + nx * h, my + ny * h

    def ang(x, y):
        return math.atan2(y - cy, x - cx)

    a0 = ang(x0, y0)
    a1 = ang(x1, y1)
    if a1 < a0:
        a1 += 2 * math.pi
    pts = []
    for i in range(steps + 1):
        t = a0 + (a1 - a0) * i / steps
        pts.append((cx + r * math.cos(t), cy + r * math.sin(t)))
    return pts


def _draw_highres(size: int) -> Image.Image:
    """在 size×size 逻辑像素上按 SS 倍超采样绘制。"""
    n = size * SS
    img = Image.new("RGBA", (n, n), CLEAR)
    draw = ImageDraw.Draw(img)
    s = n / 128.0  # 逻辑 128 坐标 → 超采样像素

    # 线宽：小尺寸略加粗，保证桌面/托盘可读
    if size <= 24:
        w_leg = max(3, int(round(9.5 * s)))
        w_arc = max(2, int(round(5.0 * s)))
    elif size <= 48:
        w_leg = max(3, int(round(8.5 * s)))
        w_arc = max(2, int(round(4.5 * s)))
    else:
        w_leg = max(2, int(round(7.5 * s)))
        w_arc = max(2, int(round(4.0 * s)))

    # 圆角底
    radius = max(2, int(round(28 * s)))
    draw.rounded_rectangle([0, 0, n - 1, n - 1], radius=radius, fill=BG)

    # C6c 圆规
    hinge = (58.0 * s, 36.0 * s)
    needle = (52.0 * s, 90.0 * s)
    pen = (90.0 * s, 78.0 * s)
    draw.line([hinge, needle], fill=NEEDLE, width=w_leg, joint="curve")
    draw.line([hinge, pen], fill=PEN, width=w_leg, joint="curve")

    r_out = 8.0 * s
    r_in = 3.2 * s
    cx, cy = hinge
    draw.ellipse([cx - r_out, cy - r_out, cx + r_out, cy + r_out], fill=NEEDLE)
    draw.ellipse([cx - r_in, cy - r_in, cx + r_in, cy + r_in], fill=BG)

    arc_pts = _draw_arc_points(36.0, 94.0, 100.0, 78.0, 58.0)
    if len(arc_pts) >= 2:
        pts = [(x * s, y * s) for x, y in arc_pts]
        draw.line(pts, fill=ARC, width=w_arc, joint="curve")

    return img


def create_icon(size: int) -> Image.Image:
    hi = _draw_highres(size)
    return hi.resize((size, size), Image.Resampling.LANCZOS)


def main():
    layers = [create_icon(s) for s in SIZES]
    _build_ico(layers, OUT_ICO)
    layers[-1].save(OUT_PNG)
    # 拼一张对比图：小尺寸放大 4 倍看清晰度
    zoom = 4
    pad = 12
    widths = [s * zoom for s in (16, 32, 48)]
    sheet = Image.new("RGBA", (sum(widths) + pad * (len(widths) + 1),
                               max(widths) + pad * 2), (36, 40, 48, 255))
    x = pad
    for s in (16, 32, 48):
        tile = create_icon(s).resize((s * zoom, s * zoom), Image.Resampling.NEAREST)
        y = (sheet.size[1] - tile.size[1]) // 2
        sheet.paste(tile, (x, y), tile)
        x += tile.size[0] + pad
    sheet.save(os.path.join(ROOT, "assets", "icon_zoom_check.png"))
    print(f"OK: {OUT_ICO} ({os.path.getsize(OUT_ICO)} bytes)")
    print(f"preview: {OUT_PNG}")
    print(f"zoom: assets/icon_zoom_check.png  sizes={SIZES}")


if __name__ == "__main__":
    main()
