# -*- coding: utf-8 -*-
"""调试辅助：直接打开配置界面（不创建托盘）"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from PySide6.QtWidgets import QApplication
from src.qt_config_gui import open_config_gui

app = QApplication(sys.argv)
win = open_config_gui()
win.show()
win.raise_()
win.activateWindow()
sys.exit(app.exec())
