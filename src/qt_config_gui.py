"""Qt 配置界面 — 导航式布局（PySide6）

结构：左侧导航栏 + 上下文区（方案列表 / 设置锚点），主区 QStackedWidget 两页：
  - 圆盘编辑页：大圆盘预览 + 可折叠命令库；点击扇区弹出就地编辑器
  - 设置页：QSettingsPanel（主题色板 / 实时预览）
功能：方案增删改、命令库拖放/搜索/放置模式、撤销重做、自动保存。
"""

import ctypes
import copy
import json
import os

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent,
                            QPoint, QPointF, QSize, Qt, QTimer, QVariantAnimation)
from PySide6.QtGui import (QColor, QIcon,
                           QKeySequence, QMouseEvent, QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup,
                               QFileDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QStyle,
                               QStackedWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from src.config_manager import (load_config, save_config,
                                get_preset_commands, get_config_path,
                                _default_config)
from src.theme import UI, build_qss, FONT_XS
from src.qt_preview import (CommandTree, _PanelToggleButton, QRadialPreview,
                            _layer_key, _layer_name)
from src.qt_sector_editor import SectorEditorPopup
from src.qt_settings_panel import QSettingsPanel

QSS = build_qss(UI) + """
QPushButton.nav {
    text-align: left; padding: 9px 14px; border-radius: 8px;
    background: transparent; border: 1px solid transparent;
    color: """ + UI.text_secondary + """; font-size: 13px; }
QPushButton.nav:hover { background: """ + UI.bg_hover + """; }
QPushButton.nav:checked {
    background: """ + UI.bg_selected + """; color: """ + UI.text + """; }
QLabel#pageTitle { font-size: 15px; font-weight: 600; }
QLabel#pageSub { color: """ + UI.text_muted + """; font-size: 11px; }
QLabel#pill { background: """ + UI.bg_card + """; color: """ + UI.text_secondary + """;
    border: 1px solid """ + UI.border + """; border-radius: 10px;
    padding: 3px 12px; font-size: 12px; }
"""


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


# 顶栏按钮样式：与标题同高（28px），避免全局 QSS 的 min-height 撑高
_TOP_BTN_QSS = f"""
QPushButton {{
    background: {UI.bg_raised}; border: 1px solid {UI.border_strong};
    border-radius: 6px; padding: 2px 12px; color: {UI.text};
}}
QPushButton:hover {{ background: {UI.bg_hover}; }}
QPushButton:pressed {{ background: {UI.bg_card}; }}
QPushButton:disabled {{ color: {UI.text_muted}; }}
"""


class QConfigGUI(QMainWindow):
    """Qt 配置界面主窗口（导航式布局）"""

    def __init__(self, on_save=None, parent=None):
        super().__init__(parent)
        self.on_save = on_save
        self.config = load_config()
        self.current_profile = self.config.get("settings", {}).get(
            "active_profile", "AutoCAD-常用")
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(500)
        self._autosave_timer.timeout.connect(self._do_save)

        self.setWindowTitle("CAD鼠标手势 - 配置")
        icon_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "assets", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1280, 820)
        self.setStyleSheet(QSS)

        # 撤销/重做栈与状态
        self._undo_stack = []
        self._redo_stack = []
        self._pending_preset = None
        self._edit_guard = False
        self._btn_undo = None
        self._btn_redo = None
        self._selected_sector = None

        self.preview = QRadialPreview()
        self.preview.on_select = self._on_sector_selected
        self.preview.on_drop = self._on_drop
        self.preview.on_swap = self._on_sector_swapped
        self.preview.on_clear = self._on_sector_cleared

        # 扇区编辑浮层（普通无边框窗 + 应用级事件过滤器管理外部点击关闭）
        self._popup = SectorEditorPopup(self)
        self._popup.save_requested.connect(self._on_sector_saved)
        self._popup.cleared.connect(self._on_popup_cleared)
        self._popup.closed.connect(self._on_popup_closed)
        self._popup.blank_clicked.connect(self._on_popup_blank_clicked)
        self._popup.esc_requested.connect(self._on_popup_esc)
        self._popup.reposition_requested.connect(self._place_popup)
        QApplication.instance().installEventFilter(self)

        # 快捷键
        QShortcut(QKeySequence(Qt.Key_Delete), self,
                  activated=self._delete_selected)
        QShortcut(QKeySequence("Ctrl+Z"), self, activated=self._undo)
        QShortcut(QKeySequence("Ctrl+Y"), self, activated=self._redo)
        QShortcut(QKeySequence(Qt.Key_Escape), self,
                  activated=self._cancel_pending)
        QShortcut(QKeySequence("Ctrl+F"), self, activated=self._focus_search)

        # 侧栏 + 主区
        root = QHBoxLayout()
        root.setContentsMargins(0, 0, 0, 0)
        root.setSpacing(0)
        root.addWidget(self._build_sidebar())
        self._main_stack = QStackedWidget()
        self._main_stack.addWidget(self._build_editor_page())
        self._settings_panel = QSettingsPanel(self.config)
        self._settings_panel.on_back = self._show_editor
        self._settings_panel.on_saved = self._on_settings_saved
        self._settings_panel.on_import = self._import_profile
        self._settings_panel.on_export = self._export_profile
        self._settings_panel.on_open_dir = self._open_config_dir
        self._main_stack.addWidget(self._settings_panel)
        self._main_stack.setCurrentIndex(0)
        root.addWidget(self._main_stack, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.setMinimumSize(1060, 720)

        self.statusBar().showMessage("就绪")
        self._refresh_profiles()
        self._load_profile(self.current_profile)

    def showEvent(self, e):
        super().showEvent(e)
        _enable_dark_titlebar(self)

    # ========== 侧栏 ==========

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        panel.setStyleSheet(f"""
            QWidget#sidebar {{ background: {UI.bg_raised};
                              border-right: 1px solid {UI.border}; }}
        """)
        v = QVBoxLayout(panel)
        v.setContentsMargins(10, 14, 10, 12)
        v.setSpacing(6)

        title = QLabel("CAD 鼠标手势")
        title.setStyleSheet(f"font-size: 15px; font-weight: 700; color: {UI.text}; "
                            "padding: 2px 8px 10px 8px;")
        v.addWidget(title)

        # 导航按钮
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self.btn_nav_editor = self._nav_btn("圆盘编辑")
        self.btn_nav_settings = self._nav_btn("设置")
        self._nav_group.addButton(self.btn_nav_editor)
        self._nav_group.addButton(self.btn_nav_settings)
        self.btn_nav_editor.setChecked(True)
        self.btn_nav_editor.clicked.connect(self._show_editor)
        self.btn_nav_settings.clicked.connect(self._show_settings)
        v.addWidget(self.btn_nav_editor)
        v.addWidget(self.btn_nav_settings)
        v.addSpacing(10)

        # 上下文区：圆盘编辑时显示方案列表，设置时显示锚点
        self._ctx_stack = QStackedWidget()
        self._ctx_stack.addWidget(self._build_profiles_panel())
        self._ctx_stack.addWidget(self._build_anchor_panel())
        v.addWidget(self._ctx_stack, 1)
        return panel

    def _nav_btn(self, text: str) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setProperty("class", "nav")
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _build_profiles_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel("配置方案")
        t.setStyleSheet(f"color: {UI.text_muted}; font-size: {FONT_XS}px; "
                        "font-weight: 600; padding-left: 8px;")
        head.addWidget(t)
        head.addStretch(1)
        v.addLayout(head)

        self.profile_list = QListWidget()
        self.profile_list.setFocusPolicy(Qt.NoFocus)
        self.profile_list.itemClicked.connect(self._on_profile_clicked)
        self.profile_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(
            self._profile_list_menu)
        v.addWidget(self.profile_list, 1)

        row = QHBoxLayout()
        row.setSpacing(6)
        btn_add = QPushButton("＋ 新增")
        btn_add.clicked.connect(self._add_profile)
        btn_more = QPushButton("⋯")
        btn_more.setProperty("class", "iconBtn")
        btn_more.setToolTip("复制 / 重命名 / 删除 / 导入 / 导出")
        btn_more.clicked.connect(self._show_profile_menu)
        row.addWidget(btn_add, 1)
        row.addWidget(btn_more)
        v.addLayout(row)
        return w

    def _build_anchor_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(8)
        t = QLabel("设置分类")
        t.setStyleSheet(f"color: {UI.text_muted}; font-size: {FONT_XS}px; "
                        "font-weight: 600; padding-left: 8px;")
        v.addWidget(t)
        self.anchor_list = QListWidget()
        self.anchor_list.setFocusPolicy(Qt.NoFocus)
        for key, name in (("appearance", "外观"), ("trigger", "触发手感"),
                          ("size", "圆盘尺寸"), ("general", "常规"),
                          ("maintenance", "维护")):
            item = QListWidgetItem(name)
            item.setData(Qt.UserRole, key)
            self.anchor_list.addItem(item)
        self.anchor_list.itemClicked.connect(self._on_anchor_clicked)
        v.addWidget(self.anchor_list, 1)
        return w

    def _on_anchor_clicked(self, item):
        self._settings_panel.scroll_to(item.data(Qt.UserRole))

    def _show_profile_menu(self):
        menu = self._build_profile_menu()
        btn = self.sender()
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _profile_list_menu(self, pos):
        menu = self._build_profile_menu()
        menu.exec(self.profile_list.viewport().mapToGlobal(pos))

    def _build_profile_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction("复制方案", self._copy_profile)
        menu.addAction("重命名", self._rename_profile)
        menu.addAction("删除方案", self._delete_profile)
        menu.addSeparator()
        menu.addAction("导入方案", self._import_profile)
        menu.addAction("导出方案", self._export_profile)
        return menu

    # ========== 主区页面 ==========

    def _build_editor_page(self) -> QWidget:
        page = QWidget()
        v = QVBoxLayout(page)
        v.setContentsMargins(18, 14, 18, 14)
        v.setSpacing(10)

        # 顶栏：标题 + 方案名 + 操作按钮（放顶部避免被圆盘下方的编辑浮层遮挡；
        # 右侧留 12px 与命令库隔开）
        top = QHBoxLayout()
        top.setSpacing(8)
        top.setContentsMargins(0, 0, 12, 0)
        self.page_title = QLabel("")
        self.page_title.setObjectName("pageTitle")
        top.addWidget(self.page_title, 0, Qt.AlignVCenter)
        self.pill_profile = QLabel("")
        self.pill_profile.setObjectName("pill")
        top.addWidget(self.pill_profile, 0, Qt.AlignVCenter)
        top.addStretch(1)
        self._btn_undo = QPushButton("撤销")
        self._btn_undo.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_ArrowBack))
        self._btn_undo.setEnabled(False)
        self._btn_undo.setToolTip("撤销上一步操作 (Ctrl+Z)")
        self._btn_undo.clicked.connect(self._undo)
        self._btn_redo = QPushButton("重做")
        self._btn_redo.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_ArrowForward))
        self._btn_redo.setEnabled(False)
        self._btn_redo.setToolTip("重做被撤销的操作 (Ctrl+Y)")
        self._btn_redo.clicked.connect(self._redo)
        for b in (self._btn_undo, self._btn_redo):
            b.setFixedHeight(28)
            b.setStyleSheet(_TOP_BTN_QSS)
        top.addWidget(self._btn_undo, 0, Qt.AlignVCenter)
        top.addWidget(self._btn_redo, 0, Qt.AlignVCenter)
        self._btn_clear_all = QPushButton("一键清除")
        self._btn_clear_all.setToolTip("清空当前方案的全部命令")
        self._btn_clear_all.clicked.connect(self._clear_all_sectors)
        self._btn_clear_all.setFixedHeight(28)
        self._btn_clear_all.setStyleSheet(
            _TOP_BTN_QSS + f"QPushButton {{ color: {UI.danger}; }}")
        top.addWidget(self._btn_clear_all, 0, Qt.AlignVCenter)
        self._btn_reset_default = QPushButton("恢复默认")
        self._btn_reset_default.setToolTip("把当前方案恢复为默认命令")
        self._btn_reset_default.clicked.connect(self._reset_default_profile)
        self._btn_reset_default.setFixedHeight(28)
        self._btn_reset_default.setStyleSheet(_TOP_BTN_QSS)
        top.addWidget(self._btn_reset_default, 0, Qt.AlignVCenter)

        # 主体：左栏（顶栏 + 圆盘 + 工具栏）| 命令库从页面顶到底，覆盖顶栏高度
        self._editor_page = page
        body = QHBoxLayout()
        body.setSpacing(0)
        body.setContentsMargins(0, 0, 0, 0)
        left = QVBoxLayout()
        left.setContentsMargins(0, 0, 0, 0)
        left.setSpacing(10)
        top_wrap = QWidget()
        top_wrap.setLayout(top)
        top_wrap.setFixedHeight(32)
        left.addWidget(top_wrap)
        # preview 放在弹性容器中：容器吸收剩余高度，preview 自身保持
        # sizeHint 高度（575）不被拉伸，避免 Qt 弹性截断打乱布局
        preview_wrap = QWidget()
        pv = QVBoxLayout(preview_wrap)
        pv.setContentsMargins(0, 0, 0, 0)
        pv.setSpacing(0)
        pv.addWidget(self.preview)
        pv.addStretch(1)  # 弹性留在底部，圆盘始终顶对齐（下方留出浮层空间）
        left.addWidget(preview_wrap, 1)
        left_wrap = QWidget()
        left_wrap.setLayout(left)
        body.addWidget(left_wrap, 1)

        self.preset_panel = self._build_preset_panel()
        self.preset_panel.setFixedWidth(320)
        body.addWidget(self.preset_panel)
        v.addLayout(body, 1)

        # 折叠按钮：圆角胶囊贴边悬挂在命令库边界线中间，跟随折叠/展开
        self._btn_toggle_presets = _PanelToggleButton(page)
        self._btn_toggle_presets.clicked.connect(self._toggle_presets)
        page.installEventFilter(self)

        # 命令库折叠/展开宽度动画
        self._preset_wide = 320
        self._preset_anim = QVariantAnimation(self)
        self._preset_anim.setDuration(150)
        self._preset_anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._preset_anim.valueChanged.connect(self._on_preset_anim)
        self._preset_anim.finished.connect(self._on_preset_anim_finished)
        self._update_toggle_btn(False)
        self._update_toggle_pos()
        return page

    def _update_toggle_pos(self):
        """把按钮骑跨到命令库边界线上（中心对齐分界线），折叠后贴窗口右缘内侧"""
        btn = getattr(self, "_btn_toggle_presets", None)
        if btn is None:
            return
        x = self.preset_panel.x()  # 命令库左边界（页面坐标，按钮以 page 为父）
        w, h = btn.width(), btn.height()
        y = self._editor_page.height() // 2 - h // 2
        # 骑跨：按钮中线对齐分界线；折叠后分界线贴近窗口右缘，退回窗口内
        bx = x - w // 2
        bx = max(0, min(bx, self._editor_page.width() - w))
        btn.move(bx, y)
        btn.raise_()

    def _build_preset_panel(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("presetPanel")
        # 命令库作为右侧独立面板：自带背景与左边框，折叠/展开边界清晰
        panel.setStyleSheet(f"""
            QWidget#presetPanel {{
                background: {UI.bg_raised};
                border-left: 1px solid {UI.border_strong};
            }}
            QWidget#presetPanel QLabel {{ background: transparent; }}
        """)
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        head = QHBoxLayout()
        t = QLabel("命令库")
        t.setStyleSheet("font-size: 14px; font-weight: 600;")
        head.addWidget(t)
        head.addStretch(1)
        self._btn_expand_toggle = QPushButton("全部折叠 ▸")
        self._btn_expand_toggle.setProperty("class", "ghost")
        self._btn_expand_toggle.setToolTip("折叠所有分类")
        self._btn_expand_toggle.clicked.connect(self._toggle_expand_all)
        head.addWidget(self._btn_expand_toggle)
        v.addLayout(head)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText("搜索命令…  (Ctrl+F)")
        self.search_entry.textChanged.connect(self._on_search)
        v.addWidget(self.search_entry)

        self.preset_tree = CommandTree()
        self.preset_tree.setHeaderHidden(True)
        self.preset_tree.setColumnCount(2)
        self.preset_tree.setIndentation(12)
        self.preset_tree.setRootIsDecorated(False)
        self.preset_tree.setAnimated(True)
        self.preset_tree.setUniformRowHeights(False)
        self.preset_tree.setFocusPolicy(Qt.NoFocus)
        self.preset_tree.header().setStretchLastSection(False)
        self.preset_tree.header().setSectionResizeMode(0, QHeaderView.Stretch)
        self.preset_tree.header().setSectionResizeMode(1, QHeaderView.ResizeToContents)
        self.preset_tree.itemClicked.connect(self._on_preset_clicked)
        self.preset_tree.setContextMenuPolicy(Qt.CustomContextMenu)
        self.preset_tree.customContextMenuRequested.connect(self._on_preset_context)
        v.addWidget(self.preset_tree, 1)

        tip = QLabel("点扇区即编辑；选扇区后点命令直接应用；未选扇区时点命令进入放置模式")
        tip.setWordWrap(True)
        tip.setStyleSheet(f"color: {UI.text_muted}; font-size: {FONT_XS}px;")
        v.addWidget(tip)
        return panel

    def _toggle_presets(self):
        """折叠/展开命令库（宽度动画，按钮在分界线中间跟随状态）"""
        if self._preset_anim.state() == QAbstractAnimation.Running:
            return
        start = self.preset_panel.width()
        collapsing = start > 0
        target = 0 if collapsing else self._preset_wide
        self._preset_anim.stop()
        self._preset_anim.setStartValue(start)
        self._preset_anim.setEndValue(target)
        self._preset_anim.start()

    def _on_preset_anim(self, v):
        self.preset_panel.setFixedWidth(int(v))
        self._update_toggle_pos()

    def _on_preset_anim_finished(self):
        """宽度动画结束：图标方向才翻转，与最终面板状态一致，避免视觉脱节"""
        self._update_toggle_btn(self.preset_panel.width() <= 0)

    def _update_toggle_btn(self, collapsed):
        """刷新气泡按钮状态（箭头/竖排文字跟随展开/折叠）"""
        self._btn_toggle_presets.set_collapsed(collapsed)
        self._update_toggle_pos()

    def _expand_all_presets(self):
        self.preset_tree.expandAll()
        self._sync_category_icons()

    def _collapse_all_presets(self):
        self.preset_tree.collapseAll()
        self._sync_category_icons()

    def _toggle_expand_all(self):
        """全部展开/全部折叠切换（点了展开就显示折叠，反之亦然）"""
        n = self.preset_tree.topLevelItemCount()
        all_expanded = n > 0 and all(
            self.preset_tree.topLevelItem(i).isExpanded() for i in range(n))
        if all_expanded:
            self._collapse_all_presets()
        else:
            self._expand_all_presets()
        self._update_expand_btn()

    def _update_expand_btn(self):
        """根据当前分类展开状态刷新切换按钮文案"""
        btn = getattr(self, "_btn_expand_toggle", None)
        if btn is None:
            return
        n = self.preset_tree.topLevelItemCount()
        all_expanded = n > 0 and all(
            self.preset_tree.topLevelItem(i).isExpanded() for i in range(n))
        btn.setText("全部折叠 ▸" if all_expanded else "全部展开 ▾")
        btn.setToolTip("折叠所有分类" if all_expanded else "展开所有分类")

    def _sync_category_icons(self):
        """同步分类标题的 ▾/▸ 前缀，保证与展开状态一致"""
        for i in range(self.preset_tree.topLevelItemCount()):
            item = self.preset_tree.topLevelItem(i)
            text = item.text(0)
            body = text[2:] if text[:2] in ("▾ ", "▸ ") else text
            item.setText(0, ("▾ " if item.isExpanded() else "▸ ") + body)

    def _focus_search(self):
        if self._main_stack.currentIndex() == 0:
            if self.preset_panel.width() <= 0:
                self._toggle_presets()  # 命令库折叠时先展开
            self.search_entry.setFocus()
            self.search_entry.selectAll()

    # ========== 页面切换 ==========

    def _show_settings(self):
        profile = self.config.get("profiles", {}).get(self.current_profile)
        self._settings_panel.refresh(self.config, profile)
        self._main_stack.setCurrentIndex(1)
        self._ctx_stack.setCurrentIndex(1)
        self.btn_nav_settings.setChecked(True)
        self.statusBar().showMessage("全局设置：修改即时保存")

    def _show_editor(self):
        self._main_stack.setCurrentIndex(0)
        self._ctx_stack.setCurrentIndex(0)
        self.btn_nav_editor.setChecked(True)
        self.preview.update_config(self.config)
        self.statusBar().showMessage("圆盘编辑")

    def _on_settings_saved(self):
        self.preview.update_config(self.config)

    def _open_config_dir(self):
        d = os.path.dirname(get_config_path())
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    # ========== 方案列表 ==========

    def _on_profile_clicked(self, item):
        name = item.data(Qt.UserRole)
        if name:
            self._load_profile(name)

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
            head.setForeground(QColor(UI.accent))
            f = head.font()
            f.setBold(True)
            f.setPixelSize(11)
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
        self.preview.pending = None
        self._popup.close()
        profile = self.config.get("profiles", {}).get(name, {})
        self.preview.set_data(self.config, profile)

        display = profile.get("name", name)
        cad_name = {"autocad": "AutoCAD", "zwcad": "中望CAD"}.get(
            profile.get("target", "autocad"),
            (profile.get("target", "autocad") or "autocad").upper())
        # 主次顺序：CAD 名（主标题）在前，配置方案名（pill）在后
        self.page_title.setText(cad_name)
        self.pill_profile.setText(display)

        self._preset_commands = get_preset_commands(
            profile.get("target", "autocad"))
        self._populate_presets(self.search_entry.text())
        self._highlight_profile()

    # ========== 扇区编辑（浮层） ==========

    def _on_sector_selected(self, layer, idx):
        if self._selected_sector is not None and self._popup._dirty:
            if self._confirm_discard() == "cancel":
                return
        self._selected_sector = (layer, idx)
        self._edit_guard = False
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        cfg = profile.get(_layer_key(layer), {}).get(str(idx), {})
        n = self.config.get("settings", {}).get("sector_count", 8)
        self._popup.show_sector(layer, idx, cfg, n)
        # 用户拖动过浮层则保持其位置，否则固定显示在圆盘下方
        if not self._popup.user_moved:
            self._place_popup()
        self._popup.show()
        self._popup.raise_()
        self.statusBar().showMessage(
            f"编辑 {_layer_name(layer)}扇区 {idx}：点击外部关闭")

    def _confirm_discard(self) -> str:
        """有未保存修改时弹确认框。返回 'save' / 'discard' / 'cancel'；
        无修改直接返回 'discard'（继续）。"""
        if not self._popup._dirty:
            return "discard"
        box = QMessageBox(self)
        box.setWindowTitle("未保存的修改")
        box.setText(f"扇区编辑有未保存的修改，要保存吗？")
        btn_save = box.addButton("保存", QMessageBox.ButtonRole.AcceptRole)
        btn_discard = box.addButton("放弃", QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton("取消", QMessageBox.ButtonRole.RejectRole)
        box.setDefaultButton(btn_save)
        box.exec()
        clicked = box.clickedButton()
        if clicked is btn_save:
            self._on_sector_saved()
            return "save"
        if clicked is btn_discard:
            self._popup._dirty = False
            self._popup.mark_saved()
            return "discard"
        return "cancel"

    def _on_popup_esc(self):
        """浮层内 Esc 且存在未保存修改：确认后关闭"""
        if self._confirm_discard() != "cancel":
            self._popup.close()

    def eventFilter(self, obj, event):
        """编辑页尺寸变化时重定位气泡按钮；浮层打开时点击外部/切走收起浮层"""
        if event.type() == QEvent.Resize and obj is getattr(self, "_editor_page", None):
            self._update_toggle_pos()
        popup = getattr(self, "_popup", None)
        if popup is not None and popup.isVisible():
            if event.type() == QEvent.MouseButtonPress:
                # 有活动弹出层（如 QComboBox 下拉）时把事件交给它，避免误关浮层
                if QApplication.activePopupWidget() is not None:
                    return super().eventFilter(obj, event)
                pos = event.globalPosition()
                if pos is not None and not self._popup.geometry().contains(pos.toPoint()):
                    # 点击浮层外：有未保存修改先弹确认框，取消则吞掉点击
                    if self._confirm_discard() == "cancel":
                        return True
                    self._popup.close()
            elif event.type() == QEvent.ApplicationDeactivate:
                self._popup.close()
        return super().eventFilter(obj, event)

    def _on_popup_closed(self):
        """浮层关闭（外部点击 / Esc / 切走）：清理选中状态"""
        if self._selected_sector is not None:
            if self._popup._dirty:
                self.statusBar().showMessage("修改未保存，已丢弃")
            else:
                self.statusBar().showMessage("已取消选择")
            self._selected_sector = None
            self.preview.selected = None
            self.preview.hovered = None
            self.preview.update()

    def _place_popup(self):
        """把浮层固定放在圆盘正下方（水平居中），下方放不下时改放上方。

        浮层是置顶 Tool 窗口：若盖住圆盘扇区，点击会被它吞掉导致无法
        切换到别的扇区（"点扇区 B 未生效"）。固定放在圆盘外侧、不随
        鼠标位置变化，彻底避开圆盘。
        """
        self._popup.adjustSize()
        geo = self.screen().availableGeometry()
        w, h = self._popup.width(), self._popup.height()
        cg = self.preview.mapToGlobal(self.preview.rect().center())
        scale = min(self.preview.width(), self.preview.height()) / 560.0
        disc_r = 240 * scale
        gap = 12

        x = cg.x() - w // 2
        y = cg.y() + disc_r + gap
        if y + h > geo.bottom() - 8:
            y = cg.y() - disc_r - gap - h  # 下方放不下，改放上方
        x = max(geo.left() + 8, min(x, geo.right() - w - 8))
        y = max(geo.top() + 8, min(y, geo.bottom() - h - 8))
        self._popup.move(x, y)
        # 上方也放不下时退化为覆盖 preview 底部（极矮屏幕兜底）
        if y + h > geo.bottom() - 8:
            self._popup.move(x, geo.bottom() - h - 8)

    def _on_popup_blank_clicked(self, gx: float, gy: float):
        """点击浮层空白处：确认未保存修改后关闭浮层，把点击转发给预览圆盘，
        让圆盘下的扇区能收到这次点击（解决浮层遮挡扇区导致无法再弹出的问题）"""
        if self._confirm_discard() == "cancel":
            return
        self._popup.close()
        try:
            origin = self.preview.mapToGlobal(QPoint(0, 0))
            px = gx - origin.x()
            py = gy - origin.y()
            px = max(0.0, min(float(self.preview.width()), px))
            py = max(0.0, min(float(self.preview.height()), py))
            pos = QPointF(px, py)
            ev = QMouseEvent(QMouseEvent.Type.MouseButtonPress, pos,
                             self.preview.mapToGlobal(pos.toPoint()),
                             Qt.LeftButton, Qt.LeftButton, Qt.NoModifier)
            self.preview.mousePressEvent(ev)
        except Exception:
            pass

    def _on_sector_saved(self):
        if not self._selected_sector:
            return
        if not self._edit_guard:
            self._push_undo()
            self._edit_guard = True
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.setdefault(_layer_key(layer), {})
        sectors[str(idx)] = {
            "label": self._popup.label_entry.text().strip(),
            "key": self._popup.key_entry.text().strip(),
            "description": self._popup.desc_entry.text().strip(),
        }
        self._popup.mark_saved()
        self.preview.update()
        self.statusBar().showMessage("● 保存中…")
        self._autosave_timer.start()

    def _on_popup_cleared(self):
        if not self._selected_sector:
            return
        self._push_undo()
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.get(_layer_key(layer), {})
        if str(idx) in sectors:
            del sectors[str(idx)]
        self.preview.update()
        self.statusBar().showMessage(f"已清空{_layer_name(layer)}扇区 {idx}")
        self._autosave_timer.start()

    def _on_sector_swapped(self, f_layer, f_idx, t_layer, t_idx):
        """扇区拖拽交换/移动命令：双方都有命令则交换，一方为空则移动"""
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        kf, kt = _layer_key(f_layer), _layer_key(t_layer)
        sf = profile.get(kf, {})
        st = profile.get(kt, {})
        a = sf.get(str(f_idx))
        b = st.get(str(t_idx))
        if a is None and b is None:
            return
        self._push_undo()
        if a is None:
            sf[str(f_idx)] = b
            st.pop(str(t_idx), None)
        elif b is None:
            st[str(t_idx)] = a
            sf.pop(str(f_idx), None)
        else:
            sf[str(f_idx)] = b
            st[str(t_idx)] = a
        self.preview.update()
        self._autosave_timer.start()
        if self._popup.isVisible():
            self._popup.close()
        verb = "交换" if a is not None and b is not None else "移动"
        self.statusBar().showMessage(
            f"已{verb}命令：{_layer_name(f_layer)}扇区 {f_idx} ↔ "
            f"{_layer_name(t_layer)}扇区 {t_idx}")

    def _on_sector_cleared(self):
        """点击圆盘外取消选择：关闭浮层并清空选中"""
        self._selected_sector = None
        self._popup.close()
        self.statusBar().showMessage("已取消选择")

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
        self.preview.update()
        self.statusBar().showMessage(f"已删除{_layer_name(layer)}扇区 {idx} 的命令")
        self._autosave_timer.start()

    def _clear_all_sectors(self):
        """一键清除：清空当前方案的全部命令"""
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        has = any(profile.get(k, {}) for k in
                  ("sectors", "outer_sectors", "extension_sectors"))
        if not has:
            self.statusBar().showMessage("当前方案本来就没有命令")
            return
        ret = QMessageBox.question(
            self, "一键清除",
            f"确定清空方案「{self.current_profile}」的全部命令吗？\n"
            "（可用 Ctrl+Z 撤销）")
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        for k in ("sectors", "outer_sectors", "extension_sectors"):
            profile[k] = {}
        self.preview.update()
        self._autosave_timer.start()
        self.statusBar().showMessage("已清空全部命令")

    def _reset_default_profile(self):
        """恢复默认：把当前方案的三圈命令恢复为默认配置"""
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        name = profile.get("name", self.current_profile)
        target = profile.get("target", "autocad")
        defp = None
        for dp in _default_config().get("profiles", {}).values():
            if dp.get("target") == target and dp.get("name") == name:
                defp = dp
                break
        if defp is None:
            for dp in _default_config().get("profiles", {}).values():
                if dp.get("target") == target:
                    defp = dp
                    break
        if defp is None:
            self.statusBar().showMessage("未找到可恢复的默认配置")
            return
        ret = QMessageBox.question(
            self, "恢复默认",
            f"确定把方案「{self.current_profile}」的三圈命令\n"
            "恢复为默认内容吗？（可用 Ctrl+Z 撤销）")
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        for k in ("sectors", "outer_sectors", "extension_sectors"):
            profile[k] = copy.deepcopy(defp.get(k, {}))
        self.preview.update()
        self._autosave_timer.start()
        self.statusBar().showMessage(f"已恢复方案「{self.current_profile}」的默认命令")

    # ========== 命令库 ==========

    def _on_search(self, text):
        self._populate_presets(text)

    def _on_preset_clicked(self, item, col):
        if item.parent() is None:
            # 分类标题：点击切换展开/折叠
            item.setExpanded(not item.isExpanded())
            self._sync_category_icons()
            self._update_expand_btn()
            return
        info = item.data(0, Qt.UserRole)
        if not info:
            return
        if self._selected_sector:
            self._apply_preset(info)
        else:
            # 未选扇区：进入放置模式，点扇区完成放置（主推路径）
            self._start_pending_place(info)

    def _on_preset_context(self, pos):
        item = self.preset_tree.itemAt(pos)
        if item is None or item.parent() is None:
            return
        data = item.data(0, Qt.UserRole)
        if not data:
            return
        menu = QMenu(self)
        act = menu.addAction("放置到圆盘扇区…")
        act.triggered.connect(lambda: self._start_pending_place(data))
        menu.exec(self.preset_tree.viewport().mapToGlobal(pos))

    def _start_pending_place(self, data):
        """进入放置模式：圆盘提示，点击扇区放置命令"""
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
        self.statusBar().showMessage(
            f"已将「{data.get('label', '')}」放置到{_layer_name(layer)}扇区 {idx}")
        self._autosave_timer.start()

    def _apply_preset(self, info):
        self._push_undo()
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.setdefault(_layer_key(layer), {})
        sectors[str(idx)] = info.copy()
        self._edit_guard = False
        self.preview.update()
        self.statusBar().showMessage(f"已将「{info.get('label', '')}」应用到扇区 {idx}")
        self._autosave_timer.start()

    def _populate_presets(self, filter_text=""):
        self.preset_tree.clear()
        if not getattr(self, "_preset_commands", None):
            return
        filter_text = filter_text.strip().lower()
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
            cat = QTreeWidgetItem([f"▸ {category}"])
            f = cat.font(0)
            f.setBold(True)
            f.setPixelSize(11)
            cat.setFont(0, f)
            cat.setForeground(0, QColor(UI.text_muted))
            cat.setSizeHint(0, QSize(0, 26))
            cat.setExpanded(True)
            cat.setText(0, f"▾ {category}")
            cat.setFirstColumnSpanned(True)
            for name, data in filtered.items():
                label = data.get("label", name)
                key = data.get("key", "")
                child = QTreeWidgetItem([label, key])
                child.setData(0, Qt.UserRole, data)
                child.setSizeHint(0, QSize(0, 30))
                child.setForeground(0, QColor(UI.text))
                child.setTextAlignment(0, Qt.AlignLeft | Qt.AlignVCenter)
                child.setForeground(1, QColor(UI.text_muted))
                child.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                child.setToolTip(
                    0, f"命令: {label}\n快捷键: {key}\nCAD 命令: {data.get('description', '')}\n\n"
                       f"拖拽到圆盘扇区即可新增/更换，也可左键应用到选中扇区")
                cat.addChild(child)
            self.preset_tree.addTopLevelItem(cat)
        self._update_expand_btn()

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
        self.config = cfg
        self.current_profile = self.config.get("settings", {}).get(
            "active_profile", "AutoCAD-常用")
        self._selected_sector = None
        self._edit_guard = False
        self._pending_preset = None
        self.preview.pending = None
        self.preview.selected = None
        self.preview.setCursor(Qt.ArrowCursor)
        self._popup.close()
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


def open_config_gui(on_save=None, master=None):
    """打开配置界面（返回窗口实例以便保持引用）"""
    win = QConfigGUI(on_save=on_save)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
