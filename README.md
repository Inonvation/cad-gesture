# CAD 鼠标手势工具 (CAD Gesture)

一款为 **AutoCAD** 和 **中望CAD** 设计的鼠标手势 + 径向圆盘菜单工具。
在 CAD 中**长按鼠标右键拖动**，即可从圆盘菜单快速选择并执行命令，无需记忆快捷键。

## 功能特性

- **三层径向圆盘菜单**：8 扇区，内层 / 外层 / 扩展圈三层命令
- **流畅手势交互**：长按右键呼出，释放即触发；悬停高亮 + 淡入动画
- **多套配置方案**：不同 CAD / 工种可分别配置，按前台窗口自动切换
- **8 套圆盘外观主题 + 自定义主题**：天蓝 / 翡翠 / 绯红 / 午夜 / 极光 / 石墨 / 琥珀 / 单色，可自选主色自动生成整套配色
- **现代深色配置界面**（PySide6/Qt）：导航式布局、圆盘预览 + 点击扇区就地编辑浮层、命令库搜索 / 拖放 / 放置模式、撤销/重做（Ctrl+Z / Ctrl+Y）
- **不影响十字光标**：命令优先通过 COM `SendCommand` 发送，钩子只监听不拦截
- **单实例运行**：重复启动自动替换旧实例，不产生多余托盘图标

## 支持环境

- Windows 10 / 11（64 位）
- AutoCAD 2025+ 或 中望CAD
- Python 3.11+（源码运行）

## 快速开始

### 方式一：使用打包版

1. 下载最新 [Release](https://github.com/Inonvation/cad-gesture/releases) 的 `CADGesture-x64.exe`
2. 双击运行，右下角出现托盘图标
3. 打开 CAD，**长按鼠标右键拖动**即可使用

### 方式二：源码运行

```powershell
# 安装依赖（Windows）
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple

# 运行
python main.py
```

## 使用说明

| 操作 | 说明 |
|------|------|
| 呼出菜单 | 在 CAD 窗口内长按鼠标右键并拖动（约 150ms） |
| 选择命令 | 按住右键拖向目标扇区，高亮后释放触发 |
| 内层 | 高频绘图命令（直线、圆、复制…） |
| 外层 | 编辑命令（圆弧、旋转、缩放…） |
| 扩展圈 | 延伸命令，拖出第二圈边界即可触发 |
| 托盘 | 右键托盘图标 → 配置 / 切换方案 / 退出 |

## 配置

托盘右键 → **配置**，打开可视化编辑器（导航式布局）：

- **左侧**：导航（圆盘编辑 / 设置）+ 配置方案管理（新增 / ⋯ 菜单含复制、重命名、删除、导入导出）
- **圆盘编辑**：大圆盘预览，**点击扇区弹出就地编辑浮层**（显示名 / 快捷键 / CAD 命令，即时保存）；命令库可折叠，支持搜索 / 点击应用到选中扇区 / 拖放到扇区 / 右键放置模式
- **快捷键**：`Delete` 删除选中扇区命令，`Ctrl+Z` / `Ctrl+Y` 撤销 / 重做，`Ctrl+F` 搜索命令，`Esc` 取消放置
- **设置**：主题色板（含自定义主色）、触发灵敏度、圆盘尺寸实时预览、开机自启

配置保存于 `config/config.json`（首次运行自动生成默认配置，模板见 `config/config.example.json`）。
每个方案包含三层命令：
`sectors`（内层）、`outer_sectors`（外层）、`extension_sectors`（扩展圈）。
每个命令由 `label`（显示名）、`key`（回退快捷键）、`description`（CAD 命令名）构成。

## 打包发布

```powershell
# 用 Python312 打包（或直接双击 scripts\build.bat）
python -m PyInstaller cad_gesture.spec --clean --noconfirm

# 输出 dist/CADGesture-x64.exe（单文件），配置文件复制到 dist/config/
```

## 技术栈

- **Python 3.11+** / Win32 API（低级鼠标钩子 `WH_MOUSE_LL`）
- **PySide6 / Qt 6**（GUI：系统托盘、透明圆盘菜单、配置界面）
- **COM / pyautogui**（命令执行）
- **PyInstaller**（打包）

## 目录结构

```
main.py                 # 入口（含单实例检查）
start.bat / start.vbs   # 一键启动（静默/带窗口）
src/                    # 程序代码
├── app.py               # 主程序（Qt）：事件队列、托盘、配置入口
├── gesture_engine.py    # 鼠标钩子与手势/圈层判定
├── qt_radial_menu.py    # Qt 透明悬浮圆盘菜单（运行时）
├── qt_renderer.py       # 共享圆盘绘制（菜单与配置预览共用）
├── qt_config_gui.py     # Qt 配置界面（导航式布局 + 扇区浮层编辑）
├── qt_preview.py        # 圆盘编辑页组件（预览/命令树/折叠按钮）
├── qt_settings_panel.py # 设置面板（主题色板网格 + 实时预览）
├── qt_sector_editor.py  # 扇区编辑浮层（就地编辑 / 保存 / 清空）
├── theme.py             # 设计 token、QSS 生成、8 套主题 + 自定义主题
├── command_executor.py  # COM 命令执行 + pyautogui 回退
├── config_manager.py    # 配置读写与自动迁移
├── config_presets.py    # 预设命令库与默认配置
└── single_instance.py   # 单实例与覆盖更新
scripts/                # 开发脚本
├── build.bat            # 一键打包（PyInstaller）
├── verify.py / verify.bat  # 一键验证：语法 + 测试 + 重启程序
└── generate_icon.py     # 生成 assets/icon.ico
config/                 # 配置（config.json 运行时生成，example 为模板）
assets/                 # 图标等资源
tests/                  # 自动化测试
```

## 开发验证

```powershell
python -m py_compile src\xxx.py   # 语法检查
python -m pytest tests/ -q        # 单元测试
python scripts\verify.py          # 一键：语法 + 测试 + 重启程序
```
