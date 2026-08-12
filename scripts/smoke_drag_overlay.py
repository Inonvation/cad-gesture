# -*- coding: utf-8 -*-
"""拖动/点击分离验证 + 覆盖层冒烟"""
import os, sys, io
sys.stdout = io.TextIOWrapper(sys.stdout.buffer, encoding="utf-8")
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
sys.path.insert(0, "F:/cad-gesture")

from PySide6.QtCore import QEvent, QPoint, QPointF, Qt
from PySide6.QtGui import QMouseEvent
from PySide6.QtWidgets import QApplication

app = QApplication.instance() or QApplication([])
from src import config_manager
config_manager.save_config = lambda cfg: True

from src.qt_config_gui import _CardListWidget, _ProfileCard, _WindowPickOverlay

# 1) header 拖动：press + move 超阈值 -> start_drag 调用，且不触发 toggle
lst = _CardListWidget()
card = _ProfileCard("a", "A", on_toggle=None)
lst.add_card(card)
started = []
toggled = []
card.header._on_toggle = lambda: toggled.append(1)
lst.start_drag = lambda c: started.append(c)

h = card.header
press = QMouseEvent(QEvent.MouseButtonPress, QPointF(20, 15), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
h.mousePressEvent(press)
move = QMouseEvent(QEvent.MouseMove, QPointF(60, 15), Qt.NoButton, Qt.LeftButton, Qt.NoModifier)
h.mouseMoveEvent(move)
assert len(started) == 1 and started[0] is card, "start_drag should be called"
assert not toggled, "drag should not toggle"
print("1. drag triggers start_drag OK, toggle not called")

# 2) header 点击：press + release 未移动 -> toggle
card2 = _ProfileCard("b", "B", on_toggle=None)
toggled2 = []
card2.header._on_toggle = lambda: toggled2.append(1)
press2 = QMouseEvent(QEvent.MouseButtonPress, QPointF(20, 15), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
card2.header.mousePressEvent(press2)
rel2 = QMouseEvent(QEvent.MouseButtonRelease, QPointF(20, 15), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
card2.header.mouseReleaseEvent(rel2)
assert toggled2 == [1], "click should toggle"
print("2. click toggles OK")

# 3) 覆盖层实例化 + 显示/隐藏
ov = _WindowPickOverlay()
picked = []
ov.show_pick(on_picked=lambda exe, title: picked.append((exe, title)))
for _ in range(3): app.processEvents()
assert ov.isVisible(), "overlay should be visible"
# 模拟点击（确认）
click = QMouseEvent(QEvent.MouseButtonPress, QPointF(100, 100), Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
ov.mousePressEvent(click)
for _ in range(3): app.processEvents()
assert not ov.isVisible(), "overlay should hide after confirm"
assert len(picked) == 1, "picked callback should fire"
print("3. overlay pick OK, callback fired")

# 4) 倒计时自动确认
ov2 = _WindowPickOverlay()
picked2 = []
ov2.show_pick(on_picked=lambda exe, title: picked2.append(1))
ov2._seconds = 1
ov2._tick()
for _ in range(3): app.processEvents()
assert picked2 == [1], "countdown should auto-confirm"
print("4. countdown auto-confirm OK")

print("ALL DRAG/OVERLAY SMOKE OK")
