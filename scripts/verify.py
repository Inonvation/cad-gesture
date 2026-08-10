"""一键验证：语法检查 → 单元测试 → 启动/覆盖更新程序

用法：python scripts/verify.py 或双击 scripts/verify.bat（项目根目录外任意位置运行）
注意：不会杀进程——靠单实例机制让新实例覆盖旧实例，避免误杀 verify.py 自身。
"""
import glob
import os
import subprocess
import sys

_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
os.chdir(_PROJECT_ROOT)
sys.path.insert(0, _PROJECT_ROOT)  # 让 src.* 可导入（版本检查用）
PY = sys.executable


def _version_ok() -> bool:
    """version.txt 的 FileVersion 与 src/version.py 的 __version__ 必须一致"""
    try:
        import re
        text = open("version.txt", encoding="utf-8").read()
        m = re.search(r"StringStruct\('FileVersion', '([^']+)'\)", text)
        if not m:
            return False
        from src.version import __version__
        return m.group(1) == __version__
    except Exception:
        return False


def main():
    print("[1/4] 语法检查...")
    for f in sorted(glob.glob("src/*.py")) + ["main.py"]:
        py_compile_ok(f)
    print("       语法检查通过")

    print("[2/4] 版本号一致性检查...")
    if not _version_ok():
        sys.exit("版本号不一致：version.txt 与 src/version.py 不同步，"
                 "请用 scripts/set_version.py 更新")
    print("       版本号一致")

    print("[3/4] 单元测试...")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"])
    if r.returncode != 0:
        sys.exit("测试失败，请先修复")

    print("[4/4] 启动/覆盖更新程序...")
    # 直接启动新实例：单实例机制会自动请求旧实例退出并由新实例接管。
    # 重定向输出，避免子进程继承本脚本管道导致调用方等待
    # （不能用 taskkill，会误杀 verify.py 自身）
    subprocess.Popen([PY, "main.py"], cwd=os.getcwd(),
                     stdin=subprocess.DEVNULL,
                     stdout=subprocess.DEVNULL,
                     stderr=subprocess.DEVNULL)
    print("程序已启动（托盘查看效果）")


def py_compile_ok(path: str):
    import py_compile
    try:
        py_compile.compile(path, doraise=True)
    except py_compile.PyCompileError as e:
        sys.exit(f"语法错误 {path}: {e}")


if __name__ == "__main__":
    main()
