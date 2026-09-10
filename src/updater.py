# -*- coding: utf-8 -*-
"""自动更新模块（Velopack 薄封装，纯逻辑无 Qt 依赖）

自 0.9.0 起由自研更新链路（Inno Setup 静默安装器 + GitHub releases HTML 解析
+ urllib 流式下载 + 子进程接管）迁移到 Velopack 1.2.0。Velopack 提供：
- GithubSource / HttpSource：GitHub Releases 或静态目录即更新源（feed 为
  releases.{channel}.json，channel 打包时由 vpk --channel 指定）；
- delta 增量更新：只下载版本间差异，跨多版本自动回退全量；
- 原子应用：Update.exe 等待本进程退出后替换文件并可选重启（绿色版同样支持）。

本模块只做薄封装，保持 app.py 的调用面（检查 / 下载 / 应用 + 错误类型）语义
不变，让更新 UI 层不感知底层框架差异。

线程模型：check/download 是网络 IO，须在后台线程执行；progress_callback 由
Velopack 在内部线程回调（实参为 0-100 的百分比整数，粒度约 5%）。apply 应在
主线程调用：wait_exit_then_apply_updates 会启动 Update.exe 等待本进程退出
（最长 60s），随后完成替换并重启，调用方在其返回后应立即退出进程。

UpdateInfo(dict) 结构（返回给 app.py，含 velopack 原生对象供下载/应用）：
    {"version": "...", "notes": "...", "size": n,
     "download_url": "...", "_info": velopack.UpdateInfo}
"""

import os
import re
import sys

# ========== 错误类型 ==========


class UpdateError(Exception):
    """更新流程中的可预期错误（网络失败、下载失败、应用失败）"""


class UpdateCancelled(UpdateError):
    """更新被用户取消。

    注：Velopack 下载无取消 API，且其 Rust 回调包装会把 Python 回调抛出的
    异常吞掉（仅 eprintln），因此该异常不再用于中断下载；保留类型仅为
    app.py 兼容旧调用点，实际取消语义由 UI 层自行处理（见 app.py）。
    """


# ========== 纯函数 ==========


def compare_versions(a: str, b: str) -> int:
    """数字逐段版本比较，返回 -1 / 0 / 1

    保留用途：Inno 桥接期 %TEMP% 更新标记的兼容判断（见 app.py
    _show_update_success_if_any）。Velopack 客户端内部的版本比对由它自己完成。
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


def is_velopack_layout() -> bool:
    """判断当前是否运行于 Velopack 布局（具备应用内自动更新能力）。

    根因：0.0.10 起安装器回归纯 Inno 直装向导（程序直接装进所选目录），
    该形态没有 Velopack 更新布局，无法自动更新；只有 vpk 产出的 portable
    bundle（解压目录）或 Velopack 安装器装出的布局才带
    root/Update.exe + root/current/ 结构。应用启动时会执行本函数决定
    "检查更新"走 Velopack 还是引导手动下载。

    判定：exe 位于名为 current 的目录且其父目录存在 Update.exe；或 exe
    同目录存在 Update.exe（平铺变体）。
    """
    exe_dir = os.path.dirname(sys.executable)
    if os.path.basename(exe_dir).lower() == "current":
        return os.path.exists(os.path.join(os.path.dirname(exe_dir),
                                           "Update.exe"))
    return os.path.exists(os.path.join(exe_dir, "Update.exe"))


def normalize_source_url(url: str) -> str:
    """把历史配置的更新地址规范化为 Velopack 可直接使用的源地址。

    根因：旧配置 update_source_url 存的是自研 HTML 解析用的地址
    （github.com/{o}/{r}/releases/latest 或 api.github.com 的 latest 接口），
    而 Velopack 的 GithubSource 需要仓库根地址 https://github.com/{o}/{r}。
    规范化后老用户的既有配置无需迁移即可继续工作。
    """
    m = re.match(
        r"https?://api\.github\.com/repos/([^/]+)/([^/]+)/releases/latest", url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}"
    m = re.match(
        r"https?://github\.com/([^/]+)/([^/]+)/releases/latest", url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}"
    m = re.match(r"https?://github\.com/([^/]+)/([^/]+)", url)
    if m:
        return f"https://github.com/{m.group(1)}/{m.group(2)}"
    # 其余地址（自定义静态目录 / 镜像源等）原样交给 HttpSource
    return url


def build_manager(source_url: str, token: str | None = None):
    """构建 Velopack UpdateManager。

    Args:
        source_url: GitHub 仓库页或任意静态目录/feed 地址（自动规范化）。
        token: GitHub 访问令牌（可选）。未认证走 60 次/小时/IP 限流；
            应用侧自动检查间隔 24h + 手动低频，个人场景足够。
    """
    import velopack

    url = normalize_source_url(source_url)
    if url.startswith("https://github.com/") or url.startswith("http://github.com/"):
        source = velopack.GithubSource(url, access_token=token or None)
    else:
        source = velopack.HttpSource(url)
    return velopack.UpdateManager(source)


# ========== 检查 / 下载 / 应用 ==========


def check_for_update(manager) -> dict | None:
    """检查是否有可用更新（feed 已按 channel/版本排序，比对交给 Velopack）。

    Returns:
        有新版本: {"version", "notes", "size", "_info"}
        无新版本: None
    Raises:
        UpdateError: 网络失败等（调用方据此给用户可理解的提示）。
    """
    try:
        info = manager.check_for_updates()
    except Exception as e:
        # 网络/超时与"无更新"分开提示：断网时不该让用户以为软件坏了
        raise UpdateError(
            "检查更新失败（网络连接异常，请检查网络后重试）") from e
    if info is None:
        return None
    target = info.TargetFullRelease
    return {
        "version": target.Version,
        "notes": (target.NotesMarkdown or target.NotesHtml or "").strip(),
        "size": target.Size,
        "_info": info,
    }


def download_update(manager, info: dict, progress_cb=None) -> None:
    """下载更新包（含 delta 组装/校验），完成后包位于本地 packages 目录。

    progress_cb(pct): Velopack 进度回调实参为 0-100 的百分比整数（约每 5%）。
    注意其 Rust 包装会吞掉 Python 回调异常（仅打印），故不能用抛异常中断下载；
    取消语义由 app.py 在 UI 层处理（丢弃后续事件即可）。

    Raises:
        UpdateError: 网络失败 / 校验失败等。
    """
    try:
        manager.download_updates(info["_info"], progress_cb)
    except Exception as e:
        raise UpdateError(f"下载更新失败：{e}") from e


def apply_update(manager, info: dict, silent: bool = True,
                 restart: bool = True) -> None:
    """应用更新：启动 Update.exe 等待本进程退出后完成替换（可选重启）。

    根因：Velopack 的文件替换必须在主进程完全退出后进行（运行中的 exe 被
    占用），因此该调用会拉起 Update.exe（--wait-current-process，最长等 60s）
    并立即返回；调用方须在其返回后尽快退出进程，让 Update.exe 接管。
    调用前应停止钩子/托盘等、保存必要状态。

    Args:
        silent: True 时无任何进度/提示 UI（默认，与应用内弹窗不重复）；
        restart: True 更新完成后自动重启应用（安装版与绿色版一致）。
    """
    try:
        manager.wait_exit_then_apply_updates(
            info["_info"], silent=silent, restart=restart)
    except Exception as e:
        raise UpdateError(f"启动更新程序失败：{e}") from e
