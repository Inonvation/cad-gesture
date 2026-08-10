# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## 项目概述

CAD 鼠标手势工具：长按鼠标右键拖动呼出 8 扇区三层径向圆盘菜单（内层 `sectors` / 外层 `outer_sectors` / 扩展圈 `extension_sectors`），释放触发 CAD 命令。服务 AutoCAD 2025+ 和中望CAD，Python 3.11+ / Win32 API / PySide6(Qt6)。

**核心设计（方案B）**：低级鼠标钩子 `WH_MOUSE_LL` 只监听不拦截 → CAD 收到右键释放可能弹上下文菜单 → 工具随后发 ESC 取消 → 命令优先走 COM `SendCommand`，不影响十字光标。

**详细指南见 `AGENTS.md`**（打包流程、发版流程、常见错误速查都在那里）。本文件只讲上手必需的架构和坑。⚠️ AGENTS.md 有少量过时信息，以本文件"现状修正"为准。

## 常用命令

```bash
python main.py                          # 调试运行（有控制台输出）
python -m py_compile src\xxx.py         # 语法检查（改完先跑）
python -m pytest tests/ -q              # 全部单元测试
python -m pytest tests\test_config.py::test_name -q   # 单个测试
python scripts\verify.py                # 一键：语法检查 → pytest → 启动程序覆盖旧实例
```

- 开发用 Python：`%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe`（`python` 可能命中多个环境，hermes venv 的 python 是 uv launcher，启动 main.py 后看到"一对 python 进程"属正常）。
- **打包必须用独立的 Python312**（`<USER>\AppData\Local\Programs\Python\Python312\python.exe`），其他环境缺 PyInstaller。统一入口 `scripts\build.bat`，产出绿色版 + 安装版两个 exe。
- **无 lint / typecheck / CI**。验证方式就是 `py_compile` + `pytest` + 手动运行。

## 架构（big picture）

### 事件流：钩子线程 → 队列 → Qt 主线程

`GestureEngine`（`gesture_engine.py`）在独立线程跑低级鼠标钩子，回调不直接碰 UI，把事件放进 `queue.Queue`。Qt 主线程的 `QTimer` 驱动 `app.py::_process_queue()` 消费队列（菜单可见时 16ms、隐藏时 100ms 间隔）。每个事件包裹 `try-except`，单次错误不崩溃队列循环。

- 队列元组格式：`("show", (x, y, window_type))`、`("gesture", (sector, ring_type, window_type))`、`("hide", None)`、`("extension_hint", is_in_zone)`。
- 更新流程同模式：后台线程检查/下载 → 结果经队列（`update_check_result` / `update_progress` / `update_download_done`）→ 主线程弹窗。

### 圈层判定（触发与 hover 共用）

`gesture_engine`（松手结算）与 `qt_radial_menu`（悬停高亮）**都从 config 的同一组 settings 键读半径**，改阈值只需改设置项，不用动两处代码：

- `trigger_distance`(15) 拖出此距离才呼出菜单；`hold_threshold_ms`(100) 长按时长
- 距离 ≤ `ring_radius`(70) = 内层；≤ `outer_ring_radius`(135) = 外层；`ext_ring_radius`(185) 外 = 扩展圈
- `dead_zone_radius`(24)：菜单已弹出时松手落在中心死区内 → 取消不触发

⚠️ **现状修正**：AGENTS.md 写的 100/180 是旧值；`theme.py` 现在是 8 套圆盘主题（azure/emerald/crimson/midnight/aurora/graphite/amber/mono）+ 自定义色，不是 6 套。

### 命令执行优先级

`command_executor.py`：键盘命令（`l`, `co`）→ COM `SendCommand("_.LINE\n")`；组合键（`ctrl+z`）→ COM 映射（见 `COMBO_TO_COMMAND` 表）；剪贴板操作 → pyautogui 回退；COM 全失败 → pyautogui + ESC 取消菜单兜底。COM 发送前自动切英文输入法（`PostMessage(WM_INPUTLANGCHANGEREQUEST)`）。

### 配置系统

运行时配置在 `%APPDATA%\CADGesture\config.json`（`config_manager.py`，与 exe 位置无关）；旧版 `config/config.json` 仅首次启动一次性迁移。结构 = `settings` + `profiles`，每个 profile 含 `sectors` / `outer_sectors` / `extension_sectors`，命令字段 `label`（显示名）/ `key`（回退快捷键）/ `description`（COM 命令名）/ `target`（autocad|zwcad）。

- 新设置项要同时改 `config_presets._default_config` 和 `config_manager._migrate_config`（自动迁移补字段），否则老用户配置缺字段。
- 支持自定义配置目录：设置页指定后写 `%APPDATA%\CADGesture\config_path.txt` 标记文件，`get_config_path()` 优先返回自定义目录；改配置路径逻辑时注意这个标记文件。
- 空 `extension_sectors` 会从默认配置按 target+name 自动补全。

### i18n（较新，改动必须遵守）

`i18n.py`：界面语言存 `settings.language`（"zh"/"en"）。**所有界面文本必须用 `T("中文原文")` 包裹**，中文模式下 key 即原文，英文查翻译表；带占位符用 `T("已切换到: {name}").format(name=...)`。新增文案要同时在翻译表补英文，否则英文模式显示中文。

## 环境关键坑（Windows，务必先读）

1. **绝不用 PowerShell 改含中文的 .py/.json**：`Get-Content`/`Set-Content` 按 GBK 读 UTF-8 会永久损坏中文（乱码不可逆）。改中文文件用 edit/write 工具；批量替换用 python 脚本（`open(path, encoding='utf-8')`）。
2. **`scripts\build.bat` / `verify.bat` 必须保持 GBK 编码 + CRLF 行尾**，cmd 按系统代码页解析。**绝不用 edit/write 直接改**（会写成 UTF-8）；需修改时先在 UTF-8 副本上编辑，再用 python 脚本转回 GBK+CRLF。
3. **Qt 单应用单线程**：主程序是 `QApplication`，Qt 控件只能在主线程操作。托盘/菜单回调已跑在主线程，无需跨线程投递。
4. **Qt 坐标是逻辑像素，钩子给物理像素**：`QRadialMenu.show(x, y)` 内部按屏幕 DPI 换算（`_to_logical`）。别直接拿钩子的 `pt.x/pt.y` 去 `move()`，DPI 缩放≠100% 时圆盘会偏移。
5. **低级钩子回调极快**：钩子线程内不做磁盘 I/O（日志先进内存队列，主线程 `flush_logs()` 落盘）；回调必须返回 `c_ssize_t` 且设 `CallNextHookEx` 的 argtypes，否则 64 位崩溃。
6. **单实例机制**：`main.py` 开头 `ensure_single_instance()` 用命名互斥体，新实例置位命名事件请求旧实例退出（覆盖更新）。`app.py` 主循环每 32 帧轮询 `is_exit_requested()`。启动逻辑别改坏这两处。
7. **PyInstaller onefile 不能读 exe 同级文件**：运行时版本号必须用 `src/version.py` 内置常量，不要读文件（`sys.executable` 指向临时解压目录）。

## 改动联动清单（一处改动，多处必须同步）

| 改动内容 | 必须同步的地方 |
|---------|---------------|
| 圆盘配色/新增主题 | `theme.py` 的 `MENU_THEMES`（配置界面主题下拉自动读取） |
| 字体/标签位置/扇区绘制 | `qt_renderer.py`（运行时菜单与配置预览共用，两处必须一致） |
| 新增 `settings` 配置项 | `config_presets._default_config` + `config_manager._migrate_config` + 相关使用处 |
| 新增界面文案 | `i18n.py` 翻译表 + 用 `T()` 包裹（见上） |
| 发版改版本号 | `version.txt` 4 处（filevers/prodvers/FileVersion/ProductVersion）+ `src/version.py` 的 `__version__`，共 5 处 |
| 新增命令预设 | `config_presets` 默认 profile + `command_executor` 的 `COMBO_TO_COMMAND` 表 |
| 新增 Python 依赖 | `requirements.txt` + `cad_gesture.spec`（PySide6 由 PyInstaller 内置 hook 自动收集） |
| 改圈层/触发阈值 | 只改 config 的对应 settings 键（gesture_engine 与 qt_radial_menu 都从 config 读） |

## 验证与提交

- **改完代码先 `py_compile` → `pytest` → 启动 `python main.py` 手动验证，不要打包**（打包很慢，仅发布时用）。每次改完都启动程序让用户看效果，不要攒到最后一起验证。
- 日志：`%TEMP%\cad-gesture.log` + 控制台（`[Gesture]` 前缀），调试钩子细节设环境变量 `CAD_GESTURE_DEBUG=1`。
- 提交格式 `前缀: 中文描述`（feat/fix/perf/refactor/chore/docs/build），一个 commit 只做一件事，**不要擅自提交/推送，等用户确认**。
