# -*- coding: utf-8 -*-
"""SolidWorks 输入法助手（键盘布局版）测试

覆盖：
1. 只对 sldworks 生效；其他软件/本进程窗口/组合态/读不到布局一律不动；
2. 决策状态机：绘图区→英文布局、文本框→恢复原中文布局；
3. 用户手动 Win+Space 切过 → 尊重不再抢，状态一致后解除；
4. 完整一轮切换（布局写入 + 状态记录）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src import sw_ime_assist as ime

EN = 0x0409
ZH = 0x0804


def _st(**kw):
    d = {"orig": None, "applied": None, "override": False}
    d.update(kw)
    return d


# ========== 目标判定 ==========

def test_is_target_exe_only_sldworks():
    assert ime.is_target_exe(r"D:\Program Files\SOLIDWORKS Corp"
                             r"\SOLIDWORKS\SLDWORKS.exe") is True
    assert ime.is_target_exe("c:/x/sldworks_fs.exe") is True
    assert ime.is_target_exe("acad.exe") is False
    assert ime.is_target_exe("zwcad.exe") is False
    assert ime.is_target_exe("") is False


# ========== 决策状态机 ==========

def test_plan_viewport_chinese_switches_to_english():
    """绘图区 + 中文布局(0804) → 切英文(0409)，并记住原中文布局"""
    mode, st = ime._plan(ZH, want_cn=False, state=_st())
    assert mode == EN
    assert st["orig"] == ZH
    assert st["applied"] == EN


def test_plan_viewport_already_english_noop():
    """绘图区已是英文布局：不动"""
    mode, st = ime._plan(EN, want_cn=False, state=_st(applied=EN))
    assert mode is None
    assert st["override"] is False


def test_plan_text_field_restores_original_chinese():
    """文本框聚焦且我们切过英文（orig 已记录）→ 恢复原中文布局"""
    prev = _st(orig=ZH, applied=EN)
    mode, st = ime._plan(EN, want_cn=True, state=prev)
    assert mode == ZH
    assert st["override"] is False


def test_plan_never_invents_chinese_without_record():
    """从未由我们切走（无 orig 记录）→ 文本框也不发明中文"""
    mode, st = ime._plan(EN, want_cn=True, state=_st())
    assert mode is None
    assert st["override"] is False


def test_plan_respects_manual_switch():
    """用户手动 Win+Space 切回中文（与我们上次写入不一致）→ 尊重，不再抢"""
    prev = _st(orig=ZH, applied=EN)
    mode, st = ime._plan(ZH, want_cn=False, state=prev)
    assert mode is None
    assert st["override"] is True


def test_plan_override_clears_when_matching_again():
    """用户又切回英文后：与目标一致 → override 解除"""
    prev = _st(orig=ZH, applied=EN, override=True)
    mode, st = ime._plan(EN, want_cn=False, state=prev)
    assert mode is None
    assert st["override"] is False
    assert st["applied"] == EN


# ========== run_cycle 作用域护栏（替身注入） ==========

def _install(monkeypatch, **fakes):
    for name, fn in fakes.items():
        monkeypatch.setattr(ime, name, fn)


def test_cycle_noop_when_no_foreground(monkeypatch):
    _install(monkeypatch, get_foreground_hwnd=lambda: 0)
    assert ime.run_cycle() is False


def test_cycle_noop_for_own_window(monkeypatch):
    _install(monkeypatch,
             get_foreground_hwnd=lambda: 0x10,
             _window_pid=lambda h: os.getpid())
    assert ime.run_cycle() is False


def test_cycle_noop_for_other_apps(monkeypatch):
    _install(monkeypatch,
             get_foreground_hwnd=lambda: 0x10,
             _window_pid=lambda h: 4242,
             _exe_of_pid=lambda pid: r"C:\Program Files\acad.exe")
    assert ime.run_cycle() is False


def test_cycle_noop_while_composing(monkeypatch):
    """正在打拼音：一律不动作"""
    _install(monkeypatch,
             get_foreground_hwnd=lambda: 0x10,
             _window_pid=lambda h: 4242,
             _exe_of_pid=lambda pid: "SLDWORKS.exe",
             _ime_composing=lambda h: True)
    assert ime.run_cycle() is False


def test_cycle_noop_when_layout_unreadable(monkeypatch):
    """读不到目标线程布局（非前台等）：不盲切"""
    _install(monkeypatch,
             get_foreground_hwnd=lambda: 0x10,
             _window_pid=lambda h: 4242,
             _exe_of_pid=lambda pid: "SLDWORKS.exe",
             _ime_composing=lambda h: False,
             _thread_layout_low=lambda h: 0)
    assert ime.run_cycle() is False


def test_cycle_viewport_switches_to_english_layout(monkeypatch):
    """完整一轮：SW 绘图区 + 中文布局 → 调 _set_layout_low(0409) 并记录状态"""
    calls = {}

    def set_layout(hwnd, lang):
        calls["lang"] = lang
        return True

    _install(monkeypatch,
             get_foreground_hwnd=lambda: 0x10,
             _window_pid=lambda h: 4242,
             _exe_of_pid=lambda pid: "SLDWORKS.exe",
             _ime_composing=lambda h: False,
             _thread_layout_low=lambda h: ZH,
             _focus_control_class=lambda h: "VETabWindowsCtrl",
             _set_layout_low=set_layout)
    assert ime.run_cycle() is True
    assert calls.get("lang") == EN
    with ime._LOCK:
        assert ime._PID_STATE[4242]["orig"] == ZH
        ime._PID_STATE.pop(4242, None)


def test_cycle_text_field_restores_chinese_layout(monkeypatch):
    """SW 文本框聚焦（英文布局是我们之前切的）→ 恢复中文布局"""
    with ime._LOCK:
        ime._PID_STATE[4242] = _st(orig=ZH, applied=EN)
    calls = {}

    def set_layout(hwnd, lang):
        calls["lang"] = lang
        return True

    _install(monkeypatch,
             get_foreground_hwnd=lambda: 0x10,
             _window_pid=lambda h: 4242,
             _exe_of_pid=lambda pid: "SLDWORKS.exe",
             _ime_composing=lambda h: False,
             _thread_layout_low=lambda h: EN,
             _focus_control_class=lambda h: "Edit",
             _set_layout_low=set_layout)
    assert ime.run_cycle() is True
    assert calls.get("lang") == ZH
    with ime._LOCK:
        ime._PID_STATE.pop(4242, None)
