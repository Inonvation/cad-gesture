# -*- coding: utf-8 -*-
"""自动更新模块测试（Velopack 深度依赖全部 mock）

updater.py 自 0.9.0 起是 Velopack 薄封装：测试重点为
1. 纯函数（compare_versions / normalize_source_url）
2. 封装层行为（错误包装、参数透传、结果结构）

build_manager 依赖 velopack 原生绑定（未打包环境初始化可能失败），用 fake
velopack 模块注入 sys.modules；check/download/apply 只操作传入的 manager
对象，直接构造 fake manager 即可，无需注入。
"""

import sys
import os
import types
import unittest.mock as mock
from contextlib import contextmanager

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.updater import (
    compare_versions, normalize_source_url, build_manager,
    check_for_update, download_update, apply_update,
    UpdateError, UpdateCancelled,
)


# ========== 版本比对（保留：Inno 桥接期 marker 兼容用） ==========

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


# ========== 更新源地址规范化 ==========

def test_normalize_repo_root():
    assert normalize_source_url(
        "https://github.com/Inonvation/cad-gesture") == (
        "https://github.com/Inonvation/cad-gesture")


def test_normalize_html_latest():
    """旧配置的 releases/latest 页地址 → 仓库根（GithubSource 要求）"""
    assert normalize_source_url(
        "https://github.com/Inonvation/cad-gesture/releases/latest") == (
        "https://github.com/Inonvation/cad-gesture")


def test_normalize_api_latest():
    """旧配置的 api.github.com latest 接口地址 → 仓库根"""
    assert normalize_source_url(
        "https://api.github.com/repos/Inonvation/cad-gesture/releases/latest") == (
        "https://github.com/Inonvation/cad-gesture")


def test_normalize_other_url_unchanged():
    """非 GitHub 地址（静态目录/镜像）原样保留，走 HttpSource"""
    url = "https://mirror.example.com/cadgesture/feed"
    assert normalize_source_url(url) == url


# ========== fake velopack（仅 build_manager 需要注入） ==========

class _FakeManager:
    """记录调用；行为由测试控制（check/download/apply 只依赖该对象接口）"""
    def __init__(self, source=None, source_url=""):
        self.source = source
        self.source_url = source_url
        self.downloaded = []
        self.apply_calls = []
        self.check_result = None
        self.check_error = None
        self.download_error = None
        self.apply_error = None

    def check_for_updates(self):
        if self.check_error:
            raise self.check_error
        return self.check_result

    def download_updates(self, info, progress_callback=None):
        if self.download_error:
            raise self.download_error
        self.downloaded.append((info, progress_callback))

    def wait_exit_then_apply_updates(self, info, silent=False, restart=True,
                                     restart_args=None):
        if self.apply_error:
            raise self.apply_error
        self.apply_calls.append((info, silent, restart, restart_args))


@contextmanager
def _install_fake_velopack():
    """注入 fake velopack 模块；yield (build_manager 结果, github_sources, http_sources)"""
    fake = types.ModuleType("velopack")
    github_sources, http_sources = [], []
    managers = []

    class FakeGithubSource:
        def __init__(self, repo_url, access_token=None, prerelease=False):
            self.repo_url = repo_url
            self.access_token = access_token
            github_sources.append(self)

    class FakeHttpSource:
        def __init__(self, url):
            self.url = url
            http_sources.append(self)

    class FakeUpdateManager:
        def __new__(cls, source, options=None, locator=None):
            mgr = _FakeManager(source, getattr(source, "repo_url", None)
                               or getattr(source, "url", ""))
            managers.append(mgr)
            return mgr

    fake.GithubSource = FakeGithubSource
    fake.HttpSource = FakeHttpSource
    fake.UpdateManager = FakeUpdateManager
    with mock.patch.dict(sys.modules, {"velopack": fake}):
        yield (managers, github_sources, http_sources)


# ========== build_manager ==========

def test_build_manager_uses_github_source():
    with _install_fake_velopack() as (managers, ghs, _):
        m = build_manager("https://github.com/o/r", token=None)
        assert managers[0] is m
        assert len(ghs) == 1
        assert ghs[0].repo_url == "https://github.com/o/r"
        assert ghs[0].access_token is None


def test_build_manager_passes_token():
    with _install_fake_velopack() as (_, ghs, _):
        build_manager("https://github.com/o/r", token="ghp_xxx")
        assert ghs[0].access_token == "ghp_xxx"


def test_build_manager_normalizes_legacy_url():
    """老配置 releases/latest 地址自动转仓库根"""
    with _install_fake_velopack() as (_, ghs, _):
        build_manager("https://github.com/o/r/releases/latest")
        assert ghs[0].repo_url == "https://github.com/o/r"


def test_build_manager_non_github_uses_http_source():
    with _install_fake_velopack() as (_, _, http_sources):
        build_manager("https://mirror.example.com/feed", token=None)
        assert len(http_sources) == 1
        assert http_sources[0].url == "https://mirror.example.com/feed"


# ========== check_for_update ==========

class _FakeAsset:
    def __init__(self, version="0.0.9", notes="修复若干问题"):
        self.Version = version
        self.NotesMarkdown = notes
        self.NotesHtml = "<p>" + notes + "</p>"
        self.Size = 12345


class _FakeUpdateInfo:
    def __init__(self, version="0.0.9"):
        self.TargetFullRelease = _FakeAsset(version)
        self.DeltasToTarget = []


def test_check_update_no_new_version():
    mgr = _FakeManager()
    mgr.check_result = None
    assert check_for_update(mgr) is None


def test_check_update_returns_info_dict():
    mgr = _FakeManager()
    mgr.check_result = _FakeUpdateInfo("0.0.9")
    info = check_for_update(mgr)
    assert info is not None
    assert info["version"] == "0.0.9"
    assert "修复" in info["notes"]
    assert info["size"] == 12345
    assert info["_info"] is mgr.check_result


def test_check_update_network_error_wrapped():
    mgr = _FakeManager()
    mgr.check_error = OSError("down")
    try:
        check_for_update(mgr)
        assert False, "应抛 UpdateError"
    except UpdateError as e:
        assert "网络" in str(e)


# ========== download_update ==========

def test_download_passes_info_and_progress():
    mgr = _FakeManager()
    info = {"_info": _FakeUpdateInfo("0.0.9")}
    cb = lambda pct: None  # noqa: E731
    download_update(mgr, info, progress_cb=cb)
    assert mgr.downloaded and mgr.downloaded[0][0] is info["_info"]
    assert mgr.downloaded[0][1] is cb


def test_download_error_wrapped():
    mgr = _FakeManager()
    mgr.download_error = RuntimeError("checksum mismatch")
    try:
        download_update(mgr, {"_info": _FakeUpdateInfo()})
        assert False, "应抛 UpdateError"
    except UpdateError:
        pass


# ========== apply_update ==========

def test_apply_update_calls_wait_exit_defaults():
    """默认 silent=True / restart=True（与应用内弹窗不重复、装后自动重启）"""
    mgr = _FakeManager()
    info = {"_info": _FakeUpdateInfo("0.0.9")}
    apply_update(mgr, info)
    assert mgr.apply_calls and mgr.apply_calls[0][0] is info["_info"]
    assert mgr.apply_calls[0][1] is True   # silent
    assert mgr.apply_calls[0][2] is True   # restart


def test_apply_update_error_wrapped():
    mgr = _FakeManager()
    mgr.apply_error = RuntimeError("update.exe missing")
    try:
        apply_update(mgr, {"_info": _FakeUpdateInfo()})
        assert False, "应抛 UpdateError"
    except UpdateError:
        pass


# ========== 错误类型兼容 ==========

def test_update_cancelled_is_update_error():
    assert issubclass(UpdateCancelled, UpdateError)
