# -*- coding: utf-8 -*-
"""一键同步版本号：version.txt（4 处）+ src/version.py（1 处）

用法:
    python scripts/set_version.py 0.0.4

发版时先跑本脚本再打包，避免 5 处手改漏同步。
按字节替换保留原文件行尾（不触发 git 行尾差异）。
"""

import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent


def _sub_bytes(path: Path, pairs) -> None:
    data = path.read_bytes()
    for pattern, repl in pairs:
        data = pattern.sub(repl, data)
    path.write_bytes(data)


def main() -> int:
    if len(sys.argv) != 2:
        print("用法: python scripts/set_version.py 0.0.4")
        return 1
    ver = sys.argv[1]
    if not re.fullmatch(r"\d+\.\d+\.\d+", ver):
        print("版本号格式应为 x.y.z，例如 0.0.4")
        return 1
    a, b, c = ver.split(".")
    ver4 = f"({a}, {b}, {c}, 0)".encode("utf-8")

    _sub_bytes(ROOT / "version.txt", [
        (re.compile(rb"filevers=\(\d+, \d+, \d+, \d+\)"),
         b"filevers=" + ver4),
        (re.compile(rb"prodvers=\(\d+, \d+, \d+, \d+\)"),
         b"prodvers=" + ver4),
        (re.compile(rb"StringStruct\('FileVersion', '[^']*'\)"),
         f"StringStruct('FileVersion', '{ver}')".encode("utf-8")),
        (re.compile(rb"StringStruct\('ProductVersion', '[^']*'\)"),
         f"StringStruct('ProductVersion', '{ver}')".encode("utf-8")),
    ])
    _sub_bytes(ROOT / "src" / "version.py", [
        (re.compile(rb'__version__ = "[^"]*"'),
         f'__version__ = "{ver}"'.encode("utf-8")),
    ])
    print(f"已同步版本号 -> {ver}（version.txt x4 + src/version.py）")
    return 0


if __name__ == "__main__":
    sys.exit(main())