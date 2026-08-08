# CAD 鼠标手势工具 — Agent 指南

## 项目概述

8 扇区径向圆盘菜单（内层/外层/扩展圈三层）：长按右键拖动 → 弹出菜单 → 释放触发 CAD 命令。
支持 AutoCAD 2025+ 和中望CAD，Python 3.11+ / Win32 API / CustomTkinter / PyInstaller 打包。

**核心设计（方案B）**：钩子只监听不拦截 → CAD 收到右键释放可能弹上下文菜单 → 工具随后发 ESC 取消 → 命令优先走 COM `SendCommand`，不影响十字光标。

## 用户特征

技术小白，第一次开发桌面工具。表述可能模糊、含错或使用非专业术语。将模糊需求翻译为可执行方案，对错误指令主动质疑和修正。

## 架构

```
main.py                 # 入口（含单实例检查）
config/config.json      # 多Profile配置（三层：sectors + outer_sectors + extension_sectors）
src/
├── app.py              # 主类：事件队列(60fps)、托盘、Profile切换、配置界面入口
├── gesture_engine.py   # [核心] WH_MOUSE_LL 钩子 → 方向/圈层判定
├── radial_menu.py      # [核心] 透明悬浮圆盘菜单（三层绘制）
├── renderer.py         # 共享圆盘绘制（radial_menu 和 config_gui 预览共用）
├── theme.py            # 界面配色 + 6 套圆盘外观主题
├── command_executor.py # COM SendCommand + pyautogui 回退
├── config_manager.py   # JSON 配置读写 + Profile管理 + 自动迁移
├── config_gui.py       # CustomTkinter 现代深色配置编辑器
└── single_instance.py  # 命名互斥体单实例 + 覆盖更新
```

事件流：钩子线程 → `queue.Queue` → 主线程 `_process_queue()` (16ms/帧)。
每个事件包裹 `try-except`，防止单次错误崩溃整个队列循环。

**圈层判定**（gesture_engine 触发 与 radial_menu hover 共用同一规则）：
距离 ≤ `ring_radius`(100) = 内层；≤ `outer_ring_radius`(180) = 外层；> 180 = 扩展圈（命令在 `extension_sectors`）。

## 环境关键坑（务必先读）

- **Python 双解释器**：`python` 命令可能命中多个环境。hermes venv 的 `python.exe` 是 uv launcher，运行 `main.py` 时会 spawn 真解释器（uv cpython）——启动后看到"一对 python 进程"是**正常现象**。启动/验证统一用 hermes venv 的 python：
  `%LOCALAPPDATA%\hermes\hermes-agent\venv\Scripts\python.exe`
- **绝不用 PowerShell 改中文文件**：PowerShell 的 `Get-Content`/`Set-Content` 按 GBK 读 UTF-8 会永久损坏中文（乱码不可逆）。改含中文的 .py/.json 必须用 edit/write 工具；批量替换用 python 脚本（`open(path, encoding='utf-8')`）。
- **配置界面不能开独立线程**：`config_gui.py` 必须通过 `open_config_gui(on_save=..., master=self.root)` 嵌入主线程（app 的 root 是 `ctk.CTk()`）。若在独立线程创建 `CTk()` 会与主线程双 Tk 冲突，CTkEntry 的 StringVar trace 跨线程抛 `RuntimeError: main thread is not in main loop` → 窗口卡死"未响应"。改配置界面最易踩。
- **单实例机制**：`main.py` 开头 `ensure_single_instance()` 用命名互斥体判断，新实例会置位命名事件请求旧实例优雅退出（覆盖更新，避免多托盘图标）。app.py 主循环每 0.5s 轮询 `is_exit_requested()`。启动逻辑别改坏这两处。

## 改动联动清单（一处改动，多处必须同步）

| 改动内容 | 必须同步的地方 |
|---------|---------------|
| 圆盘配色/主题 | `theme.py` 的 `MENU_THEMES`（配置界面主题下拉自动读取，无需改界面） |
| 字体/标签位置/扇区绘制 | `renderer.py` 的 `draw_ring`（被 `radial_menu` 和 `config_gui` 预览共用，两处必须一致） |
| 新增 `settings` 配置项 | `config_presets._default_config` + `config_manager._migrate_config`（迁移补字段） + 需要时 `config_gui`/`radial_menu`/`gesture_engine` |
| 新增命令预设 | `config_presets` 默认 profile + `command_executor` 的 `COMBO_TO_COMMAND` 表 |
| 新增 Python 依赖 | `requirements.txt` + `cad_gesture.spec`（hiddenimports / collect_data_files） |
| 改圈层/触发阈值 | `gesture_engine`（钩子判定）与 `radial_menu`（hover 显示）必须用同一半径常量 |

## 一键验证

改完代码用 `python verify.py`（或双击 `verify.bat`）：自动跑 `py_compile` → `pytest` → 启动新实例（单实例机制自动覆盖旧实例，不杀进程）。

## 命令

```bash
python main.py                        # 调试运行（有控制台输出）
python -m py_compile src\xxx.py       # 快速语法校验（改完先跑）
python -m pytest tests/ -q            # 运行测试（pytest：test_config.py + test_renderer.py）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
```

**无 lint / typecheck / CI 流程。** 验证方式是 `py_compile` + `pytest` + `python main.py` 手动测试。

## 测试流程

**改完代码先 `py_compile` → `pytest` → 启动 `python main.py` 手动验证，不要打包。** 打包很慢，只有最终发布时才需要。

## 打包流程（仅发布时使用）

**打包必须用 Python312**（`<USER>\AppData\Local\Programs\Python\Python312\python.exe`），其他 Python 环境可能缺 PyInstaller。

**onefile 单文件打包**：输出 `dist/CADGesture.exe`。

```powershell
cd F:\cad-gesture
Get-Process CADGesture -ErrorAction SilentlyContinue | Stop-Process -Force
& "<USER>\AppData\Local\Programs\Python\Python312\python.exe" -m PyInstaller cad_gesture.spec --clean --noconfirm
Copy-Item config\config.json dist\config\config.json -Force
dist\CADGesture.exe
```

或直接运行 `build.bat`（双击即可）。

### 打包前检查清单

1. 关闭所有 CADGesture.exe 进程
2. Python312 环境装依赖（`requirements.txt` 含 `customtkinter`）
3. `config/config.json` 存在
4. `assets/icon.ico` 存在（`python generate_icon.py` 生成）

`cad_gesture.spec` 已含 `customtkinter`/`darkdetect` 的 hiddenimports 与 `collect_data_files('customtkinter')`，改依赖时同步检查 spec。

### 常见错误速查

| 错误现象 | 原因 | 解决 |
|---------|------|------|
| `PermissionError` / `Access denied` | exe 正在运行 | 关闭 exe 后重试 |
| 打包成功但 exe 启动闪退 | 缺隐式导入/DLL/customtkinter | 先 `python main.py` 确认源码没问题 |
| `ModuleNotFoundError: customtkinter` | 装到了别的 Python | 用 Python312 的 pip 装 `requirements.txt` |
| `pywintypes` DLL not found | pywin32 DLL 路径错误 | 确认 spec 的 `pywin32_system32/` 路径 |

## 关键技术细节

- 钩子回调必须返回 `c_ssize_t`（非 `c_long`），否则 64 位崩溃
- `CallNextHookEx` 必须设 `argtypes`，否则参数溢出
- `GetModuleHandleW(None)` 在 ctypes 中传 `None`（非 0）
- 菜单窗口用 `tk.Toplevel(parent)`（非独立 `Tk()`），`-transparentcolor` 实现透明
- COM 发送前自动切换英文输入法：`PostMessage(WM_INPUTLANGCHANGEREQUEST)`
- 钩子线程退出：`stop()` 发 `PostThreadMessageW(WM_QUIT)`
- 事件队列格式：`("show", (x, y, window_type))` 元组嵌套
- **圆盘外观主题**：改圆盘配色去 `theme.py` 的 `MENU_THEMES`（6 套：azure/emerald/crimson/midnight/aurora/graphite），由 `settings.menu_theme` 控制，`get_menu_theme(name)` 获取。改字体/位置/渲染去 `renderer.py`（`draw_ring` 被菜单和配置预览共用，改动必须两处一致）。
- **配置自动迁移**：`config_manager._migrate_config` 自动补旧配置字段；空的 `extension_sectors` 会从默认配置按 target+name 自动补全。

## 命令执行优先级

| 场景 | 方式 | 说明 |
|------|------|------|
| 键盘命令（`l`, `co`） | COM `SendCommand("_.LINE\n")` | CAD内部执行 |
| 组合键（`ctrl+z`） | COM 映射（`_.U`） | 见 `COMBO_TO_COMMAND` 表 |
| 剪贴板操作（`ctrl+c/v/x`） | pyautogui 回退 | 少数场景 |
| COM 全部失败 | pyautogui + ESC 取消菜单 | 兜底 |

## 配置结构

`config/config.json` — `settings` + `profiles`。每个 profile 有 `sectors`（内层）、`outer_sectors`（外层）、`extension_sectors`（扩展圈）。
字段：`description` = COM 命令名，`key` = pyautogui 回退键，`target` = `autocad`|`zwcad`。
`settings` 关键项：`menu_theme`（圆盘外观）、`hold_threshold_ms`（长按延迟，默认 80）、`trigger_distance`（触发距离，默认 15）、`open_config_on_start`、`auto_switch_profile`。

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
- 配置窗口"未响应"：多半是配置界面被放到独立线程（见「环境关键坑」）
- 钩子安装失败：检查其他手势软件冲突（WGestures、Quicker）或杀毒拦截
- 命令错乱：确认输入法是英文（程序自动切换，首次可能需手动切一次）
