"""主题系统测试：生成器 / 自定义主题 / 对比度 / QSS / 界面模式解析"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src.theme import (MENU_THEMES, get_menu_theme, make_custom_theme,
                       theme_from_settings, make_light_theme, build_qss,
                       effective_ui_mode, set_ui_mode, current_ui_mode,
                       get_ui, UI_DARK, UI_LIGHT, UI)


def _lum(hexc):
    h = hexc.lstrip("#")
    r, g, b = (int(h[i:i + 2], 16) / 255 for i in (0, 2, 4))
    def f(c):
        return c / 12.92 if c <= 0.03928 else ((c + 0.055) / 1.055) ** 2.4
    r, g, b = f(r), f(g), f(b)
    return 0.2126 * r + 0.7152 * g + 0.0722 * b


def _contrast(a, b):
    la, lb = _lum(a), _lum(b)
    hi, lo = max(la, lb), min(la, lb)
    return (hi + 0.05) / (lo + 0.05)


def test_theme_count():
    assert len(MENU_THEMES) == 5  # 预设精简为 5 套，其余走自定义


def test_every_theme_complete():
    """每套主题三层环字段齐全且非空"""
    for t in MENU_THEMES.values():
        for ring in (t.inner, t.outer, t.extension):
            for attr in ("normal", "empty", "highlight", "hover",
                         "outline", "outline_hl", "text", "text_dim"):
                assert getattr(ring, attr), f"{t.name}.{attr} 为空"


def test_unknown_theme_fallback():
    t = get_menu_theme("no_such_theme")
    assert t.name == "azure"


def test_custom_theme_follows_accent():
    """自定义主题：主色相跟随用户主色"""
    t = make_custom_theme("#e9edf2", "#ff8844", "#1a202b", "#2a3a4d")
    assert t.name == "custom"
    assert t.label == "自定义"
    # 橙色色相：#ff8844 的 hue 应明显偏暖（>0.05 且 <0.15 附近的橙红）
    from src.theme import _hex_to_hls
    h, _, _ = _hex_to_hls("#ff8844")
    th, _, _ = _hex_to_hls(t.inner.highlight)
    assert abs(h - th) < 0.02, "自定义主题高亮色相应贴近用户主色"


def test_theme_from_settings_custom():
    t = theme_from_settings({"menu_theme": "custom",
                             "custom_text": "#e9edf2",
                             "custom_highlight": "#22aa66",
                             "custom_bg": "#1a202b",
                             "custom_hover": "#2a3a4d"})
    assert t is not None
    assert t.name == "custom"
    assert t.inner.highlight == "#22aa66"
    assert t.inner.text == "#e9edf2"


def test_text_contrast_on_normal():
    """白字在扇区底色上的对比度 >= 4（保证任何主题标签可读）"""
    for t in MENU_THEMES.values():
        for ring in (t.inner, t.outer, t.extension):
            c = _contrast("#ffffff", ring.normal)
            assert c >= 4.0, f"{t.name} normal 对比度不足: {c:.2f}"


def test_center_text_contrast():
    for t in MENU_THEMES.values():
        assert _contrast(t.center_text, t.dead_zone) >= 6.0


def test_light_theme_quicker_style():
    """浅色主题（Quicker 风）：字段齐全 + 白字高亮对比 + 深字浅底对比"""
    for t in MENU_THEMES.values():
        lt = make_light_theme(t)
        assert lt.light is True
        for ring in (lt.inner, lt.outer, lt.extension):
            for attr in ("normal", "empty", "highlight", "hover",
                         "outline", "outline_hl", "text", "text_dim"):
                assert getattr(ring, attr), f"light {t.name}.{attr} 为空"
            # 深字在淡主题色高亮扇面上可读
            assert _contrast(ring.text, ring.highlight) >= 3.0, \
                f"light {t.name} 高亮深字对比不足: {_contrast(ring.text, ring.highlight):.2f}"
            # 深字在近白普通扇面上可读
            assert _contrast(ring.text, ring.normal) >= 6.0, \
                f"light {t.name} 普通扇面深字对比不足"
        # 中心深字与浅色中心区对比
        assert _contrast(lt.center_text, lt.dead_zone) >= 6.0


def test_build_qss():
    qss = build_qss(UI)
    assert UI.bg in qss          # 背景 token 注入
    assert UI.accent in qss      # 强调色 token 注入
    assert "QPushButton" in qss


# ========== 界面模式解析（含跟随系统） ==========


@pytest.fixture(autouse=True)
def _save_ui_mode_state():
    """保存并恢复模块级模式状态，避免测试间相互污染"""
    import src.theme as theme
    saved = (theme._CONFIGURED_MODE, theme._CURRENT_MODE)
    yield
    theme._CONFIGURED_MODE, theme._CURRENT_MODE = saved


def test_effective_ui_mode_plain():
    assert effective_ui_mode("dark") == "dark"
    assert effective_ui_mode("light") == "light"
    assert effective_ui_mode("whatever") == "dark"   # 非法值回退深色
    assert effective_ui_mode(None) == "dark"


def test_effective_ui_mode_system(monkeypatch):
    monkeypatch.setattr("src.theme.system_ui_mode", lambda: "light")
    assert effective_ui_mode("system") == "light"
    monkeypatch.setattr("src.theme.system_ui_mode", lambda: "dark")
    assert effective_ui_mode("system") == "dark"


def test_set_ui_mode_system_follows_system(monkeypatch):
    monkeypatch.setattr("src.theme.system_ui_mode", lambda: "light")
    set_ui_mode("system")
    assert current_ui_mode() == "light"
    assert get_ui() is UI_LIGHT
    monkeypatch.setattr("src.theme.system_ui_mode", lambda: "dark")
    set_ui_mode("system")
    assert current_ui_mode() == "dark"
    assert get_ui() is UI_DARK


def test_get_ui_explicit_mode():
    assert get_ui("light") is UI_LIGHT
    assert get_ui("dark") is UI_DARK


def test_theme_from_settings_system(monkeypatch):
    monkeypatch.setattr("src.theme.system_ui_mode", lambda: "light")
    t = theme_from_settings({"menu_theme": "azure", "ui_mode": "system"})
    assert t.light is True
    monkeypatch.setattr("src.theme.system_ui_mode", lambda: "dark")
    t = theme_from_settings({"menu_theme": "azure", "ui_mode": "system"})
    assert t.light is False


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"[OK] {name}")
