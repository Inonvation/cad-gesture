# -*- coding: utf-8 -*-
"""生成 Velopack 安装器的 splash 图（assets/installer_splash.png）

设计：克制/质感 —— 左侧八扇区圆环呼应手势圆盘，右侧应用名 + 一句说明。
深蓝主色 + 浅灰扇区，白底圆角卡片（安装器 splash 铺在窗口内，四周留边）。

用法：Python312 python scripts/generate_splash.py
依赖：Pillow（requirements.txt 已有）
"""

import os

from PIL import Image, ImageDraw, ImageFont

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
OUT = os.path.join(ROOT, "assets", "installer_splash.png")

W, H = 560, 315          # 画布（splash 显示时会等比缩放，四周留空）
CARD = (255, 255, 255)   # 白底
INK = (43, 76, 126)      # 深蓝（主色）
INK_SOFT = (96, 116, 141)  # 副文字
SECTOR_LIGHT = (233, 238, 244)  # 浅灰扇区
RING = (148, 164, 184)   # 圆环描边

FONT_DIR = r"C:\Windows\Fonts"
FONT_TITLE = os.path.join(FONT_DIR, "msyhbd.ttc")   # 微软雅黑 Bold
FONT_BODY = os.path.join(FONT_DIR, "msyh.ttc")      # 微软雅黑


def _font(path, size):
    try:
        return ImageFont.truetype(path, size)
    except OSError:
        # 回退默认字体（仅影响字形美感，不阻断生成）
        return ImageFont.load_default()


def _draw_dial(draw, cx, cy, r_inner, sector_r, highlight):
    """八扇区圆环：8 段扇形楔形，highlight 扇区用主色其余浅灰，中心盖圆成环。"""
    n = 8
    for i in range(n):
        a0 = i * (360 / n) - 90
        a1 = a0 + 360 / n
        fill = INK if i == highlight else SECTOR_LIGHT
        draw.pieslice([cx - sector_r, cy - sector_r,
                       cx + sector_r, cy + sector_r], a0, a1, fill=fill)
    # 中心盖出环形效果
    draw.ellipse([cx - r_inner, cy - r_inner,
                  cx + r_inner, cy + r_inner], fill=CARD)
    draw.ellipse([cx - r_inner, cy - r_inner,
                  cx + r_inner, cy + r_inner], outline=RING, width=2)
    draw.ellipse([cx - sector_r, cy - sector_r,
                  cx + sector_r, cy + sector_r], outline=RING, width=2)


def main():
    img = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    # 白底圆角卡片（splash 直接铺在窗口，留 6px 透明边让窗口底色透出）
    draw.rounded_rectangle([6, 6, W - 6, H - 6], radius=20, fill=CARD)
    # 左侧圆盘图形
    _draw_dial(draw, cx=128, cy=H // 2, r_inner=34, sector_r=96,
               highlight=0)
    draw.ellipse([128 - 12, H // 2 - 12, 128 + 12, H // 2 + 12],
                 fill=INK, outline=CARD, width=3)
    # 右侧文字
    f_title = _font(FONT_TITLE, 46)
    f_sub = _font(FONT_BODY, 22)
    f_note = _font(FONT_BODY, 15)
    draw.text((250, 108), "CAD Gesture", font=f_title, fill=INK)
    draw.text((252, 172), "长按右键 · 呼出八方向命令圆盘",
              font=f_sub, fill=INK_SOFT)
    draw.text((252, 236), "支持 AutoCAD 2025+ / 中望CAD",
              font=f_note, fill=(168, 178, 192))
    img.save(OUT)
    print("saved:", OUT)


if __name__ == "__main__":
    main()
