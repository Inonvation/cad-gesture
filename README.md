# CAD Gesture

[English](README.en.md) | 简体中文

面向 **AutoCAD** 和 **中望CAD** 的鼠标手势与径向圆盘菜单工具。在 CAD 中长按鼠标右键并拖动，即可从圆盘菜单快速选择并执行命令，无需记忆快捷键。内置预设配置，开箱即用，适用于成图大赛等需要快速绘图的场景。

## 功能特性

- **三层径向圆盘菜单**：8 扇区 × 3 圈，内层 / 外层 / 扩展圈分级组织命令
- **流畅手势交互**：长按呼出、释放触发，支持悬停高亮与淡入动画
- **多套配置方案**：按 CAD 应用 / 工种分别配置，随前台窗口自动切换
- **6 套圆盘主题**：天蓝 / 翡翠 / 绯红 / 午夜 / 极光 / 石墨
- **可视化配置界面**（CustomTkinter）：点击扇区编辑命令，命令库支持搜索与拖放
- **不干扰 CAD 操作**：命令通过 COM `SendCommand` 发送，钩子仅监听、不拦截
- **单实例运行**：重复启动自动替换旧实例

## 支持环境

- Windows 10 / 11（64 位）
- AutoCAD 2025+ 或中望CAD
- Python 3.11+（源码运行）

## 快速开始

### 打包版

1. 从 [Releases](https://github.com/Inonvation/cad-gesture/releases) 下载 `CADGesture.exe`
2. 双击运行，托盘区出现图标即完成启动
3. 打开 CAD，长按鼠标右键并拖动即可使用

> 若 Releases 暂未提供安装包，请使用源码方式运行。

### 源码运行

```powershell
pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple
python main.py
```

## 使用说明

| 操作 | 说明 |
|------|------|
| 呼出菜单 | 在 CAD 窗口内长按鼠标右键并拖动（约 80ms） |
| 选择命令 | 拖向目标扇区，高亮后释放触发 |
| 内层 | 高频绘图命令（直线、圆、复制等） |
| 外层 | 编辑命令（圆弧、旋转、缩放等） |
| 扩展圈 | 低频延伸命令，拖过第二圈边界触发 |
| 托盘 | 右键托盘图标 → 配置 / 切换方案 / 退出 |

## 配置

右键托盘图标 → **配置**，打开可视化编辑器：

- **左侧**：方案管理（新增 / 复制 / 重命名 / 删除）
- **中间**：圆盘预览，点击扇区编辑命令
- **右侧**：命令库，支持搜索与拖放
- **侧边栏**：圆盘主题、启动选项

配置存于 `config/config.json`，首次运行自动生成，模板见 `config/config.example.json`。每个方案包含三层命令：`sectors`（内层）、`outer_sectors`（外层）、`extension_sectors`（扩展圈）。每条命令由 `label`（显示名）、`key`（回退快捷键）、`description`（CAD 命令名）组成。

## 技术栈

- **Python 3.11+** / Win32 API：低级鼠标钩子 `WH_MOUSE_LL`、Per-Monitor V2 DPI 感知
- **CustomTkinter**：配置界面
- **COM / pyautogui**：命令执行
- **pystray / Pillow**：托盘图标
- **PyInstaller**：打包

## 目录结构

```
main.py                  # 入口（单实例检查 + DPI 感知）
requirements.txt         # 依赖清单
config/                  # 配置（首次运行自动生成，模板见 config.example.json）
src/                     # 源码
├── app.py               # 主程序：事件队列、托盘、配置入口
├── gesture_engine.py    # 鼠标钩子与手势/圈层判定
├── radial_menu.py       # 透明悬浮圆盘菜单
├── command_executor.py  # COM 命令执行 + 回退
├── config_gui.py        # 配置界面
└── ...                  # 渲染、主题、日志、单实例等模块
assets/                  # 应用图标
tests/                   # 单元测试
```

本项目为个人独立开发，灵感来自 Quicker 与 SolidWorks 的鼠标笔式，首次尝试使用 AI 辅助开发 Python 桌面应用。时间与精力有限，欢迎提交 issue 或 PR。
