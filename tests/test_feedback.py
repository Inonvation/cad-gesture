"""命令反馈组件与新增设置页测试"""
import os
import sys
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

from PySide6.QtWidgets import QApplication


def _app():
    return QApplication.instance() or QApplication([])


def test_feedback_tip_show_and_hide():
    """反馈提示：显示后按时长自动淡出（模拟 hide_timer 触发）"""
    _app()
    from src.qt_feedback import QFeedbackTip
    tip = QFeedbackTip()
    tip.show_feedback("直线", "L", {"feedback_duration_ms": 500,
                                    "feedback_position": "bottom_center"})
    QApplication.processEvents()  # 延迟一帧显示，处理后再验证可见
    assert tip.isVisible()
    tip._hide_timer.stop()
    tip.hide()


def test_feedback_page_controls():
    """命令反馈设置页：开关 / 位置 / 名称 / 快捷键 / 时长齐全"""
    _app()
    from src.qt_settings_panel import TriggerPage
    page = TriggerPage({"settings": {}})
    assert page.chk_feedback.isChecked() is True
    assert page.chk_name.isChecked() is True
    assert page.chk_key.isChecked() is True
    assert "feedback_duration_ms" in page._slider_labels
    assert "feedback_offset_x" in page._slider_labels
    assert "feedback_offset_y" in page._slider_labels
    assert page.pos_combo.count() >= 7


def test_test_page_constructs():
    """手势测试页可构造，含预览与信息行"""
    _app()
    from src.qt_settings_panel import TestPage
    page = TestPage({"settings": {}})
    assert page.preview is not None
    assert page.info is not None
    page._timer.stop()


def test_feedback_tip_offset_clamped():
    """反馈提示：偏移微调生效且夹紧在屏幕可用区内"""
    _app()
    from src.qt_feedback import QFeedbackTip
    tip = QFeedbackTip()
    screen = tip.screen().availableGeometry()
    tip.show_feedback("直线", "L", {
        "feedback_duration_ms": 500,
        "feedback_position": "bottom_center",
        "feedback_offset_x": -99999,
        "feedback_offset_y": 99999,
    })
    assert tip.x() >= screen.left()
    assert tip.y() <= screen.bottom() - tip.height()
    tip._hide_timer.stop()
    tip.hide()

def test_feedback_hide_tip():
    """hide_tip：立即隐藏提示并停掉隐藏计时器（防旧弹窗残留）"""
    _app()
    from src.qt_feedback import QFeedbackTip
    tip = QFeedbackTip()
    tip.show_feedback("直线", "L", {"feedback_duration_ms": 5000,
                                    "feedback_position": "bottom_center"})
    QApplication.processEvents()  # 延迟一帧显示，处理后再验证可见
    assert tip.isVisible()
    tip.hide_tip()
    assert not tip.isVisible()
    assert not tip._hide_timer.isActive()
