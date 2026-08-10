"""app 层界面模式轮询逻辑测试（只测判断逻辑，不创建 QApplication / 钩子）"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from src import app as app_mod


class _FakeApp:
    """CADGestureApp 的最小替身，只含 _poll_system_theme 用到的成员"""

    def __init__(self, ui_mode="system", applied="dark"):
        self.config = {"settings": {"ui_mode": ui_mode}}
        self._applied_mode = applied
        self.calls = []

    def _apply_ui_mode(self, mode):
        self.calls.append(mode)


def test_poll_skips_non_system_mode():
    fa = _FakeApp(ui_mode="dark")
    app_mod.CADGestureApp._poll_system_theme(fa)
    assert fa.calls == []


def test_poll_applies_when_system_theme_changed(monkeypatch):
    fa = _FakeApp(ui_mode="system", applied="dark")
    monkeypatch.setattr(app_mod, "system_ui_mode", lambda: "light")
    app_mod.CADGestureApp._poll_system_theme(fa)
    assert fa.calls == ["system"]


def test_poll_noop_when_system_theme_unchanged(monkeypatch):
    fa = _FakeApp(ui_mode="system", applied="light")
    monkeypatch.setattr(app_mod, "system_ui_mode", lambda: "light")
    app_mod.CADGestureApp._poll_system_theme(fa)
    assert fa.calls == []


def test_wake_queue_wakes_on_put():
    """事件入队立即唤醒主线程（呼出菜单低延迟的关键）"""
    calls = []
    q = app_mod._WakeQueue(lambda: calls.append(1))
    q.put(("show", (1, 2, "autocad")))
    assert calls == [1]
    q.put(("hide", None))
    assert calls == [1, 1]
