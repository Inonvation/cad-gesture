# CADGesture 安装包（Inno Setup）+ 一键更新 实施规划

> 版本：v1.0（规划稿）
> 日期：2026-08-09
> 状态：✅ 已实施（2026-08-10，待发版 v0.0.3 验证端到端更新链路）
> 背景：当前仅发布绿色版 onefile exe（28.7MB，双击即用）。本规划新增**安装版 Setup.exe** 与**程序内一键更新**，双形态发布。

---

## 1. 目标与总览

| 形态 | 产物 | 用户场景 |
|------|------|----------|
| 绿色版（现有） | `dist\CADGesture-x64.exe` | 免安装，双击即用 |
| 安装版（新增） | `dist\Setup-CADGesture-vX.Y.Z.exe` | 走标准安装向导，开始菜单/卸载入口 |
| 自动更新（新增） | 程序内 `src/updater.py` | 检测新版 → 下载 Setup → 静默覆盖安装 |

**核心原理（决定一切设计）**：用户配置在 `%APPDATA%\CADGesture\config.json`，**与 exe 位置无关**。
→ 安装/覆盖/卸载都不影响配置，两种形态可无缝互换。

```
PyInstaller onefile ──> CADGesture-x64.exe（绿色版）
        │
        └──> Inno Setup 打包 ──> Setup-CADGesture-vX.Y.Z.exe（安装版）
                                     │
      程序内 updater.py 下载新版 Setup ──> 静默安装（/VERYSILENT）──> 覆盖更新
```

---

## 2. 前置准备（第一步做）

1. 下载安装 **Inno Setup 6**：https://jrsoftware.org/isdl.php
   - 安装时保持默认选项（含命令行编译器 ISCC.exe）
   - 安装后确认：`C:\Program Files (x86)\Inno Setup 6\ISCC.exe` 存在
   - Inno Setup 6 自带简体中文语言文件 `Languages\ChineseSimplified.isl`
2. 确认 Python312 环境可用（打包必需，现有流程不变）

---

## 3. Inno Setup 脚本设计（新增 `cad_gesture.iss`）

### 3.1 关键配置决策

| 项目 | 决策 | 理由 |
|------|------|------|
| 安装目录 | `{localappdata}\Programs\CADGesture` | 免 UAC 弹窗，对小白友好 |
| 装入内容 | 仅 `CADGesture-x64.exe` + `config.example.json`（装到 `config\` 子目录） | 用户配置在 `%APPDATA%`，安装器不碰 |
| 快捷方式 | 开始菜单（"CAD鼠标手势"文件夹）；不做桌面快捷方式 | 托盘程序无需桌面图标 |
| 自动关闭程序 | `CloseApplications=yes`（Inno 6.2+） | 更新时旧版在运行也能覆盖 |
| 版本号 | `#define MyAppVersion` 从 `version.txt` 预处理读取 | 单一版本来源 |
| 向导语言 | 简体中文 | `Languages\ChineseSimplified.isl` |
| 卸载 | 标准卸载器，自动保留 `%APPDATA%` 配置 | Inno 只删自己装的文件 |

### 3.2 脚本骨架（明日照此实现）

```ini
; cad_gesture.iss
#define MyAppName "CAD鼠标手势"
#define MyAppExeName "CADGesture-x64.exe"
; 版本号从 version.txt 中读取（PyInstaller VSVersionInfo 格式的 FileVersion 行）
#define MyAppVersion "0.0.2"   ; 构建时可用脚本/预处理器自动替换

[Setup]
AppId={{8E1F2A3B-4C5D-4E6F-8A7B-9C0D1E2F3A4B}}   ; 固定 GUID，覆盖安装依赖它
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=CAD Gesture
DefaultDirName={localappdata}\Programs\CADGesture
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
Compression=lzma2/max
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=Setup-CADGesture-{#MyAppVersion}
CloseApplications=yes
CloseApplicationFilter=CADGesture-x64.exe
PrivilegesRequired=lowest          ; 无需管理员
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "startmenu"; Description: "创建开始菜单快捷方式"; GroupDescription: "快捷方式:"

[Files]
Source: "dist\CADGesture-x64.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config\config.example.json"; DestDir: "{app}\config"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动"; Flags: nowait postinstall skipifsilent
```

**注意事项**：
- `AppId` GUID 一旦确定**不可更改**（改了就变成"另一个软件"，覆盖安装失效）
- `PrivilegesRequired=lowest` + `{localappdata}` = 免 UAC
- `Flags: ignoreversion` = 覆盖安装时直接覆盖旧文件（关键）
- 卸载入口自动出现在"程序和功能"（设置 → 应用）

### 3.3 静默安装参数（供自动更新调用）

```
Setup-CADGesture-vX.Y.Z.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-
```

- `/VERYSILENT`：无界面安装
- `/SUPPRESSMSGBOXES`：不弹任何确认框
- `/NORESTART`：不重启系统
- `/SP-`：跳过"是否安装到该目录"确认
- 静默安装完成后 [Run] 节自动启动新版本（skipifsilent 不生效？注意：`skipifsilent` 会在静默模式下跳过启动——需要时改为 `nowait`）

> ⚠️ 静默模式下 [Run] 的 `skipifsilent` 标志会跳过启动动作。若要更新后自动拉起新版，需去掉 `skipifsilent` 或使用 `Flags: nowait`。**明日实现时以实际行为为准测试。**

---

## 4. 自动更新模块设计（新增 `src/updater.py`）

### 4.1 更新流程（状态图）

```
托盘菜单"检查更新" / 启动时后台静默检查
    ↓
GET https://api.github.com/repos/Inonvation/cad-gesture/releases/latest
（必须带 User-Agent 头，否则 403）
    ↓
解析 JSON：tag_name（v0.0.3）、body（更新说明）、assets[].name/browser_download_url
    ↓
版本比对（数字逐段比较，0.0.9 < 0.0.10，不能字符串比）
    ↓
有新版：
    ├─ 弹出更新窗口：版本号 + 更新说明 + [立即更新] [稍后]
    ├─ 流式下载 Setup exe 到 %TEMP%\CADGesture-Setup.exe（显示进度条）
    ├─ 校验下载文件大小与 Release assets 一致（防止残缺）
    ├─ 确认框"将退出程序并自动完成更新"
    ├─ 程序保存状态并退出
    └─ 运行 Setup.exe /VERYSILENT /SUPPRESSMSGBOXES /NORESTART（脱离进程运行）
无新版：托盘气泡"已是最新版本"（手动检查时）
```

### 4.2 模块接口（明日实现参考）

```python
# src/updater.py
def check_for_update(current_version: str, update_url: str) -> dict | None
    # 返回 {"version": "0.0.3", "notes": "...", "download_url": "..."} 或 None

def download_update(url: str, dest: str, progress_cb) -> bool
    # 流式下载到 %TEMP%，带进度回调

def run_installer(installer_path: str)
    # subprocess.Popen 启动静默安装（不等待，父进程已退出）
```

### 4.3 settings 新增配置项（3 个）

| 配置项 | 默认值 | 说明 |
|--------|--------|------|
| `check_update_on_start` | `true` | 启动时后台静默检查（不弹窗，仅托盘气泡） |
| `update_source_url` | `https://api.github.com/repos/Inonvation/cad-gesture/releases/latest` | 可改镜像源（国内用户） |
| `last_update_check` | `""` | 上次检查时间，控制检查频率（如 24h 一次） |

**联动修改（AGENTS.md 的改动联动清单）**：
- `config_presets.py` 的 `_default_config` 加默认值
- `config_manager.py` 的 `_migrate_config` 补字段（旧配置自动迁移）
- `app.py` 托盘菜单加"检查更新"项 + 启动时调度
- `qt_settings_panel.py` 常规设置卡片加 3 个开关/输入框（可选，先不加 UI 也行）

### 4.4 GitHub API 细节

- API：`GET /repos/{owner}/{repo}/releases/latest`，无需 token（60 次/小时/IP 限制，个人软件够用）
- 请求头必须含 `User-Agent`，否则 403
- Release 附件命名约定：`Setup-CADGesture-v0.0.3.exe`（与 Inno 的 OutputBaseFilename 一致）
- 版本号来源：`version.txt` 由 `config_manager` 或固定路径读取（打包时 `version.txt` 在 exe 同级；打包后读取方式用 `os.path.join(os.path.dirname(sys.executable), ...)` 或内置常量）

---

## 5. 文件变更清单（完整）

### 5.1 新增文件

| 文件 | 说明 |
|------|------|
| `cad_gesture.iss` | Inno Setup 脚本（项目根目录，与 spec 同级） |
| `src/updater.py` | 自动更新模块 |
| `tests/test_updater.py` | 版本比对/解析逻辑测试（网络部分 mock） |

### 5.2 修改文件

| 文件 | 改动 | 联动依据 |
|------|------|----------|
| `scripts/build.bat` | 增加 [4/5] ISCC 编译 Setup 步骤（见第 6 节） | 打包流程 |
| `src/app.py` | 托盘菜单加"检查更新"；启动时调度检查；退出前保存状态 | 事件流 |
| `src/config_presets.py` | `_default_config` 加 3 个 update 配置项 | 改动联动清单 |
| `src/config_manager.py` | `_migrate_config` 补 update 字段 | 改动联动清单 |
| `src/logger.py` | 无需改（复用现有日志） | — |
| `AGENTS.md` | 更新架构图（加 updater.py）、打包流程（加 ISCC）、发版流程（双附件）、`build.bat` 位置说明 | 文档同步 |
| `README.md` / `README.en.md` | 下载区说明两种形态 + 自动更新说明；FAQ 加"如何更新/被 SmartScreen 拦截" | 文档同步 |
| `version.txt` | 发版时更新 4 处（filevers/prodvers/FileVersion/ProductVersion） | 发版流程 |

### 5.3 不需要动的

- `requirements.txt`：更新模块用 urllib 标准库，零新依赖
- `cad_gesture.spec`：PyInstaller 配置不变（updater.py 被 app.py 引用会自动收集）
- 配置目录结构：`%APPDATA%\CADGesture` 不变

---

## 6. 构建流程（scripts/build.bat 新版本）

现有脚本：清理 → PyInstaller → 复制 config → 完成
新脚本：**清理 → PyInstaller → 复制配置 → ISCC 编译 Setup → 完成**

```
[1/5] 清理 build\ 和 dist\
[2/5] PyInstaller: python -m PyInstaller cad_gesture.spec --clean --noconfirm
[3/5] 复制 config\config.json → dist\config\（现有逻辑保留）
[4/5] ISCC 编译: "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" cad_gesture.iss
      （.iss 里 Source 指向 dist\CADGesture-x64.exe，OutputDir 指向 dist）
[5/5] 输出:
      dist\CADGesture-x64.exe            （绿色版）
      dist\Setup-CADGesture-v0.0.2.exe   （安装版，新增）
```

**实现要点**：
- `.iss` 的 `Source` 路径用相对路径（相对 .iss 文件所在目录），ISCC 从项目根目录运行
- 版本号注入：ISCC 命令行传参 `/DMyAppVersion=0.0.2`，或写个小脚本从 version.txt 正则提取 `FileVersion` 后替换 `.iss` 里的占位符
  - 简单方案：`scripts\build.bat` 里用 findstr 读 version.txt 的 FileVersion 行，`set VERSION=0.0.2`，然后 `ISCC.exe /DMyAppVersion=%VERSION% cad_gesture.iss`
- `build.bat` 已有 `chcp 65001`，中文路径安全

---

## 7. 发版流程（更新后完整版）

> 基于 AGENTS.md 现有发版流程扩展，新增/变化处用 ★ 标出

1. **更新版本号**：`version.txt` 4 处（`filevers`/`prodvers`/`FileVersion`/`ProductVersion`，当前 0.0.2 → 0.0.3）
2. **★ 确认 `cad_gesture.iss` 的 `AppVersion` 一致**（用 build 脚本自动注入则无需手工改）
3. **打包**：运行 `scripts\build.bat`（Python312 PyInstaller + ISCC）
   - 产物：`dist\CADGesture-x64.exe` + `dist\Setup-CADGesture-v0.0.3.exe`
4. **自测**：绿色版双击跑一遍；Setup 全新安装一遍（另一台机器或沙箱）
5. **提交**：`version.txt` + 本次代码改动，commit 一次
6. **打 tag**：`git tag -a v0.0.3 -m "v0.0.3"`
7. **push**：`git push origin master --tags`
8. **★ 创建 Release 前向用户展示**：版本号、两个 exe 路径/体积、Release notes、附件清单，用户确认后执行（AGENTS.md 强制要求）
9. **★ 创建 Release**（附件 3 个）：
   ```
   gh release create v0.0.3 --title "v0.0.3" --notes "..." \
     dist/CADGesture-x64.exe \
     dist/Setup-CADGesture-v0.0.3.exe \
     config/config.example.json
   ```
   - Release notes 格式：**新增/修复/已知问题** 三段，同步进 CHANGELOG（建议新建 `CHANGELOG.md`，从本版本开始记录）
10. **★ 发布后验证更新链路**：手动触发"检查更新" → 应检测到 v0.0.3 → 下载 → 静默安装 → 新版启动

**注意**：`gh release create` 的附件**绝不包含** `config/config.json`（用户私有），只发 `config.example.json` 模板。

---

## 8. 测试验收清单（明日完成标准）

### 8.1 安装包
- [ ] 全新安装：向导中文、默认目录 `%LOCALAPPDATA%\Programs\CADGesture`、开始菜单有图标和卸载入口
- [ ] 安装后 `%APPDATA%\CADGesture` 无残留垃圾、程序正常启动、托盘正常
- [ ] **配置保留**：安装前手动改配置（如主题改 crimson）→ 卸载 → 重装 → 配置仍在
- [ ] 旧版绿色版 exe 在运行时 → 静默安装 Setup（模拟更新）→ 自动关进程、覆盖成功
- [ ] "程序和功能"里能看到"CAD鼠标手势"，卸载只删程序文件

### 8.2 自动更新
- [ ] 版本比对函数单测：0.0.9 < 0.0.10、v 前缀处理、非法版本容错
- [ ] 手动"检查更新"→ 无新版提示 / 有新版显示说明
- [ ] 下载进度条显示正常，下载中断（断网）有错误提示不崩溃
- [ ] 完整更新链路：v0.0.2 环境 → 检测到 v0.0.3 → 下载 → 静默安装 → 自动启动 v0.0.3 → 配置保留
- [ ] 更新失败回退：安装失败时程序还能正常用（旧版未被破坏）

### 8.3 回归
- [ ] `python -m py_compile` 全绿
- [ ] `python -m pytest tests/ -q` 全绿（原 39 项 + 新增 updater 测试）
- [ ] 绿色版 exe 功能不受影响（手势、配置界面、主题）

---

## 9. 风险与备选方案

| 风险 | 影响 | 对策/备选 |
|------|------|-----------|
| SmartScreen/Defender 拦截无签名安装器 | 用户看到"未知发布者"提示 | 文档 FAQ 说明"点更多信息→仍要运行"；未来买代码签名证书（约 ¥400/年） |
| 国内用户 GitHub 下载慢/失败 | 更新失败 | `update_source_url` 可配置镜像；下载失败提示重试不崩溃 |
| GitHub API 60 次/小时限制 | 检查更新 403 | 启动检查频率限制（24h 一次）；API 失败静默跳过，不打扰用户 |
| 静默安装 [Run] 启动行为与预期不符 | 更新后不自动启动 | 以实际测试为准调整 Flags（见 3.3 注意事项） |
| `AppId` GUID 写错/改了 | 覆盖安装变双安装 | 文档固化 GUID，一次写死 |

---

## 10. 实施顺序（明日步骤）

| 步骤 | 任务 | 预估 |
|------|------|------|
| 1 | 安装 Inno Setup 6，确认 ISCC.exe 路径 | 10 分钟 |
| 2 | 写 `cad_gesture.iss`，手工 ISCC 编译一次，全新安装测试 | 1 小时 |
| 3 | 改 `scripts\build.bat` 集成 ISCC（版本号注入） | 30 分钟 |
| 4 | 写 `src/updater.py` + `tests/test_updater.py`（版本比对/解析） | 1.5 小时 |
| 5 | `app.py` 托盘菜单 + 启动检查 + `config_presets`/`config_manager` 迁移字段 | 1 小时 |
| 6 | 全流程测试（第 8 节清单）+ 修复 | 1.5 小时 |
| 7 | 更新 AGENTS.md / README / README.en.md / 新建 CHANGELOG.md | 1 小时 |
| 8 | 按第 7 节发版流程走一遍 v0.0.3 | 1 小时 |

总计约 **1 天**（含测试缓冲）。

---

## 11. 与现有流程的衔接确认（防遗漏）

- [x] `scripts/build.bat` 是唯一打包入口（AGENTS.md 有引用，脚本在 `scripts\` 下，注意 AGENTS.md 里写的 `build.bat` 指 `scripts\build.bat`）
- [x] 打包必须用 Python312（`C:\Users\cy\AppData\Local\Programs\Python\Python312\python.exe`）
- [x] 单实例机制：更新时 `CloseApplications` 会关闭旧实例，新实例启动无互斥冲突
- [x] 开机自启：安装版卸载时注册表自启项（如有）由程序卸载逻辑清理，安装器不管理自启
- [x] 配置迁移：`_migrate_config` 补 3 个 update 字段，旧用户升级无感
- [x] 版本号单一来源：`version.txt`（PyInstaller 4 处 + Inno 注入同源）
