# -*- coding: utf-8 -*-
"""不弹圆盘应用名单控件：解析 / 归一化 / 列表交互（存储仍是逗号分隔字符串）"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_parse_entries_dedup_and_order():
    """逗号/分号/空白分隔 → 小写去重保序；空串 / None → 空列表"""
    from src.qt_exclude_apps import join_entries, parse_entries
    assert parse_entries("sldworks") == ["sldworks"]
    assert parse_entries(" SLDWORKS, acad ，sldworks") == ["sldworks", "acad"]
    assert parse_entries("a；b， c") == ["a", "b", "c"]
    assert parse_entries("") == []
    assert parse_entries(None) == []
    assert join_entries(["a", "b"]) == "a,b"


def test_normalize_entry():
    """粘贴带路径 / 引号 / .exe 后缀的内容都归一成无后缀小写关键字"""
    from src.qt_exclude_apps import normalize_entry
    assert normalize_entry(r"C:\Program Files\X\EXCEL.EXE") == "excel"
    assert normalize_entry('"D:\\tools\\Notepad.exe"') == "notepad"
    assert normalize_entry("  Excel.exe ") == "excel"
    assert normalize_entry("a/b/c.EXE") == "c"
    assert normalize_entry("sldworks") == "sldworks"
    assert normalize_entry("") == ""
    assert normalize_entry(None) == ""


def test_widget_add_remove_and_changed_signal():
    """列表增删去重，changed 发归一化后的存储串"""
    from src.qt_exclude_apps import ExcludeAppsWidget
    w = ExcludeAppsWidget("sldworks")
    seen = []
    w.changed.connect(seen.append)
    assert w.add_entry(r"D:\X\Notepad.EXE") is True
    assert w.text() == "sldworks,notepad"
    assert w.add_entry("notepad") is False          # 大小写不敏感去重
    assert len(seen) == 1
    assert w.remove_entry("notepad") is True
    assert w.text() == "sldworks"
    assert w.remove_entry("nope") is False          # 不存在的不发信号
    assert seen == ["sldworks,notepad", "sldworks"]
    assert w.add_entry("   ") is False              # 空名不加入


def test_widget_set_text_rebuilds_and_empty_placeholder():
    """set_text 重建列表并去重；名单为空就是干净的空列表（无占位行）"""
    from PySide6.QtWidgets import QLabel
    from src.qt_exclude_apps import ExcludeAppsWidget
    w = ExcludeAppsWidget("a, b ,a")
    assert w.text() == "a,b"
    assert w.list.count() == 2
    w.set_text("")
    assert w.list.count() == 0
    # 空名单时列表框仍保持最小高度，不会缩成一条
    assert w.list.height() >= w._MIN_VISIBLE * w._ROW_H
    w.set_text("x")
    assert w.list.count() == 1
    assert w.list.itemWidget(w.list.item(0)).findChild(QLabel).text() == "x"


def test_pick_button_signal_feeds_widget():
    """拖动拾取识别到 exe（信号直连 add_entry）→ 归一化入列表"""
    _app()
    from src.qt_exclude_apps import ExcludeAppsWidget
    w = ExcludeAppsWidget("")
    w.btn_pick.picked.emit(r"E:\CAD\ZWCAD.EXE")
    assert w.text() == "zwcad"


def test_add_feedback_shows_toast_on_duplicate_and_success():
    """拾取/添加的操作反馈：成功入列、重复添加都有浮层提示（不静默失败）"""
    _app()
    from src.qt_exclude_apps import ExcludeAppsWidget
    w = ExcludeAppsWidget("sldworks")
    w._add_with_feedback(r"D:\X\ACAD.EXE")
    assert w.text() == "sldworks,acad"
    assert w._toast_timer.isActive()
    assert w._toast_lbl.isVisibleTo(w.list)
    w._add_with_feedback("acad")                    # 重复 → 提示且不变更
    assert w.text() == "sldworks,acad"
    assert w._toast_timer.isActive()


def test_empty_state_hint_visibility():
    """空名单显示占位提示，添加后隐藏；反馈浮层结束后占位恢复"""
    _app()
    from src.qt_exclude_apps import ExcludeAppsWidget
    w = ExcludeAppsWidget("")
    w.show()
    assert w._empty_lbl.isVisible()
    w.add_entry("a")
    assert not w._empty_lbl.isVisible()
    w.set_text("")
    assert w._empty_lbl.isVisibleTo(w.list)
    w._toast_timer.stop()                           # 模拟反馈超时
    w._update_overlays()
    assert w._empty_lbl.isVisible()
