"""配置管理模块 - 处理配置文件的读写和Profile管理"""

import json
import os
import sys
import copy
from typing import Dict, Any, Optional, List

from src.config_presets import get_preset_commands, _default_config


def get_config_path() -> str:
    """获取配置文件路径"""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "config", "config.json")


CONFIG_FILE = get_config_path()


def load_config() -> Dict[str, Any]:
    """加载配置文件"""
    if not os.path.exists(CONFIG_FILE):
        config = _default_config()
        save_config(config)
        return config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        # 兼容旧配置：如果没有 outer_sectors 则补全
        if _migrate_config(config):
            save_config(config)  # 迁移后持久化，防止异常退出丢失
        return config
    except (json.JSONDecodeError, IOError) as e:
        print(f"配置文件加载失败: {e}")
        return _default_config()


def save_config(config: Dict[str, Any]) -> None:
    """保存配置文件"""
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    with open(CONFIG_FILE, "w", encoding="utf-8") as f:
        json.dump(config, f, ensure_ascii=False, indent=2)


def _migrate_config(config: Dict[str, Any]) -> bool:
    """兼容旧配置格式，返回是否进行了迁移"""
    migrated = False
    settings = config.get("settings", {})
    if "version" not in settings:
        settings["version"] = 1
        migrated = True
    if "outer_ring_radius" not in settings:
        settings["outer_ring_radius"] = 180
        migrated = True
    if "ext_ring_radius" not in settings:
        settings["ext_ring_radius"] = 240
        migrated = True
    if "auto_switch_profile" not in settings:
        settings["auto_switch_profile"] = True
        migrated = True
    if "open_config_on_start" not in settings:
        settings["open_config_on_start"] = False
        migrated = True
    if "menu_theme" not in settings:
        settings["menu_theme"] = "azure"
        migrated = True
    # 为旧配置中的 profile 添加 target、outer_sectors 和 extension_sectors
    for name, profile in config.get("profiles", {}).items():
        if "target" not in profile:
            if "zwcad" in name.lower() or "中望" in profile.get("name", ""):
                profile["target"] = "zwcad"
            else:
                profile["target"] = "autocad"
            migrated = True
        if "outer_sectors" not in profile:
            profile["outer_sectors"] = {}
            migrated = True
        if "extension_sectors" not in profile:
            profile["extension_sectors"] = {}
            migrated = True
    # 补全空的扩展圈命令：从默认配置按 target + name 匹配复制
    defaults = _default_config()
    for name, profile in config.get("profiles", {}).items():
        if profile.get("extension_sectors"):
            continue
        dname = profile.get("name", name)
        target = profile.get("target", "")
        for dp in defaults.get("profiles", {}).values():
            if (dp.get("target") == target
                    and dp.get("name", "") == dname
                    and dp.get("extension_sectors")):
                profile["extension_sectors"] = copy.deepcopy(dp["extension_sectors"])
                migrated = True
                break
    return migrated


def get_active_profile(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """获取当前活动的Profile"""
    profile_name = config.get("settings", {}).get("active_profile", "AutoCAD-常用")
    return config.get("profiles", {}).get(profile_name)


def get_profile_for_window(config: Dict[str, Any], window_type: str) -> Optional[Dict[str, Any]]:
    """根据窗口类型自动选择匹配的 Profile
    
    Args:
        config: 配置字典
        window_type: "autocad" 或 "zwcad"
    
    Returns:
        匹配的 Profile，如果没有匹配则返回当前 active_profile
    """
    if not config.get("settings", {}).get("auto_switch_profile", True):
        return get_active_profile(config)
    
    # 获取当前 active_profile 的 target
    active_name = config.get("settings", {}).get("active_profile", "")
    active_profile = config.get("profiles", {}).get(active_name)
    
    # 如果当前 profile 已经匹配，直接返回
    if active_profile and active_profile.get("target", "") == window_type:
        return active_profile
    
    # 否则查找匹配的 profile
    for name, profile in config.get("profiles", {}).items():
        if profile.get("target", "") == window_type:
            return profile
    
    # 没有匹配的，返回当前 active
    return active_profile


def get_profile_names(config: Dict[str, Any]) -> List[str]:
    """获取所有Profile名称列表"""
    return list(config.get("profiles", {}).keys())


def get_profile_names_by_target(config: Dict[str, Any], target: str) -> List[str]:
    """按 target 获取 Profile 名称列表"""
    return [
        name for name, profile in config.get("profiles", {}).items()
        if profile.get("target", "") == target
    ]


def set_active_profile(config: Dict[str, Any], profile_name: str) -> bool:
    """设置活动Profile"""
    if profile_name not in config.get("profiles", {}):
        return False
    config.setdefault("settings", {})["active_profile"] = profile_name
    save_config(config)
    return True
