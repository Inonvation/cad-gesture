"""命令执行反馈提示 — 屏幕角落短暂显示"命令名 / 快捷键"两行"""

from PySide6.QtCore import (QEasingCurve, QPropertyAnimation, QRect, Qt, QTimer)
from PySide6.QtGui import (QColor, QFont, QFontMetrics, QPainter, QPen,
                           QCursor, QGuiApplication)
from PySide6.QtWidgets import QWidget

from src.theme import get_ui, font_px


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
        self._line1_font_size = 16  # 超长命令名自动缩小的字号
        self.setFixedSize(260, 64)
        self._fade = QPropertyAnimation(self, b"windowOpacity", self)
        self._fade.setDuration(300)
        self._fade.setEasingCurve(QEasingCurve.InOutQuad)
        # 淡出完成后隐藏（只连接一次，避免反复 disconnect 触发警告）
        self._fade.finished.connect(self.hide)
        self._hide_timer = QTimer(self)
        self._hide_timer.setSingleShot(True)
        self._hide_timer.timeout.connect(self._fade_out)

    def show_feedback(self, text1: str, text2: str, settings: dict) -> None:
        """显示提示：text1 命令名 / text2 快捷键，按 settings 定位与计时"""
        # 先停止淡出并隐藏旧弹窗：避免上一个命令的旧画面在重绘前被看到。
        # 不在本函数内立即 show：show() 到 repaint() 之间 Windows
        # 会先显示隐藏前的旧表面（高刷新率显示器上可见），
        # 延迟一帧再显示，确保窗口展示时带的是新内容。
        self._fade.stop()
        self._hide_timer.stop()
        self.hide()
        self._line1, self._line2 = text1, text2
        self._duration_ms = int(settings.get("feedback_duration_ms", 1500))
        self._resize_to_fit()
        self.setWindowOpacity(1.0)
        self._position_for(
            settings.get("feedback_position", "bottom_center"),
            int(settings.get("feedback_offset_x", 0)),
            int(settings.get("feedback_offset_y", 0)),
        )
        self.update()
        QTimer.singleShot(0, self._show_now)
        self._hide_timer.start(self._duration_ms)

    def _show_now(self):
        """事件循环下一轮显示：hide 已完全生效后，新表面不会带上一命令旧画面"""
        # 若延迟期间被 hide_tip 清空（新手势已开始），则不再显示
        if not (self._line1 or self._line2):
            return
        self.show()
        self.raise_()
        self.repaint()

    def hide_tip(self) -> None:
        """立即隐藏当前提示：新一次手势开始时清除上一条残留弹窗"""
        self._fade.stop()
        self._hide_timer.stop()
        self._line1 = ""
        self._line2 = ""
        self.hide()

    def _resize_to_fit(self):
        """弹窗宽度随最长文本自适应，超长命令名缩字号不溢出"""
        f1 = QFont("Microsoft YaHei")
        f1.setPixelSize(font_px(16))
        f1.setBold(True)
        f2 = QFont("Microsoft YaHei")
        f2.setPixelSize(font_px(12))
        w1 = QFontMetrics(f1).horizontalAdvance(self._line1)
        w2 = QFontMetrics(f2).horizontalAdvance(self._line2)
        w = max(180, min(420, max(w1, w2) + 56))
        self.setFixedSize(w, 64)
        # 极长文本：主行字号从 16 往下缩，保证不超出弹窗宽度
        size = 16
        while size > 10 and QFontMetrics(f1).horizontalAdvance(
                self._line1) > w - 40:
            size -= 1
            f1.setPixelSize(size)
        self._line1_font_size = size

    def _position_for(self, pos: str, offset_x: int = 0, offset_y: int = 0) -> None:
        """按预设锚点定位，再叠加像素偏移，最后夹紧在屏幕可用区内"""
        # 弹在光标所在屏幕（多显示器时提示出现在正在操作的屏，而非主屏）
        screen = (QGuiApplication.screenAt(QCursor.pos())
                  or self.screen()).availableGeometry()
        w, h = self.width(), self.height()
        if pos == "top_center":
            x = screen.center().x() - w // 2
            y = screen.top() + int(screen.height() * 0.12)
        elif pos == "bottom_right":
            x = screen.right() - w - 20
            y = screen.bottom() - h - 20
        elif pos == "bottom_left":
            x = screen.left() + 20
            y = screen.bottom() - h - 20
        elif pos == "top_left":
            x = screen.left() + 20
            y = screen.top() + 20
        elif pos == "top_right":
            x = screen.right() - w - 20
            y = screen.top() + 20
        elif pos == "center":
            x = screen.center().x() - w // 2
            y = screen.center().y() - h // 2
        else:  # bottom_center 默认：下部中间偏上，避开屏幕中心挡视野
            x = screen.center().x() - w // 2
            y = screen.top() + int(screen.height() * 0.75)
        x = max(screen.left(), min(screen.right() - w, x + offset_x))
        y = max(screen.top(), min(screen.bottom() - h, y + offset_y))
        self.move(x, y)

    def _fade_out(self):
        self._fade.stop()
        self._fade.setStartValue(self.windowOpacity())
        self._fade.setEndValue(0.0)
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
        f.setPixelSize(self._line1_font_size)
        f.setBold(True)
        p.setFont(f)
        # 命令名用主题强调色，突出“刚执行了什么”
        p.setPen(QColor(ui.accent))
        p.drawText(QRect(0, 8, self.width(), 24), Qt.AlignCenter, self._line1)
        if self._line2:
            f2 = QFont("Microsoft YaHei")
            f2.setPixelSize(font_px(12))
            p.setFont(f2)
            fm = QFontMetrics(f2)
            pw = fm.horizontalAdvance(self._line2) + 18
            pr = QRect((self.width() - pw) // 2, 33, pw, 20)
            # 快捷键底色 pill：低调强调，深/浅主题均清晰
            p.setPen(Qt.NoPen)
            p.setBrush(QColor(ui.bg_selected))
            p.drawRoundedRect(pr, 10, 10)
            p.setPen(QColor(ui.text_secondary))
            p.drawText(pr, Qt.AlignCenter, self._line2)
        p.end()
