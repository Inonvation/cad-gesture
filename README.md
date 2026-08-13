# CAD 鼠标手势工具 (CAD Gesture)

一款为 **AutoCAD** 和 **中望CAD** 设计的鼠标手势 + 径向圆盘菜单工具。
在 CAD 中**长按鼠标右键拖动**，即可从圆盘菜单快速选择并执行命令，无需记忆快捷键。

[![Release](https://img.shields.io/github/v/release/Inonvation/cad-gesture)](https://github.com/Inonvation/cad-gesture/releases)
[![License: MIT](https://img.shields.io/badge/license-MIT-blue.svg)](LICENSE)
[![Issues](https://img.shields.io/github/issues/Inonvation/cad-gesture)](https://github.com/Inonvation/cad-gesture/issues)

[更新日志](CHANGELOG.md) · [许可证](LICENSE)

![配置界面预览](docs/_preview_cards.png)

## 功能特性

- **三层径向圆盘菜单**：8 扇区，内层 / 外层 / 扩展圈三层命令
- **流畅手势交互**：长按右键呼出，释放即触发；悬停高亮 + 淡入动画
- **多套配置方案**：不同 CAD / 工种可分别配置，按前台窗口自动切换
- **5 套圆盘外观主题 + 自定义主题**：石墨 / 天蓝 / 翡翠 / 绯红 / 午夜，可自选主色自动生成整套配色
- **现代深/浅色配置界面**（PySide6/Qt，可跟随系统主题）：导航式布局、圆盘预览 + 点击扇区就地编辑浮层、命令库搜索 / 拖放 / 放置模式、撤销/重做（Ctrl+Z / Ctrl+Y）
- **不影响十字光标**：命令优先通过 COM `SendCommand` 发送，钩子只监听不拦截
- **单实例运行**：重复启动自动替换旧实例，不产生多余托盘图标
- **一键更新**：托盘"检查更新"或启动时自动检查，下载新版自动静默覆盖安装

## 支持环境

- Windows 10 / 11（64 位）
- AutoCAD 2025+ 或 中望CAD
- Python 3.11+（源码运行）

## 快速开始

### 方式一：使用打包版

两种形态任选其一（配置保存在 `%APPDATA%`，两种形态可无缝互换）：

| 形态 | 文件 | 说明 |
|------|------|------|
| 安装版（推荐） | `Setup-CADGesture-vX.Y.Z.exe` | 标准安装向导，开始菜单 / 卸载入口，支持程序内一键更新 |
| 绿色版 | `CADGesture-vX.Y.Z.zip` | 免安装，解压后运行 `CADGesture-x64.exe` |

1. 下载最新 [Release](https://github.com/Inonvation/cad-gesture/releases) 中的安装包或绿色版
2. 安装版直接双击运行；绿色版先解压 zip，再运行其中的 `CADGesture-x64.exe`，右下角出现托盘图标即开始使用
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
| 呼出菜单 | 在 CAD 窗口内按住鼠标右键拖动：滑动超过触发距离（默认 10px）立即弹出，或长按约 80ms 且有轻微位移时弹出 |
| 选择命令 | 按住右键拖向目标扇区，高亮后释放触发 |
| 内层 | 高频绘图命令（直线、圆、复制…） |
| 外层 | 编辑命令（圆弧、旋转、缩放…） |
| 扩展圈 | 延伸命令，拖出第二圈边界即可触发 |
| 托盘 | 右键托盘图标 → 配置 / 检查更新 / 切换方案 / 退出 |

## 自动更新

- **检查更新**：托盘右键 → 检查更新，立即查询最新版本；有新版本弹出更新说明，点击"立即更新"自动下载并静默安装
- **启动时自动检查**：可在设置界面开启（默认关闭），启动后后台静默检查，距上次检查超过 24 小时才会再次检查；发现新版本会弹出提示
- 更新不丢失配置：配置保存在 `%APPDATA%\CADGesture`，安装/覆盖/卸载均不影响

> **遇到 SmartScreen 提示？** 安装包/绿色版未做代码签名，Windows 可能显示"未知发布者"。点击"更多信息"→"仍要运行"即可，程序本身是安全的开源工具。

## FAQ

| 问题 | 解答 |
|------|------|
| 如何更新？ | 托盘右键 → 检查更新（或启动时自动检查），按提示点击"立即更新"即可 |
| 更新会丢配置吗？ | 不会。配置在 `%APPDATA%\CADGesture`，与安装目录无关 |
| 绿色版可以更新吗？ | 可以，更新时会自动安装到用户目录并建立卸载入口 |
| 国内下载慢 / 更新失败？ | 检查更新走 GitHub Release 页面（不受 API 流量限制），下载失败请稍后重试；也可手动到 Release 页下载最新版 |
| 占用内存多少？ | 常驻托盘程序，正常约 100~200MB（Python + Qt）。若明显偏高，先确认没有多个实例在运行 |
| 手势没反应 / 命令错乱？ | 见 [常见问题排查](docs/troubleshooting.md)：杀软白名单、其他手势软件冲突、输入法、触发键占用等 |

## 配置

托盘右键 → **配置**，打开可视化编辑器（导航式布局）：

- **左侧**：配置方案以**卡片**按应用分组（AutoCAD / 中望CAD / 自定义应用）。卡片默认折叠，头部显示应用名和当前生效方案；点卡片头展开方案列表，按住卡片头拖动可调整顺序；顶部「添加应用」可为其他软件配置手势方案
- **圆盘编辑**：大圆盘预览，**点击扇区弹出就地编辑浮层**（显示名 / 快捷键 / 命令，即时保存）；命令库可折叠，支持搜索 / 点击应用到选中扇区 / 拖放到扇区 / 右键放置模式；扇区可选图标
- **快捷键**：`Delete` 删除选中扇区命令，`Ctrl+Z` / `Ctrl+Y` 撤销 / 重做，`Ctrl+F` 搜索命令，`Esc` 取消放置
- **设置**：界面模式（深色 / 浅色 / 跟随系统）、主题色板（含自定义主色）、触发灵敏度、圆盘尺寸实时预览、开机自启、自动更新

配置保存在 `%APPDATA%\CADGesture\config.json`（Windows 标准用户目录，与 exe 位置无关，可随时手动编辑；首次运行自动从旧版本位置迁移，模板见 `config/config.example.json`）。

### 配置结构

- `profiles`：方案字典。每个方案包含三层命令：`sectors`（内层）、`outer_sectors`（外层）、`extension_sectors`（扩展圈）；每条命令由 `label`（显示名）、`key`（快捷键 / 回退键）、`description`（CAD 命令名）和 `icon`（可选图标）构成
- `target`：方案适用的应用，内置 `autocad` / `zwcad`，自定义应用为 `app_xxx`（如 `app_sldworks`）
- `settings` 关键项：
  - `app_order`：卡片显示顺序，如 `["autocad", "zwcad", "app_sldworks"]`
  - `custom_targets`：自定义应用列表，每项含 `id`（唯一标识）、`name`（显示名）、`match_exe`（可执行文件名，如 `sldworks.exe`）、`match_title`（窗口标题，可选）
  - `autocad_profile` / `zwcad_profile` / `{target}_profile`：各应用当前生效的方案
  - `menu_theme`、`menu_scale`、`menu_opacity`、`ui_mode`、`language`、`hold_threshold_ms`、`trigger_distance` 等外观与触发参数

自定义应用的手势命令使用按键模拟，COM 命令仅用于 AutoCAD / 中望CAD。

## 打包发布

```powershell
# 用 Python312 打包（或直接双击 scripts\build.bat，自动执行 PyInstaller + Inno Setup）
python -m PyInstaller cad_gesture.spec --clean --noconfirm

# 发版前先同步版本号（5 处：version.txt 4 处 + src/version.py）：
python scriptsset_version.py 0.0.9

# 产物（发布物为三件，私有 config/config.json 绝不打包）：
#   dist/CADGesture-vX.Y.Z.zip            绿色版（onedir 目录压缩）
#   dist/Setup-CADGesture-vX.Y.Z.exe       安装版（Inno Setup，需先安装 Inno Setup 6.3+）
#   config/config.example.json             配置模板（Release 附件）
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
cad_gesture.iss         # Inno Setup 安装包脚本（构建 Setup-CADGesture-vX.Y.Z.exe）
src/                    # 程序代码（部分列出）
├── app.py               # 主程序（Qt）：事件队列、托盘、配置入口、更新流程
├── gesture_engine.py    # 鼠标钩子与手势/圈层判定
├── qt_radial_menu.py    # Qt 透明悬浮圆盘菜单（运行时）
├── qt_renderer.py       # 共享圆盘绘制（菜单与配置预览共用）
├── qt_config_gui.py     # Qt 配置界面（侧边栏分类导航 + 扇区浮层编辑）
├── qt_preview.py        # 圆盘编辑页组件（预览/命令树/折叠按钮）
├── qt_settings_panel.py # 设置分类页（外观/触发/尺寸/常规/维护，每类一页）
├── qt_sector_editor.py  # 扇区编辑浮层（就地编辑 / 保存 / 清空）
├── theme.py             # 设计 token、深浅色 QSS 生成、5 套主题 + 自定义主题
├── i18n.py              # 中英文界面语言切换（翻译表 + 全局刷新）
├── command_executor.py  # COM 命令执行 + pyautogui 回退
├── config_manager.py    # 配置读写与自动迁移
├── config_presets.py    # 预设命令库与默认配置
├── updater.py           # 自动更新（版本检查 / 下载 / 静默安装）
├── version.py           # 运行时版本号（与 version.txt 同步）
├── single_instance.py   # 单实例与覆盖更新
├── menu_geometry.py     # 圆盘半径/缩放唯一来源（三处共用）
├── logger.py            # 文件 + 控制台双写日志
├── qt_feedback.py       # 命令执行反馈提示条
├── qt_popup.py          # 扇区编辑浮层定位与信号接线
├── qt_update_dialog.py  # 更新弹窗（说明 + 下载进度）
├── icon_library.py      # 内置矢量图标库与自定义图片解析
└── icon_picker.py       # 图标选择对话框
scripts/                # 开发脚本
├── build.bat            # 一键打包（PyInstaller + Inno Setup）
├── read_version.py      # 从 version.txt 提取版本号（构建用）
├── set_version.py       # 一键同步版本号（version.txt 4 处 + src/version.py）
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
