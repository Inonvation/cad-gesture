"""内置矢量图标库与自定义图片解析 — 圆盘扇区图标

扇区配置字段 icon 的取值格式：
- "" 或缺失：无图标，显示文字
- "preset:<id>"：内置矢量图标（assets/icons/<id>.svg，单色，渲染时染色）
- "file:<绝对路径>"：本地图片拷贝（存放在 %APPDATA%\\CADGesture\\icons\\）

resolve_icon 把引用解析成可绘制的 QPixmap；preset 图标按传入颜色染色，
结果按 (kind, value, color, size) 缓存，避免每帧重渲染 SVG。
"""

import hashlib
import os
import shutil

from PySide6.QtCore import QByteArray, QRectF, Qt
from PySide6.QtGui import QColor, QPainter, QPixmap
from PySide6.QtSvg import QSvgRenderer

# 内置图标 id 列表（文件名 = id.svg），全部为单色 stroke 图标
ICON_IDS = [
    "line", "polyline", "circle", "arc", "rect", "ellipse", "spline",
    "hatch", "xline", "polygon", "erase", "copy", "move", "offset",
    "trim", "extend", "mirror", "rotate", "scale", "fillet", "explode",
    "block", "insert", "dim", "text", "osnap", "ortho", "polar", "grid",
    "layer",
]

_CACHE = {}
_CACHE_MAX = 512

_IMAGE_EXTS = {".png", ".jpg", ".jpeg", ".bmp", ".ico", ".svg", ".webp"}


def _assets_dir() -> str:
    """assets 目录：源码运行 = 仓库根/assets；onedir 打包 = _internal/assets"""
    return os.path.join(
        os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "assets")


def icons_dir() -> str:
    """自定义图标存放目录（%APPDATA%\\CADGesture\\icons），不存在则创建"""
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    d = os.path.join(base, "CADGesture", "icons")
    os.makedirs(d, exist_ok=True)
    return d


def preset_path(icon_id: str) -> str:
    """内置矢量图标文件路径"""
    return os.path.join(_assets_dir(), "icons", f"{icon_id}.svg")


def parse_icon_ref(ref) -> tuple:
    """把 icon 引用解析为 (kind, value)；非法引用返回 (None, None)"""
    if not ref or not isinstance(ref, str):
        return None, None
    if ref.startswith("preset:"):
        return "preset", ref[len("preset:"):]
    if ref.startswith("file:"):
        return "file", ref[len("file:"):]
    return None, None


def import_custom_icon(src_path: str) -> str:
    """把本地图片复制进 icons 目录（按内容 hash 命名去重），返回 file: 引用。

    Raises:
        ValueError: 文件不存在或格式不支持
    """
    src_path = os.path.abspath(src_path)
    if not os.path.isfile(src_path):
        raise ValueError("文件不存在")
    ext = os.path.splitext(src_path)[1].lower()
    if ext not in _IMAGE_EXTS:
        raise ValueError("不支持的图片格式: " + ext)
    with open(src_path, "rb") as f:
        digest = hashlib.sha1(f.read()).hexdigest()[:16]
    dst = os.path.join(icons_dir(), digest + ext)
    if not os.path.exists(dst):
        shutil.copy2(src_path, dst)
    return "file:" + dst


def list_custom_icons():
    """列出已保存的自定义图片，返回 [(file:引用, 文件名)]（按文件名排序）"""
    d = icons_dir()
    out = []
    if not os.path.isdir(d):
        return out
    for name in sorted(os.listdir(d)):
        ext = os.path.splitext(name)[1].lower()
        if ext in _IMAGE_EXTS:
            out.append(("file:" + os.path.join(d, name), name))
    return out


def clear_cache() -> None:
    """清空图标缓存（主题/颜色大改时调用）"""
    _CACHE.clear()


def _load_svg_pixmap(path: str, size: int) -> QPixmap:
    pm = QPixmap(size, size)
    pm.fill(Qt.transparent)
    with open(path, "rb") as f:
        data = QByteArray(f.read())
    renderer = QSvgRenderer(data)
    p = QPainter(pm)
    renderer.render(p, QRectF(0, 0, size, size))
    p.end()
    return pm


def _tint(pm: QPixmap, color: str) -> QPixmap:
    """把单色图标的非透明像素染成指定颜色（保留原 alpha）"""
    out = QPixmap(pm.size())
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap(0, 0, pm)
    p.setCompositionMode(QPainter.CompositionMode_SourceIn)
    p.fillRect(out.rect(), QColor(color))
    p.end()
    return out


def _load_file_pixmap(path: str, size: int):
    """加载本地图片并按比例缩放居中到透明画布；svg 走矢量渲染"""
    if path.lower().endswith(".svg"):
        return _load_svg_pixmap(path, size)
    pm = QPixmap(path)
    if pm.isNull():
        return None
    scaled = pm.scaled(size, size, Qt.KeepAspectRatio, Qt.SmoothTransformation)
    out = QPixmap(size, size)
    out.fill(Qt.transparent)
    p = QPainter(out)
    p.drawPixmap((size - scaled.width()) // 2, (size - scaled.height()) // 2,
                 scaled)
    p.end()
    return out


def resolve_icon(ref, color: str = "#888888", size: int = 24):
    """把扇区 icon 引用解析成 QPixmap；无法解析返回 None。

    - preset:<id>：内置 SVG，按 color 染色
    - file:<path>：本地图片原样绘制（不染色）
    """
    size = max(4, int(size))
    kind, value = parse_icon_ref(ref)
    if kind is None:
        return None
    key = (kind, value, color.lower() if kind == "preset" else "", size)
    cached = _CACHE.get(key)
    if cached is not None:
        return cached
    pm = None
    if kind == "preset":
        path = preset_path(value)
        if os.path.isfile(path):
            pm = _tint(_load_svg_pixmap(path, size), color)
    elif kind == "file":
        if os.path.isfile(value):
            pm = _load_file_pixmap(value, size)
    if pm is None:
        return None
    if len(_CACHE) >= _CACHE_MAX:
        _CACHE.clear()
    _CACHE[key] = pm
    return pm