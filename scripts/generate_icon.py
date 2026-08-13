"""生成 CAD 鼠标手势工具的图标 (assets/icon.ico)

与 Qt 圆盘菜单视觉统一：8 扇区 + 高亮扇区 + 中心高光 + 柔和投影。
"""
import io
import os
import math
import struct
from PIL import Image, ImageDraw

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)),
                        "..", "assets")
os.makedirs(ICON_DIR, exist_ok=True)


def _build_ico(imgs, path):
    """手动构造多尺寸 ICO（PNG 压缩条目，Vista+ 支持）。

    Pillow 12 的 ICO 保存存在回归：传 sizes + append_images 也只写出
    第一个尺寸（16x16），托盘/任务栏大图标会糊。这里按 ICO 规范直接
    拼 ICONDIR + 每条目 PNG 数据，保证 16~256 全尺寸入库。
    """
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


def create_layer(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx = cy = size / 2
    s = size / 256.0  # 以 256 为基准缩放

    def dot(cx_, cy_, r_, fill):
        draw.ellipse([cx_ - r_, cy_ - r_, cx_ + r_, cy_ + r_], fill=fill)

    # 1. 柔和投影（多层半透明同心圆）
    for k in range(7, 0, -1):
        alpha = int(26 - k * 3)
        if alpha <= 0:
            continue
        rr = (104 + k * 5) * s
        dot(cx, cy, rr, (0, 0, 0, alpha))

    # 2. 圆盘底座（深色底）
    dot(cx, cy, 102 * s, "#0f1319")

    # 3. 8 个扇区（pieslice，交替蓝，顶部扇区高亮）
    n = 8
    sec = 360.0 / n
    colors = ["#2b5278", "#1e3a5c"]
    outline_w = max(1, int(2 * s))
    for i in range(n):
        start = i * sec - 90 - sec / 2
        fill = "#38bdf8" if i == 0 else colors[i % 2]
        draw.pieslice([cx - 98 * s, cy - 98 * s, cx + 98 * s, cy + 98 * s],
                      start, start + sec, fill=fill,
                      outline="#0f1319", width=outline_w)

    # 4. 外圈高亮描边
    draw.ellipse([cx - 98 * s, cy - 98 * s, cx + 98 * s, cy + 98 * s],
                 outline="#3b6ea5", width=outline_w)

    # 5. 中心死区挖空
    dot(cx, cy, 32 * s, "#0d1017")
    dot(cx, cy, 26 * s, "#182940")

    # 6. 中心高光（亮蓝渐变 + 白点）
    dot(cx, cy, 17 * s, "#38bdf8")
    dot(cx, cy, 7 * s, "#ffffff")
    return img


sizes = [16, 32, 48, 64, 128, 256]
layers = [create_layer(s) for s in sizes]

ico_path = os.path.join(ICON_DIR, "icon.ico")
_build_ico(layers, ico_path)
print(f"OK: {ico_path}  ({os.path.getsize(ico_path)} bytes)  sizes={sizes}")
