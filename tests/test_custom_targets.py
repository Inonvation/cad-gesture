"""自定义应用（其他软件）功能测试：数据层 + 运行时窗口识别

覆盖：
- settings.app_order / custom_targets 的默认值与迁移
- add_custom_target / remove_custom_target / set_target_order
- get_profile_for_window 对自定义 target 的绑定
- get_preset_commands 对未知 target 返回通用预设
- qt_profile_ops 的绑定键泛化（重命名/删除时同步自定义绑定）
- gesture_engine._detect_window_type 的 exe / 标题匹配
"""

import os
import sys
import ctypes

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config_manager import (
    get_target_order, set_target_order, get_target_label,
    add_custom_target, remove_custom_target, get_custom_targets,
    get_profile_for_window, BUILTIN_TARGETS, _default_config,
)
from src.config_presets import get_preset_commands
from src.qt_profile_ops import rename_profile, delete_profile


def _cfg():
    cfg = _default_config()
    return cfg


def test_target_order_default():
    cfg = _cfg()
    assert get_target_order(cfg) == ["autocad", "zwcad"]
    assert cfg["settings"]["app_order"] == ["autocad", "zwcad"]
    assert get_custom_targets(cfg) == []


def test_add_custom_target_creates_profile_and_binding():
    cfg = _cfg()
    ok, err = add_custom_target(cfg, "SolidWorks", "sldworks.exe")
    assert ok and err is None
    apps = get_custom_targets(cfg)
    assert len(apps) == 1
    app = apps[0]
    assert app["id"] == "app_sldworks"
    assert app["name"] == "SolidWorks"
    assert app["match_exe"] == "sldworks.exe"
    # 自动创建同名方案并绑定
    prof = cfg["profiles"]["SolidWorks"]
    assert prof["target"] == "app_sldworks"
    assert len(prof["sectors"]) == 8
    assert cfg["settings"]["app_sldworks_profile"] == "SolidWorks"
    # 顺序追加
    assert get_target_order(cfg) == ["autocad", "zwcad", "app_sldworks"]
    # 窗口匹配走自定义 target
    p = get_profile_for_window(cfg, "app_sldworks")
    assert p is not None and p.get("name") == "SolidWorks"


def test_add_custom_target_validation():
    cfg = _cfg()
    ok, err = add_custom_target(cfg, "", "a.exe")
    assert not ok and err
    ok, err = add_custom_target(cfg, "App", "")
    assert not ok and err


def test_add_custom_target_duplicate_id_gets_suffix():
    cfg = _cfg()
    add_custom_target(cfg, "SolidWorks", "sldworks.exe")
    ok, err = add_custom_target(cfg, "SolidWorks2", "sldworks.exe")
    assert ok and err is None
    ids = [a["id"] for a in get_custom_targets(cfg)]
    assert "app_sldworks" in ids and "app_sldworks_2" in ids


def test_set_target_order_reorder():
    cfg = _cfg()
    add_custom_target(cfg, "SolidWorks", "sldworks.exe")
    add_custom_target(cfg, "PS", "photoshop.exe")
    order = get_target_order(cfg)
    assert order == ["autocad", "zwcad", "app_sldworks", "app_photoshop"]
    # 重排：自定义应用移到最前
    new_order = ["app_photoshop", "autocad", "app_sldworks", "zwcad"]
    got = set_target_order(cfg, new_order)
    assert got == new_order
    assert cfg["settings"]["app_order"] == new_order


def test_set_target_order_drops_invalid():
    cfg = _cfg()
    add_custom_target(cfg, "SolidWorks", "sldworks.exe")
    got = set_target_order(cfg, ["app_sldworks", "ghost_target"])
    assert "ghost_target" not in got
    assert got == ["app_sldworks", "autocad", "zwcad"]


def test_remove_custom_target_cleanup():
    cfg = _cfg()
    add_custom_target(cfg, "SolidWorks", "sldworks.exe")
    ok, err = remove_custom_target(cfg, "app_sldworks")
    assert ok and err is None
    assert get_custom_targets(cfg) == []
    assert "SolidWorks" not in cfg["profiles"]
    assert "app_sldworks_profile" not in cfg["settings"]
    assert "app_sldworks" not in cfg["settings"]["app_order"]
    # 内置 target 不可删除
    ok, err = remove_custom_target(cfg, "autocad")
    assert not ok and err


def test_target_label():
    cfg = _cfg()
    assert get_target_label(cfg, "autocad") == "AutoCAD"
    assert get_target_label(cfg, "zwcad") == "中望CAD"
    add_custom_target(cfg, "SolidWorks", "sldworks.exe")
    assert get_target_label(cfg, "app_sldworks") == "SolidWorks"


def test_generic_preset_for_unknown_target():
    cmds = get_preset_commands("app_sldworks")
    assert "常用快捷键" in cmds
    assert cmds["常用快捷键"]["复制"]["key"] == "ctrl+c"
    # 内置 target 不受影响
    assert "绘图" in get_preset_commands("autocad")


def test_rename_profile_updates_custom_binding():
    cfg = _cfg()
    add_custom_target(cfg, "SolidWorks", "sldworks.exe")
    ok, err = rename_profile(cfg, "SolidWorks", "SolidWorks-常用")
    assert ok and err is None
    assert cfg["settings"]["app_sldworks_profile"] == "SolidWorks-常用"
    assert cfg["profiles"]["SolidWorks-常用"]["target"] == "app_sldworks"


def test_delete_profile_resets_custom_binding():
    cfg = _cfg()
    add_custom_target(cfg, "SolidWorks", "sldworks.exe")
    add_custom_target(cfg, "SolidWorks2", "sldworks2.exe")
    ok, err = delete_profile(cfg, "SolidWorks")
    assert ok and err is None
    assert cfg["settings"]["app_sldworks_profile"] == ""
    # 另一个自定义应用的绑定仍在
    assert cfg["settings"]["app_sldworks2_profile"] == "SolidWorks2"


def _make_engine(monkeypatch, custom_targets):
    from src.gesture_engine import GestureEngine
    eng = GestureEngine(
        config={"settings": {"custom_targets": custom_targets}},
        on_gesture=lambda *a: None,
        on_gesture_feedback=lambda *a: None,
        on_menu_show=lambda *a: None,
        on_menu_hide=lambda: None,
        on_extension_hint=lambda *a: None,
    )
    eng._window_cache = ("", 0.0)  # 清缓存
    return eng


def test_detect_window_type_custom_exe(monkeypatch):
    eng = _make_engine(monkeypatch, [
        {"id": "app_sldworks", "name": "SolidWorks",
         "match_exe": "sldworks.exe", "match_title": ""},
    ])
    eng._foreground_exe = lambda hwnd: "sldworks.exe"
    assert eng._detect_window_type() == "app_sldworks"


def test_detect_window_type_custom_title(monkeypatch):
    eng = _make_engine(monkeypatch, [
        {"id": "app_sldworks", "name": "SolidWorks",
         "match_exe": "", "match_title": "solidworks"},
    ])
    eng._foreground_exe = lambda hwnd: ""

    def fake_class(hwnd, buf, n):
        buf.value = "SldWorksFrame"

    def fake_title(hwnd, buf, n):
        buf.value = "SolidWorks - Part1"
    monkeypatch.setattr(ctypes.windll.user32, "GetClassNameW", fake_class)
    monkeypatch.setattr(ctypes.windll.user32, "GetWindowTextW", fake_title)
    # 快路径（进程名）未命中返回空串，由慢路径（标题/类名）兜底确认
    assert eng._detect_window_type() == ""
    assert eng._confirm_window_type_slow(0) == "app_sldworks"


def test_detect_window_type_slow_no_match(monkeypatch):
    """慢路径（标题/类名）也无匹配时返回空串，不误判为 CAD"""
    eng = _make_engine(monkeypatch, [
        {"id": "app_sldworks", "name": "SolidWorks",
         "match_exe": "", "match_title": "solidworks"},
    ])
    eng._foreground_exe = lambda hwnd: ""

    def fake_class(hwnd, buf, n):
        buf.value = "NotepadFrame"

    def fake_title(hwnd, buf, n):
        buf.value = "Untitled - Notepad"
    monkeypatch.setattr(ctypes.windll.user32, "GetClassNameW", fake_class)
    monkeypatch.setattr(ctypes.windll.user32, "GetWindowTextW", fake_title)
    assert eng._detect_window_type() == ""
    assert eng._confirm_window_type_slow(0) == ""


def test_detect_window_type_builtin_priority(monkeypatch):
    """内置 CAD 优先于自定义应用：exe 同时命中 acad 与自定义规则时走内置"""
    eng = _make_engine(monkeypatch, [
        {"id": "app_custom_acad", "name": "X",
         "match_exe": "acad", "match_title": ""},
    ])
    eng._foreground_exe = lambda hwnd: "acad.exe"
    assert eng._detect_window_type() == "autocad"
