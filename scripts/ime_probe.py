"""SW 输入法助手诊断脚本 - 打印每步判定的原始数据

用法（控制台运行）：
    python scripts/ime_probe.py

然后把窗口切到 SolidWorks，鼠标点进绘图区，按两下字母键（如 S），
回到控制台看输出，把最后十几行发出来即可。
脚本每 1 秒刷新一次，Ctrl+C 结束。
"""
import os
import sys
import time

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from src import sw_ime_assist as ime

_pid_state = {}

def main():
    print("诊断开始（Ctrl+C 结束）。请切到 SolidWorks 并点击绘图区…")
    last = {}
    try:
        while True:
            row = {}
            try:
                hwnd = ime.get_foreground_hwnd()
                row["fg_hwnd"] = hex(hwnd) if hwnd else 0
                if hwnd:
                    pid = ime._window_pid(hwnd)
                    row["pid"] = pid
                    if pid and pid != os.getpid():
                        exe = ime._exe_of_pid(pid)
                        row["exe"] = os.path.basename(exe or "")
                        row["is_target"] = ime.is_target_exe(exe)
                    else:
                        row["exe"] = "-"
                        row["is_target"] = False
                    if pid and pid != os.getpid() and row.get("is_target"):
                        row["composing"] = ime._ime_composing(hwnd)
                        conv = ime._ime_conversion_mode(hwnd)
                        row["conv"] = ("中文" if (conv & 1) else "英文") \
                            if conv is not None else None
                        cls = ime._focus_control_class(hwnd)
                        row["focus_class"] = cls
                        row["want_cn(文本框?)"] = ime._is_edit_control_class(cls)
                        st = dict(ime._PID_STATE.get(pid) or {})
                        mode, _ = ime._plan_flip(st, conv,
                                                 ime._is_edit_control_class(cls))
                        row["plan_mode"] = ("切英文(0)" if mode == 0
                                            else ("切中文" if mode
                                            else "不动"))
            except Exception as e:
                row["error"] = repr(e)
            if row != last:
                print(row)
                last = row
            time.sleep(1.0)
    except KeyboardInterrupt:
        print("已结束")


if __name__ == "__main__":
    main()
