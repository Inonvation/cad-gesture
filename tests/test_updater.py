# -*- coding: utf-8 -*-
"""自动更新模块测试（网络部分全部 mock）

版本检查走 releases HTML 页面（geturl 提取 tag + read 提取 notes），
下载直链不经过 API。
"""

import sys
import os
import unittest.mock as mock

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.updater import (
    compare_versions, check_for_update, download_update, UpdateError
)


# ========== 版本比对 ==========

def test_compare_versions_equal():
    assert compare_versions("0.0.2", "0.0.2") == 0


def test_compare_versions_greater():
    assert compare_versions("0.0.3", "0.0.2") == 1
    assert compare_versions("0.1.0", "0.0.9") == 1
    assert compare_versions("1.0.0", "0.9.9") == 1


def test_compare_versions_less():
    assert compare_versions("0.0.2", "0.0.3") == -1


def test_compare_versions_multi_digit():
    assert compare_versions("0.0.9", "0.0.10") == -1
    assert compare_versions("0.0.10", "0.0.9") == 1


def test_compare_versions_v_prefix():
    assert compare_versions("v0.0.3", "0.0.2") == 1
    assert compare_versions("0.0.2", "V0.0.3") == -1


def test_compare_versions_diff_length():
    assert compare_versions("0.1", "0.1.0") == 0


def test_compare_versions_invalid():
    assert compare_versions("abc", "0.0.2") == 0
    assert compare_versions("0.0.2", "") == 0


# ========== 检查更新（HTML 页面） ==========

def _fake_urlopen(tag="v0.0.3", notes="修复若干问题"):
    final = (f"https://github.com/owner/repo/releases/tag/{tag}"
             if tag else "https://github.com/owner/repo/releases/latest")
    body = (f'<html><body><div class="markdown-body">{notes}</div>'
            f'</body></html>').encode("utf-8")

    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def geturl(self):
            return final

        def read(self, *args, **kwargs):
            return body

    return FakeResp()


def test_check_update_new_version():
    """HTML 页面有新版本：返回版本/说明/直链"""
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_urlopen()):
        info = check_for_update(
            "0.0.2", "https://github.com/owner/repo/releases/latest")
    assert info is not None
    assert info["version"] == "0.0.3"
    assert "修复" in info["notes"]
    assert info["download_url"].endswith(
        "/releases/download/v0.0.3/Setup-CADGesture-v0.0.3.exe")
    assert info["size"] == 0


def test_check_update_api_url_converted():
    """API URL 自动转 HTML 页面（避开未认证 API 限流）"""
    captured = {}

    def fake(req, *args, **kwargs):
        captured["url"] = req.full_url
        return _fake_urlopen()

    with mock.patch("urllib.request.urlopen", side_effect=fake):
        check_for_update(
            "0.0.2",
            "https://api.github.com/repos/Inonvation/cad-gesture/releases/latest")
    assert captured["url"] == (
        "https://github.com/Inonvation/cad-gesture/releases/latest")


def test_check_update_no_new_version():
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_urlopen(tag="v0.0.2")):
        assert check_for_update("0.0.2", "https://x/latest") is None


def test_check_update_older_release():
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_urlopen(tag="v0.0.1")):
        assert check_for_update("0.0.2", "https://x/latest") is None


def test_check_update_no_tag():
    """页面无版本号时抛 UpdateError"""
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_urlopen(tag="")):
        try:
            check_for_update("0.0.2", "https://x/latest")
            assert False, "应抛出 UpdateError"
        except UpdateError:
            pass


def test_check_update_network_error():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        try:
            check_for_update("0.0.2", "https://x/latest")
            assert False, "应抛出 UpdateError"
        except UpdateError:
            pass


def test_check_update_sends_user_agent():
    captured = {}

    def fake_urlopen(req, *args, **kwargs):
        captured["ua"] = req.get_header("User-agent")
        return _fake_urlopen()

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        check_for_update("0.0.2", "https://x/latest")
    assert captured["ua"], "请求必须带 User-Agent 头"


# ========== 下载 ==========

def _fake_download_response(data: bytes, content_length=None):
    class FakeResp:
        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, n):
            if not self._left:
                return b""
            chunk = self._left[:n]
            self._left = self._left[n:]
            return chunk

        headers = {"Content-Length": str(content_length or len(data))}

    resp = FakeResp()
    resp._left = data
    return resp


def test_download_success(tmp_path):
    data = b"x" * 10000
    dest = str(tmp_path / "setup.exe")
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_download_response(data)):
        assert download_update("https://example.com/setup.exe", dest, 10000) is True
    assert os.path.getsize(dest) == 10000
    assert not os.path.exists(dest + ".part")


def test_download_progress_callback(tmp_path):
    data = b"y" * 5000
    dest = str(tmp_path / "setup.exe")
    progress = []
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_download_response(data)):
        assert download_update("https://example.com/setup.exe", dest, 5000,
                               progress_cb=lambda d, t: progress.append((d, t)))
    assert progress and progress[-1][0] == 5000
    assert progress[-1][1] == 5000


def test_download_size_mismatch(tmp_path):
    data = b"z" * 1000
    dest = str(tmp_path / "setup.exe")
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_download_response(data)):
        assert download_update("https://example.com/setup.exe", dest, 2000) is False
    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")


def test_download_network_error(tmp_path):
    dest = str(tmp_path / "setup.exe")
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert download_update("https://example.com/setup.exe", dest, 0) is False
    assert not os.path.exists(dest)