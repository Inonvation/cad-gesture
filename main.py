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

get_logger()


def main():
    """主函数"""
    if not ensure_single_instance():
        print("[Gesture] 已有实例运行，旧实例将退出并由本实例接管")
        return
    app = CADGestureApp()
    app.run()


if __name__ == "__main__":
    main()
