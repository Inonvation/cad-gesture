"""配置管理模块 - 处理配置文件的读写和Profile管理"""

import json
import os
import sys
import copy
import winreg
from typing import Dict, Any, Optional, List

from src.logger import get_logger

from src.config_presets import _default_config


def _user_config_dir() -> str:
    """用户数据目录（Windows 标准：%APPDATA%\\CADGesture）

    与 exe 位置无关：exe 在受保护目录（如 Program Files）或随版本
    覆盖更新时，配置始终保留且用户可读可改。
    """
    base = os.environ.get("APPDATA") or os.path.expanduser("~")
    return os.path.join(base, "CADGesture")


_META_FILE = "config_path.txt"   # 自定义配置目录标记文件（位于用户数据目录）


def _custom_config_dir() -> Optional[str]:
    """自定义配置目录（由用户在设置页指定）；未设置返回 None"""
    meta = os.path.join(_user_config_dir(), _META_FILE)
    try:
        with open(meta, "r", encoding="utf-8") as f:
            path = f.read().strip()
        if path and os.path.isdir(path):
            return path
    except OSError:
        pass
    return None


def _legacy_config_path() -> str:
    """旧版本配置路径（exe/脚本旁的 config/config.json，仅用于一次性迁移）"""
    if getattr(sys, 'frozen', False):
        base_dir = os.path.dirname(sys.executable)
    else:
        base_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    return os.path.join(base_dir, "config", "config.json")


def get_config_path() -> str:
    """获取当前配置文件路径（默认 %APPDATA%\\CADGesture，可自定义目录）"""
    return os.path.join(_custom_config_dir() or _user_config_dir(), "config.json")


CONFIG_FILE = get_config_path()


def set_config_dir(path: str) -> str:
    """设置自定义配置目录并迁移现有配置；返回新的配置文件路径"""
    path = os.path.abspath(path)
    new = os.path.join(path, "config.json")
    old = get_config_path()
    os.makedirs(path, exist_ok=True)
    if os.path.abspath(old) != new and os.path.exists(old) and not os.path.exists(new):
        import shutil
        shutil.copy2(old, new)
    meta = os.path.join(_user_config_dir(), _META_FILE)
    os.makedirs(os.path.dirname(meta), exist_ok=True)
    with open(meta, "w", encoding="utf-8") as f:
        f.write(path)
    global CONFIG_FILE
    CONFIG_FILE = new
    return new


def reset_config_dir() -> str:
    """恢复默认配置目录（%APPDATA%\\CADGesture），现有配置迁移回去"""
    new = os.path.join(_user_config_dir(), "config.json")
    old = get_config_path()
    if os.path.abspath(old) != new and os.path.exists(old) and not os.path.exists(new):
        import shutil
        shutil.copy2(old, new)
    meta = os.path.join(_user_config_dir(), _META_FILE)
    try:
        os.remove(meta)
    except OSError:
        pass
    global CONFIG_FILE
    CONFIG_FILE = new
    return new


def migrate_legacy_config() -> bool:
    """把旧版本（exe 旁 config/config.json）迁移到用户目录；成功返回 True"""
    legacy = _legacy_config_path()
    if not os.path.exists(legacy) or os.path.exists(CONFIG_FILE):
        return False
    try:
        os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
        import shutil
        shutil.copy2(legacy, CONFIG_FILE)
        return True
    except Exception:
        return False


def load_config() -> Dict[str, Any]:
    """加载配置文件（首次从旧位置迁移，缺失时生成默认配置）"""
    if not os.path.exists(CONFIG_FILE):
        migrate_legacy_config()  # 0.0.2 及更早版本：exe 旁 config/config.json
    if not os.path.exists(CONFIG_FILE):
        config = _default_config()
        save_config(config)
        return config
    try:
        with open(CONFIG_FILE, "r", encoding="utf-8") as f:
            config = json.load(f)
        if not isinstance(config, dict):
            raise ValueError("配置文件结构异常: 顶层应为对象")
        # 兼容旧配置：如果没有 outer_sectors 则补全
        if _migrate_config(config):
            save_config(config)  # 迁移后持久化，防止异常退出丢失
        return config
    except Exception as e:
        # 兜底任何结构异常（profiles 为 list、settings 缺失等），
        # 避免异常穿透导致整个程序启动崩溃
        get_logger().error("配置文件加载失败: %s", e)
        return _default_config()


def save_config(config: Dict[str, Any]) -> bool:
    """保存配置文件（原子写入 + 自动备份）

    先写临时文件再 os.replace 原子替换，避免写入中途崩溃/断电
    导致 config.json 被截断损坏；保存前备份旧配置到 config.json.bak，
    供误操作/损坏时恢复。

    Returns:
        True 表示写入成功；False 表示失败（调用方据此提示）。
    """
    os.makedirs(os.path.dirname(CONFIG_FILE), exist_ok=True)
    tmp_path = CONFIG_FILE + ".tmp"
    try:
        # 备份旧配置（保留最近一份旧版本，用于误操作恢复）
        if os.path.exists(CONFIG_FILE):
            try:
                import shutil
                shutil.copy2(CONFIG_FILE, CONFIG_FILE + ".bak")
            except Exception:
                pass
        with open(tmp_path, "w", encoding="utf-8") as f:
            json.dump(config, f, ensure_ascii=False, indent=2)
        os.replace(tmp_path, CONFIG_FILE)
        return True
    except Exception:
        # 清理残留的临时文件，避免下次启动时误读
        try:
            if os.path.exists(tmp_path):
                os.remove(tmp_path)
        except Exception:
            pass
        return False


def _migrate_config(config: Dict[str, Any]) -> bool:
    """兼容旧配置格式，返回是否进行了迁移"""
    migrated = False
    settings = config.get("settings", {})
    if "version" not in settings:
        settings["version"] = 1
        migrated = True
    if "outer_ring_radius" not in settings:
        settings["outer_ring_radius"] = 135
        migrated = True
    if "ext_ring_radius" not in settings:
        settings["ext_ring_radius"] = 185
        migrated = True
    if "auto_switch_profile" not in settings:
        settings["auto_switch_profile"] = True
        migrated = True
    if "autocad_profile" not in settings:
        settings["autocad_profile"] = ""
        migrated = True
    if "zwcad_profile" not in settings:
        settings["zwcad_profile"] = ""
        migrated = True
    if "open_config_on_start" not in settings:
        settings["open_config_on_start"] = False
        migrated = True
    if "menu_theme" not in settings:
        settings["menu_theme"] = "azure"
        migrated = True
    if "trigger_distance" not in settings:
        settings["trigger_distance"] = 15
        migrated = True
    if "auto_start" not in settings:
        settings["auto_start"] = False
        migrated = True
    if "menu_opacity" not in settings:
        settings["menu_opacity"] = 0.95
        migrated = True
    if "menu_scale" not in settings:
        settings["menu_scale"] = 100
        migrated = True
    if "check_update_on_start" not in settings:
        settings["check_update_on_start"] = True
        migrated = True
    if "update_source_url" not in settings:
        settings["update_source_url"] = "https://api.github.com/repos/Inonvation/cad-gesture/releases/latest"
        migrated = True
    if "last_update_check" not in settings:
        settings["last_update_check"] = ""
        migrated = True
    if "language" not in settings:
        settings["language"] = "zh"
        migrated = True
    if "ui_mode" not in settings:
        settings["ui_mode"] = "dark"
        migrated = True
    # 为旧配置中的 profile 添加 target、outer_sectors 和 extension_sectors
    # 记录哪些 profile 原本缺少 extension_sectors 字段（区分"旧配置缺失"与"用户主动清空"）
    missing_ext = set()
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
            missing_ext.add(name)
            migrated = True
    # 仅为"旧配置原本缺失扩展圈字段"的 profile 从默认配置补命令。
    # 用户主动清空的空 dict 不会被覆盖（silent data loss 防护）。
    defaults = _default_config()
    for name in missing_ext:
        profile = config["profiles"][name]
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


def get_sector_command(profile: dict, ring_type: str, sector: int) -> dict:
    """取某扇区（圈层 + 编号）的命令配置；空扇区返回 {}（不触发命令）。

    不再回退到内层同方向扇区：外层/扩展圈未设置的扇区应保持为空，
    避免用户划到空白扇区误触发一个"看起来没设置"的内层命令。
    """
    key_map = {"extension": "extension_sectors", "outer": "outer_sectors",
               "inner": "sectors"}
    return profile.get(key_map.get(ring_type, "sectors"), {}).get(str(sector), {})


def get_active_profile(config: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """获取当前活动的Profile"""
    profile_name = config.get("settings", {}).get("active_profile", "AutoCAD-常用")
    return config.get("profiles", {}).get(profile_name)


def get_profile_for_window(config: Dict[str, Any], window_type: str) -> Optional[Dict[str, Any]]:
    """根据窗口类型选择匹配的 Profile（显式绑定优先）

    Args:
        config: 配置字典
        window_type: "autocad" 或 "zwcad"

    Returns:
        匹配的 Profile，如果没有匹配则返回当前 active_profile

    选择优先级（auto_switch_profile=True 时）：
        1. settings 中显式绑定的方案（autocad_profile / zwcad_profile）
        2. 该 target 下第一个方案（旧版本行为，向后兼容）
    """
    if not config.get("settings", {}).get("auto_switch_profile", True):
        return get_active_profile(config)

    settings = config.get("settings", {})
    # 1. 显式绑定优先
    bound_name = settings.get(f"{window_type}_profile", "")
    if bound_name:
        bound = config.get("profiles", {}).get(bound_name)
        if bound and bound.get("target", "") == window_type:
            return bound

    # 2. 该 target 下第一个方案（向后兼容旧行为）
    for name, profile in config.get("profiles", {}).items():
        if profile.get("target", "") == window_type:
            # 绑定字段为空时自动补全并落盘，避免内存态与磁盘态不一致
            if not settings.get(f"{window_type}_profile"):
                settings[f"{window_type}_profile"] = name
                save_config(config)
            return profile

    # 3. 无匹配，返回当前 active
    return get_active_profile(config)


def set_profile_for_target(config: Dict[str, Any], target: str,
                           profile_name: str) -> bool:
    """把某 CAD 类型显式绑定到指定方案（target: autocad / zwcad）"""
    profile = config.get("profiles", {}).get(profile_name)
    if not profile:
        return False
    if profile.get("target", "") != target:
        return False
    config.setdefault("settings", {})[f"{target}_profile"] = profile_name
    return True


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


# ========== 开机自启（注册表 HKCU\...\Run） ==========

_RUN_KEY = r"Software\Microsoft\Windows\CurrentVersion\Run"
_RUN_VALUE = "CADGesture"


def get_auto_start() -> bool:
    """查询是否已注册开机自启（以注册表为准）"""
    try:
        with winreg.OpenKey(winreg.HKEY_CURRENT_USER, _RUN_KEY) as key:
            winreg.QueryValueEx(key, _RUN_VALUE)
            return True
    except OSError:
        return False


def set_auto_start(enabled: bool) -> bool:
    """设置/取消开机自启

    源码运行注册 python.exe + main.py；打包 exe 注册可执行文件本身。

    Returns:
        True 表示注册表写入成功；False 表示失败。
    """
    try:
        with winreg.CreateKeyEx(winreg.HKEY_CURRENT_USER, _RUN_KEY, 0,
                                winreg.KEY_SET_VALUE) as key:
            if enabled:
                if getattr(sys, "frozen", False):
                    cmd = f'"{sys.executable}"'
                else:
                    main_py = os.path.abspath(os.path.join(
                        os.path.dirname(os.path.abspath(__file__)), "..", "main.py"))
                    cmd = f'"{sys.executable}" "{main_py}"'
                winreg.SetValueEx(key, _RUN_VALUE, 0, winreg.REG_SZ, cmd)
            else:
                try:
                    winreg.DeleteValue(key, _RUN_VALUE)
                except OSError:
                    pass
        return True
    except Exception:
        return False
