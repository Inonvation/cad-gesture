"""Qt 渲染器模块测试"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.gesture_engine import calc_sector
from src.theme import get_menu_theme
from src.qt_renderer import (blend, layer_from_key, INNER, OUTER, EXTENSION,
                             draw_ring, draw_center)


def test_calc_sector_eight_directions():
    """测试 8 方向扇区计算（扇区0=下，顺时针）"""
    n = 8
    assert calc_sector(0, 100, n) == 0, f"下方向: {calc_sector(0, 100, n)}"
    assert calc_sector(100, 100, n) == 1, f"右下方向: {calc_sector(100, 100, n)}"
    assert calc_sector(100, 0, n) == 2, f"右方向: {calc_sector(100, 0, n)}"
    assert calc_sector(100, -100, n) == 3, f"右上方向: {calc_sector(100, -100, n)}"
    assert calc_sector(0, -100, n) == 4, f"上方向: {calc_sector(0, -100, n)}"
    assert calc_sector(-100, -100, n) == 5, f"左上方向: {calc_sector(-100, -100, n)}"
    assert calc_sector(-100, 0, n) == 6, f"左方向: {calc_sector(-100, 0, n)}"
    assert calc_sector(-100, 100, n) == 7, f"左下方向: {calc_sector(-100, 100, n)}"


def test_calc_sector_dead_zone():
    """测试死区（距离为0）不会报错"""
    result = calc_sector(0, 0, 8)
    assert 0 <= result < 8


def test_calc_sector_edge_angles():
    """扇区边界角度计算（8 扇区，每 45°）"""
    n = 8
    # 正上、正下、正左、正右 各方向的扇区
    assert calc_sector(0, -1, n) == 4          # 上
    assert calc_sector(0, 1, n) == 0           # 下
    assert calc_sector(1, 0, n) == 2           # 右
    assert calc_sector(-1, 0, n) == 6          # 左
    # 对角线方向
    assert calc_sector(1000, -1, n) == 2           # 接近正右
    assert calc_sector(1000, -1000, n) == 3        # 右上对角线
    assert calc_sector(-1000, -1000, n) == 5       # 左上
    # 大位移不溢出
    for dx, dy in [(999999, 1), (-999999, 999999), (0, 999999)]:
        assert 0 <= calc_sector(dx, dy, n) < n


def test_layer_from_key():
    """配置 sector 字段名 -> 层名映射（曾因字符串切片写错导致外层高亮失效）"""
    assert layer_from_key("sectors") == INNER
    assert layer_from_key("outer_sectors") == OUTER
    assert layer_from_key("extension_sectors") == EXTENSION


def test_blend():
    """颜色线性插值：黑色到白色，中间应为灰"""
    c = blend("#000000", "#ffffff", 0.5)
    assert 127 <= c.red() <= 128
    assert c.green() == c.red()
    assert c.blue() == c.red()
    # 端点
    assert blend("#112233", "#445566", 0.0).red() == 0x11
    assert blend("#112233", "#445566", 1.0).red() == 0x44


def test_theme_creation():
    """测试圆盘主题创建"""
    t = get_menu_theme("azure")
    assert t is not None
    assert t.inner.normal is not None
    assert t.inner.highlight is not None
    assert t.center_text is not None


def test_draw_ring_offscreen():
    """离屏绘制三层圆盘不崩溃（offscreen 平台，无需显示器）"""
    from PySide6.QtGui import QImage, QPainter
    from PySide6.QtWidgets import QApplication

    app = QApplication.instance() or QApplication([])
    img = QImage(600, 600, QImage.Format_ARGB32)
    img.fill(0)
    p = QPainter(img)
    t = get_menu_theme("azure")
    sectors = {"0": {"label": "直线", "key": "l", "description": "LINE"},
               "2": {"label": "圆", "key": "c", "description": "CIRCLE"}}
    # 三层绘制（运行时高亮层 + 空扇区 + 标签）
    draw_ring(p, 300, 300, 180, 240, 8, sectors, t.extension,
              layer=EXTENSION, hl_idx=0, hl_layer=EXTENSION)
    draw_ring(p, 300, 300, 100, 180, 8, sectors, t.outer,
              layer=OUTER, hl_idx=-1)
    draw_ring(p, 300, 300, 30, 100, 8, sectors, t.inner,
              layer=INNER, sel=("inner", 2))
    draw_center(p, 300, 300, 30, t, 600, "测试")
    p.end()
    assert not img.isNull()
    app.processEvents()


if __name__ == "__main__":
    test_calc_sector_eight_directions()
    test_calc_sector_dead_zone()
    test_calc_sector_edge_angles()
    test_layer_from_key()
    test_blend()
    test_theme_creation()
    test_draw_ring_offscreen()
    print("\nAll tests passed!")
