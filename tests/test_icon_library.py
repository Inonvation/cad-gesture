# -*- coding: utf-8 -*-
"""图标库模块测试：引用解析、SVG 渲染染色、自定义图片导入、缓存"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication

from src.icon_library import (ICON_IDS, clear_cache, icons_dir,
                              import_custom_icon, parse_icon_ref,
                              preset_path, resolve_icon)

_app = QApplication.instance() or QApplication([])


def test_parse_icon_ref():
    assert parse_icon_ref("") == (None, None)
    assert parse_icon_ref(None) == (None, None)
    assert parse_icon_ref("preset:line") == ("preset", "line")
    assert parse_icon_ref("file:C:\\x.png") == ("file", "C:\\x.png")
    assert parse_icon_ref("random") == (None, None)


def test_preset_resolve_and_tint():
    clear_cache()
    pm = resolve_icon("preset:line", "#ff0000", 24)
    assert pm is not None and not pm.isNull()
    assert pm.width() == 24 and pm.height() == 24
    # 缓存命中：相同参数返回同一对象
    assert resolve_icon("preset:line", "#ff0000", 24) is pm
    # 颜色不同 -> 不同缓存项
    pm2 = resolve_icon("preset:line", "#00ff00", 24)
    assert pm2 is not pm


def test_preset_invalid_and_missing():
    clear_cache()
    assert resolve_icon("") is None
    assert resolve_icon("preset:not_exist") is None
    assert resolve_icon("file:C:\\no_such_file.png") is None
    assert resolve_icon(123) is None


def test_icons_dir_created(tmp_path, monkeypatch):
    monkeypatch.setenv("APPDATA", str(tmp_path))
    d = icons_dir()
    assert os.path.isdir(d)
    assert d.endswith(os.path.join("CADGesture", "icons"))


def test_import_custom_icon(tmp_path, monkeypatch):
    from PySide6.QtGui import QImage, QColor
    monkeypatch.setenv("APPDATA", str(tmp_path))
    src = tmp_path / "a.png"
    img = QImage(32, 32, QImage.Format_ARGB32)
    img.fill(QColor("#123456"))
    assert img.save(str(src))
    ref = import_custom_icon(str(src))
    assert ref.startswith("file:")
    path = ref[len("file:"):]
    assert os.path.isfile(path)
    # 同内容重复导入去重
    assert import_custom_icon(str(src)) == ref
    assert resolve_icon(ref, "#000000", 24) is not None


def test_import_custom_icon_rejects(tmp_path):
    import pytest
    bad = tmp_path / "bad.txt"
    bad.write_text("hello", encoding="utf-8")
    with pytest.raises(ValueError):
        import_custom_icon(str(bad))


def test_icon_ids_assets_exist():
    for iid in ICON_IDS:
        assert os.path.isfile(preset_path(iid)), iid