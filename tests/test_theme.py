"""主题系统测试：生成器 / 自定义主题 / 对比度 / QSS"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.theme import (MENU_THEMES, get_menu_theme, make_custom_theme,
                       theme_from_settings, build_qss, UI)


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
    assert len(MENU_THEMES) >= 8


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
    t = make_custom_theme("#ff8844")
    assert t.name == "custom"
    assert t.label == "自定义"
    # 橙色色相：#ff8844 的 hue 应明显偏暖（>0.05 且 <0.15 附近的橙红）
    from src.theme import _hex_to_hls
    h, _, _ = _hex_to_hls("#ff8844")
    th, _, _ = _hex_to_hls(t.inner.highlight)
    assert abs(h - th) < 0.02, "自定义主题高亮色相应贴近用户主色"


def test_theme_from_settings_custom():
    t = theme_from_settings({"menu_theme": "custom", "custom_accent": "#22aa66"})
    assert t is not None
    assert t.name == "custom"


def test_text_contrast_on_normal():
    """白字在扇区底色上的对比度 >= 4（保证任何主题标签可读）"""
    for t in MENU_THEMES.values():
        for ring in (t.inner, t.outer, t.extension):
            c = _contrast("#ffffff", ring.normal)
            assert c >= 4.0, f"{t.name} normal 对比度不足: {c:.2f}"


def test_center_text_contrast():
    for t in MENU_THEMES.values():
        assert _contrast(t.center_text, t.dead_zone) >= 6.0


def test_build_qss():
    qss = build_qss(UI)
    assert UI.bg in qss          # 背景 token 注入
    assert UI.accent in qss      # 强调色 token 注入
    assert "QPushButton" in qss


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"[OK] {name}")
