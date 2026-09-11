# CADGesture 安装/更新架构迁移方案:Inno Setup → Velopack

> 版本:v1.0(方案稿,已实施后于同日回退)
> 日期:2026-09-08
> 关联:`docs/installer-update-plan.md`(Inno 时代规划,已实施,存档)
> 状态:**已废弃**（2026-09-11）：项目已回退为 Inno Setup 单一形态，去掉
> Velopack / .NET / vpk。本文仅作历史存档，不代表现状。

---

## 1. 背景与目标

现状:PyInstaller onedir 双形态分发(Inno Setup 安装版 + 绿色版 zip),自动更新为自研
(`src/updater.py` 解析 GitHub Releases HTML → 下载 Setup.exe → 静默 `/VERYSILENT` 覆盖),
外加单实例事件机制配合"覆盖更新",并自研了更新成功/失败标记。

痛点(前一轮评审已确认):
1. 更新链路全自研,维护面大:HTML 解析、直链拼接、静默安装器时序、失败无感知检测、托盘替换,都是自己造的轮子。
2. 绿色版无法自更新(形态缺陷,已做 UI 分流补丁,但架构上没根治)。
3. 全量下载 Setup 重装,无增量更新;版本号 5 处手工同步;无 CI 发版闭环。

**决策(2026-09-08 用户确认)**:安装器 + 自动更新整体迁移到 **Velopack**
(Squirrel.Windows 继任者,2026 桌面应用安装/更新的主流方案),接受构建链新增
.NET SDK(vpk 打包工具前置)。官方一等支持 Python 3.8+ / PyInstaller onedir /
GitHub Releases 更新源,自带 delta 增量更新、绿色版自更新、one-click 安装器。

---

## 2. Velopack 与本项目的能力对照(事实,2026-09-08 核实)

| 能力 | 现状(自研) | Velopack(pip 1.2.0 / vpk) |
|---|---|---|
| 增量更新 | 无,全量下载 Setup 重装 | ✅ delta 包默认开启(`--delta BestSpeed`),只下 diff |
| 绿色版自更新 | ❌(只能手动换 zip) | ✅ portable bundle 自带更新(经 Update.exe) |
| 安装器 | Inno Setup .iss 脚本 + taskkill 双保险 | ✅ vpk 生成 one-click Setup.exe,内置进程管理 |
| 更新检查 | 自研 releases HTML 解析(绕 API 限流) | ✅ `GithubSource`(repo URL 直连;未认证 60 次/h/IP) |
| 下载校验 | Content-Length + .part 原子改名 | ✅ 内建 SHA1/SHA256 + 大小校验(feed 驱动) |
| 应用更新 | 启动静默安装器 → 主进程退出 → 接管 | ✅ `apply_updates_and_restart` / `wait_exit_then_apply_updates` |
| 成功感知 | 自研 %TEMP% 标记 + 版本比对 | ✅ `on_restarted` hook(重启成功后触发) |
| 卸载 | Inno 卸载器;配置外置天然保留 | ✅ Velopack 卸载;配置在 %APPDATA% 不受影响 |
| 发布上传 | 手工 gh release | ✅ `vpk upload github`(也可手工上传产物) |
| 免 UAC 每用户 | `{localappdata}\Programs` | ✅ 默认每用户安装(MSI 机器级可选,不开) |

Python API(核实自 velopack-1.2.0 wheel 的 `__init__.pyi`):
`App()`(builder:hooks `on_first_run` / `on_restarted` / `on_before_update_fast_callback`
等 + `run()`)、`UpdateManager(source)`、`GithubSource(repo_url, access_token=None,
prerelease=False)`、`check_for_updates()`、`download_updates(info, progress_callback)`、
`apply_updates_and_restart(info)`、`wait_exit_then_apply_updates(info, silent, restart,
restart_args)`、`get_current_version()`、`get_is_portable()`。

---

## 3. 目标架构

```
PyInstaller onedir ──> dist\CADGesture-x64\（与现在同）
        │
        └──> vpk pack --packId CADGesture --packVersion vX.Y.Z --mainExe CADGesture-x64.exe
             产物（默认 Releases\ 目录，channel=win）：
             ├─ Setup.exe                     安装版引导器（one-click）
             ├─ CADGesture-X.Y.Z-win-x64.nupkg  全量更新包
             ├─ CADGesture-X.Y.Z-win-x64-delta.nupkg 增量包（若可生成）
             ├─ CADGesture-X.Y.Z-win-x64-portable.zip 绿色版（自带自更新）
             └─ releases.win.json             更新源索引
                │  （全部作为 GitHub Release assets 上传）
                ▼
程序内更新（src/updater.py 重写为 velopack 薄封装）
  启动检查/手动 → GithubSource 查 feed → 有新版弹窗
  → download_updates(进度条) → wait_exit_then_apply_updates
  → Update.exe 原子替换 → 重启 → on_restarted 弹"已更新"
```

**不变的部分**:用户配置仍在 `%APPDATA%\CADGesture`(程序目录无关 → 升级/卸载天然不
碰配置);单实例互斥保留(防重复托盘);手势引擎/圆盘/配置界面零改动;版本号来源
`version.txt` + `src/version.py` 不变(packVersion 从 `read_version.py` 注入)。

**删除的部分**(随迁移退役):
- `cad_gesture.iss` + Inno 编译链路(build.bat 中 ISCC 步骤);
- updater.py 的 HTML 解析/直链拼接/urllib 下载/子进程静默安装器;
- `_UPDATE_SUCCESS_MARKER` 期望版本比对(改为 `on_restarted` hook);
- P0-1 的"绿色版分流 UI"(portable 也能自更新,不再需要禁用)。

---

## 4. 逐文件改造清单

### 4.1 `main.py`(入口,核心改动)

Velopack 要求其初始化在进程最早、任何其他启动代码之前:

```python
import velopack

if __name__ == "__main__":
    # 根因:Velopack 安装/卸载/更新由 Update.exe 以特殊参数启动本程序
    # （--velopack-install/--velopack-update 等），必须在 GUI 创建前消费；
    # 未处理这些参数会导致安装流程卡住。
    vp = velopack.App()
    vp.on_restarted(lambda: _mark_updated())   # 更新重启成功 → 记录，UI 就绪后弹窗
    vp.run()
    # 现有:ensure_single_instance() + run() 流程不变
```

实现要点:
- `on_restarted` 回调在 Qt 事件循环就绪前触发,回调内只置标志(如写内存标志/环境变量),
  由现有 `QTimer.singleShot(800, ...)` 的弹窗位读取并弹"已更新到 vX"(复用现 UI 文案)。
- 顺序:velopack 初始化 → 单实例检查 → 现有 run()。普通启动时 `run()` 是 no-op(仅
  设置定位器),不会阻塞。
- `ensure_single_instance` 中"请求旧实例退出以覆盖更新"的路径在 Velopack 时代不再
  承担更新职责,保留仅作双击防重。语义注释同步更新。

### 4.2 `src/updater.py`(重写为 velopack 薄封装,保留文件名减少 app.py 联动)

```python
class UpdateError(Exception): ...      # 保留,错误文案层继续用

def build_manager(repo_url, token=None):      # → velopack.UpdateManager(GithubSource(...))
def check_for_update(current_version, repo_url, token=None) -> dict | None
    # info = manager.check_for_updates()
    # 无 → None;有 → {"version","notes"(TargetFullRelease.NotesMarkdown),"_info": UpdateInfo}
    # 注:版本比对交给 Velopack(feed 已按 channel 排好),不再自研 compare_versions
def download_update(manager, info, progress_cb) -> None      # 下载,done 后可 apply
def apply_update(manager, info) -> None
    # 根因:应用更新必须等当前进程完全退出,由 Update.exe 接管原子替换。
    # 优先 wait_exit_then_apply_updates(info, silent=True, restart=True);
    # 实施时若该绑定行为不符合(见里程碑 M3 实测),fallback 到先保存状态再
    # apply_updates_and_restart(info)。
```

退役:`compare_versions`(如需保留给旧标记兼容则留在 i18n/app 层临时用,见 4.3)、
`is_installed_build`、`_to_releases_html_url`/`_fetch_latest_release`/`_extract_notes`/
`download_update`(urllib 版)/`run_installer`。

### 4.3 `src/app.py`(更新流程对接)

- `_check_update` / `_download_worker`:换用 updater 新封装;后台线程 + 事件队列结构不变。
- `_show_update_dialog`:绿色版/安装版不再分流(portable 也走自更新),恢复单一
  「立即更新」路径;notes 取 `NotesMarkdown`。
- `_start_and_finish`(原"启动静默安装器后退出")→ 改为:下载完成 → 用户点「开始安装」
  → `_quit()` 停钩子/托盘(现有实现)→ 随后 `apply_update`(Update.exe 等待并接管)。
  若 `wait_exit_then_apply_updates` 已内含"等待退出",则先调用它、由其结束进程;
  具体顺序以 M3 真机实测为准,代码注释写明根因。
- `_show_update_success_if_any`:保留旧 %TEMP% 标记兼容分支(供 Inno 老用户经桥接升级后
  首启弹一次"已更新",见 §6),来源改为 `on_restarted` 置位;下一个大版本删除标记逻辑。
- 更新弹窗新增字段:安装/绿色版形态提示不再需要(删除 i18n 中对应 key,保留无妨)。

### 4.4 `src/qt_update_dialog.py`

基本不动。下载进度回调接口与 `set_progress(downloaded, total)` 对齐;
`show_update_info` 的 `primary_text` 覆盖参数可保留(为将来"打开下载页"等场景兜底)。

### 4.5 `scripts/build.bat`(打包流程改造)

保留:清理 → PyInstaller → 复制 config.example.json。
替换:删除 ISCC 编译与"绿色版 zip 压缩"(portable zip 由 vpk 产出,自带更新)。

新增步骤(版本号仍经 `scripts/read_version.py` 注入):

```bat
:: [4/6] vpk 打包(需 .NET SDK 全局工具 vpk;装法 dotnet tool install -g vpk)
vpk pack --packId CADGesture ^
         --packVersion %VERSION% ^
         --packDir dist\CADGesture-x64 ^
         --mainExe CADGesture-x64.exe ^
         --icon assets\icon.ico ^
         --packTitle "CAD Gesture" ^
         --releaseNotes %TEMP%\release-notes-%VERSION%.md ^
         --outputDir Releases
:: [5/6] 桥接资产:旧 Inno updater 硬编码下载 Setup-CADGesture-vX.exe
copy Releases\Setup.exe Releases\Setup-CADGesture-v%VERSION%.exe
```

产物输出目录约定:建议固定 `Releases\`(进 .gitignore)。

### 4.6 版本号与发布

- `version.txt`(4 处) + `src/version.py`:`__version__` 保留(供 UI 显示、packVersion 注入)。
- 发布三步:① 打包得到 Releases\ 产物;② 自测(§8 清单);③ 上传 GitHub Release assets
  (releases.win.json、Setup.exe、nupkg×N、portable.zip、Setup-CADGesture-vX.exe 桥接名、
  config.example.json),Release notes 同步 CHANGELOG。
- 上传工具二选一:`vpk upload github --repoUrl ... --token ... --publish`,或
  `gh release create` + 手动传 assets(asset 文件名必须与 feed 一致,vpk upload 更省心)。

### 4.7 配套文档与配置

| 文件 | 改动 |
|---|---|
| `AGENTS.md` | 架构图补 velopack;打包流程替换 ISCC;命令区加 vpk;坑列表加"dotnet 沙箱不可用/velopack 初始化须最先" |
| `README.md` / `README.en.md` | 下载区:Setup.exe(安装版,自动更新)/ portable zip(绿色版,也支持自更新);SmartScreen 说明不变 |
| `requirements.txt` | 加 `velopack==1.2.0`(仅运行时依赖,随 PyInstaller 打包;开发/测试环境也需装) |
| `config_presets.py` / `config_manager.py` | `update_source_url` 语义改为"GitHub 仓库页或更新 feed";字段名不变免迁移;加 `update_token`(可选,空=未认证限流) |
| `tests/test_updater.py` | 重写:velopack 深度依赖 → 用 monkeypatch 伪造 velopack 模块测封装层;保留版本相关纯函数测试(若保留 compare_versions) |
| `.gitignore` | 加 `Releases/` |
| `CHANGELOG.md` | 迁移版本记录 |

---

## 5. 实施里程碑(每步可独立验收,尽量小步提交)

| 里程碑 | 内容 | 验收标准 | 依赖 |
|---|---|---|---|
| **M0 环境** | .NET SDK 可用(`dotnet --list-sdks` 有输出);`dotnet tool install -g vpk` 成功;`pip install velopack==1.2.0`(Python312) | `vpk --version` 有输出;`python -c "import velopack"` 通过 | 真机执行(dotnet 在沙箱无输出,需用户本机确认) |
| **M1 最小打包** | build 出 Velopack 产物;PyInstaller 包内 import velopack 正常(无 hidden import 缺失) | Releases\ 含 Setup.exe + nupkg + portable.zip + releases.win.json;Setup 真机全新安装→启动→托盘→手势可用 | M0 |
| **M2 入口与钩子** | main.py 接入 `velopack.App().run()` + `on_restarted`;安装/卸载/更新参数链路打通 | 安装后首启正常;更新后重启自动弹"已更新";卸载后无残留进程/快捷方式 | M1 |
| **M3 更新链路** | updater.py 重写 + app.py 对接;验证全量/增量(delta)更新;下载进度;失败提示;绿色版 portable 自更新 | 旧版(装 0.0.8)→ 检测 → 下载 → 应用 → 新版启动 → 弹确认;断网/取消不崩溃;portable 更新同样成功 | M2 |
| **M4 发布与桥接** | build.bat 改造;.iss/Inno 退役;文档/测试/版本策略;老 Inno 用户桥接(§6) | 全量验收清单(§8)通过;发布一版走完整流程 | M3 |

---

## 6. 老 Inno 用户桥接(关键取舍)

老用户分两类,核心前提是**配置在 %APPDATA%,与程序目录无关**,所以迁移不会丢用户数据:

1. **Inno 安装版用户(会点自动更新)**:迁移版发版时,把 vpk 生成的 `Setup.exe`
   额外以 `Setup-CADGesture-vX.Y.Z.exe` 命名上传(§4.5 的 copy 步骤)。旧自研 updater
   仍会下载到该文件并静默运行 → 实为 Velopack one-click 安装器,用户在无感知下
   完成迁移(装到 Velopack 每用户目录)。成功后旧 %TEMP% 更新标记被迁移版首启消费,
   弹一次"已更新"。**遗留**:程序列表会出现 Velopack 新条目,旧 Inno 条目残留
   (两个卸载入口)——Release notes 引导卸载旧条目一次。若要彻底自动,需迁移版检测旧
   `unins000.exe` 并触发卸载,列为可选增强(不阻塞主线,单独评估)。
2. **绿色版用户**:下载新版 portable zip 解压覆盖即可(配置保留),无迁移负担。

**风险提示**:迁移版发布前必须确认旧 updater 下载到的确实是 Velopack Setup(文件名
匹配 + 双击行为正确),否则老用户会卡在"更新失败"。

---

## 7. 测试验收清单(迁移完成标准)

- [ ] `py_compile` 全绿;`pytest tests/ -q` 全绿(updater 测试已重写,其余回归不动)
- [ ] M1 全新安装:Velopack 每用户目录、开始菜单/桌面快捷方式、卸载入口、安装后启动正常
- [ ] 安装/卸载后 `%APPDATA%\CADGesture` 配置保留;程序目录残留清干净
- [ ] 增量更新:0.0.8 → 0.0.9 只下 delta(看下载体积明显小于全量);断网重试不崩溃
- [ ] 绿色版 portable zip:解压运行 → 手动检查更新 → 更新成功且版本正确
- [ ] 更新全程托盘/钩子正常:应用更新时旧实例干净退出、无多托盘图标
- [ ] 老 Inno 安装版经桥接链路升级成功(§6 场景 1)
- [ ] 全新用户经 Setup.exe 安装即最新版,无更新提示;手动检查提示"已是最新"
- [ ] 版本号:程序内"关于"显示、Setup 安装信息、feed 版本三方一致

---

## 8. 风险与对策

| 风险 | 影响 | 对策 |
|---|---|---|
| 本机 dotnet SDK 缺失/沙箱不可运行(sandbox 中 `dotnet --version` 无输出) | M0 卡住 | M0 在用户真实 shell 确认;缺则装 .NET 8 SDK(官方安装器,一次) |
| velopack 客户端与 PyInstaller 打包兼容问题(velopack.pyd 未被收集) | 打包产物启动报 ImportError | M1 先验证;必要时 `--hidden-import velopack` 或确认 wheel 的 abi3 pyd 被自动收集 |
| Python 侧 `apply_updates_and_restart` 退出时序不符合预期(进程未自动退出) | 更新卡在"等待退出" | 用 `wait_exit_then_apply_updates`;以 M3 实测两种 API 决定;注释写根因 |
| GitHub 未认证 API 限流(60 次/h/IP) | 更新检查 403 | 沿用低频策略(自动 24h + 手动);预留 `update_token` 配置;国内可配 HttpSource 镜像(update_source_url 扩展) |
| 老 Inno 用户桥接文件名不匹配 | 老用户更新失败 | M4 前用 0.0.8 环境实测桥接链路(§6) |
| SmartScreen/Defender 误报(无签名) | 新用户安装被拦 | 与现状相同;文档 FAQ 已有指引;Velopack 支持 `--signTemplate`,未来接代码签名时直接受益 |
| delta 更新依赖相邻版本;跨多版本用户 | 大版本跳跃时无 delta 会回退全量 | Velopack 自动 fallback 全量(默认最多考虑 10 个 delta),无需处理 |

---

## 9. 待确认决策点(不阻塞 M0/M1)

1. **packId 命名**:建议 `CADGesture`(与 Inno AppId GUID 体系无关,Velopack 每用户目录/卸载项均以此为标识)。
2. **绿色版分发命名**:portable zip 是否额外复制一份旧名 `CADGesture-vX.Y.Z.zip` 上传(便于老绿色版用户找文件)?建议是,README 同步。
3. **旧 Inno 条目自动卸载**:是否做迁移版自动检测并触发旧 Inno 卸载(可选增强,评估后单独排期)。
4. **更新检查 Token**:是否现在就预留 `update_token` 配置位(默认空)。
