# -*- coding: utf-8 -*-
"""设置面板测试：圆盘尺寸页半径顺序约束 + 扇区数量项已移除"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_appearance_page_clamps_radii_order():
    """合并页（外观与尺寸）半径乱序时按 中心圆 < 第一圈 < 第二圈 < 最外圈 夹紧"""
    _app()
    from src.qt_settings_panel import AppearancePage
    cfg = {"settings": {"menu_scale": 100, "dead_zone_radius": 200,
                        "ring_radius": 10, "outer_ring_radius": 20,
                        "ext_ring_radius": 30}}
    AppearancePage(cfg)
    s = cfg["settings"]
    assert s["dead_zone_radius"] < s["ring_radius"]
    assert s["ring_radius"] < s["outer_ring_radius"]
    assert s["outer_ring_radius"] < s["ext_ring_radius"]
    assert s["ring_radius"] - s["dead_zone_radius"] >= 10
    assert s["outer_ring_radius"] - s["ring_radius"] >= 10
    assert s["ext_ring_radius"] - s["outer_ring_radius"] >= 10


def test_appearance_page_no_sector_count_slider():
    """扇区数量设置项已移除（固定 8 扇区设计）"""
    _app()
    from src.qt_settings_panel import AppearancePage
    page = AppearancePage({"settings": {}})
    assert "sector_count" not in page._size_sliders


def test_trigger_page_keeps_hold_and_distance():
    """触发手感页仍保留长按延迟与触发距离"""
    _app()
    from src.qt_settings_panel import TriggerPage
    page = TriggerPage({"settings": {}})
    assert "hold_threshold_ms" in page._slider_labels
    assert "trigger_distance" in page._slider_labels


def test_trigger_page_has_sw_ime_assist_switch():
    """SolidWorks 输入法助手开关在「触发与反馈」页，默认开启且能写回配置"""
    _app()
    from src.qt_settings_panel import TriggerPage
    cfg = {"settings": {}}
    page = TriggerPage(cfg)
    assert page.chk_ime_assist.isChecked() is True  # 默认开启
    page.chk_ime_assist.setChecked(False)
    assert cfg["settings"]["ime_assist_sw"] is False


def test_trigger_page_refresh_syncs_sw_ime_assist():
    """进入页面时用配置值回写助手开关（切换方案/重载后不串状态）"""
    _app()
    from src.qt_settings_panel import TriggerPage
    page = TriggerPage({"settings": {}})
    page.refresh({"settings": {"ime_assist_sw": False}})
    assert page.chk_ime_assist.isChecked() is False
    page.refresh({"settings": {"ime_assist_sw": True}})
    assert page.chk_ime_assist.isChecked() is True


def test_trigger_page_has_sw_key_pass_through_controls():
    """按键直通：处理方式下拉 + 键集 + 额外视口类名，默认「按键直通」"""
    _app()
    from src.qt_settings_panel import TriggerPage
    cfg = {"settings": {}}
    page = TriggerPage(cfg)
    assert page.ime_mode_combo.currentData() == "key"
    assert page.key_list_edit.text() == "A-Z,0-9,SPACE"
    assert page.extra_cls_edit.text() == ""
    # 切成布局切换 → 键集/类名对布局模式无意义，置灰
    page.ime_mode_combo.setCurrentIndex(
        page.ime_mode_combo.findData("layout"))
    assert cfg["settings"]["ime_assist_mode"] == "layout"
    assert page.key_list_edit.isEnabled() is False
    assert page.extra_cls_edit.isEnabled() is False
    page.ime_mode_combo.setCurrentIndex(page.ime_mode_combo.findData("key"))
    assert page.key_list_edit.isEnabled() is True


def test_trigger_page_refresh_syncs_sw_key_settings():
    """进入页面时用配置值回写处理方式/键集/类名（切方案后不串状态）"""
    _app()
    from src.qt_settings_panel import TriggerPage
    page = TriggerPage({"settings": {}})
    page.refresh({"settings": {"ime_assist_mode": "layout",
                               "sw_key_list": "E,F",
                               "sw_key_extra_classes": "gxwnd"}})
    assert page.ime_mode_combo.currentData() == "layout"
    assert page.key_list_edit.text() == "E,F"
    assert page.extra_cls_edit.text() == "gxwnd"
    assert page.key_list_edit.isEnabled() is False


def test_trigger_page_has_exclude_apps_field():
    """不弹圆盘的应用名单（SolidWorks 自带右键笔势，默认排除）"""
    _app()
    from src.qt_settings_panel import TriggerPage
    cfg = {"settings": {}}
    page = TriggerPage(cfg)
    assert page.exclude_edit.text() == "sldworks"
    page.refresh({"settings": {"gesture_exclude_apps": "sldworks,acad"}})
    assert page.exclude_edit.text() == "sldworks,acad"


def test_help_icons_have_tooltips():
    """各设置页的说明图标存在且 tooltip 非空（中文模式）"""
    _app()
    from src.qt_settings_panel import (_HelpIcon, AppearancePage, TriggerPage,
                                       AboutPage)
    for cls in (AppearancePage, TriggerPage, AboutPage):
        page = cls({"settings": {}})
        icons = page.findChildren(_HelpIcon)
        assert icons, f"{cls.__name__} 应有说明图标"
        for icon in icons:
            assert icon.help_text(), f"{cls.__name__} 存在空说明文案的图标"


def test_help_icons_follow_language():
    """切换英文后说明图标 tooltip 跟随翻译，且非空"""
    _app()
    from src import i18n
    from src.qt_settings_panel import _HelpIcon, TriggerPage
    page = TriggerPage({"settings": {}})
    icons = page.findChildren(_HelpIcon)
    assert icons
    try:
        i18n.set_language("en")
        page.retranslate()
        for icon in icons:
            assert icon.help_text(), "英文模式下说明文案不应为空"
            assert icon.help_text() != icon._help_zh, "英文模式下说明文案应已翻译"
    finally:
        i18n.set_language("zh")
        page.retranslate()



def test_radius_defaults_single_source():
    """设置页半径默认值必须与 menu_geometry 唯一来源一致"""
    _app()
    from src.qt_settings_panel import AppearancePage
    from src.menu_geometry import DEFAULT_RADII
    assert AppearancePage._RADIUS_DEFAULTS == DEFAULT_RADII
    assert tuple(AppearancePage._RADIUS_KEYS) == tuple(DEFAULT_RADII)
