"""圆盘几何 — 半径与缩放参数的唯一来源

运行时圆盘（qt_radial_menu）、手势引擎（gesture_engine）、配置编辑页预览
（qt_preview）、尺寸页预览（qt_settings_panel）都从这里取半径，保证显示、
命中测试与触发判定使用同一套数值；新增/修改尺寸设置只改这里与
config_presets._default_config / config_manager._migrate_config。
"""

DEFAULT_RADII = {
    "dead_zone_radius": 24,
    "ring_radius": 70,
    "outer_ring_radius": 135,
    "ext_ring_radius": 185,
}
_RADIUS_KEYS = ("dead_zone_radius", "ring_radius",
                "outer_ring_radius", "ext_ring_radius")


def menu_scale(settings: dict) -> float:
    """整体圆盘缩放比例（50% ~ 150%，默认 100%）"""
    return int(settings.get("menu_scale", 100)) / 100.0


def scaled_radius(settings: dict, key: str) -> int:
    """某半径的实际生效值 = 配置值 × menu_scale（向下取整）"""
    return int(int(settings.get(key, DEFAULT_RADII[key])) * menu_scale(settings))


def scaled_radii(settings: dict) -> dict:
    """一次取回四个半径（键同 DEFAULT_RADII）"""
    return {k: scaled_radius(settings, k) for k in _RADIUS_KEYS}
