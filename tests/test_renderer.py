"""渲染器模块测试"""
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import math
from src.gesture_engine import calc_sector
from src.theme import get_theme, ThemeColors
from src.renderer import draw_ring, ring_state_normal, ring_state_preview, sector_angles


def test_calc_sector_eight_directions():
    """测试 8 方向扇区计算（扇区0=下，顺时针）"""
    n = 8
    # 下 (屏幕+y) → 扇区 0
    assert calc_sector(0, 100, n) == 0, f"下方向: {calc_sector(0, 100, n)}"
    # 右下
    assert calc_sector(100, 100, n) == 1, f"右下方向: {calc_sector(100, 100, n)}"
    # 右
    assert calc_sector(100, 0, n) == 2, f"右方向: {calc_sector(100, 0, n)}"
    # 右上
    assert calc_sector(100, -100, n) == 3, f"右上方向: {calc_sector(100, -100, n)}"
    # 上 (屏幕-y) → 扇区 4
    assert calc_sector(0, -100, n) == 4, f"上方向: {calc_sector(0, -100, n)}"
    # 左上
    assert calc_sector(-100, -100, n) == 5, f"左上方向: {calc_sector(-100, -100, n)}"
    # 左
    assert calc_sector(-100, 0, n) == 6, f"左方向: {calc_sector(-100, 0, n)}"
    # 左下
    assert calc_sector(-100, 100, n) == 7, f"左下方向: {calc_sector(-100, 100, n)}"
    print("[OK] 8 directions")


def test_calc_sector_dead_zone():
    """测试死区（距离为0）不会报错"""
    result = calc_sector(0, 0, 8)
    assert 0 <= result < 8, f"死区: {result}"
    print("[OK]  死区计算通过")


def test_sector_angles():
    """测试扇区角度计算"""
    start, extent = sector_angles(8, 0)
    # 8扇区，每个45度，第一个扇区从 -90 - 22.5 = -112.5 开始
    assert abs(start + 112.5) < 0.1, f"起始角度: {start}"
    assert abs(extent - 45) < 0.1, f"展角: {extent}"
    print("[OK]  扇区角度计算通过")


def test_theme_creation():
    """测试主题创建"""
    dark = get_theme(True)
    light = get_theme(False)
    assert isinstance(dark, ThemeColors)
    assert dark.inner.normal == "#2a4f78"
    assert light.inner.normal == "#d4e8f8"
    assert dark.bg != light.bg
    print("[OK]  主题创建通过")


def test_ring_state_normal():
    """测试运行时菜单状态"""
    t = get_theme(True)
    # 高亮状态
    state = ring_state_normal(t.inner, True, True)
    assert state["fill"] == t.inner.highlight
    assert state["width"] == 2
    # 正常状态
    state = ring_state_normal(t.inner, True, False)
    assert state["fill"] == t.inner.normal
    assert state["width"] == 1
    # 空状态
    state = ring_state_normal(t.inner, False, False)
    assert state["fill"] == t.inner.empty
    print("[OK]  运行时状态通过")


def test_ring_state_preview():
    """测试配置预览状态"""
    t = get_theme(True)
    # 选中
    state = ring_state_preview(t.inner, True, True, False, t.border, t.accent_dim)
    assert state["fill"] == t.inner.highlight
    assert state["width"] == 2
    # Hover
    state = ring_state_preview(t.inner, True, False, True, t.border, t.accent_dim)
    assert state["fill"] == t.inner.hover
    # 正常
    state = ring_state_preview(t.inner, True, False, False, t.border, t.accent_dim)
    assert state["fill"] == t.inner.normal
    # 空
    state = ring_state_preview(t.inner, False, False, False, t.border, t.accent_dim)
    assert state["fill"] == t.inner.empty
    print("[OK]  预览状态通过")


if __name__ == "__main__":
    test_calc_sector_eight_directions()
    test_calc_sector_dead_zone()
    test_sector_angles()
    test_theme_creation()
    test_ring_state_normal()
    test_ring_state_preview()
    print("\nAll tests passed!")