"""统一配色与设计 token — 深色界面 + 圆盘外观主题

分层：
1. UITheme：界面 chrome 的设计 token（背景/文字/边框/强调色），QSS 由它生成，
   消除散落在各控件里的硬编码颜色。
2. MenuTheme：圆盘菜单外观主题（仅圆盘配色）。全部由主色经 HLS 推导生成，
   保证每套视觉质感一致；另支持"自定义"主题（用户挑一个主色自动推导整套）。
"""

import colorsys
from dataclasses import dataclass
from typing import Dict, Optional

# ========== 布局常量（间距 / 圆角 / 字号） ==========

SP_SM = 4
SP_MD = 8
SP_LG = 12
SP_XL = 16
SP_XXL = 24

RADIUS_SM = 5
RADIUS_MD = 9
RADIUS_LG = 14

FONT_XS = 11
FONT_SM = 12
FONT_BASE = 13
FONT_MD = 15
FONT_LG = 18
FONT_TITLE = 20


# ========== 界面设计 token ==========


@dataclass
class UITheme:
    """界面 chrome 配色（深色、低饱和、克制）"""
    bg: str                 # 窗口最底层
    bg_raised: str          # 面板 / 列表
    bg_card: str            # 卡片
    bg_overlay: str         # 浮层 / 弹层
    bg_input: str           # 输入框
    bg_hover: str           # 悬停项
    bg_selected: str        # 选中项（低调的强调色，不整块染色）
    text: str
    text_secondary: str
    text_muted: str
    border: str
    border_strong: str
    accent: str
    accent_hover: str
    accent_text: str        # 强调色上的浅色文字（用于 primary 按钮）
    accent_dim: str         # 深一档的强调色
    danger: str
    danger_bg: str
    danger_border: str
    scroll_handle: str
    scroll_handle_hover: str


UI_DARK = UITheme(
    bg="#0f1218",
    bg_raised="#151a22",
    bg_card="#1a202b",
    bg_overlay="#1e2532",
    bg_input="#12161e",
    bg_hover="#222a36",
    bg_selected="#2a3a4d",
    text="#dfe4ec",
    text_secondary="#a0a9b6",
    text_muted="#6f7a88",
    border="#232b37",
    border_strong="#303b4a",
    accent="#6fa3d8",
    accent_hover="#8bb7e6",
    accent_text="#f2f7fd",
    accent_dim="#3f5f85",
    danger="#d98a8a",
    danger_bg="#3c2629",
    danger_border="#5a3439",
    scroll_handle="#303b4a",
    scroll_handle_hover="#42506a",
)

# 浅色界面（低饱和、温和，与深色同 accent 保持品牌一致）
UI_LIGHT = UITheme(
    bg="#f4f5f7",
    bg_raised="#ffffff",
    bg_card="#fafbfc",
    bg_overlay="#ffffff",
    bg_input="#ffffff",
    bg_hover="#e9edf2",
    bg_selected="#d7e4f2",
    text="#1f2733",
    text_secondary="#4a5568",
    text_muted="#7a8595",
    border="#e0e4ea",
    border_strong="#cfd6df",
    accent="#2f6db3",
    accent_hover="#3b7cc7",
    accent_text="#ffffff",
    accent_dim="#c5d9ee",
    danger="#c03b3b",
    danger_bg="#fbeaea",
    danger_border="#f0cccc",
    scroll_handle="#c5cdd8",
    scroll_handle_hover="#aab6c4",
)

# 兼容旧引用（模块级 UI 即深色主题）
UI = UI_DARK

# 当前界面模式：_CONFIGURED_MODE 存用户配置值（dark/light/system），
# _CURRENT_MODE 存解析后的实际生效值（仅 dark/light），供无参取色的地方使用
_CONFIGURED_MODE = "dark"
_CURRENT_MODE = "dark"


def system_ui_mode() -> str:
    """读取 Windows 系统深浅色设置（注册表 AppsUseLightTheme）。

    1=浅色 0=深色；读取失败回退深色（与默认界面模式一致）。
    """
    try:
        import winreg
        key = winreg.OpenKey(
            winreg.HKEY_CURRENT_USER,
            r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
        try:
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if val == 1 else "dark"
        finally:
            winreg.CloseKey(key)
    except OSError:
        return "dark"


def effective_ui_mode(mode: str) -> str:
    """把界面模式配置值解析为实际生效的 "dark"/"light"。

    - "system" → 读系统当前主题
    - "light" → "light"
    - 其余（"dark" / 未知值）→ "dark"
    """
    if mode == "system":
        return system_ui_mode()
    return "light" if mode == "light" else "dark"


def set_ui_mode(mode: str) -> None:
    """记录当前界面模式（切换浅/深/跟随系统时由主窗口调用）。

    保存原始配置值，并把解析后的生效值写入 _CURRENT_MODE。
    """
    global _CONFIGURED_MODE, _CURRENT_MODE
    _CONFIGURED_MODE = mode
    _CURRENT_MODE = effective_ui_mode(mode)


def current_ui_mode() -> str:
    """返回当前实际生效的界面模式（"dark"/"light"，system 已解析）。"""
    return _CURRENT_MODE


def get_ui(mode: str = None) -> UITheme:
    """按界面模式返回 UI 主题（"dark"/"light"，system 自动解析）。

    不传 mode 时使用模块级当前生效模式——供 paintEvent 等需要
    跟随主题的绘制代码调用（折叠按钮、拖拽卡片、预览标注等）。
    """
    m = _CURRENT_MODE if mode is None else effective_ui_mode(mode)
    return UI_LIGHT if m == "light" else UI_DARK


def set_title_bar_theme(win, dark: bool = True) -> None:
    """让窗口标题栏跟随深色/浅色主题（Windows 10 1809+，兼容 19/20 属性）。

    只对带原生标题栏的窗口有效；无边框窗口（Frameless）调用无害但无效果。
    已显示的窗口设置 DWM 属性后标题栏不会自动重绘——SWP_FRAMECHANGED、
    WM_NCPAINT、RedrawWindow 等常规手段实测均无效，唯一可靠且几乎无闪烁的
    触发方式是"宽度 ±2px 再还原"强制 DWM 重绘非客户区。DWM 属性在锁屏/
    远程桌面重连后可能丢失，调用方可在窗口激活时重复设置。
    """
    try:
        import ctypes
        import ctypes.wintypes as wintypes
        hwnd = int(win.winId())
        while True:
            parent = ctypes.windll.user32.GetParent(hwnd)
            if parent == 0:
                break
            hwnd = parent
        val = ctypes.c_int(1 if dark else 0)
        # Win10 1809~1909 用属性 19，2004+ / Win11 用 20；两个都设置以兼容所有版本
        for attr in (20, 19):
            ctypes.windll.dwmapi.DwmSetWindowAttribute(
                ctypes.c_void_p(hwnd), attr,
                ctypes.byref(val), ctypes.sizeof(val))
        # 已显示窗口：改宽 2px 再还原，强制 DWM 重绘标题栏
        if getattr(win, "isVisible", lambda: False)():
            user32 = ctypes.windll.user32
            user32.SetWindowPos.argtypes = [
                wintypes.HWND, wintypes.HWND, ctypes.c_int, ctypes.c_int,
                ctypes.c_int, ctypes.c_int, wintypes.UINT]
            r = wintypes.RECT()
            user32.GetWindowRect(hwnd, ctypes.byref(r))
            wpx = r.right - r.left
            hpx = r.bottom - r.top
            # 保持位置不变，只增宽再还原（NOZORDER | NOACTIVATE）
            user32.SetWindowPos(hwnd, None, r.left, r.top, wpx + 2, hpx,
                                0x0004 | 0x0010)
            user32.SetWindowPos(hwnd, None, r.left, r.top, wpx, hpx,
                                0x0004 | 0x0010)
    except Exception:
        pass


def build_qss(t: UITheme) -> str:
    """从设计 token 生成全局样式表（界面统一风格，不再散落硬编码颜色）"""
    return f"""
QMainWindow, QWidget {{ background: {t.bg}; color: {t.text};
                       font-size: {FONT_BASE}px; }}
QLabel {{ background: transparent; }}
QToolTip {{ background: {t.bg_overlay}; color: {t.text};
            border: 1px solid {t.border_strong}; padding: 4px 8px; }}

/* ---- 输入控件 ---- */
QLineEdit, QComboBox, QSpinBox {{
    background: {t.bg_input}; border: 1px solid {t.border_strong};
    border-radius: {RADIUS_SM}px; padding: 5px 9px; min-height: 24px;
    selection-background-color: {t.accent_dim};
}}
QLineEdit:focus, QComboBox:focus, QSpinBox:focus {{ border-color: {t.accent}; }}
QLineEdit:disabled, QComboBox:disabled {{
    color: {t.text_muted}; background: {t.bg_raised}; }}
QComboBox::drop-down {{ border: none; width: 22px; }}
QComboBox QAbstractItemView {{
    background: {t.bg_overlay}; border: 1px solid {t.border_strong};
    selection-background-color: {t.bg_selected}; selection-color: {t.text};
}}

/* ---- 按钮 ---- */
QPushButton {{
    background: {t.bg_raised}; border: 1px solid {t.border_strong};
    border-radius: {RADIUS_SM}px; padding: 6px 14px; min-height: 26px;
    color: {t.text};
}}
QPushButton:hover {{ background: {t.bg_hover}; }}
QPushButton:pressed {{ background: {t.bg_card}; }}
QPushButton:disabled {{ color: {t.text_muted}; background: {t.bg_raised}; }}
QPushButton.primary {{ background: {t.accent}; border-color: {t.accent}; color: {t.accent_text}; }}
QPushButton.primary:hover {{ background: {t.accent_hover}; }}
QPushButton.ghost {{ background: transparent; border-color: transparent;
                     color: {t.text_secondary}; }}
QPushButton.ghost:hover {{ background: {t.bg_hover}; color: {t.text}; }}
QPushButton.danger {{ background: {t.danger_bg}; border-color: {t.danger_border};
                      color: {t.danger}; }}
QPushButton.danger:hover {{ background: {t.danger_border}; }}
QPushButton.iconBtn {{ background: transparent; border: 1px solid transparent;
                       border-radius: {RADIUS_SM}px; padding: 4px 8px; }}
QPushButton.iconBtn:hover {{ background: {t.bg_hover}; border-color: {t.border}; }}
QPushButton.iconBtn:disabled {{ color: {t.text_muted}; }}

/* ---- 列表 / 树 ---- */
QListWidget, QTreeWidget {{
    background: {t.bg_raised}; border: 1px solid {t.border};
    border-radius: {RADIUS_MD}px; padding: 4px;
}}
QListWidget::item {{ padding: 6px 9px; border-radius: {RADIUS_SM}px; }}
QListWidget::item:hover, QTreeWidget::item:hover {{ background: {t.bg_hover}; }}
QListWidget::item:selected, QTreeWidget::item:selected {{
    background: {t.bg_selected}; color: {t.text}; }}
QTreeWidget::item {{ padding: 7px 10px; border: none; }}
QTreeWidget::branch {{ background: transparent; }}
QHeaderView::section {{
    background: {t.bg_card}; color: {t.text_secondary};
    border: none; padding: 4px 8px; }}

/* ---- 滚动条 ---- */
QScrollBar:vertical {{ background: transparent; width: 10px; margin: 0; }}
QScrollBar::handle:vertical {{ background: {t.scroll_handle};
                              border-radius: 5px; min-height: 24px; }}
QScrollBar::handle:vertical:hover {{ background: {t.scroll_handle_hover}; }}
QScrollBar:horizontal {{ background: transparent; height: 10px; margin: 0; }}
QScrollBar::handle:horizontal {{ background: {t.scroll_handle};
                                 border-radius: 5px; min-width: 24px; }}
QScrollBar::handle:horizontal:hover {{ background: {t.scroll_handle_hover}; }}
QScrollBar::add-line, QScrollBar::sub-line {{ height: 0; width: 0; }}
QScrollBar::add-page, QScrollBar::sub-page {{ background: transparent; }}

/* ---- 分割条 / 状态栏 ---- */
QSplitter::handle {{ background: {t.border_strong}; }}
QSplitter::handle:hover {{ background: {t.accent}; }}
QStatusBar {{ background: {t.bg_raised}; color: {t.text_muted}; }}

/* ---- 开关与滑杆 ---- */
QCheckBox {{ spacing: 6px; }}
QCheckBox::indicator {{ width: 15px; height: 15px; border-radius: 4px;
                        border: 1px solid {t.border_strong}; background: {t.bg_input}; }}
QCheckBox::indicator:checked {{ background: {t.accent}; border-color: {t.accent}; }}
QSlider::groove:horizontal {{ height: 4px; background: {t.border_strong};
                              border-radius: 2px; }}
QSlider::handle:horizontal {{ width: 14px; background: {t.accent};
                              border-radius: 7px; margin: -5px 0; }}
QSlider::handle:horizontal:hover {{ background: {t.accent_hover}; }}
"""


def build_app_qss(mode: str = "dark") -> str:
    """生成应用级全局样式表（含全部界面组件，浅/深模式通用入口）。

    所有 UI 组件样式集中于此，通过 objectName / class 属性匹配；
    切换界面模式时只需重新生成并 QApplication.setStyleSheet 即可全局生效。
    """
    t = get_ui(mode)
    base = build_qss(t)
    # 深色模式下的悬停叠色与浅色不同，用半透明黑/白区分
    hover_overlay = "rgba(0,0,0,10)" if mode == "light" else "rgba(255,255,255,10)"
    return base + f"""
/* ---- 侧栏导航 ---- */
QPushButton.nav {{
    text-align: left; padding: 7px 10px; border-radius: 6px;
    background: transparent; border: none;
    color: {t.text_secondary}; font-size: 13px;
    icon-size: 16px; }}
QPushButton.nav:hover {{ background: {t.bg_hover}; color: {t.text}; }}
QPushButton.nav:checked {{
    background: {t.bg_selected}; color: {t.text};
    font-weight: 600; }}
QWidget#sidebar {{ background: {t.bg_raised};
                  border-right: 1px solid {t.border}; }}
QLabel#appLogo {{ font-size: 14px; font-weight: 700; color: {t.text}; }}
QFrame#sidebarSep {{ background: {t.border}; border: none;
                     max-height: 1px; min-height: 1px; }}
QLabel#pageTitle {{ font-size: 15px; font-weight: 600; }}
QLabel#pageSub {{ color: {t.text_muted}; font-size: 11px;
                  font-weight: 600; padding-left: 8px; }}
QLabel#pill {{ background: {t.bg_card}; color: {t.text_secondary};
    border: 1px solid {t.border}; border-radius: 10px;
    padding: 3px 12px; font-size: 12px; }}

/* ---- 上下文区列表（无边框，融入侧栏） ---- */
QListWidget#ctxList {{
    background: transparent; border: none; padding: 2px;
}}
QListWidget#ctxList::item {{
    padding: 5px 10px; border-radius: 6px; margin: 1px 0;
}}
QListWidget#ctxList::item:hover {{ background: {t.bg_hover}; }}
QListWidget#ctxList::item:selected {{
    background: transparent; color: {t.accent};
    border-left: 3px solid {t.accent}; padding-left: 7px; }}

/* ---- 顶栏操作按钮（撤销/重做/清除/恢复默认） ---- */
QPushButton.topBtn {{
    background: {t.bg_raised}; border: 1px solid {t.border_strong};
    border-radius: 6px; padding: 2px 12px; color: {t.text}; }}
QPushButton.topBtn:hover {{ background: {t.bg_hover}; }}
QPushButton.topBtn:pressed {{ background: {t.bg_card}; }}
QPushButton.topBtn:disabled {{ color: {t.text_muted}; }}
QPushButton#btnClearAll {{ color: {t.danger}; }}

/* ---- 命令库面板 ---- */
QWidget#presetPanel {{
    background: {t.bg_raised};
    border-left: 1px solid {t.border_strong};
}}
QWidget#presetPanel QLabel {{ background: transparent; }}

/* ---- 设置页卡片 ---- */
QWidget#secCard {{
    background: {t.bg_card}; border: 1px solid {t.border};
    border-radius: {RADIUS_LG}px;
}}
QWidget#secCard QLabel, QWidget#secCard QCheckBox {{ background: transparent; }}
QWidget#secCard QComboBox {{ background: {t.bg_input}; }}

/* ---- 扇区编辑浮层 ---- */
QFrame#popupCard {{
    background: {t.bg_overlay};
    border: 1px solid {t.border_strong};
    border-radius: {RADIUS_LG}px;
}}
QFrame#popupCard QLabel {{ background: transparent; }}
QLabel#popupTitle {{
    color: {t.text}; font-size: {FONT_SM}px; font-weight: 600;
}}
QLabel#popupMeta {{ color: {t.text_muted}; font-size: {FONT_XS}px; }}
QLabel#fieldName {{ color: {t.text_muted}; font-size: {FONT_XS}px; }}
QFrame#popupCard QLineEdit {{
    background: {t.bg_input}; border: 1px solid {t.border_strong};
    border-radius: 5px; padding: 4px 8px; min-height: 0;
}}
QFrame#popupCard QLineEdit:focus {{ border-color: {t.accent}; }}
QFrame#popupCard QPushButton {{
    background: {t.bg_raised}; border: 1px solid {t.border_strong};
    border-radius: 5px; padding: 3px 10px; min-height: 0;
    color: {t.text};
}}
QFrame#popupCard QPushButton:hover {{ background: {t.bg_hover}; }}
QPushButton#clearBtn {{ color: {t.danger}; }}

/* ---- 主题色板格 ---- */
QPushButton.themeTile {{
    border: 2px solid transparent; border-radius: 10px;
    background: transparent; padding: 0; min-width: 112px;
    min-height: 132px;
}}
QPushButton.themeTile:hover {{ background: {hover_overlay}; }}
QPushButton.themeTile:checked {{
    border-color: {t.accent}; background: {hover_overlay};
}}
QPushButton.themeTile QLabel {{
    background: transparent; color: {t.text_secondary};
    font-size: 11px; border: none; padding: 0; min-height: 0;
}}
QPushButton.themeTile:hover QLabel {{ color: {t.text}; }}
QPushButton.themeTile:checked QLabel {{ color: {t.text}; }}
"""


# ========== 圆盘主题 ==========


@dataclass
class RingColors:
    """单层扇区环配色"""
    normal: str
    empty: str
    highlight: str
    hover: str = ""
    outline: str = ""
    outline_hl: str = ""
    text: str = ""
    text_dim: str = ""


@dataclass
class MenuTheme:
    """圆盘菜单外观主题"""
    name: str
    label: str
    inner: RingColors
    outer: RingColors
    extension: RingColors
    dead_zone: str
    dead_zone_outline: str
    center_text: str
    selected_border: str
    border: str
    accent_dim: str
    menu_bg: str = "#010101"
    light: bool = False  # 浅色主题（Quicker 风：白扇面 + 主题色高亮白字 + 扇区间隙）


# ---------- HLS 颜色推导 ----------


def _hex_to_hls(hex_color: str):
    h = hex_color.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255.0 for i in (0, 2, 4))
    return colorsys.rgb_to_hls(r, g, b)  # (hue, lightness, saturation)


def _hls(h: float, l: float, s: float) -> str:
    """hue/lightness/saturation -> hex，越界自动夹紧"""
    r, g, b = colorsys.hls_to_rgb(h % 1.0, max(0.0, min(1.0, l)),
                                  max(0.0, min(1.0, s)))
    return "#%02x%02x%02x" % (int(r * 255), int(g * 255), int(b * 255))


def _derive_ring(h: float, l_normal: float, s_normal: float) -> RingColors:
    """从一个色相推导单层扇区环的完整配色。

    高亮态 = 更饱和 + 略提亮的扇面 + 亮描边 + 柔光晕，文字始终保持
    白字可读（高亮色与白字对比度 >= 4），不靠刷亮背景表达选中。
    """
    l_hl = min(0.52, l_normal + 0.12)
    s_hl = min(0.80, s_normal * 2.6 + 0.18)
    return RingColors(
        normal=_hls(h, l_normal, s_normal),
        empty=_hls(h, l_normal - 0.10, s_normal * 0.55),
        highlight=_hls(h, l_hl, s_hl),
        hover=_hls(h, l_normal + 0.07, min(0.6, s_normal + 0.08)),
        outline=_hls(h, 0.06, min(0.4, s_normal)),
        outline_hl=_hls(h, 0.62, s_hl * 0.7),
        text="#ffffff",
        text_dim=_hls(h, 0.82, 0.10),
    )


# 三层亮度节奏：内层亮 → 外层暗 → 扩展圈居中，制造视觉层次
_INNER_L, _OUTER_L, _EXT_L = 0.35, 0.30, 0.325


def _make_theme(name: str, label: str, h: float, s: float) -> MenuTheme:
    """由主色相生成一套圆盘主题（三层统一质感）"""
    inner = _derive_ring(h, _INNER_L, s)
    return MenuTheme(
        name=name, label=label,
        inner=inner,
        outer=_derive_ring(h, _OUTER_L, s),
        extension=_derive_ring(h, _EXT_L, s),
        dead_zone=_hls(h, 0.075, 0.14),
        dead_zone_outline=_hls(h, 0.20, 0.20),
        center_text="#e9edf2",
        selected_border=inner.highlight,
        border=_hls(h, 0.06, min(0.4, s)),
        accent_dim=_hls(h, 0.40, min(0.65, s + 0.15)),
    )


# ---------- 浅色圆盘主题（浅色界面模式用） ----------

# 浅色主题是 Quicker 风格：近白扇面 + 主题色高亮（高亮时文字反转为白色）
# + 扇区间靠浅色描边/间隙分割，整体干净明亮。


def _derive_ring_light(h: float, s_normal: float) -> RingColors:
    """从色相推导浅色扇区环配色（Quicker 风）。

    普通扇区 = 近白卡片底 + 深色文字；
    高亮扇区 = 淡主题色底 + 主题色描边 + 深色粗体文字（浅色界面下的
    高亮应保持"浅"，不用深色填充，否则看起来像深色模式的高亮）；
    描边 = 浅灰，弱化分割（靠扇区间隙分隔）。
    """
    s_hl = max(0.55, min(0.75, s_normal + 0.38))
    return RingColors(
        normal=_hls(h, 0.975, 0.04),
        empty=_hls(h, 0.91, 0.05),
        highlight=_hls(h, 0.82, 0.38),   # 淡主题色底（浅色高亮）
        hover=_hls(h, 0.90, 0.07),
        outline=_hls(h, 0.80, 0.06),
        outline_hl=_hls(h, 0.48, s_hl),  # 主题色描边（高亮边界清晰）
        text="#1f2430",
        text_dim=_hls(h, 0.46, min(0.35, s_normal + 0.10)),
    )


def make_light_theme(t: MenuTheme) -> MenuTheme:
    """由深色圆盘主题推导浅色版（Quicker 风：白扇面 + 主题色高亮白字）。

    用于浅色界面模式：圆盘配色与浅色 chrome 协调，避免深色圆盘
    在浅色背景下显得突兀。
    """
    def ring(r: RingColors) -> RingColors:
        h, _, s = _hex_to_hls(r.normal)
        return _derive_ring_light(h, s)

    inner = ring(t.inner)
    outer = ring(t.outer)
    ext = ring(t.extension)
    h = _hex_to_hls(t.dead_zone)[0]
    s_hl = max(0.55, min(0.75, _hex_to_hls(t.inner.normal)[2] + 0.38))
    return MenuTheme(
        name=t.name, label=t.label,
        inner=inner,
        outer=outer,
        extension=ext,
        dead_zone=_hls(h, 0.985, 0.03),
        dead_zone_outline=_hls(h, 0.80, 0.06),
        center_text="#20242c",
        selected_border=_hls(h, 0.48, s_hl),
        border=_hls(h, 0.78, 0.05),
        accent_dim=_hls(h, 0.80, min(0.45, _hex_to_hls(t.inner.normal)[2] + 0.20)),
        light=True,
    )


def _hue_of(hex_color: str) -> float:
    return _hex_to_hls(hex_color)[0]


MENU_THEMES: Dict[str, MenuTheme] = {}


def _reg(t: MenuTheme):
    MENU_THEMES[t.name] = t


# 8 套主题：色相取自现主题主色，保证"天蓝还是天蓝"，但由生成器统一质感
_reg(_make_theme("azure", "天蓝", _hue_of("#38bdf8"), 0.30))
_reg(_make_theme("emerald", "翡翠", _hue_of("#34d399"), 0.30))
_reg(_make_theme("crimson", "绯红", _hue_of("#fb7185"), 0.30))
_reg(_make_theme("midnight", "午夜", _hue_of("#a78bfa"), 0.34))
# 极光保留三色特色：内层青、外层紫、扩展圈青（由色相覆盖实现）
_reg(MenuTheme(
    name="aurora", label="极光",
    inner=_derive_ring(_hue_of("#22d3ee"), _INNER_L, 0.30),
    outer=_derive_ring(_hue_of("#a78bfa"), _OUTER_L, 0.34),
    extension=_derive_ring(_hue_of("#22d3ee"), _EXT_L, 0.30),
    dead_zone=_hls(_hue_of("#22d3ee"), 0.075, 0.14),
    dead_zone_outline=_hls(_hue_of("#22d3ee"), 0.20, 0.20),
    center_text="#e9edf2",
    selected_border=_derive_ring(_hue_of("#22d3ee"), _INNER_L, 0.30).highlight,
    border=_hls(_hue_of("#22d3ee"), 0.06, 0.3),
    accent_dim=_hls(_hue_of("#a78bfa"), 0.40, 0.60),
))
_reg(_make_theme("graphite", "石墨", _hue_of("#94a3b8"), 0.22))
_reg(_make_theme("amber", "琥珀", _hue_of("#d9a545"), 0.32))   # 新增
_reg(_make_theme("mono", "单色", _hue_of("#c8d0d8"), 0.0))     # 新增：无彩色

# 自定义主题色相（用户主色），默认给一个柔和蓝
_CUSTOM_ACCENT = "#6fa3d8"


def make_custom_theme(accent: str) -> MenuTheme:
    """由用户自选主色推导整套圆盘主题"""
    h, _, _ = _hex_to_hls(accent)
    return _make_theme("custom", "自定义", h, 0.32)


def get_menu_theme(name: str = "azure",
                   custom_accent: Optional[str] = None) -> MenuTheme:
    """按名称获取圆盘主题；custom 时用自选主色生成，未知名称回退天蓝"""
    if name == "custom":
        return make_custom_theme(custom_accent or _CUSTOM_ACCENT)
    return MENU_THEMES.get(name, MENU_THEMES["azure"])


def theme_from_settings(settings: dict, ui_mode: str = None) -> MenuTheme:
    """从配置 settings 取圆盘主题（含自定义主色）。

    浅色界面模式下自动返回浅色版主题（亮扇面 + 深色文字），
    与浅色 chrome 协调；深色模式返回原深色主题。
    """
    mode = (ui_mode or settings.get("ui_mode", "dark"))
    t = get_menu_theme(settings.get("menu_theme", "azure"),
                       settings.get("custom_accent"))
    if effective_ui_mode(mode) == "light":
        return make_light_theme(t)
    return t
