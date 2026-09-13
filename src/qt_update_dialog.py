"""更新弹窗 — 自定义两阶段弹窗（发现新版本说明 + 下载进度），跟随应用深/浅主题"""

from PySide6.QtCore import QEvent, Qt
from PySide6.QtWidgets import (QDialog, QHBoxLayout, QLabel, QProgressBar,
                               QPushButton, QScrollArea, QVBoxLayout)

from src.i18n import T
from src.theme import get_ui, font_px


class UpdateDialog(QDialog):
    """更新弹窗：信息模式（发现新版本）→ 下载模式切换"""

    def __init__(self, parent=None):
        super().__init__(parent)
        # 带最小化按钮：下载可能较久，允许最小化到任务栏后台继续
        self.setWindowFlags(Qt.Dialog | Qt.WindowTitleHint
                            | Qt.WindowMinimizeButtonHint
                            | Qt.WindowCloseButtonHint)
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
        self._on_retry = None
        self._on_minimized = None  # 最小化/恢复回调（下载期间托盘提示用）
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
                         on_update, on_later,
                         primary_text: str | None = None,
                         size_bytes: int = 0) -> None:
        """发现新版本：标题 + 版本 + 说明 + 立即更新/稍后

        Args:
            primary_text: 主按钮文案覆盖。绿色版不支持自动安装，由调用方
                传入「打开下载页」；None 时用默认「立即更新」。
            size_bytes: 安装包体积（API 提供；302 探测兜底为 0 不显示）。
        """
        self._title.setText(T("发现新版本 v{ver}").format(ver=version))
        sub = T("当前版本 v{cur} → 新版本 v{new}").format(
            cur=current, new=version)
        if size_bytes > 0:
            sub += " · " + T("安装包约 {mb} MB").format(
                mb=max(1, size_bytes // 1048576))
        self._subtitle.setText(sub)
        self._notes.setText(notes or T("（无更新说明）"))
        self._btn_primary.setText(primary_text or T("立即更新"))
        self._btn_secondary.setText(T("稍后再说"))
        self._on_update = on_update
        self._on_later = on_later
        self._on_cancel = None
        self._on_done = None
        self._on_minimized = None
        for w in self._info_widgets:
            w.show()
        for w in self._progress_widgets:
            w.hide()
        self._btn_primary.show()
        self._btn_secondary.show()

    # ========== 下载模式 ==========

    def show_download(self, version: str, on_cancel, on_minimized=None) -> None:
        """开始下载：进度条 + 取消按钮

        下载可能持续较久，切为非模态并允许最小化，不阻塞配置窗等应用内窗口；
        最小化/恢复经 on_minimized 通知 app 切托盘提示。
        """
        self.setModal(False)
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
        self._on_minimized = on_minimized

    def show_installing(self, on_done) -> None:
        """安装确认：更新包已就绪，点「开始安装」退出主进程交给安装器接管。

        下载完成后调用，把下载进度区替换为说明文字，「开始安装」放在
        primary 主按钮位（最强动作要有最强视觉）。
        """
        self._title.setText(T("更新包已就绪"))
        self._subtitle.setText("")
        self._notes.setText("")
        # 进度条转为忙碌模式（不定量动画），提示点「开始安装」后立即退出安装
        self._progress.setRange(0, 0)
        self._progress.setValue(0)
        self._progress_label.setText(
            T("点击「开始安装」将退出程序并自动安装更新，完成后自动启动新版。"))
        for w in self._info_widgets:
            w.hide()
        for w in self._progress_widgets:
            w.show()
        # 主按钮 = 开始安装；次按钮作「稍后」关闭
        self._btn_primary.setText(T("开始安装"))
        self._btn_primary.show()
        self._btn_secondary.setText(T("稍后再说"))
        self._on_done = on_done
        self._on_update = None
        self._on_later = None
        self._on_cancel = None
        self._on_minimized = None  # 安装确认阶段无下载，无需托盘进度提示

    def changeEvent(self, event):
        """最小化/恢复时回调 app（下载期间用它切托盘气泡与进度 tooltip）"""
        if (event.type() == QEvent.Type.WindowStateChange
                and self._on_minimized is not None):
            try:
                self._on_minimized(
                    bool(self.windowState() & Qt.WindowMinimized))
            except Exception:
                pass
        super().changeEvent(event)

    def show_download_failed(self, reason: str, on_retry) -> None:
        """下载失败：留在原窗口显示原因，主按钮「重试」、次按钮「关闭」。

        断点续传下重试可从上次中断处继续，不弹系统错误框打断流程。
        """
        self._title.setText(T("下载失败"))
        self._subtitle.setText(reason or T("下载失败，请检查网络后重试"))
        self._notes.setText("")
        for w in self._info_widgets:
            w.hide()
        for w in self._progress_widgets:
            w.hide()
        self._btn_primary.setText(T("重试"))
        self._btn_primary.show()
        self._btn_secondary.setText(T("关闭"))
        self._btn_secondary.show()
        self._on_retry = on_retry
        self._on_update = None
        self._on_later = None
        self._on_done = None
        self._on_cancel = self.close  # 失败模式次按钮 = 关闭窗口
        self._on_minimized = None

    def set_status(self, text: str) -> None:
        """下载源变化提示（副标题在下载模式下空闲，直接复用，零布局改动）"""
        self._subtitle.setText(text)

    def set_progress_percent(self, pct: int) -> None:
        """按百分比更新下载进度（0-100）"""
        pct = max(0, min(int(pct), 100))
        self._progress.setRange(0, 100)
        self._progress.setValue(pct)
        self._progress_label.setText(T("{pct}%").format(pct=pct))

    def set_progress(self, downloaded: int, total: int,
                     speed_bps: float = 0.0) -> None:
        """更新下载进度（按字节）；speed_bps>0 时附速度与剩余时间"""
        speed_txt = self._fmt_speed(speed_bps) if speed_bps > 0 else ""
        if total > 0:
            self._progress.setRange(0, 100)
            pct = int(downloaded * 100 / total)
            self._progress.setValue(min(pct, 100))
            txt = T("{pct}%  ({got} MB / {all} MB)").format(
                pct=min(pct, 100),
                got=downloaded // 1048576,
                all=max(1, total // 1048576))
            if speed_txt:
                txt += " · " + speed_txt
                remain = (total - downloaded) / speed_bps
                if remain > 0:
                    txt += " · " + self._fmt_eta(remain)
            self._progress_label.setText(txt)
        else:
            self._progress.setRange(0, 0)  # 无总大小：忙判模式
            txt = T("已下载 {got} MB").format(got=downloaded // 1048576)
            if speed_txt:
                txt += " · " + speed_txt
            self._progress_label.setText(txt)

    @staticmethod
    def _fmt_speed(speed_bps: float) -> str:
        """速度文案：≥1MB/s 一位小数，否则整数 KB/s"""
        if speed_bps >= 1048576:
            return T("{spd} MB/s").format(spd=f"{speed_bps / 1048576:.1f}")
        return T("{spd} KB/s").format(spd=max(1, int(speed_bps / 1024)))

    @staticmethod
    def _fmt_eta(seconds: float) -> str:
        """剩余时间文案：秒 / 分钟 / 小时三档"""
        if seconds < 90:
            return T("剩余约 {n} 秒").format(n=max(1, int(seconds)))
        minutes = int(seconds // 60)
        if minutes < 90:
            return T("剩余约 {n} 分钟").format(n=max(1, minutes))
        return T("剩余约 {n} 小时").format(n=max(1, int(seconds // 3600)))

    def _primary_clicked(self):
        if self._on_done:
            self._on_done()
            return
        if self._on_retry:
            self._on_retry()
            return
        if self._on_update:
            self._on_update()

    def _secondary_clicked(self):
        if self._on_done:
            # 安装确认阶段：次按钮 = 稍后关闭
            self.close()
            return
        cb = self._on_cancel or self._on_later
        if cb:
            cb()
