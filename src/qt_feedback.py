"""命令执行反馈提示 — 屏幕角落短暂显示"命令名 / 快捷键"两行"""

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer)
from PySide6.QtGui import QColor, QFont, QPainter, QPen
from PySide6.QtWidgets import QWidget

from src.theme import get_ui


class QFeedbackTip(QWidget):
    """无边框置顶提示窗：两行文字，短暂停留后淡出。

    位置 / 是否显示名称 / 是否显示快捷键 / 停留时长均由 settings 配置，
    跟随界面深浅色主题（paintEvent 时取当前 get_ui()）。
    """

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint
                         | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._line1 = ""
        self._line2 = ""
        self._duration_ms = 1500
        self.setFixedSize(260, 64)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(300)
        self._fade.setEasingCurve(QEasingCurve.InOutQuad)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

    def show_feedback(self, text1: str, text2: str, settings: dict) -> None:
        """显示提示：text1 命令名 / text2 快捷键，按 settings 定位与计时"""
        self._line1, self._line2 = text1, text2
        self._duration_ms = int(settings.get("feedback_duration_ms", 1500))
        self._fade.stop()
        self.setWindowOpacity(1.0)
        self._position_for(settings.get("feedback_position", "bottom_center"))
        self.update()
        self.show()
        self.raise_()
        self._hide_timer.start(self._duration_ms)

    def _position_for(self, pos: str) -> None:
        screen = self.screen().availableGeometry()
        w, h = self.width(), self.height()
        if pos == "top_center":
            x = screen.center().x() - w // 2
            y = screen.top() + int(screen.height() * 0.12)
        elif pos == "bottom_right":
            x = screen.right() - w - 20
            y = screen.bottom() - h - 20
        elif pos == "center":
            x = screen.center().x() - w // 2
            y = screen.center().y() - h // 2
        else:  # bottom_center 默认（用户要求"中间偏下"）
            x = screen.center().x() - w // 2
            y = screen.top() + int(screen.height() * 0.62)
        self.move(x, y)

    def _fade_out(self):
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
        self._fade.finished.connect(self.hide)
        self._fade.start()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        ui = get_ui()
        p.setPen(Qt.NoPen)
        p.setBrush(QColor(ui.bg_overlay))
        p.drawRoundedRect(self.rect(), 10, 10)
        p.setBrush(Qt.NoBrush)
        p.setPen(QPen(QColor(ui.border_strong), 1))
        p.drawRoundedRect(self.rect().adjusted(1, 1, -1, -1), 10, 10)
        f = QFont("Microsoft YaHei")
        f.setPixelSize(16)
        f.setBold(True)
        p.setFont(f)
        p.setPen(QColor(ui.text))
        p.drawText(QRect(0, 8, self.width(), 24), Qt.AlignCenter, self._line1)
        f.setPixelSize(12)
        f.setBold(False)
        p.setFont(f)
        p.setPen(QColor(ui.text_secondary))
        p.drawText(QRect(0, 34, self.width(), 18), Qt.AlignCenter, self._line2)
        p.end()
