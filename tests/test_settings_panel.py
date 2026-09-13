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
    """高级区：处理方式下拉 + 键集 + 额外视口类名，默认「按键直通」且默认真折叠"""
    _app()
    from src.qt_settings_panel import TriggerPage
    cfg = {"settings": {}}
    page = TriggerPage(cfg)
    assert page._adv_toggle.isChecked() is False  # 默认折叠，不干扰小白
    assert page._ime_adv.isHidden() is True
    page._adv_toggle.setChecked(True)
    assert page._ime_adv.isHidden() is False
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
    page._adv_toggle.setChecked(True)
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
    assert page.exclude_widget.text() == "sldworks"
    # 列表增删 → 归一化后写回配置（changed 信号联动 _set）
    assert page.exclude_widget.add_entry(r"D:\X\ACAD.EXE") is True
    assert cfg["settings"]["gesture_exclude_apps"] == "sldworks,acad"
    # 重复添加（大小写不敏感）不写配置
    assert page.exclude_widget.add_entry("acad") is False
    assert cfg["settings"]["gesture_exclude_apps"] == "sldworks,acad"
    # 进页面时按配置重建列表，重复项会被去重（refresh 换用新 config dict）
    cfg2 = {"settings": {"gesture_exclude_apps": "sldworks,acad,sldworks"}}
    page.refresh(cfg2)
    assert page.exclude_widget.text() == "sldworks,acad"
    assert page.exclude_widget.list.count() == 2
    # 删除条目 → 同步写回当前配置
    page.exclude_widget.remove_entry("acad")
    assert cfg2["settings"]["gesture_exclude_apps"] == "sldworks"


def test_trigger_page_pause_hotkey_editor():
    """暂停快捷键：合法组合写配置，非法组合回退，清除恢复为不启用"""
    _app()
    from PySide6.QtGui import QKeySequence
    from src.qt_settings_panel import TriggerPage
    cfg = {"settings": {}}
    page = TriggerPage(cfg)
    # 默认留空 = 不启用
    assert page.hotkey_edit.keySequence().isEmpty()
    assert cfg["settings"].get("pause_hotkey", "") == ""
    # 录制合法组合 → 写入配置
    page.hotkey_edit.setKeySequence(QKeySequence("Ctrl+Alt+P"))
    page._on_pause_hotkey_changed()
    assert cfg["settings"]["pause_hotkey"] == "Ctrl+Alt+P"
    # 非法组合（裸字母会全局吞打字）→ 拒绝并回退到上一个有效值
    page.hotkey_edit.setKeySequence(QKeySequence("P"))
    page._on_pause_hotkey_changed()
    assert cfg["settings"]["pause_hotkey"] == "Ctrl+Alt+P"
    # 清除 = 不启用
    page._clear_pause_hotkey()
    assert cfg["settings"]["pause_hotkey"] == ""
    assert page.hotkey_edit.keySequence().isEmpty()


def test_trigger_page_refresh_syncs_pause_hotkey():
    """进入页面时用配置值回写快捷键（切方案/重载后不串状态）"""
    _app()
    from PySide6.QtGui import QKeySequence
    from src.qt_settings_panel import TriggerPage
    page = TriggerPage({"settings": {}})
    page.refresh({"settings": {"pause_hotkey": "Ctrl+Alt+K"}})
    assert page.hotkey_edit.keySequence() == QKeySequence("Ctrl+Alt+K")
    page.refresh({"settings": {}})
    assert page.hotkey_edit.keySequence().isEmpty()


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
