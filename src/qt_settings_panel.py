"""设置面板 — 全屏覆盖式（左侧设置项卡片 + 右侧真实数据预览）

改进点：
- 主题选择从下拉框改为色板网格：每套主题画迷你圆盘缩略图，一眼看出效果
- 支持自定义主题：从预设主色板或调色板自选主色，自动推导整套配色
- 右侧预览圆盘用当前方案的真实命令数据绘制，拖尺寸滑杆所见即所得
- 卡片分组 + 锚点滚动：外观 / 触发手感 / 圆盘尺寸 / 常规 / 维护
"""

import os

from PySide6.QtCore import QEasingCurve, QPoint, Qt, QVariantAnimation
from PySide6.QtGui import QColor, QFont, QPainter, QPixmap, QRadialGradient
from PySide6.QtWidgets import (QButtonGroup, QCheckBox, QColorDialog,
                               QComboBox, QFileDialog, QFormLayout,
                               QGraphicsDropShadowEffect, QGridLayout,
                               QHBoxLayout, QLabel, QPushButton, QScrollArea,
                               QSizePolicy, QSlider, QSpinBox, QVBoxLayout,
                               QWidget, QMessageBox)

from src.config_manager import (save_config, get_auto_start, set_auto_start,
                                get_config_path, set_config_dir,
                                reset_config_dir, _default_config)
from src.theme import (UI, build_qss, MENU_THEMES, make_custom_theme,
                       theme_from_settings, FONT_XS, FONT_SM, RADIUS_LG,
                       _CUSTOM_ACCENT)
from src.qt_renderer import (draw_shadow, draw_ring, draw_center,
                             INNER, OUTER, EXTENSION)

# 自定义主题的预设主色板（柔和、低饱和）
_CUSTOM_COLORS = [
    "#6fa3d8", "#4ec9a0", "#7fb069", "#d9a545", "#e08a5e", "#d98a8a",
    "#c084d9", "#9d8cf0", "#5aa7b4", "#4fc8d8", "#b8c4d0", "#c7c9d6",
]

_SECTION_QSS = f"""
QWidget#secCard {{
    background: {UI.bg_card}; border: 1px solid {UI.border};
    border-radius: {RADIUS_LG}px;
}}
QWidget#secCard QLabel {{ background: transparent; }}
QWidget#secCard QCheckBox {{ background: transparent; }}
QWidget#secCard QComboBox {{ background: {UI.bg_input}; }}
"""


def _tile_pixmap(t, w=96, h=96) -> QPixmap:
    """离屏绘制迷你圆盘缩略图（主题色板用）"""
    pm = QPixmap(w, h)
    pm.fill(Qt.transparent)
    p = QPainter(pm)
    p.setRenderHint(QPainter.Antialiasing)
    c = w / 2
    # 三层示意缩放到画布内（外层 42 半径，直径 84 < 96，四周留白不裁切）
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
    p.drawEllipse(QPoint(c, c), r, r)
    p.setPen(QColor("#ffffff"))
    f = QFont("Microsoft YaHei")
    f.setPixelSize(26)
    f.setBold(True)
    p.setFont(f)
    p.drawText(QPoint(c - 14, c + 12), "自")
    p.end()
    return pm


class _ThemeTile(QPushButton):
    """主题色板格：图标 + 名称由布局驱动，文字不被挤压遮挡"""

    def __init__(self, text: str, pixmap, parent=None):
        super().__init__(parent)
        self.setCheckable(True)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(text)
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
        self.setStyleSheet(f"""
            QPushButton {{
                border: 2px solid transparent; border-radius: 10px;
                background: transparent; padding: 0; min-width: 112px;
                min-height: 132px;
            }}
            QPushButton:hover {{ background: rgba(255,255,255,8); }}
            QPushButton:checked {{
                border-color: {UI.accent}; background: rgba(255,255,255,6);
            }}
            QPushButton QLabel {{
                background: transparent; color: {UI.text_secondary};
                font-size: 11px; border: none; padding: 0; min-height: 0;
            }}
            QPushButton:hover QLabel {{ color: {UI.text}; }}
            QPushButton:checked QLabel {{ color: {UI.text}; }}
        """)

    def set_icon_pixmap(self, pixmap):
        self._icon.setPixmap(pixmap)


class _CollapsibleSection(QWidget):
    """可折叠设置卡片：点击标题展开/折叠，带高度动画"""

    ANIM_MS = 200

    def __init__(self, key: str, title: str, expanded: bool = True, parent=None):
        super().__init__(parent)
        self.setObjectName("secCard")
        self.setSizePolicy(QSizePolicy.Expanding, QSizePolicy.Preferred)
        self._key = key
        self._title = title
        self._expanded = expanded

        outer = QVBoxLayout(self)
        outer.setContentsMargins(20, 14, 20, 16)
        outer.setSpacing(0)

        self._btn = QPushButton(f"{title}  {'▾' if expanded else '▸'}")
        self._btn.setCursor(Qt.PointingHandCursor)
        self._btn.setStyleSheet(f"""
            QPushButton {{
                background: transparent; border: none; text-align: left;
                color: {UI.text_secondary}; font-weight: bold;
                font-size: {FONT_SM}px; padding: 2px;
            }}
            QPushButton:hover {{ color: {UI.text}; }}
        """)
        outer.addWidget(self._btn)
        self._btn.clicked.connect(self._toggle)

        self._content = QWidget()
        self.lay = QVBoxLayout(self._content)
        self.lay.setContentsMargins(0, 12, 0, 0)
        self.lay.setSpacing(12)
        outer.addWidget(self._content)

        self._anim = QVariantAnimation(self)
        self._anim.setDuration(self.ANIM_MS)
        self._anim.setEasingCurve(QEasingCurve.InOutCubic)
        self._anim.valueChanged.connect(self._apply_height)
        self._anim.finished.connect(self._on_anim_finished)

        if not expanded:
            self._content.setMaximumHeight(0)
            self._content.setVisible(False)

    # ---- 折叠控制 ----

    def is_expanded(self) -> bool:
        return self._expanded

    def set_expanded(self, expand: bool):
        if expand == self._expanded:
            return
        self._expanded = expand
        if expand:
            self._content.setVisible(True)
            start = self._content.height()
            end = self._content.sizeHint().height()
        else:
            start = self._content.height()
            end = 0
        self._btn.setText(f"{self._title}  {'▾' if expand else '▸'}")
        self._anim.stop()
        self._anim.setStartValue(start)
        self._anim.setEndValue(end)
        self._anim.start()

    def _toggle(self):
        self.set_expanded(not self._expanded)

    def _apply_height(self, v):
        self._content.setMaximumHeight(int(v))

    def _on_anim_finished(self):
        if self._expanded:
            self._content.setMaximumHeight(16777215)
        else:
            self._content.setMaximumHeight(0)
            self._content.setVisible(False)


class _MenuPreview(QWidget):
    """右侧圆盘预览：用当前方案的真实命令数据绘制，反映真实尺寸效果"""

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
        dead = int(s.get("dead_zone_radius", 30))
        inner = int(s.get("ring_radius", 100))
        outer = int(s.get("outer_ring_radius", 180))
        ext = int(s.get("ext_ring_radius", 240))
        n = int(s.get("sector_count", 8))
        theme = theme_from_settings(s)

        avail = min(self.width(), self.height()) / 2 - 24
        scale = avail / ext if ext else 1.0
        cx, cy = self.width() / 2, self.height() / 2
        prof = self.profile or {}

        draw_shadow(p, cx, cy, ext * scale)
        draw_ring(p, cx, cy, outer * scale, ext * scale, n,
                  prof.get("extension_sectors", {}), theme.extension,
                  layer=EXTENSION)
        draw_ring(p, cx, cy, inner * scale, outer * scale, n,
                  prof.get("outer_sectors", {}), theme.outer, layer=OUTER)
        draw_ring(p, cx, cy, dead * scale, inner * scale, n,
                  prof.get("sectors", {}), theme.inner, layer=INNER)
        name = prof.get("name", "") if prof else ""
        draw_center(p, cx, cy, dead * scale, theme,
                    min(self.width(), self.height()), "", name)

        # 底部标注各层半径与实际直径
        p.setOpacity(1.0)
        p.setPen(QColor(UI.text_muted))
        f = QFont("Microsoft YaHei")
        f.setPixelSize(FONT_XS)
        p.setFont(f)
        p.drawText(6, self.height() - 6,
                   f"内 {inner}px · 外 {outer}px · 扩展 {ext}px   实际直径 {ext * 2}px")
        p.end()


class QSettingsPanel(QWidget):
    """全局设置面板（覆盖整个界面）"""

    def __init__(self, config, parent=None):
        super().__init__(parent)
        self.config = config
        self.on_back = None
        self.on_saved = None
        self.on_import = None
        self.on_export = None
        self.on_open_dir = None
        self.setStyleSheet(build_qss(UI) + _SECTION_QSS)
        self._slider_labels = {}
        self._cards = {}

        outer = QHBoxLayout(self)
        outer.setContentsMargins(24, 16, 24, 16)
        outer.addStretch(1)
        center = QWidget()
        center.setMaximumWidth(1200)
        cv = QVBoxLayout(center)
        cv.setSpacing(16)
        outer.addWidget(center)
        outer.addStretch(1)

        # 顶部导航
        top = QHBoxLayout()
        btn_back = QPushButton("← 返回圆盘编辑")
        btn_back.setProperty("class", "ghost")
        btn_back.clicked.connect(self._back)
        top.addWidget(btn_back)
        top.addStretch(1)
        title = QLabel("全局设置")
        title.setStyleSheet("font-size: 20px; font-weight: bold;")
        top.addWidget(title)
        top.addStretch(1)
        sub = QLabel("修改即时保存")
        sub.setStyleSheet("color: #6f7a88; font-size: 11px;")
        top.addWidget(sub)
        cv.addLayout(top)

        body = QHBoxLayout()
        body.setSpacing(28)

        # ---- 左侧：设置卡片（滚动） ----
        self.scroll = QScrollArea()
        self.scroll.setWidgetResizable(True)
        self.scroll.setFrameShape(QScrollArea.NoFrame)
        self.scroll.setMinimumWidth(540)
        inner = QWidget()
        form = QVBoxLayout(inner)
        form.setSpacing(14)
        form.setContentsMargins(0, 0, 0, 0)

        form.addWidget(self._build_appearance_card(), 0)
        form.addWidget(self._build_trigger_card(), 0)
        form.addWidget(self._build_size_card(), 0)
        form.addWidget(self._build_general_card(), 0)
        form.addWidget(self._build_maintenance_card(), 0)
        form.addStretch(1)

        self.scroll.setWidget(inner)
        body.addWidget(self.scroll, 1)

        # ---- 右侧：预览 ----
        right_col = QWidget()
        right_col.setFixedWidth(450)
        rv = QVBoxLayout(right_col)
        rv.setSpacing(12)
        rv.setContentsMargins(0, 0, 0, 0)
        rv.addStretch(1)
        self.preview = _MenuPreview(self.config)
        rv.addWidget(self.preview, 0, Qt.AlignHCenter)
        hint = QLabel("预览随设置实时更新，拖动尺寸滑杆可查看实际大小效果")
        hint.setWordWrap(True)
        hint.setAlignment(Qt.AlignCenter)
        hint.setStyleSheet(f"color: {UI.text_muted}; font-size: {FONT_XS}px;")
        rv.addWidget(hint)
        rv.addStretch(1)
        body.addWidget(right_col, 0)

        cv.addLayout(body, 1)

    # ========== 卡片构建 ==========

    def _section(self, key, title, expanded=True):
        card = _CollapsibleSection(key, title, expanded=expanded)
        self._cards[key] = card
        return card

    def _build_appearance_card(self):
        card = self._section("appearance", "外观")

        # 主题色板网格（3 列 3 行共 9 格，宽度充裕不挤压、文字不被遮挡）
        grid = QGridLayout()
        grid.setSpacing(12)
        for c in range(3):
            grid.setColumnStretch(c, 1)
        self._theme_group = QButtonGroup(self)
        self._theme_group.setExclusive(True)
        self._theme_tiles = {}       # theme name -> tile
        self._tile_by_btn = {}       # button -> theme name or "custom"
        for i, th in enumerate(MENU_THEMES.values()):
            tile = self._make_tile(th.label, _tile_pixmap(th))
            self._theme_tiles[th.name] = tile
            self._theme_group.addButton(tile)
            self._tile_by_btn[tile] = th.name
            grid.addWidget(tile, i // 3, i % 3)
        i = len(MENU_THEMES)
        self._custom_tile = self._make_tile("自定义", _custom_tile_pixmap())
        self._theme_group.addButton(self._custom_tile)
        self._tile_by_btn[self._custom_tile] = "custom"
        grid.addWidget(self._custom_tile, i // 3, i % 3)
        self._theme_group.buttonClicked.connect(self._on_theme_picked)
        card.lay.addLayout(grid)

        # 自定义主题主色选择（默认隐藏，选"自定义"时显示）
        self._custom_row = QWidget()
        cr = QVBoxLayout(self._custom_row)
        cr.setContentsMargins(0, 0, 0, 0)
        cr.setSpacing(8)
        head = QHBoxLayout()
        head.addWidget(QLabel("主色"))
        head.addStretch(1)
        self._btn_picker = QPushButton("自选颜色…")
        self._btn_picker.setProperty("class", "ghost")
        self._btn_picker.clicked.connect(self._pick_color)
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
            b.setStyleSheet(
                f"background: {col}; border-radius: 11px; border: 2px solid "
                f"{UI.bg_card};"
                f"QPushButton:checked {{ border: 2px solid {UI.accent}; }}")
            b.setToolTip(col)
            b.clicked.connect(lambda _=False, c=col: self._set_custom_accent(c))
            self._color_group.addButton(b)
            self._color_buttons.append(b)
            color_grid.addWidget(b, i // 6, i % 6)
        color_grid.setColumnStretch(6, 1)
        cr.addLayout(color_grid)
        self._custom_row.hide()
        card.lay.addWidget(self._custom_row)

        # 不透明度
        self._opacity_slider, self._opacity_label = self._slider_row(
            card, "不透明度", "menu_opacity", 30, 100, "%",
            on_change=self._update_preview, divisor=100.0)
        return card

    def _make_tile(self, text, pixmap):
        """主题色板格：图标 + 名称，选中描边"""
        return _ThemeTile(text, pixmap)

    def _build_trigger_card(self):
        card = self._section("trigger", "触发手感", expanded=False)
        self._hold_slider, self._hold_label = self._slider_row(
            card, "长按延迟", "hold_threshold_ms", 10, 200, "ms")
        self._trig_slider, self._trig_label = self._slider_row(
            card, "触发距离", "trigger_distance", 8, 40, "px")
        return card

    def _build_size_card(self):
        card = self._section("size", "圆盘尺寸", expanded=False)
        self._size_sliders = {}
        for key, text, lo, hi, unit in (("dead_zone_radius", "中心死区", 8, 60, "px"),
                                        ("ring_radius", "内层半径", 40, 160, "px"),
                                        ("outer_ring_radius", "外层半径", 90, 260, "px"),
                                        ("ext_ring_radius", "扩展圈", 140, 360, "px"),
                                        ("sector_count", "扇区数量", 4, 16, "")):
            sl, lb = self._slider_row(card, text, key, lo, hi, unit,
                                      on_change=self._update_preview)
            self._size_sliders[key] = sl
        return card

    def _build_general_card(self):
        card = self._section("general", "常规")
        self.chk_open = QCheckBox("启动时打开此界面")
        self.chk_open.toggled.connect(lambda b: self._set("open_config_on_start", b))
        card.lay.addWidget(self.chk_open)
        self.chk_auto = QCheckBox("根据 CAD 窗口自动切换")
        self.chk_auto.toggled.connect(lambda b: self._set("auto_switch_profile", b))
        card.lay.addWidget(self.chk_auto)
        self.chk_startup = QCheckBox("开机自启")
        self.chk_startup.toggled.connect(self._on_startup)
        card.lay.addWidget(self.chk_startup)
        return card

    def _build_maintenance_card(self):
        card = self._section("maintenance", "维护")

        # 配置目录行：标题 + 当前路径 + 更改/重置（同一行）
        dir_head = QHBoxLayout()
        dir_head.setSpacing(8)
        dir_head.addWidget(QLabel("配置目录"))
        self._config_dir_label = QLabel(get_config_path())
        self._config_dir_label.setWordWrap(True)
        self._config_dir_label.setStyleSheet(
            f"color: {UI.text_muted}; font-size: {FONT_XS}px;")
        dir_head.addWidget(self._config_dir_label, 1)
        btn_change = QPushButton("更改")
        btn_change.setToolTip("把配置迁移到自选目录（如 D 盘）")
        btn_change.clicked.connect(self._change_config_dir)
        btn_reset_dir = QPushButton("重置")
        btn_reset_dir.setToolTip("恢复默认 %APPDATA%\\CADGesture")
        btn_reset_dir.clicked.connect(self._restore_config_dir)
        dir_head.addWidget(btn_change, 0, Qt.AlignVCenter)
        dir_head.addWidget(btn_reset_dir, 0, Qt.AlignVCenter)
        card.lay.addLayout(dir_head)

        # 方案操作：保持原排版
        row = QHBoxLayout()
        row.setSpacing(8)
        btn_import = QPushButton("导入方案")
        btn_import.clicked.connect(lambda: self.on_import() if self.on_import else None)
        btn_export = QPushButton("导出方案")
        btn_export.clicked.connect(lambda: self.on_export() if self.on_export else None)
        btn_dir = QPushButton("打开配置目录")
        btn_dir.clicked.connect(lambda: self.on_open_dir() if self.on_open_dir else None)
        btn_reset = QPushButton("恢复默认")
        btn_reset.setProperty("class", "danger")
        btn_reset.setToolTip("把当前方案的三圈命令恢复为默认内容")
        btn_reset.clicked.connect(self._reset_defaults)
        row.addWidget(btn_import)
        row.addWidget(btn_export)
        row.addWidget(btn_dir)
        row.addStretch(1)
        row.addWidget(btn_reset)
        card.lay.addLayout(row)
        return card

    def _change_config_dir(self):
        """选择新配置目录并迁移现有配置"""
        d = QFileDialog.getExistingDirectory(self, "选择配置目录")
        if not d:
            return
        try:
            set_config_dir(d)
        except Exception as e:
            QMessageBox.warning(self, "更改失败", f"无法使用该目录：{e}")
            return
        self._config_dir_label.setText(get_config_path())
        self._save()  # 把当前配置立即写入新位置
        self._update_preview()
        QMessageBox.information(
            self, "配置目录已更改",
            f"配置已迁移到：\n{get_config_path()}\n\n"
            "目录位置已记住，下次启动自动使用。")

    def _restore_config_dir(self):
        """恢复默认配置目录（%APPDATA%\\CADGesture）"""
        try:
            reset_config_dir()
        except Exception as e:
            QMessageBox.warning(self, "恢复失败", str(e))
            return
        self._config_dir_label.setText(get_config_path())
        self._save()
        self._update_preview()
        QMessageBox.information(
            self, "已恢复默认",
            f"配置目录已恢复为：\n{get_config_path()}")

    # ========== 交互 ==========

    def _on_theme_picked(self, btn):
        name = self._tile_by_btn[btn]
        self.config.setdefault("settings", {})["menu_theme"] = name
        self._custom_row.setVisible(name == "custom")
        if name == "custom":
            # 同步当前主色的色点选中态
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
        col = QColorDialog.getColor(QColor(accent), self, "选择圆盘主色")
        if col.isValid():
            self._set_custom_accent(col.name())

    def _sync_color_buttons(self, accent):
        for b in self._color_buttons:
            b.setChecked(b.styleSheet().find(accent) >= 0)

    def _refresh_custom_tile(self):
        accent = self.config.get("settings", {}).get("custom_accent", _CUSTOM_ACCENT)
        t = make_custom_theme(accent)
        self._custom_tile.set_icon_pixmap(_tile_pixmap(t))

    # ========== 通用 ==========

    def _slider_row(self, card, text, key, lo, hi, unit, on_change=None, divisor=1.0):
        """向卡片内添加一行：名称 | 滑杆 | 当前值"""
        row = QHBoxLayout()
        row.setSpacing(10)
        name = QLabel(text)
        name.setFixedWidth(76)
        row.addWidget(name)
        raw = self.config.get("settings", {}).get(key, lo)
        val = int(round(raw * divisor)) if divisor != 1.0 else int(raw)
        val = max(lo, min(hi, val))
        lb = QLabel(f"{val}{unit}")
        lb.setFixedWidth(48)
        lb.setAlignment(Qt.AlignRight | Qt.AlignVCenter)
        lb.setStyleSheet(f"color: {UI.text_secondary};")
        sl = QSlider(Qt.Horizontal)
        sl.setRange(lo, hi)
        sl.setValue(val)

        def _on_value(v, l=lb, u=unit, k=key, d=divisor):
            l.setText(f"{v}{u}")
            self.config.setdefault("settings", {})[k] = v / d if d != 1.0 else v
            if on_change:
                on_change()
        sl.valueChanged.connect(_on_value)
        sl.sliderReleased.connect(self._save)  # 拖动结束才保存
        row.addWidget(sl, 1)
        row.addWidget(lb)
        card.lay.addLayout(row)
        self._slider_labels[key] = (unit, lb, divisor)
        return sl, lb

    def _update_preview(self):
        if getattr(self, "preview", None):
            self.preview.update()

    def scroll_to(self, key):
        """滚动到指定设置卡片（侧栏锚点导航用）"""
        card = self._cards.get(key)
        if card:
            self.scroll.ensureWidgetVisible(card, 0, 50)

    def refresh(self, config, profile=None):
        """从配置刷新控件（进入设置面板时调用）"""
        self.config = config
        s = config.get("settings", {})
        for w in (self.chk_open, self.chk_auto, self.chk_startup):
            w.blockSignals(True)
        self.chk_open.setChecked(bool(s.get("open_config_on_start", False)))
        self.chk_auto.setChecked(bool(s.get("auto_switch_profile", True)))
        self.chk_startup.setChecked(get_auto_start())
        for w in (self.chk_open, self.chk_auto, self.chk_startup):
            w.blockSignals(False)

        # 主题选中态（断连防递归，刷新后重连）
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
        self._refresh_custom_tile()

        # 滑杆同步
        for key, (unit, lb, divisor) in self._slider_labels.items():
            sl = self._size_sliders.get(key)
            if sl is None and hasattr(self, "_opacity_slider") and key == "menu_opacity":
                sl = self._opacity_slider
            if sl is None:
                continue
            raw = s.get(key, 0)
            val = int(round(raw * divisor)) if divisor != 1.0 else int(raw)
            sl.blockSignals(True)
            sl.setValue(val)
            sl.blockSignals(False)
            lb.setText(f"{val}{unit}")
        self.preview.set_data(config, profile)

    # ========== 保存与重置 ==========

    def _back(self):
        if self.on_back:
            self.on_back()

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
