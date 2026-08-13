# 贡献指南 (Contributing)

感谢你愿意参与 CAD 鼠标手势工具。项目不大，但遵循下面几条约定能让协作顺畅。

## 开发环境

- Windows 10/11 + Python 3.11+
- 安装依赖：`pip install -r requirements.txt -i https://pypi.tuna.tsinghua.edu.cn/simple`
- 运行：`python main.py`

## 验证流程（提交前必须做）

```powershell
python -m py_compile src\修改的文件.py   # 语法检查
python -m pytest tests/ -q               # 全量测试
python scripts\verify.py                 # 一键：语法 + 测试 + 重启程序
```

## 提交规范

格式：`前缀: 中文描述`（前缀英文小写，描述中文）。

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
- 含中文的提交信息用 `git commit -F <message 文件>`（UTF-8），避免终端编码问题

## 改动联动清单

改代码前先看根目录 `AGENTS.md` 的"改动联动清单"：
- 圆盘配色/主题 → `theme.py` 的 `MENU_THEMES`
- 字体/扇区绘制 → `qt_renderer.py`（运行时菜单与两处预览共用）
- 新增 settings 配置项 → `config_presets._default_config` + `config_manager._migrate_config`
- 改圈层/触发阈值 → 只改 `menu_geometry.py` 的 `DEFAULT_RADII`

## 打包（仅发版时）

双击 `scripts\build.bat`（需 Python312 + Inno Setup 6.3+），产物见 README"打包发布"。

