"""诊断拖放坐标偏移"""
import tkinter as tk
import math

root = tk.Tk()
root.title("坐标诊断")
root.geometry("600x500")

canvas = tk.Canvas(root, width=300, height=300, bg="#2a2a2a",
                   highlightthickness=0, borderwidth=0)
canvas.pack(pady=20, padx=20)

# 画一个参考圆
canvas.create_oval(50, 50, 250, 250, outline="#666", width=2)
canvas.create_line(150, 0, 150, 300, fill="#444")
canvas.create_line(0, 150, 300, 150, fill="#444")

info = tk.Label(root, text="在圆盘上移动鼠标看坐标", fg="white", bg="#1a1a1a",
                font=("Consolas", 10), justify=tk.LEFT, anchor=tk.W)
info.pack(fill=tk.X, padx=20)

offset_info = tk.Label(root, text="", fg="#ff6", bg="#1a1a1a",
                       font=("Consolas", 10), justify=tk.LEFT, anchor=tk.W)
offset_info.pack(fill=tk.X, padx=20, pady=5)

def on_motion(e):
    # 方法1: event.x 直接
    ex, ey = e.x, e.y
    # 方法2: canvasx/y
    cx, cy = canvas.canvasx(e.x), canvas.canvasy(e.y)
    # 方法3: x_root - winfo
    rx = e.x_root - canvas.winfo_rootx()
    ry = e.y_root - canvas.winfo_rooty()

    info.config(text=(
        f"event.x/y:      ({ex:4d}, {ey:4d})\n"
        f"canvasx/y:      ({cx:6.1f}, {cy:6.1f})\n"
        f"x_root-winfo:   ({rx:4d}, {ry:4d})\n"
        f"差异 (root法-event法): ({rx - ex}, {ry - ey})"
    ))

canvas.bind("<Motion>", on_motion)

# 测试拖放坐标
drag_label = None

def start_drag(e):
    global drag_label
    drag_label = tk.Label(root, text="[拖动代理]", fg="#fff", bg="#6366f1",
                          padx=8, pady=4)
    drag_label.place(x=e.x_root - root.winfo_rootx() + 10,
                     y=e.y_root - root.winfo_rooty() + 10)
    root.bind("<B1-Motion>", on_drag)
    root.bind("<ButtonRelease-1>", end_drag)

def on_drag(e):
    if drag_label:
        drag_label.place(x=e.x_root - root.winfo_rootx() + 10,
                         y=e.y_root - root.winfo_rooty() + 10)

    rx = e.x_root - canvas.winfo_rootx()
    ry = e.y_root - canvas.winfo_rooty()
    cx = canvas.canvasx(rx)
    cy = canvas.canvasy(ry)

    dist = math.sqrt((cx - 150)**2 + (cy - 150)**2)
    offset_info.config(text=(
        f"[拖动中] x_root-winfo=({rx}, {ry}) canvasxy=({cx:.0f}, {cy:.0f}) dist={dist:.0f}"
    ))

def end_drag(e):
    global drag_label
    root.unbind("<B1-Motion>")
    root.unbind("<ButtonRelease-1>")
    if drag_label:
        drag_label.destroy()
        drag_label = None
    offset_info.config(text="拖放结束")

canvas.bind("<Button-1>", start_drag)

root.mainloop()
