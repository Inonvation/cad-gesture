"""pytest 全局 fixture：隔离配置文件路径

配置已迁移到 %APPDATA%\\CADGesture，测试必须把 CONFIG_FILE 指向临时
目录，避免读写（或污染）用户真实配置。
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest


@pytest.fixture(autouse=True)
def isolate_config(monkeypatch, tmp_path):
    from src import config_manager
    # 用户数据目录与配置文件都指向临时目录，避免触碰真实 %APPDATA%；
    # 两者保持一致（get_config_path() 与模块级 CONFIG_FILE 同路径）
    monkeypatch.setattr(config_manager, "_user_config_dir",
                        lambda: str(tmp_path / "appdata"))
    monkeypatch.setattr(config_manager, "CONFIG_FILE",
                        str(tmp_path / "appdata" / "config.json"))
    # 测试环境禁用旧配置迁移（源路径指向不存在位置），
    # 避免把项目真实 config 带入临时目录；迁移逻辑本身由专门测试覆盖
    monkeypatch.setattr(config_manager, "_legacy_config_path",
                        lambda: str(tmp_path / "no-legacy" / "config.json"))
    yield
