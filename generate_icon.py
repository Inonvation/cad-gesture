"""生成 CAD 鼠标手势工具的图标 (assets/icon.ico)"""
import os, math
from PIL import Image, ImageDraw

ICON_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "assets")
os.makedirs(ICON_DIR, exist_ok=True)


def create_layer(size: int) -> Image.Image:
    img = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    cx, cy = size / 2, size / 2
    margin = max(1, size // 12)
    r = size / 2 - margin

    draw.ellipse(
        [cx - r, cy - r, cx + r, cy + r],
        fill="#2b5278", outline="#0078D4",
        width=max(2, size // 32),
    )

    for i in range(8):
        angle = -math.pi / 2 + i * math.pi / 4
        mid_angle = angle + math.pi / 8
        mid_r = r * 0.62
        mx = cx + mid_r * math.cos(mid_angle)
        my = cy + mid_r * math.sin(mid_angle)
        dot_r = max(2, size // 20)
        color = "#0078D4" if i % 2 == 0 else "#4a90d9"
        draw.ellipse(
            [mx - dot_r, my - dot_r, mx + dot_r, my + dot_r],
            fill=color,
        )

    center_r = max(2, size // 14)
    draw.ellipse(
        [cx - center_r, cy - center_r, cx + center_r, cy + center_r],
        fill="#ffffff",
    )
    return img


sizes = [16, 32, 48, 64, 128, 256]
layers = [create_layer(s) for s in sizes]

ico_path = os.path.join(ICON_DIR, "icon.ico")
layers[0].save(ico_path, format="ICO", sizes=[(s, s) for s in sizes], append_images=layers[1:])
print(f"OK: {ico_path}  ({os.path.getsize(ico_path)} bytes)  sizes={sizes}")