# 更新日志 (Changelog)

格式基于 [Keep a Changelog](https://keepachangelog.com/zh-CN/1.1.0/)，
版本号遵循 [语义化版本](https://semver.org/lang/zh-CN/)。

## [0.0.3] - 2026-08-10

### 新增

- 安装版 Setup 安装包（Inno Setup）：标准安装向导、开始菜单 / 桌面快捷方式 / 卸载入口、免 UAC、可选择安装位置
- 程序内一键更新：托盘"检查更新" + 设置界面"检查更新"按钮 + 启动时自动检查（24h 间隔），下载新版自动静默覆盖安装
- 设置界面新增"启动时检查更新"开关
- 新增 `src/updater.py` 自动更新模块与 `src/version.py` 运行时版本号

### 变更

- 构建脚本 `scripts/build.bat` 集成 Inno Setup，一次构建产出绿色版 + 安装版双产物
- 发布物新增安装包（Release 附件：绿色版 + 安装版 + 配置模板）

### 修复

- 打包版 https 不可用（spec 误排除 OpenSSL DLL）导致更新功能失效
- 设置界面"启动时检查更新"开关显示状态不同步
- 手动检查更新结果改为弹窗提示（托盘气泡可能被系统屏蔽）

### 文档

- README / README.en 新增安装版与自动更新说明、SmartScreen FAQ
- 新增 `docs/installer-update-plan.md` 实施规划
