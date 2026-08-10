"""自动更新模块（纯逻辑，无 Qt 依赖）

提供版本比对、GitHub Release 检查、流式下载、静默安装四个能力。
网络检查/下载应在后台线程执行，避免阻塞 UI（见 app.py 集成方式）。

UpdateInfo 结构:
    {"version": "0.0.3", "notes": "...", "download_url": "...", "size": 12345}
"""

import json
import os
import re
import subprocess
import urllib.request

from src.version import __version__

_USER_AGENT = f"CADGesture/{__version__}"
_TIMEOUT = 15
_CHUNK_SIZE = 64 * 1024

# Setup 安装包的文件名约定（与 cad_gesture.iss 的 OutputBaseFilename 一致）
_SETUP_NAME_RE = re.compile(r"^Setup-CADGesture-v\d+\.\d+\.\d+\.exe$", re.IGNORECASE)


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
    """检查 GitHub Release 是否有新版本

    Returns:
        有新版本: {"version", "notes", "download_url", "size"}
        无新版本: None
    Raises:
        UpdateError: 网络失败 / JSON 解析失败 / 找不到 Setup 附件
    """
    try:
        req = urllib.request.Request(update_url, headers={"User-Agent": _USER_AGENT})
        with urllib.request.urlopen(req, timeout=_TIMEOUT) as resp:
            data = json.loads(resp.read().decode("utf-8"))
    except Exception as e:
        raise UpdateError(f"检查更新失败（网络或 API 错误）: {e}") from e

    tag = data.get("tag_name", "")
    version = tag.lstrip("vV")
    if not version:
        raise UpdateError("Release 数据缺少版本号")

    if compare_versions(version, current_version) <= 0:
        return None

    asset = None
    for a in data.get("assets", []) or []:
        name = a.get("name", "")
        if _SETUP_NAME_RE.match(name):
            if asset is None or a.get("size", 0) > asset.get("size", 0):
                asset = a
    if asset is None:
        raise UpdateError("Release 中找不到安装包附件")

    return {
        "version": version,
        "notes": data.get("body", "") or "",
        "download_url": asset.get("browser_download_url", ""),
        "size": asset.get("size", 0),
    }


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
    /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
    """
    try:
        args = [installer_path, "/VERYSILENT", "/SUPPRESSMSGBOXES",
                "/NORESTART", "/SP-"]
        flags = subprocess.DETACHED_PROCESS | subprocess.CREATE_NEW_PROCESS_GROUP
        subprocess.Popen(args, creationflags=flags, close_fds=True,
                         stdin=None, stdout=None, stderr=None)
        return True
    except Exception:
        return False


def _safe_remove(path: str):
    try:
        os.remove(path)
    except OSError:
        pass
