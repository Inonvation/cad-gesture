# -*- coding: utf-8 -*-
"""暂停快捷键模块：快捷键解析/安全校验 + 真实注册周期（Win32 RegisterHotKey）"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.hotkey_pause import (MOD_ALT, MOD_CONTROL, MOD_SHIFT, MOD_WIN,
                              PauseHotkey, is_valid_hotkey, parse_hotkey)


def test_parse_hotkey_basic():
    """Qt PortableText 风格字符串 → (modifiers, vk)"""
    assert parse_hotkey("Ctrl+Alt+P") == (MOD_CONTROL | MOD_ALT, 0x50)
    assert parse_hotkey("ctrl+shift+f5") == (MOD_CONTROL | MOD_SHIFT, 0x74)
    assert parse_hotkey("Meta+P") == (MOD_WIN, 0x50)   # Qt 的 Meta = Win 键
    assert parse_hotkey("Windows+K") == (MOD_WIN, 0x4B)
    assert parse_hotkey("F9") == (0, 0x78)
    assert parse_hotkey("Ctrl+Enter") == (MOD_CONTROL, 0x0D)
    assert parse_hotkey("Ctrl+,") == (MOD_CONTROL, 0xBC)


def test_parse_hotkey_invalid():
    """缺主键 / 多段组合 / 未识别键名 → None"""
    assert parse_hotkey("") is None
    assert parse_hotkey("Ctrl+") is None
    assert parse_hotkey("Ctrl+X, Ctrl+C") is None
    assert parse_hotkey("Ctrl+乱码") is None
    assert parse_hotkey(None) is None


def test_is_valid_hotkey_safety_rule():
    """带 Ctrl/Alt/Win 修饰才安全；Shift 单独修饰与裸键不放行，F 单键允许"""
    assert is_valid_hotkey("Ctrl+Alt+P")
    assert is_valid_hotkey("Ctrl+P")
    assert is_valid_hotkey("Win+Space")
    assert is_valid_hotkey("F9")            # F1~F24 单键不与打字冲突
    assert not is_valid_hotkey("P")         # 裸字母会全局吞掉打字
    assert not is_valid_hotkey("1")
    assert not is_valid_hotkey("Shift+P")   # 大写字母同样影响打字
    assert not is_valid_hotkey("Ctrl+X, Ctrl+C")
    assert not is_valid_hotkey("")


def test_pause_hotkey_register_cycle():
    """真实注册周期：注册 / 换键 / 注销 / 线程退出均成功（Ctrl+Alt+F15 无冲突）"""
    hk = PauseHotkey(on_toggle=lambda: None)
    try:
        assert hk.start()
        ok, err = hk.set_hotkey("Ctrl+Alt+F15")
        assert ok, f"注册失败: {err}"
        # 同键重复设置：短路成功，不重复注册
        ok, err = hk.set_hotkey("Ctrl+Alt+F15")
        assert ok, f"重复设置失败: {err}"
        ok, err = hk.set_hotkey("")  # 注销
        assert ok, f"注销失败: {err}"
        # 注销后可再注册
        ok, err = hk.set_hotkey("Ctrl+Alt+F14")
        assert ok, f"再次注册失败: {err}"
        ok, _ = hk.set_hotkey("")
        assert ok
    finally:
        hk.stop()


def test_pause_hotkey_rejects_unsafe_combo():
    """会干扰打字的组合在 set_hotkey 入口被拒绝，不触达系统注册"""
    hk = PauseHotkey(on_toggle=lambda: None)
    try:
        assert hk.start()
        ok, err = hk.set_hotkey("P")
        assert not ok and err == "invalid"
        ok, err = hk.set_hotkey("Shift+P")
        assert not ok and err == "invalid"
    finally:
        hk.stop()


def test_pause_hotkey_stop_is_idempotent():
    """未 start 直接 stop / 重复 stop 都安全"""
    hk = PauseHotkey(on_toggle=lambda: None)
    hk.stop()
    hk.stop()
