"""图标选择对话框 — 内置矢量图标 + 已上传的本地图片

交互：点击图标先选中（高亮），点"确定"或双击确认；"从文件选择…"
导入本地图片后立即选中并关闭。结果写入 self.selected_ref。
"""

from PySide6.QtCore import Qt, Signal
from PySide6.QtGui import QIcon
from PySide6.QtWidgets import (QDialog, QFileDialog, QGridLayout, QHBoxLayout,
                               QLabel, QLineEdit, QMessageBox, QPushButton,
                               QScrollArea, QVBoxLayout, QWidget)

from src.i18n import T
from src.icon_library import (ICON_IDS, ICON_ZH_NAMES, import_custom_icon,
                              list_custom_icons, resolve_icon)
from src.theme import get_ui

_COLS = 6


class _TileButton(QPushButton):
    """带双击信号的图标瓦片按钮（双击=选中并确认）"""

    doubleClicked = Signal()

    def mouseDoubleClickEvent(self, e):
        self.doubleClicked.emit()
        e.accept()
        super().mouseDoubleClickEvent(e)


class IconPickerDialog(QDialog):
    """图标选择器：网格缩略 + 搜索 + 内置/已上传分区 + 从文件导入"""

    def __init__(self, current_ref: str = "", parent=None):
        super().__init__(parent)
        self.setWindowTitle(T("选择图标"))
        self.setModal(True)
        # 浮层本身总在最前，对话框也要置顶才不会被它盖住
        self.setWindowFlags(self.windowFlags() | Qt.WindowStaysOnTopHint)
        self.resize(560, 500)
        self.selected_ref = None
        self._current_ref = current_ref or ""
        self._selected = current_ref or None   # 当前点选的图标（未确认）
        self._tiles = []                       # (ref, QPushButton)
        self._build()

    def _build(self):
        lay = QVBoxLayout(self)

        self.search = QLineEdit()
        self.search.setPlaceholderText(T("搜索图标…"))
        self.search.textChanged.connect(self._reload)
        lay.addWidget(self.search)

        self.grid_host = QWidget()
        self.grid = QGridLayout(self.grid_host)
        self.grid.setSpacing(6)
        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setWidget(self.grid_host)
        lay.addWidget(scroll, 1)

        btns = QHBoxLayout()
        self.btn_file = QPushButton(T("从文件选择…"))
        self.btn_file.setToolTip(
            T("选择本地图片（png/svg/ico），自动复制到应用数据目录"))
        self.btn_file.clicked.connect(self._pick_from_file)
        self.btn_ok = QPushButton(T("确定"))
        self.btn_ok.setProperty("class", "primary")
        self.btn_ok.setFocusPolicy(Qt.NoFocus)
        self.btn_ok.clicked.connect(self._confirm)
        self.btn_cancel = QPushButton(T("取消"))
        self.btn_cancel.setFocusPolicy(Qt.NoFocus)
        self.btn_cancel.clicked.connect(self.reject)
        btns.addWidget(self.btn_file)
        btns.addStretch(1)
        btns.addWidget(self.btn_ok)
        btns.addWidget(self.btn_cancel)
        lay.addLayout(btns)

        self._reload("")
        self._sync_ok_state()
        self.search.setFocus()

    def _items(self):
        """[(ref, 显示名, 是否自定义图片)]"""
        items = [("preset:" + i, ICON_ZH_NAMES.get(i, i), False)
                 for i in ICON_IDS]
        items += [(ref, name, True) for ref, name in list_custom_icons()]
        return items

    def _add_header(self, text, row):
        h = QLabel(text)
        h.setObjectName("iconSectionTitle")
        self.grid.addWidget(h, row, 0, 1, _COLS)
        return row + 1

    def _add_buttons(self, refs, row, ui):
        for idx, (ref, name) in enumerate(refs):
            btn = _TileButton()
            btn.setObjectName("iconTile")
            btn.setFixedSize(56, 56)
            btn.setToolTip(name)
            btn.setCheckable(True)
            btn.setFocusPolicy(Qt.NoFocus)
            btn.setChecked(ref == self._selected)
            pm = resolve_icon(ref, ui.text, 32)
            if pm is not None:
                btn.setIcon(QIcon(pm))
                btn.setIconSize(pm.size())
            btn.clicked.connect(lambda _=False, r=ref: self._select(r))
            btn.doubleClicked.connect(lambda r=ref: self._accept_ref(r))
            self._tiles.append((ref, btn))
            self.grid.addWidget(btn, row + idx // _COLS, idx % _COLS)
        return row + (len(refs) + _COLS - 1) // _COLS

    def _reload(self, text: str):
        """按搜索词重建图标网格（内置矢量 + 已上传图片分区）"""
        while self.grid.count():
            item = self.grid.takeAt(0)
            w = item.widget()
            if w is not None:
                w.deleteLater()
        self._tiles = []
        text = (text or "").strip().lower()
        ui = get_ui()
        items = ([it for it in self._items()
                  if text in it[1].lower()
                  or (not it[2] and text in it[0].lower())]
                 if text else self._items())
        presets = [(it[0], it[1]) for it in items if not it[2]]
        customs = [(it[0], it[1]) for it in items if it[2]]

        row = 0
        if presets:
            row = self._add_header(T("内置图标"), row)
            row = self._add_buttons(presets, row, ui)
        if customs:
            row = self._add_header(T("已上传图片"), row)
            row = self._add_buttons(customs, row, ui)
        if not items:
            self.grid.addWidget(QLabel(T("无匹配图标")), 0, 0)

    def _select(self, ref: str):
        """点选图标：只高亮选中，不立即关闭"""
        self._selected = ref
        for r, btn in self._tiles:
            btn.setChecked(r == ref)
        self._sync_ok_state()

    def _confirm(self):
        if self._selected:
            self.selected_ref = self._selected
            self.accept()

    def _accept_ref(self, ref: str):
        self._selected = ref
        self.selected_ref = ref
        self.accept()

    def _sync_ok_state(self):
        self.btn_ok.setEnabled(self._selected is not None)

    def _pick_from_file(self):
        path, _ = QFileDialog.getOpenFileName(
            self, T("选择图片文件"), "",
            T("图片文件 (*.png *.jpg *.jpeg *.bmp *.ico *.svg)"))
        if not path:
            return
        try:
            ref = import_custom_icon(path)
        except Exception as e:
            QMessageBox.warning(
                self, T("错误"), T("无法使用该图片: {msg}").format(msg=e))
            return
        self.selected_ref = ref
        self.accept()