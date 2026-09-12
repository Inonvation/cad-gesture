# -*- coding: utf-8 -*-
"""自动更新模块测试

updater.py 是 GitHub Releases 路径的薄封装：测试重点为
1. 纯函数（compare_versions / to_releases_latest_url / _parse_release /
   _tag_from_url / proxy_handlers）
2. 检查链路（API JSON 优先 → 302 探测兜底；非 GitHub 源走旧 HTML 路径）
3. 下载/安装封装层行为
"""

import os
import sys
import urllib.request

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.updater import (
    compare_versions, to_releases_latest_url, _parse_release, _tag_from_url,
    normalize_mirror, download_source_urls, proxy_handlers,
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


# ========== URL / 解析纯函数 ==========

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


def test_tag_from_url():
    assert _tag_from_url(
        "https://github.com/a/b/releases/tag/v0.1.0") == "v0.1.0"
    assert _tag_from_url(
        "https://github.com/a/b/releases/tag/v0.1.0?x=1") == "v0.1.0"
    assert _tag_from_url("https://github.com/a/b") == ""


def test_parse_release_full():
    data = {"tag_name": "v0.1.0", "body": "更新说明",
            "assets": [{"name": "Setup-CADGesture-v0.1.0.exe", "size": 123}]}
    assert _parse_release(data) == ("v0.1.0", "更新说明", 123, "")


def test_parse_release_digest():
    data = {"tag_name": "v0.1.0",
            "assets": [{"name": "Setup-CADGesture-v0.1.0.exe", "size": 123,
                        "digest": "sha256:E4E0..."}]}
    tag, notes, size, sha = _parse_release(data)
    assert (tag, size) == ("v0.1.0", 123)
    assert sha == "e4e0..."  # 去 sha256: 前缀并转小写


def test_parse_release_asset_name_case_insensitive():
    data = {"tag_name": "V0.1.0",
            "assets": [{"name": "setup-cadgesture-v0.1.0.EXE", "size": 9}]}
    assert _parse_release(data)[2] == 9


def test_parse_release_no_assets():
    assert _parse_release({"tag_name": "v0.1.0"}) == ("v0.1.0", "", 0, "")


def test_parse_release_no_tag():
    assert _parse_release({}) == ("", "", 0, "")


# ========== 镜像前缀 / 下载源列表 ==========

def test_normalize_mirror():
    assert normalize_mirror("gh-proxy.com") == "https://gh-proxy.com/"
    assert normalize_mirror("https://ghfast.top") == "https://ghfast.top/"
    assert normalize_mirror("https://x.com/gh") == "https://x.com/gh/"
    assert normalize_mirror("") == ""
    assert normalize_mirror("https://") == ""
    assert normalize_mirror(None) == ""


def test_download_source_urls():
    direct = "https://github.com/a/b/releases/download/v1/x.exe"
    urls = download_source_urls(
        direct, ["https://gh-proxy.com/", "ghfast.top", "https://gh-proxy.com/"])
    assert urls[0] == direct
    assert urls[1] == "https://gh-proxy.com/" + direct
    assert urls[2] == "https://ghfast.top/" + direct
    assert len(urls) == 3  # 重复镜像被去重
    assert download_source_urls(direct, []) == [direct]
    assert download_source_urls(direct, ["", "https://"]) == [direct]


# ========== 代理 handlers ==========

def test_proxy_handlers_empty_follows_system():
    assert proxy_handlers("") == []
    assert proxy_handlers("   ") == []
    assert proxy_handlers(None) == []


def test_proxy_handlers_explicit():
    hs = proxy_handlers("127.0.0.1:7890")
    assert len(hs) == 1
    assert isinstance(hs[0], urllib.request.ProxyHandler)
    # 自动补 http:// 前缀，https 也走同一地址
    hs2 = proxy_handlers("http://127.0.0.1:7890")
    assert len(hs2) == 1


# ========== 检查链路：API 优先 → 302 探测兜底 ==========

def test_check_for_update_newer_via_api(monkeypatch):
    """有新版：API 路径返回 download_url / 真实体积 / 说明 / 官方校验值"""
    monkeypatch.setattr(
        "src.updater._fetch_via_api",
        lambda api_url, proxy: {
            "tag_name": "v0.0.12", "body": "notes",
            "assets": [{"name": "Setup-CADGesture-v0.0.12.exe",
                        "size": 12345,
                        "digest": "sha256:abc123"}]})
    info = check_for_update(
        "0.0.11", "https://github.com/Inonvation/cad-gesture")
    assert info is not None
    assert info["version"] == "0.0.12"
    assert info["mode"] == "github"
    assert info["size"] == 12345
    assert info["sha256"] == "abc123"
    assert info["notes"] == "notes"
    assert info["download_url"].endswith(
        "/releases/download/v0.0.12/Setup-CADGesture-v0.0.12.exe")


def test_check_for_update_fallback_to_probe(monkeypatch):
    """API 失败（限流/被墙）：退回 302 探测，只有版本号无说明/体积/校验值"""
    def _boom(api_url, proxy):
        raise UpdateError("API 检查失败")

    monkeypatch.setattr("src.updater._fetch_via_api", _boom)
    monkeypatch.setattr(
        "src.updater._probe_latest_tag", lambda html_url, proxy: "v0.0.12")
    info = check_for_update(
        "0.0.11", "https://github.com/Inonvation/cad-gesture")
    assert info is not None
    assert info["version"] == "0.0.12"
    assert info["notes"] == ""
    assert info["size"] == 0
    assert info["sha256"] == ""


def test_check_for_update_same_or_older(monkeypatch):
    monkeypatch.setattr(
        "src.updater._fetch_via_api",
        lambda api_url, proxy: {"tag_name": "v0.0.11", "body": "",
                                "assets": []})
    assert check_for_update(
        "0.0.11", "https://github.com/Inonvation/cad-gesture") is None
    assert check_for_update(
        "0.0.12", "https://github.com/Inonvation/cad-gesture") is None


def test_check_for_update_all_paths_fail(monkeypatch):
    def _boom(*a, **k):
        raise UpdateError("检查更新失败（网络连接异常，请检查网络后重试）")

    monkeypatch.setattr("src.updater._fetch_via_api", _boom)
    monkeypatch.setattr("src.updater._probe_latest_tag", _boom)
    try:
        check_for_update("0.0.11", "https://github.com/x/y")
        assert False, "应抛 UpdateError"
    except UpdateError:
        pass


def test_check_for_update_non_github_uses_legacy_html(monkeypatch):
    """自定义非 GitHub 更新源：仍走整页 HTML 老路径"""
    monkeypatch.setattr(
        "src.updater._fetch_latest_release",
        lambda html_url, proxy: (
            "v0.0.12", '<div class="markdown-body">notes</div>'))
    info = check_for_update("0.0.11", "https://example.com/repo")
    assert info is not None
    assert info["version"] == "0.0.12"
    assert info["notes"] == "notes"
    assert info["download_url"].startswith("https://example.com/repo/")


# ========== 下载多源回退链 ==========

def test_download_installer_switches_to_mirror(monkeypatch, tmp_path):
    """直连过慢 → 自动换镜像；成功即停，不再走兜底直连重试"""
    direct = "https://github.com/a/b/releases/download/v1/x.exe"
    calls = []

    def fake_one(src, dest, size, cb, proxy, sha, bail):
        calls.append((src, bail))
        if src == direct:
            return (False, "下载速度过慢")
        return (True, "")

    monkeypatch.setattr("src.updater._download_one", fake_one)
    ok, reason = download_installer(
        direct, str(tmp_path / "x.exe"), mirrors=["m1.com"])
    assert ok is True
    assert reason == ""
    # 直连(测速) → 镜像(测速) 成功；最后的直连不限速兜底未触发
    assert calls == [(direct, True),
                     ("https://m1.com/" + direct, True)]


def test_download_installer_all_fail(monkeypatch, tmp_path):
    """所有源都失败：返回最后的原因"""
    def fake_one(src, dest, size, cb, proxy, sha, bail):
        return (False, "URLError: timeout")

    monkeypatch.setattr("src.updater._download_one", fake_one)
    ok, reason = download_installer(
        "https://github.com/a/b/x.exe", str(tmp_path / "x.exe"),
        mirrors=["m1.com"])
    assert ok is False
    assert reason == "URLError: timeout"


def test_download_installer_reports_status(monkeypatch, tmp_path):
    """status_cb 依次收到 (模板, 参数)：直连 → 镜像"""
    statuses = []
    direct = "https://github.com/a/b/x.exe"

    def fake_one(src, dest, size, cb, proxy, sha, bail):
        if src == direct:
            return (False, "下载速度过慢")
        return (True, "")

    monkeypatch.setattr("src.updater._download_one", fake_one)
    download_installer(
        direct, str(tmp_path / "x.exe"),
        mirrors=["m1.com"],
        status_cb=lambda st: statuses.append(st))
    assert statuses[0][0].startswith("正在从 GitHub 直连下载")
    assert statuses[1] == ("直连较慢，正在用镜像 {host} 加速下载…",
                           {"host": "m1.com"})


def test_download_installer_cancel_propagates(monkeypatch, tmp_path):
    """用户取消：中断整个下载，不再尝试其他源"""
    def fake_one(src, dest, size, cb, proxy, sha, bail):
        raise UpdateCancelled("下载被取消")

    monkeypatch.setattr("src.updater._download_one", fake_one)
    try:
        download_installer(
            "https://github.com/a/b/x.exe", str(tmp_path / "x.exe"),
            mirrors=["m1.com"])
        assert False, "应抛 UpdateCancelled"
    except UpdateCancelled:
        pass
