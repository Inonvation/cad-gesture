# CAD Gesture — Agent 指南

## 项目概述

8 扇区径向圆盘菜单（内层/外层/扩展圈三层）：长按右键拖动 → 弹出菜单 → 释放触发 CAD 命令。
支持 AutoCAD 2025+ 和中望CAD，Python 3.11+ / Win32 API / PySide6(Qt6) / PyInstaller 打包。

**核心设计（方案B）**：钩子只监听不拦截 → CAD 收到右键释放可能弹上下文菜单 → 工具随后发 ESC 取消 → 命令优先走 COM `SendCommand`，不影响十字光标。

## 用户特征

技术小白，第一次开发桌面工具。表述可能模糊、含错或使用非专业术语。将模糊需求翻译为可执行方案，对错误指令主动质疑和修正。

## 架构

```
main.py                 # 入口（单实例 + run()）
config/config.json      # 旧版配置位置（0.0.2-：仅迁移用，现配置在 %APPDATA%\CADGesture）
scripts/build.bat       # 一键打包（PyInstaller → Inno Setup → 绿色版 zip）
src/
├── app.py              # 主类（Qt）：事件队列、异步启动初始化(_init_late)、托盘(QSystemTrayIcon)、Profile切换、配置入口、更新流程
├── gesture_engine.py   # [核心] WH_MOUSE_LL 钩子 → 方向/圈层判定
├── qt_radial_menu.py   # [核心] Qt 透明悬浮圆盘菜单（三层绘制 + 淡入/高亮动画）
├── menu_geometry.py    # 圆盘半径/缩放唯一来源（运行时菜单、手势引擎、两处预览共用）
├── qt_renderer.py      # 共享 Qt 圆盘绘制（qt_radial_menu 运行时 与 qt_config_gui/qt_settings_panel 预览共用）
├── theme.py            # 界面配色 + 5 套圆盘外观主题（+ 自定义主色）
├── command_executor.py # COM SendCommand + pyautogui 回退
├── config_manager.py   # JSON 配置读写 + Profile管理 + 自动迁移
├── config_presets.py   # 预设命令库 + 默认配置
├── qt_config_gui.py    # Qt 配置界面（导航式 + 撤销重做 + 方案拖放排序 + Delete 删除）
├── qt_popup.py         # 扇区编辑浮层控制器（定位/信号接线，定位算法可单测）
├── qt_profile_ops.py   # 方案增删改查/导入导出的纯函数（无 Qt，可单测）
├── sw_key_assist.py    # [SW] 按键直通（默认）：键盘钩子拦截被输入法吞掉的单键 → 直投 SW 窗口
├── sw_ime_assist.py    # [SW] 输入法助手（可选回退）：按焦点自动切换键盘布局
├── updater.py          # 自动更新（GitHub Releases → 下载 Setup → Inno 静默安装）
├── version.py          # 运行时版本号常量（发版时与 version.txt 同步）
└── single_instance.py  # 命名互斥体单实例
```

事件流：钩子线程 → `queue.Queue` → 主线程 `_process_queue()`（QTimer 驱动，菜单可见 16ms / 隐藏 250ms）。
每个事件包裹 `try-except`，防止单次错误崩溃整个队列循环。
更新流程：后台线程检查（解析 Releases HTML）/下载（`Setup-CADGesture-vX.exe` 到 %TEMP%，
字节进度转百分比） → 结果经 event_queue（`update_check_result` / `update_progress_pct` /
`update_download_done`）→ 主线程弹窗。确认后静默启动 Inno 安装器并退出主进程。
启动流程：`run()` 先出托盘图标，QSS/圆盘/引擎/钩子在事件循环内由 `_init_late` 异步完成（`singleShot(0)` 排队）；配置界面、updater、pyautogui 均为延迟加载，启动只加载运行时必需模块。

**触发与圈层判定**：触发 = 右键按下后滑动超过 `trigger_distance` 立即弹出（对齐 Quicker，
不等长按时间），或按住超过 `hold_threshold_ms` 且有轻微位移时弹出。判定在独立轮询线程
（每 15ms），不受鼠标事件频率影响，鼠标停住也能按时触发。
圈层判定（半径统一取自 `menu_geometry.py` 的 `DEFAULT_RADII`，gesture_engine 触发、
qt_radial_menu hover、配置两处预览共用）：
距离 ≤ `ring_radius`(70) = 内层；≤ `outer_ring_radius`(135) = 外层；> `outer_ring_radius`(135) = 扩展圈（扩展圈绘制至 `ext_ring_radius`(185)）
（命令在 `extension_sectors`）。整体缩放由 `menu_scale`（50~150%）控制。

## 环境关键坑（务必先读）

- **Python 解释器现状（2026-09-10 复核）**：本机实际可用的是 **Python312**
  （`%LOCALAPPDATA%\Programs\Python\Python312\python.exe`），依赖齐全（PySide6 /
  pyautogui / pywin32 / pytest 9.0.2），`main.py`、`pytest`、`scripts\verify.py` 都用它。
  历史上用的 hermes venv（`%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe`）**本机已不存在**；
  若又看到"一对 python 进程"属正常（uv launcher 会 spawn 真解释器）。受管 python 3.13 无 pytest /
  PySide6 / tkinter，不要拿它跑测试或界面。
- **绝不用 PowerShell 改中文文件**：PowerShell 的 `Get-Content`/`Set-Content` 按 GBK 读 UTF-8 会永久损坏中文（乱码不可逆）。改含中文的 .py/.json 必须用 edit/write 工具；批量替换用 python 脚本（`open(path, encoding='utf-8')`）。
- **`scripts\build.bat` 必须保持 GBK 编码 + CRLF 行尾**：cmd 按系统代码页（GBK）解析 bat，UTF-8/LF 会让中文行被拆成碎片命令（曾经踩坑）。**绝不用 edit/write 工具改它**（会写成 UTF-8）；如需修改：先用 edit 改一个 UTF-8 副本，再跑 `python -c "d=open(p,'rb').read().decode('utf-8');d=d.replace('\r\n','\n').replace('\n','\r\n');open(p,'wb').write(d.encode('gbk'))"` 转回 GBK+CRLF。同理 `scripts\verify.bat`。
- **Qt 单应用单线程**：主程序是 `QApplication`（`app.py` 创建）。Qt 控件只能在主线程操作（QObject 非线程安全）；托盘/菜单回调都运行在主线程，无需跨线程投递。配置界面 `qt_config_gui.open_config_gui(on_save=...)` 返回独立 `QMainWindow`（非模态），app 用 `self._config_win` 持有引用防 GC。
- **Qt 坐标是逻辑像素，钩子给物理像素**：`QRadialMenu.show(x, y)` 内部用 `_to_logical` 按所在屏幕 DPI 换算，圆盘中心才对准鼠标。别直接拿钩子的 `pt.x/pt.y` 去 `move()`（DPI 缩放≠100% 时圆盘会偏移）。
- **单实例机制**：`main.py` 开头 `ensure_single_instance()` 用命名互斥体判断，新实例会置位命名事件请求旧实例优雅退出（覆盖更新，避免多托盘图标）。app.py 主循环每 32 帧轮询 `is_exit_requested()`。启动逻辑别改坏这两处。

- **PowerShell 管道会把中文弄坏（本次最大坑）**：`@'...'@ | python -` 的 here-string 传给 Python 时中文常损坏成 `?`/乱码，`$env:PYTHONUTF8='1'` 也不总是可靠。脚本/文件里出现中文时，一律改用 Node REPL（node_repl 的 js 工具）读写，或先让 Node 写 UTF-8 文件再让 Python 读取；PowerShell here-string 只适合纯 ASCII。
- **git commit message 含中文**：绝不用 `git commit -m "中文"`（PowerShell 直传会乱码），也不要让中文经 PowerShell here-string 写进 message 文件。可靠流程：Node 写 UTF-8 message 文件 → `git commit -F <文件>`。提交后必须验证：`git cat-file commit HEAD` 看原始字节是否 UTF-8——终端显示正常不代表存对了（PowerShell 管道会把 git 输出的 UTF-8 显示成乱码假象）。验证文件内容用 Python subprocess capture 或直接读文件，别用 `git show | python` 经管道（会乱码+行尾转换）。
- **低级键盘钩子回调禁止做重活（sw_key_assist）**：`WH_KEYBOARD_LL` 回调只做「读快照 +
  廉价判定 + 入队」，绝不 `OpenProcess` / `SendMessage` / 任何 IPC。回调超时会拖慢全局输入，
  且 Windows 会静默移除超时的钩子（`LowLevelHooksTimeout`，默认 300ms）。重活放两处：
  主线程 100ms 轮询（`probe_context` 采集）+ 独立投递线程。
- **钩子回调必须先判 `LLKHF_INJECTED` 并放行**：这是「不改动 CAD 逻辑」的技术保证 —— CAD 的
  pyautogui 回退注入的正是注入键，吞掉会让手势命令失聪；同时避免自己的注入被自己再吞（回环）。
- **SW 按键直通的作用域**：只在 `SLDWORKS.exe` 前台、且焦点被判定为「绘图区视口」时吞键。
  文本控件与**未识别**控件一律放行（正向白名单，认不出就不吞 —— 宁可快捷键不生效，也不能
  误吞中文输入）。曾有 PropertyManager 输入框「单字母仍直投视口」例外，会打断拼音首字母，**已删除**：
  文本框（含 PM 改名/尺寸框）永远优先打字。认不出的类名会以 `[SWKey] 焦点控件未识别…class=xxx`
  记进日志，需要时填进 `settings.sw_key_extra_classes`。SW 以管理员运行时（UIPI）自动不拦截。
  设置页主路径只有一个开关；处理方式/键集/类名在「高级选项」折叠组内。
- **「afx 类名 → autocad」兜底会误伤 MFC 程序（踩过）**：`_confirm_window_type_slow` 里
  `if "afx" in cs → autocad` 是给 AutoCAD 的 MFC 窗口兜底用的，但 SolidWorks 主窗也是
  `Afx:0000…`（MFC），于是 SW 被认成 AutoCAD、右键拖动弹出 CAD 圆盘并与 SW 鼠标笔势打架。
  修法是 `gesture_exclude_apps`（默认 `sldworks`）在**所有品牌判定之前**拦下并返回真值哨兵
  `NO_TARGET`（必须为真值：返回 "" 会继续走标题/类名兜底，又会被同一启发式抓回去）。
  该名单**优先于自定义应用注册**。新增类似"自带右键手势"的应用时加进这个名单。
- **Qt 窗口“假可见”**：Qt `isVisible()` 对隐藏/残留窗口可能返回 True，但 Win32 `IsWindowVisible(hwnd)` 为 False。判断窗口是否真正显示必须查 Win32（ctypes）：`GetWindowThreadProcessId` + `IsWindowVisible` + `IsIconic` + `GetWindowRect`。`_config_win_usable` 加了 Win32 校验才修好“配置打不开”。
- **启动方式影响窗口显示**：`Start-Process -WindowStyle Hidden` 启动的程序，所有顶层窗口初始 Win32 隐藏（无 WS_VISIBLE），表现为“窗口打不开”。排查窗口显示问题用正常方式启动。
- **托盘双击不可靠**：Windows 上 QSystemTrayIcon 设置 contextMenu 后，单击会自动弹菜单抢焦点，双击信号（DoubleClick）常收不到。方案：不设 contextMenu，单击(Trigger)/双击(DoubleClick)都打开功能，右键(Context)手动 `menu.popup(QCursor.pos())`。
- **托盘图标残留**：多次覆盖启动（单实例替换）后系统托盘可能残留多个死图标，点击无反应。用户报“点了没反应”先确认点的是不是最新实例的图标，重新覆盖启动可刷新。
- **showEvent 延迟定时器“复活”窗口**：`showEvent` 里 `QTimer.singleShot(100, ...)` 做延迟校验时，若窗口在定时器触发前被 close，回调可能把已关闭窗口重新 show。延迟回调里要判窗口仍有效（`isVisible()` 且未被 close）。
- **已提交 message 发现乱码**：`git reset --soft <坏提交的 parent>` 把改动放回暂存区，重新 `git commit -F` 正确文件（会重写 commit hash，多人协作分支慎用）。

## 改动联动清单（一处改动，多处必须同步）

| 改动内容 | 必须同步的地方 |
|---------|---------------|
| 圆盘配色/主题 | `theme.py` 的 `MENU_THEMES`（5 套 + 自定义，配置界面主题下拉自动读取） |
| 字体/标签位置/扇区绘制 | `qt_renderer.py`（`qt_radial_menu` 运行时、`qt_config_gui` 编辑预览、`qt_settings_panel` 尺寸预览共用，三处必须一致） |
| 新增 `settings` 配置项 | `config_presets._default_config` + `config_manager._migrate_config`（迁移补字段） + 需要时 `qt_config_gui`/`qt_radial_menu`/`gesture_engine`/`app.py`；半径/缩放类同时改 `menu_geometry.py` |
| 发版改版本号 | `version.txt` 4 处（filevers/prodvers/FileVersion/ProductVersion） + `src/version.py` 的 `__version__`（共 5 处；`build.bat` 注入 `vpk pack --packVersion`） |
| 新增命令预设 | `config_presets` 默认 profile + `command_executor` 的 `COMBO_TO_COMMAND` 表 |
| 新增界面文案 | `i18n.py` 翻译表 + 界面文本用 `T()` 包裹（中文模式 key 即原文） |
| 新增 Python 依赖 | `requirements.txt` + `cad_gesture.spec`（PySide6 由 PyInstaller 内置 hook 自动收集） |
| SW 按键直通（处理方式/键集/类名白名单） | `config_presets` 默认值 + `config_manager._migrate_config` + `qt_settings_panel`(TriggerPage) + `i18n.py` + `src/sw_key_assist.py` |
| 不弹圆盘的应用名单（`gesture_exclude_apps`） | `config_presets` 默认值 + `config_manager._migrate_config` + `qt_settings_panel`(TriggerPage) + `i18n.py`；匹配逻辑在 `gesture_engine.parse_exclude_apps`/`match_exclude_exe` |
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
**Inno Setup 6** 安装在 `C:\Program Files (x86)\Inno Setup 6\`（或 `D:\Inno Setup 6\`），`build.bat` 会自动探测。

**统一入口：双击 `scripts\build.bat`**，一次产出：
- 安装版：`Releases/Setup-CADGesture-vX.Y.Z.exe`（Inno Setup 中文向导，品牌图 `assets/installer_wizard.bmp`）
- 绿色版：`Releases/CADGesture-vX.Y.Z-portable.zip`（解压运行 `CADGesture-x64\`）
- Release 附件：`config/config.example.json`（模板）

build.bat 流程：清理 → PyInstaller（Python312，onedir）→ 复制配置 → `scripts\read_version.py`
提取版本号 → ISCC 编译 Inno 向导 → PowerShell `Compress-Archive` 压绿色版 zip → 完成。

手动打包（等价）：
```powershell
cd F:\cad-gesture
Get-Process CADGesture-x64 -ErrorAction SilentlyContinue | Stop-Process -Force
& "<USER>\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller cad_gesture.spec --clean --noconfirm
Copy-Item config\config.example.json dist\config\config.example.json -Force
# 版本号从 scripts\read_version.py 取
& "C:\Program Files (x86)\Inno Setup 6\ISCC.exe" /DMyAppVersion=<X.Y.Z> cad_gesture.iss
Compress-Archive -Path dist\CADGesture-x64 -DestinationPath "Releases\CADGesture-v<X.Y.Z>-portable.zip" -Force
```

### 打包前检查清单

1. 关闭所有 CADGesture-x64.exe 进程
2. Python312 环境装依赖（`requirements.txt` 含 `PySide6`）
3. Inno Setup 6 已安装（`ISCC.exe` 存在）
4. `config/config.example.json` 存在
5. `assets/icon.ico` 与 `assets/installer_wizard.bmp` 存在（向导图用 `python scripts\generate_wizard_image.py` 生成）

`cad_gesture.spec` 的 PySide6 由 PyInstaller 内置 hook 自动收集（Qt 插件/DLL），改依赖时同步检查 spec。

### 常见错误速查

| 错误现象 | 原因 | 解决 |
|---------|------|------|
| `PermissionError` / `Access denied` | exe 正在运行 | 关闭 exe 后重试 |
| 打包成功但 exe 启动闪退 | 缺隐式导入/DLL/PySide6 插件 | 先 `python main.py` 确认源码没问题 |
| `ModuleNotFoundError: PySide6` | 装到了别的 Python | 用 Python312 的 pip 装 `requirements.txt` |
| `pywintypes` DLL not found | pywin32 DLL 路径错误 | 确认 spec 的 `pywin32_system32/` 路径 |
| ISCC 找不到 | 未装 Inno Setup 6 | 安装 Inno Setup 6 后重试 |

## 发版流程（打 tag 发布 GitHub Release）

1. 更新 `version.txt` 版本号（4 处：`filevers`/`prodvers`/`FileVersion`/`ProductVersion`）+ `src/version.py` 的 `__version__`（共 5 处）
2. 打包：`scripts\build.bat` 产出 `Releases\Setup-CADGesture-vX.Y.Z.exe` + `Releases\CADGesture-vX.Y.Z-portable.zip`
3. 提交 version.txt + 本次改动，打 annotated tag：`git tag -a vX.Y.Z -m "vX.Y.Z"`
4. `git push origin master --tags`
5. **创建 Release 前，必须先向用户展示待发布内容（版本号、产物清单、体积、Release notes、附件清单）并等待用户确认**，确认后再执行下一步
6. `gh release create vX.Y.Z --title "vX.Y.Z" --notes "..." Releases\* config\config.example.json`
   - 附件：安装版 + 绿色版 + `config/config.example.json`（模板）
   - **绝不打包用户私有 `config/config.json`**
7. 发布后实测更新链路：托盘"检查更新" → 检测到新版 → 下载 → 自动更新 → 新版自动启动

## 关键技术细节

- 钩子回调必须返回 `c_ssize_t`（非 `c_long`），否则 64 位崩溃
- `CallNextHookEx` 必须设 `argtypes`，否则参数溢出
- `GetModuleHandleW(None)` 在 ctypes 中传 `None`（非 0）
- 圆盘菜单用 Qt `QRadialMenu`：`FramelessWindowHint` + `WA_TranslucentBackground` 实现透明悬浮窗，`WA_ShowWithoutActivating` 不抢焦点
- COM 发送前自动切换英文输入法：`PostMessage(WM_INPUTLANGCHANGEREQUEST)`
- 钩子线程退出：`stop()` 发 `PostThreadMessageW(WM_QUIT)`
- 事件队列格式：`("show", (x, y, window_type))` 元组嵌套
- **圆盘外观主题**：改圆盘配色去 `theme.py` 的 `MENU_THEMES`（5 套：graphite/azure/emerald/crimson/midnight + 自定义主色），由 `settings.menu_theme` 控制，`get_menu_theme(name)` 获取。改字体/位置/渲染去 `qt_renderer.py`（`draw_ring` 被运行时圆盘和两处预览共用，改动必须三处一致）。
- **圆盘几何**：半径/缩放统一从 `menu_geometry.py` 取（`DEFAULT_RADII` + `menu_scale`），不要在各模块里各自写死半径默认值。
- **配置自动迁移**：`config_manager._migrate_config` 自动补旧配置字段；空的 `extension_sectors` 会从默认配置按 target+name 自动补全。
- **自动更新**：统一走 GitHub Releases HTML 检查（`src/updater.py`）：下载
  `Setup-CADGesture-vX.exe` 到 %TEMP% → 静默 `/VERYSILENT` 启动 Inno 安装器 →
  写 %TEMP% 更新标记 → 退出主进程；新版启动时消费标记弹"已更新"。
  检查/下载在后台线程，进度与结果经 event_queue 回主线程。
- **onedir 打包（启动免解压）**：PyInstaller 用 `--onedir`，`sys.executable`
  指向真实 exe 路径；版本号统一用 `src/version.py` 内置常量。绿色版 zip
  整包压缩 `dist\CADGesture-x64\`，解压后运行其中的 exe。

## 命令执行优先级

| 场景 | 方式 | 说明 |
|------|------|------|
| 键盘命令（`l`, `co`） | COM `SendCommand("_.LINE\n")` | CAD内部执行 |
| 组合键（`ctrl+z`） | COM 映射（`_.U`） | 见 `COMBO_TO_COMMAND` 表 |
| 剪贴板操作（`ctrl+c/v/x`） | pyautogui 回退 | 少数场景 |
| COM 全部失败 | pyautogui + ESC 取消菜单 | 兜底 |

## 配置结构

`%APPDATA%\CADGesture\config.json` — `settings` + `profiles`（与 exe 位置无关，用户可编辑；旧版 `config/config.json` 仅用于首次迁移）。每个 profile 有 `sectors`（内层）、`outer_sectors`（外层）、`extension_sectors`（扩展圈）。
字段：`description` = COM 命令名，`key` = pyautogui 回退键（自定义应用只走按键模拟），`target` = `autocad`|`zwcad` 或自定义应用 id（`app_xxx`）。
`settings` 关键项：`app_order`（卡片显示顺序，内置 autocad/zwcad 在前）、`custom_targets`（自定义应用列表：`id`/`name`/`match_exe`/`match_title`）、`gesture_exclude_apps`（不弹圆盘的应用，exe 关键字逗号分隔，默认 `sldworks` —— 自带右键笔势的程序；优先于自定义应用注册）、`autocad_profile`/`zwcad_profile`/`{target}_profile`（各应用当前方案绑定）、`menu_theme`（圆盘外观）、`menu_scale`（整体缩放 50~150%）、`menu_opacity`（不透明度）、`ui_mode`（dark/light/system）、`language`（zh/en）、`hold_threshold_ms`（长按延迟，默认 80）、`trigger_distance`（触发距离，默认 10，可调 5~40）、`open_config_on_start`、`auto_switch_profile`、`check_update_on_start`（启动时检查更新，默认 false）、`update_source_url`（更新源，默认 GitHub Release 页面）、`last_update_check`（上次检查时间，24h 频率控制）、`ime_assist_sw`（SW 快捷键直通总开关，默认 true）、`ime_assist_mode`（`key`=按键直通 / `layout`=切键盘布局，默认 key）、`sw_key_list`（直通键集，默认 `A-Z,0-9,SPACE`）、`sw_key_extra_classes`（额外视口类名白名单，默认空）。

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
   Start-Process "C:\Users\cy\AppData\Local\Programs\Python\Python312\python.exe" -ArgumentList "main.py" -WorkingDirectory "F:\cad-gesture"
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
