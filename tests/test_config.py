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