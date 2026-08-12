"""Qt 配置界面 — 导航式布局（PySide6）

结构：左侧导航栏 + 上下文区（方案列表），主区 QStackedWidget 多页：
  - 圆盘编辑页：大圆盘预览 + 可折叠命令库；点击扇区弹出就地编辑器
  - 设置分类页：外观与尺寸 / 触发与反馈 / 关于（侧边栏进入；测试页由关于页按钮进入）
功能：方案增删改、命令库拖放/搜索/放置模式、撤销重做、自动保存、
中英文切换、浅色/深色界面模式。
"""

import copy
import math
import os
from datetime import datetime

from PySide6.QtCore import (QAbstractAnimation, QEasingCurve, QEvent,
                            QPoint, QPointF, QSettings, QSize, Qt, QTimer,
                            QVariantAnimation)
from PySide6.QtGui import (QColor, QIcon, QPainter, QPen, QPixmap,
                           QKeySequence, QMouseEvent, QShortcut)
from PySide6.QtWidgets import (QApplication, QButtonGroup, QFrame,
                               QFileDialog, QHBoxLayout, QHeaderView,
                               QInputDialog, QLabel, QLineEdit, QListWidget,
                               QListWidgetItem, QMainWindow, QMenu,
                               QMessageBox, QPushButton, QStyle,
                               QStackedWidget, QTreeWidgetItem,
                               QVBoxLayout, QWidget)

from src.config_manager import (load_config, save_config,
                                get_config_path, get_profile_for_window,
                                set_profile_for_target, _default_config,
                                export_full_config, import_full_config)
from src.config_presets import get_preset_commands
from src.i18n import T, add_listener, remove_listener
from src.theme import (get_ui, set_ui_mode, build_app_qss,
                       current_ui_mode, set_title_bar_theme, font_px,
                       set_ui_font_scale)
from src.qt_preview import (CommandTree, _PanelToggleButton, QRadialPreview,
                            _layer_key, _layer_name)
from src.qt_sector_editor import SectorEditorPopup
from src.qt_popup import PopupController
from src.qt_profile_ops import (add_profile, copy_profile, rename_profile,
                                delete_profile, export_profile,
                                load_profile_data, apply_profile_data)
from src.qt_settings_panel import (AppearancePage, TriggerPage,
                                   AboutPage, TestPage)

# 侧边栏分类页元数据：(分类 key, 中文标题)
_SETTINGS_PAGES = (("appearance", "外观与尺寸"), ("trigger", "触发与反馈"),
                   ("about", "关于"),
                   ("test", "测试"))

# 侧边栏锚点分类：与 _SETTINGS_PAGES 一致，但跳过「测试」（由维护页按钮进入）
_ANCHOR_PAGES = tuple((k, zh) for k, zh in _SETTINGS_PAGES if k != "test")


class QConfigGUI(QMainWindow):
    """Qt 配置界面主窗口（导航式布局）"""

    def __init__(self, on_save=None, on_check_update=None, parent=None):
        super().__init__(parent)
        self.on_save = on_save
        self.on_check_update = on_check_update
        self.config = load_config()
        self.current_profile = self.config.get("settings", {}).get(
            "active_profile", "AutoCAD-常用")
        self._autosave_timer = QTimer(self)
        self._autosave_timer.setSingleShot(True)
        self._autosave_timer.setInterval(500)
        self._autosave_timer.timeout.connect(self._do_save)

        self.setWindowTitle(T("CAD鼠标手势 - 配置"))
        icon_path = os.path.join(os.path.dirname(os.path.dirname(
            os.path.abspath(__file__))), "assets", "icon.ico")
        if os.path.exists(icon_path):
            self.setWindowIcon(QIcon(icon_path))
        self.resize(1280, 820)
        self.setMinimumSize(1060, 720)

        # 语言切换监听（切换语言时刷新全部文本）
        self._lang_listener = self._apply_language
        add_listener(self._lang_listener)

        # 撤销/重做栈与状态
        self._undo_stack = []
        self._redo_stack = []
        self._pending_preset = None
        self._edit_guard = False
        self._btn_undo = None
        self._btn_redo = None
        self._selected_sector = None
        self._last_status = ""
        self._ui_mode = "dark"

        self.preview = QRadialPreview()
        self.preview.on_select = self._on_sector_selected
        self.preview.on_drop = self._on_drop
        self.preview.on_swap = self._on_sector_swapped
        self.preview.on_clear = self._on_sector_cleared

        # 扇区编辑浮层（普通无边框窗 + 应用级事件过滤器管理外部点击关闭）
        self._popup = SectorEditorPopup(self)
        self._popup_ctrl = PopupController(
            self._popup,
            on_save=self._on_sector_saved,
            on_clear=self._on_popup_cleared,
            on_closed=self._on_popup_closed,
            on_blank_clicked=self._on_popup_blank_clicked,
            on_esc=self._on_popup_esc,
            on_reposition=self._place_popup,
        )
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

        # 设置分类页（外观与尺寸 / 触发与反馈 / 关于 / 测试）
        self._setting_pages = {}
        page_cls = {"appearance": AppearancePage, "trigger": TriggerPage,
                    "about": AboutPage, "test": TestPage}
        for key, _zh in _SETTINGS_PAGES:
            page = page_cls[key](self.config)
            page.on_saved = self._on_settings_saved
            page.on_check_update = self.on_check_update
            page.on_import = self._import_profile
            page.on_export = self._export_profile
            page.on_open_dir = self._open_config_dir
            page.on_backup = self._backup_full_config
            page.on_restore = self._restore_full_config
            page.on_ui_mode_changed = self._on_ui_mode_changed
            page.on_language_changed = self._on_language_changed
            page.on_ui_font_changed = self._refresh_font
            page.on_open_test = lambda: self._show_setting("test")
            self._setting_pages[key] = page
            self._main_stack.addWidget(page)
        self._main_stack.setCurrentIndex(0)
        root.addWidget(self._main_stack, 1)
        central = QWidget()
        central.setLayout(root)
        self.setCentralWidget(central)
        self.setMinimumSize(1060, 720)

        self._apply_ui_mode(self.config.get("settings", {}).get("ui_mode", "dark"))
        self.statusBar().showMessage(T("就绪"))
        self._refresh_profiles()
        self._load_profile(self.current_profile)

    def showEvent(self, e):
        super().showEvent(e)
        # 记忆上次关闭时的窗口位置/大小（QSettings 存注册表，不污染配置文件）
        geo = QSettings("CADGesture", "CADGesture").value("config_win_geometry")
        if geo is not None:
            self.restoreGeometry(geo)
        set_title_bar_theme(self, current_ui_mode() == "dark")
        # 窗口完全映射后再校验几何：showEvent 阶段 frameGeometry 可能未反映
        # 恢复后的位置（拔掉副屏/分辨率变化遗留的屏幕外位置）；
        # 同时负责把异常状态导致的隐藏窗口重新显示
        QTimer.singleShot(100, self._validate_geometry)
        # 窗口完全显示后 DWM 属性更稳定，延迟再应用一次（覆盖显示时序问题）
        QTimer.singleShot(150,
                          lambda: set_title_bar_theme(self, current_ui_mode() == "dark"))

    def event(self, e):
        # DWM 标题栏属性在锁屏/远程桌面重连后可能丢失，窗口重新激活时重设
        if e.type() == QEvent.WindowActivate:
            set_title_bar_theme(self, current_ui_mode() == "dark")
        return super().event(e)

    # ========== 界面模式 / 语言 ==========

    def _on_ui_mode_changed(self, mode: str):
        """界面模式切换（外观页）：保存配置 + 重建全局 QSS/标题栏 + 同步运行时圆盘"""
        self.config.setdefault("settings", {})["ui_mode"] = mode
        save_config(self.config)
        self._apply_ui_mode(mode)
        if self.on_save:
            self.on_save(self.config)  # app 层重载配置 → 运行时圆盘主题跟随

    def _apply_ui_mode(self, mode: str):
        self._ui_mode = mode
        set_ui_mode(mode)
        QApplication.instance().setStyleSheet(build_app_qss(mode))
        set_title_bar_theme(self, current_ui_mode() == "dark")

    def _on_language_changed(self, lang: str):
        """语言切换（常规页）：保存配置 + 通知全局刷新"""
        from src.i18n import set_language
        set_language(lang)

    def _apply_language(self):
        """语言切换后的全量文本刷新（侧栏 / 顶栏 / 命令库 / 设置页 / 浮层）"""
        self.setWindowTitle(T("CAD鼠标手势 - 配置"))
        for b, zh in self._nav_texts:
            b.setText(T(zh))
        self.btn_add.setToolTip(T("新增方案"))
        self.btn_more.setToolTip(T("复制 / 重命名 / 删除 / 导入 / 导出"))
        # 设置分类锚点文本
        for i in range(self.anchor_list.count()):
            it = self.anchor_list.item(i)
            it.setText(T(_ANCHOR_PAGES[i][1]))
        self._refresh_profiles()
        self._load_profile(self.current_profile)
        self._populate_presets(self.search_entry.text())
        for page in self._setting_pages.values():
            page.retranslate()
        if self._popup.isVisible():
            self._popup.retranslate()
        self.statusBar().showMessage(self._last_status or T("就绪"))

    # ========== 侧栏 ==========

    def _build_sidebar(self) -> QWidget:
        panel = QWidget()
        panel.setObjectName("sidebar")
        v = QVBoxLayout(panel)
        v.setContentsMargins(12, 12, 12, 12)
        v.setSpacing(4)

        # ---- Logo 区（图标 + 名称 + 底部细分隔线）----
        logo_row = QHBoxLayout()
        logo_row.setSpacing(8)
        logo_icon = QLabel()
        logo_icon.setPixmap(self._app_logo_pixmap())
        logo_icon.setFixedSize(22, 22)
        logo_row.addWidget(logo_icon)
        logo = QLabel("CAD 鼠标手势")
        logo.setObjectName("appLogo")
        logo_row.addWidget(logo)
        logo_row.addStretch(1)
        v.addLayout(logo_row)

        sep1 = QFrame()
        sep1.setObjectName("sidebarSep")
        sep1.setFrameShape(QFrame.HLine)
        v.addSpacing(6)
        v.addWidget(sep1)
        v.addSpacing(6)

        # ---- 主导航（图标按钮，选中高亮）----
        self._nav_group = QButtonGroup(self)
        self._nav_group.setExclusive(True)
        self._nav_texts = []  # (btn, zh)
        self.btn_nav_editor = self._nav_btn("圆盘编辑", "disc")
        self._nav_texts.append((self.btn_nav_editor, "圆盘编辑"))
        self._nav_group.addButton(self.btn_nav_editor)
        self.btn_nav_editor.setChecked(True)
        self.btn_nav_editor.clicked.connect(self._show_editor)
        v.addWidget(self.btn_nav_editor)

        self.btn_nav_settings = self._nav_btn("设置", "gear")
        self._nav_texts.append((self.btn_nav_settings, "设置"))
        self._nav_group.addButton(self.btn_nav_settings)
        self.btn_nav_settings.clicked.connect(self._show_settings)
        v.addWidget(self.btn_nav_settings)

        v.addSpacing(8)

        # ---- 上下文区：圆盘编辑时显示方案列表，设置时显示分类锚点 ----
        self._ctx_stack = QStackedWidget()
        self._ctx_stack.addWidget(self._build_profiles_panel())
        self._ctx_stack.addWidget(self._build_anchor_panel())
        v.addWidget(self._ctx_stack, 1)

        # ---- 底部固定操作区 ----
        bottom = QHBoxLayout()
        bottom.setSpacing(6)
        self.btn_more = QPushButton("⋯")
        self.btn_more.setProperty("class", "iconBtn")
        self.btn_more.setToolTip(T("复制 / 重命名 / 删除 / 导入 / 导出"))
        self.btn_more.clicked.connect(self._show_profile_menu)
        bottom.addStretch(1)
        bottom.addWidget(self.btn_more)
        v.addLayout(bottom)
        return panel

    @staticmethod
    def _app_logo_pixmap(size: int = 22) -> QPixmap:
        """代码绘制品牌圆盘图标（跟随深浅色）"""
        ui = get_ui()
        pm = QPixmap(size, size)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        cx = cy = size / 2
        r = size / 2 - 3
        p.setPen(QPen(QColor(ui.accent), 2))
        p.setBrush(Qt.NoBrush)
        p.drawEllipse(QPointF(cx, cy), r, r)
        for i in range(8):
            ang = -math.pi / 2 + i * math.pi / 4
            px = cx + r * 0.65 * math.cos(ang)
            py = cy + r * 0.65 * math.sin(ang)
            p.setBrush(QColor(ui.accent))
            p.setPen(Qt.NoPen)
            p.drawEllipse(QPointF(px, py), 1.8, 1.8)
        p.end()
        return pm

    def _nav_icon(self, kind: str) -> QIcon:
        """导航按钮图标（圆盘 / 齿轮，跟随深浅色）"""
        ui = get_ui()
        s = 18
        pm = QPixmap(s, s)
        pm.fill(Qt.transparent)
        p = QPainter(pm)
        p.setRenderHint(QPainter.Antialiasing)
        col = QColor(ui.text_secondary)
        p.setPen(QPen(col, 1.6))
        p.setBrush(Qt.NoBrush)
        if kind == "disc":
            p.drawEllipse(QPointF(s / 2, s / 2), 6.0, 6.0)
            for i in range(8):
                ang = -math.pi / 2 + i * math.pi / 4
                px = s / 2 + 4.2 * math.cos(ang)
                py = s / 2 + 4.2 * math.sin(ang)
                p.setBrush(col)
                p.setPen(Qt.NoPen)
                p.drawEllipse(QPointF(px, py), 1.2, 1.2)
                p.setBrush(Qt.NoBrush)
                p.setPen(QPen(col, 1.6))
        else:  # gear
            for i in range(8):
                ang = -math.pi / 2 + i * math.pi / 4
                px = s / 2 + 5.0 * math.cos(ang)
                py = s / 2 + 5.0 * math.sin(ang)
                p.drawLine(QPointF(s / 2 + 2.6 * math.cos(ang),
                                   s / 2 + 2.6 * math.sin(ang)),
                           QPointF(px, py))
            p.drawEllipse(QPointF(s / 2, s / 2), 3.2, 3.2)
        p.end()
        return QIcon(pm)

    def _nav_btn(self, text: str, icon_kind: str) -> QPushButton:
        b = QPushButton(text)
        b.setCheckable(True)
        b.setProperty("class", "nav")
        b.setIcon(self._nav_icon(icon_kind))
        b.setCursor(Qt.PointingHandCursor)
        return b

    def _build_profiles_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        # 标题行：小标题 + 右侧新增按钮
        head = QHBoxLayout()
        head.setSpacing(4)
        self._lb_profiles = QLabel(T("配置方案"))
        self._lb_profiles.setObjectName("pageSub")
        self._lb_profiles.setFixedHeight(28)
        head.addWidget(self._lb_profiles)
        head.addStretch(1)
        self.btn_add = QPushButton("＋")
        self.btn_add.setProperty("class", "iconBtn")
        self.btn_add.setToolTip(T("新增方案"))
        self.btn_add.clicked.connect(self._add_profile)
        head.addWidget(self.btn_add)
        v.addLayout(head)

        self.profile_list = QListWidget()
        self.profile_list.setObjectName("ctxList")
        self.profile_list.setFocusPolicy(Qt.NoFocus)
        self.profile_list.itemClicked.connect(self._on_profile_clicked)
        self.profile_list.setContextMenuPolicy(Qt.CustomContextMenu)
        self.profile_list.customContextMenuRequested.connect(
            self._profile_list_menu)
        v.addWidget(self.profile_list, 1)
        return w

    def _build_anchor_panel(self) -> QWidget:
        w = QWidget()
        v = QVBoxLayout(w)
        v.setContentsMargins(0, 0, 0, 0)
        v.setSpacing(6)
        head = QHBoxLayout()
        head.setSpacing(4)
        self._lb_anchor = QLabel(T("设置分类"))
        self._lb_anchor.setObjectName("pageSub")
        self._lb_anchor.setFixedHeight(28)
        head.addWidget(self._lb_anchor)
        head.addStretch(1)
        v.addLayout(head)
        self.anchor_list = QListWidget()
        self.anchor_list.setObjectName("ctxList")
        self.anchor_list.setFocusPolicy(Qt.NoFocus)
        for key, zh in _ANCHOR_PAGES:
            item = QListWidgetItem(T(zh))
            item.setData(Qt.UserRole, key)
            self.anchor_list.addItem(item)
        self.anchor_list.itemClicked.connect(self._on_anchor_clicked)
        v.addWidget(self.anchor_list, 1)
        return w

    def _on_anchor_clicked(self, item):
        key = item.data(Qt.UserRole)
        self._show_setting(key)

    def _show_profile_menu(self):
        menu = self._build_profile_menu()
        btn = self.sender()
        menu.exec(btn.mapToGlobal(btn.rect().bottomLeft()))

    def _profile_list_menu(self, pos):
        menu = self._build_profile_menu()
        menu.exec(self.profile_list.viewport().mapToGlobal(pos))

    def _build_profile_menu(self) -> QMenu:
        menu = QMenu(self)
        menu.addAction(T("复制方案"), self._copy_profile)
        menu.addAction(T("重命名"), self._rename_profile)
        menu.addAction(T("删除方案"), self._delete_profile)
        # 绑定：只显示与当前方案 target 匹配的那一项
        # （CAD 方案只能设为 AutoCAD 应用方案，中望方案只能设为中望CAD 应用方案）
        target = self.config.get("profiles", {}).get(
            self.current_profile, {}).get("target")
        if target == "autocad":
            menu.addSeparator()
            menu.addAction(T("设为 AutoCAD 应用方案"),
                           lambda: self._set_profile_binding("autocad"))
        elif target == "zwcad":
            menu.addSeparator()
            menu.addAction(T("设为中望CAD 应用方案"),
                           lambda: self._set_profile_binding("zwcad"))
        menu.addSeparator()
        menu.addAction(T("导入方案"), self._import_profile)
        menu.addAction(T("导出方案"), self._export_profile)
        return menu

    def _set_profile_binding(self, target: str):
        """把当前方案设为 AutoCAD / 中望CAD 的应用方案"""
        if set_profile_for_target(self.config, target, self.current_profile):
            self._push_undo()
            self._refresh_profiles()
            self._autosave_timer.start()
            cad_name = {"autocad": "AutoCAD", "zwcad": T("中望CAD")}.get(
                target, target)
            self._set_status(T("已设为 {cad} 的应用方案").format(cad=cad_name))
        else:
            QMessageBox.warning(self, T("错误"),
                                T("方案类型与目标 CAD 不匹配"))

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
        self._btn_undo = QPushButton(T("撤销"))
        self._btn_undo.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_ArrowBack))
        self._btn_undo.setEnabled(False)
        self._btn_undo.setToolTip(T("撤销上一步操作 (Ctrl+Z)"))
        self._btn_undo.clicked.connect(self._undo)
        self._btn_redo = QPushButton(T("重做"))
        self._btn_redo.setIcon(self.style().standardIcon(
            QStyle.StandardPixmap.SP_ArrowForward))
        self._btn_redo.setEnabled(False)
        self._btn_redo.setToolTip(T("重做被撤销的操作 (Ctrl+Y)"))
        self._btn_redo.clicked.connect(self._redo)
        for b in (self._btn_undo, self._btn_redo):
            b.setFixedHeight(28)
            b.setProperty("class", "topBtn")
        top.addWidget(self._btn_undo, 0, Qt.AlignVCenter)
        top.addWidget(self._btn_redo, 0, Qt.AlignVCenter)
        self._btn_clear_all = QPushButton(T("一键清除"))
        self._btn_clear_all.setToolTip(T("清空当前方案的全部命令"))
        self._btn_clear_all.clicked.connect(self._clear_all_sectors)
        self._btn_clear_all.setFixedHeight(28)
        self._btn_clear_all.setProperty("class", "topBtn")
        self._btn_clear_all.setObjectName("btnClearAll")
        top.addWidget(self._btn_clear_all, 0, Qt.AlignVCenter)
        self._btn_reset_default = QPushButton(T("恢复默认"))
        self._btn_reset_default.setToolTip(T("把当前方案恢复为默认命令"))
        self._btn_reset_default.clicked.connect(self._reset_default_profile)
        self._btn_reset_default.setFixedHeight(28)
        self._btn_reset_default.setProperty("class", "topBtn")
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
        # 命令库作为右侧独立面板：自带背景与左边框（样式在全局 QSS），折叠/展开边界清晰
        v = QVBoxLayout(panel)
        v.setContentsMargins(14, 12, 14, 12)
        v.setSpacing(8)
        head = QHBoxLayout()
        self._lb_library = QLabel(T("命令库"))
        self._lb_library.setStyleSheet("font-size: 14px; font-weight: 600;")
        head.addWidget(self._lb_library)
        head.addStretch(1)
        self._btn_expand_toggle = QPushButton(T("全部折叠 ▸"))
        self._btn_expand_toggle.setProperty("class", "ghost")
        self._btn_expand_toggle.setToolTip(T("折叠所有分类"))
        self._btn_expand_toggle.clicked.connect(self._toggle_expand_all)
        head.addWidget(self._btn_expand_toggle)
        v.addLayout(head)

        self.search_entry = QLineEdit()
        self.search_entry.setPlaceholderText(T("搜索命令…  (Ctrl+F)"))
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

        self._tip = QLabel(T("点扇区即编辑；选扇区后点命令直接应用；未选扇区时点命令进入放置模式"))
        self._tip.setWordWrap(True)
        v.addWidget(self._tip)
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
        btn.setText(T("全部折叠 ▸") if all_expanded else T("全部展开 ▾"))
        btn.setToolTip(T("折叠所有分类") if all_expanded else T("展开所有分类"))

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
        """进入设置：上下文区显示分类锚点，默认打开第一个分类页"""
        self.btn_nav_settings.setChecked(True)
        self._ctx_stack.setCurrentIndex(1)
        self._set_status(T("全局设置：修改即时保存"))
        # 锚点默认选中当前分类
        cur = self._current_setting_key()
        self._highlight_anchor(cur)
        self._show_setting(cur)

    def _current_setting_key(self) -> str:
        """当前设置分类 key（根据主区索引推算，默认外观）"""
        idx = self._main_stack.currentIndex()
        if 1 <= idx <= len(_SETTINGS_PAGES):
            return _SETTINGS_PAGES[idx - 1][0]
        return _SETTINGS_PAGES[0][0]

    def _highlight_anchor(self, key: str):
        for i in range(self.anchor_list.count()):
            it = self.anchor_list.item(i)
            if it.data(Qt.UserRole) == key:
                self.anchor_list.setCurrentItem(it)
                break

    def _show_setting(self, key: str):
        """进入指定设置分类页（锚点点击）"""
        page = self._setting_pages[key]
        profile = self.config.get("profiles", {}).get(self.current_profile)
        page.refresh(self.config, profile)
        idx = 1 + [k for k, _ in _SETTINGS_PAGES].index(key)
        self._main_stack.setCurrentIndex(idx)
        self._ctx_stack.setCurrentIndex(1)
        self.btn_nav_settings.setChecked(True)
        self._highlight_anchor(key)
        self._set_status(T("全局设置：修改即时保存"))

    def _show_editor(self):
        self._main_stack.setCurrentIndex(0)
        self._ctx_stack.setCurrentIndex(0)
        self.btn_nav_editor.setChecked(True)
        self.preview.update_config(self.config)
        self._set_status(T("圆盘编辑"))

    def _on_settings_saved(self):
        self.preview.update_config(self.config)
        # 设置页改动即时生效：通知 app 重载配置（菜单/引擎/全局 QSS 跟随更新）
        if self.on_save:
            self.on_save(self.config)

    def _set_status(self, msg: str):
        """记录最近状态消息（语言切换后按需重译显示）"""
        self._last_status = msg
        self.statusBar().showMessage(msg)

    def _refresh_font(self):
        """界面字号滑杆拖动时实时重建 QSS（模块级字号缩放生效）"""
        try:
            set_ui_font_scale(self.config.get("settings", {}).get(
                "ui_font_scale", 100) / 100.0)
            self.setStyleSheet(build_app_qss(self._ui_mode))
        except Exception:
            pass

    def _open_config_dir(self):
        d = os.path.dirname(get_config_path())
        os.makedirs(d, exist_ok=True)
        os.startfile(d)

    def _backup_full_config(self):
        """整包配置备份：settings + profiles 导出为 JSON"""
        path, _ = QFileDialog.getSaveFileName(
            self, T("备份配置"),
            f"CADGesture-config-{datetime.now().strftime('%Y%m%d')}.json",
            T("JSON 文件 (*.json)"))
        if not path:
            return
        ok, err = export_full_config(path)
        if ok:
            QMessageBox.information(
                self, T("备份完成"),
                T("配置已备份到：\n{path}").format(path=path))
        else:
            QMessageBox.warning(
                self, T("错误"), T("备份失败：{e}").format(e=err))

    def _restore_full_config(self):
        """整包配置恢复：校验备份文件后覆盖当前配置并立即生效"""
        path, _ = QFileDialog.getOpenFileName(
            self, T("恢复配置"), "", T("JSON 文件 (*.json)"))
        if not path:
            return
        ok, data = import_full_config(path)
        if not ok:
            QMessageBox.warning(self, T("错误"), data)
            return
        if QMessageBox.question(
                self, T("确认"),
                T("确定用备份文件覆盖当前全部配置吗？")) != QMessageBox.Yes:
            return
        save_config(data)
        self.config = data
        self.current_profile = data.get("settings", {}).get(
            "active_profile", "AutoCAD-常用")
        self._refresh_profiles()
        self._load_profile(self.current_profile)
        self._populate_presets(self.search_entry.text())
        profile = data.get("profiles", {}).get(self.current_profile)
        for page in self._setting_pages.values():
            page.refresh(data, profile)
        if self.on_save:
            self.on_save(self.config)
        QMessageBox.information(
            self, T("已恢复"), T("配置已恢复，立即生效。"))

    # ========== 方案列表 ==========

    def _on_profile_clicked(self, item):
        name = item.data(Qt.UserRole)
        if name:
            self._load_profile(name)

    def _refresh_profiles(self):
        self.profile_list.clear()
        profiles = self.config.get("profiles", {})
        settings = self.config.get("settings", {})
        groups = {
            T("AutoCAD"): [n for n, p in profiles.items() if p.get("target") == "autocad"],
            T("中望CAD"): [n for n, p in profiles.items() if p.get("target") == "zwcad"],
            T("其他"): [n for n, p in profiles.items()
                        if p.get("target") not in ("autocad", "zwcad")],
        }
        # 各 CAD 当前应用方案（绑定或首个匹配），与运行时规则一致
        bound = {}
        for tgt, label in (("autocad", "AutoCAD"), ("zwcad", T("中望CAD"))):
            prof = get_profile_for_window(self.config, tgt)
            if prof is not None:
                bound[label] = prof.get("name", "")
        for gname, names in groups.items():
            if not names:
                continue
            current_name = bound.get(gname)
            head_text = gname
            if current_name and names and current_name in names:
                head_text = T("{cad}（当前：{name}）").format(
                    cad=gname, name=current_name)
            head = QListWidgetItem(head_text)
            head.setFlags(Qt.NoItemFlags)
            head.setForeground(QColor(get_ui().accent))
            f = head.font()
            f.setBold(True)
            f.setPixelSize(font_px(11))
            head.setFont(f)
            self.profile_list.addItem(head)
            for name in names:
                text = profiles[name].get("name", name)
                item = QListWidgetItem(text)
                item.setData(Qt.UserRole, name)
                self.profile_list.addItem(item)
                # 当前应用方案：方案名左对齐，「● 当前」标记右对齐
                if current_name == profiles[name].get("name", name):
                    item.setText("")
                    w = QWidget()
                    lay = QHBoxLayout(w)
                    lay.setContentsMargins(8, 0, 8, 0)
                    lay.setSpacing(0)
                    lb_name = QLabel(text)
                    f2 = item.font()
                    f2.setBold(True)
                    lb_name.setFont(f2)
                    lb_name.setStyleSheet("background: transparent;")
                    lb_tag = QLabel(T("● 当前"))
                    lb_tag.setStyleSheet(
                        "background: transparent; color: %s;" % get_ui().accent)
                    lay.addWidget(lb_name)
                    lay.addStretch(1)
                    lay.addWidget(lb_tag)
                    self.profile_list.setItemWidget(item, w)
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
        cad_name = {"autocad": "AutoCAD", "zwcad": T("中望CAD")}.get(
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
        self._popup_ctrl.fill(
            layer, idx, cfg, n, self.config.get("settings", {}))
        # 用户拖动过浮层则保持其位置，否则固定显示在圆盘下方
        if not self._popup.user_moved:
            self._place_popup()
        self._popup_ctrl.show()
        self._set_status(
            T("编辑 {layer}扇区 {idx}：点击外部关闭")
            .format(layer=T(_layer_name(layer)), idx=idx))

    def _confirm_discard(self) -> str:
        """有未保存修改时弹确认框。返回 'save' / 'discard' / 'cancel'；
        无修改直接返回 'discard'（继续）。"""
        if not self._popup._dirty:
            return "discard"
        box = QMessageBox(self)
        box.setWindowTitle(T("未保存的修改"))
        box.setText(T("扇区编辑有未保存的修改，要保存吗？"))
        btn_save = box.addButton(T("保存"), QMessageBox.ButtonRole.AcceptRole)
        btn_discard = box.addButton(T("放弃"), QMessageBox.ButtonRole.DestructiveRole)
        btn_cancel = box.addButton(T("取消"), QMessageBox.ButtonRole.RejectRole)
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
                self._set_status(T("修改未保存，已丢弃"))
            else:
                self._set_status(T("已取消选择"))
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
        self._popup_ctrl.place(
            self.preview.mapToGlobal(self.preview.rect().center()),
            self.preview.outermost_radius_px())

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
        self._set_status(T("● 保存中…"))
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
        self._set_status(
            T("已清空{layer}扇区 {idx}").format(layer=T(_layer_name(layer)), idx=idx))
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
        self._set_status(
            T("已{verb}命令：{f_layer}扇区 {f_idx} ↔ {t_layer}扇区 {t_idx}")
            .format(verb=T(verb), f_layer=T(_layer_name(f_layer)), f_idx=f_idx,
                    t_layer=T(_layer_name(t_layer)), t_idx=t_idx))

    def _on_sector_cleared(self):
        """点击圆盘外取消选择：关闭浮层并清空选中"""
        self._selected_sector = None
        self._popup.close()
        self._set_status(T("已取消选择"))

    def _delete_selected(self):
        """Delete 键删除当前选中扇区的命令"""
        if not getattr(self, "_selected_sector", None):
            self._set_status(T("请先在圆盘上选择一个扇区"))
            return
        self._push_undo()
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.get(_layer_key(layer), {})
        if str(idx) in sectors:
            del sectors[str(idx)]
        self.preview.update()
        self._set_status(
            T("已删除{layer}扇区 {idx} 的命令").format(
                layer=T(_layer_name(layer)), idx=idx))
        self._autosave_timer.start()

    def _clear_all_sectors(self):
        """一键清除：清空当前方案的全部命令"""
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        has = any(profile.get(k, {}) for k in
                  ("sectors", "outer_sectors", "extension_sectors"))
        if not has:
            self._set_status(T("当前方案本来就没有命令"))
            return
        ret = QMessageBox.question(
            self, T("一键清除"),
            T("确定清空方案「{name}」的全部命令吗？\n（可用 Ctrl+Z 撤销）")
            .format(name=self.current_profile))
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        for k in ("sectors", "outer_sectors", "extension_sectors"):
            profile[k] = {}
        self.preview.update()
        self._autosave_timer.start()
        self._set_status(T("已清空全部命令"))

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
            self._set_status(T("未找到可恢复的默认配置"))
            return
        ret = QMessageBox.question(
            self, T("恢复默认"),
            T("确定把方案「{name}」的三圈命令\n恢复为默认内容吗？（可用 Ctrl+Z 撤销）")
            .format(name=self.current_profile))
        if ret != QMessageBox.StandardButton.Yes:
            return
        self._push_undo()
        for k in ("sectors", "outer_sectors", "extension_sectors"):
            profile[k] = copy.deepcopy(defp.get(k, {}))
        self.preview.update()
        self._autosave_timer.start()
        self._set_status(
            T("已恢复方案「{name}」的默认命令").format(name=self.current_profile))

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
        act = menu.addAction(T("放置到圆盘扇区…"))
        act.triggered.connect(lambda: self._start_pending_place(data))
        menu.exec(self.preset_tree.viewport().mapToGlobal(pos))

    def _start_pending_place(self, data):
        """进入放置模式：圆盘提示，点击扇区放置命令"""
        self._pending_preset = data
        self.preview.pending = data
        self.preview.setCursor(Qt.CrossCursor)
        self._set_status(
            T("点击圆盘扇区放置「{label}」，右键 / Esc 取消")
            .format(label=data.get("label", "")))
        self.preview.update()

    def _cancel_pending(self):
        if self._pending_preset:
            self._pending_preset = None
            self.preview.pending = None
            self.preview.setCursor(Qt.ArrowCursor)
            self.preview.update()
            self._set_status(T("已取消放置"))

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
        self._set_status(
            T("已将「{label}」放置到{layer}扇区 {idx}")
            .format(label=data.get("label", ""),
                    layer=T(_layer_name(layer)), idx=idx))
        self._autosave_timer.start()

    def _apply_preset(self, info):
        self._push_undo()
        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        sectors = profile.setdefault(_layer_key(layer), {})
        sectors[str(idx)] = info.copy()
        self._edit_guard = False
        self.preview.update()
        self._set_status(
            T("已将「{label}」应用到扇区 {idx}")
            .format(label=info.get("label", ""), idx=idx))
        self._autosave_timer.start()

    def _populate_presets(self, filter_text=""):
        self.preset_tree.clear()
        if not getattr(self, "_preset_commands", None):
            return
        filter_text = filter_text.strip().lower()
        ui = get_ui()
        for category, commands in self._preset_commands.items():
            cat_zh = T(category)
            if filter_text:
                filtered = {k: v for k, v in commands.items()
                            if filter_text in k.lower()
                            or filter_text in T(v.get("label", "")).lower()
                            or filter_text in v.get("key", "").lower()
                            or filter_text in v.get("description", "").lower()}
                if not filtered:
                    continue
            else:
                filtered = commands
            cat = QTreeWidgetItem([f"▸ {cat_zh}"])
            f = cat.font(0)
            f.setBold(True)
            f.setPixelSize(font_px(11))
            cat.setFont(0, f)
            cat.setForeground(0, QColor(ui.text_muted))
            cat.setSizeHint(0, QSize(0, 26))
            cat.setExpanded(True)
            cat.setText(0, f"▾ {cat_zh}")
            cat.setFirstColumnSpanned(True)
            for name, data in filtered.items():
                label = T(data.get("label", name))
                key = data.get("key", "")
                child = QTreeWidgetItem([label, key])
                child.setData(0, Qt.UserRole, data)
                child.setSizeHint(0, QSize(0, 30))
                child.setForeground(0, QColor(ui.text))
                child.setTextAlignment(0, Qt.AlignLeft | Qt.AlignVCenter)
                child.setForeground(1, QColor(ui.text_muted))
                child.setTextAlignment(1, Qt.AlignRight | Qt.AlignVCenter)
                child.setToolTip(
                    0, T("命令: {label}\n快捷键: {key}\nCAD 命令: {desc}\n\n"
                         "拖拽到圆盘扇区即可新增/更换，也可左键应用到选中扇区")
                    .format(label=label, key=key,
                            desc=data.get("description", "")))
                cat.addChild(child)
            self.preset_tree.addTopLevelItem(cat)
        self._update_expand_btn()

    # ========== 方案操作 ==========

    def _add_profile(self):
        name, ok = QInputDialog.getText(self, T("新增配置方案"), T("请输入方案名称:"))
        if not ok or not name.strip():
            return
        name = name.strip()
        if name in self.config.get("profiles", {}):
            QMessageBox.warning(self, T("错误"), T("方案「{name}」已存在").format(name=name))
            return
        target, ok = QInputDialog.getItem(self, T("选择目标软件"),
                                          T("适用的 CAD 软件:"),
                                          ["AutoCAD", T("中望CAD")], 0, False)
        if not ok:
            return
        tgt = "autocad" if target == "AutoCAD" else "zwcad"
        self._push_undo()
        ok, err = add_profile(
            self.config, name, tgt,
            self.config.get("settings", {}).get("sector_count", 8), tr=T)
        if not ok:
            QMessageBox.warning(self, T("错误"), err)
            return
        self._refresh_profiles()
        self._load_profile(name)
        self._autosave_timer.start()

    def _copy_profile(self):
        new_name, ok = QInputDialog.getText(self, T("复制配置方案"),
                                            T("请输入新方案名称:"),
                                            text=f"{self.current_profile}-副本")
        if not ok or not new_name.strip():
            return
        new_name = new_name.strip()
        if new_name in self.config.get("profiles", {}):
            QMessageBox.warning(self, T("错误"),
                                T("方案「{name}」已存在").format(name=new_name))
            return
        self._push_undo()
        ok, err = copy_profile(self.config, self.current_profile, new_name, tr=T)
        if not ok:
            QMessageBox.warning(self, T("错误"), err)
            return
        self._refresh_profiles()
        self._load_profile(new_name)
        self._autosave_timer.start()

    def _rename_profile(self):
        new_name, ok = QInputDialog.getText(self, T("重命名配置方案"), T("请输入新名称:"),
                                            text=self.current_profile)
        if not ok or not new_name.strip() or new_name.strip() == self.current_profile:
            return
        new_name = new_name.strip()
        if new_name in self.config.get("profiles", {}):
            QMessageBox.warning(self, T("错误"),
                                T("方案「{name}」已存在").format(name=new_name))
            return
        self._push_undo()
        ok, err = rename_profile(self.config, self.current_profile, new_name, tr=T)
        if not ok:
            QMessageBox.warning(self, T("错误"), err)
            return
        self.current_profile = new_name
        self._refresh_profiles()
        self._autosave_timer.start()

    def _export_profile(self):
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        if not profile:
            QMessageBox.warning(self, T("提示"), T("没有可导出的配置"))
            return
        path, _ = QFileDialog.getSaveFileName(
            self, T("导出方案"), f"{self.current_profile}.json",
            T("JSON 文件 (*.json)"))
        if not path:
            return
        ok, err = export_profile(profile, path, tr=T)
        if not ok:
            QMessageBox.warning(self, T("错误"), err)
            return
        self._set_status(f"{T('已从')} {path} {T('导出')}")

    def _import_profile(self):
        path, _ = QFileDialog.getOpenFileName(
            self, T("导入方案"), "", T("JSON 文件 (*.json)"))
        if not path:
            return
        ok, data = load_profile_data(path, tr=T)
        if not ok:
            QMessageBox.warning(self, T("错误"), data)
            return
        self._push_undo()
        profile = self.config.get("profiles", {}).get(self.current_profile, {})
        apply_profile_data(profile, data)
        self.preview.update()
        self._set_status(T("已从 {path} 导入配置").format(path=path))
        self._autosave_timer.start()

    def _delete_profile(self):
        if len(self.config.get("profiles", {})) <= 1:
            QMessageBox.warning(self, T("错误"), T("至少保留一个配置方案"))
            return
        if QMessageBox.question(self, T("确认"),
                                T("确定要删除「{name}」吗?").format(
                                    name=self.current_profile)) != QMessageBox.Yes:
            return
        self._push_undo()
        ok, err = delete_profile(self.config, self.current_profile, tr=T)
        if not ok:
            QMessageBox.warning(self, T("错误"), err)
            return
        remaining = list(self.config.get("profiles", {}).keys())
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
        self._set_status(T("已撤销"))

    def _redo(self):
        if not self._redo_stack:
            return
        after = self._redo_stack.pop()
        self._undo_stack.append(copy.deepcopy(self.config))
        self._restore_config(after)
        self._update_undo_btns()
        self._set_status(T("已重做"))

    def _restore_config(self, cfg):
        self.config = cfg
        self._popup.set_settings(self.config.get("settings", {}))
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
        self._set_status(T("✓ 已保存") if ok else T("保存失败"))
        if ok and self.on_save:
            self.on_save(self.config)

    def _frame_intersects_any_screen(self) -> bool:
        """窗口矩形是否至少部分落在某个屏幕的可用区域内"""
        rect = self.frameGeometry()
        for scr in QApplication.screens():
            if rect.intersects(scr.availableGeometry()):
                return True
        return False

    def _center_on_primary(self):
        """把窗口移到主屏可用区中央（窗口位置异常时的兜底）"""
        scr = QApplication.primaryScreen()
        if scr is None:
            return
        geo = scr.availableGeometry()
        self.move(geo.center().x() - self.width() // 2,
                  geo.center().y() - self.height() // 2)

    def _validate_geometry(self):
        """窗口映射后校验几何：屏幕外则居中并清掉坏记忆，隐藏则重新显示"""
        try:
            if not self._frame_intersects_any_screen():
                self._center_on_primary()
                # 清掉异常的位置记忆，免下次启动再恢复屏幕外位置
                try:
                    QSettings("CADGesture", "CADGesture").remove("config_win_geometry")
                except Exception:
                    pass
            if not self.isVisible():
                self.show()
                self.raise_()
                self.activateWindow()
        except Exception:
            pass

    def closeEvent(self, e):
        # 只在窗口位于屏幕内时记忆位置；屏幕外（拔掉副屏/分辨率变化遗留）

        # 不保存，避免下次启动恢复不可见位置

        try:

            if self._frame_intersects_any_screen():

                QSettings("CADGesture", "CADGesture").setValue(

                    "config_win_geometry", self.saveGeometry())

            else:

                QSettings("CADGesture", "CADGesture").remove("config_win_geometry")

        except Exception:

            pass

        remove_listener(self._lang_listener)
        # 设置页防抖中的修改先落盘（各页共享同一 config 对象）
        for page in self._setting_pages.values():
            try:
                page.flush_save()
            except Exception:
                pass
        if self._autosave_timer.isActive():
            self._autosave_timer.stop()
            self._do_save()
        if self.on_save:
            self.on_save(self.config)
        super().closeEvent(e)


def open_config_gui(on_save=None, on_check_update=None, master=None):
    """打开配置界面（返回窗口实例以便保持引用）"""
    win = QConfigGUI(on_save=on_save, on_check_update=on_check_update)
    win.show()
    win.raise_()
    win.activateWindow()
    return win
