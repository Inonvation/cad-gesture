"""自动更新模块测试（网络部分全部 mock）"""

import sys
import os
import io
import json
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
    # 0.0.9 < 0.0.10（字符串比较会出错的情况）
    assert compare_versions("0.0.9", "0.0.10") == -1
    assert compare_versions("0.0.10", "0.0.9") == 1


def test_compare_versions_v_prefix():
    assert compare_versions("v0.0.3", "0.0.2") == 1
    assert compare_versions("0.0.2", "V0.0.3") == -1


def test_compare_versions_diff_length():
    assert compare_versions("0.1", "0.1.0") == 0
    assert compare_versions("0.1.0", "0.1") == 0


def test_compare_versions_invalid():
    # 非法版本视为相等（不触发更新），不抛异常
    assert compare_versions("abc", "0.0.2") == 0
    assert compare_versions("0.0.2", "") == 0
    assert compare_versions("", "") == 0


# ========== 检查更新 ==========

def _make_release(tag="v0.0.3", with_asset=True, size=12345):
    release = {"tag_name": tag, "body": "修复若干问题"}
    if with_asset:
        release["assets"] = [
            {"name": "CADGesture-x64.exe", "size": 28000000,
             "browser_download_url": "https://example.com/green.exe"},
            {"name": "Setup-CADGesture-v0.0.3.exe", "size": size,
             "browser_download_url": "https://example.com/setup.exe"},
        ]
    else:
        release["assets"] = []
    return release


def _fake_urlopen(release_data):
    body = json.dumps(release_data).encode("utf-8")

    class FakeResp:
        def __init__(self):
            self._body = body

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def read(self, *args, **kwargs):
            return self._body

    return FakeResp()


def test_check_update_new_version():
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_urlopen(_make_release())):
        info = check_for_update("0.0.2", "https://api.example.com/latest")
    assert info is not None
    assert info["version"] == "0.0.3"
    assert "修复" in info["notes"]
    assert info["download_url"].endswith("setup.exe")
    assert info["size"] == 12345


def test_check_update_no_new_version():
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_urlopen(_make_release(tag="v0.0.2"))):
        info = check_for_update("0.0.2", "https://api.example.com/latest")
    assert info is None


def test_check_update_older_release():
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_urlopen(_make_release(tag="v0.0.1"))):
        info = check_for_update("0.0.2", "https://api.example.com/latest")
    assert info is None


def test_check_update_no_asset():
    with mock.patch("urllib.request.urlopen",
                    return_value=_fake_urlopen(_make_release(with_asset=False))):
        try:
            check_for_update("0.0.2", "https://api.example.com/latest")
            assert False, "应抛出 UpdateError"
        except UpdateError:
            pass


def test_check_update_network_error():
    with mock.patch("urllib.request.urlopen", side_effect=OSError("timeout")):
        try:
            check_for_update("0.0.2", "https://api.example.com/latest")
            assert False, "应抛出 UpdateError"
        except UpdateError:
            pass


def test_check_update_sends_user_agent():
    captured = {}

    def fake_urlopen(req, *args, **kwargs):
        captured["ua"] = req.get_header("User-agent")
        return _fake_urlopen(_make_release())

    with mock.patch("urllib.request.urlopen", side_effect=fake_urlopen):
        check_for_update("0.0.2", "https://api.example.com/latest")
    assert captured["ua"], "请求必须带 User-Agent 头（否则 GitHub 403）"


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
        # 期望 2000，实际 1000 → 失败且不留残缺文件
        assert download_update("https://example.com/setup.exe", dest, 2000) is False
    assert not os.path.exists(dest)
    assert not os.path.exists(dest + ".part")


def test_download_network_error(tmp_path):
    dest = str(tmp_path / "setup.exe")
    with mock.patch("urllib.request.urlopen", side_effect=OSError("down")):
        assert download_update("https://example.com/setup.exe", dest, 0) is False
    assert not os.path.exists(dest)
