# -*- coding: utf-8 -*-
"""SolidWorks 按键直通（拦截 + 直投）测试

覆盖：
1. 键集解析（区间 / 单键 / 别名 / 容错）；
2. lParam 位域（扫描码、过渡位、前态位）—— 拼错会"发一次响应两次"；
3. 焦点分类（文本控件 vs 绘图区视口 vs 未识别）；
4. 判定真值表：任一守卫命中必须放行（尤其是 injected 放行，那是"不动 CAD"的保证）；
5. 快照发布/读取、投递空窗口防护、拦截器生命周期不抛异常。

只测纯逻辑与无需真实窗口的调用；不安装任何钩子（避免影响跑测试的桌面）。
"""
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import sw_key_assist as sk


# ========== 键集解析 ==========

def test_parse_key_list_default_set():
    keys = sk.parse_key_list(sk.DEFAULT_KEY_LIST)
    assert ord("A") in keys and ord("Z") in keys
    assert ord("0") in keys and ord("9") in keys
    assert 0x20 in keys                     # SPACE
    assert len(keys) == 26 + 10 + 1
    assert ord("a") not in keys             # 存的是大写 VK，小写靠 upper() 归一


def test_parse_key_list_single_and_aliases():
    assert sk.parse_key_list("E") == frozenset({ord("E")})
    assert sk.parse_key_list("e") == frozenset({ord("E")})
    assert sk.parse_key_list("SPACE") == frozenset({0x20})
    assert sk.parse_key_list("空格") == frozenset({0x20})
    assert sk.parse_key_list("") == frozenset()


def test_parse_key_list_separators_and_tolerance():
    a = sk.parse_key_list("A-C, 1-2; 空格")
    assert a == frozenset({ord("A"), ord("B"), ord("C"),
                           ord("1"), ord("2"), 0x20})
    assert sk.parse_key_list("A，B") == frozenset({ord("A"), ord("B")})
    # 无法识别的 token 忽略，不抛异常（配置容错）
    assert sk.parse_key_list("XYZ-,??,A") == frozenset({ord("A")})
    assert sk.parse_key_list("Z-A") == frozenset()   # 反向区间视为无效


# ========== lParam 位域 ==========

def test_build_key_lparam_bitfields():
    vk = ord("E")
    scan = sk.user32.MapVirtualKeyW(vk, 0) & 0xFF
    down = sk.build_key_lparam(vk, False)
    up = sk.build_key_lparam(vk, True)
    assert down & 0xFFFF == 1
    assert (down >> 16) & 0xFF == scan
    assert down & (1 << 31) == 0            # 按下：过渡位 0
    assert up & (1 << 31)                      # 抬起：过渡位 1
    assert up & (1 << 30)                      # 抬起：前态"已按下"
    assert (up >> 16) & 0xFF == scan


def test_build_key_lparam_without_scan():
    lp = sk.build_key_lparam(ord("S"), False, use_scan=False)
    assert (lp >> 16) & 0xFF == 0


# ========== 焦点分类 ==========

def test_classify_text_controls():
    assert sk.classify_focus("Edit") == "text"
    assert sk.classify_focus("RichEdit20W") == "text"
    assert sk.classify_focus("ComboBox") == "text"
    assert sk.classify_focus("SomeSpinBox") == "text"
    # 有插入符 → 一律按文本处理（第二道保险）
    assert sk.classify_focus("WeirdControl", caret_present=True) == "text"


def test_classify_view_controls():
    assert sk.classify_focus("AfxFrameOrView140u") == "view"
    assert sk.classify_focus("GXWND") == "view"
    assert sk.classify_focus("Extra", extra_hints=("extra",)) == "view"
    # MFC 自定义窗口：只有覆盖框架客户区大半才算视口
    assert sk.classify_focus("Afx:0000ABCD:8", coverage=0.9) == "view"
    assert sk.classify_focus("Afx:0000ABCD:8", coverage=0.1) == "unknown"
    assert sk.classify_focus("", focus_is_frame=True, coverage=0.9) == "unknown"
    assert sk.classify_focus("Any", focus_is_frame=True, coverage=0.9) == "view"


def test_classify_unknown_is_conservative():
    # SWCadEditor 这类"以 editor 结尾的视口类"不能被误判成文本输入
    assert sk.classify_focus("SWCadEditor") == "unknown"
    assert sk.classify_focus("SysListView32") == "unknown"
    assert sk.classify_focus("") == "unknown"


def test_classify_ime_focus_overrides_caret():
    """焦点在 IME 组合窗口上时，caret 不应触发 text 判定（快捷键变拼音的根因）。"""
    # 无 IME 焦点 + caret → text（原有行为不变）
    assert sk.classify_focus("Edit", caret_present=True) == "text"
    assert sk.classify_focus("WeirdControl", caret_present=True) == "text"
    # IME 焦点 + caret → 按视口/兜底判定，不再判 text
    assert sk.classify_focus("Edit", caret_present=True,
                             ime_focus=True) == "unknown"
    assert sk.classify_focus("AfxFrameOrView140u", caret_present=True,
                             ime_focus=True) == "view"
    assert sk.classify_focus("IME", caret_present=True,
                             ime_focus=True) == "unknown"


# ========== 判定真值表 ==========

def _snap(**kw):
    base = dict(enabled=True, sw_hwnd=0x1000, focus_hwnd=0x2000,
                focus_kind="view", focus_class="AfxFrameOrView140u",
                composing=False, ime_focus=False,
                elevated_blocked=False,
                delivery_broken=False, keyset=frozenset({ord("E")}))
    base.update(kw)
    return sk.Snap(**base)


def test_should_intercept_happy_path():
    s = _snap()
    assert sk.should_intercept(ord("E"), False, s, 0x1000, False, False)


def test_should_intercept_guards_each_block():
    vk, s = ord("E"), _snap()
    assert not sk.should_intercept(vk, False, s, 0x1000, True, False)     # 注入事件
    assert not sk.should_intercept(vk, True, s, 0x1000, False, False)     # 抬起
    assert not sk.should_intercept(vk, False, s, 0x1000, False, True)     # 组合键
    # 非目标前台 / 快照过期
    assert not sk.should_intercept(vk, False, s, 0x9999, False, False)
    assert not sk.should_intercept(vk, False, _snap(sw_hwnd=0), 0, False, False)
    # 开关与降级
    assert not sk.should_intercept(vk, False, _snap(enabled=False), 0x1000,
                                   False, False)
    assert not sk.should_intercept(vk, False, _snap(delivery_broken=True),
                                   0x1000, False, False)
    assert not sk.should_intercept(vk, False, _snap(elevated_blocked=True),
                                   0x1000, False, False)
    # 键集
    assert not sk.should_intercept(ord("Q"), False, s, 0x1000, False, False)
    # 焦点语境：文本控件 / 未识别 都放行
    assert not sk.should_intercept(vk, False, _snap(focus_kind="text"),
                                   0x1000, False, False)
    assert not sk.should_intercept(vk, False, _snap(focus_kind="unknown"),
                                   0x1000, False, False)
    # 正在拼音组合
    assert not sk.should_intercept(vk, False, _snap(composing=True),
                                   0x1000, False, False)


def test_injected_guard_is_independent_of_other_state():
    """injected 放行必须无条件 —— CAD 的 pyautogui 回退注入键靠这条不被吞。"""
    s = _snap()
    for injected in (True,):
        assert not sk.should_intercept(ord("E"), False, s, 0x1000, injected,
                                       False)


def test_should_intercept_ime_focus_bypasses_composing():
    """焦点在 IME 组合窗口 + 视口语境 → 仍然拦截（跳过 composing 守卫）。"""
    s = _snap(ime_focus=True, composing=True)
    assert sk.should_intercept(ord("E"), False, s, 0x1000, False, False)
    # ime_focus 但焦点不是视口 → 仍放行（未知/文本控件保守档不变）
    assert not sk.should_intercept(ord("E"), False,
                                   _snap(ime_focus=True, focus_kind="unknown"),
                                   0x1000, False, False)
    assert not sk.should_intercept(ord("E"), False,
                                   _snap(ime_focus=True, focus_kind="text"),
                                   0x1000, False, False)


def test_should_intercept_text_field_always_pass():
    """文本输入（含 PropertyManager 改名/尺寸框）一律放行：中文优先于快捷键。

    曾有 pm_edit 单字母例外（焦点在 PM 输入框时仍吞字母投视口），会打断
    拼音组合首字母；已删除。
    """
    s = _snap(focus_kind="text", focus_class="Edit",
              keyset=frozenset({ord("E"), ord("S"), ord("0"), 0x20}))
    assert not sk.should_intercept(ord("E"), False, s, 0x1000, False, False)
    assert not sk.should_intercept(ord("S"), False, s, 0x1000, False, False)
    assert not sk.should_intercept(ord("0"), False, s, 0x1000, False, False)
    assert not sk.should_intercept(0x20, False, s, 0x1000, False, False)


def test_snap_is_immutable_and_replaceable():
    s = _snap()
    s2 = s._replace(enabled=False, delivery_broken=True)
    assert s.enabled is True and s2.enabled is False
    assert s2.delivery_broken is True and s.delivery_broken is False


# ========== 轮询快照 ==========

def test_probe_context_disabled_returns_immediately():
    assert sk.probe_context({"ime_assist_sw": False}).enabled is False
    # layout 模式下按键直通不启用（由布局切换那条路径负责）
    s = sk.probe_context({"ime_assist_sw": True, "ime_assist_mode": "layout"})
    assert s.enabled is False
    assert s.sw_hwnd == 0


def test_probe_context_returns_snap_with_keyset():
    s = sk.probe_context({"ime_assist_sw": True, "ime_assist_mode": "key"})
    assert isinstance(s, sk.Snap)
    assert ord("E") in s.keyset
    # 前台若不是 SLDWORKS，目标句柄必须是 0（绝不对其他窗口动手）
    if s.sw_hwnd == 0:
        assert s.focus_kind == "unknown"


# ========== 投递与生命周期 ==========

def test_post_key_pair_rejects_empty_hwnd():
    assert sk.post_key_pair(0, ord("E")) is False


def test_any_modifier_down_returns_bool():
    assert isinstance(sk._any_modifier_down(), bool)


def test_interceptor_update_and_stop_without_start():
    it = sk.Interceptor(log=None)
    assert it.snapshot().enabled is False
    it.update(_snap())
    assert it.snapshot().sw_hwnd == 0x1000
    it.stop()          # 未启动时停止不应抛异常
    assert it.stats["swallowed"] == 0
