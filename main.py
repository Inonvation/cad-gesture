#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""CAD鼠标手势工具 - 主入口"""

import sys
import os

# 添加项目根目录到路径
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from src.logger import get_logger
from src.single_instance import ensure_single_instance
from src.app import CADGestureApp


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
    if not ensure_single_instance():
        print("[Gesture] 已有实例运行，旧实例将退出并由本实例接管")
        return
    app = CADGestureApp()
    app.run()


if __name__ == "__main__":
    main()
