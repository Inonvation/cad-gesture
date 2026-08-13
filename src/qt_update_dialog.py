"""更新弹窗 — 自定义两阶段弹窗（发现新版本说明 + 下载进度），跟随应用深/浅主题"""

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QScrollArea, QVBoxLayout)

from src.i18n import T
from src.theme import get_ui, font_px


class UpdateDialog(QDialog):
    """更新弹窗：信息模式（发现新版本）→ 下载模式切换"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint)
        self.setWindowTitle(T("软件更新"))
        self.setModal(True)
        self.setFixedWidth(460)
        self._build_ui()
        self._apply_style()

    def _build_ui(self):
        root = QVBoxLayout(self)
        root.setContentsMargins(22, 20, 22, 16)
        root.setSpacing(12)

        self._title = QLabel()
        self._title.setObjectName("title")
        root.addWidget(self._title)

        self._subtitle = QLabel()
        self._subtitle.setObjectName("subtitle")
        self._subtitle.setWordWrap(True)
        root.addWidget(self._subtitle)

        # 更新说明（可滚动）
        self._scroll = QScrollArea()
        self._scroll.setWidgetResizable(True)
        self._scroll.setFixedHeight(150)
        self._scroll.setFrameShape(QScrollArea.NoFrame)
        self._notes = QLabel()
        self._notes.setObjectName("notes")
        self._notes.setWordWrap(True)
        self._notes.setTextInteractionFlags(Qt.TextSelectableByMouse)
        self._scroll.setWidget(self._notes)
        root.addWidget(self._scroll)

        # 下载进度区（默认隐藏）
        self._progress = QProgressBar()
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress.setFixedHeight(18)
        self._progress.setTextVisible(False)
        root.addWidget(self._progress)

        self._progress_label = QLabel()
        self._progress_label.setObjectName("progressLabel")
        root.addWidget(self._progress_label)

        # 按钮行
        btn_row = QHBoxLayout()
        btn_row.addStretch(1)
        self._btn_primary = QPushButton()
        self._btn_primary.setProperty("class", "primary")
        self._btn_primary.setCursor(Qt.PointingHandCursor)
        self._btn_primary.setFixedWidth(110)
        btn_row.addWidget(self._btn_primary)
        self._btn_secondary = QPushButton()
        self._btn_secondary.setProperty("class", "ghost")
        self._btn_secondary.setCursor(Qt.PointingHandCursor)
        self._btn_secondary.setFixedWidth(90)
        btn_row.addWidget(self._btn_secondary)
        root.addLayout(btn_row)

        self._info_widgets = (self._scroll,)
        self._progress_widgets = (self._progress, self._progress_label)

        # 回调存储（信号只连接一次）
        self._on_update = None
        self._on_later = None
        self._on_cancel = None
        self._on_done = None
        self._btn_primary.clicked.connect(self._primary_clicked)
        self._btn_secondary.clicked.connect(self._secondary_clicked)

    def _apply_style(self):
        ui = get_ui()
        self.setStyleSheet(
            f"QDialog {{ background: {ui.bg_raised}; }}"
            f"\nQLabel#title {{ color: {ui.accent}; font-size: {font_px(17)}px; "
            f"font-weight: bold; }}"
            f"\nQLabel#subtitle {{ color: {ui.text_secondary}; "
            f"font-size: {font_px(12)}px; }}"
            f"\nQLabel#notes {{ color: {ui.text}; font-size: {font_px(12)}px; "
            f"background: transparent; }}"
            f"\nQLabel#progressLabel {{ color: {ui.text_secondary}; "
            f"font-size: {font_px(11)}px; }}"
            f"\nQScrollArea {{ border: 1px solid {ui.border}; border-radius: 8px; "
            f"background: {ui.bg_card}; }}"
            f"\nQScrollArea QWidget#qt_scrollarea_viewport {{ background: {ui.bg_card}; }}"
            f"\nQProgressBar {{ border: 1px solid {ui.border_strong}; "
            f"border-radius: 9px; background: {ui.bg_input}; }}"
            f"\nQProgressBar::chunk {{ background: qlineargradient("
            f"x1:0, y1:0, x2:1, y2:0, stop:0 {ui.accent_dim}, stop:1 {ui.accent}); "
            f"border-radius: 8px; }}"
            f"\nQPushButton {{ background: {ui.bg_card}; color: {ui.text}; "
            f"border: 1px solid {ui.border_strong}; border-radius: 6px; "
            f"padding: 6px 14px; font-size: {font_px(12)}px; }}"
            f"\nQPushButton:hover {{ background: {ui.bg_hover}; }}"
            f"\nQPushButton[class=\"primary\"] {{ background: {ui.accent}; "
            f"color: {ui.accent_text}; border: 1px solid {ui.accent}; "
            f"font-weight: bold; }}"
            f"\nQPushButton[class=\"primary\"]:hover {{ background: {ui.accent_hover}; }}"
            f"\nQPushButton[class=\"ghost\"] {{ background: transparent; "
            f"border-color: transparent; color: {ui.text_secondary}; }}"
            f"\nQPushButton[class=\"ghost\"]:hover {{ background: {ui.bg_hover}; "
            f"color: {ui.text}; }}"
        )

    # ========== 信息模式 ==========

    def show_update_info(self, version: str, current: str, notes: str,
                         on_update, on_later) -> None:
        """发现新版本：标题 + 版本 + 说明 + 立即更新/稍后"""
        self._title.setText(T("发现新版本 v{ver}").format(ver=version))
        self._subtitle.setText(T("当前版本 v{cur} → 新版本 v{new}")
                               .format(cur=current, new=version))
        self._notes.setText(notes or T("（无更新说明）"))
        self._btn_primary.setText(T("立即更新"))
        self._btn_secondary.setText(T("稍后再说"))
        self._on_update = on_update
        self._on_later = on_later
        self._on_cancel = None
        self._on_done = None
        for w in self._info_widgets:
            w.show()
        for w in self._progress_widgets:
            w.hide()
        self._btn_primary.show()
        self._btn_secondary.show()

    # ========== 下载模式 ==========

    def show_download(self, version: str, on_cancel) -> None:
        """开始下载：进度条 + 取消按钮"""
        self._title.setText(T("正在下载 v{ver} 更新包").format(ver=version))
        self._subtitle.setText("")
        self._notes.setText("")
        self._progress.setRange(0, 100)
        self._progress.setValue(0)
        self._progress_label.setText("0%")
        for w in self._info_widgets:
            w.hide()
        for w in self._progress_widgets:
            w.show()
        self._btn_primary.hide()
        self._btn_secondary.setText(T("取消"))
        self._on_cancel = on_cancel
        self._on_update = None
        self._on_later = None
        self._on_done = None

    def show_installing(self, on_done) -> None:
        """安装确认：更新包已就绪，点「开始安装」退出主进程交给安装器接管。

        下载完成后调用，把下载进度区替换为说明文字，原「取消」按钮变为
        「开始安装」。点它触发 on_done（主进程内启动静默安装器并退出）。
        """
        self._title.setText(T("更新包已就绪"))
        self._subtitle.setText("")
        self._notes.setText("")
        # 进度条转为忙碌模式（不定量动画），提示点「开始安装」后立即退出安装
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        self._progress_label.setText(T("点击「开始安装」将退出程序并自动安装更新，完成后自动启动新版。"))
        for w in self._info_widgets:
            w.hide()
        for w in self._progress_widgets:
            w.show()
        self._btn_primary.hide()
        self._btn_secondary.setText(T("开始安装"))
        self._btn_secondary.setFixedWidth(110)
        self._on_done = on_done
        self._on_cancel = None
        self._on_update = None
        self._on_later = None

    def set_progress(self, downloaded: int, total: int) -> None:
        """更新下载进度"""
        if total > 0:
            self._progress.setRange(0, 100)
            pct = int(downloaded * 100 / total)
            self._progress.setValue(min(pct, 100))
            self._progress_label.setText(
                T("{pct}%  ({got} MB / {all} MB)")
                .format(pct=min(pct, 100),
                        got=downloaded // 1048576,
                        all=max(1, total // 1048576)))
        else:
            self._progress.setRange(0, 0)  # 无总大小：忙判模式
            self._progress_label.setText(
                T("已下载 {got} MB").format(got=downloaded // 1048576))

    def _primary_clicked(self):
        if self._on_update:
            self._on_update()

    def _secondary_clicked(self):
        if self._on_done:
            self._on_done()
            return
        cb = self._on_cancel or self._on_later
        if cb:
            cb()
