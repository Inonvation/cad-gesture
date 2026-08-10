"""扇区编辑浮层 — 点击圆盘扇区后就地弹出的编辑器

无边框 Tool 窗口：外部点击关闭由主窗口的应用级事件过滤器统一管理
（不再用 Qt.Popup，规避其关闭-重开竞态导致的黑边问题）；输入即时
写回配置（发信号，由主窗口负责落盘）。只负责展示与交互，不持有配置数据。

样式由全局 QSS 提供（build_app_qss 的 QFrame#popupCard 等规则），
随界面模式（浅/深）自动切换；语言切换通过 retranslate 刷新文本。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtWidgets import (QFormLayout, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QPushButton, QVBoxLayout)

from src.i18n import T
from src.theme import FONT_SM


class SectorEditorPopup(QFrame):
    """扇区编辑浮层（无边框 Tool 窗：外部点击/Esc 关闭由事件过滤器与按键处理完成）"""

    edited = Signal()                  # 任一输入变化（仅标记未保存）
    save_requested = Signal()          # 点击保存按钮（外部写回 + 撤销记录）
    cleared = Signal()                 # 清空当前扇区
    closed = Signal()                  # 浮层关闭（用于清理状态）
    blank_clicked = Signal(float, float)  # 点击浮层空白处（全局逻辑坐标，转发给预览）
    esc_requested = Signal()           # Esc：有未保存修改，由主窗口确认后关闭
    reposition_requested = Signal()    # 双击头部：恢复圆盘下方默认位置

    def __init__(self, parent=None):
        super().__init__(parent, Qt.FramelessWindowHint | Qt.WindowStaysOnTopHint | Qt.Tool)
        self.setAttribute(Qt.WA_TranslucentBackground)
        # 浮层窗口自身保持透明（防止应用级 QSS 的背景规则污染）；
        # 内容卡片背景由全局 QSS 的 QFrame#popupCard 提供（特异性更高）
        self.setStyleSheet("QFrame { background: transparent; }")
        self._loading = False
        self._layer = "inner"
        self._idx = 0
        self._dirty = False            # 有未保存的输入修改
        self._dragging = False
        self._drag_offset = None
        self.user_moved = False   # 用户拖动过浮层：此后不再自动定位到圆盘下方

        root = QFrame(self)
        root.setObjectName("popupCard")
        outer = QVBoxLayout(self)
        outer.setContentsMargins(1, 1, 1, 1)
        outer.addWidget(root)
        lay = QVBoxLayout(root)
        lay.setContentsMargins(16, 10, 16, 10)
        lay.setSpacing(5)

        # 头部：所在层 · 扇区 N（整行是拖动把手，按住可移动浮层）
        head = QHBoxLayout()
        self.drag_handle = QLabel("⠿")
        self.drag_handle.setToolTip(T("按住此处可拖动编辑窗"))
        self.drag_handle.setCursor(Qt.OpenHandCursor)
        self.title = QLabel("")
        self.title.setObjectName("popupTitle")
        self.title.setCursor(Qt.OpenHandCursor)
        self.meta = QLabel("")
        self.meta.setObjectName("popupMeta")
        head.addWidget(self.drag_handle)
        head.addSpacing(6)
        head.addWidget(self.title)
        head.addSpacing(6)
        head.addWidget(self.meta)
        head.addStretch(1)
        lay.addLayout(head)

        # 三个输入
        form = QFormLayout()
        form.setSpacing(5)
        form.setLabelAlignment(Qt.AlignLeft)
        self.label_entry = QLineEdit()
        self.label_entry.setPlaceholderText(T("圆盘上显示的名称"))
        self.key_entry = QLineEdit()
        self.key_entry.setPlaceholderText(T("回退快捷键，如 L / CO"))
        self.desc_entry = QLineEdit()
        self.desc_entry.setPlaceholderText(T("发送到 CAD 的命令名，如 LINE"))
        form.addRow(self._field(T("显示名称")), self.label_entry)
        form.addRow(self._field(T("快捷键")), self.key_entry)
        form.addRow(self._field(T("CAD 命令")), self.desc_entry)
        lay.addLayout(form)

        for w in (self.label_entry, self.key_entry, self.desc_entry):
            w.textChanged.connect(self._on_edited)

        # 按钮行：保存 / 清空
        btn_row = QHBoxLayout()
        btn_row.setSpacing(8)
        self.btn_save = QPushButton(T("保存"))
        self.btn_save.setProperty("class", "primary")
        self.btn_save.setToolTip(T("保存该扇区的命令修改"))
        self.btn_save.clicked.connect(self.save_requested.emit)
        btn_row.addWidget(self.btn_save)
        self.btn_clear = QPushButton(T("清空"))
        self.btn_clear.setObjectName("clearBtn")
        self.btn_clear.setToolTip(T("删除该扇区命令"))
        self.btn_clear.clicked.connect(self._on_clear)
        btn_row.addWidget(self.btn_clear)
        btn_row.addStretch(1)
        lay.addLayout(btn_row)

    def _field(self, text: str) -> QLabel:
        lb = QLabel(text)
        lb.setObjectName("fieldName")
        lb.setFixedWidth(72)
        lb.setStyleSheet(f"font-size: {FONT_SM}px;")
        return lb

    # ========== 语言切换 ==========

    def retranslate(self):
        """语言切换：刷新浮层内全部文本（打开状态时由主窗口调用）"""
        self.drag_handle.setToolTip(T("按住此处可拖动编辑窗"))
        self.label_entry.setPlaceholderText(T("圆盘上显示的名称"))
        self.key_entry.setPlaceholderText(T("回退快捷键，如 L / CO"))
        self.desc_entry.setPlaceholderText(T("发送到 CAD 的命令名，如 LINE"))
        self.btn_save.setText(T("保存"))
        self.btn_save.setToolTip(T("保存该扇区的命令修改"))
        self.btn_clear.setText(T("清空"))
        self.btn_clear.setToolTip(T("删除该扇区命令"))
        self._update_title()

    # ========== 外部接口 ==========

    def show_sector(self, layer: str, idx: int, cfg: dict, n: int) -> None:
        """打开浮层显示某扇区配置。cfg 为扇区命令 dict（可能为空）。"""
        self._layer = layer
        self._idx = idx
        self._loading = True
        self._update_title()
        self.meta.setText(T("已保存"))
        self._dirty = False
        self.label_entry.setText(cfg.get("label", ""))
        self.key_entry.setText(cfg.get("key", ""))
        self.desc_entry.setText(cfg.get("description", ""))
        self._loading = False

    def _update_title(self):
        layer_names = {"inner": T("内层"), "outer": T("外层"), "extension": T("扩展圈")}
        self.title.setText(
            T("{layer} · 扇区 {idx}").format(
                layer=layer_names.get(self._layer, self._layer), idx=self._idx))

    # ========== 内部 ==========

    def _on_edited(self, text):
        if not self._loading:
            self._dirty = True
            self.meta.setText(T("未保存"))
            self.edited.emit()

    def mark_saved(self):
        self._dirty = False
        self.meta.setText(T("已保存"))

    def _on_clear(self):
        self.cleared.emit()

    def showEvent(self, e):
        super().showEvent(e)
        self.activateWindow()
        self.label_entry.setFocus()
        self.label_entry.selectAll()

    def hideEvent(self, e):
        super().hideEvent(e)
        self.closed.emit()

    def keyPressEvent(self, event):
        if event.key() == Qt.Key_Escape:
            if self._dirty:
                # 有未保存修改：交由主窗口弹确认框（保存/放弃/取消）
                self.esc_requested.emit()
            else:
                self.close()
        else:
            super().keyPressEvent(event)

    def mouseDoubleClickEvent(self, event):
        if (event.button() == Qt.LeftButton
                and event.position().y() <= 32):
            # 双击头部：恢复圆盘下方默认位置
            self.user_moved = False
            self.reposition_requested.emit()
            return
        super().mouseDoubleClickEvent(event)

    def mousePressEvent(self, event):
        """按住头部拖动浮层；点击空白处（非输入控件/按钮）关闭并把点击转发给
        预览，让圆盘下的扇区能收到这次点击（解决浮层遮挡扇区导致无法再弹出的问题）"""
        if event.button() == Qt.LeftButton:
            from PySide6.QtWidgets import QLineEdit, QPushButton
            child = self.childAt(event.position().toPoint())
            is_input = isinstance(child, (QLineEdit, QPushButton))
            if not is_input and event.position().y() <= 32:
                # 头部区域：开始拖动
                self._dragging = True
                self._drag_offset = (event.globalPosition().toPoint()
                                     - self.geometry().topLeft())
                return
            if not is_input:
                gpos = event.globalPosition()
                # 不自行关闭：由主窗口确认未保存修改后统一关闭并转发
                self.blank_clicked.emit(gpos.x(), gpos.y())
                return
        super().mousePressEvent(event)

    def mouseMoveEvent(self, event):
        if self._dragging and self._drag_offset is not None:
            self.move(event.globalPosition().toPoint() - self._drag_offset)
            self.user_moved = True
            event.accept()
            return
        super().mouseMoveEvent(event)

    def mouseReleaseEvent(self, event):
        if self._dragging:
            self._dragging = False
            self._drag_offset = None
            event.accept()
            return
        super().mouseReleaseEvent(event)
