"""配置管理模块测试"""

import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.config_manager import (
    load_config, save_config, get_active_profile, get_profile_names,
    get_profile_for_window, set_active_profile, _migrate_config
)
from src.config_presets import get_preset_commands, _default_config


def test_load_config():
    """测试配置加载"""
    config = load_config()
    assert "settings" in config
    assert "profiles" in config
    assert "version" in config.get("settings", {})
    print("[OK]  配置加载成功")


def test_get_active_profile():
    """测试获取活动Profile"""
    config = load_config()
    profile = get_active_profile(config)
    assert profile is not None
    assert "name" in profile
    assert "sectors" in profile
    print(f"[OK]  当前Profile: {profile['name']}")


def test_get_profile_names():
    """测试获取Profile列表"""
    config = load_config()
    names = get_profile_names(config)
    assert len(names) > 0
    print(f"[OK]  可用Profile: {len(names)}个")


def test_get_profile_for_window():
    """测试窗口类型自动匹配"""
    config = load_config()
    profile = get_profile_for_window(config, "autocad")
    assert profile is not None
    assert profile.get("target") == "autocad"
    print(f"[OK]  AutoCAD Profile: {profile['name']}")

    profile = get_profile_for_window(config, "zwcad")
    assert profile is not None
    assert profile.get("target") == "zwcad"
    print(f"[OK]  ZWCAD Profile: {profile['name']}")


def test_migrate_config():
    """测试配置迁移"""
    old = {
        "settings": {
            "hold_threshold_ms": 200,
            "dead_zone_radius": 30,
            "ring_radius": 100,
            "active_profile": "AutoCAD-常用",
        },
        "profiles": {
            "AutoCAD-常用": {
                "name": "常用",
                "sectors": {"0": {"label": "直线", "key": "l", "description": "LINE"}},
            }
        }
    }
    migrated = _migrate_config(old)
    assert migrated
    assert old["settings"]["version"] == 1
    assert old["settings"]["outer_ring_radius"] == 180
    assert old["settings"]["ext_ring_radius"] == 240
    assert old["settings"]["auto_switch_profile"] == True
    assert old["profiles"]["AutoCAD-常用"]["target"] == "autocad"
    assert "outer_sectors" in old["profiles"]["AutoCAD-常用"]
    print("[OK]  配置迁移通过")


def test_preset_commands():
    """测试预设命令库完整性"""
    autocad = get_preset_commands("autocad")
    assert "绘图" in autocad
    assert "编辑修改" in autocad
    assert "标注" in autocad
    assert len(autocad["绘图"]) > 0
    assert autocad["绘图"]["直线"]["key"] == "l"
    print(f"[OK]  AutoCAD预设命令: {len(autocad)}个分类")

    zwcad = get_preset_commands("zwcad")
    assert "符号标注" in zwcad
    assert "序号明细" in zwcad
    print(f"[OK]  ZWCAD预设命令: {len(zwcad)}个分类")


def test_default_config():
    """测试默认配置"""
    config = _default_config()
    assert "settings" in config
    assert config["settings"]["version"] == 1
    assert "AutoCAD-常用" in config["profiles"]
    assert "ZWCAD-机械" in config["profiles"]
    print(f"[OK]  默认配置: {len(config['profiles'])}个Profile")


if __name__ == "__main__":
    test_load_config()
    test_get_active_profile()
    test_get_profile_names()
    test_get_profile_for_window()
    test_migrate_config()
    test_preset_commands()
    test_default_config()
    print("\nAll tests passed!")