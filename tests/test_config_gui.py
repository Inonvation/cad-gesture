"""配置界面交互逻辑测试（扇区交换 / 保存 / 清除 / 恢复默认 / 撤销栈上限）

offscreen 平台运行；通过 monkeypatch 阻止写盘，只验证内存配置。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

import pytest
from PySide6.QtWidgets import QApplication, QMessageBox


@pytest.fixture(scope="module")
def app():
    a = QApplication.instance() or QApplication([])
    yield a


@pytest.fixture()
def gui(app, monkeypatch):
    from src import config_manager

    monkeypatch.setattr(config_manager, "save_config",
                        lambda cfg: True)  # 禁止写盘
    from src.qt_config_gui import QConfigGUI

    w = QConfigGUI()
    w._autosave_timer.stop()
    yield w
    w.close()


def _profile(w):
    return w.config["profiles"][w.current_profile]


def test_sector_swap_exchange(gui):
    """两个扇区都有命令：交换"""
    p = _profile(gui)
    p["sectors"]["0"] = {"label": "A", "key": "a", "description": "AAA"}
    p["sectors"]["1"] = {"label": "B", "key": "b", "description": "BBB"}
    gui._on_sector_swapped("inner", 0, "inner", 1)
    assert p["sectors"]["0"]["label"] == "B"
    assert p["sectors"]["1"]["label"] == "A"
    assert gui._undo_stack, "交换应记录撤销"


def test_sector_swap_move(gui):
    """目标扇区为空：移动"""
    p = _profile(gui)
    p["sectors"]["0"] = {"label": "A", "key": "a", "description": "AAA"}
    p["sectors"].pop("1", None)
    gui._on_sector_swapped("inner", 0, "inner", 1)
    assert "0" not in p["sectors"]
    assert p["sectors"]["1"]["label"] == "A"


def test_sector_swap_cross_layer(gui):
    """内层 → 外层 跨层交换"""
    p = _profile(gui)
    p["sectors"]["0"] = {"label": "A", "key": "a", "description": "AAA"}
    p["outer_sectors"]["3"] = {"label": "B", "key": "b", "description": "BBB"}
    gui._on_sector_swapped("inner", 0, "outer", 3)
    assert p["outer_sectors"]["3"]["label"] == "A"
    assert p["sectors"]["0"]["label"] == "B"


def test_sector_swap_empty_both(gui):
    """双方都为空：无操作、不记录撤销"""
    p = _profile(gui)
    p["sectors"].clear()
    gui._on_sector_swapped("inner", 0, "inner", 1)
    assert not gui._undo_stack


def test_sector_save_writes_config(gui):
    """点保存：写回配置 + 记录撤销 + 清除未保存标记"""
    p = _profile(gui)
    p["sectors"]["0"] = {"label": "旧", "key": "l", "description": "OLD"}
    gui._on_sector_selected("inner", 0)
    gui._popup.label_entry.setText("新命令")
    assert gui._popup._dirty
    gui._on_sector_saved()
    assert p["sectors"]["0"]["label"] == "新命令"
    assert not gui._popup._dirty
    assert len(gui._undo_stack) >= 1


def test_clear_all(gui, monkeypatch):
    """一键清除：全部清空并记录撤销"""
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    p = _profile(gui)
    assert any(p.get(k, {}) for k in
               ("sectors", "outer_sectors", "extension_sectors"))
    gui._clear_all_sectors()
    for k in ("sectors", "outer_sectors", "extension_sectors"):
        assert p[k] == {}
    assert gui._undo_stack


def test_clear_all_empty_no_undo(gui, monkeypatch):
    """本来就没命令：不弹框不记录"""
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    p = _profile(gui)
    for k in ("sectors", "outer_sectors", "extension_sectors"):
        p[k] = {}
    before = len(gui._undo_stack)
    gui._clear_all_sectors()
    assert len(gui._undo_stack) == before


def test_reset_default(gui, monkeypatch):
    """恢复默认：按 target+name 匹配默认方案"""
    monkeypatch.setattr(
        QMessageBox, "question",
        staticmethod(lambda *a, **k: QMessageBox.StandardButton.Yes))
    p = _profile(gui)
    for k in ("sectors", "outer_sectors", "extension_sectors"):
        p[k] = {}
    gui._reset_default_profile()
    total = sum(len(p.get(k, {})) for k in
                ("sectors", "outer_sectors", "extension_sectors"))
    assert total > 0
    assert gui._undo_stack


def test_undo_stack_limit(gui):
    """撤销栈上限 50 条"""
    for i in range(60):
        gui._push_undo()
    assert len(gui._undo_stack) == 50
    gui._undo()
    assert len(gui._undo_stack) == 49
def test_undo_redo_restores_config(gui):
    """撤销恢复上一次配置，重做恢复修改后的配置（_restore_config 会替换 config 对象，
    断言前须重新获取 profile 引用）"""
    p = _profile(gui)
    p["sectors"]["0"] = {"label": "A", "key": "a", "description": "AAA"}
    gui._push_undo()
    _profile(gui)["sectors"]["0"] = {"label": "B", "key": "b",
                                     "description": "BBB"}
    gui._undo()
    assert _profile(gui)["sectors"]["0"]["label"] == "A"
    gui._redo()
    assert _profile(gui)["sectors"]["0"]["label"] == "B"


def test_settings_anchor_excludes_test(gui):
    """侧边栏设置锚点 4 项（外观与尺寸/触发与反馈/常规/维护），不含「测试」"""
    texts = [gui.anchor_list.item(i).text()
             for i in range(gui.anchor_list.count())]
    assert texts == ["外观与尺寸", "触发与反馈", "常规", "维护"]


def test_open_test_via_maintenance(gui):
    """维护页「打开手势测试」按钮回调可切到测试页"""
    from src import qt_config_gui
    idx = 1 + [k for k, _ in qt_config_gui._SETTINGS_PAGES].index("test")
    gui._setting_pages["maintenance"].on_open_test()
    assert gui._main_stack.currentIndex() == idx
