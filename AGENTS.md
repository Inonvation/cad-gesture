# CAD 鼠标手势工具 — Agent 指南

## 项目概述

8 扇区径向圆盘菜单（内层/外层/扩展圈三层）：长按右键拖动 → 弹出菜单 → 释放触发 CAD 命令。
支持 AutoCAD 2025+ 和中望CAD，Python 3.11+ / Win32 API / PySide6(Qt6) / PyInstaller 打包。

**核心设计（方案B）**：钩子只监听不拦截 → CAD 收到右键释放可能弹上下文菜单 → 工具随后发 ESC 取消 → 命令优先走 COM `SendCommand`，不影响十字光标。

## 用户特征

技术小白，第一次开发桌面工具。表述可能模糊、含错或使用非专业术语。将模糊需求翻译为可执行方案，对错误指令主动质疑和修正。

## 架构

```
main.py                 # 入口（含单实例检查）
config/config.json      # 旧版配置位置（0.0.2-：仅迁移用，现配置在 %APPDATA%\CADGesture）
cad_gesture.iss         # Inno Setup 安装包脚本（产出 Setup-CADGesture-vX.Y.Z.exe）
src/
├── app.py              # 主类（Qt）：事件队列、托盘(QSystemTrayIcon)、Profile切换、配置入口、更新流程
├── gesture_engine.py   # [核心] WH_MOUSE_LL 钩子 → 方向/圈层判定
├── qt_radial_menu.py   # [核心] Qt 透明悬浮圆盘菜单（三层绘制 + 淡入/高亮动画）
├── menu_geometry.py    # 圆盘半径/缩放唯一来源（运行时菜单、手势引擎、两处预览共用）
├── qt_renderer.py      # 共享 Qt 圆盘绘制（qt_radial_menu 运行时 与 qt_config_gui/qt_settings_panel 预览共用）
├── theme.py            # 界面配色 + 8 套圆盘外观主题（+ 自定义主色）
├── command_executor.py # COM SendCommand + pyautogui 回退
├── config_manager.py   # JSON 配置读写 + Profile管理 + 自动迁移
├── config_presets.py   # 预设命令库 + 默认配置
├── qt_config_gui.py    # Qt 配置界面（三栏 + 撤销重做 + 右键放置 + Delete 删除）
├── qt_popup.py         # 扇区编辑浮层控制器（定位/信号接线，定位算法可单测）
├── qt_profile_ops.py   # 方案增删改查/导入导出的纯函数（无 Qt，可单测）
├── updater.py          # 自动更新（版本比对/检查/下载/静默安装，纯逻辑无 Qt）
├── version.py          # 运行时版本号常量（发版时与 version.txt 同步）
└── single_instance.py  # 命名互斥体单实例 + 覆盖更新
```

事件流：钩子线程 → `queue.Queue` → 主线程 `_process_queue()`（QTimer 驱动，菜单可见 16ms / 隐藏 200ms）。
每个事件包裹 `try-except`，防止单次错误崩溃整个队列循环。
更新流程同模式：后台线程检查/下载 → 结果经 event_queue（`update_check_result` / `update_progress` / `update_download_done`）→ 主线程弹窗。

**触发与圈层判定**：触发 = 右键按下后滑动超过 `trigger_distance` 立即弹出（对齐 Quicker，
不等长按时间），或按住超过 `hold_threshold_ms` 且有轻微位移时弹出。判定在独立轮询线程
（每 15ms），不受鼠标事件频率影响，鼠标停住也能按时触发。
圈层判定（半径统一取自 `menu_geometry.py` 的 `DEFAULT_RADII`，gesture_engine 触发、
qt_radial_menu hover、配置两处预览共用）：
距离 ≤ `ring_radius`(70) = 内层；≤ `outer_ring_radius`(135) = 外层；> `ext_ring_radius`(185) = 扩展圈
（命令在 `extension_sectors`）。整体缩放由 `menu_scale`（50~150%）控制。

## 环境关键坑（务必先读）

- **Python 双解释器**：`python` 命令可能命中多个环境。hermes venv 的 `python.exe` 是 uv launcher，运行 `main.py` 时会 spawn 真解释器（uv cpython）——启动后看到"一对 python 进程"是**正常现象**。启动/验证统一用 hermes venv 的 python：
  `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe`
- **绝不用 PowerShell 改中文文件**：PowerShell 的 `Get-Content`/`Set-Content` 按 GBK 读 UTF-8 会永久损坏中文（乱码不可逆）。改含中文的 .py/.json 必须用 edit/write 工具；批量替换用 python 脚本（`open(path, encoding='utf-8')`）。
- **`scripts\build.bat` 必须保持 GBK 编码 + CRLF 行尾**：cmd 按系统代码页（GBK）解析 bat，UTF-8/LF 会让中文行被拆成碎片命令（曾经踩坑）。**绝不用 edit/write 工具改它**（会写成 UTF-8）；如需修改：先用 edit 改一个 UTF-8 副本，再跑 `python -c "d=open(p,'rb').read().decode('utf-8');d=d.replace('\r\n','\n').replace('\n','\r\n');open(p,'wb').write(d.encode('gbk'))"` 转回 GBK+CRLF。同理 `scripts\verify.bat`。
- **Qt 单应用单线程**：主程序是 `QApplication`（`app.py` 创建）。Qt 控件只能在主线程操作（QObject 非线程安全）；托盘/菜单回调都运行在主线程，无需跨线程投递。配置界面 `qt_config_gui.open_config_gui(on_save=...)` 返回独立 `QMainWindow`（非模态），app 用 `self._config_win` 持有引用防 GC。
- **Qt 坐标是逻辑像素，钩子给物理像素**：`QRadialMenu.show(x, y)` 内部用 `_to_logical` 按所在屏幕 DPI 换算，圆盘中心才对准鼠标。别直接拿钩子的 `pt.x/pt.y` 去 `move()`（DPI 缩放≠100% 时圆盘会偏移）。
- **单实例机制**：`main.py` 开头 `ensure_single_instance()` 用命名互斥体判断，新实例会置位命名事件请求旧实例优雅退出（覆盖更新，避免多托盘图标）。app.py 主循环每 32 帧轮询 `is_exit_requested()`。启动逻辑别改坏这两处。

## 改动联动清单（一处改动，多处必须同步）

| 改动内容 | 必须同步的地方 |
|---------|---------------|
| 圆盘配色/主题 | `theme.py` 的 `MENU_THEMES`（8 套 + 自定义，配置界面主题下拉自动读取） |
| 字体/标签位置/扇区绘制 | `qt_renderer.py`（`qt_radial_menu` 运行时、`qt_config_gui` 编辑预览、`qt_settings_panel` 尺寸预览共用，三处必须一致） |
| 新增 `settings` 配置项 | `config_presets._default_config` + `config_manager._migrate_config`（迁移补字段） + 需要时 `qt_config_gui`/`qt_radial_menu`/`gesture_engine`/`app.py`；半径/缩放类同时改 `menu_geometry.py` |
| 发版改版本号 | `version.txt` 4 处（filevers/prodvers/FileVersion/ProductVersion） + `src/version.py` 的 `__version__`（共 5 处，`.iss` 由 build.bat 自动注入） |
| 新增命令预设 | `config_presets` 默认 profile + `command_executor` 的 `COMBO_TO_COMMAND` 表 |
| 新增界面文案 | `i18n.py` 翻译表 + 界面文本用 `T()` 包裹（中文模式 key 即原文） |
| 新增 Python 依赖 | `requirements.txt` + `cad_gesture.spec`（PySide6 由 PyInstaller 内置 hook 自动收集） |
| 改圈层/触发阈值 | 只改 `menu_geometry.py` 的 `DEFAULT_RADII`（gesture_engine 与 qt_radial_menu 都从它取） |

## 一键验证

改完代码用 `python scripts\verify.py`（或双击 `scripts\verify.bat`）：自动跑 `py_compile` → `pytest` → 启动新实例（单实例机制自动覆盖旧实例，不杀进程）。

## 命令

```bash
python main.py                        # 调试运行（有控制台输出）
python -m py_compile src\xxx.py       # 快速语法校验（改完先跑）
python -m pytest tests/ -q            # 运行测试（pytest：test_config.py + test_qt_renderer.py）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**无 lint / typecheck / CI 流程。** 验证方式是 `py_compile` + `pytest` + `python main.py` 手动测试。

## 测试流程

**改完代码先 `py_compile` → `pytest` → 启动 `python main.py` 手动验证，不要打包。** 打包很慢，只有最终发布时才需要。

## 打包流程（仅发布时使用）

**打包必须用 Python312**（`<USER>\AppData\Local\Programs\Python\Python312\python.exe`），其他 Python 环境可能缺 PyInstaller。

**统一入口：双击 `scripts\build.bat`**，一次产出双形态：
- 绿色版：`dist/CADGesture-x64.exe`
- 安装版：`dist/Setup-CADGesture-vX.Y.Z.exe`（需先安装 Inno Setup 6.3+，`C:\Program Files (x86)\Inno Setup 6\ISCC.exe`）

build.bat 流程：清理 → PyInstaller（Python312）→ 复制配置 → `scripts\read_version.py` 提取版本号 → `ISCC /DMyAppVersion=...` 编译安装包。

手动打包（等价）：
```powershell
cd F:\cad-gesture
Get-Process CADGesture-x64 -ErrorAction SilentlyContinue | Stop-Process -Force
& "<USER>\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller cad_gesture.spec --clean --noconfirm
Copy-Item config\config.example.json dist\config\config.example.json -Force  # 发版用模板；本地自测可复制 config.json
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=0.0.2 cad_gesture.iss
dist\CADGesture-x64.exe
```

### 打包前检查清单

1. 关闭所有 CADGesture-x64.exe 进程
2. Python312 环境装依赖（`requirements.txt` 含 `PySide6`）
3. `config/config.json` 存在
4. `assets/icon.ico` 存在（`python scripts\generate_icon.py` 生成）

`cad_gesture.spec` 的 PySide6 由 PyInstaller 内置 hook 自动收集（Qt 插件/DLL），改依赖时同步检查 spec。

### 常见错误速查

| 错误现象 | 原因 | 解决 |
|---------|------|------|
| `PermissionError` / `Access denied` | exe 正在运行 | 关闭 exe 后重试 |
| 打包成功但 exe 启动闪退 | 缺隐式导入/DLL/PySide6 插件 | 先 `python main.py` 确认源码没问题 |
| `ModuleNotFoundError: PySide6` | 装到了别的 Python | 用 Python312 的 pip 装 `requirements.txt` |
| `pywintypes` DLL not found | pywin32 DLL 路径错误 | 确认 spec 的 `pywin32_system32/` 路径 |

## 发版流程（打 tag 发布 GitHub Release）

1. 更新 `version.txt` 版本号（4 处：`filevers`/`prodvers`/`FileVersion`/`ProductVersion`）+ `src/version.py` 的 `__version__`（共 5 处）
2. 打包双产物：双击 `scripts\build.bat`（PyInstaller + ISCC，UPX 已在用户 PATH）
   - 产物：`dist/CADGesture-x64.exe` + `dist/Setup-CADGesture-vX.Y.Z.exe`
3. 提交 version.txt + 本次改动，打 annotated tag：`git tag -a vX.Y.Z -m "vX.Y.Z"`
4. `git push origin master --tags`
5. **创建 Release 前，必须先向用户展示待发布内容（版本号、两个 exe 路径/体积、Release notes、附件清单）并等待用户确认**，确认后再执行下一步
6. `gh release create vX.Y.Z --title "vX.Y.Z" --notes "..." dist/CADGesture-x64.exe dist/Setup-CADGesture-vX.Y.Z.exe config/config.example.json`
   - 附件 3 个：绿色版 + 安装版 + `config.example.json`（模板），**绝不打包用户私有 `config/config.json`**
7. 发布后实测更新链路：托盘"检查更新" → 检测到新版 → 下载 → 静默安装 → 新版自动启动

## 关键技术细节

- 钩子回调必须返回 `c_ssize_t`（非 `c_long`），否则 64 位崩溃
- `CallNextHookEx` 必须设 `argtypes`，否则参数溢出
- `GetModuleHandleW(None)` 在 ctypes 中传 `None`（非 0）
- 圆盘菜单用 Qt `QRadialMenu`：`FramelessWindowHint` + `WA_TranslucentBackground` 实现透明悬浮窗，`WA_ShowWithoutActivating` 不抢焦点
- COM 发送前自动切换英文输入法：`PostMessage(WM_INPUTLANGCHANGEREQUEST)`
- 钩子线程退出：`stop()` 发 `PostThreadMessageW(WM_QUIT)`
- 事件队列格式：`("show", (x, y, window_type))` 元组嵌套
- **圆盘外观主题**：改圆盘配色去 `theme.py` 的 `MENU_THEMES`（8 套：azure/emerald/crimson/midnight/aurora/graphite/amber/mono + 自定义主色），由 `settings.menu_theme` 控制，`get_menu_theme(name)` 获取。改字体/位置/渲染去 `qt_renderer.py`（`draw_ring` 被运行时圆盘和两处预览共用，改动必须三处一致）。
- **圆盘几何**：半径/缩放统一从 `menu_geometry.py` 取（`DEFAULT_RADII` + `menu_scale`），不要在各模块里各自写死半径默认值。
- **配置自动迁移**：`config_manager._migrate_config` 自动补旧配置字段；空的 `extension_sectors` 会从默认配置按 target+name 自动补全。
- **自动更新**：检查/下载放后台线程，结果经 event_queue 回主线程（`update_check_result`/`update_progress`/`update_download_done`），Qt 控件只在主线程操作。下载到 `%TEMP%\CADGesture-Setup.exe` 后经 `run_installer` 静默安装（`/VERYSILENT /SUPPRESSMSGBOXES /NORESTART /SP-`），主进程随即退出，Inno 的 `CloseApplications` 兜底关进程。静默安装后新版自动启动已验证（[Run] 用 `nowait` 不带 `skipifsilent`）。
- **安装包卸载杀进程**：`cad_gesture.iss` 的 `[Code]` 节在卸载时 `taskkill /F` 终止主程序，否则运行中的 exe 被锁删不掉（卸载残留）。改 .iss 时别删这段。
- **onefile 下不能读 exe 同级文件**：`sys.executable` 在 PyInstaller onefile 运行时指向临时解压目录（`%TEMP%\_MEIxxxx`），当前版本号必须用 `src/version.py` 的内置常量，不要运行时读文件。

## 命令执行优先级

| 场景 | 方式 | 说明 |
|------|------|------|
| 键盘命令（`l`, `co`） | COM `SendCommand("_.LINE\n")` | CAD内部执行 |
| 组合键（`ctrl+z`） | COM 映射（`_.U`） | 见 `COMBO_TO_COMMAND` 表 |
| 剪贴板操作（`ctrl+c/v/x`） | pyautogui 回退 | 少数场景 |
| COM 全部失败 | pyautogui + ESC 取消菜单 | 兜底 |

## 配置结构

`%APPDATA%\CADGesture\config.json` — `settings` + `profiles`（与 exe 位置无关，用户可编辑；旧版 `config/config.json` 仅用于首次迁移）。每个 profile 有 `sectors`（内层）、`outer_sectors`（外层）、`extension_sectors`（扩展圈）。
字段：`description` = COM 命令名，`key` = pyautogui 回退键，`target` = `autocad`|`zwcad`。
`settings` 关键项：`menu_theme`（圆盘外观）、`menu_scale`（整体缩放 50~150%）、`menu_opacity`（不透明度）、`ui_mode`（dark/light/system）、`language`（zh/en）、`hold_threshold_ms`（长按延迟，默认 80）、`trigger_distance`（触发距离，默认 10，可调 5~40）、`open_config_on_start`、`auto_switch_profile`、`check_update_on_start`（启动时检查更新，默认 true）、`update_source_url`（更新源，默认 GitHub API）、`last_update_check`（上次检查时间，24h 频率控制）。

## 提交规范

格式：`前缀: 中文描述`（前缀英文小写，描述中文）

| 前缀 | 用途 |
|------|------|
| `feat:` | 新功能 |
| `fix:` | 修复 Bug |
| `perf:` | 性能优化 |
| `refactor:` | 重构 |
| `chore:` | 杂项、依赖 |
| `docs:` | 文档 |
| `build:` | 构建/打包 |

- 一个 commit 只做一件事
- 不要擅自提交，等用户确认
- 全部提交完后最后一次性 push

## 修改代码流程

1. 搜索受影响的调用方，确认改动范围
2. 读取相关文件上下文
3. 修改代码
4. **立即验证**（必须，不要跳过）：
   ```powershell
   python -m py_compile src\修改的文件.py
   python -m pytest tests/ -q
   # 后台启动主程序让用户看效果
   Start-Process "%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe" -ArgumentList "main.py" -WorkingDirectory "F:\cad-gesture"
   ```
   告诉用户"程序已启动，请查看改动效果"，然后继续下一步
5. 检查未使用的 import
6. 等用户确认后提交

**注意**：每次改完代码都要启动程序让用户看效果，不要等全部改完再验证。

**错误处理**：只负责自己修改的代码。遇到非本次修改造成的报错，告知用户即可，不要尝试修改。

## 调试

- 日志：文件 `%TEMP%\cad-gesture.log` + 控制台（`[Gesture]` 前缀）
- 用 `python main.py`（非 `pythonw`）看完整输出
- 托盘右键 → 配置 可编辑扇区
- 钩子安装失败：检查其他手势软件冲突（WGestures、Quicker）或杀毒拦截
- 命令错乱：确认输入法是英文（程序自动切换，首次可能需手动切一次）
