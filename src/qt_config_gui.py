"""Qt 配置界面 — PySide6 实现（阶段 3 核心版）

三栏布局：方案列表 | 圆盘预览+扇区编辑 | 命令库
功能：方案切换/新增/复制/重命名/删除、圆盘点击选扇区、扇区编辑即时保存、
命令库搜索/点击应用。设置面板在独立对话框（QSettingsDialog）。
"""

import ctypes
import copy
import json
import math
import os

from PySide6.QtCore import (QMimeData, QPointF, QRectF, QSize, Qt, QTimer)
from PySide6.QtGui import (QColor, QCursor, QDrag, QFont, QFontMetrics, QIcon,
                           QKeySequence, QPainter, QPen, QPixmap,
                           QRadialGradient, QShortcut)
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox,
                               QFileDialog, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit,
                               QListWidget, QListWidgetItem, QMainWindow,
                               QMenu, QMessageBox, QPushButton, QScrollArea,
                               QSlider, QSplitter, QStackedWidget, QTreeWidget,
                               QTreeWidgetItem, QVBoxLayout, QWidget)

from src.config_manager import (load_config, save_config, get_profile_names,
                                _default_config, get_preset_commands,
                                set_active_profile, get_auto_start, set_auto_start)
from src.gesture_engine import calc_sector
from src.theme import get_menu_theme, MENU_THEMES
from src.qt_renderer import (INNER, OUTER, EXTENSION, draw_shadow, draw_ring,
                             draw_center)

# ========== 深色主题 ==========

QSS = """
QMainWindow, QWidget { background: #0d1017; color: #e6e9ef; font-size: 13px; }
QLabel { background: transparent; }
QSplitter::handle { background: #232a34; }
QSplitter::handle:hover { background: #38bdf8; }
QListWidget, QTreeWidget { background: #12161d; border: 1px solid #232a34;
                           border-radius: 6px; padding: 4px; }
QListWidget::item { padding: 5px 8px; border-radius: 4px; }
QListWidget::item:hover, QTreeWidget::item:hover { background: #252d39; }
QListWidget::item:selected, QTreeWidget::item:selected { background: #0369a1; }
QTreeWidget::item { padding: 6px 10px; border: none; }
QLineEdit, QComboBox { background: #12161d; border: 1px solid #2c3542;
                       border-radius: 4px; padding: 5px 8px; }
QLineEdit:focus, QComboBox:focus { border-color: #38bdf8; }
QPushButton { background: #161b23; border: 1px solid #2c3542; border-radius: 4px;
              padding: 6px 14px; }
QPushButton:hover { background: #252d39; }
QPushButton:pressed { background: #1f2733; }
QPushButton:disabled { color: #4a5568; }
QPushButton.primary { background: #0369a1; border-color: #0369a1; color: #ffffff; }
QPushButton.primary:hover { background: #0ea5e9; }
QScrollBar:vertical { background: transparent; width: 10px; margin: 0; }
QScrollBar::handle:vertical { background: #2c3542; border-radius: 5px; min-height: 24px; }
QScrollBar::handle:vertical:hover { background: #3b4a63; }
QScrollBar::add-line, QScrollBar::sub-line { height: 0; }
QScrollBar::add-page, QScrollBar::sub-page { background: transparent; }
QStatusBar { background: #0f1319; color: #7b8494; }
QTreeWidget::branch { background: transparent; }
QHeaderView::section { background: #161b23; color: #a8b2bf; border: none; padding: 4px; }
QCheckBox { spacing: 6px; }
QSlider::groove:horizontal { height: 4px; background: #232a34; border-radius: 2px; }
QSlider::handle:horizontal { width: 14px; background: #38bdf8; border-radius: 7px;
                             margin: -5px 0; }
"""


def _blend(c1: str, c2: str, t: float) -> QColor:
    a = QColor(c1)
    b = QColor(c2)
    return QColor(
        int(a.red() + (b.red() - a.red()) * t),
        int(a.green() + (b.green() - a.green()) * t),
        int(a.blue() + (b.blue() - a.blue()) * t),
    )


def _enable_dark_titlebar(win) -> None:
    """让窗口标题栏跟随深色主题（Windows 10 1809+）"""
    try:
        hwnd = int(win.winId())
        while True:
            parent = ctypes.windll.user32.GetParent(hwnd)
            if parent == 0:
                break
            hwnd = parent
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def _layer_key(layer: str) -> str:
    if layer == "outer":
        return "outer_sectors"
    if layer == "extension":
        return "extension_sectors"
    return "sectors"


_COMMAND_MIME = "application/x-cad-gesture-command"


class PresetTree(QTreeWidget):
    """命令库树：节点可拖拽（携带命令 JSON），拖到圆盘直接放置"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.setDragEnabled(True)
        self.setDragDropMode(QAbstractItemView.DragOnly)

    def startDrag(self, supported_actions):
        item = self.currentItem()
        if item is None or item.parent() is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        md = QMimeData()
        md.setData(_COMMAND_MIME, json.dumps(data, ensure_ascii=False).encode("utf-8"))

        drag = QDrag(self)
        drag.setMimeData(md)
        # 拖拽时的半透明预览图标
        label = data.get("label", "")
        pm = QPixmap(max(56, len(label) * 14 + 16), 30)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        p.setPen(QColor("#7dd3fc"))
        p.setBrush(QColor(8, 145, 178, 220))
        p.drawRoundedRect(1, 1, pm.width() - 2, pm.height() - 2, 6, 6)
        p.setPen(QColor("#ffffff"))
        f = QFont("Microsoft YaHei")
        f.setPixelSize(12)
        p.setFont(f)
        p.drawText(pm.rect(), Qt.AlignCenter, label)
        p.end()
        drag.setPixmap(pm)
        drag.setHotSpot(pm.rect().center())
        drag.exec(Qt.CopyAction)


def _layer_name(layer: str) -> str:
    return {"outer": "外层", "extension": "扩展圈"}.get(layer, "内层")


# ========== 圆盘预览 ==========

class QRadialPreview(QWidget):
    """可交互圆盘预览：hover 高亮 + 点击选择扇区"""

    def __init__(self, parent=None):
        super().__init__(parent)
        self.config = None
        self.profile = None
        self.theme = None
        self.selected: tuple | None = None   # (layer, idx)
        self.hovered: tuple | None = None
        self.pending: dict | None = None     # 待放置的命令（右键命令后进入放置模式）
        self.on_select = None                # 回调 (layer, idx)
        self.on_drop = None                  # 回调 (layer, idx, data)
        self.on_clear = None                 # 回调 () 点击圆盘外取消选择
        self.setMouseTracking(True)
        self.setAcceptDrops(True)
        self.setMinimumSize(320, 320)

    def set_data(self, config, profile):
        self.config = config
        self.profile = profile
        self.theme = get_menu_theme(config.get("settings", {}).get("menu_theme", "azure"))
        self.update()

    def update_config(self, config):
        self.config = config
        self.theme = get_menu_theme(config.get("settings", {}).get("menu_theme", "azure"))
        self.update()

    # ---- 几何 ----
    def _geo(self):
        s = min(self.width(), self.height())
        cx, cy = self.width() / 2, self.height() / 2
        scale = s / 560.0  # 基准 560px 圆盘
        return cx, cy, scale

    def _radius(self, key, base):
        s = self.config.get("settings", {})
        return s.get(key, base)

    def _sector_at(self, x, y):
        if self.profile is None:
            return None
        cx, cy, scale = self._geo()
        dx, dy = x - cx, y - cy
        dist = math.hypot(dx, dy) / scale
        dead = self._radius("dead_zone_radius", 30)
        inner = self._radius("ring_radius", 100)
        outer = self._radius("outer_ring_radius", 180)
        ext = self._radius("ext_ring_radius", 240)
        n = self.config.get("settings", {}).get("sector_count", 8)
        if dist < dead:
            return None
        sec = calc_sector(dx, dy, n)
        if dist < inner:
            return ("inner", sec)
        if dist < outer:
            return ("outer", sec)
        if dist < ext:
            return ("extension", sec)
        return None

    # ---- 事件 ----
    def mouseMoveEvent(self, e):
        s = self._sector_at(e.position().x(), e.position().y())
        if s != self.hovered:
            self.hovered = s
            self.update()

    def leaveEvent(self, e):
        self.hovered = None
        self.update()

    # ---- 拖放（命令库拖拽到圆盘） ----
    def dragEnterEvent(self, e):
        if e.mimeData().hasFormat(_COMMAND_MIME):
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragMoveEvent(self, e):
        if e.mimeData().hasFormat(_COMMAND_MIME):
            s = self._sector_at(e.position().x(), e.position().y())
            if s != self.hovered:
                self.hovered = s
                self.update()
            e.acceptProposedAction()
        else:
            e.ignore()

    def dragLeaveEvent(self, e):
        self.hovered = None
        self.update()

    def dropEvent(self, e):
        md = e.mimeData()
        if not md.hasFormat(_COMMAND_MIME):
            e.ignore()
            return
        try:
            data = json.loads(bytes(md.data(_COMMAND_MIME)).decode("utf-8"))
        except Exception:
            data = None
        s = self._sector_at(e.position().x(), e.position().y())
        self.hovered = None
        self.update()
        if s and data and self.on_drop:
            self.on_drop(*s, data)
        e.acceptProposedAction()

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            s = self._sector_at(e.position().x(), e.position().y())
            if s:
                if self.pending is not None:
                    # 放置模式：左键点击扇区放置命令
                    if self.on_drop:
                        self.on_drop(*s, self.pending)
                    self.pending = None
                    self.setCursor(Qt.ArrowCursor)
                    self.update()
                    return
                self.selected = s
                self.update()
                if self.on_select:
                    self.on_select(*s)
            else:
                # 点击圆盘外：取消放置模式或取消选中高亮
                if self.pending is not None:
                    self.pending = None
                    self.setCursor(Qt.ArrowCursor)
                self._clear_selection()
        elif e.button() == Qt.RightButton:
            # 右键取消放置模式
            if self.pending is not None:
                self.pending = None
                self.setCursor(Qt.ArrowCursor)
                self.update()

    def _clear_selection(self):
        """清除选中高亮（点击圆盘外触发）"""
        if self.selected is not None:
            self.selected = None
            self.hovered = None
            self.update()
            if self.on_clear:
                self.on_clear()

    # ---- 绘制 ----
    def paintEvent(self, event):
        if self.profile is None:
            return
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        cx, cy, scale = self._geo()
        t = self.theme
        n = self.config.get("settings", {}).get("sector_count", 8)
        dead = self._radius("dead_zone_radius", 30) * scale
        inner = self._radius("ring_radius", 100) * scale
        outer = self._radius("outer_ring_radius", 180) * scale
        ext = self._radius("ext_ring_radius", 240) * scale

        # 与运行时圆盘共用同一套绘制（视觉完全一致，含投影/光晕/渐变）
        draw_shadow(p, cx, cy, ext)
        draw_ring(p, cx, cy, outer, ext, n,
                  self.profile.get("extension_sectors", {}), t.extension,
                  layer=EXTENSION, sel=self.selected, hov=self.hovered)
        draw_ring(p, cx, cy, inner, outer, n,
                  self.profile.get("outer_sectors", {}), t.outer,
                  layer=OUTER, sel=self.selected, hov=self.hovered)
        draw_ring(p, cx, cy, dead, inner, n,
                  self.profile.get("sectors", {}), t.inner,
                  layer=INNER, sel=self.selected, hov=self.hovered)

        label = self._center_label()
        if self.pending:
            label = f"放置: {self.pending.get('label', '')}"
        draw_center(p, cx, cy, dead, t, min(self.width(), self.height()),
                    label)
        p.end()

    def _center_label(self) -> str:
        if not self.selected:
            return ""
        layer, idx = self.selected
        key = {"inner": "sectors", "outer": "outer_sectors",
               "extension": "extension_sectors"}.get(layer, "sectors")
        return self.profile.get(key, {}).get(str(idx), {}).get("label", "")


# ========== 主配置界面 ==========

class QConfigGUI(QMainWindow):
    """Qt 配置界面主窗口（三栏布局）"""

    def __init__(self, on_save=None, parent=None):
        super().__init__(parent)
        self.on_save = on_save
        self.config = load_config()
        self.current_profile = self.config.get("settings", {}).get("active_profile", "AutoCAD-常用")
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(500)
        self._autosave_timer.timeout.connect(self._do_save)

        self.setWindowTitle("CAD鼠标手势 - 设置")
        icon_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "assets", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1180, 780)
        self.setStyleSheet(QSS)

        # 撤销/重做栈与待放置状态
        self._undo_stack = []
        self._redo_stack = []
        self._pending_preset = None
        self._edit_guard = False
        self._btn_undo = None
        self._btn_redo = None

        self.preview = QRadialPreview()
        self.preview.on_select = self._on_sector_selected
        self.preview.on_drop = self._on_drop
        self.preview.on_clear = self._on_sector_cleared

        # 快捷键：Delete 删除选中命令、Ctrl+Z 撤销、Ctrl+Y 重做、Esc 取消放置
        QShortcut(QKeySequence(Qt.Key_Delete), self,
                  activated=self._delete_selected)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._redo)
        QShortcut(QKeySequence(Qt.Key_Escape), self,
                  activated=self._cancel_pending)

        splitter = QSplitter(Qt.Horizontal)
        splitter.setHandleWidth(5)
        left = self._build_left()
        center = self._build_center()
        right = self._build_right()
        # 边栏宽度限制（QSplitter 拖动会尊重控件的 min/max）
        left.setMinimumWidth(170)
        left.setMaximumWidth(340)
        center.setMinimumWidth(400)
        right.setMinimumWidth(240)
        right.setMaximumWidth(430)
        splitter.addWidget(left)
        splitter.addWidget(center)
        splitter.addWidget(right)
        splitter.setSizes([230, 620, 300])
        splitter.setStretchFactor(0, 0)
        splitter.setStretchFactor(1, 1)
        splitter.setStretchFactor(2, 0)
        self._splitter = splitter
        self.setCentralWidget(splitter)
        self.setMinimumSize(1000, 700)

        self.statusBar().showMessage("就绪")
        self._refresh_profiles()
        self._load_profile(self.current_profile)
        self._populate_presets()

    def showEvent(self, e):
        super().showEvent(e)
        _enable_dark_titlebar(self)

    # ========== 左栏：方案列表 ==========

    def _build_left(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        title = QLabel("配置方案")
        title.setStyleSheet("font-size: 16px; font-weight: bold;")
        v.addWidget(title)
        sub = QLabel("选择一个方案进行编辑")
        sub.setStyleSheet("color: #7b8494; font-size: 11px;")
        v.addWidget(sub)

        self.profile_list = QListWidget()
        # 去掉选中时的焦点虚线框（整行块选中，无虚线包裹）
        self.profile_list.setFocusPolicy(Qt.NoFocus)
        self.profile_list.itemClicked.connect(self._on_profile_clicked)
        v.addWidget(self.profile_list, 1)

        row1 = QHBoxLayout()
        btn_add = QPushButton("＋ 新增")
        btn_add.clicked.connect(self._add_profile)
        btn_copy = QPushButton("复制")
        btn_copy.clicked.connect(self._copy_profile)
        row1.addWidget(btn_add)
        row1.addWidget(btn_copy)
        v.addLayout(row1)

        row2 = QHBoxLayout()
        btn_rename = QPushButton("重命名")
        btn_rename.clicked.connect(self._rename_profile)
        btn_del = QPushButton("删除")
        btn_del.clicked.connect(self._delete_profile)
        row2.addWidget(btn_rename)
        row2.addWidget(btn_del)
        v.addLayout(row2)

        btn_settings = QPushButton("设置")
        btn_settings.setProperty("class", "primary")
        btn_settings.clicked.connect(self._show_settings)
        v.addWidget(btn_settings)
        return panel

    def _on_profile_clicked(self, item):
        name = item.data(Qt.UserRole)
        if name:
            self._load_profile(name)

    # ========== 中栏：预览 + 编辑 ==========

    def _build_center(self) -> QWidget:
        self._center_stack = QStackedWidget()

        # ---- 页面 0：圆盘编辑 ----
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(20, 14, 20, 14)
        v.setSpacing(10)

        # 顶栏
        top = QHBoxLayout()
        self.badge = QLabel("")
        self.badge.setStyleSheet("font-size: 15px; font-weight: bold;")
        self.target_badge = QLabel("")
        self.target_badge.setStyleSheet("color: #7b8494;")
        top.addWidget(self.badge)
        top.addWidget(self.target_badge)
        top.addStretch(1)
        self._btn_undo = QPushButton("↩ 撤销")
        self._btn_undo.setEnabled(False)
        self._btn_undo.setToolTip("撤销上一步操作 (Ctrl+Z)")
        self._btn_undo.clicked.connect(self._undo)
        self._btn_redo = QPushButton("↪ 重做")
        self._btn_redo.setEnabled(False)
        self._btn_redo.setToolTip("重做被撤销的操作 (Ctrl+Y)")
        self._btn_redo.clicked.connect(self._redo)
        top.addWidget(self._btn_undo)
        top.addWidget(self._btn_redo)
        v.addLayout(top)

        # 预览
        v.addWidget(self.preview, 1)

        # 扇区编辑
        card = QWidget()
        card.setStyleSheet("QWidget { background: #161b23; border-radius: 10px; }")
        card_l = QVBoxLayout(card)
        card_l.setContentsMargins(16, 14, 16, 14)
        head = QHBoxLayout()
        h = QLabel("扇区编辑")
        h.setStyleSheet("color: #38bdf8; font-weight: bold;")
        self.sel_info = QLabel("点击圆盘选择扇区")
        self.sel_info.setStyleSheet("color: #7b8494;")
        head.addWidget(h)
        head.addStretch(1)
        head.addWidget(self.sel_info)
        card_l.addLayout(head)

        form = QFormLayout()
        form.setSpacing(8)
        self.layer_label = QLabel("未选择")
        self.layer_label.setStyleSheet("color: #38bdf8; font-weight: bold;")
        form.addRow("所在层", self.layer_label)
        self.label_entry = QLineEdit()
        self.key_entry = QLineEdit()
        self.desc_entry = QLineEdit()
        self.label_entry.textChanged.connect(self._on_detail_change)
        self.key_entry.textChanged.connect(self._on_detail_change)
        self.desc_entry.textChanged.connect(self._on_detail_change)
        form.addRow("显示名称", self.label_entry)
        form.addRow("快捷键", self.key_entry)
        form.addRow("CAD 命令", self.desc_entry)
        card_l.addLayout(form)

        btn_row = QHBoxLayout()
        btn_clear = QPushButton("清空")
        btn_clear.clicked.connect(self._clear_sector)
        btn_copyto = QPushButton("复制到…")
        btn_copyto.clicked.connect(self._copy_sector_to)
        btn_row.addWidget(btn_clear)
        btn_row.addWidget(btn_copyto)
        btn_row.addStretch(1)
        card_l.addLayout(btn_row)
        v.addWidget(card)
        self._center_stack.addWidget(panel)

        # ---- 页面 1：全局设置（内嵌，不新开窗口） ----
        self._settings_panel = QSettingsPanel(self.config, self)
        self._settings_panel.on_back = self._show_editor
        self._settings_panel.on_saved = self._on_settings_saved
        self._settings_panel.on_import = self._import_profile
        self._settings_panel.on_export = self._export_profile
        self._center_stack.addWidget(self._settings_panel)
        self._center_stack.setCurrentIndex(0)
        return self._center_stack

    def _show_settings(self):
        self._settings_panel.refresh(self.config)
        self._center_stack.setCurrentIndex(1)
        self.statusBar().showMessage("全局设置：修改即时保存")

    def _show_editor(self):
        self._center_stack.setCurrentIndex(0)
        self.preview.update_config(self.config)
        self.statusBar().showMessage("圆盘编辑")

    def _on_settings_saved(self):
        self.preview.update_config(self.config)
        self._populate_presets(self.search_entry.text())

    # ========== 右栏：命令库 ==========

    def _build_right(self) -> QWidget:
        panel = QWidget()
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel("命令库")
        t.setStyleSheet("font-size: 15px; font-weight: 600;")
        head.addWidget(t)
        head.addStretch(1)
        hint = QLabel("拖拽到圆盘放置")
        hint.setStyleSheet("color: #7b8494; font-size: 11px;")
        head.addWidget(hint)
        v.addLayout(head)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("搜索命令…  (Ctrl+F)")
        self.search_entry.textChanged.connect(self._on_search)
        v.addWidget(self.search_entry)

        self.preset_tree = PresetTree()
        self.preset_tree.setHeaderHidden(True)
        self.preset_tree.setColumnCount(2)
        self.preset_tree.setIndentation(12)
        # 隐藏左侧展开箭头列（branch），避免选中时左边缘留下背景分块；
        # 展开/折叠改为点击分类标题，标题前用 ▸/▾ 指示状态
        self.preset_tree.setRootIsDecorated(False)
        self.preset_tree.setAnimated(True)      # 展开/折叠缓动动画
        self.preset_tree.setUniformRowHeights(False)  # 动画需要非统一行高
        # 去掉选中时的焦点虚线框（整行块选中，无虚线包裹）
        self.preset_tree.setFocusPolicy(Qt.NoFocus)
        # 列宽：名称列自适应拉伸，快捷键列按内容
        self.preset_tree.header().setStretchLastSection(False)
        self.preset_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.preset_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.preset_tree.itemClicked.connect(self._on_preset_clicked)
        self.preset_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preset_tree.customContextMenuRequested.connect(self._on_preset_context)
        v.addWidget(self.preset_tree, 1)
        return panel

    def _on_search(self, text):
        self._populate_presets(text)

    def _on_preset_clicked(self, item, col):
        if item.parent() is None:
            # 分类标题：点击切换展开/折叠，并更新 ▸/▾ 前缀
            item.setExpanded(not item.isExpanded())
            text = item.text(0)
            prefix = "▾ " if item.isExpanded() else "▸ "
            item.setText(0, prefix + text[2:])
            return
        info = item.data(0, Qt.UserRole)
        if info and self._selected_sector:
            self._apply_preset(info)
        else:
            self.statusBar().showMessage("请先在圆盘上点击选择一个扇区")

    def _on_preset_context(self, pos):
        """命令库右键菜单：添加到圆盘扇区"""
        item = self.preset_tree.itemAt(pos)
        if item is None or item.parent() is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        menu = QMenu(self)
        act = menu.addAction("拖拽或点击放置到圆盘扇区")
        act.setEnabled(False)
        menu.addSeparator()
        act2 = menu.addAction("放置到圆盘扇区…")
        act2.triggered.connect(lambda: self._start_pending_place(data))
        menu.exec(self.preset_tree.viewport().mapToGlobal(pos))

    def _start_pending_place(self, data):
        """进入放置模式：圆盘高亮提示，左键点击扇区放置命令"""
        self._pending_preset = data
        self.preview.pending = data
        self.preview.setCursor(Qt.CrossCursor)
        self.statusBar().showMessage(
            f"点击圆盘扇区放置「{data.get('label', '')}」，右键 / Esc 取消")
        self.preview.update()

    def _cancel_pending(self):
        if self._pending_preset:
            self._pending_preset = None
            self.preview.pending = None
            self.preview.setCursor(Qt.ArrowCursor)
            self.preview.update()
            self.statusBar().showMessage("已取消放置")

    def _on_drop(self, layer, idx, data):
        """放置模式：命令放到指定扇区（添加/替换）"""
        self._push_undo()
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.setdefault(_layer_key(layer), {})
        sectors[str(idx)] = data.copy()
        self._pending_preset = None
        self._selected_sector = (layer, idx)
        self.preview.selected = (layer, idx)
        self._edit_guard = False
        self._on_sector_selected(layer, idx)
        self.statusBar().showMessage(
            f"已将「{data.get('label', '')}」放置到{_layer_name(layer)}扇区 {idx}")
        self._autosave_timer.start()

    def _delete_selected(self):
        """Delete 键删除当前选中扇区的命令"""
        if not getattr(self, "_selected_sector", None):
            self.statusBar().showMessage("请先在圆盘上选择一个扇区")
            return
        self._push_undo()
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.get(_layer_key(layer), {})
        if str(idx) in sectors:
            del sectors[str(idx)]
        self._clear_form()
        self.preview.update()
        self.statusBar().showMessage(f"已删除{_layer_name(layer)}扇区 {idx} 的命令")
        self._autosave_timer.start()

    # ========== 数据加载 ==========

    def _refresh_profiles(self):
        self.profile_list.clear()
        profiles = self.config.get("profiles", {})
        groups = {
            "AutoCAD": [n for n, p in profiles.items() if p.get("target") == "autocad"],
            "中望CAD": [n for n, p in profiles.items() if p.get("target") == "zwcad"],
            "其他": [n for n, p in profiles.items()
                    if p.get("target") not in ("autocad", "zwcad")],
        }
        for gname, names in groups.items():
            if not names:
                continue
            head = QListWidgetItem(gname)
            head.setFlags(Qt.NoItemFlags)
            head.setForeground(QColor("#38bdf8"))
            f = head.font()
            f.setBold(True)
            head.setFont(f)
            self.profile_list.addItem(head)
            for name in names:
                item = QListWidgetItem(profiles[name].get("name", name))
                item.setData(Qt.UserRole, name)
                self.profile_list.addItem(item)
        self._highlight_profile()

    def _highlight_profile(self):
        for i in range(self.profile_list.count()):
            it = self.profile_list.item(i)
            if it.data(Qt.UserRole) == self.current_profile:
                self.profile_list.setCurrentItem(it)

    def _load_profile(self, name):
        self.current_profile = name
        self._selected_sector = None
        self.preview.selected = None
        self.preview.hovered = None
        profile = self.config.get("profiles", {}).get(name, {})
        self.preview.set_data(self.config, profile)

        target = profile.get("target", "autocad")
        display = profile.get("name", name)
        self.badge.setText(display[:12] + "…" if len(display) > 12 else display)
        self.target_badge.setText(
            {"autocad": "AutoCAD", "zwcad": "中望CAD"}.get(target, target.upper()))

        # 命令库随 target 切换
        self._preset_commands = get_preset_commands(target)
        self._populate_presets(self.search_entry.text())
        self._highlight_profile()
        self._clear_form()

    def _clear_form(self):
        self._edit_guard = False
        self.layer_label.setText("未选择")
        self.sel_info.setText("点击圆盘选择扇区")
        self._block_form(True)
        self.label_entry.clear()
        self.key_entry.clear()
        self.desc_entry.clear()
        self._block_form(False)

    def _block_form(self, on):
        for w in (self.label_entry, self.key_entry, self.desc_entry):
            w.blockSignals(on)

    # ========== 扇区编辑 ==========

    def _on_sector_selected(self, layer, idx):
        self._edit_guard = False
        self._selected_sector = (layer, idx)
        self.sel_info.setText(f"正在编辑: {_layer_name(layer)}扇区 {idx}")
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        cfg = profile.get(_layer_key(layer), {}).get(str(idx), {})
        self.layer_label.setText(f"{_layer_name(layer)} · 扇区 {idx}")
        self._block_form(True)
        self.label_entry.setText(cfg.get("label", ""))
        self.key_entry.setText(cfg.get("key", ""))
        self.desc_entry.setText(cfg.get("description", ""))
        self._block_form(False)

    def _on_sector_cleared(self):
        """点击圆盘外取消选择：清空扇区编辑表单与选中状态"""
        self._selected_sector = None
        self._clear_form()
        self.statusBar().showMessage("已取消选择")

    def _on_detail_change(self, text):
        if not getattr(self, "_selected_sector", None):
            return
        if not self._edit_guard:
            self._push_undo()
            self._edit_guard = True
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.setdefault(_layer_key(layer), {})
        sectors[str(idx)] = {
            "label": self.label_entry.text().strip(),
            "key": self.key_entry.text().strip(),
            "description": self.desc_entry.text().strip(),
        }
        self.statusBar().showMessage("● 保存中…")
        self._autosave_timer.start()

    def _clear_sector(self):
        if not getattr(self, "_selected_sector", None):
            return
        self._push_undo()
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.get(_layer_key(layer), {})
        if str(idx) in sectors:
            del sectors[str(idx)]
        self._clear_form()
        self.preview.update()
        self._autosave_timer.start()

    def _copy_sector_to(self):
        if not getattr(self, "_selected_sector", None):
            return
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        cfg = profile.get(_layer_key(layer), {}).get(str(idx), {})
        if not cfg:
            return
        layers = [("inner", "内层"), ("outer", "外层"), ("extension", "扩展圈")]
        layer_names = [n for _, n in layers]
        choice, ok = QInputDialog.getItem(self, "复制到…", "选择目标层:", layer_names, 0, False)
        if not ok:
            return
        target_layer = next(k for k, n in layers if n == choice)
        idx_text, ok = QInputDialog.getText(self, "复制到…", "目标扇区编号:",
                                            text=str(idx))
        if not ok:
            return
        try:
            target_idx = int(idx_text)
        except ValueError:
            QMessageBox.warning(self, "错误", "扇区编号必须是数字")
            return
        n = self.config.get("settings", {}).get("sector_count", 8)
        if not (0 <= target_idx < n):
            QMessageBox.warning(self, "错误", f"扇区编号需在 0~{n - 1} 之间")
            return
        self._push_undo()
        sectors = profile.setdefault(_layer_key(target_layer), {})
        sectors[str(target_idx)] = cfg.copy()
        self.preview.update()
        self.statusBar().showMessage(f"已复制到{_layer_name(target_layer)}扇区 {target_idx}")
        self._autosave_timer.start()

    def _apply_preset(self, info):
        self._push_undo()
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.setdefault(_layer_key(layer), {})
        sectors[str(idx)] = info.copy()
        self._edit_guard = False
        self._block_form(True)
        self.label_entry.setText(info.get("label", ""))
        self.key_entry.setText(info.get("key", ""))
        self.desc_entry.setText(info.get("description", ""))
        self._block_form(False)
        self.preview.update()
        self.statusBar().showMessage(f"已将「{info.get('label', '')}」应用到扇区 {idx}")
        self._autosave_timer.start()

    # ========== 命令库 ==========

    def _populate_presets(self, filter_text=""):
        self.preset_tree.clear()
        if not getattr(self, "_preset_commands", None):
            return
        filter_text = filter_text.strip().lower()
        is_searching = bool(filter_text)
        for category, commands in self._preset_commands.items():
            if filter_text:
                filtered = {k: v for k, v in commands.items()
                            if filter_text in k.lower()
                            or filter_text in v.get("label", "").lower()
                            or filter_text in v.get("key", "").lower()
                            or filter_text in v.get("description", "").lower()}
                if not filtered:
                    continue
            else:
                filtered = commands
            # 分类标题：低调小字，弱化层级；▸/▾ 指示展开状态
            cat = QTreeWidgetItem([f"▸ {category}"])
            f = cat.font(0)
            f.setBold(True)
            f.setPixelSize(11)
            cat.setFont(0, f)
            cat.setForeground(0, QColor("#8a93a3"))
            cat.setSizeHint(0, QSize(0, 26))
            # 搜索时默认全部展开显示结果；非搜索时默认展开便于浏览
            cat.setExpanded(True)
            cat.setText(0, f"▾ {category}")
            cat.setFirstColumnSpanned(True)
            for name, data in filtered.items():
                label = data.get("label", name)
                key = data.get("key", "")
                child = QTreeWidgetItem([label, key])
                child.setData(0, Qt.UserRole, data)
                child.setSizeHint(0, QSize(0, 30))
                # 显示名称左对齐，快捷键右对齐（灰色弱化）
                child.setForeground(0, QColor("#e6e9ef"))
                child.setTextAlignment(0, Qt.AlignLeft | Qt.AlignVCenter)
                child.setForeground(1, QColor("#7b8494"))
                child.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                child.setToolTip(
                    0, f"命令: {label}\n快捷键: {key}\nCAD 命令: {data.get('description', '')}\n\n"
                       f"拖拽到圆盘扇区即可新增/更换，也可左键应用到选中扇区")
                cat.addChild(child)
            self.preset_tree.addTopLevelItem(cat)

    # ========== 方案操作 ==========

    def _add_profile(self):
        name, ok = QInputDialog.getText(self, "新增配置方案", "请输入方案名称:")
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.config.get("profiles", {}):
            QMessageBox.warning(self, "错误", f"方案「{name}」已存在")
            return
        target, ok = QInputDialog.getItem(self, "选择目标软件",
                                          "适用的 CAD 软件:",
                                          ["AutoCAD", "中望CAD"], 0, False)
        if not ok:
            return
        tgt = "autocad" if target == "AutoCAD" else "zwcad"
        self._push_undo()
        n = self.config.get("settings", {}).get("sector_count", 8)
        sectors = {str(i): {"label": "", "key": "", "description": ""} for i in range(n)}
        self.config.setdefault("profiles", {})[name] = {
            "name": name, "target": tgt, "sectors": sectors,
            "outer_sectors": {}, "extension_sectors": {},
        }
        self._refresh_profiles()
        self._load_profile(name)
        self._autosave_timer.start()

    def _copy_profile(self):
        src = self.config.get("profiles", {}).get(self.current_profile, {})
        new_name, ok = QInputDialog.getText(self, "复制配置方案", "请输入新方案名称:",
                                            text=f"{self.current_profile}-副本")
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name in self.config.get("profiles", {}):
            QMessageBox.warning(self, "错误", f"方案「{new_name}」已存在")
            return
        new = copy.deepcopy(src)
        new["name"] = new_name
        self._push_undo()
        self.config["profiles"][new_name] = new
        self._refresh_profiles()
        self._load_profile(new_name)
        self._autosave_timer.start()

    def _rename_profile(self):
        new_name, ok = QInputDialog.getText(self, "重命名配置方案", "请输入新名称:",
                                            text=self.current_profile)
        if not ok or not new_name.strip() or new_name.strip() == self.current_profile:
            return
        new_name = new_name.strip()
        if new_name in self.config.get("profiles", {}):
            QMessageBox.warning(self, "错误", f"方案「{new_name}」已存在")
            return
        self._push_undo()
        profile = self.config["profiles"].pop(self.current_profile)
        profile["name"] = new_name
        self.config["profiles"][new_name] = profile
        if self.config.get("settings", {}).get("active_profile") == self.current_profile:
            self.config["settings"]["active_profile"] = new_name
        self.current_profile = new_name
        self._refresh_profiles()
        self._autosave_timer.start()

    def _export_profile(self):
        """导出当前方案为 JSON 文件"""
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        if not profile:
            QMessageBox.warning(self, "提示", "没有可导出的配置")
            return
        path, _ = QFileDialog.getSaveFileName(
            self, "导出方案", f"{self.current_profile}.json", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
            self.statusBar().showMessage(f"已导出到: {path}")
        except Exception as e:
            QMessageBox.warning(self, "错误", f"导出失败: {e}")

    def _import_profile(self):
        """从 JSON 文件导入方案（合并到当前方案）"""
        path, _ = QFileDialog.getOpenFileName(
            self, "导入方案", "", "JSON 文件 (*.json)")
        if not path:
            return
        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except Exception as e:
            QMessageBox.warning(self, "错误", f"导入失败（无法读取文件）: {e}")
            return
        if not isinstance(data, dict):
            QMessageBox.warning(self, "错误", "导入失败：文件格式无效（应为对象）")
            return
        # 先校验结构，再合并：避免坏数据污染内存配置后被保存
        for key in ("sectors", "outer_sectors", "extension_sectors"):
            if key in data:
                if not isinstance(data[key], dict):
                    QMessageBox.warning(self, "错误", f"导入失败：{key} 格式无效")
                    return
                for v in data[key].values():
                    if not isinstance(v, dict):
                        QMessageBox.warning(self, "错误",
                                            f"导入失败：{key} 中存在无效数据")
                        return
        self._push_undo()
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        for key in ("sectors", "outer_sectors", "extension_sectors"):
            if key in data:
                profile[key] = data[key]
        self.preview.update()
        self._on_sector_selected(*self._selected_sector) if self._selected_sector else None
        self.statusBar().showMessage(f"已从 {path} 导入配置")
        self._autosave_timer.start()

    def _delete_profile(self):
        if len(self.config.get("profiles", {})) <= 1:
            QMessageBox.warning(self, "错误", "至少保留一个配置方案")
            return
        if QMessageBox.question(self, "确认",
                                f"确定要删除「{self.current_profile}」吗?") != QMessageBox.Yes:
            return
        self._push_undo()
        del self.config["profiles"][self.current_profile]
        remaining = list(self.config.get("profiles", {}).keys())
        self.config["settings"]["active_profile"] = remaining[0]
        self._refresh_profiles()
        self._load_profile(remaining[0])
        self._autosave_timer.start()

    # ========== 撤销/重做 ==========

    def _push_undo(self):
        if len(self._undo_stack) >= 50:
            self._undo_stack.pop(0)
        self._undo_stack.append(copy.deepcopy(self.config))
        self._redo_stack.clear()
        self._update_undo_btns()

    def _undo(self):
        if not self._undo_stack:
            return
        before = self._undo_stack.pop()
        self._redo_stack.append(copy.deepcopy(self.config))
        self._restore_config(before)
        self._update_undo_btns()
        self.statusBar().showMessage("已撤销")

    def _redo(self):
        if not self._redo_stack:
            return
        after = self._redo_stack.pop()
        self._undo_stack.append(copy.deepcopy(self.config))
        self._restore_config(after)
        self._update_undo_btns()
        self.statusBar().showMessage("已重做")

    def _restore_config(self, cfg):
        """恢复配置并刷新整个界面"""
        self.config = cfg
        self.current_profile = self.config.get("settings", {}).get(
            "active_profile", "AutoCAD-常用")
        self._selected_sector = None
        self._edit_guard = False
        self._pending_preset = None
        self.preview.pending = None
        self.preview.selected = None
        self.preview.setCursor(Qt.ArrowCursor)
        self._refresh_profiles()
        self._load_profile(self.current_profile)
        self._populate_presets(self.search_entry.text())
        self.preview.update_config(self.config)
        self._do_save()

    def _update_undo_btns(self):
        if self._btn_undo is not None:
            self._btn_undo.setEnabled(bool(self._undo_stack))
        if self._btn_redo is not None:
            self._btn_redo.setEnabled(bool(self._redo_stack))

    # ========== 保存 ==========

    def _do_save(self):
        self.config["settings"]["active_profile"] = self.current_profile
        ok = save_config(self.config)
        self.statusBar().showMessage("✓ 已保存" if ok else "保存失败")
        if ok and self.on_save:
            self.on_save()

    def closeEvent(self, e):
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self._do_save()
        if self.on_save:
            self.on_save()
        super().closeEvent(e)


# ========== 设置对话框 ==========

class QSettingsPanel(QWidget):
    """全局设置面板（内嵌到配置界面中间区域，不新开窗口）"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.on_back = None
        self.on_saved = None
        self.on_import = None
        self.on_export = None
        self.setStyleSheet(QSS)

        v = QVBoxLayout(self)
        v.setContentsMargins(20, 14, 20, 14)
        v.setSpacing(10)

        top = QHBoxLayout()
        btn_back = QPushButton("← 返回圆盘编辑")
        btn_back.clicked.connect(self._back)
        top.addWidget(btn_back)
        top.addStretch(1)
        v.addLayout(top)

        scroll = QScrollArea()
        scroll.setWidgetResizable(True)
        scroll.setFrameShape(QScrollArea.NoFrame)
        inner = QWidget()
        form = QVBoxLayout(inner)
        form.setSpacing(6)
        form.setContentsMargins(4, 4, 4, 4)

        # 常规
        form.addWidget(self._title("常规"))
        self.chk_open = QCheckBox("启动时打开此界面")
        self.chk_open.toggled.connect(lambda b: self._set("open_config_on_start", b))
        form.addWidget(self.chk_open)
        self.chk_auto = QCheckBox("根据 CAD 窗口自动切换")
        self.chk_auto.toggled.connect(lambda b: self._set("auto_switch_profile", b))
        form.addWidget(self.chk_auto)
        self.chk_startup = QCheckBox("开机自启")
        self.chk_startup.toggled.connect(self._on_startup)
        form.addWidget(self.chk_startup)

        # 外观
        form.addWidget(self._title("圆盘外观"))
        self.theme_combo = QComboBox()
        for th in MENU_THEMES.values():
            self.theme_combo.addItem(th.label, th.name)
        self.theme_combo.currentIndexChanged.connect(
            lambda: self._set("menu_theme", self.theme_combo.currentData()))
        form.addWidget(self.theme_combo)

        # 触发灵敏度
        form.addWidget(self._title("触发灵敏度"))
        self._hold_slider, self._hold_label = self._slider(
            "长按延迟", "hold_threshold_ms", 60, 200, "ms")
        form.addWidget(self._hold_label)
        form.addWidget(self._hold_slider)
        self._trig_slider, self._trig_label = self._slider(
            "触发距离", "trigger_distance", 8, 40, "px")
        form.addWidget(self._trig_label)
        form.addWidget(self._trig_slider)

        # 圆盘尺寸
        form.addWidget(self._title("圆盘尺寸（高级）"))
        self._size_sliders = {}
        for key, text, lo, hi, unit in (("dead_zone_radius", "中心死区半径", 10, 60, ""),
                                        ("ring_radius", "内层半径", 60, 160, ""),
                                        ("outer_ring_radius", "外层半径", 120, 260, ""),
                                        ("ext_ring_radius", "扩展圈半径", 180, 360, ""),
                                        ("sector_count", "扇区数量", 4, 16, "")):
            sl, lb = self._slider(text, key, lo, hi, unit)
            self._size_sliders[key] = sl
            form.addWidget(lb)
            form.addWidget(sl)

        btn_row = QHBoxLayout()
        btn_import = QPushButton("导入方案")
        btn_import.clicked.connect(lambda: self.on_import() if self.on_import else None)
        btn_export = QPushButton("导出方案")
        btn_export.clicked.connect(lambda: self.on_export() if self.on_export else None)
        btn_row.addWidget(btn_import)
        btn_row.addWidget(btn_export)
        btn_row.addStretch(1)
        form.addLayout(btn_row)

        btn_reset = QPushButton("恢复默认")
        btn_reset.clicked.connect(self._reset_defaults)
        form.addWidget(btn_reset)

        scroll.setWidget(inner)
        v.addWidget(scroll, 1)

    def _back(self):
        if self.on_back:
            self.on_back()

    def _title(self, text):
        l = QLabel(text)
        l.setStyleSheet("color: #38bdf8; font-weight: bold; margin-top: 8px;")
        return l

    def _slider(self, text, key, lo, hi, unit):
        val = int(self.config.get("settings", {}).get(key, lo))
        lb = QLabel(f"{text}: {val}{unit}")
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        sl.valueChanged.connect(lambda v, t=text, l=lb, u=unit: l.setText(f"{t}: {v}{u}"))
        sl.sliderReleased.connect(self._save)  # 拖动结束才保存，避免高频写盘
        return sl, lb

    def refresh(self, config):
        """从配置刷新控件显示（进入设置面板时调用）"""
        self.config = config
        s = config.get("settings", {})
        for w in (self.chk_open, self.chk_auto, self.chk_startup,
                  self.theme_combo):
            w.blockSignals(True)
        self.chk_open.setChecked(bool(s.get("open_config_on_start", False)))
        self.chk_auto.setChecked(bool(s.get("auto_switch_profile", True)))
        self.chk_startup.setChecked(get_auto_start())
        idx = self.theme_combo.findData(s.get("menu_theme", "azure"))
        if idx >= 0:
            self.theme_combo.setCurrentIndex(idx)
        for w in (self.chk_open, self.chk_auto, self.chk_startup,
                  self.theme_combo):
            w.blockSignals(False)

    def _set(self, key, value):
        self.config.setdefault("settings", {})[key] = value
        self._save()

    def _on_startup(self, checked):
        set_auto_start(checked)

    def _save(self):
        ok = save_config(self.config)
        if ok and self.on_saved:
            self.on_saved()

    def _reset_defaults(self):
        if QMessageBox.question(self, "确认",
                                "确定要重置所有配置为默认值吗?") != QMessageBox.Yes:
            return
        self.config = _default_config()
        self.refresh(self.config)
        self._save()
        QMessageBox.information(self, "提示", "已重置为默认配置")


def open_config_gui(on_save=None, master=None):
    """打开配置界面（Qt 版，返回窗口实例以便保持引用）"""
    win = QConfigGUI(on_save=on_save)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
