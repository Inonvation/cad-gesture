# -*- coding: utf-8 -*-
"""生成 Inno Setup 安装向导侧边图（assets/installer_wizard.bmp）

Inno 6.3+ 支持 BMP；标准尺寸 164x314（左侧大图）。
设计语言与 installer_splash 一致：深蓝主色 + 八扇区圆环。

用法：Python312 python scripts/generate_wizard_image.py
"""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "installer_wizard.bmp")

W, H = 164, 314
BG = (43, 76, 126)          # 深蓝底
CARD = (255, 255, 255)
INK_SOFT = (180, 196, 216)
SECTOR_LIGHT = (72, 110, 160)
RING = (200, 216, 236)

FONT_DIR = r"C:\Windows\Fonts"
FONT_TITLE = os.path.join(FONT_DIR, "msyhbd.ttc")
FONT_NOTE = os.path.join(FONT_DIR, "msyh.ttc")


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        return ImageFont.load_default()


def _draw_dial(draw, cx, cy, r_inner, sector_r, highlight):
    n = 8
    for i in range(n):
        a0 = i * (360 / n) - 90
        a1 = a0 + 360 / n
        fill = (255, 255, 255) if i == highlight else SECTOR_LIGHT
        draw.pieslice([cx - sector_r, cy - sector_r,
                       cx + sector_r, cy + sector_r], a0, a1, fill=fill)
    draw.ellipse([cx - r_inner, cy - r_inner,
                  cx + r_inner, cy + r_inner], fill=BG)
    draw.ellipse([cx - r_inner, cy - r_inner,
                  cx + r_inner, cy + r_inner], outline=RING, width=2)
    draw.ellipse([cx - sector_r, cy - sector_r,
                  cx + sector_r, cy + sector_r], outline=RING, width=2)


def main():
    img = Image.new("RGB", (W, H), BG)
    draw = ImageDraw.Draw(img)
    _draw_dial(draw, cx=W // 2, cy=118, r_inner=16, sector_r=52, highlight=0)
    draw.ellipse([W // 2 - 8, 118 - 8, W // 2 + 8, 118 + 8],
                 fill=(255, 255, 255), outline=BG, width=2)

    f_title = _font(FONT_TITLE, 16)
    f_note = _font(FONT_NOTE, 11)
    title = "CAD Gesture"
    note1 = "长按右键"
    note2 = "八方向圆盘"

    def _center_text(y, text, font, fill):
        bbox = draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        draw.text(((W - tw) // 2, y), text, font=font, fill=fill)

    _center_text(198, title, f_title, CARD)
    _center_text(232, note1, f_note, INK_SOFT)
    _center_text(250, note2, f_note, INK_SOFT)

    # 保存为 BMP（无损、向导友好）
    img.save(OUT, format="BMP")
    print("saved:", OUT)


if __name__ == "__main__":
    main()
