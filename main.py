#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CAD鼠标手势工具 - 主入口"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

import velopack  # noqa: E402  顶层导入确保 PyInstaller 收集 velopack.pyd

from src.logger import get_logger  # noqa: E402
from src.single_instance import ensure_single_instance  # noqa: E402
from src.app import CADGestureApp, _RESTART_FLAG  # noqa: E402


def _enable_dpi_awareness():
    """声明 Per-Monitor V2 DPI 感知，修复混合 DPI 多屏下圆盘与光标错位。

    必须在创建任何窗口之前调用；Windows 10 1703 以下回退到
    shcore.SetProcessDpiAwareness(PER_MONITOR_AWARE)。
    """
    try:
        import ctypes
        # Windows 10 1703+：DPI_AWARENESS_CONTEXT_PER_MONITOR_AWARE_V2 = -4
        ctypes.windll.user32.SetProcessDpiAwarenessContext(-4)
    except Exception:
        try:
            import ctypes
            ctypes.windll.shcore.SetProcessDpiAwareness(2)
        except Exception:
            pass


_enable_dpi_awareness()
get_logger()


def _velopack_bootstrap():
    """Velopack 初始化，必须在本进程最早、任何窗口创建前执行。

    根因：Velopack 的 Setup.exe / Update.exe 会以特殊命令行参数
    （--velopack-install / --velopack-update 等）重新拉起主程序来完成
    安装/卸载/更新后的收尾；这些参数必须由 velopack.App().run() 消费。
    若在 GUI 初始化之后才调用，安装流程会卡住、更新重启会被当成普通启动。
    run() 在普通启动时仅做定位器初始化并返回（no-op）；在需要时会自行
    结束或重启本进程，无需调用方处理。
    """
    try:
        vp = velopack.App()
        # 更新成功重启后的首次启动：置标志，由 app 弹"已更新到 vX"
        vp.on_restarted(lambda: os.environ.setdefault(_RESTART_FLAG, "1"))
        vp.run()
    except Exception:
        # Velopack 初始化失败不阻塞程序运行（例如非打包环境缺失 Update.exe）；
        # 仅影响自动更新能力，手势等核心功能不受牵连。
        get_logger().exception("Velopack 初始化失败，自动更新不可用")


def _install_excepthook():
    """全局未捕获异常兜底：写入日志文件，避免异常被静默吞掉（打包版无控制台）"""
    import traceback

    def _hook(exc_type, exc_value, exc_tb):
        try:
            from src.logger import get_logger
            get_logger().error(
                "未捕获异常: %s\n%s",
                exc_value,
                "".join(traceback.format_exception(
                    exc_type, exc_value, exc_tb)))
        except Exception:
            pass
        sys.__excepthook__(exc_type, exc_value, exc_tb)

    sys.excepthook = _hook


_install_excepthook()


def main():
    """主函数"""
    # Velopack 最先执行（消费安装/更新命令行参数），再进入单实例与 GUI 启动
    _velopack_bootstrap()
    if not ensure_single_instance():
        print("[Gesture] 已有实例运行，旧实例将退出并由本实例接管")
        return
    app = CADGestureApp()
    app.run()


if __name__ == "__main__":
    main()
