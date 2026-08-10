# -*- coding: utf-8 -*-
"""圆盘几何统一测试：menu_geometry 与运行时/预览取同一套半径"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from src.menu_geometry import menu_scale, scaled_radius, scaled_radii, DEFAULT_RADII


def _app():
    from PySide6.QtWidgets import QApplication
    return QApplication.instance() or QApplication([])


def test_defaults_match_runtime():
    assert DEFAULT_RADII == {"dead_zone_radius": 24, "ring_radius": 70,
                             "outer_ring_radius": 135, "ext_ring_radius": 185}


def test_scaled_radius_defaults():
    assert scaled_radius({}, "dead_zone_radius") == 24
    assert scaled_radius({}, "ring_radius") == 70
    assert scaled_radius({}, "outer_ring_radius") == 135
    assert scaled_radius({}, "ext_ring_radius") == 185


def test_scaled_radius_with_menu_scale():
    s = {"menu_scale": 150, "ext_ring_radius": 185}
    assert scaled_radius(s, "ext_ring_radius") == int(185 * 1.5)
    assert scaled_radius(s, "ring_radius") == int(70 * 1.5)


def test_scaled_radii_keys():
    r = scaled_radii({"menu_scale": 100})
    assert set(r) == set(DEFAULT_RADII)
    assert r["ring_radius"] == 70


def test_geometry_consistent_across_modules():
    """运行时圆盘与手势引擎的半径必须等于 menu_geometry 计算结果"""
    _app()
    cfg = {"settings": {"menu_scale": 120, "dead_zone_radius": 24,
                        "ring_radius": 70, "outer_ring_radius": 135,
                        "ext_ring_radius": 185}}
    from src.qt_radial_menu import QRadialMenu
    from src.gesture_engine import GestureEngine
    menu = QRadialMenu(cfg)
    engine = GestureEngine(config=cfg, on_gesture=lambda *a: None,
                           on_gesture_feedback=lambda *a: None,
                           on_menu_show=lambda *a: None,
                           on_menu_hide=lambda: None,
                           on_extension_hint=lambda *a: None)
    s = cfg["settings"]
    assert menu.ring_radius == scaled_radius(s, "ring_radius") == engine.ring_radius
    assert (menu.outer_ring_radius == scaled_radius(s, "outer_ring_radius")
            == engine.outer_ring_radius)
    assert menu.ext_ring_radius == scaled_radius(s, "ext_ring_radius")
    assert menu.dead_zone == scaled_radius(s, "dead_zone_radius") == engine.dead_zone


def test_preview_uses_real_radii():
    """编辑页预览几何与运行时一致（修复硬编码 30/100/180/240 与忽略缩放）"""
    _app()
    from src.qt_preview import QRadialPreview
    cfg = {"settings": {"menu_scale": 150, "dead_zone_radius": 24,
                        "ring_radius": 70, "outer_ring_radius": 135,
                        "ext_ring_radius": 185}}
    preview = QRadialPreview()
    preview.config = cfg
    r = preview._radii()
    assert r["ring_radius"] == int(70 * 1.5)
    assert r["ext_ring_radius"] == int(185 * 1.5)
    # 自适应缩放后最外圈像素半径落在窗口内
    preview.resize(400, 400)
    assert 0 < preview.outermost_radius_px() <= 200