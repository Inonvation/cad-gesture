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
    assert old["settings"]["outer_ring_radius"] == 135
    assert old["settings"]["ext_ring_radius"] == 185
    assert old["settings"]["menu_scale"] == 100
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
    assert "序号与明细表" in zwcad
    assert "尺寸标注" in zwcad
    assert "图纸与图框" in zwcad
    assert "超级符号库" in zwcad
    assert zwcad["绘图工具"]["智能画线"]["description"] == "ZWMINTELLIGENTLINE"
    assert zwcad["符号标注"]["锥斜度"]["description"] == "ZWMTAPERSYM"
    assert zwcad["符号标注"]["圆孔标记"]["description"] == "ZWMCIRCLEMARK"
    print(f"[OK]  ZWCAD预设命令: {len(zwcad)}个分类")


def test_default_config():
    """测试默认配置"""
    config = _default_config()
    assert "settings" in config
    assert config["settings"]["version"] == 1
    assert config["settings"]["menu_theme"] == "graphite"
    assert config["settings"]["ui_mode"] == "light"
    assert config["settings"]["check_update_on_start"] is False
    assert "AutoCAD-常用" in config["profiles"]
    assert "ZWCAD-机械" in config["profiles"]
    print(f"[OK]  默认配置: {len(config['profiles'])}个Profile")


def test_migrate_missing_layers():
    """旧配置缺外层/扩展圈时自动补全（含 target 推断）"""
    old = {
        "settings": {"active_profile": "AutoCAD-常用"},
        "profiles": {
            "AutoCAD-常用": {
                "name": "常用",
                "sectors": {"0": {"label": "直线", "key": "l", "description": "LINE"}},
            },
            "ZWCAD-常用": {
                "name": "常用",
                "sectors": {"0": {"label": "直线", "key": "l", "description": "LINE"}},
            },
        }
    }
    migrated = _migrate_config(old)
    assert migrated
    ac = old["profiles"]["AutoCAD-常用"]
    zw = old["profiles"]["ZWCAD-常用"]
    # target 推断：AutoCAD-常用 -> autocad，ZWCAD-常用 -> zwcad
    assert ac["target"] == "autocad"
    assert zw["target"] == "zwcad"
    # 外层/扩展圈补全
    assert "outer_sectors" in ac
    assert "extension_sectors" in ac
    assert isinstance(ac["outer_sectors"], dict)
    assert "extension_sectors" in zw


def test_migrate_no_rewrite_empty_extension():
    """用户主动清空的 extension_sectors 不应被默认值覆盖"""
    old = {
        "settings": {"version": 1},
        "profiles": {
            "AutoCAD-常用": {
                "name": "常用", "target": "autocad",
                "sectors": {}, "outer_sectors": {},
                "extension_sectors": {},  # 用户主动清空
            }
        }
    }
    migrated = _migrate_config(old)
    # 用户主动清空不覆盖；无缺失字段则无需迁移
    assert migrated is False or old["profiles"]["AutoCAD-常用"]["extension_sectors"] == {}


def test_migrate_missing_settings_key_regression():
    """顶层缺失 settings 键时，迁移补全的 settings 必须写回 config

    （回归 B2）：原来用 config.get("settings", {}) 拿到临时空 dict，
    迁移写入全部丢失，配置永远修不好。setdefault 修复后应保留补全。
    """
    old = {
        "profiles": {
            "AutoCAD-常用": {
                "name": "常用",
                "sectors": {"0": {"label": "直线", "key": "l", "description": "LINE"}},
            }
        }
    }
    migrated = _migrate_config(old)
    assert migrated
    # settings 键必须存在且补全了 version / radius 等默认字段
    assert isinstance(old.get("settings"), dict)
    assert old["settings"]["version"] == 1
    assert old["settings"]["outer_ring_radius"] == 135
    assert "auto_switch_profile" in old["settings"]
    # 再次调用应为幂等（不再产生新的迁移）
    assert _migrate_config(old) is False


def test_migrate_legacy_config(monkeypatch, tmp_path):
    """旧位置（exe/脚本旁 config/config.json）迁移到用户目录"""
    import json
    from src import config_manager as cm
    legacy = tmp_path / "legacy" / "config.json"
    legacy.parent.mkdir(parents=True)
    legacy.write_text(
        json.dumps({"settings": {"version": 1}, "profiles": {}},
                   ensure_ascii=False), encoding="utf-8")
    monkeypatch.setattr(cm, "_legacy_config_path", lambda: str(legacy))
    monkeypatch.setattr(cm, "CONFIG_FILE", str(tmp_path / "user" / "config.json"))
    assert cm.migrate_legacy_config()
    assert os.path.exists(cm.CONFIG_FILE)
    # 用户目录已有配置时不覆盖
    assert not cm.migrate_legacy_config()


def test_migrate_legacy_config_missing_source(monkeypatch, tmp_path):
    """旧位置没有配置时迁移失败但不报错"""
    from src import config_manager as cm
    monkeypatch.setattr(cm, "_legacy_config_path",
                        lambda: str(tmp_path / "nope" / "config.json"))
    monkeypatch.setattr(cm, "CONFIG_FILE", str(tmp_path / "user" / "config.json"))
    assert not cm.migrate_legacy_config()


def test_set_and_reset_config_dir(monkeypatch, tmp_path):
    """自定义配置目录：迁移现有配置 + 元文件记录 + 恢复默认"""
    from src import config_manager as cm
    old = cm.CONFIG_FILE
    try:
        # 先造一份现有配置
        cm.save_config(_default_config())
        assert os.path.exists(cm.CONFIG_FILE)

        new_path = cm.set_config_dir(str(tmp_path / "custom"))
        assert new_path == str(tmp_path / "custom" / "config.json")
        assert cm.CONFIG_FILE == new_path
        assert cm.get_config_path() == new_path
        # 配置已迁移到新位置
        assert os.path.exists(new_path)
        # 元文件记录自定义目录
        meta = os.path.join(cm._user_config_dir(), cm._META_FILE)
        assert os.path.exists(meta)
        assert open(meta, encoding="utf-8").read().strip() == str(tmp_path / "custom")

        # 恢复默认：配置回到用户目录
        default_path = cm.reset_config_dir()
        assert default_path == os.path.join(cm._user_config_dir(), "config.json")
        assert cm.get_config_path() == default_path
        assert not os.path.exists(meta)
    finally:
        monkeypatch.setattr(cm, "CONFIG_FILE", old)


if __name__ == "__main__":
    test_load_config()
    test_get_active_profile()
    test_get_profile_names()
    test_get_profile_for_window()
    test_migrate_config()
    test_preset_commands()
    test_default_config()
    print("\nAll tests passed!")


def test_get_sector_command_no_inner_fallback():
    """外层/扩展圈空扇区返回空，不回退内层同方向命令"""
    from src.config_manager import get_sector_command
    profile = {
        "sectors": {"0": {"label": "直线", "key": "l", "description": "LINE"}},
        "outer_sectors": {},
        "extension_sectors": {"0": {"label": "构造线", "key": "xl"}},
    }
    assert get_sector_command(profile, "inner", 0)["key"] == "l"
    assert get_sector_command(profile, "outer", 0) == {}      # 外层空 -> 不触发
    assert get_sector_command(profile, "extension", 0)["key"] == "xl"
    assert get_sector_command(profile, "extension", 1) == {}  # 扩展圈空 -> 不触发


def test_full_config_backup_restore(tmp_path):
    """整包配置备份/恢复往返"""
    from src.config_manager import (load_config, save_config,
                                    export_full_config, import_full_config)
    cfg = load_config()
    cfg["settings"]["trigger_button"] = "middle"
    save_config(cfg)
    path = str(tmp_path / "backup.json")
    ok, err = export_full_config(path)
    assert ok and err is None
    ok, data = import_full_config(path)
    assert ok
    assert data["settings"]["trigger_button"] == "middle"
    assert "profiles" in data


def test_full_config_rejects_invalid(tmp_path):
    """备份文件结构无效时拒绝恢复"""
    from src.config_manager import import_full_config
    bad = tmp_path / "bad.json"
    bad.write_text('{"foo": 1}', encoding="utf-8")
    ok, msg = import_full_config(str(bad))
    assert not ok and msg


def test_migrate_adds_new_settings():
    """新设置项（触发键/轨迹线/反馈）迁移补全"""
    from src.config_manager import _migrate_config
    cfg = {"settings": {}, "profiles": {}}
    assert _migrate_config(cfg)
    s = cfg["settings"]
    assert s["trigger_button"] == "right"
    assert s["gesture_trail"] is True
    assert s["command_feedback"] is True
    assert s["feedback_position"] == "bottom_center"
    assert s["feedback_show_name"] is True
    assert s["feedback_show_key"] is True
    assert s["feedback_duration_ms"] == 1500
    assert s["feedback_offset_x"] == 0
    assert s["feedback_offset_y"] == 0


def test_default_config_icons():
    """默认方案常用扇区带预设矢量图标，隐藏文字开关默认关"""
    config = _default_config()
    prof = next(p for p in config["profiles"].values()
                if p.get("target") == "autocad" and p.get("name") == "常用")
    assert prof["sectors"]["0"].get("icon") == "preset:line"
    assert prof["sectors"]["2"].get("icon") == "preset:copy"
    assert config["settings"]["menu_icon_hide_label"] is False
    assert config["settings"]["menu_icon_scale"] == 100


def test_preset_commands_carry_icon():
    """命令库高频命令带 icon，拖放/应用命令时随数据复制到扇区"""
    ac = get_preset_commands("autocad")
    found = False
    for cat in ac.values():
        for entry in cat.values():
            if entry.get("description") == "LINE":
                assert entry.get("icon") == "preset:line"
                found = True
    assert found


def test_migrate_adds_icon_hide_setting():
    """旧配置迁移补 menu_icon_hide_label 默认值"""
    cfg = {"settings": {}, "profiles": {}}
    assert _migrate_config(cfg)
    assert cfg["settings"]["menu_icon_hide_label"] is False
    assert cfg["settings"]["menu_icon_scale"] == 100


def test_migrate_adds_all_default_settings_keys():
    """迁移必须补齐 _default_config 的全部 settings 键（防联动清单漏项）"""
    old = {"settings": {"version": 1}, "profiles": {}}
    _migrate_config(old)
    defaults = _default_config().get("settings", {})
    missing = [k for k in defaults if k not in old["settings"]]
    assert not missing, f"迁移后仍缺失 settings 键: {missing}"
    # 本次修复重点核对：这 6 个键必须补齐且值与默认一致
    for key in ("active_profile", "dead_zone_radius", "ring_radius",
                "hold_threshold_ms", "sector_count", "gesture_paused"):
        assert old["settings"][key] == defaults[key]
