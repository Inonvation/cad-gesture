"""Qt 渲染器模块测试"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gesture_engine import calc_sector
from src.theme import get_menu_theme
from src.qt_renderer import blend, layer_from_key, INNER, OUTER, EXTENSION


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


if __name__ == "__main__":
    test_calc_sector_eight_directions()
    test_calc_sector_dead_zone()
    test_layer_from_key()
    test_blend()
    test_theme_creation()
    print("\nAll tests passed!")
