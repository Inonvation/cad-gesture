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

def test_cmd_worker_runs_in_background(monkeypatch):
    """命令执行在后台线程：入队立即返回，worker 随后执行，不阻塞主线程

    回归保护：COM SendCommand 在 CAD 忙时可能阻塞数秒，若在主线程执行，
    弹窗/菜单/下一次手势全部排队等待（用户反馈"弹窗滞后一个手势"）。
    """
    import queue
    import threading
    import time

    calls = []

    def fake_exec(key, desc, target):
        calls.append((key, desc, target, threading.current_thread().name))
        time.sleep(0.1)  # 模拟慢命令
        return "ok"

    monkeypatch.setattr(app_mod, "execute_with_cancel", fake_exec)

    class _NoopLog:
        def error(self, *a, **k):
            pass

        def warning(self, *a, **k):
            pass

    class _FakeCmdApp:
        def __init__(self):
            self._cmd_queue = queue.Queue()
            self.log = _NoopLog()

    fake = _FakeCmdApp()
    t = threading.Thread(
        target=app_mod.CADGestureApp._cmd_worker_loop,
        args=(fake,), daemon=True)
    t.start()

    t0 = time.perf_counter()
    fake._cmd_queue.put(("l", "LINE", "zwcad"))
    enqueue_ms = (time.perf_counter() - t0) * 1000
    assert enqueue_ms < 50, f"入队被阻塞 {enqueue_ms:.0f}ms，命令执行应异步化"

    deadline = time.time() + 2
    while time.time() < deadline and not calls:
        time.sleep(0.01)
    assert calls, "worker 未执行命令"
    assert calls[0][:3] == ("l", "LINE", "zwcad")
    assert calls[0][3] != threading.main_thread().name
