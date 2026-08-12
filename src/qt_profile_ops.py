"""方案（Profile）数据操作 — 纯逻辑，无 Qt 依赖，可独立测试

qt_config_gui 只负责对话框交互与撤销/保存调度，数据变更全部走这里，
保证界面与配置状态一致。返回 (ok, message)：ok=True 成功；否则 message
为已本地化的错误文案（传入 tr 进行翻译，默认原样返回）。
"""

import copy
import json

from typing import Callable, Optional, Tuple

_identity: Callable[[str], str] = lambda s: s


def add_profile(config: dict, name: str, target: str,
                sector_count: int = 8, tr: Callable[[str], str] = None) -> Tuple[bool, Optional[str]]:
    """新增方案。sector_count 用于预填内层空扇区。"""
    tr = tr or _identity
    if not name:
        return False, tr("名称不能为空")
    if name in config.get("profiles", {}):
        return False, tr("方案「{name}」已存在").format(name=name)
    sectors = {str(i): {"label": "", "key": "", "description": "", "icon": ""}
               for i in range(sector_count)}
    config.setdefault("profiles", {})[name] = {
        "name": name, "target": target, "sectors": sectors,
        "outer_sectors": {}, "extension_sectors": {},
    }
    return True, None


def copy_profile(config: dict, src_name: str, new_name: str,
                 tr: Callable[[str], str] = None) -> Tuple[bool, Optional[str]]:
    """深拷贝方案到新名称。"""
    tr = tr or _identity
    if not new_name:
        return False, tr("名称不能为空")
    if new_name in config.get("profiles", {}):
        return False, tr("方案「{name}」已存在").format(name=new_name)
    src = config.get("profiles", {}).get(src_name)
    if src is None:
        return False, tr("方案「{name}」已存在").format(name=new_name)
    new = copy.deepcopy(src)
    new["name"] = new_name
    config["profiles"][new_name] = new
    return True, None


def rename_profile(config: dict, old_name: str, new_name: str,
                   tr: Callable[[str], str] = None) -> Tuple[bool, Optional[str]]:
    """重命名方案，并同步 settings 里的 active_profile / 绑定字段。"""
    tr = tr or _identity
    if not new_name or new_name == old_name:
        return False, tr("名称不能为空")
    if new_name in config.get("profiles", {}):
        return False, tr("方案「{name}」已存在").format(name=new_name)
    profile = config["profiles"].pop(old_name)
    profile["name"] = new_name
    config["profiles"][new_name] = profile
    s = config.setdefault("settings", {})
    if s.get("active_profile") == old_name:
        s["active_profile"] = new_name
    # 所有 {target}_profile 绑定键（含自定义应用）统一更新
    for key in [k for k in s if k.endswith("_profile")
                and k != "active_profile"]:
        if s.get(key) == old_name:
            s[key] = new_name
    return True, None


def delete_profile(config: dict, name: str,
                   tr: Callable[[str], str] = None) -> Tuple[bool, Optional[str]]:
    """删除方案：至少保留一个；被删方案的绑定字段重置为该 target 下首个方案。"""
    tr = tr or _identity
    profiles = config.get("profiles", {})
    if len(profiles) <= 1:
        return False, tr("至少保留一个配置方案")
    if name not in profiles:
        return False, tr("至少保留一个配置方案")
    del profiles[name]
    remaining = list(profiles.keys())
    s = config.setdefault("settings", {})
    # 所有 {target}_profile 绑定键（含自定义应用）统一重置为该 target 下首个方案
    for key in [k for k in list(s) if k.endswith("_profile")
                and k != "active_profile"]:
        if s.get(key) == name:
            tgt = key[: -len("_profile")]
            s[key] = next((n for n in remaining
                           if profiles[n].get("target") == tgt), "")
    s["active_profile"] = remaining[0]
    return True, None


def export_profile(profile: dict, path: str,
                   tr: Callable[[str], str] = None) -> Tuple[bool, Optional[str]]:
    """把方案写成 JSON 文件。"""
    tr = tr or _identity
    try:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(profile, f, ensure_ascii=False, indent=2)
        return True, None
    except Exception:
        return False, tr("导出失败")


def load_profile_data(path: str, tr: Callable[[str], str] = None) -> Tuple[bool, object]:
    """读取并校验方案 JSON；成功返回 (True, data)，失败返回 (False, 错误文案)。"""
    tr = tr or _identity
    try:
        with open(path, "r", encoding="utf-8") as f:
            data = json.load(f)
    except Exception as e:
        return False, tr("导入失败（无法读取文件）: {e}").format(e=e)
    if not isinstance(data, dict):
        return False, tr("导入失败：文件格式无效（应为对象）")
    for key in ("sectors", "outer_sectors", "extension_sectors"):
        if key in data:
            if not isinstance(data[key], dict):
                return False, tr("导入失败：{key} 格式无效").format(key=key)
            for v in data[key].values():
                if not isinstance(v, dict):
                    return False, tr("导入失败：{key} 中存在无效数据").format(key=key)
    return True, data


def apply_profile_data(profile: dict, data: dict) -> None:
    """把导入数据合并进现有方案（仅覆盖存在的圈层键）。"""
    for key in ("sectors", "outer_sectors", "extension_sectors"):
        if key in data:
            profile[key] = data[key]
