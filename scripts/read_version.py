"""从 version.txt 提取 FileVersion 版本号，供构建脚本使用

用法: python scripts/read_version.py   （输出如 0.0.2）
"""

import ast
import os
import sys


def read_version() -> str:
    path = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))),
                        "version.txt")
    with open(path, "r", encoding="utf-8") as f:
        source = f.read()
    tree = ast.parse(source)
    for node in ast.walk(tree):
        if isinstance(node, ast.Call) and getattr(node.func, "id", "") == "StringStruct":
            args = [a.value for a in node.args if isinstance(a, ast.Constant)]
            if len(args) >= 2 and args[0] == "FileVersion":
                return str(args[1])
    raise SystemExit("version.txt 中未找到 FileVersion")


if __name__ == "__main__":
    print(read_version())
