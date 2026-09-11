# -*- coding: utf-8 -*-
"""自动更新模块测试

updater.py 是 GitHub Releases 路径的薄封装：测试重点为
1. 纯函数（compare_versions / to_releases_latest_url）
2. 检查/下载/安装封装层行为
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.updater import (
    compare_versions, to_releases_latest_url,
    check_for_update, download_installer, run_installer,
    UpdateError, UpdateCancelled,
)


# ========== 版本比对 ==========

def test_compare_versions_equal():
    assert compare_versions("0.0.2", "0.0.2") == 0


def test_compare_versions_greater():
    assert compare_versions("0.0.3", "0.0.2") == 1
    assert compare_versions("1.0.0", "0.9.9") == 1


def test_compare_versions_less():
    assert compare_versions("0.0.2", "0.0.3") == -1


def test_compare_versions_multi_digit():
    assert compare_versions("0.0.9", "0.0.10") == -1


def test_compare_versions_v_prefix():
    assert compare_versions("v0.0.3", "0.0.2") == 1


def test_compare_versions_invalid():
    assert compare_versions("abc", "0.0.2") == 0
    assert compare_versions("0.0.2", "") == 0


# ========== 错误类型 ==========

def test_update_cancelled_is_update_error():
    assert issubclass(UpdateCancelled, UpdateError)


# ========== GitHub Releases 更新路径 ==========

def test_to_releases_latest_from_repo_root():
    assert to_releases_latest_url(
        "https://github.com/Inonvation/cad-gesture") == (
        "https://github.com/Inonvation/cad-gesture/releases/latest")


def test_to_releases_latest_from_api():
    assert to_releases_latest_url(
        "https://api.github.com/repos/Inonvation/cad-gesture/releases/latest") == (
        "https://github.com/Inonvation/cad-gesture/releases/latest")


def test_to_releases_latest_idempotent():
    url = "https://github.com/Inonvation/cad-gesture/releases/latest"
    assert to_releases_latest_url(url) == url


def test_check_for_update_newer(monkeypatch):
    """有新版：返回 download_url 指向 Setup-CADGesture-vX.exe"""
    monkeypatch.setattr(
        "src.updater._fetch_latest_release",
        lambda html_url: ("v0.0.12", '<div class="markdown-body">notes</div>'))
    info = check_for_update(
        "0.0.11", "https://github.com/Inonvation/cad-gesture")
    assert info is not None
    assert info["version"] == "0.0.12"
    assert info["mode"] == "github"
    assert info["download_url"].endswith(
        "/releases/download/v0.0.12/Setup-CADGesture-v0.0.12.exe")


def test_check_for_update_same_or_older(monkeypatch):
    monkeypatch.setattr(
        "src.updater._fetch_latest_release",
        lambda html_url: ("v0.0.11", ""))
    assert check_for_update(
        "0.0.11", "https://github.com/Inonvation/cad-gesture") is None
    assert check_for_update(
        "0.0.12", "https://github.com/Inonvation/cad-gesture") is None


def test_check_for_update_no_tag(monkeypatch):
    monkeypatch.setattr(
        "src.updater._fetch_latest_release", lambda html_url: ("", ""))
    try:
        check_for_update("0.0.11", "https://github.com/x/y")
        assert False, "应抛 UpdateError"
    except UpdateError:
        pass
