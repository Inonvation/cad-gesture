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
                            on_menu_show=lambda *a: None,
                            on_menu_hide=lambda: None,
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
