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
    """侧边栏设置锚点 3 项（外观与尺寸/触发与反馈/关于），不含「测试」"""
    texts = [gui.anchor_list.item(i).text()
             for i in range(gui.anchor_list.count())]
    assert texts == ["外观与尺寸", "触发与反馈", "关于"]


def test_open_test_via_maintenance(gui):
    """关于页「打开手势测试」按钮回调可切到测试页"""
    from src import qt_config_gui
    idx = 1 + [k for k, _ in qt_config_gui._SETTINGS_PAGES].index("test")
    gui._setting_pages["about"].on_open_test()
    assert gui._main_stack.currentIndex() == idx


# ========== 卡片式方案列表（折叠 / 当前方案 / 拖动排序 / 添加应用） ==========

def test_card_default_collapsed_and_current(gui):
    """默认全部折叠；卡片头部显示应用名与当前方案次标题"""
    gui._refresh_profiles()
    targets = gui.profile_list.order()
    assert targets == ["autocad", "zwcad"]
    for t in targets:
        assert gui._collapsed.get(t) is True
        card = gui._cards[t]
        title = card.header.title.text()
        assert "AutoCAD" in title or "中望" in title
        assert card.header.current.text() != ""


def test_card_toggle_expand_collapse(gui):
    """点击卡片头折叠/展开：状态切换正确，动画结束后方案列表显隐正确。

    offscreen 平台不推进 QVariantAnimation，这里直接断言状态机，
    并用 _on_anim_finished 模拟动画完成回调。
    """
    gui._refresh_profiles()
    card = gui._cards["autocad"]
    # 展开：body 可见，动画结束后恢复无限制高度
    gui._toggle_card("autocad")
    assert gui._collapsed["autocad"] is False
    assert card._expanded is True
    assert card.body.isHidden() is False
    card._on_anim_finished()
    assert card.body.maximumHeight() == 16777215
    # 折叠：动画结束后 body 隐藏
    gui._toggle_card("autocad")
    assert gui._collapsed["autocad"] is True
    assert card._expanded is False
    card._on_anim_finished()
    assert card.body.isHidden() is True


def test_add_custom_target_shows_card(gui):
    """添加自定义应用：出现新卡片并可按 target 匹配方案"""
    from src.config_manager import add_custom_target, get_profile_for_window
    ok, err = add_custom_target(gui.config, "SolidWorks", "sldworks.exe")
    assert ok and err is None
    gui._refresh_profiles()
    targets = gui.profile_list.order()
    assert "app_sldworks" in targets
    prof = get_profile_for_window(gui.config, "app_sldworks")
    assert prof is not None and prof.get("name") == "SolidWorks"


def test_card_order_change_persists(gui):
    """拖动排序回调写回 settings.app_order"""
    from src.config_manager import add_custom_target
    add_custom_target(gui.config, "SolidWorks", "sldworks.exe")
    gui._refresh_profiles()
    gui._on_card_order_changed(["autocad", "app_sldworks", "zwcad"])
    assert gui.config["settings"]["app_order"] == [
        "autocad", "app_sldworks", "zwcad"]


def test_app_menu_builtin_has_no_delete(gui):
    """内置应用菜单不含「删除此应用」，自定义应用含"""
    from src.config_manager import add_custom_target
    gui._refresh_profiles()
    builtin_acts = [a.text() for a in gui._build_app_menu("autocad").actions()]
    assert not any("删除" in a for a in builtin_acts)
    add_custom_target(gui.config, "SolidWorks", "sldworks.exe")
    gui._refresh_profiles()
    custom_acts = [a.text() for a in gui._build_app_menu("app_sldworks").actions()]
    assert any("删除" in a for a in custom_acts)


def test_card_list_drop_reorder(app):
    """卡片容器拖动排序：drop 到末尾后顺序与回调正确"""
    from PySide6.QtCore import Qt, QPointF, QMimeData
    from PySide6.QtGui import QDropEvent
    from src.qt_config_gui import (_CardListWidget, _ProfileCard, _CARD_MIME)

    lst = _CardListWidget()
    changed = []
    lst.on_order_changed = lambda o: changed.append(list(o))
    for t in ("a", "b", "c"):
        lst.add_card(_ProfileCard(t, t, on_toggle=lambda: None))
    lst.show()
    for _ in range(5):
        app.processEvents()
    mime = QMimeData()
    mime.setData(_CARD_MIME, b"a")
    # 用足够大的 y 强制插到末尾
    ev = QDropEvent(QPointF(10, 100000), Qt.MoveAction, mime,
                    Qt.LeftButton, Qt.NoModifier)
    lst.dropEvent(ev)
    assert lst.order() == ["b", "c", "a"]
    assert changed and changed[-1] == ["b", "c", "a"]


def test_card_header_drag_vs_click(app):
    """卡片头：按下移动超阈值触发拖动，原地松开触发折叠（拖动与点击分离）"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from src.qt_config_gui import _CardListWidget, _ProfileCard

    lst = _CardListWidget()
    card = _ProfileCard("a", "A", on_toggle=None)
    lst.add_card(card)
    started, toggled = [], []
    card.header._on_toggle = lambda: toggled.append(1)
    lst.start_drag = lambda c: started.append(c)

    h = card.header
    press = QMouseEvent(QEvent.MouseButtonPress, QPointF(20, 15),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    h.mousePressEvent(press)
    move = QMouseEvent(QEvent.MouseMove, QPointF(60, 15),
                       Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
    h.mouseMoveEvent(move)
    assert len(started) == 1 and started[0] is card
    assert not toggled

    # 原地点击：press + release -> toggle，不触发拖动
    card2 = _ProfileCard("b", "B", on_toggle=None)
    toggled2 = []
    card2.header._on_toggle = lambda: toggled2.append(1)
    press2 = QMouseEvent(QEvent.MouseButtonPress, QPointF(20, 15),
                         Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    card2.header.mousePressEvent(press2)
    rel2 = QMouseEvent(QEvent.MouseButtonRelease, QPointF(20, 15),
                       Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    card2.header.mouseReleaseEvent(rel2)
    assert toggled2 == [1]




def test_window_pick_overlay_click_does_not_confirm(app):
    """窗口捕捉覆盖层：点击不提前确认且鼠标穿透，倒计时结束自动确认"""
    from PySide6.QtCore import QEvent, QPointF, Qt
    from PySide6.QtGui import QMouseEvent
    from src.qt_config_gui import _WindowPickOverlay

    ov = _WindowPickOverlay()
    picked = []
    ov.show_pick(on_picked=lambda exe, title: picked.append((exe, title)))
    for _ in range(3):
        app.processEvents()
    assert ov.isVisible()
    # 点击穿透属性已设置（不拦截点击，用户可正常操作切换窗口）
    assert ov.testAttribute(Qt.WA_TransparentForMouseEvents)
    # 点击不提前确认
    click = QMouseEvent(QEvent.MouseButtonPress, QPointF(100, 100),
                        Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
    ov.mousePressEvent(click)
    for _ in range(3):
        app.processEvents()
    assert ov.isVisible(), "click should NOT confirm early"
    assert picked == []
    # 倒计时结束自动确认
    ov._seconds = 1
    ov._tick()
    for _ in range(3):
        app.processEvents()
    assert not ov.isVisible()
    assert len(picked) == 1
