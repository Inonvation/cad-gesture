# -*- coding: utf-8 -*-
"""方案数据操作纯函数测试（qt_profile_ops）+ 浮层定位算法（qt_popup.place_under）"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from PySide6.QtCore import QPoint, QRect

from src.qt_profile_ops import (add_profile, copy_profile, rename_profile,
                                delete_profile, export_profile,
                                load_profile_data, apply_profile_data)
from src.qt_popup import place_under


def _cfg():
    return {
        "settings": {"active_profile": "A", "autocad_profile": "A",
                     "zwcad_profile": "Z", "sector_count": 8},
        "profiles": {
            "A": {"name": "A", "target": "autocad", "sectors": {}},
            "Z": {"name": "Z", "target": "zwcad", "sectors": {}},
        },
    }


def test_add_profile_creates_sectors():
    cfg = _cfg()
    ok, err = add_profile(cfg, "B", "autocad", sector_count=8)
    assert ok and err is None
    prof = cfg["profiles"]["B"]
    assert prof["target"] == "autocad"
    assert len(prof["sectors"]) == 8
    assert prof["outer_sectors"] == {} and prof["extension_sectors"] == {}


def test_add_profile_duplicate():
    cfg = _cfg()
    ok, err = add_profile(cfg, "A", "autocad")
    assert not ok and err


def test_copy_profile():
    cfg = _cfg()
    cfg["profiles"]["A"]["sectors"] = {"0": {"label": "直线"}}
    ok, err = copy_profile(cfg, "A", "A2")
    assert ok
    assert cfg["profiles"]["A2"]["name"] == "A2"
    assert cfg["profiles"]["A2"]["sectors"]["0"]["label"] == "直线"
    # 深拷贝：改副本不影响原方案
    cfg["profiles"]["A2"]["sectors"]["0"]["label"] = "改"
    assert cfg["profiles"]["A"]["sectors"]["0"]["label"] == "直线"


def test_rename_profile_updates_bindings():
    cfg = _cfg()
    ok, err = rename_profile(cfg, "A", "A1")
    assert ok and err is None
    assert "A" not in cfg["profiles"] and cfg["profiles"]["A1"]["name"] == "A1"
    s = cfg["settings"]
    assert s["active_profile"] == "A1" and s["autocad_profile"] == "A1"
    assert s["zwcad_profile"] == "Z"


def test_delete_profile_resets_binding():
    cfg = _cfg()
    ok, err = delete_profile(cfg, "A")
    assert ok and err is None
    assert "A" not in cfg["profiles"]
    # autocad 绑定被删，重置为空；active 指向剩余方案 Z
    assert cfg["settings"]["autocad_profile"] == ""
    assert cfg["settings"]["active_profile"] == "Z"


def test_delete_profile_requires_at_least_one():
    cfg = {"profiles": {"A": {}}, "settings": {}}
    ok, err = delete_profile(cfg, "A")
    assert not ok and err


def test_export_import_roundtrip(tmp_path):
    cfg = _cfg()
    profile = cfg["profiles"]["A"]
    profile["sectors"] = {"0": {"label": "直线", "key": "l", "description": "LINE"}}
    path = str(tmp_path / "profile.json")
    ok, err = export_profile(profile, path)
    assert ok and err is None
    ok, data = load_profile_data(path)
    assert ok
    target = {"name": "T", "target": "autocad", "sectors": {}}
    apply_profile_data(target, data)
    assert target["sectors"]["0"]["label"] == "直线"


def test_load_profile_data_rejects_invalid(tmp_path):
    bad = tmp_path / "bad.json"
    bad.write_text("[1,2]", encoding="utf-8")
    ok, msg = load_profile_data(str(bad))
    assert not ok and msg
    bad2 = tmp_path / "bad2.json"
    bad2.write_text('{"sectors": {"0": "not-a-dict"}}', encoding="utf-8")
    ok, msg = load_profile_data(str(bad2))
    assert not ok and msg


def test_place_under_below_center():
    """浮层默认放在锚点正下方"""
    geo = QRect(0, 0, 1920, 1080)
    pos = place_under(QPoint(960, 540), 277, 320, 200, geo)
    assert pos.x() == 960 - 160
    assert pos.y() == 540 + 277 + 12


def test_place_under_moves_above_when_no_room_below():
    geo = QRect(0, 0, 1920, 1080)
    pos = place_under(QPoint(960, 1000), 277, 320, 200, geo)
    # 下方放不下 -> 上方
    assert pos.y() + 200 <= geo.bottom() - 8
    assert pos.y() < 1000


def test_place_under_clamps_to_screen():
    geo = QRect(0, 0, 1920, 1080)
    pos = place_under(QPoint(10, 540), 277, 320, 200, geo)
    assert pos.x() >= geo.left() + 8
    pos = place_under(QPoint(1910, 540), 277, 320, 200, geo)
    assert pos.x() + 320 <= geo.right() - 8