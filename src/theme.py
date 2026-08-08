"""统一配色方案 — 深色/浅色两套主题"""

from dataclasses import dataclass
from typing import Dict


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
class ThemeColors:
    """完整 UI 配色"""
    bg: str
    card_bg: str
    text: str
    text_dim: str
    text_secondary: str
    accent: str
    accent_hover: str
    accent_dim: str
    border: str
    border_light: str
    inner: RingColors
    outer: RingColors
    extension: RingColors
    dead_zone: str
    dead_zone_outline: str
    selected_border: str
    panel_bg: str
    sidebar_bg: str
    preset_bg: str
    preset_hover: str
    drag_proxy_bg: str
    menu_bg: str = "#010101"
    center_text: str = "#ffffff"


DARK_THEME = ThemeColors(
    bg="#0d1017",
    card_bg="#161b23",
    text="#e6e9ef",
    text_dim="#8a93a3",
    text_secondary="#a8b2bf",
    accent="#38bdf8",
    accent_hover="#0ea5e9",
    accent_dim="#0369a1",
    border="#232a34",
    border_light="#2c3542",
    inner=RingColors(
        normal="#2a4f78",
        empty="#182940",
        highlight="#38bdf8",
        hover="#3a6b9a",
        outline="#0f1319",
        outline_hl="#7dd3fc",
        text="#ffffff",
        text_dim="#c9d6e2",
    ),
    outer=RingColors(
        normal="#1e3a5c",
        empty="#132338",
        highlight="#38bdf8",
        hover="#2b5278",
        outline="#0f1319",
        outline_hl="#7dd3fc",
        text="#ffffff",
        text_dim="#a9bccd",
    ),
    extension=RingColors(
        normal="#24507a",
        empty="#15273a",
        highlight="#38bdf8",
        hover="#2b5278",
        outline="#0f1319",
        outline_hl="#7dd3fc",
        text="#ffffff",
        text_dim="#b0c4d8",
    ),
    dead_zone="#10141a",
    dead_zone_outline="#29323e",
    selected_border="#38bdf8",
    panel_bg="#12161d",
    sidebar_bg="#0f1319",
    preset_bg="#1b212b",
    preset_hover="#252d39",
    drag_proxy_bg="#38bdf8",
    menu_bg="#010101",
    center_text="#e8ecf0",
)

LIGHT_THEME = ThemeColors(
    bg="#f0f0f0",
    card_bg="#ffffff",
    text="#1a1a1a",
    text_dim="#888888",
    text_secondary="#555555",
    accent="#0078D4",
    accent_hover="#1a86d9",
    accent_dim="#005a9e",
    border="#d0d0d0",
    border_light="#e0e0e0",
    inner=RingColors(
        normal="#d4e8f8",
        empty="#e8f0f8",
        highlight="#0078D4",
        hover="#b0d0ec",
        outline="#b0cce0",
        outline_hl="#1a86d9",
        text="#1a1a1a",
        text_dim="#888888",
    ),
    outer=RingColors(
        normal="#dce8f0",
        empty="#e8f0f4",
        highlight="#0078D4",
        hover="#c0d8e8",
        outline="#c0d4e0",
        outline_hl="#1a86d9",
        text="#1a1a1a",
        text_dim="#888888",
    ),
    extension=RingColors(
        normal="#e0ecf4",
        empty="#eaf0f8",
        highlight="#0078D4",
        hover="#c4dcec",
        outline="#c8dce8",
        outline_hl="#1a86d9",
        text="#1a1a1a",
        text_dim="#888888",
    ),
    dead_zone="#e8e8e8",
    dead_zone_outline="#d0d0d0",
    selected_border="#0078D4",
    panel_bg="#fafafa",
    sidebar_bg="#f0f0f0",
    preset_bg="#f5f5f5",
    preset_hover="#e8e8e8",
    drag_proxy_bg="#0078D4",
    menu_bg="#010101",
    center_text="#1a1a1a",
)


def get_theme(is_dark: bool = True) -> ThemeColors:
    return DARK_THEME if is_dark else LIGHT_THEME


# ========== 圆盘菜单外观主题（仅圆盘配色，不含界面 chrome） ==========


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


MENU_THEMES: Dict[str, MenuTheme] = {}


def _reg(t: MenuTheme):
    MENU_THEMES[t.name] = t


_reg(MenuTheme(
    name="azure", label="天蓝",
    inner=RingColors(normal="#2a4f78", empty="#182940", highlight="#38bdf8",
                     hover="#3a6b9a", outline="#0f1319", outline_hl="#7dd3fc",
                     text="#ffffff", text_dim="#c9d6e2"),
    outer=RingColors(normal="#1e3a5c", empty="#132338", highlight="#38bdf8",
                     hover="#2b5278", outline="#0f1319", outline_hl="#7dd3fc",
                     text="#ffffff", text_dim="#a9bccd"),
    extension=RingColors(normal="#24507a", empty="#15273a", highlight="#38bdf8",
                         hover="#2b5278", outline="#0f1319", outline_hl="#7dd3fc",
                         text="#ffffff", text_dim="#b0c4d8"),
    dead_zone="#10141a", dead_zone_outline="#29323e",
    center_text="#e8ecf0", selected_border="#38bdf8",
    border="#0f1319", accent_dim="#0369a1",
))

_reg(MenuTheme(
    name="emerald", label="翡翠",
    inner=RingColors(normal="#1e5a48", empty="#14362c", highlight="#34d399",
                     hover="#2a745c", outline="#0e1412", outline_hl="#6ee7b7",
                     text="#ffffff", text_dim="#c3ddd2"),
    outer=RingColors(normal="#174736", empty="#0f2d23", highlight="#34d399",
                     hover="#1e5a48", outline="#0e1412", outline_hl="#6ee7b7",
                     text="#ffffff", text_dim="#a9c9bc"),
    extension=RingColors(normal="#1b5a46", empty="#103026", highlight="#34d399",
                         hover="#1e5a48", outline="#0e1412", outline_hl="#6ee7b7",
                         text="#ffffff", text_dim="#b3d4c7"),
    dead_zone="#0f1417", dead_zone_outline="#1f3a30",
    center_text="#e8f2ec", selected_border="#34d399",
    border="#0e1412", accent_dim="#0f766e",
))

_reg(MenuTheme(
    name="crimson", label="绯红",
    inner=RingColors(normal="#7a2f45", empty="#401a26", highlight="#fb7185",
                     hover="#8a3a52", outline="#160f13", outline_hl="#fda4af",
                     text="#ffffff", text_dim="#e2c3cc"),
    outer=RingColors(normal="#5c2238", empty="#341722", highlight="#fb7185",
                     hover="#6e2a40", outline="#160f13", outline_hl="#fda4af",
                     text="#ffffff", text_dim="#cfadb8"),
    extension=RingColors(normal="#6e2a40", empty="#381725", highlight="#fb7185",
                         hover="#7a2f45", outline="#160f13", outline_hl="#fda4af",
                         text="#ffffff", text_dim="#d8b7c2"),
    dead_zone="#160f13", dead_zone_outline="#3a1e2a",
    center_text="#fce8ec", selected_border="#fb7185",
    border="#160f13", accent_dim="#9f1239",
))

_reg(MenuTheme(
    name="midnight", label="午夜",
    inner=RingColors(normal="#43358a", empty="#241d4d", highlight="#a78bfa",
                     hover="#52429e", outline="#100f1a", outline_hl="#c4b5fd",
                     text="#ffffff", text_dim="#d2cbea"),
    outer=RingColors(normal="#33286b", empty="#1c1739", highlight="#a78bfa",
                     hover="#3d2f7d", outline="#100f1a", outline_hl="#c4b5fd",
                     text="#ffffff", text_dim="#bdb4dd"),
    extension=RingColors(normal="#3a2f7d", empty="#1f1a42", highlight="#a78bfa",
                         hover="#43358a", outline="#100f1a", outline_hl="#c4b5fd",
                         text="#ffffff", text_dim="#c6bde2"),
    dead_zone="#0f0e16", dead_zone_outline="#2c2550",
    center_text="#efeafc", selected_border="#a78bfa",
    border="#100f1a", accent_dim="#6d28d9",
))

_reg(MenuTheme(
    name="aurora", label="极光",
    inner=RingColors(normal="#2b4d8a", empty="#182942", highlight="#22d3ee",
                     hover="#3a6b9a", outline="#0e1120", outline_hl="#67e8f9",
                     text="#ffffff", text_dim="#c6d6ee"),
    outer=RingColors(normal="#5b3a8a", empty="#311a4d", highlight="#a78bfa",
                     hover="#6b4a9e", outline="#120e22", outline_hl="#c4b5fd",
                     text="#ffffff", text_dim="#d0c3e4"),
    extension=RingColors(normal="#1e5a7a", empty="#14303d", highlight="#22d3ee",
                         hover="#2a6b8a", outline="#0d1418", outline_hl="#67e8f9",
                         text="#ffffff", text_dim="#b3cdd8"),
    dead_zone="#0f111a", dead_zone_outline="#2a3550",
    center_text="#ecf2fb", selected_border="#22d3ee",
    border="#0e1120", accent_dim="#0e7490",
))

_reg(MenuTheme(
    name="graphite", label="石墨",
    inner=RingColors(normal="#3a4048", empty="#22262c", highlight="#94a3b8",
                     hover="#484f58", outline="#0e1013", outline_hl="#cbd5e1",
                     text="#ffffff", text_dim="#c8cdd4"),
    outer=RingColors(normal="#2e333a", empty="#1b1e23", highlight="#94a3b8",
                     hover="#3a4048", outline="#0e1013", outline_hl="#cbd5e1",
                     text="#ffffff", text_dim="#b3b9c0"),
    extension=RingColors(normal="#343a42", empty="#1e2227", highlight="#94a3b8",
                         hover="#3a4048", outline="#0e1013", outline_hl="#cbd5e1",
                         text="#ffffff", text_dim="#bcc2c9"),
    dead_zone="#0d0e10", dead_zone_outline="#2e3338",
    center_text="#e8eaed", selected_border="#94a3b8",
    border="#0e1013", accent_dim="#334155",
))


def get_menu_theme(name: str = "azure") -> MenuTheme:
    """按名称获取圆盘外观主题，未知名称回退到默认天蓝"""
    return MENU_THEMES.get(name, MENU_THEMES["azure"])