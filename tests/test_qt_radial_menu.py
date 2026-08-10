"""运行时圆盘测试：窗口尺寸随配置更新（防裁切回归）+ 中心文字"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def _cfg(ext=185, theme="azure"):
    return {"settings": {"ext_ring_radius": ext, "ring_radius": 100,
                         "outer_ring_radius": 135, "menu_theme": theme}}


def test_window_resizes_with_ext_radius():
    """修尺寸裁切 bug：扩展圈半径改大后窗口必须跟着变大"""
    _app()
    from src.qt_radial_menu import QRadialMenu
    menu = QRadialMenu(_cfg(185))
    w1, h1 = menu.width(), menu.height()
    assert w1 >= 185 * 2  # 窗口至少覆盖整个扩展圈
    menu.update_config(_cfg(360))
    w2, h2 = menu.width(), menu.height()
    assert w2 > w1 and h2 > h1, f"窗口未随扩展圈半径增大: {w1}->{w2}"
    assert w2 >= 360 * 2


def test_center_texts_shows_profile_name():
    """无悬停时中心显示方案名（确认当前配置）"""
    _app()
    from src.qt_radial_menu import QRadialMenu
    menu = QRadialMenu(_cfg())
    profile = {"name": "AutoCAD-常用", "sectors": {}}
    menu._profile = profile
    label, sub = menu._center_texts()
    assert label == ""
    assert sub == "AutoCAD-常用"


def test_center_texts_shows_command_and_key():
    """悬停时中心显示命令名 + 快捷键"""
    _app()
    from src.qt_radial_menu import QRadialMenu
    menu = QRadialMenu(_cfg())
    menu._profile = {
        "name": "AutoCAD-常用",
        "sectors": {"0": {"label": "直线", "key": "l", "description": "LINE"}},
    }
    menu._highlighted_sector = 0
    menu._highlighted_outer = False
    label, sub = menu._center_texts()
    assert label == "直线"
    assert sub == "L"



def test_menu_scale_scales_radii():
    """menu_scale 缩放时各圈半径同步缩放，窗口尺寸随扩展圈变大"""
    _app()
    from src.qt_radial_menu import QRadialMenu
    cfg = _cfg(185)
    cfg["settings"]["menu_scale"] = 150
    menu = QRadialMenu(cfg)
    assert menu.ext_ring_radius == int(185 * 1.5)
    assert menu.ring_radius == int(100 * 1.5)
    assert menu.outer_ring_radius == int(135 * 1.5)
    assert menu.dead_zone == int(24 * 1.5)
    assert menu.width() >= int(185 * 1.5) * 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"[OK] {name}")
