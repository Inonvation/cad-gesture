# -*- coding: utf-8 -*-
"""i18n 完整性测试：所有 T()/tr() 字符串字面量都必须在翻译表中"""
import ast
import glob
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src.i18n import _EN

_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))


def _collect_keys():
    keys = set()
    for path in glob.glob(os.path.join(_ROOT, "src", "*.py")):
        tree = ast.parse(open(path, encoding="utf-8").read())
        for node in ast.walk(tree):
            if (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Name)
                    and node.func.id in ("T", "tr")
                    and node.args
                    and isinstance(node.args[0], ast.Constant)
                    and isinstance(node.args[0].value, str)):
                keys.add(node.args[0].value)
    return keys


def test_all_translation_keys_present():
    """防回归：新增界面文案后漏补英文翻译，英文模式会显示中文"""
    missing = sorted(k for k in _collect_keys() if k not in _EN)
    assert missing == [], "缺失翻译键: %r" % missing