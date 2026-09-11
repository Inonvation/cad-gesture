# -*- coding: utf-8 -*-
"""自动更新模块（纯逻辑无 Qt 依赖）

安装版 / 绿色版统一走 GitHub Releases：
检查 Releases 是否有新版 → 下载 `Setup-CADGesture-vX.exe` 安装包 →
`/VERYSILENT` 静默覆盖安装 → 主进程退出。检查走 releases HTML 页面
（不受未认证 API 60 次/小时/IP 限流），下载用资产直链。

线程模型：检查/下载应在后台线程；进度回调由下载线程触发。
`run_installer` 应在主线程调用并随后尽快 `_quit()`。

UpdateInfo(dict) 结构：
    {"version", "notes", "download_url", "size", "mode": "github"}
"""

import html
import os
import re
import subprocess
import sys
import time
import urllib.request

from src.version import __version__

_USER_AGENT = f"CADGesture/{__version__}"
_TIMEOUT = 15
_CHUNK_SIZE = 64 * 1024

# ========== 错误类型 ==========


class UpdateError(Exception):
    """更新流程中的可预期错误（网络失败、下载失败、应用失败）"""


class UpdateCancelled(UpdateError):
    """下载被用户取消（progress_cb 抛此异常中断下载）"""


# ========== 纯函数 ==========


def compare_versions(a: str, b: str) -> int:
    """数字逐段版本比较，返回 -1 / 0 / 1

    - "0.0.9" < "0.0.10"（不能按字符串比较）
    - 容忍 "v0.0.3" 前缀
    - 非法版本（段非数字）返回 0（视为相等，不触发更新）
    """
    def _parts(s):
        raw = s.strip().lstrip("vV")
        if not raw:
            return None
        segs = raw.split(".")
        nums = []
        for seg in segs:
            if seg == "":
                nums.append(0)
                continue
            try:
                nums.append(int(seg))
            except ValueError:
                return None
        return nums

    pa, pb = _parts(a), _parts(b)
    if pa is None or pb is None:
        return 0
    n = max(len(pa), len(pb))
    pa += [0] * (n - len(pa))
    pb += [0] * (n - len(pb))
    for x, y in zip(pa, pb):
        if x < y:
            return -1
        if x > y:
            return 1
    return 0


def to_releases_latest_url(url: str) -> str:
    """规范化为 GitHub releases/latest 页面地址（HTML 检查用）。

    接受仓库根、releases/latest、api.github.com latest 等写法。
    """
    m = re.match(
        r"https?://api\.github\.com/repos/([^/]+)/([^/]+)(?:/.*)?$", url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}/releases/latest"
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/releases(?:/latest)?/?$",
        url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}/releases/latest"
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)/releases/latest", url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}/releases/latest"
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}/releases/latest"
    return url


# ========== GitHub Releases HTML 检查 / 下载 / Inno 静默安装 ==========


def check_for_update(current_version: str, update_url: str) -> dict | None:
    """检查 GitHub Release 是否有新版本（走 HTML 页面，不限流）。

    Returns:
        有新版本: {"version", "notes", "download_url", "size", "mode": "github"}
        无新版本: None
    Raises:
        UpdateError: 网络失败 / 页面无版本号
    """
    html_url = to_releases_latest_url(update_url)
    tag, page_html = _fetch_latest_release(html_url)
    if not tag:
        raise UpdateError("检查更新失败（无法从 Release 页面获取版本号）")
    version = tag.lstrip("vV")
    if not version:
        raise UpdateError("Release 数据缺少版本号")

    if compare_versions(version, current_version) <= 0:
        return None

    base = html_url.rsplit("/releases/latest", 1)[0]
    # 安装包固定命名（build.bat / 发版流程保证）
    download_url = (f"{base}/releases/download/{tag}/"
                    f"Setup-CADGesture-v{version}.exe")
    return {
        "version": version,
        "notes": _extract_notes(page_html),
        "download_url": download_url,
        "size": 0,
        "mode": "github",
    }


def _fetch_latest_release(html_url: str) -> tuple:
    """请求 releases/latest 页面；返回 (tag, html)。"""
    try:
        req = urllib.request.Request(html_url,
                                     headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            final = resp.geturl()
            page_html = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"/releases/tag/([^/?#]+)", final)
        return (m.group(1), page_html) if m else ("", "")
    except Exception as e:
        raise UpdateError(
            "检查更新失败（网络连接异常，请检查网络后重试）") from e


def _extract_notes(page_html: str) -> str:
    """从 release 页面 HTML 提取 markdown-body 描述文本；失败返回空串"""
    try:
        m = re.search(
            r'<div[^>]*class="[^"]*markdown-body[^"]*"[^>]*>(.*?)</div>',
            page_html, re.S)
        if not m:
            return ""
        body = re.sub(r"<[^>]+>", "", m.group(1))
        return html.unescape(body).strip()[:2000]
    except Exception:
        return ""


def download_installer(url: str, dest: str, expected_size: int = 0,
                       progress_cb=None) -> bool:
    """流式下载安装包到 dest（先写 .part 再原子改名）。

    progress_cb(downloaded, total)：可抛 UpdateCancelled 中断。
    Returns: 成功 True；失败 False
    """
    part = dest + ".part"
    try:
        req = urllib.request.Request(url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            total = int(resp.headers.get("Content-Length") or 0)
            downloaded = 0
            with open(part, "wb") as f:
                while True:
                    chunk = resp.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    downloaded += len(chunk)
                    if progress_cb:
                        try:
                            progress_cb(downloaded, total)
                        except UpdateCancelled:
                            raise
                        except Exception:
                            pass
        if expected_size > 0 and downloaded != expected_size:
            _safe_remove(part)
            return False
        if expected_size <= 0 and total > 0 and downloaded != total:
            _safe_remove(part)
            return False
        os.replace(part, dest)
        return True
    except UpdateCancelled:
        _safe_remove(part)
        raise
    except Exception:
        _safe_remove(part)
        return False


def run_installer(installer_path: str) -> tuple:
    """以静默模式启动 Inno 安装程序并确认其确实启动成功。

    参数与 cad_gesture.iss 一致：/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-

    Returns:
        (ok, reason)：ok=True 表示安装程序已正常启动；ok=False 表示失败。
    """
    try:
        log = os.path.join(os.environ.get("TEMP", "."), "CADGesture-Setup.log")
        args = [installer_path, "/VERYSILENT", "/SUPPRESSMSGBOXES",
                "/NORESTART", "/SP-", f"/LOG={log}"]
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        proc = subprocess.Popen(args, creationflags=flags, close_fds=True,
                                stdin=None, stdout=None, stderr=None)
    except Exception as e:
        return False, f"启动安装程序失败: {e}"
    time.sleep(1.5)
    ret = proc.poll()
    if ret is not None and ret != 0:
        return False, f"安装程序异常退出（代码 {ret}）"
    return True, ""


def _safe_remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass
