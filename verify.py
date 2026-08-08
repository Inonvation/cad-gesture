"""一键验证：语法检查 → 单元测试 → 启动/覆盖更新程序

用法：python verify.py 或双击 verify.bat
注意：不会杀进程——靠单实例机制让新实例覆盖旧实例，避免误杀 verify.py 自身。
"""
import glob
import os
import subprocess
import sys

os.chdir(os.path.dirname(os.path.abspath(__file__)))
PY = r"C:\Users\cy\AppData\Local\hermes\hermes-agent\venv\Scripts\python.exe"


def main():
    print("[1/3] 语法检查...")
    for f in sorted(glob.glob("src/*.py")) + ["main.py"]:
        py_compile_ok(f)
    print("       语法检查通过")

    print("[2/3] 单元测试...")
    r = subprocess.run([sys.executable, "-m", "pytest", "tests/", "-q"])
    if r.returncode != 0:
        sys.exit("测试失败，请先修复")

    print("[3/3] 启动/覆盖更新程序...")
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
