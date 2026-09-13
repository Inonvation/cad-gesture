# -*- coding: utf-8 -*-
"""自动更新模块（纯逻辑无 Qt 依赖）

安装版 / 绿色版统一走 GitHub Releases：
检查是否有新版 → 下载 `Setup-CADGesture-vX.exe` 安装包 →
`/VERYSILENT` 静默覆盖安装 → 主进程退出。

检查流量最小化（跨境链路下整页 HTML 有 200KB+ 且慢）：
1. 优先 GitHub API JSON（约 7KB，含版本号 / 更新说明 / 安装包体积 /
   官方 SHA256 校验值）；
2. API 失败（限流 403 / 被墙）时退回 releases/latest 的 302 跳转探测，
   只读 Location 头拿版本号，不下载页面正文。
两者都失败才报网络错误。

下载走多源回退链：GitHub 直连 → 镜像前缀列表（settings.update_mirrors，
借鉴 Clash Verge Rev 的 endpoints 模式）→ 直连不设速限重试。每个源先
测速 3 秒，低于阈值立即换下一个；下载全程按 API 提供的官方 SHA256
校验，防第三方镜像篡改。所有源均失败才报错（提示配置 update_proxy）。
支持显式代理（settings.update_proxy，留空则跟随系统代理）。

线程模型：检查/下载应在后台线程；进度回调由下载线程触发。
`run_installer` 应在主线程调用并随后尽快 `_quit()`。

UpdateInfo(dict) 结构：
    {"version", "notes", "download_url", "size", "sha256", "mode": "github"}
"""

import hashlib
import html
import json
import os
import re
import subprocess
import time
import urllib.error
import urllib.request

from src.version import __version__

_USER_AGENT = f"CADGesture/{__version__}"
_TIMEOUT = 15
_CHECK_TIMEOUT = 10
_CHUNK_SIZE = 64 * 1024
# 每个下载源先测速 _BAIL_SECONDS 秒，不足 _BAIL_BYTES 视为过慢换下一个
_BAIL_SECONDS = 3.0
_BAIL_BYTES = 512 * 1024

# ========== 错误类型 ==========


class UpdateError(Exception):
    """更新流程中的可预期错误（网络失败、下载失败、应用失败）"""


class UpdateCancelled(UpdateError):
    """下载被用户取消（progress_cb 抛此异常中断下载）"""


# ========== 代理 ==========


def proxy_handlers(proxy: str) -> list:
    """按代理设置构造 opener handlers。

    空串 = 跟随系统（urllib 默认读注册表/环境变量，注意 PAC 脚本不支持）；
    非空 = 强制走指定代理（如 http://127.0.0.1:7890，可省略 http:// 前缀）。
    """
    if not proxy or not str(proxy).strip():
        return []
    addr = str(proxy).strip()
    if "://" not in addr:
        addr = "http://" + addr
    return [urllib.request.ProxyHandler({"http": addr, "https": addr})]


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
    """规范化为 GitHub releases/latest 页面地址（检查入口）。

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


def _tag_from_url(url: str) -> str:
    """从 .../releases/tag/vX.Y.Z 形式的 URL 提取 tag；失败返回空串"""
    m = re.search(r"/releases/tag/([^/?#]+)", url or "")
    return m.group(1) if m else ""


def normalize_mirror(entry: str) -> str:
    """规范化镜像前缀：接受域名或完整 URL，返回 `https://host[/path]/`。

    非法（空 / 无 host）返回空串。例：
    "gh-proxy.com" → "https://gh-proxy.com/"；
    "https://x.com/gh" → "https://x.com/gh/"（gh-proxy 自建 PREFIX 路径写法）。
    """
    e = str(entry or "").strip()
    if not e:
        return ""
    if "://" not in e:
        e = "https://" + e
    e = e.rstrip("/") + "/"
    if not re.match(r"^https?://[^/]+/", e):
        return ""
    return e


def download_source_urls(url: str, mirrors=None) -> list:
    """构造下载源列表：直连在前，镜像前缀 URL 依次追加（去重）"""
    urls = [url]
    for m in mirrors or []:
        prefix = normalize_mirror(m)
        candidate = prefix + url
        if prefix and candidate not in urls:
            urls.append(candidate)
    return urls


def _parse_release(data: dict) -> tuple:
    """解析 GitHub API releases/latest JSON → (tag, notes, size, sha256)。

    size / sha256 取与固定命名 `Setup-CADGesture-vX.exe` 匹配的资产；
    sha256 来自 GitHub 官方 digest 字段（2025-06 起新上传的资产才有），
    用于镜像下载后的完整性校验；缺资产或缺字段返回 "" / 0。
    """
    tag = str(data.get("tag_name") or "").strip()
    if not tag:
        return ("", "", 0, "")
    notes = str(data.get("body") or "")[:2000]
    size = 0
    sha256 = ""
    want = f"Setup-CADGesture-v{tag.lstrip('vV')}.exe".lower()
    for a in data.get("assets") or []:
        try:
            if str(a.get("name") or "").lower() == want:
                size = int(a.get("size") or 0)
                digest = str(a.get("digest") or "").strip().lower()
                if digest.startswith("sha256:"):
                    sha256 = digest[len("sha256:"):]
                break
        except (TypeError, ValueError):
            continue
    return (tag, notes, size, sha256)


# ========== GitHub Releases 检查 / 下载 / Inno 静默安装 ==========


def check_for_update(current_version: str, update_url: str,
                     proxy: str = "") -> dict | None:
    """检查 GitHub Release 是否有新版本。

    Returns:
        有新版本: {"version", "notes", "download_url", "size", "mode": "github"}
        无新版本: None
    Raises:
        UpdateError: 网络失败 / 页面无版本号
    """
    html_url = to_releases_latest_url(update_url)
    base = html_url.rsplit("/releases/latest", 1)[0]
    if re.match(r"https?://github\.com/[^/]+/[^/]+$", base):
        tag, notes, size, sha256 = _latest_via_github(base, proxy)
    else:
        # 自定义非 GitHub 更新源：保留旧的整页 HTML 路径
        tag, page_html = _fetch_latest_release(html_url, proxy)
        notes = _extract_notes(page_html) if tag else ""
        size, sha256 = 0, ""
    if not tag:
        raise UpdateError("检查更新失败（无法从 Release 页面获取版本号）")
    version = tag.lstrip("vV")
    if not version:
        raise UpdateError("Release 数据缺少版本号")

    if compare_versions(version, current_version) <= 0:
        return None

    # 安装包固定命名（build.bat / 发版流程保证）
    download_url = (f"{base}/releases/download/{tag}/"
                    f"Setup-CADGesture-v{version}.exe")
    return {
        "version": version,
        "notes": notes,
        "download_url": download_url,
        "size": size,
        "sha256": sha256,
        "mode": "github",
    }


def _latest_via_github(base: str, proxy: str) -> tuple:
    """github 仓库的最新稳定版：(tag, notes, size, sha256)。

    先 API JSON（小而全），失败（限流/网络）退回 302 探测（只有版本号）。
    """
    api_url = (re.sub(r"https?://github\.com", "https://api.github.com/repos",
                      base) + "/releases/latest")
    try:
        data = _fetch_via_api(api_url, proxy)
        tag, notes, size, sha256 = _parse_release(data)
        if tag:
            return (tag, notes, size, sha256)
    except UpdateError:
        pass
    tag = _probe_latest_tag(base + "/releases/latest", proxy)
    return (tag, "", 0, "")


def _fetch_via_api(api_url: str, proxy: str) -> dict:
    try:
        req = urllib.request.Request(
            api_url, headers={"User-Agent": _USER_AGENT,
                              "Accept": "application/vnd.github+json"})
        opener = urllib.request.build_opener(*proxy_handlers(proxy))
        with opener.open(req, timeout=_CHECK_TIMEOUT) as resp:
            return json.loads(resp.read().decode("utf-8", errors="ignore"))
    except Exception as e:
        raise UpdateError("API 检查失败") from e


def _probe_latest_tag(html_url: str, proxy: str) -> str:
    """请求 releases/latest 只取 302 Location 里的 tag（不下载页面正文）"""
    try:
        handlers = [_NoRedirect()] + proxy_handlers(proxy)
        opener = urllib.request.build_opener(*handlers)
        req = urllib.request.Request(html_url,
                                     headers={"User-Agent": _USER_AGENT})
        try:
            with opener.open(req, timeout=_CHECK_TIMEOUT) as resp:
                # 未按预期跳转（缓存/代理改写）时兜底从最终 URL 取
                return _tag_from_url(resp.geturl())
        except urllib.error.HTTPError as e:
            loc = e.headers.get("Location") or ""
            e.close()
            return _tag_from_url(loc)
    except UpdateError:
        raise
    except Exception as e:
        raise UpdateError(
            "检查更新失败（网络连接异常，请检查网络后重试）") from e


class _NoRedirect(urllib.request.HTTPRedirectHandler):
    """禁止自动跟随跳转：releases/latest 靠 302 Location 拿版本号"""

    def redirect_request(self, req, fp, code, msg, headers, newurl):
        return None


def _fetch_latest_release(html_url: str, proxy: str = "") -> tuple:
    """（旧路径）请求 releases/latest 整页；返回 (tag, html)。"""
    try:
        req = urllib.request.Request(html_url,
                                     headers={"User-Agent": _USER_AGENT})
        opener = urllib.request.build_opener(*proxy_handlers(proxy))
        with opener.open(req, timeout=_CHECK_TIMEOUT) as resp:
            final = resp.geturl()
            page_html = resp.read().decode("utf-8", errors="ignore")
        return (_tag_from_url(final), page_html)
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
                       progress_cb=None, proxy: str = "", mirrors=None,
                       expected_sha256: str = "",
                       status_cb=None) -> tuple:
    """多源回退下载安装包到 dest（先写 .part 再原子改名，支持断点续传）。

    源顺序：直连 → 各镜像前缀（download_source_urls）→ 直连不设速限
    重试兜底。每个源先测速 _BAIL_SECONDS 秒（最后一个重试除外），不足
    _BAIL_BYTES 判定过慢，换下一个源；换源不删 .part，下一个源从中断处
    续传。expected_sha256 非空时对下载结果做 SHA256 校验，不过按失败
    处理继续换源。

    安全约束：expected_sha256 为空（如 API 被限流退回 302 探测，拿不到
    官方校验值）时只走直连、不启用镜像——镜像属第三方中转，无校验值时
    有被篡改风险，防篡改保证优先于下载加速。

    progress_cb(downloaded, total)：可抛 UpdateCancelled 中断整个下载
    （取消保留 .part，下次下载可续传）。
    status_cb(text)：当前下载源变化提示（已做 i18n 的中文文案）。

    Returns: (ok, reason)
    """
    if expected_sha256:
        attempts = [(u, True) for u in download_source_urls(url, mirrors)]
        attempts.append((url, False))  # 兜底：直连重试，不限速
    else:
        # 无官方校验值：只用直连（见上安全约束）
        attempts = [(url, True), (url, False)]
    ok, reason = False, ""
    for src, bail in attempts:
        host = re.sub(r"^https?://([^/]+).*$", r"\1", src)
        if src == url:
            status = ((T_DOWNLOAD_DIRECT, {})
                      if bail else (T_DOWNLOAD_RETRY, {}))
        else:
            status = (T_DOWNLOAD_MIRROR, {"host": host})
        if status_cb:
            try:
                status_cb(status)
            except Exception:
                pass
        ok, reason = _download_one(src, dest, expected_size, progress_cb,
                                   proxy, expected_sha256, bail)
        if ok:
            return True, ""
    return False, (reason or T_DOWNLOAD_ALL_FAILED)


def _hash_file(path: str, expected_sha256: str) -> bool:
    """校验文件 SHA256；expected_sha256 为空视为通过"""
    if not expected_sha256:
        return True
    hasher = hashlib.sha256()
    with open(path, "rb") as f:
        while True:
            chunk = f.read(_CHUNK_SIZE)
            if not chunk:
                break
            hasher.update(chunk)
    return hasher.hexdigest().lower() == expected_sha256.lower()


def _download_one(url: str, dest: str, expected_size: int, progress_cb,
                  proxy: str, expected_sha256: str, bail: bool) -> tuple:
    """单源流式下载（支持断点续传）。Returns: (ok, reason)；用户取消抛 UpdateCancelled

    dest.part 为断点文件：已存在且服务器支持 Range（206 响应）则从中断处
    续传；服务器忽略 Range（200 整段返回）则丢弃分片重下。换源/测速失败
    /网络异常/用户取消均保留 .part 供下次续传，仅校验失败或大小不符时
    删除。下载完成经 SHA256 校验后原子改名。
    """
    part = dest + ".part"
    base = 0
    if os.path.exists(part):
        base = os.path.getsize(part)
        if expected_size > 0:
            if base > expected_size:
                _safe_remove(part)
                base = 0
            elif base == expected_size:
                # 断点文件已下满（上次完成后未及改名）：直接校验晋级，免重复请求
                if _hash_file(part, expected_sha256):
                    os.replace(part, dest)
                    return True, ""
                _safe_remove(part)
                base = 0
    try:
        headers = {"User-Agent": _USER_AGENT}
        if base > 0:
            headers["Range"] = f"bytes={base}-"
        req = urllib.request.Request(url, headers=headers)
        opener = urllib.request.build_opener(*proxy_handlers(proxy))
        with opener.open(req, timeout=_TIMEOUT) as resp:
            status = getattr(resp, "status", None) or resp.getcode()
            if base > 0 and status == 206:
                total = base + int(resp.headers.get("Content-Length") or 0)
                mode = "ab"
            else:
                # 服务器不支持断点续传：丢弃分片整段重下
                base = 0
                total = int(resp.headers.get("Content-Length") or 0)
                mode = "wb"
            hasher = hashlib.sha256()
            if base > 0:
                # 校验和覆盖完整文件：先把已有分片喂进哈希
                with open(part, "rb") as pf:
                    while True:
                        prev = pf.read(_CHUNK_SIZE)
                        if not prev:
                            break
                        hasher.update(prev)
            downloaded = base
            session = 0
            start = time.monotonic()
            too_slow = False
            with open(part, mode) as f:
                while True:
                    chunk = resp.read(_CHUNK_SIZE)
                    if not chunk:
                        break
                    f.write(chunk)
                    session += len(chunk)
                    downloaded += len(chunk)
                    hasher.update(chunk)
                    if (bail and session < _BAIL_BYTES
                            and time.monotonic() - start > _BAIL_SECONDS):
                        too_slow = True
                        break
                    if progress_cb:
                        try:
                            progress_cb(downloaded, total)
                        except UpdateCancelled:
                            raise
                        except Exception:
                            pass
        if too_slow:
            # 保留分片：换下一个源可从此处续传（进度不回退）
            return False, T_DOWNLOAD_SLOW
        if expected_size > 0 and downloaded != expected_size:
            _safe_remove(part)
            return False, T_DOWNLOAD_SIZE_MISMATCH
        if expected_size <= 0 and total > 0 and downloaded != total:
            _safe_remove(part)
            return False, T_DOWNLOAD_SIZE_MISMATCH
        if (expected_sha256
                and hasher.hexdigest().lower() != expected_sha256.lower()):
            _safe_remove(part)
            return False, T_DOWNLOAD_BAD_SHA
        os.replace(part, dest)
        return True, ""
    except UpdateCancelled:
        raise  # 用户取消：保留 .part，下次下载可续传
    except urllib.error.HTTPError as e:
        e.close()
        if e.code == 416:  # Range 超出文件末尾：分片异常，弃用重下
            _safe_remove(part)
            return False, T_DOWNLOAD_SIZE_MISMATCH
        return False, f"{type(e).__name__}: {e}"
    except Exception as e:
        # 网络中断等：保留分片前缀，下次续传
        return False, f"{type(e).__name__}: {e}"


# 下载状态/失败文案（中文模板常量；界面展示处经 T() 翻译，i18n.py 有对应条目）
T_DOWNLOAD_DIRECT = "正在从 GitHub 直连下载…（较慢会自动切换镜像）"
T_DOWNLOAD_MIRROR = "直连较慢，正在用镜像 {host} 加速下载…"
T_DOWNLOAD_RETRY = "镜像均不可用，直连重试（不限速）…"
T_DOWNLOAD_SLOW = "下载速度过慢"
T_DOWNLOAD_SIZE_MISMATCH = "下载文件不完整"
T_DOWNLOAD_BAD_SHA = "下载文件校验失败"
T_DOWNLOAD_ALL_FAILED = ("下载失败：所有下载源均不可用。"
                         "可在 设置→关于→更新代理 填写代理地址后重试")


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
