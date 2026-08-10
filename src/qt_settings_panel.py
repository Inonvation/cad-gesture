"""设置分类页面 — 每个分类独立一页（由侧边栏导航切换进入）

页面（与侧边栏分类一一对应，qt_config_gui 将其加入 QStackedWidget）：
- AppearancePage  外观：界面模式（浅/深）、圆盘主题色板、自定义主色、不透明度
- TriggerPage     触发手感：长按延迟、触发距离
- SizePage        圆盘尺寸：5 个滑杆 + 实时预览
- GeneralPage     常规：语言、启动项、检查更新
- MaintenancePage 维护：配置目录、方案导入导出、恢复默认

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
                               QSlider, QVBoxLayout, QWidget, QMessageBox)

from src.config_manager import (save_config, get_auto_start, set_auto_start,
                                get_config_path, set_config_dir,
                                reset_config_dir, _default_config)
from src.i18n import T
from src.menu_geometry import scaled_radii
from src.theme import (get_ui, MENU_THEMES, make_custom_theme,
                       make_light_theme, theme_from_settings,
                       effective_ui_mode, FONT_XS, _CUSTOM_ACCENT)
from src.qt_renderer import (draw_shadow, draw_ring, draw_center,
                             INNER, OUTER, EXTENSION)

# 自定义主题的预设主色板（柔和、低饱和）
_CUSTOM_COLORS = [
    "#6fa3d8", "#4ec9a0", "#7fb069", "#d9a545", "#e08a5e", "#d98a8a",
    "#c084d9", "#9d8cf0", "#5aa7b4", "#4fc8d8", "#b8c4d0", "#c7c9d6",
]


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
    for i, col in enumerate(_CUSTOM_COLORS[:8]):
        grad.setColorAt(i / 8, QColor(col))
    grad.setColorAt(1, QColor("#2a3340"))
    p.setPen(Qt.NoPen)
    p.setBrush(grad)
    p.drawEllipse(QPointF(c, c), r, r)
    p.setPen(QColor("#ffffff"))
    f = QFont("Microsoft YaHei")
    f.setPixelSize(26)
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

        avail = min(self.width(), self.height()) / 2 - 24
        fit = avail / ext if ext else 1.0
        cx, cy = self.width() / 2, self.height() / 2
        prof = self.profile or {}

        draw_shadow(p, cx, cy, ext * fit)
        draw_ring(p, cx, cy, outer * fit, ext * fit, n,
                  prof.get("extension_sectors", {}), theme.extension,
                  layer=EXTENSION, placeholder=True)
        draw_ring(p, cx, cy, inner * fit, outer * fit, n,
                  prof.get("outer_sectors", {}), theme.outer,
                  layer=OUTER, placeholder=True)
        draw_ring(p, cx, cy, dead * fit, inner * fit, n,
                  prof.get("sectors", {}), theme.inner,
                  layer=INNER, placeholder=True)
        name = prof.get("name", "") if prof else ""
        draw_center(p, cx, cy, dead * fit, theme,
                    min(self.width(), self.height()), "", name)

        # 底部标注各层半径与实际直径
        p.setOpacity(1.0)
        p.setPen(QColor(get_ui().text_muted))
        f = QFont("Microsoft YaHei")
        f.setPixelSize(FONT_XS)
        p.setFont(f)
        p.drawText(6, self.height() - 6,
                   T("第一圈 {inner}px · 第二圈 {outer}px · 最外圈 {ext}px   实际直径 {dia}px")
                   .format(inner=inner, outer=outer, ext=ext, dia=ext * 2))
        p.end()


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
        self.on_ui_mode_changed = None
        self.on_language_changed = None
        self._slider_labels = {}       # key -> (name_lb, unit, val_lb, divisor, slider)
        self._tr = []                  # [(widget, zh_text)] 语言切换刷新

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
        self.title.setText(T(self.title_zh))

    # ---- 公共控件 ----

    def _slider_row(self, zh_name, key, lo, hi, unit,
                    on_change=None, divisor=1.0, container=None):
        """向页面添加一行：名称 | 滑杆 | 当前值。container 为 None 时加进 body"""
        row = QHBoxLayout()
        row.setSpacing(10)
        name = QLabel(T(zh_name))
        name.setMinimumWidth(96)
        row.addWidget(name)
        raw = self.config.get("settings", {}).get(key, lo)
        val = int(round(raw * divisor)) if divisor != 1.0 else int(raw)
        val = max(lo, min(hi, val))
        lb = QLabel(f"{val}{unit}")
        lb.setFixedWidth(56)
        lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)
        self._slider_labels[key] = (name, unit, lb, divisor, sl)

        def _on_value(v, l=lb, u=unit, k=key, d=divisor):
            l.setText(f"{v}{u}")
            self.config.setdefault("settings", {})[k] = v / d if d != 1.0 else v
            if on_change:
                on_change()
        sl.valueChanged.connect(_on_value)
        sl.sliderReleased.connect(self._save)  # 拖动结束才保存
        row.addWidget(sl, 1)
        row.addWidget(lb)
        (container or self.body).addLayout(row)
        self.register_text(name, zh_name)
        return sl, lb

    # ---- 保存 / 配置 ----

    def _set(self, key, value):
        self.config.setdefault("settings", {})[key] = value
        self._save()

    def _save(self):
        ok = save_config(self.config)
        if ok and self.on_saved:
            self.on_saved()

    def refresh(self, config, profile=None):
        """进入页面时同步控件状态（子类覆盖）"""
        self.config = config
        self._refresh_sliders()

    def _refresh_sliders(self):
        for key, (name_lb, unit, lb, divisor, sl) in self._slider_labels.items():
            raw = self.config.get("settings", {}).get(key, 0)
            val = int(round(raw * divisor)) if divisor != 1.0 else int(raw)
            sl.blockSignals(True)
            sl.setValue(val)
            sl.blockSignals(False)
            lb.setText(f"{val}{unit}")


class AppearancePage(_BasePage):
    """外观：界面模式（浅/深）、圆盘主题色板、自定义主色、不透明度 + 实时预览"""

    def __init__(self, config, parent=None):
        self.title_zh = "外观"
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

        # 自定义主题主色选择（默认隐藏，选"自定义"时显示）
        self._custom_row = QWidget()
        cr = QVBoxLayout(self._custom_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        head = QHBoxLayout()
        self._lb_color = QLabel(T("主色"))
        self.register_text(self._lb_color, "主色")
        head.addWidget(self._lb_color)
        head.addStretch(1)
        self._btn_picker = QPushButton(T("自选颜色…"))
        self._btn_picker.setProperty("class", "ghost")
        self._btn_picker.clicked.connect(self._pick_color)
        self.register_text(self._btn_picker, "自选颜色…")
        head.addWidget(self._btn_picker)
        cr.addLayout(head)
        # 色点网格：6 列两行，点击即应用
        color_grid = QGridLayout()
        color_grid.setSpacing(8)
        self._color_group = QButtonGroup(self)
        self._color_group.setExclusive(True)
        self._color_buttons = []
        for i, col in enumerate(_CUSTOM_COLORS):
            b = QPushButton()
            b.setFixedSize(22, 22)
            b.setCheckable(True)
            b.setProperty("class", "colorDot")
            b.setStyleSheet(
                f"background: {col}; border-radius: 11px; border: 2px solid transparent;"
                f" QPushButton:checked {{ border: 2px solid #6fa3d8; }}"
                f" QPushButton:hover {{ border: 1px solid #8a94a3; }}")
            b.setToolTip(col)
            b.clicked.connect(lambda _=False, c=col: self._set_custom_accent(c))
            self._color_group.addButton(b)
            self._color_buttons.append(b)
            color_grid.addWidget(b, i // 6, i % 6)
        color_grid.setColumnStretch(6, 1)
        cr.addLayout(color_grid)
        self._custom_row.hide()
        lv.addWidget(self._custom_row)

        # 不透明度（加进左列）
        self._opacity_slider, self._opacity_label = self._slider_row(
            "不透明度", "menu_opacity", 30, 100, "%",
            on_change=self._update_preview, divisor=100.0, container=lv)
        lv.addStretch(1)

        hbox.addWidget(left, 1)
        self.preview = _MenuPreview(self.config)
        hbox.addWidget(self.preview, 0, Qt.AlignHCenter)
        self.body.addLayout(hbox)

    def _update_preview(self):
        if getattr(self, "preview", None):
            self.preview.update()

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
        self._custom_row.setVisible(name == "custom")
        if name == "custom":
            accent = self.config.get("settings", {}).get("custom_accent", _CUSTOM_ACCENT)
            self._sync_color_buttons(accent)
            self._refresh_custom_tile()
        self._save()
        self._update_preview()

    def _set_custom_accent(self, col):
        self.config.setdefault("settings", {})["custom_accent"] = col
        self.config.setdefault("settings", {})["menu_theme"] = "custom"
        self._sync_color_buttons(col)
        self._refresh_custom_tile()
        self._save()
        self._update_preview()

    def _pick_color(self):
        accent = self.config.get("settings", {}).get("custom_accent", _CUSTOM_ACCENT)
        col = QColorDialog.getColor(QColor(accent), self, T("选择圆盘主色"))
        if col.isValid():
            self._set_custom_accent(col.name())

    def _sync_color_buttons(self, accent):
        for b in self._color_buttons:
            b.setChecked(b.styleSheet().find(accent) >= 0)

    def _refresh_custom_tile(self):
        accent = self.config.get("settings", {}).get("custom_accent", _CUSTOM_ACCENT)
        t = make_custom_theme(accent)
        if effective_ui_mode(self.config.get("settings", {}).get("ui_mode", "dark")) == "light":
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
        self._custom_row.setVisible(name == "custom")
        self._sync_color_buttons(s.get("custom_accent", _CUSTOM_ACCENT))
        self._refresh_theme_thumbnails()
        self._refresh_sliders()
        self.preview.set_data(config, profile)


class TriggerPage(_BasePage):
    """触发手感：长按延迟、触发距离"""

    def __init__(self, config, parent=None):
        self.title_zh = "触发手感"
        super().__init__(config, parent)
        self.title.setText(T(self.title_zh))
        self._hold_slider, self._hold_label = self._slider_row(
            "长按延迟", "hold_threshold_ms", 0, 200, "ms")
        self._trig_slider, self._trig_label = self._slider_row(
            "触发距离", "trigger_distance", 5, 40, "px")
        self.body.addStretch(1)


class SizePage(_BasePage):
    """圆盘尺寸：整体大小 + 4 个半径滑杆（带顺序约束）+ 扇区数量 + 右侧实时预览"""

    _RADIUS_KEYS = ("dead_zone_radius", "ring_radius",
                    "outer_ring_radius", "ext_ring_radius")
    _RADIUS_GAP = 10  # 相邻圈层最小间隔（px）
    _RADIUS_DEFAULTS = {"dead_zone_radius": 24, "ring_radius": 70,
                        "outer_ring_radius": 135, "ext_ring_radius": 185}

    def __init__(self, config, parent=None):
        self.title_zh = "圆盘尺寸"
        super().__init__(config, parent)
        self.title.setText(T(self.title_zh))
        # 横向：左滑杆列 + 右预览
        self._hbox = QHBoxLayout()
        self._hbox.setSpacing(24)
        left = QWidget()
        lv = QVBoxLayout(left)
        lv.setContentsMargins(0, 0, 0, 0)
        lv.setSpacing(12)
        self._size_sliders = {}
        for key, text, lo, hi, unit in (("menu_scale", "整体圆盘大小", 50, 150, "%"),
                                        ("dead_zone_radius", "中心圆半径", 8, 60, "px"),
                                        ("ring_radius", "第一圈半径", 40, 160, "px"),
                                        ("outer_ring_radius", "第二圈半径", 90, 260, "px"),
                                        ("ext_ring_radius", "最外圈半径", 140, 360, "px")):
            sl, lb = self._slider_row(text, key, lo, hi, unit,
                                      on_change=self._on_size_changed,
                                      container=lv)
            self._size_sliders[key] = sl
        self._apply_radius_constraints()
        lv.addStretch(1)
        self._hbox.addWidget(left, 1)
        self.preview = _MenuPreview(self.config)
        self._hbox.addWidget(self.preview, 0, Qt.AlignHCenter)
        self.body.addLayout(self._hbox)

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
            self._slider_labels[k][2].setText(f"{vals[k]}px")

    def refresh(self, config, profile=None):
        self.config = config
        self.preview.set_data(config, profile)
        self._apply_radius_constraints()
        self._refresh_sliders()


class GeneralPage(_BasePage):
    """常规：语言、启动项、检查更新"""

    def __init__(self, config, parent=None):
        self.title_zh = "常规"
        super().__init__(config, parent)
        self.title.setText(T(self.title_zh))

        # 语言
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

        self.chk_open = QCheckBox(T("启动时打开此界面"))
        self.chk_open.toggled.connect(lambda b: self._set("open_config_on_start", b))
        self.body.addWidget(self.chk_open)
        self.chk_auto = QCheckBox(T("根据 CAD 窗口自动切换"))
        self.chk_auto.toggled.connect(lambda b: self._set("auto_switch_profile", b))
        self.body.addWidget(self.chk_auto)
        self.chk_startup = QCheckBox(T("开机自启"))
        self.chk_startup.toggled.connect(self._on_startup)
        self.body.addWidget(self.chk_startup)
        self.chk_update = QCheckBox(T("启动时检查更新"))
        self.chk_update.toggled.connect(lambda b: self._set("check_update_on_start", b))
        self.body.addWidget(self.chk_update)
        self.btn_check_update = QPushButton(T("检查更新"))
        self.btn_check_update.setToolTip(T("立即检查是否有新版本"))
        self.btn_check_update.clicked.connect(self._on_check_update_click)
        self.body.addWidget(self.btn_check_update)
        self.body.addStretch(1)

        self.register_text(self.chk_open, "启动时打开此界面")
        self.register_text(self.chk_auto, "根据 CAD 窗口自动切换")
        self.register_text(self.chk_startup, "开机自启")
        self.register_text(self.chk_update, "启动时检查更新")
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

        # 配置目录行：标题 + 当前路径 + 更改/重置（同一行）
        dir_head = QHBoxLayout()
        dir_head.setSpacing(8)
        self._lb_dir_title = QLabel(T("配置目录"))
        self.register_text(self._lb_dir_title, "配置目录")
        dir_head.addWidget(self._lb_dir_title)
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
        btn_reset = QPushButton(T("恢复默认"))
        btn_reset.setProperty("class", "danger")
        btn_reset.setToolTip(T("把当前方案的三圈命令恢复为默认内容"))
        btn_reset.clicked.connect(self._reset_defaults)
        self.register_text(btn_reset, "恢复默认")
        row.addWidget(btn_import)
        row.addWidget(btn_export)
        row.addWidget(btn_dir)
        row.addStretch(1)
        row.addWidget(btn_reset)
        self.body.addLayout(row)
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
