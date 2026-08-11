"""设置分类页面 — 每个分类独立一页（由侧边栏导航切换进入）

页面（与侧边栏分类一一对应，qt_config_gui 将其加入 QStackedWidget）：
- AppearancePage  外观与尺寸：界面模式、主题、自定义主色、不透明度、字号 + 圆盘大小/半径/屏幕内限制 + 实时预览
- TriggerPage     触发与反馈：触发按键、长按延迟、触发距离、手势轨迹线 + 命令反馈提示
- GeneralPage     常规：语言、启动项、检查更新
- MaintenancePage 维护：配置目录、方案操作、备份恢复、手势测试入口
- TestPage        手势测试页保留在页面栈中，但不在侧边栏（由维护页按钮进入）

公共基类 _BasePage 提供：slider_row / save / refresh 骨架 / retranslate 钩子。
回调属性（由 qt_config_gui 注入）：
- on_saved / on_check_update / on_import / on_export / on_open_dir
- on_ui_mode_changed(mode)   界面模式切换（主窗口重建全局 QSS）
- on_language_changed(lang)  语言切换（主窗口调 i18n.set_language）
"""

from PySide6.QtCore import QPoint, QPointF, Qt, QTimer
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog,
                               QComboBox, QFileDialog, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSlider, QSpinBox, QToolTip, QVBoxLayout, QWidget,
                               QMessageBox)

from src.config_manager import (save_config, get_auto_start, set_auto_start,
                                get_config_path, set_config_dir,
                                reset_config_dir, _default_config)
from src.i18n import T
from src.menu_geometry import scaled_radii
from src.theme import (get_ui, MENU_THEMES, make_custom_theme,
                       make_light_theme, theme_from_settings,
                       effective_ui_mode, FONT_XS, font_px, _CUSTOM_DEFAULTS)
from src.qt_renderer import (draw_shadow, draw_ring, draw_center,
                             INNER, OUTER, EXTENSION)



def _tile_pixmap(t, w=96, h=96) -> QPixmap:
    """离屏绘制迷你圆盘缩略图（主题色板用）"""
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = w / 2
    draw_shadow(p, c, c, 18)
    draw_ring(p, c, c, 12, 34, 8, {}, t.inner, layer=INNER, sel=("inner", 0))
    draw_ring(p, c, c, 34, 42, 8, {}, t.outer, layer=OUTER)
    draw_center(p, c, c, 12, t, w)
    p.end()
    return pm


def _custom_tile_pixmap(w=96, h=96) -> QPixmap:
    """自定义主题占位图：多彩渐变圆 + 问号"""
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = w / 2
    r = 46
    grad = QRadialGradient(c, c, r)
    for i, col in enumerate(("#6fa3d8", "#4ec9a0", "#7fb069", "#d9a545",
                                 "#e08a5e", "#d98a8a", "#c084d9", "#9d8cf0")):
        grad.setColorAt(i / 8, QColor(col))
    grad.setColorAt(1, QColor("#2a3340"))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawEllipse(QPointF(c, c), r, r)
    p.setPen(QColor("#ffffff"))
    f = QFont("Microsoft YaHei")
    f.setPixelSize(font_px(26))
    f.setBold(True)
    p.setFont(f)
    p.drawText(QPoint(c - 14, c + 12), "自")
    p.end()
    return pm


class _ThemeTile(QPushButton):
    """主题色板格：图标 + 名称（文字语言切换时可更新）"""

    def __init__(self, text: str, pixmap, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(text)
        self.setProperty("class", "themeTile")
        lay = QVBoxLayout(self)
        lay.setContentsMargins(8, 8, 8, 7)
        lay.setSpacing(5)
        self._icon = QLabel()
        self._icon.setPixmap(pixmap)
        self._icon.setAlignment(Qt.AlignCenter)
        lay.addWidget(self._icon, 1)
        self._text = QLabel(text)
        self._text.setAlignment(Qt.AlignCenter)
        self._text.setMinimumHeight(16)
        lay.addWidget(self._text, 0)
        self.setMinimumSize(112, 132)

    def set_icon_pixmap(self, pixmap):
        self._icon.setPixmap(pixmap)

    def set_label(self, text: str):
        self._text.setText(text)
        self.setToolTip(text)


class _MenuPreview(QWidget):
    """圆盘预览：用当前方案的真实命令数据绘制（尺寸页右侧预览）"""

    def __init__(self, config=None, profile=None, parent=None):
        super().__init__(parent)
        self.config = config or {}
        self.profile = profile
        self.setMinimumSize(400, 400)

    def set_data(self, config, profile):
        self.config = config
        self.profile = profile
        self.update()

    def paintEvent(self, e):
        p = QPainter(self)
        p.setRenderHint(QPainter.Antialiasing)
        op = self.config.get("settings", {}).get("menu_opacity", 0.95)
        p.setOpacity(max(0.3, min(1.0, op)))
        s = self.config.get("settings", {})
        r = scaled_radii(s)
        dead, inner, outer, ext = (r["dead_zone_radius"], r["ring_radius"],
                                   r["outer_ring_radius"], r["ext_ring_radius"])
        n = int(s.get("sector_count", 8))
        theme = theme_from_settings(s)
        fs = float(s.get("menu_font_scale", 100)) / 100.0

        avail = min(self.width(), self.height()) / 2 - 24
        fit = avail / ext if ext else 1.0
        cx, cy = self.width() / 2, self.height() / 2
        prof = self.profile or {}

        draw_shadow(p, cx, cy, ext * fit)
        draw_ring(p, cx, cy, outer * fit, ext * fit, n,
                  prof.get("extension_sectors", {}), theme.extension,
                  layer=EXTENSION, placeholder=True, font_scale=fs)
        draw_ring(p, cx, cy, inner * fit, outer * fit, n,
                  prof.get("outer_sectors", {}), theme.outer,
                  layer=OUTER, placeholder=True, font_scale=fs)
        draw_ring(p, cx, cy, dead * fit, inner * fit, n,
                  prof.get("sectors", {}), theme.inner,
                  layer=INNER, placeholder=True, font_scale=fs)
        name = prof.get("name", "") if prof else ""
        draw_center(p, cx, cy, dead * fit, theme,
                    min(self.width(), self.height()), "", name, font_scale=fs)

        # 底部标注各层半径与实际直径
        p.setOpacity(1.0)
        p.setPen(QColor(get_ui().text_muted))
        f = QFont("Microsoft YaHei")
        f.setPixelSize(font_px(FONT_XS))
        p.setFont(f)
        p.drawText(6, self.height() - 6,
                   T("第一圈 {inner}px · 第二圈 {outer}px · 最外圈 {ext}px   实际直径 {dia}px")
                   .format(inner=inner, outer=outer, ext=ext, dia=ext * 2))
        p.end()


class _HelpIcon(QLabel):
    """说明图标：选项标签后的 "?" 圆圈，鼠标悬浮立即显示说明"""

    def __init__(self, help_zh: str, parent=None):
        super().__init__("?", parent)
        self.setProperty("class", "helpIcon")
        self.setFixedSize(16, 16)
        self.setAlignment(Qt.AlignCenter)
        self.setCursor(Qt.PointingHandCursor)
        self.setAttribute(Qt.WA_Hover)
        self._help_zh = help_zh

    def set_help(self, zh: str):
        """语言切换后刷新说明文案"""
        self._help_zh = zh

    def help_text(self) -> str:
        return T(self._help_zh)

    def enterEvent(self, e):
        QToolTip.showText(
            self.mapToGlobal(QPoint(0, self.height())),
            self.help_text(), self)
        super().enterEvent(e)

    def leaveEvent(self, e):
        QToolTip.hideText()
        super().leaveEvent(e)


class _BasePage(QWidget):
    """设置分类页基类：公共布局骨架 + 公共能力（滑杆行/保存/刷新/重译）"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.on_saved = None
        self.on_check_update = None
        self.on_import = None
        self.on_export = None
        self.on_open_dir = None
        self.on_backup = None
        self.on_restore = None
        self.on_ui_mode_changed = None
        self.on_language_changed = None
        self.on_ui_font_changed = None   # 界面字号实时变化回调
        self.on_open_test = None         # 打开手势测试页（维护页按钮）
        self._slider_labels = {}       # key -> (name_lb, unit, spinbox, divisor, slider)
        self._tr = []                  # [(widget, zh_text)] 语言切换刷新
        self._help_items = []          # [_HelpIcon] 语言切换刷新 tooltip

        # 保存防抖：连续修改 500ms 内合并成一次写盘（与编辑页 autosave 一致），
        # 避免每个勾选/滑杆松手都触发「写盘 → 全量重载 → 重建全局 QSS」
        self._save_dirty = False
        self._save_timer = QTimer(self)
        self._save_timer.setSingleShot(True)
        self._save_timer.setInterval(500)
        self._save_timer.timeout.connect(self._save_now)

        # 页面骨架：标题 + 滚动内容区
        outer = QVBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.setSpacing(14)
        self.title = QLabel("")
        self.title.setObjectName("pageTitle")
        outer.addWidget(self.title)
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self._content = QWidget()
        self.body = QVBoxLayout(self._content)
        self.body.setSpacing(14)
        self.body.setContentsMargins(0, 0, 0, 0)
        self.scroll.setWidget(self._content)
        outer.addWidget(self.scroll, 1)

    # ---- 语言 / 主题钩子 ----

    def register_text(self, widget, zh: str):
        """注册语言刷新项：语言切换时 widget 显示 T(zh)"""
        self._tr.append((widget, zh))

    def retranslate(self):
        """语言切换时刷新本页文本（子类覆盖并调用 super）"""
        for w, zh in self._tr:
            try:
                w.setText(T(zh))
            except Exception:
                pass
        for icon in self._help_items:
            try:
                icon.set_help(icon._help_zh)
            except Exception:
                pass
        self.title.setText(T(self.title_zh))

    # ---- 公共控件 ----

    def _slider_row(self, zh_name, key, lo, hi, unit,
                    on_change=None, divisor=1.0, container=None, help=None):
        """添加统一的滑杆行：名称 | 滑杆 | 可输入数字。

        滑杆和右侧数字框共用同一份整数范围，数字框显示经过 divisor 换算
        前的编辑值。拖动时实时更新预览，松手或输入数字后通过防抖保存。
        """
        row = QHBoxLayout()
        row.setSpacing(10)
        name = QLabel(T(zh_name))
        name.setMinimumWidth(96)
        row.addWidget(name)
        if help:
            row.addWidget(self._help(help))
        raw = self.config.get("settings", {}).get(key, lo)
        val = int(round(raw * divisor)) if divisor != 1.0 else int(raw)
        val = max(lo, min(hi, val))

        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        spin = QSpinBox()
        spin.setRange(lo, hi)
        spin.setValue(val)
        spin.setSuffix(unit)
        spin.setFixedWidth(82)
        spin.setAlignment(Qt.AlignRight)
        spin.setKeyboardTracking(False)
        self._slider_labels[key] = (name, unit, spin, divisor, sl)
        syncing = {"value": False}

        def _write(v, k=key, d=divisor):
            self.config.setdefault("settings", {})[k] = v / d if d != 1.0 else v
            if on_change:
                on_change()

        def _on_slider(v):
            if syncing["value"]:
                return
            syncing["value"] = True
            spin.setValue(v)
            syncing["value"] = False
            _write(v)

        def _on_spin(v):
            if syncing["value"]:
                return
            syncing["value"] = True
            sl.setValue(v)
            syncing["value"] = False
            _write(v)
            self._save()

        sl.valueChanged.connect(_on_slider)
        spin.valueChanged.connect(_on_spin)
        sl.sliderReleased.connect(self._save)  # 拖动结束才保存
        row.addWidget(sl, 1)
        row.addWidget(spin)
        (container or self.body).addLayout(row)
        self.register_text(name, zh_name)
        return sl, spin

    def _section(self, zh: str, container=None):
        """分组小标题：把页面按逻辑分段，避免一长列平铺"""
        lb = QLabel(T(zh))
        lb.setObjectName("sectionTitle")
        self.register_text(lb, zh)
        (container or self.body).addWidget(lb)
        return lb

    def _help(self, zh: str) -> "_HelpIcon":
        """创建一个说明图标并注册（调用方负责把它加入布局）"""
        icon = _HelpIcon(zh, self)
        self._help_items.append(icon)
        return icon

    def _check_row(self, zh, key, default, container=None, help=None,
                   toggled=None):
        """一行勾选项：名称（可带说明图标）。toggled 覆盖默认写配置行为"""
        chk = QCheckBox(T(zh))
        chk.setChecked(bool(self.config.get("settings", {}).get(key, default)))
        if toggled is None:
            chk.toggled.connect(lambda b: self._set(key, b))
        else:
            chk.toggled.connect(toggled)
        self.register_text(chk, zh)
        row = QHBoxLayout()
        row.setSpacing(6)
        row.addWidget(chk)
        if help:
            row.addWidget(self._help(help))
        row.addStretch(1)
        (container or self.body).addLayout(row)
        return chk

    # ---- 保存 / 配置 ----

    def _set(self, key, value):
        self.config.setdefault("settings", {})[key] = value
        self._save()

    def _save(self):
        """设置变更后延迟落盘（500ms 合并连续修改）"""
        self._save_dirty = True
        self._save_timer.start()

    def _save_now(self):
        """防抖定时器到点 / 窗口关闭前落盘"""
        if not self._save_dirty:
            return
        self._save_dirty = False
        ok = save_config(self.config)
        if ok and self.on_saved:
            self.on_saved()

    def flush_save(self):
        """窗口关闭前强制落盘未保存的修改"""
        if self._save_timer.isActive():
            self._save_timer.stop()
            self._save_now()

    def refresh(self, config, profile=None):
        """进入页面时同步控件状态（子类覆盖）"""
        self.config = config
        self._refresh_sliders()

    def _refresh_sliders(self):
        for key, (name_lb, unit, spin, divisor, sl) in self._slider_labels.items():
            raw = self.config.get("settings", {}).get(key, 0)
            val = int(round(raw * divisor)) if divisor != 1.0 else int(raw)
            sl.blockSignals(True)
            spin.blockSignals(True)
            sl.setValue(val)
            spin.setValue(val)
            spin.blockSignals(False)
            sl.blockSignals(False)


class AppearancePage(_BasePage):
    """外观与尺寸：界面模式、主题、自定义主色、不透明度、字号 + 圆盘大小/半径/屏幕内限制 + 实时预览"""

    _RADIUS_KEYS = ("dead_zone_radius", "ring_radius",
                    "outer_ring_radius", "ext_ring_radius")
    _RADIUS_GAP = 10  # 相邻圈层最小间隔（px）
    _RADIUS_DEFAULTS = {"dead_zone_radius": 24, "ring_radius": 70,
                        "outer_ring_radius": 135, "ext_ring_radius": 185}

    def __init__(self, config, parent=None):
        self.title_zh = "外观与尺寸"
        super().__init__(config, parent)
        self.title.setText(T(self.title_zh))

        # 横向：左设置项 + 右实时预览
        hbox = QHBoxLayout()
        hbox.setSpacing(24)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)

        # 界面模式（浅/深）
        mode_row = QHBoxLayout()
        mode_row.setSpacing(10)
        self._lb_mode = QLabel(T("界面模式"))
        self.register_text(self._lb_mode, "界面模式")
        mode_row.addWidget(self._lb_mode)
        self.mode_combo = QComboBox()
        self.mode_combo.addItem(T("深色"), "dark")
        self.mode_combo.addItem(T("浅色"), "light")
        self.mode_combo.addItem(T("跟随系统"), "system")
        self.mode_combo.currentIndexChanged.connect(self._on_mode_changed)
        mode_row.addWidget(self.mode_combo)
        mode_row.addStretch(1)
        lv.addLayout(mode_row)

        # 圆盘主题色板网格（3 列）
        grid = QGridLayout()
        grid.setSpacing(12)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        self._theme_group = QButtonGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_tiles = {}       # theme name -> tile
        self._tile_by_btn = {}       # button -> theme name or "custom"
        for i, th in enumerate(MENU_THEMES.values()):
            tile = _ThemeTile(th.label, self._tile_pixmap_for(th))
            self._theme_tiles[th.name] = tile
            self._theme_group.addButton(tile)
            self._tile_by_btn[tile] = th.name
            grid.addWidget(tile, i // 3, i % 3)
        i = len(MENU_THEMES)
        self._custom_tile = _ThemeTile("自定义", _custom_tile_pixmap())
        self._theme_group.addButton(self._custom_tile)
        self._tile_by_btn[self._custom_tile] = "custom"
        grid.addWidget(self._custom_tile, i // 3, i % 3)
        self._theme_group.buttonClicked.connect(self._on_theme_picked)
        lv.addLayout(grid)

        # 自定义主题四个颜色（选"自定义"时显示）
        self._custom_color_row = QWidget()
        cc = QVBoxLayout(self._custom_color_row)
        cc.setContentsMargins(0, 0, 0, 0)
        cc.setSpacing(8)
        self._color_fields = {}   # key -> 色块按钮
        for key, zh in (("custom_text", "文字颜色"),
                        ("custom_highlight", "高亮颜色"),
                        ("custom_bg", "背景颜色"),
                        ("custom_hover", "悬浮颜色")):
            row = QHBoxLayout()
            row.setSpacing(10)
            lb = QLabel(T(zh))
            self.register_text(lb, zh)
            row.addWidget(lb)
            btn = QPushButton()
            btn.setFixedSize(28, 22)
            btn.setCursor(Qt.PointingHandCursor)
            btn.setToolTip(T("点击选择颜色"))
            btn.clicked.connect(
                lambda _=False, k=key: self._pick_custom_color(k))
            self._color_fields[key] = btn
            row.addWidget(btn)
            row.addStretch(1)
            cc.addLayout(row)
        self._custom_color_row.hide()
        lv.addWidget(self._custom_color_row)

        # 不透明度（加进左列）
        self._opacity_slider, self._opacity_label = self._slider_row(
            "不透明度", "menu_opacity", 30, 100, "%",
            on_change=self._update_preview, divisor=100.0, container=lv,
            help="圆盘的透明程度。数值越低越透明，背后的图纸越清楚。")

        # 文字大小：圆盘 / 界面（百分比，100 = 默认）
        self._menu_font_slider, self._menu_font_label = self._slider_row(
            "圆盘文字大小", "menu_font_scale", 70, 160, "%",
            on_change=self._update_preview, container=lv,
            help="圆盘扇区内命令文字的缩放比例，100% 为默认大小。")
        self._ui_font_slider, self._ui_font_label = self._slider_row(
            "界面文字大小", "ui_font_scale", 75, 160, "%",
            on_change=self._on_ui_font_changed, container=lv,
            help="设置窗口界面的文字缩放，调整后立即生效。")

        # ===== 圆盘尺寸（原「圆盘尺寸」分类合并进来） =====
        self._section("圆盘大小", lv)
        self._size_sliders = {}
        sl, lb = self._slider_row(
            "整体圆盘大小", "menu_scale", 50, 150, "%",
            on_change=self._on_size_changed, container=lv,
            help="按百分比整体放大或缩小圆盘，所有圈层一起变化。")
        self._size_sliders["menu_scale"] = sl
        self._section("圈层半径", lv)
        for key, text, lo, hi, unit, help_text in (
                ("dead_zone_radius", "中心圆半径", 8, 60, "px",
                 "圆心附近的空白区域。半径越大越容易从中心起手瞄准，但会压缩第一圈可用面积。"),
                ("ring_radius", "第一圈半径", 40, 160, "px", None),
                ("outer_ring_radius", "第二圈半径", 90, 260, "px", None),
                ("ext_ring_radius", "最外圈半径", 140, 360, "px", None)):
            sl, lb = self._slider_row(text, key, lo, hi, unit,
                                      on_change=self._on_size_changed,
                                      container=lv, help=help_text)
            self._size_sliders[key] = sl
        self._apply_radius_constraints()
        self._section("显示", lv)
        self.chk_clamp = self._check_row(
            "显示限制在屏幕范围内", "menu_clamp_to_screen", True,
            container=lv,
            help="开启后圆盘整体保持完整可见；关闭后圆心始终对准按下位置，靠近屏幕边缘可能被裁剪。")
        lv.addStretch(1)

        hbox.addWidget(left, 1)
        self.preview = _MenuPreview(self.config)
        hbox.addWidget(self.preview, 0, Qt.AlignHCenter)
        self.body.addLayout(hbox)

    def _update_preview(self):
        if getattr(self, "preview", None):
            self.preview.update()

    def _on_ui_font_changed(self):
        """界面字号滑杆拖动：实时重建界面 QSS（由主窗口注入回调）"""
        if self.on_ui_font_changed:
            self.on_ui_font_changed()

    # ---- 圆盘尺寸 ----

    def _on_size_changed(self):
        self._apply_radius_constraints()
        self.preview.update()

    def _apply_radius_constraints(self):
        """按顺序夹紧四个半径：中心圆半径 < 第一圈半径 < 第二圈半径 < 最外圈半径。
        更新滑块范围并写回夹紧后的配置值，避免圈层重叠或倒序。"""
        s = self.config.setdefault("settings", {})
        d = self._RADIUS_DEFAULTS
        keys = self._RADIUS_KEYS
        vals = {k: int(s.get(k, d[k])) for k in keys}
        bounds = {}
        for i, k in enumerate(keys):
            if i == 0:
                v_min, v_max = 8, vals[keys[1]] - self._RADIUS_GAP
            elif i == len(keys) - 1:
                v_min, v_max = vals[keys[i - 1]] + self._RADIUS_GAP, 360
            else:
                v_min, v_max = (vals[keys[i - 1]] + self._RADIUS_GAP,
                                vals[keys[i + 1]] - self._RADIUS_GAP)
            v_max = max(v_min, v_max)
            vals[k] = max(v_min, min(v_max, vals[k]))
            bounds[k] = (v_min, v_max)
        for k in keys:
            s[k] = vals[k]
            sl = self._size_sliders.get(k)
            if sl is None:
                continue
            v_min, v_max = bounds[k]
            sl.blockSignals(True)
            sl.setRange(v_min, v_max)
            sl.setValue(vals[k])
            sl.blockSignals(False)
            spin = self._slider_labels[k][2]
            spin.blockSignals(True)
            spin.setRange(v_min, v_max)
            spin.setValue(vals[k])
            spin.blockSignals(False)

    # ---- 界面模式 ----

    def _on_mode_changed(self, idx):
        mode = self.mode_combo.itemData(idx)
        s = self.config.setdefault("settings", {})
        if s.get("ui_mode") != mode:
            s["ui_mode"] = mode
            self._save()
            if self.on_ui_mode_changed:
                self.on_ui_mode_changed(mode)
        # 界面模式切换：主题色板缩略图跟随浅/深显示对应版本
        self._refresh_theme_thumbnails()

    def _tile_pixmap_for(self, th):
        """按当前界面模式生成主题缩略图（浅色模式显示浅色版圆盘）"""
        if effective_ui_mode(self.config.get("settings", {}).get("ui_mode", "dark")) == "light":
            return _tile_pixmap(make_light_theme(th))
        return _tile_pixmap(th)

    def _refresh_theme_thumbnails(self):
        """刷新全部主题格缩略图（界面模式切换后调用）"""
        for name, tile in self._theme_tiles.items():
            tile.set_icon_pixmap(self._tile_pixmap_for(MENU_THEMES[name]))
        self._refresh_custom_tile()
        self.preview.update()

    # ---- 主题 ----

    def _on_theme_picked(self, btn):
        name = self._tile_by_btn[btn]
        self.config.setdefault("settings", {})["menu_theme"] = name
        self._custom_color_row.setVisible(name == "custom")
        if name == "custom":
            self._sync_custom_colors()
            self._refresh_custom_tile()
        self._save()
        self._update_preview()

    def _pick_custom_color(self, key):
        """点击色块：取色器选色，写入对应自定义颜色项"""
        s = self.config.setdefault("settings", {})
        cur = s.get(key, _CUSTOM_DEFAULTS.get(key, "#6fa3d8"))
        col = QColorDialog.getColor(QColor(cur), self, T("选择颜色"))
        if col.isValid():
            s[key] = col.name()
            s["menu_theme"] = "custom"
            self._sync_custom_colors()
            self._refresh_custom_tile()
            self._save()
            self._update_preview()

    def _sync_custom_colors(self):
        """刷新四个色块按钮的显示颜色"""
        s = self.config.get("settings", {})
        for key, btn in self._color_fields.items():
            col = s.get(key, _CUSTOM_DEFAULTS.get(key, "#6fa3d8"))
            btn.setStyleSheet(
                f"QPushButton {{ background: {col}; border: 1px solid"
                f" #ffffff66; border-radius: 4px; }}")

    def _refresh_custom_tile(self):
        s = self.config.get("settings", {})
        t = make_custom_theme(
            s.get("custom_text", _CUSTOM_DEFAULTS["custom_text"]),
            s.get("custom_highlight", _CUSTOM_DEFAULTS["custom_highlight"]),
            s.get("custom_bg", _CUSTOM_DEFAULTS["custom_bg"]),
            s.get("custom_hover", _CUSTOM_DEFAULTS["custom_hover"]))
        if effective_ui_mode(s.get("ui_mode", "dark")) == "light":
            t = make_light_theme(t)
        self._custom_tile.set_icon_pixmap(_tile_pixmap(t))

    def retranslate(self):
        super().retranslate()
        # 界面模式下拉项
        _mode_text = {"dark": T("深色"), "light": T("浅色"), "system": T("跟随系统")}
        for i, mode in enumerate(("dark", "light", "system")):
            self.mode_combo.setItemText(i, _mode_text[mode])
        # 主题色板名称
        for name, tile in self._theme_tiles.items():
            tile.set_label(T(MENU_THEMES[name].label))
        self._custom_tile.set_label(T("自定义"))

    def refresh(self, config, profile=None):
        self.config = config
        s = config.get("settings", {})
        # 界面模式
        mode = s.get("ui_mode", "dark")
        idx = self.mode_combo.findData(mode)
        if idx >= 0:
            self.mode_combo.blockSignals(True)
            self.mode_combo.setCurrentIndex(idx)
            self.mode_combo.blockSignals(False)
        # 主题选中态
        name = s.get("menu_theme", "azure")
        try:
            self._theme_group.buttonClicked.disconnect(self._on_theme_picked)
        except (RuntimeError, TypeError):
            pass
        for tile, n in self._tile_by_btn.items():
            tile.setChecked(n == name)
        self._theme_group.buttonClicked.connect(self._on_theme_picked)
        self._custom_color_row.setVisible(name == "custom")
        if name == "custom":
            self._sync_custom_colors()
        self._refresh_theme_thumbnails()
        self._refresh_sliders()
        self.preview.set_data(config, profile)
        self._apply_radius_constraints()
        self.chk_clamp.blockSignals(True)
        self.chk_clamp.setChecked(
            config.get("settings", {}).get("menu_clamp_to_screen", True))
        self.chk_clamp.blockSignals(False)


class TriggerPage(_BasePage):
    """触发与反馈：触发按键/长按延迟/触发距离/轨迹线 + 命令反馈提示"""

    def __init__(self, config, parent=None):
        self.title_zh = "触发与反馈"
        super().__init__(config, parent)
        self.title.setText(T(self.title_zh))

        # 触发方式
        self._section("触发方式")

        # 触发按键（右键 / 中键 / 侧键）
        btn_row = QHBoxLayout()
        btn_row.setSpacing(10)
        self._lb_btn = QLabel(T("触发按键"))
        self.register_text(self._lb_btn, "触发按键")
        btn_row.addWidget(self._lb_btn)
        btn_row.addWidget(self._help(
            "按下哪个键呼出圆盘。侧键需要鼠标带前进/后退按键。"))
        self.btn_combo = QComboBox()
        self.btn_combo.addItem(T("右键"), "right")
        self.btn_combo.addItem(T("中键"), "middle")
        self.btn_combo.addItem(T("侧键 1（后退）"), "x1")
        self.btn_combo.addItem(T("侧键 2（前进）"), "x2")
        cur = config.get("settings", {}).get("trigger_button", "right")
        idx = self.btn_combo.findData(cur)
        self.btn_combo.setCurrentIndex(max(0, idx))
        self.btn_combo.currentIndexChanged.connect(self._on_btn_changed)
        btn_row.addWidget(self.btn_combo)
        btn_row.addStretch(1)
        self.body.addLayout(btn_row)

        self._hold_slider, self._hold_label = self._slider_row(
            "长按延迟", "hold_threshold_ms", 0, 200, "ms",
            help="按下后不动时，经过该时长且有小幅位移即弹出圆盘；数值越小响应越快。")
        self._trig_slider, self._trig_label = self._slider_row(
            "触发距离", "trigger_distance", 5, 40, "px",
            help="按下后滑动多少像素立即弹出圆盘。越小越灵敏，也越容易误触。")

        # 手势轨迹线（从中心引出跟随光标）
        self.chk_trail = self._check_row(
            "手势轨迹线", "gesture_trail", True,
            help="拖动时从圆心画一条跟随光标的线，帮你判断当前滑向哪个扇区。")

        # ===== 命令反馈（原「命令反馈」分类合并进来） =====
        self._section("命令反馈")
        self.chk_feedback = QCheckBox(T("显示命令反馈"))
        self.chk_feedback.setToolTip(T("执行命令后在屏幕上短暂提示"))
        self.chk_feedback.setChecked(
            config.get("settings", {}).get("command_feedback", True))
        self.chk_feedback.toggled.connect(
            lambda b: self._set("command_feedback", b))
        self.body.addWidget(self.chk_feedback)
        self.register_text(self.chk_feedback, "显示命令反馈")

        # 提示位置
        pos_row = QHBoxLayout()
        pos_row.setSpacing(10)
        self._lb_pos = QLabel(T("提示位置"))
        self.register_text(self._lb_pos, "提示位置")
        pos_row.addWidget(self._lb_pos)
        pos_row.addWidget(self._help("命令执行后，提示文字出现在屏幕的哪个位置。"))
        self.pos_combo = QComboBox()
        self.pos_combo.addItem(T("下部中间偏上"), "bottom_center")
        self.pos_combo.addItem(T("屏幕中心"), "center")
        self.pos_combo.addItem(T("顶部居中"), "top_center")
        self.pos_combo.addItem(T("右下角"), "bottom_right")
        self.pos_combo.addItem(T("左下角"), "bottom_left")
        self.pos_combo.addItem(T("左上角"), "top_left")
        self.pos_combo.addItem(T("右上角"), "top_right")
        cur = config.get("settings", {}).get("feedback_position", "bottom_center")
        idx = self.pos_combo.findData(cur)
        self.pos_combo.setCurrentIndex(max(0, idx))
        self.pos_combo.currentIndexChanged.connect(self._on_pos_changed)
        pos_row.addWidget(self.pos_combo)
        pos_row.addStretch(1)
        self.body.addLayout(pos_row)

        # 位置微调：在所选锚点基础上再平移（像素），默认 0 不动
        s = config.setdefault("settings", {})
        s.setdefault("feedback_offset_x", 0)
        s.setdefault("feedback_offset_y", 0)
        self._ox_slider, self._ox_label = self._slider_row(
            "水平偏移", "feedback_offset_x", -300, 300, "px",
            help="在所选位置基础上再平移的像素值，用于微调提示位置。")
        self._oy_slider, self._oy_label = self._slider_row(
            "垂直偏移", "feedback_offset_y", -300, 300, "px",
            help="在所选位置基础上再平移的像素值，用于微调提示位置。")

        # 提示内容：命令名称 / 快捷键
        content_row = QHBoxLayout()
        content_row.setSpacing(16)
        self.chk_name = QCheckBox(T("显示命令名称"))
        self.chk_name.setChecked(
            config.get("settings", {}).get("feedback_show_name", True))
        self.chk_name.toggled.connect(
            lambda b: self._set("feedback_show_name", b))
        content_row.addWidget(self.chk_name)
        self.chk_key = QCheckBox(T("显示快捷键"))
        self.chk_key.setChecked(
            config.get("settings", {}).get("feedback_show_key", True))
        self.chk_key.toggled.connect(
            lambda b: self._set("feedback_show_key", b))
        content_row.addWidget(self.chk_key)
        content_row.addStretch(1)
        self.body.addLayout(content_row)
        self.register_text(self.chk_name, "显示命令名称")
        self.register_text(self.chk_key, "显示快捷键")

        # 停留时长
        self._dur_slider, self._dur_label = self._slider_row(
            "提示时长", "feedback_duration_ms", 500, 3000, "ms")
        self.body.addStretch(1)

    def _on_btn_changed(self, idx):
        self._set("trigger_button", self.btn_combo.itemData(idx))

    def _on_pos_changed(self, idx):
        self._set("feedback_position", self.pos_combo.itemData(idx))

    def refresh(self, config, profile=None):
        self.config = config
        self._refresh_sliders()
        idx = self.btn_combo.findData(
            config.get("settings", {}).get("trigger_button", "right"))
        self.btn_combo.blockSignals(True)
        self.btn_combo.setCurrentIndex(max(0, idx))
        self.btn_combo.blockSignals(False)
        self.chk_trail.blockSignals(True)
        self.chk_trail.setChecked(
            config.get("settings", {}).get("gesture_trail", True))
        self.chk_trail.blockSignals(False)
        # 命令反馈
        s = config.get("settings", {})
        self.chk_feedback.blockSignals(True)
        self.chk_feedback.setChecked(s.get("command_feedback", True))
        self.chk_feedback.blockSignals(False)
        self.chk_name.blockSignals(True)
        self.chk_name.setChecked(s.get("feedback_show_name", True))
        self.chk_name.blockSignals(False)
        self.chk_key.blockSignals(True)
        self.chk_key.setChecked(s.get("feedback_show_key", True))
        self.chk_key.blockSignals(False)
        idx = self.pos_combo.findData(
            s.get("feedback_position", "bottom_center"))
        self.pos_combo.blockSignals(True)
        self.pos_combo.setCurrentIndex(max(0, idx))
        self.pos_combo.blockSignals(False)


class GeneralPage(_BasePage):
    """常规：语言、启动项、检查更新"""

    def __init__(self, config, parent=None):
        self.title_zh = "常规"
        super().__init__(config, parent)
        self.title.setText(T(self.title_zh))

        # 语言
        self._section("语言")
        lang_row = QHBoxLayout()
        lang_row.setSpacing(10)
        self._lb_lang = QLabel(T("语言"))
        self.register_text(self._lb_lang, "语言")
        lang_row.addWidget(self._lb_lang)
        self.lang_combo = QComboBox()
        self.lang_combo.addItem("简体中文", "zh")
        self.lang_combo.addItem("English", "en")
        self.lang_combo.currentIndexChanged.connect(self._on_lang_changed)
        lang_row.addWidget(self.lang_combo)
        lang_row.addStretch(1)
        self.body.addLayout(lang_row)

        # 启动
        self._section("启动")
        self.chk_open = self._check_row(
            "启动时打开此界面", "open_config_on_start", False,
            help="程序启动后自动打开设置窗口，适合第一次配置时使用。")
        self.chk_auto = self._check_row(
            "根据 CAD 窗口自动切换", "auto_switch_profile", True,
            help="打开 AutoCAD 时自动使用 AutoCAD 方案，切换到中望CAD 时自动使用对应方案。")
        self.chk_startup = self._check_row(
            "开机自启", "auto_start", False, toggled=self._on_startup,
            help="登录 Windows 后自动在后台启动本工具，无需手动打开。")

        # 更新
        self._section("更新")
        self.chk_update = self._check_row(
            "启动时检查更新", "check_update_on_start", True,
            help="每次启动自动联网检查新版本，发现更新会提示你。")
        self.btn_check_update = QPushButton(T("检查更新"))
        self.btn_check_update.setToolTip(T("立即检查是否有新版本"))
        self.btn_check_update.clicked.connect(self._on_check_update_click)
        self.body.addWidget(self.btn_check_update)
        self.body.addStretch(1)
        self.register_text(self.btn_check_update, "检查更新")

    def _on_lang_changed(self, idx):
        lang = self.lang_combo.itemData(idx)
        s = self.config.setdefault("settings", {})
        if s.get("language") != lang:
            s["language"] = lang
            self._save()
            if self.on_language_changed:
                self.on_language_changed(lang)

    def _on_check_update_click(self):
        if self.on_check_update:
            self.on_check_update()
        self.btn_check_update.setEnabled(False)
        from PySide6.QtCore import QTimer
        QTimer.singleShot(5000, lambda: self.btn_check_update.setEnabled(True))

    def _on_startup(self, checked):
        set_auto_start(checked)

    def refresh(self, config, profile=None):
        self.config = config
        s = config.get("settings", {})
        lang = s.get("language", "zh")
        idx = self.lang_combo.findData(lang)
        if idx >= 0:
            self.lang_combo.blockSignals(True)
            self.lang_combo.setCurrentIndex(idx)
            self.lang_combo.blockSignals(False)
        for w in (self.chk_open, self.chk_auto, self.chk_startup, self.chk_update):
            w.blockSignals(True)
        self.chk_open.setChecked(bool(s.get("open_config_on_start", False)))
        self.chk_auto.setChecked(bool(s.get("auto_switch_profile", True)))
        self.chk_startup.setChecked(get_auto_start())
        self.chk_update.setChecked(bool(s.get("check_update_on_start", True)))
        for w in (self.chk_open, self.chk_auto, self.chk_startup, self.chk_update):
            w.blockSignals(False)

    def retranslate(self):
        super().retranslate()


class MaintenancePage(_BasePage):
    """维护：配置目录、方案导入导出、恢复默认"""

    def __init__(self, config, parent=None):
        self.title_zh = "维护"
        super().__init__(config, parent)
        self.title.setText(T(self.title_zh))

        # 配置目录
        self._section("配置目录")
        # 配置目录行：标题 + 当前路径 + 更改/重置（同一行）
        dir_head = QHBoxLayout()
        dir_head.setSpacing(8)
        self._lb_dir_title = QLabel(T("配置目录"))
        self.register_text(self._lb_dir_title, "配置目录")
        dir_head.addWidget(self._lb_dir_title)
        dir_head.addWidget(self._help(
            "配置和方案的保存位置。默认在 %APPDATA%\\CADGesture，可迁移到其他磁盘。"))
        self._config_dir_label = QLabel(get_config_path())
        self._config_dir_label.setWordWrap(True)
        dir_head.addWidget(self._config_dir_label, 1)
        btn_change = QPushButton(T("更改"))
        btn_change.setToolTip(T("把配置迁移到自选目录（如 D 盘）"))
        btn_change.clicked.connect(self._change_config_dir)
        self.register_text(btn_change, "更改")
        btn_reset_dir = QPushButton(T("重置"))
        btn_reset_dir.setToolTip(T("恢复默认 %APPDATA%\\CADGesture"))
        btn_reset_dir.clicked.connect(self._restore_config_dir)
        self.register_text(btn_reset_dir, "重置")
        dir_head.addWidget(btn_change, 0, Qt.AlignVCenter)
        dir_head.addWidget(btn_reset_dir, 0, Qt.AlignVCenter)
        self.body.addLayout(dir_head)

        # 方案操作
        self._section("方案操作")
        row = QHBoxLayout()
        row.setSpacing(8)
        btn_import = QPushButton(T("导入方案"))
        btn_import.clicked.connect(lambda: self.on_import() if self.on_import else None)
        self.register_text(btn_import, "导入方案")
        btn_export = QPushButton(T("导出方案"))
        btn_export.clicked.connect(lambda: self.on_export() if self.on_export else None)
        self.register_text(btn_export, "导出方案")
        btn_dir = QPushButton(T("打开配置目录"))
        btn_dir.clicked.connect(lambda: self.on_open_dir() if self.on_open_dir else None)
        self.register_text(btn_dir, "打开配置目录")
        btn_test = QPushButton(T("打开手势测试"))
        btn_test.setToolTip(T("打开手势测试页，移动鼠标查看各扇区将触发的命令"))
        btn_test.clicked.connect(
            lambda: self.on_open_test() if self.on_open_test else None)
        self.register_text(btn_test, "打开手势测试")
        btn_reset = QPushButton(T("恢复默认"))
        btn_reset.setProperty("class", "danger")
        btn_reset.setToolTip(T("把当前方案的三圈命令恢复为默认内容"))
        btn_reset.clicked.connect(self._reset_defaults)
        self.register_text(btn_reset, "恢复默认")
        row.addWidget(btn_import)
        row.addWidget(btn_export)
        row.addWidget(btn_dir)
        row.addWidget(btn_test)
        row.addStretch(1)
        row.addWidget(btn_reset)
        self.body.addLayout(row)

        # 整包配置备份 / 恢复
        self._section("备份与恢复")
        row2 = QHBoxLayout()
        row2.setSpacing(8)
        btn_backup = QPushButton(T("备份配置"))
        btn_backup.setToolTip(T("把全部配置（设置 + 方案）备份到文件"))
        btn_backup.clicked.connect(
            lambda: self.on_backup() if self.on_backup else None)
        self.register_text(btn_backup, "备份配置")
        btn_restore = QPushButton(T("恢复配置"))
        btn_restore.setToolTip(T("从备份文件恢复全部配置"))
        btn_restore.clicked.connect(
            lambda: self.on_restore() if self.on_restore else None)
        self.register_text(btn_restore, "恢复配置")
        row2.addWidget(btn_backup)
        row2.addWidget(btn_restore)
        row2.addStretch(1)
        self.body.addLayout(row2)
        self.body.addStretch(1)

    def _change_config_dir(self):
        d = QFileDialog.getExistingDirectory(self, T("选择配置目录"))
        if not d:
            return
        try:
            set_config_dir(d)
        except Exception as e:
            QMessageBox.warning(self, T("更改失败"), T("无法使用该目录：{e}").format(e=e))
            return
        self._config_dir_label.setText(get_config_path())
        self._save()
        QMessageBox.information(
            self, T("配置目录已更改"),
            T("配置已迁移到：\n{path}\n\n目录位置已记住，下次启动自动使用。")
            .format(path=get_config_path()))

    def _restore_config_dir(self):
        try:
            reset_config_dir()
        except Exception as e:
            QMessageBox.warning(self, T("恢复失败"), str(e))
            return
        self._config_dir_label.setText(get_config_path())
        self._save()
        QMessageBox.information(
            self, T("已恢复默认"),
            T("配置目录已恢复为：\n{path}").format(path=get_config_path()))

    def _reset_defaults(self):
        if QMessageBox.question(self, T("确认"),
                                T("确定要重置所有配置为默认值吗?")) != QMessageBox.Yes:
            return
        self.config = _default_config()
        self.refresh(self.config)
        self._save()
        QMessageBox.information(self, T("提示"), T("已重置为默认配置"))

    def refresh(self, config, profile=None):
        self.config = config
        self._config_dir_label.setText(get_config_path())


class TestPage(_BasePage):
    """手势测试：真实配置圆盘预览，移动鼠标查看扇区命令"""

    _LAYER_KEY = {"inner": "sectors", "outer": "outer_sectors",
                  "extension": "extension_sectors"}

    def __init__(self, config, parent=None):
        self.title_zh = "测试"
        super().__init__(config, parent)
        self.title.setText(T(self.title_zh))

        tip = QLabel(T("在圆盘上移动鼠标查看各扇区命令；悬停处会显示将触发的命令。"))
        tip.setWordWrap(True)
        tip.setObjectName("pageSub")
        self.body.addWidget(tip)

        from src.qt_preview import QRadialPreview
        self.preview = QRadialPreview()
        self.preview.setMinimumSize(420, 420)
        self.body.addWidget(self.preview, 0, Qt.AlignHCenter)

        self.info = QLabel("")
        self.info.setAlignment(Qt.AlignCenter)
        self.info.setMinimumHeight(28)
        self.body.addWidget(self.info)

        # 低频轮询 hover 状态，实时显示将触发命令
        self._timer = QTimer(self)
        self._timer.setInterval(100)
        self._timer.timeout.connect(self._update_info)
        self._timer.start()

        self.body.addStretch(1)

    def refresh(self, config, profile=None):
        self.config = config
        self.preview.update_config(config)
        if profile is None:
            profile = config.get("profiles", {}).get(
                config.get("settings", {}).get(
                    "active_profile", "AutoCAD-常用"))
        self.preview.set_data(config, profile)
        self._update_info()

    def _update_info(self):
        try:
            if not self.preview.hovered:
                if self.info.text():
                    self.info.setText("")
                return
            layer, idx = self.preview.hovered
            key = self._LAYER_KEY.get(layer, "sectors")
            cfg = (self.preview.profile or {}).get(key, {}).get(str(idx), {})
            if cfg.get("label") or cfg.get("key"):
                name = cfg.get("label", "") or cfg.get("description", "")
                key_text = cfg.get("key", "")
                text = T("将触发：{name}    快捷键 {key}").format(
                    name=name,
                    key=key_text.upper() if key_text else "—")
            else:
                text = T("空扇区（未设置命令）")
            if text != self.info.text():
                self.info.setText(text)
        except Exception:
            pass
