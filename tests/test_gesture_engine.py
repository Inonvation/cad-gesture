"""手势引擎松手结算规则测试：中心圆区不触发命令"""

import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.gesture_engine import (should_trigger_on_release,
                                should_trigger_now, calc_sector)

DEAD = 24.0
TRIG = 15.0
HOLD = 100.0


def test_menu_shown_center_release_cancels():
    """菜单已弹出 + 松手在中心死区内 → 不触发（停在中心区误触发回归）"""
    assert not should_trigger_on_release(True, 10.0, DEAD, TRIG, 500, HOLD)
    assert not should_trigger_on_release(True, 23.9, DEAD, TRIG, 500, HOLD)
    assert not should_trigger_on_release(True, 0.0, DEAD, TRIG, 500, HOLD)


def test_menu_shown_sector_release_triggers():
    """菜单已弹出 + 松手在死区外 → 按最终位置触发"""
    assert should_trigger_on_release(True, 24.0, DEAD, TRIG, 500, HOLD)
    assert should_trigger_on_release(True, 50.0, DEAD, TRIG, 500, HOLD)
    assert should_trigger_on_release(True, 100.0, DEAD, TRIG, 500, HOLD)


def test_menu_shown_slide_back_to_center_cancels():
    """滑到扇区后返回中心松手 → 不触发之前扇区（滑动返回回归）"""
    # 模拟：按下原点 → 滑到 (100,0) → 返回 (10,0) 松手
    assert not should_trigger_on_release(True, 10.0, DEAD, TRIG, 500, HOLD)


def test_flick_fallback_unchanged():
    """快速甩动兜底（菜单未弹出）：距离 + 按住时长条件不变"""
    assert not should_trigger_on_release(False, 14.9, DEAD, TRIG, 500, HOLD)
    assert should_trigger_on_release(False, 15.0, DEAD, TRIG, 500, HOLD)
    assert not should_trigger_on_release(False, 30.0, DEAD, TRIG, 50, HOLD)
    assert not should_trigger_on_release(False, 5.0, DEAD, TRIG, 500, HOLD)


def test_calc_sector_stable():
    """扇区计算不变（回归保护）"""
    assert calc_sector(0, 100, 8) == 0
    assert calc_sector(100, 0, 8) == 2


if __name__ == "__main__":
    for name, fn in sorted(globals().items()):
        if name.startswith("test_"):
            fn()
            print(f"[OK] {name}")



def test_should_trigger_now_slide_immediate():
    """滑动超过触发距离立即弹出，不要求长按时间（Quicker 风格）"""
    assert should_trigger_now(10.0, 5.0, 10.0, 80.0)      # 距离达标，时间很短也触发
    assert should_trigger_now(50.0, 0.0, 10.0, 80.0)
    assert not should_trigger_now(9.9, 50.0, 10.0, 80.0)  # 距离不足且未到长按延迟不触发


def test_should_trigger_now_long_press():
    """按住超过长按延迟且有轻微位移（去手抖）时触发"""
    assert should_trigger_now(3.0, 80.0, 10.0, 80.0)
    assert should_trigger_now(5.0, 120.0, 10.0, 80.0)
    assert not should_trigger_now(2.9, 120.0, 10.0, 80.0)  # 位移太小视为手抖


def test_should_trigger_now_hold_without_move():
    """按住不动（位移 0）不触发"""
    assert not should_trigger_now(0.0, 500.0, 10.0, 80.0)


def test_trigger_button_mapping():
    """触发键映射：右键 / 中键 / 侧键 1 / 侧键 2"""
    import src.gesture_engine as ge
    from src.gesture_engine import GestureEngine

    def make(btn):
        eng = GestureEngine(config={"settings": {"trigger_button": btn}},
                            on_gesture=lambda *a: None,
                            on_gesture_feedback=lambda *a: None,
                            on_menu_show=lambda *a: None,
                            on_menu_hide=lambda *a: None,
                            on_extension_hint=lambda *a: None)
        return eng

    eng = make("right")
    assert eng._trigger_down(ge.WM_RBUTTONDOWN, 0)
    assert eng._trigger_up(ge.WM_RBUTTONUP, 0)
    assert not eng._trigger_down(ge.WM_MBUTTONDOWN, 0)

    eng = make("middle")
    assert eng._trigger_down(ge.WM_MBUTTONDOWN, 0)
    assert eng._trigger_up(ge.WM_MBUTTONUP, 0)
    assert not eng._trigger_down(ge.WM_RBUTTONDOWN, 0)

    eng = make("x1")
    assert eng._trigger_down(ge.WM_XBUTTONDOWN, ge.XBUTTON1 << 16)
    assert not eng._trigger_down(ge.WM_XBUTTONDOWN, ge.XBUTTON2 << 16)
    assert eng._trigger_up(ge.WM_XBUTTONUP, ge.XBUTTON1 << 16)

    eng = make("x2")
    assert eng._trigger_down(ge.WM_XBUTTONDOWN, ge.XBUTTON2 << 16)
    assert not eng._trigger_down(ge.WM_XBUTTONDOWN, ge.XBUTTON1 << 16)

def test_physical_to_logical():
    """物理像素→逻辑像素换算：DPR 有效时缩放，无效时按 1:1"""
    from src.gesture_engine import physical_to_logical
    assert physical_to_logical(80, 1.25) == 64.0
    assert physical_to_logical(87.5, 1.25) == 70.0
    assert physical_to_logical(80, 1.0) == 80.0
    assert physical_to_logical(80, 0) == 80.0
    assert physical_to_logical(80, -1) == 80.0


def test_ring_resolution_matches_visual_at_dpi():
    """高 DPI（125%）下松手圈层判定与圆盘显示一致（回归保护）

    钩子给物理像素、圆盘半径是逻辑像素；若不做换算，物理距离落在
    70~87.5px 区间会被判成外层，而圆盘显示仍是内层——"命令提示不同步"。
    """
    from src.gesture_engine import GestureEngine, physical_to_logical
    from src.menu_geometry import scaled_radius

    cfg = {"settings": {"menu_scale": 100}}
    dpr = 1.25
    eng = GestureEngine(config=cfg, on_gesture=lambda *a: None,
                        on_gesture_feedback=lambda *a: None,
                        on_menu_show=lambda *a: None,
                        on_menu_hide=lambda *a: None,
                        on_extension_hint=lambda *a: None)

    def visual_ring(phys: float) -> str:
        # 与 qt_radial_menu.update_highlight 一致：扩展圈边界是 outer_ring_radius
        d = phys / dpr
        if d > scaled_radius(cfg["settings"], "outer_ring_radius"):
            return "extension"
        if d > scaled_radius(cfg["settings"], "ring_radius"):
            return "outer"
        if d > scaled_radius(cfg["settings"], "dead_zone_radius"):
            return "inner"
        return "dead"

    dead = scaled_radius(cfg["settings"], "dead_zone_radius")
    for phys in range(0, 300):
        logical = physical_to_logical(phys, dpr)
        if logical <= dead:
            continue  # 死区内不触发命令，不校验圈层
        ring = eng._resolve_gesture(100, 0, logical)[1]
        assert ring == visual_ring(phys), f"phys={phys}px"



def _simulate_hook(engine, wparam, x, y):
    """构造低级鼠标钩子事件并调用 _hook_proc_impl（不启动真实钩子）"""
    import ctypes
    from src.gesture_engine import HC_ACTION, MSLLHOOKEX
    msll = MSLLHOOKEX()
    msll.pt.x, msll.pt.y = x, y
    lp = ctypes.cast(ctypes.pointer(msll), ctypes.c_void_p).value
    return engine._hook_proc_impl(HC_ACTION, wparam, lp)


def _make_recording_engine():
    """返回 (engine, calls)：calls 记录 hide 标记与 gesture 回调"""
    from src.gesture_engine import GestureEngine
    calls = {"hide": [], "gesture": []}
    eng = GestureEngine(
        config={"settings": {"trigger_distance": 15, "hold_threshold_ms": 80,
                             "dead_zone_radius": 24, "menu_scale": 100}},
        on_gesture=lambda *a: calls["gesture"].append(a),
        on_gesture_feedback=lambda *a: None,
        on_menu_show=lambda *a: None,
        on_menu_hide=lambda flag: calls["hide"].append(flag),
        on_extension_hint=lambda *a: None)
    eng._detect_window_type = lambda: "autocad"  # 测试桩：命中 CAD 窗口
    return eng, calls


def test_plain_right_click_preserves_cad_context_menu(monkeypatch):
    """无滑动普通右键：hide 事件不要求取消 CAD 菜单，也不触发手势

    回归：ce7eb79 把 ESC 取消从命令路径挪到每次右键松手后，普通右键的
    CAD 原生菜单被 ESC 关掉。现在只有实际手势交互才发 ESC。
    """
    import ctypes
    from src.gesture_engine import WM_RBUTTONDOWN, WM_RBUTTONUP
    monkeypatch.setattr(ctypes.windll.user32, "CallNextHookEx", lambda *a: 0)
    eng, calls = _make_recording_engine()
    _simulate_hook(eng, WM_RBUTTONDOWN, 100, 100)
    _simulate_hook(eng, WM_RBUTTONUP, 100, 100)
    assert calls["hide"] == [False], calls["hide"]
    assert calls["gesture"] == []


def test_menu_shown_center_release_still_cancels_cad_menu(monkeypatch):
    """圆盘已弹出 + 中心死区松手（取消手势）：仍需取消 CAD 菜单"""
    import ctypes
    from src.gesture_engine import WM_RBUTTONDOWN, WM_RBUTTONUP
    monkeypatch.setattr(ctypes.windll.user32, "CallNextHookEx", lambda *a: 0)
    eng, calls = _make_recording_engine()
    _simulate_hook(eng, WM_RBUTTONDOWN, 100, 100)
    with eng._lock:
        eng._menu_shown = True
    _simulate_hook(eng, WM_RBUTTONUP, 100, 100)
    assert calls["hide"] == [True], calls["hide"]
    assert calls["gesture"] == []


def test_menu_shown_sector_release_cancels_cad_menu(monkeypatch):
    """圆盘已弹出 + 死区外松手：触发命令且取消 CAD 菜单"""
    import ctypes
    from src.gesture_engine import WM_RBUTTONDOWN, WM_RBUTTONUP
    monkeypatch.setattr(ctypes.windll.user32, "CallNextHookEx", lambda *a: 0)
    eng, calls = _make_recording_engine()
    _simulate_hook(eng, WM_RBUTTONDOWN, 100, 100)
    with eng._lock:
        eng._menu_shown = True
    _simulate_hook(eng, WM_RBUTTONUP, 130, 100)
    assert calls["hide"] == [True], calls["hide"]
    assert len(calls["gesture"]) == 1


def test_flick_fallback_release_cancels_cad_menu(monkeypatch):
    """快速甩动兜底（未弹圆盘但触发命令）：松手仍需取消 CAD 菜单"""
    import ctypes
    from src.gesture_engine import WM_RBUTTONDOWN, WM_RBUTTONUP
    monkeypatch.setattr(ctypes.windll.user32, "CallNextHookEx", lambda *a: 0)
    eng, calls = _make_recording_engine()
    _simulate_hook(eng, WM_RBUTTONDOWN, 100, 100)
    with eng._lock:
        eng._press_time -= 1.0  # 按住够久，满足快速甩动兜底条件
    _simulate_hook(eng, WM_RBUTTONUP, 130, 100)
    assert calls["hide"] == [True], calls["hide"]
    assert len(calls["gesture"]) == 1


def test_aborted_flick_preserves_cad_context_menu(monkeypatch):
    """甩动未达触发距离：不取消 CAD 菜单，也不触发命令"""
    import ctypes
    from src.gesture_engine import WM_RBUTTONDOWN, WM_RBUTTONUP
    monkeypatch.setattr(ctypes.windll.user32, "CallNextHookEx", lambda *a: 0)
    eng, calls = _make_recording_engine()
    _simulate_hook(eng, WM_RBUTTONDOWN, 100, 100)
    with eng._lock:
        eng._press_time -= 1.0
    _simulate_hook(eng, WM_RBUTTONUP, 105, 100)  # 只拖出 5px
    assert calls["hide"] == [False], calls["hide"]
    assert calls["gesture"] == []



def _clamp_engine(settings):
    from src.gesture_engine import GestureEngine
    return GestureEngine(
        config={"settings": settings},
        on_gesture=lambda *a: None,
        on_gesture_feedback=lambda *a: None,
        on_menu_show=lambda *a: None,
        on_menu_hide=lambda *a: None,
        on_extension_hint=lambda *a: None)


def test_trigger_distance_clamped():
    eng = _clamp_engine({"trigger_distance": 0, "sector_count": 100})
    assert eng.trigger_distance == 5
    assert eng.sector_count == 24


def test_trigger_values_invalid_fallback_defaults():
    eng = _clamp_engine({"trigger_distance": "abc", "sector_count": None})
    assert eng.trigger_distance == 10
    assert eng.sector_count == 8


def test_trigger_values_normal():
    eng = _clamp_engine({"trigger_distance": 15, "sector_count": 8})
    assert eng.trigger_distance == 15
    assert eng.sector_count == 8
