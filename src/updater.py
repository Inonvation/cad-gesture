# -*- coding: utf-8 -*-
"""自动更新模块（纯逻辑，无 Qt 依赖）

提供版本比对、GitHub Release 检查、流式下载、静默安装四个能力。
网络检查/下载应在后台线程执行，避免阻塞 UI（见 app.py 集成方式）。

版本检查走 GitHub releases HTML 页面（不受未认证 API 60 次/小时/IP 限流），
下载用 release 资产直链（同样不经过 API）。

UpdateInfo 结构:
    {"version": "0.0.4", "notes": "...", "download_url": "...", "size": 0}
"""

import html
import os
import re
import subprocess
import time
import urllib.request

from src.version import __version__

_USER_AGENT = f"CADGesture/{__version__}"
_TIMEOUT = 15
_CHUNK_SIZE = 64 * 1024


class UpdateError(Exception):
    """更新流程中的可预期错误（网络失败、解析失败、下载校验失败）"""


class UpdateCancelled(UpdateError):
    """下载被用户取消（进度回调中抛出以中断下载）"""


def compare_versions(a: str, b: str) -> int:
    """数字逐段版本比较，返回 -1 / 0 / 1

    - "0.0.9" < "0.0.10"（不能按字符串比较）
    - 容忍 "v0.0.3" 前缀
    - 非法版本（段非数字）返回 0（视为相等，不触发更新）
    """
    def _parts(s: str):
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


def check_for_update(current_version: str, update_url: str) -> dict | None:
    """检查 GitHub Release 是否有新版本（走 releases HTML 页面，不受 API 限流）

    GitHub 未认证 API 限 60 次/小时/IP，共享 IP 下很快耗尽（表现为 403）。
    releases HTML 页面与下载直链不经过 API，无此限制。update_url 支持：
    - api.github.com/repos/{owner}/{repo}/releases/latest（自动转为 HTML 页面）
    - github.com/{owner}/{repo}/releases/latest

    Returns:
        有新版本: {"version", "notes", "download_url", "size"}
        无新版本: None
    Raises:
        UpdateError: 网络失败 / 页面无版本号
    """
    html_url = _to_releases_html_url(update_url)
    tag, page_html = _fetch_latest_release(html_url)
    if not tag:
        raise UpdateError("检查更新失败（无法从 Release 页面获取版本号）")
    version = tag.lstrip("vV")
    if not version:
        raise UpdateError("Release 数据缺少版本号")

    if compare_versions(version, current_version) <= 0:
        return None

    # 资产直链（release 下载不走 API，不受限流）
    base = html_url.rsplit("/releases/latest", 1)[0]
    download_url = (f"{base}/releases/download/{tag}/"
                    f"Setup-CADGesture-v{version}.exe")
    return {
        "version": version,
        "notes": _extract_notes(page_html),
        "download_url": download_url,
        "size": 0,  # 下载时从响应头实时读取 Content-Length
    }


def _to_releases_html_url(url: str) -> str:
    """api.github.com/repos/{owner}/{repo}/releases/latest → github.com HTML 页面"""
    m = re.match(
        r"https?://api\.github\.com/repos/([^/]+)/([^/]+)/releases/latest",
        url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}/releases/latest"
    return url


def _fetch_latest_release(html_url: str) -> tuple:
    """请求 releases/latest 页面；返回 (tag, html)；失败返回 ("", "")"""
    try:
        req = urllib.request.Request(html_url,
                                     headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            final = resp.geturl()
            page_html = resp.read().decode("utf-8", errors="ignore")
        m = re.search(r"/releases/tag/([^/?#]+)", final)
        return (m.group(1), page_html) if m else ("", "")
    except Exception:
        return "", ""


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


def download_update(url: str, dest: str, expected_size: int = 0,
                    progress_cb=None) -> bool:
    """流式下载到 dest（先写 .part 再原子改名）

    Args:
        url: 下载地址
        dest: 目标文件路径（%TEMP% 下）
        expected_size: 期望字节数，>0 时下载完成后校验，不符则返回 False
        progress_cb: 可选进度回调 (downloaded: int, total: int)

    Returns:
        成功 True；失败（网络/大小校验不符）False
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
        os.replace(part, dest)
        return True
    except Exception:
        _safe_remove(part)
        return False


def run_installer(installer_path: str) -> bool:
    """以静默模式启动安装程序（不等待，调用方随后退出）

    参数与 cad_gesture.iss 的静默安装约定一致：
    /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP- + /LOG 写安装日志（排查时用）。
    启动后等待短时间确认 Setup 进程已真正起来（立即退出 = 启动失败）。
    """
    try:
        log = os.path.join(os.environ.get("TEMP", "."), "CADGesture-Setup.log")
        args = [installer_path, "/VERYSILENT", "/SUPPRESSMSGBOXES",
                "/NORESTART", "/SP-", f"/LOG={log}"]
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, creationflags=flags, close_fds=True,
                         stdin=None, stdout=None, stderr=None)
        # Popen 成功即视为已启动：Setup 静默安装可能很快完成并退出，
        # 不能用进程退出判断失败（会误判安装成功为失败）
        time.sleep(0.5)
        return True
    except Exception:
        return False


def _safe_remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass