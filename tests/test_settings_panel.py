# -*- coding: utf-8 -*-
"""设置面板测试：圆盘尺寸页半径顺序约束 + 扇区数量项已移除"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_size_page_clamps_radii_order():
    """半径乱序时按 中心圆 < 第一圈 < 第二圈 < 最外圈 夹紧，相邻间隔 >= 10"""
    _app()
    from src.qt_settings_panel import SizePage
    cfg = {"settings": {"menu_scale": 100, "dead_zone_radius": 200,
                        "ring_radius": 10, "outer_ring_radius": 20,
                        "ext_ring_radius": 30}}
    SizePage(cfg)
    s = cfg["settings"]
    assert s["dead_zone_radius"] < s["ring_radius"]
    assert s["ring_radius"] < s["outer_ring_radius"]
    assert s["outer_ring_radius"] < s["ext_ring_radius"]
    assert s["ring_radius"] - s["dead_zone_radius"] >= 10
    assert s["outer_ring_radius"] - s["ring_radius"] >= 10
    assert s["ext_ring_radius"] - s["outer_ring_radius"] >= 10


def test_size_page_no_sector_count_slider():
    """扇区数量设置项已移除（固定 8 扇区设计）"""
    _app()
    from src.qt_settings_panel import SizePage
    page = SizePage({"settings": {}})
    assert "sector_count" not in page._size_sliders


def test_trigger_page_keeps_hold_and_distance():
    """触发手感页仍保留长按延迟与触发距离"""
    _app()
    from src.qt_settings_panel import TriggerPage
    page = TriggerPage({"settings": {}})
    assert "hold_threshold_ms" in page._slider_labels
    assert "trigger_distance" in page._slider_labels