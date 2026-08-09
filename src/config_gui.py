"""GUI配置界面 — CustomTkinter 现代深色版"""

import math
import time
import copy
import json
import ctypes
import tkinter as tk
from tkinter import filedialog
from typing import Dict, Optional, Callable, Tuple

import customtkinter as ctk

from src.config_manager import (
    load_config, save_config, get_profile_names, _default_config,
    get_preset_commands
)
from src.gesture_engine import calc_sector
from src.theme import get_menu_theme, MENU_THEMES
from src.renderer import draw_ring, ring_state_preview

ctk.set_appearance_mode("dark")
ctk.set_default_color_theme("blue")

# ========== 配色（深色分层 + 天蓝霓虹） ==========
BG = "#0d1017"
CARD = "#161b23"
PANEL = "#12161d"
SIDEBAR = "#0f1319"
BORDER = "#232a34"
BORDER_LIGHT = "#2c3542"
TEXT = "#e6e9ef"
TEXT_SECONDARY = "#a8b2bf"
TEXT_DIM = "#7b8494"
ACCENT = "#38bdf8"
ACCENT_HOVER = "#0ea5e9"
ACCENT_DIM = "#0369a1"
PRESET_BG = "#1b212b"
PRESET_HOVER = "#252d39"
DRAG_PROXY_BG = "#38bdf8"
WARN = "#f0b429"
DANGER = "#f87171"

_FONT = ("Microsoft YaHei", 12)
_FONT_SMALL = ("Microsoft YaHei", 11)
_FONT_TITLE = ("Microsoft YaHei", 16, "bold")


def _enable_dark_titlebar(win: "ctk.CTk"):
    """让系统标题栏跟随深色主题（Windows 10 1809+）"""
    try:
        hwnd = win.winfo_id()
        while True:
            parent = ctypes.windll.user32.GetParent(hwnd)
            if parent == 0:
                break
            hwnd = parent
        DWMWA_USE_IMMERSIVE_DARK_MODE = 20
        val = ctypes.c_int(1)
        ctypes.windll.dwmapi.DwmSetWindowAttribute(
            ctypes.c_void_p(hwnd), DWMWA_USE_IMMERSIVE_DARK_MODE,
            ctypes.byref(val), ctypes.sizeof(val))
    except Exception:
        pass


def _layer_to_sectors_key(layer: str) -> str:
    if layer == "outer":
        return "outer_sectors"
    elif layer == "extension":
        return "extension_sectors"
    return "sectors"


def _layer_display_name(layer: str) -> str:
    if layer == "outer":
        return "外层"
    elif layer == "extension":
        return "扩展圈"
    return "内层"


class _ToolTip:
    """轻量 hover 提示框"""

    def __init__(self, widget, text, delay=450):
        self.widget = widget
        self.text = text
        self._delay = delay
        self._after = None
        self._tip = None
        widget.bind("<Enter>", self._on_enter, add="+")
        widget.bind("<Leave>", self._on_leave, add="+")
        widget.bind("<Button-1>", self._on_leave, add="+")

    def _on_enter(self, e):
        self._cancel()
        self._after = self.widget.after(self._delay, self._show)

    def _on_leave(self, e):
        self._cancel()
        self._hide()

    def _cancel(self):
        if self._after is not None:
            self.widget.after_cancel(self._after)
            self._after = None

    def _hide(self):
        if self._tip is not None:
            self._tip.destroy()
            self._tip = None

    def _show(self):
        self._after = None
        if self._tip is not None or not self.widget.winfo_exists():
            return
        x = self.widget.winfo_rootx()
        y = self.widget.winfo_rooty() + self.widget.winfo_height() + 6
        self._tip = tk.Toplevel(self.widget)
        self._tip.overrideredirect(True)
        self._tip.attributes("-topmost", True)
        self._tip.configure(bg="#232a35")
        tk.Label(self._tip, text=self.text, bg="#232a35", fg="#d5dbe3",
                 font=("Microsoft YaHei", 10), padx=12, pady=8,
                 justify="left", wraplength=300).pack()
        self._tip.geometry(f"+{x}+{y}")


class _VSeparator(tk.Frame):
    """垂直可拖拽分隔条（PanedWindow 已替代，保留备用）"""

    def __init__(self, master, on_drag, bg=BORDER, width=5):
        super().__init__(master, width=width, bg=bg,
                         cursor="sb_h_double_arrow", highlightthickness=0)
        self._on_drag = on_drag
        self._start_x = 0
        self._dragging = False
        self._preview = None
        self.bind("<Button-1>", self._press)
        self.bind("<B1-Motion>", self._motion)
        self.bind("<ButtonRelease-1>", self._release)
        self.bind("<Double-Button-1>", lambda e: on_drag("reset"))

    def _press(self, e):
        self._start_x = e.x_root
        self._dragging = True
        self._show_preview(e.x_root)

    def _motion(self, e):
        if self._dragging:
            self._move_preview(e.x_root)

    def _release(self, e):
        self._dragging = False
        self._hide_preview()
        self._on_drag(e.x_root - self._start_x)

    def _show_preview(self, x):
        try:
            top = self.winfo_toplevel()
            h = top.winfo_screenheight()
            win = tk.Toplevel(top)
            win.overrideredirect(True)
            win.attributes("-topmost", True)
            win.configure(bg=ACCENT)
            win.geometry(f"2x{h}+{x}+0")
            # 鼠标点击穿透，避免预览线挡住分隔条拖动
            hwnd = win.winfo_id()
            while True:
                parent = ctypes.windll.user32.GetParent(hwnd)
                if parent == 0:
                    break
                hwnd = parent
            GWL_EXSTYLE = -20
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | 0x00000020 | 0x00080000 | 0x08000000)
            win.lift()
            self._preview = win
        except Exception:
            self._preview = None

    def _move_preview(self, x):
        if self._preview is not None:
            try:
                h = self.winfo_toplevel().winfo_screenheight()
                self._preview.geometry(f"2x{h}+{x}+0")
            except Exception:
                pass

    def _hide_preview(self):
        if self._preview is not None:
            try:
                self._preview.destroy()
            except Exception:
                pass
            self._preview = None


class ConfigGUI:
    """配置界面主类"""

    def __init__(self, on_save: Optional[Callable[[], None]] = None,
                 master: Optional[ctk.CTk] = None):
        self.on_save = on_save
        self._embedded = master is not None
        self.config = load_config()
        self.current_profile_name = self.config.get("settings", {}).get("active_profile", "AutoCAD-常用")
        self._current_target = "autocad"
        self.preset_commands = get_preset_commands(self._current_target)
        self._menu_theme_name = self.config.get("settings", {}).get("menu_theme", "azure")

        # 选中/hover 状态
        self._selected_sector: Optional[Tuple[str, int]] = None
        self._hovered_sector: Optional[Tuple[str, int]] = None
        # 预览圆盘参数
        self._preview_cx = 0
        self._preview_cy = 0
        self._preview_inner_r = 100
        self._preview_outer_r = 180
        self._preview_ext_r = 240
        self._preview_dead_r = 30
        self._preview_n = 8
        # 拖放状态
        self._drag_proxy: Optional[tk.Toplevel] = None
        self._drag_preset: Optional[Dict[str, str]] = None
        self._drag_pending: Optional[Dict[str, str]] = None
        self._drag_start_x: int = 0
        self._drag_start_y: int = 0
        # hover 节流
        self._hover_after_id: Optional[str] = None
        # 自动保存标志
        self._updating_detail = False
        # 编辑/搜索输入去抖 id
        self._detail_debounce_id: Optional[str] = None
        self._search_debounce_id: Optional[str] = None
        # profile 列表按钮引用
        self._profile_buttons: Dict[str, ctk.CTkButton] = {}

        # 创建主窗口（嵌入主程序 root 时用 Toplevel，避免多线程双 Tk 冲突）
        if self._embedded:
            self.root = ctk.CTkToplevel(master)
        else:
            self.root = ctk.CTk()
        self.root.title("CAD鼠标手势 - 设置")
        self.root.geometry("1180x780")
        self.root.minsize(1180, 760)
        self.root.configure(fg_color=BG)
        _enable_dark_titlebar(self.root)

        # 未保存修改标志
        self._has_changes = False
        self._autosave_after = None

        self._create_widgets()
        self._fix_window_flicker()
        self._load_profile(self.current_profile_name)

        # 快捷键
        self.root.bind("<Control-s>", lambda e: self._save())
        self.root.bind("<Control-f>", lambda e: self._focus_search())
        self.root.bind("<Escape>", lambda e: self._cancel_drag())
        self.root.protocol("WM_DELETE_WINDOW", self._on_close)

    def _set_initial_sash(self):
        """设置初始分隔条位置（paned.add 的 width 已处理，此方法备用）"""
        try:
            self._paned.paneconfigure(self.sidebar, width=230)
            self._paned.paneconfigure(self.right_panel, width=290)
        except Exception:
            pass

    def _fix_window_flicker(self):
        """修复 Windows 窗口切换/最小化后恢复时闪黑问题（设置窗口背景刷）"""
        try:
            hwnd = self.root.winfo_id()
            while True:
                parent = ctypes.windll.user32.GetParent(hwnd)
                if parent == 0:
                    break
                hwnd = parent

            bg_hex = BG.lstrip("#")
            bg_int = int(bg_hex[4:6] + bg_hex[2:4] + bg_hex[0:2], 16)
            dark_brush = ctypes.windll.gdi32.CreateSolidBrush(
                ctypes.c_uint32(bg_int))
            old_brush = ctypes.windll.user32.SetClassLongPtrW(hwnd, -10, dark_brush)
            if old_brush:
                ctypes.windll.gdi32.DeleteObject(old_brush)

            ctypes.windll.user32.InvalidateRect(hwnd, None, True)
            ctypes.windll.user32.UpdateWindow(hwnd)
        except Exception as e:
            print(f"[ConfigGUI] 无法设置窗口背景刷: {e}")

    # ========== 界面搭建 ==========

    def _create_widgets(self):
        """三栏布局（左侧导航 + 中间预览编辑 + 右侧命令库）"""
        main_frame = ctk.CTkFrame(self.root, fg_color=BG, corner_radius=0)
        main_frame.pack(fill=tk.BOTH, expand=True)
        main_frame.grid_rowconfigure(0, weight=1)
        main_frame.grid_rowconfigure(1, weight=0)
        main_frame.grid_columnconfigure(0, weight=1)

        # 三栏可拖拽布局：tk.PanedWindow（opaque=False = 拖动时只移动 sash，
        # pane 释放后才重排，避免 CustomTkinter 拖动分隔条时全量重排卡顿重影）
        self._paned = tk.PanedWindow(
            main_frame, orient=tk.HORIZONTAL, opaque=False, showhandle=False,
            sashwidth=5, sashrelief=tk.FLAT, bg=BORDER,
            borderwidth=0, relief=tk.FLAT)
        self._paned.grid(row=0, column=0, sticky="nsew")

        # ===== 左侧导航栏 =====
        self.sidebar = ctk.CTkFrame(self._paned, width=230, fg_color=SIDEBAR,
                                    corner_radius=0)
        self._paned.add(self.sidebar, width=230, minsize=160, stretch="never")
        self.sidebar.pack_propagate(False)
        sidebar = self.sidebar

        ctk.CTkLabel(sidebar, text="配置方案", text_color=TEXT,
                     font=_FONT_TITLE, anchor="w").pack(
            anchor="w", padx=22, pady=(22, 4))
        ctk.CTkLabel(sidebar, text="选择一个方案进行编辑",
                     text_color=TEXT_DIM, font=("Microsoft YaHei", 10),
                     anchor="w").pack(anchor="w", padx=22, pady=(0, 12))

        # Profile 列表（可滚动）
        list_frame = ctk.CTkScrollableFrame(
            sidebar, fg_color=SIDEBAR, scrollbar_button_color=PANEL,
            scrollbar_button_hover_color=BORDER_LIGHT)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=14, pady=(0, 10))
        self._list_frame = list_frame

        # Profile 操作按钮
        btn_grid = ctk.CTkFrame(sidebar, fg_color=SIDEBAR, corner_radius=0)
        btn_grid.pack(fill=tk.X, padx=14, pady=(0, 14))
        btn_grid.grid_columnconfigure(0, weight=1)
        btn_grid.grid_columnconfigure(1, weight=1)

        self._btn_add = ctk.CTkButton(
            btn_grid, text="＋ 新增", height=32, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#ffffff", font=_FONT_SMALL,
            command=self._add_profile)
        self._btn_add.grid(row=0, column=0, sticky="ew", padx=(0, 5), pady=3)
        _ToolTip(self._btn_add, "新建一个配置方案")
        self._btn_copy = ctk.CTkButton(
            btn_grid, text="复制", height=32, corner_radius=8,
            fg_color=CARD, hover_color=PRESET_HOVER,
            border_width=1, border_color=BORDER_LIGHT,
            text_color=TEXT, font=_FONT_SMALL,
            command=self._copy_profile)
        self._btn_copy.grid(row=0, column=1, sticky="ew", padx=(5, 0), pady=3)
        _ToolTip(self._btn_copy, "复制当前方案为副本")
        self._btn_rename = ctk.CTkButton(
            btn_grid, text="重命名", height=32, corner_radius=8,
            fg_color=CARD, hover_color=PRESET_HOVER,
            border_width=1, border_color=BORDER_LIGHT,
            text_color=TEXT, font=_FONT_SMALL,
            command=self._rename_profile)
        self._btn_rename.grid(row=1, column=0, sticky="ew", padx=(0, 5), pady=3)
        _ToolTip(self._btn_rename, "重命名当前方案")
        self._btn_del = ctk.CTkButton(
            btn_grid, text="删除", height=32, corner_radius=8,
            fg_color=CARD, hover_color="#3a2430",
            border_width=1, border_color="#4a2a35",
            text_color=DANGER, font=_FONT_SMALL,
            command=self._delete_profile)
        self._btn_del.grid(row=1, column=1, sticky="ew", padx=(5, 0), pady=3)
        _ToolTip(self._btn_del, "删除当前方案（至少保留一个）")

        # 底部全局设置入口
        tk.Frame(sidebar, bg=BORDER, height=1).pack(fill=tk.X, padx=20, pady=8)
        self._btn_settings = ctk.CTkButton(
            sidebar, text="设置", height=34, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#ffffff", font=_FONT_SMALL,
            command=self._show_settings)
        self._btn_settings.pack(fill=tk.X, padx=14, pady=(0, 14))
        _ToolTip(self._btn_settings, "全局设置：启动行为、外观、触发灵敏度、圆盘尺寸、导入导出")

        # ===== 中间内容区 =====
        center_frame = ctk.CTkFrame(self._paned, fg_color=BG, corner_radius=0)
        self._paned.add(center_frame, stretch="always")
        center_frame.grid_columnconfigure(0, weight=1)
        center_frame.grid_rowconfigure(1, weight=1)

        # 顶栏：当前方案 + 操作按钮
        top_bar = ctk.CTkFrame(center_frame, fg_color=BG, corner_radius=0)
        top_bar.grid(row=0, column=0, sticky="ew", pady=(0, 10))
        top_bar.grid_columnconfigure(0, weight=1)
        self.profile_badge = ctk.CTkLabel(top_bar, text="", text_color=TEXT,
                                          font=("Microsoft YaHei", 15, "bold"),
                                          anchor="w")
        self.profile_badge.grid(row=0, column=0, sticky="w")
        self.target_badge = ctk.CTkLabel(top_bar, text="", text_color=TEXT_DIM,
                                         font=_FONT_SMALL, anchor="w")
        self.target_badge.grid(row=0, column=1, sticky="w", padx=(10, 0), pady=(2, 0))

        # 右侧快捷操作（固定列，窗口变窄时按钮组不会被挤出）
        top_actions = ctk.CTkFrame(top_bar, fg_color=BG, corner_radius=0)
        top_actions.grid(row=0, column=2, sticky="e")
        self._btn_save = ctk.CTkButton(
            top_actions, text="保存", height=30, corner_radius=8,
            fg_color=ACCENT, hover_color=ACCENT_HOVER,
            text_color="#ffffff", font=_FONT_SMALL,
            command=self._save)
        self._btn_save.pack(side=tk.LEFT, padx=(9, 0))
        _ToolTip(self._btn_save, "保存全部修改并关闭 (Ctrl+S)")

        # 内容主体（预览 + 编辑），预览占满剩余空间
        self.body = ctk.CTkFrame(center_frame, fg_color=BG, corner_radius=0)
        self.body.grid(row=1, column=0, sticky="nsew")
        self.body.grid_columnconfigure(0, weight=1)
        self.body.grid_rowconfigure(0, weight=1)

        # 圆盘预览区（卡片，撑满主体）
        preview_card = ctk.CTkFrame(self.body, fg_color=CARD,
                                    corner_radius=14, border_width=1,
                                    border_color=BORDER)
        preview_card.grid(row=0, column=0, sticky="nsew", pady=(0, 14))
        preview_card.grid_rowconfigure(1, weight=1)
        preview_card.grid_columnconfigure(0, weight=1)

        preview_head = ctk.CTkFrame(preview_card, fg_color=CARD, corner_radius=0)
        preview_head.grid(row=0, column=0, sticky="ew", padx=18, pady=(12, 0))
        preview_head.grid_columnconfigure(1, weight=1)
        ctk.CTkLabel(preview_head, text="圆盘预览", text_color=TEXT,
                     font=("Microsoft YaHei", 13, "bold"),
                     anchor="w").grid(row=0, column=0, sticky="w")
        ctk.CTkLabel(preview_head, text="点击选择 · 双击快速编辑 · 从右侧拖入命令",
                     text_color=TEXT_DIM, font=("Microsoft YaHei", 11),
                     anchor="e").grid(row=0, column=1, sticky="e", pady=(2, 0))

        preview_inner = ctk.CTkFrame(preview_card, fg_color=CARD, corner_radius=14)
        preview_inner.grid(row=1, column=0, sticky="nsew", padx=20, pady=14)
        preview_inner.grid_rowconfigure(0, weight=1)
        preview_inner.grid_columnconfigure(0, weight=1)

        ext_r = self.config.get("settings", {}).get("ext_ring_radius", 240)
        self.preview_size = max(min(ext_r * 2 + 40, 420), 320)
        self._needs_preview_resize = False
        self.preview_canvas = tk.Canvas(
            preview_inner, width=self.preview_size, height=self.preview_size,
            bg=CARD, highlightthickness=0, borderwidth=0)
        self.preview_canvas.grid(row=0, column=0)
        self.preview_canvas.bind("<Button-1>", self._on_canvas_click)
        self.preview_canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.preview_canvas.bind("<Motion>", self._on_canvas_motion)
        self.preview_canvas.bind("<Leave>", self._on_canvas_leave)
        preview_inner.bind("<Configure>", self._on_preview_resize)

        # 扇区编辑卡片（紧凑，置于预览下方）
        sector_card = ctk.CTkFrame(self.body, fg_color=CARD,
                                   corner_radius=14, border_width=1,
                                   border_color=BORDER)
        sector_card.grid(row=1, column=0, sticky="ew", pady=(0, 4))
        card_inner = ctk.CTkFrame(sector_card, fg_color=CARD, corner_radius=14)
        card_inner.pack(fill=tk.X, padx=24, pady=18)

        sector_head = ctk.CTkFrame(card_inner, fg_color=CARD, corner_radius=0)
        sector_head.pack(fill=tk.X, pady=(0, 14))
        ctk.CTkLabel(sector_head, text="扇区编辑", text_color=ACCENT,
                     font=("Microsoft YaHei", 13, "bold"),
                     anchor="w").pack(side=tk.LEFT)
        self.selected_info = ctk.CTkLabel(
            sector_head, text="点击圆盘选择扇区", text_color=TEXT_DIM,
            font=("Microsoft YaHei", 11), anchor="e")
        self.selected_info.pack(side=tk.RIGHT)

        # 编辑表单（Grid 布局，加大行距）
        form_frame = ctk.CTkFrame(card_inner, fg_color=CARD, corner_radius=0)
        form_frame.pack(fill=tk.X)
        form_frame.grid_columnconfigure(1, weight=1, minsize=110)
        form_frame.grid_columnconfigure(2, minsize=100)
        form_frame.grid_columnconfigure(3, weight=2, minsize=130)
        form_frame.grid_columnconfigure(5, weight=2, minsize=130)

        # Row 0: 标签（统一左对齐，避免被拉伸后居中偏移）
        ctk.CTkLabel(form_frame, text="所在层", text_color=TEXT_DIM,
                     font=_FONT_SMALL, anchor="w").grid(row=0, column=0, sticky="w", padx=(0, 8), pady=(0, 8))
        ctk.CTkLabel(form_frame, text="显示名称", text_color=TEXT_DIM,
                     font=_FONT_SMALL, anchor="w").grid(row=0, column=1, sticky="w", padx=(0, 8), pady=(0, 8))
        ctk.CTkLabel(form_frame, text="快捷键", text_color=TEXT_DIM,
                     font=_FONT_SMALL, anchor="w").grid(row=0, column=2, sticky="w", padx=(0, 8), pady=(0, 8))
        ctk.CTkLabel(form_frame, text="CAD 命令", text_color=TEXT_DIM,
                     font=_FONT_SMALL, anchor="w").grid(row=0, column=3, sticky="w", padx=(0, 8), pady=(0, 8))

        # Row 1: 输入（加高，与按钮对齐）
        self.layer_label = ctk.CTkLabel(form_frame, text="未选择",
                                        text_color=ACCENT,
                                        font=("Microsoft YaHei", 12, "bold"))
        self.layer_label.grid(row=1, column=0, sticky="w", padx=(0, 8))

        self.detail_label_var = tk.StringVar()
        self.detail_label_entry = ctk.CTkEntry(
            form_frame, textvariable=self.detail_label_var, height=40,
            corner_radius=8, fg_color=PANEL, border_color=BORDER,
            text_color=TEXT, font=_FONT_SMALL,
            placeholder_text="扇区名称，如: 直线")
        self.detail_label_entry.grid(row=1, column=1, sticky="ew", padx=(0, 8))

        self.detail_key_var = tk.StringVar()
        self.detail_key_entry = ctk.CTkEntry(
            form_frame, textvariable=self.detail_key_var, height=40,
            corner_radius=8, fg_color=PANEL, border_color=BORDER,
            text_color=TEXT, font=_FONT_SMALL,
            placeholder_text="如: l")
        self.detail_key_entry.grid(row=1, column=2, sticky="ew", padx=(0, 8))

        self.detail_desc_var = tk.StringVar()
        self.detail_desc_entry = ctk.CTkEntry(
            form_frame, textvariable=self.detail_desc_var, height=40,
            corner_radius=8, fg_color=PANEL, border_color=BORDER,
            text_color=TEXT, font=_FONT_SMALL,
            placeholder_text="CAD 命令名，如: LINE")
        self.detail_desc_entry.grid(row=1, column=3, sticky="ew", padx=(0, 14))

        # 清空 / 复制按钮
        btn_col = ctk.CTkFrame(form_frame, fg_color=CARD, corner_radius=0)
        btn_col.grid(row=0, column=4, rowspan=2, sticky="nsew")
        self._btn_clear = ctk.CTkButton(
            btn_col, text="清空", height=36, corner_radius=8,
            fg_color=CARD, hover_color=PRESET_HOVER,
            border_width=1, border_color=BORDER_LIGHT,
            text_color=TEXT, font=_FONT_SMALL,
            command=self._clear_sector)
        self._btn_clear.pack(side=tk.LEFT, padx=(0, 8))
        _ToolTip(self._btn_clear, "清空当前选中扇区的配置")
        self._btn_copyto = ctk.CTkButton(
            btn_col, text="复制到…", height=36, corner_radius=8,
            fg_color=CARD, hover_color=PRESET_HOVER,
            border_width=1, border_color=BORDER_LIGHT,
            text_color=TEXT, font=_FONT_SMALL,
            command=self._copy_sector_to)
        self._btn_copyto.pack(side=tk.LEFT)
        _ToolTip(self._btn_copyto, "将当前扇区配置复制到其他扇区")

        # 自动保存
        self.detail_label_var.trace_add("write", self._on_detail_change)
        self.detail_key_var.trace_add("write", self._on_detail_change)
        self.detail_desc_var.trace_add("write", self._on_detail_change)

        # ===== 内嵌全局设置面板（与圆盘编辑同区域切换，不新开窗口） =====
        self.settings_view = ctk.CTkFrame(center_frame, fg_color=BG, corner_radius=0)
        self.settings_view.grid(row=1, column=0, sticky="nsew")
        self.settings_view.grid_rowconfigure(1, weight=1)
        self.settings_view.grid_columnconfigure(0, weight=1)
        self.settings_view.grid_remove()

        # 固定返回条（不随内容滚动）
        set_head = ctk.CTkFrame(self.settings_view, fg_color=BG, corner_radius=0)
        set_head.grid(row=0, column=0, sticky="ew", padx=6, pady=(6, 2))
        ctk.CTkButton(set_head, text="← 返回圆盘编辑", height=30, corner_radius=8,
                      fg_color=CARD, hover_color=PRESET_HOVER,
                      border_width=1, border_color=BORDER_LIGHT,
                      text_color=TEXT, font=_FONT_SMALL,
                      command=self._show_editor).pack(side=tk.LEFT)

        # 可滚动内容区
        self._settings_scroll = ctk.CTkScrollableFrame(
            self.settings_view, fg_color=BG, scrollbar_button_color=PANEL,
            scrollbar_button_hover_color=BORDER_LIGHT)
        self._settings_scroll.grid(row=1, column=0, sticky="nsew")

        self._settings_sliders = {}
        self._settings_checks = {}
        self._updating_settings = False

        # —— 常规 ——
        self._add_settings_section("常规")
        self._add_settings_check("open_config_on_start", "启动时打开此界面",
                                 "程序启动时自动弹出本配置界面")
        self._add_settings_check("auto_switch_profile", "根据 CAD 窗口自动切换",
                                 "前台窗口为 AutoCAD 或中望 CAD 时自动切换对应方案")

        # —— 圆盘外观 ——
        self._add_settings_section("圆盘外观")
        self._add_settings_theme()

        # —— 触发灵敏度 ——
        self._add_settings_section("触发灵敏度")
        self._add_settings_slider("hold_threshold_ms", "长按延迟",
                                  60, 200, 14, "ms",
                                  "长按鼠标右键多久后响应拖动（越小越灵敏）")
        self._add_settings_slider("trigger_distance", "触发距离",
                                  8, 40, 16, "px",
                                  "拖动多少像素后弹出圆盘（越小越灵敏）")

        # —— 圆盘尺寸（高级） ——
        self._add_settings_section("圆盘尺寸（高级）")
        self._add_settings_slider("dead_zone_radius", "中心死区半径",
                                  10, 60, 10, "",
                                  "圆盘中心不触发手势的区域半径")
        self._add_settings_slider("ring_radius", "内层半径",
                                  60, 160, 20, "",
                                  "内层扇区半径，需大于死区半径")
        self._add_settings_slider("outer_ring_radius", "外层半径",
                                  120, 260, 28, "",
                                  "外层扇区半径，需大于内层半径")
        self._add_settings_slider("ext_ring_radius", "扩展圈半径",
                                  180, 360, 36, "",
                                  "扩展圈半径，需大于外层半径")
        self._add_settings_slider("sector_count", "扇区数量",
                                  4, 16, 12, "",
                                  "圆盘扇区数（改动后需为新增扇区配置命令）")

        # —— 配置方案管理 ——
        self._add_settings_section("配置方案管理")
        mgmt = ctk.CTkFrame(self._settings_scroll, fg_color=BG, corner_radius=0)
        mgmt.pack(fill=tk.X, padx=20, pady=6)
        btn_imp = ctk.CTkButton(mgmt, text="导入方案", height=30, corner_radius=8,
                                fg_color=CARD, hover_color=PRESET_HOVER,
                                border_width=1, border_color=BORDER_LIGHT,
                                text_color=TEXT, font=_FONT_SMALL,
                                command=self._import_profile)
        btn_imp.pack(side=tk.LEFT, padx=(0, 8))
        _ToolTip(btn_imp, "从 JSON 文件合并配置到当前方案")
        btn_exp = ctk.CTkButton(mgmt, text="导出方案", height=30, corner_radius=8,
                                fg_color=CARD, hover_color=PRESET_HOVER,
                                border_width=1, border_color=BORDER_LIGHT,
                                text_color=TEXT, font=_FONT_SMALL,
                                command=self._export_profile)
        btn_exp.pack(side=tk.LEFT, padx=(0, 8))
        _ToolTip(btn_exp, "将当前方案导出为 JSON 文件")
        btn_rs = ctk.CTkButton(mgmt, text="恢复默认", height=30, corner_radius=8,
                               fg_color="#3a2430", hover_color="#4a2a35",
                               border_width=1, border_color="#4a2a35",
                               text_color=DANGER, font=_FONT_SMALL,
                               command=self._reset)
        btn_rs.pack(side=tk.LEFT)
        _ToolTip(btn_rs, "恢复全部默认配置（会丢失自定义设置）")

        # ===== 右侧命令库 =====
        self.right_panel = ctk.CTkFrame(self._paned, width=290, fg_color=PANEL,
                                        corner_radius=0)
        self._paned.add(self.right_panel, width=290, minsize=220, stretch="never")
        self.right_panel.pack_propagate(False)
        right_panel = self.right_panel

        right_head = ctk.CTkFrame(right_panel, fg_color=PANEL, corner_radius=0)
        right_head.pack(fill=tk.X, padx=18, pady=(20, 10))
        ctk.CTkLabel(right_head, text="命令库", text_color=ACCENT,
                     font=_FONT_TITLE, anchor="w").pack(side=tk.LEFT)
        ctk.CTkLabel(right_head, text="Ctrl+F", text_color=TEXT_DIM,
                     font=("Microsoft YaHei", 10), anchor="e").pack(
            side=tk.RIGHT, pady=(6, 0))

        # 搜索框
        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", lambda *a: self._on_search_change())
        self._search_entry = ctk.CTkEntry(
            right_panel, textvariable=self.search_var, height=38,
            corner_radius=8, placeholder_text="搜索命令…",
            placeholder_text_color=TEXT_DIM,
            fg_color=SIDEBAR, border_color=BORDER,
            text_color=TEXT, font=_FONT_SMALL)
        self._search_entry.pack(fill=tk.X, padx=18, pady=(0, 12))

        # 命令滚动区域
        preset_scroll = ctk.CTkScrollableFrame(
            right_panel, fg_color=PANEL, scrollbar_button_color=SIDEBAR,
            scrollbar_button_hover_color=BORDER_LIGHT)
        preset_scroll.pack(fill=tk.BOTH, expand=True, padx=10, pady=(0, 12))
        self.preset_container = preset_scroll

        # ===== 底部状态栏 =====
        status_bar = ctk.CTkFrame(main_frame, fg_color=SIDEBAR,
                                  corner_radius=0, height=36)
        status_bar.grid(row=1, column=0, sticky="ew")
        status_bar.grid_propagate(False)
        self.status_label = ctk.CTkLabel(
            status_bar, text="就绪", text_color=TEXT_DIM,
            font=("Microsoft YaHei", 10), anchor="w")
        self.status_label.pack(side=tk.LEFT, padx=16)
        self._unsaved_label = ctk.CTkLabel(
            status_bar, text="", text_color=WARN,
            font=("Microsoft YaHei", 10, "bold"), anchor="e")
        self._unsaved_label.pack(side=tk.RIGHT, padx=16)

        self._populate_presets()
        self._refresh_profile_list()

    def _focus_search(self):
        """Ctrl+F 聚焦搜索框"""
        self._search_entry.focus_set()
        self._search_entry.select_range(0, tk.END)

    # ========== Profile 列表 ==========

    def _refresh_profile_list(self):
        """刷新 Profile 列表（分组 + 按钮）"""
        for w in self._list_frame.winfo_children():
            w.destroy()
        self._profile_buttons.clear()

        autocad_profiles = []
        zwcad_profiles = []
        other_profiles = []
        for name, profile in self.config.get("profiles", {}).items():
            target = profile.get("target", "")
            display = profile.get("name", name)
            if target == "autocad":
                autocad_profiles.append((name, display))
            elif target == "zwcad":
                zwcad_profiles.append((name, display))
            else:
                other_profiles.append((name, display))

        def add_group(title, items):
            if not items:
                return
            head = ctk.CTkFrame(self._list_frame, fg_color=SIDEBAR, corner_radius=0)
            head.pack(fill=tk.X, padx=2, pady=(10, 2))
            ctk.CTkFrame(head, width=3, height=13, fg_color=ACCENT,
                         corner_radius=2).pack(side=tk.LEFT, padx=(4, 7), pady=2)
            ctk.CTkLabel(head, text=title, text_color=ACCENT,
                         font=("Microsoft YaHei", 11, "bold"),
                         anchor="w").pack(side=tk.LEFT)
            for name, display in items:
                btn = ctk.CTkButton(
                    self._list_frame, text=display, anchor="w",
                    height=32, corner_radius=8, font=_FONT_SMALL,
                    fg_color=SIDEBAR, hover_color=PRESET_HOVER,
                    text_color=TEXT_SECONDARY,
                    command=lambda n=name: self._select_profile(n))
                btn.pack(fill=tk.X, pady=1)
                self._profile_buttons[name] = btn

        add_group("AutoCAD", autocad_profiles)
        add_group("中望CAD", zwcad_profiles)
        add_group("其他", other_profiles)
        self._highlight_profile(self.current_profile_name)

    def _highlight_profile(self, name: str):
        for n, btn in self._profile_buttons.items():
            if n == name:
                btn.configure(fg_color=ACCENT_DIM, text_color="#ffffff",
                              hover_color=ACCENT_DIM)
            else:
                btn.configure(fg_color=SIDEBAR, text_color=TEXT_SECONDARY,
                              hover_color=PRESET_HOVER)

    def _select_profile(self, profile_name: str):
        self._load_profile(profile_name)

    # ========== 设置/保存 ==========

    def _set_changed(self):
        """标记有未保存修改，并触发防抖自动保存"""
        self._has_changes = True
        if getattr(self, "_unsaved_label", None) is not None:
            self._unsaved_label.configure(text="● 保存中…")
        self._schedule_autosave()

    def _clear_changed(self):
        """清除未保存标记"""
        self._has_changes = False
        if getattr(self, "_unsaved_label", None) is not None:
            self._unsaved_label.configure(text="")

    def _schedule_autosave(self):
        """防抖自动保存：改动后 500ms 写盘，避免频繁写"""
        if getattr(self, "_autosave_after", None) is not None:
            self.root.after_cancel(self._autosave_after)
        self._autosave_after = self.root.after(500, self._do_autosave)

    def _do_autosave(self):
        """执行自动保存"""
        self._autosave_after = None
        self._collect_config()
        save_config(self.config)
        if getattr(self, "_unsaved_label", None) is not None:
            self._unsaved_label.configure(text="✓ 已自动保存")

    def _show_settings(self):
        """就地切换到全局设置面板（不新开窗口）"""
        self._refresh_settings_values()
        self.body.grid_remove()
        self.settings_view.grid()
        self._btn_save.pack_forget()
        try:
            self._settings_scroll._parent_canvas.yview_moveto(0.0)
        except Exception:
            pass
        self.status_label.configure(text="全局设置：修改即时保存")

    def _show_editor(self):
        """返回圆盘编辑视图"""
        self.settings_view.grid_remove()
        self.body.grid()
        self._btn_save.pack(side=tk.LEFT, padx=(9, 0))
        self._refresh_badges()
        self._draw_preview()
        self.status_label.configure(text="圆盘编辑")

    def _refresh_badges(self):
        """刷新顶栏当前方案徽标"""
        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        display_name = profile.get("name", self.current_profile_name)
        if len(display_name) > 12:
            display_name = display_name[:12] + "…"
        target = profile.get("target", "autocad")
        target_label = {"autocad": "AutoCAD", "zwcad": "中望CAD"}.get(
            target, target.upper())
        self.profile_badge.configure(text=display_name)
        self.target_badge.configure(text=target_label)

    def _refresh_settings_values(self):
        """进入设置面板时从配置刷新控件显示值"""
        s = self.config.get("settings", {})
        self._updating_settings = True
        try:
            for key, var in self._settings_checks.items():
                var.set(bool(s.get(key, False)))
            labels = [t.label for t in MENU_THEMES.values()]
            cur = s.get("menu_theme", "azure")
            cur_label = next((t.label for t in MENU_THEMES.values()
                              if t.name == cur), labels[0])
            self._settings_theme.set(cur_label)
            for key, (slider, label, unit) in self._settings_sliders.items():
                val = int(s.get(key, slider.get()))
                slider.set(val)
                label.configure(text=f"{val}{unit}")
        finally:
            self._updating_settings = False

    def _add_settings_section(self, title):
        """设置面板区块标题"""
        head = ctk.CTkFrame(self._settings_scroll, fg_color=BG, corner_radius=0)
        head.pack(fill=tk.X, pady=(18, 4))
        ctk.CTkFrame(head, width=3, height=14, fg_color=ACCENT,
                     corner_radius=2).pack(side=tk.LEFT, padx=(18, 8))
        ctk.CTkLabel(head, text=title, text_color=ACCENT,
                     font=("Microsoft YaHei", 12, "bold")).pack(side=tk.LEFT)

    def _add_settings_check(self, key, text, tip):
        """设置面板开关项"""
        var = tk.BooleanVar(
            value=bool(self.config.get("settings", {}).get(key, False)))
        cb = ctk.CTkCheckBox(self._settings_scroll, text=text, variable=var,
                             text_color=TEXT, fg_color=ACCENT,
                             hover_color=ACCENT_DIM, checkmark_color="#ffffff",
                             border_color=BORDER_LIGHT, corner_radius=6,
                             font=_FONT_SMALL,
                             command=lambda k=key: self._on_settings_check(k))
        cb.pack(anchor="w", padx=20, pady=4)
        _ToolTip(cb, tip)
        self._settings_checks[key] = var

    def _add_settings_theme(self):
        """设置面板外观主题下拉"""
        labels = [t.label for t in MENU_THEMES.values()]
        cur = self.config.get("settings", {}).get("menu_theme", "azure")
        cur_label = next((t.label for t in MENU_THEMES.values()
                          if t.name == cur), labels[0])
        row = ctk.CTkFrame(self._settings_scroll, fg_color=BG, corner_radius=0)
        row.pack(fill=tk.X, padx=20, pady=4)
        ctk.CTkLabel(row, text="外观主题", text_color=TEXT,
                     font=_FONT_SMALL, anchor="w").pack(side=tk.LEFT)
        option = ctk.CTkOptionMenu(
            row, values=labels, height=30, corner_radius=8,
            fg_color=CARD, button_color=PANEL, button_hover_color=PRESET_HOVER,
            dropdown_fg_color=CARD, dropdown_hover_color=PRESET_HOVER,
            dropdown_text_color=TEXT, text_color=TEXT, font=_FONT_SMALL,
            command=self._on_settings_theme)
        option.set(cur_label)
        option.pack(side=tk.RIGHT)
        _ToolTip(option, "切换圆盘菜单的配色风格")
        self._settings_theme = option

    def _add_settings_slider(self, key, text, from_, to, steps, unit, tip):
        """设置面板滑块项（带实时数值标签）"""
        row = ctk.CTkFrame(self._settings_scroll, fg_color=BG, corner_radius=0)
        row.pack(fill=tk.X, padx=20, pady=(8, 0))
        ctk.CTkLabel(row, text=text, text_color=TEXT,
                     font=_FONT_SMALL, anchor="w").pack(side=tk.LEFT)
        value_label = ctk.CTkLabel(row, text="", text_color=ACCENT,
                                   font=_FONT_SMALL, anchor="e")
        value_label.pack(side=tk.RIGHT)

        val = int(self.config.get("settings", {}).get(key, from_))
        value_label.configure(text=f"{val}{unit}")

        slider = ctk.CTkSlider(
            self._settings_scroll, from_=from_, to=to, number_of_steps=steps,
            height=16, button_color=ACCENT, button_hover_color=ACCENT_HOVER,
            progress_color=ACCENT, fg_color=BORDER,
            command=lambda v, k=key: self._on_settings_slider(k, v))
        slider.set(val)
        slider.pack(fill=tk.X, padx=20, pady=(2, 2))
        _ToolTip(slider, tip)
        self._disable_slider_wheel(slider)
        self._settings_sliders[key] = (slider, value_label, unit)

    def _disable_slider_wheel(self, slider):
        """禁用滚轮对滑块值的改动（滚轮改为滚动设置面板，防误触）

        CTkSlider 把滚轮绑定在其内部 canvas 上且 bind 代理用 add=True 追加，
        无法通过外部 bind 覆盖，须直接替换内部 canvas 的滚轮绑定。
        滚动速度与 CTkScrollableFrame 的标准滚轮一致（-delta/6，非 -delta/120）。
        """
        scroll_view = self._settings_scroll

        def _on_wheel(e):
            try:
                canvas = scroll_view._parent_canvas
                if getattr(e, "num", None) in (4, 5):
                    if canvas.yview() != (0.0, 1.0):
                        canvas.yview_scroll(-1 if e.num == 4 else 1, "units")
                elif getattr(e, "delta", 0):
                    if canvas.yview() != (0.0, 1.0):
                        canvas.yview("scroll", -int(e.delta / 6), "units")
            except Exception:
                pass
            return "break"

        try:
            inner = slider._canvas
        except AttributeError:
            return
        inner.bind("<MouseWheel>", _on_wheel)
        inner.bind("<Button-4>", _on_wheel)
        inner.bind("<Button-5>", _on_wheel)

    def _save_now(self):
        """设置改动立即写盘（取消防抖）"""
        if getattr(self, "_autosave_after", None) is not None:
            self.root.after_cancel(self._autosave_after)
            self._autosave_after = None
            self._do_autosave()
        elif save_config(self.config):
            self._has_changes = False
            if getattr(self, "_unsaved_label", None) is not None:
                self._unsaved_label.configure(text="✓ 已保存")

    def _on_settings_slider(self, key, value):
        """设置面板滑块回调（即时写入配置并保存）"""
        if self._updating_settings or key not in self._settings_sliders:
            return
        val = int(round(value))
        slider, label, unit = self._settings_sliders[key]
        label.configure(text=f"{val}{unit}")
        self.config.setdefault("settings", {})[key] = val
        if key in ("dead_zone_radius", "ring_radius", "outer_ring_radius",
                   "ext_ring_radius"):
            self._apply_radius_constraints()
        self._save_now()
        self._draw_preview()

    def _on_settings_check(self, key):
        """设置面板开关回调（即时写入配置并保存）"""
        if self._updating_settings:
            return
        var = self._settings_checks[key]
        self.config.setdefault("settings", {})[key] = var.get()
        self._save_now()

    def _on_settings_theme(self, label):
        """设置面板主题回调（即时写入配置并保存）"""
        if self._updating_settings:
            return
        name = next((t.name for t in MENU_THEMES.values()
                     if t.label == label), "azure")
        self._menu_theme_name = name
        self.config.setdefault("settings", {})["menu_theme"] = name
        self._save_now()
        self._draw_preview()

    def _apply_radius_constraints(self):
        """保证 死区 < 内层 < 外层 < 扩展圈，并同步滑块位置"""
        s = self.config.setdefault("settings", {})
        dead = int(s.get("dead_zone_radius", 30))
        inner = int(s.get("ring_radius", 100))
        outer = int(s.get("outer_ring_radius", 180))
        ext = int(s.get("ext_ring_radius", 240))
        inner = max(inner, dead + 10)
        outer = max(outer, inner + 10)
        ext = max(ext, outer + 10)
        s["ring_radius"] = inner
        s["outer_ring_radius"] = outer
        s["ext_ring_radius"] = ext
        self._updating_settings = True
        try:
            for key, val in (("dead_zone_radius", dead), ("ring_radius", inner),
                             ("outer_ring_radius", outer),
                             ("ext_ring_radius", ext)):
                slider, label, unit = self._settings_sliders[key]
                slider.set(val)
                label.configure(text=f"{val}{unit}")
        finally:
            self._updating_settings = False

    def _load_profile(self, profile_name: str):
        """加载 Profile"""
        self.current_profile_name = profile_name
        self._selected_sector = None
        self._hovered_sector = None
        self._highlight_profile(profile_name)

        profile = self.config.get("profiles", {}).get(profile_name, {})
        new_target = profile.get("target", "autocad")
        if new_target != self._current_target:
            self._current_target = new_target
            self.preset_commands = get_preset_commands(new_target)
            self._populate_presets()

        self._updating_detail = True
        self._update_detail_panel()
        self._updating_detail = False
        self._draw_preview()

        display_name = profile.get("name", profile_name)
        if len(display_name) > 12:
            display_name = display_name[:12] + "…"
        target_label = {"autocad": "AutoCAD", "zwcad": "中望CAD"}.get(
            new_target, new_target.upper())
        self.profile_badge.configure(text=display_name)
        self.target_badge.configure(text=target_label)
        self.status_label.configure(text=f"已加载方案「{display_name}」")

    # ========== 圆盘绘制 ==========

    def _on_preview_resize(self, event):
        """预览区大小变化时调整画布尺寸（防抖：停止缩放后再重绘，避免拖动窗口卡顿）"""
        if event.width <= 10 or event.height <= 10:
            return
        if getattr(self, "_preview_resize_after", None) is not None:
            self.root.after_cancel(self._preview_resize_after)
        self._preview_resize_after = self.root.after(
            80, lambda: self._apply_preview_resize(event.width, event.height))

    def _apply_preview_resize(self, w: int, h: int):
        """实际执行预览重绘"""
        self._preview_resize_after = None
        new_size = min(w - 28, h - 28, 620)
        new_size = max(new_size, 260)
        if abs(new_size - self.preview_size) > 8:
            self.preview_size = new_size
            self.preview_canvas.config(width=new_size, height=new_size)
            self._draw_preview()

    def _draw_preview(self):
        """绘制圆盘预览 - 使用共享渲染器"""
        self.preview_canvas.delete("all")

        cx = self.preview_size // 2
        cy = self.preview_size // 2
        inner_r = self.config.get("settings", {}).get("ring_radius", 100)
        outer_r = self.config.get("settings", {}).get("outer_ring_radius", 180)
        ext_r = self.config.get("settings", {}).get("ext_ring_radius", 240)
        dead_r = self.config.get("settings", {}).get("dead_zone_radius", 30)

        self._preview_cx = cx
        self._preview_cy = cy
        self._preview_inner_r = inner_r
        self._preview_outer_r = outer_r
        self._preview_ext_r = ext_r
        self._preview_dead_r = dead_r

        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        n = self.config.get("settings", {}).get("sector_count", 8)
        self._preview_n = n
        t = get_menu_theme(self._menu_theme_name)

        # 扩展圈阴影
        self.preview_canvas.create_oval(
            cx - ext_r - 3, cy - ext_r - 3,
            cx + ext_r + 3, cy + ext_r + 3,
            fill="#14181f", outline="")

        # 扩展圈（预览保留三圈，便于编辑扩展命令）
        draw_ring(self.preview_canvas, cx, cy, outer_r, ext_r, n,
                  profile.get("extension_sectors", {}),
                  lambda i, cfg: ring_state_preview(
                      t.extension, bool(cfg.get("label")),
                      self._selected_sector == ("extension", i),
                      self._hovered_sector == ("extension", i),
                      t.border, t.accent_dim),
                  label_offset=0.5)

        # 外层
        draw_ring(self.preview_canvas, cx, cy, inner_r, outer_r, n,
                  profile.get("outer_sectors", {}),
                  lambda i, cfg: ring_state_preview(
                      t.outer, bool(cfg.get("label")),
                      self._selected_sector == ("outer", i),
                      self._hovered_sector == ("outer", i),
                      t.border, t.accent_dim),
                  label_offset=0.5)

        # 内层
        draw_ring(self.preview_canvas, cx, cy, dead_r, inner_r, n,
                  profile.get("sectors", {}),
                  lambda i, cfg: ring_state_preview(
                      t.inner, bool(cfg.get("label")),
                      self._selected_sector == ("inner", i),
                      self._hovered_sector == ("inner", i),
                      t.border, t.accent_dim),
                  label_offset=0.5)

        # 中心死区
        self.preview_canvas.create_oval(
            cx - dead_r, cy - dead_r, cx + dead_r, cy + dead_r,
            fill=t.dead_zone, outline=t.border, width=1)

        # 中心文字
        if self._selected_sector:
            layer, idx = self._selected_sector
            sectors_key = _layer_to_sectors_key(layer)
            cfg = profile.get(sectors_key, {}).get(str(idx), {})
            label = cfg.get("label", "")
            layer_prefix = "扩展 " if layer == "extension" else ""
            center_text = f"{layer_prefix}{label}" if label else f"{layer_prefix}扇区{idx}"
        else:
            center_text = "释放"
        self.preview_canvas.create_text(cx, cy, text=center_text, fill=t.center_text,
                                        font=("Microsoft YaHei", 10), anchor=tk.CENTER)

    def _calc_sector_at(self, canvas_x: int, canvas_y: int) -> Optional[Tuple[str, int]]:
        """计算 canvas 坐标所在的扇区"""
        cx, cy = self._preview_cx, self._preview_cy
        dx, dy = canvas_x - cx, canvas_y - cy
        dist = math.sqrt(dx * dx + dy * dy)

        if dist < self._preview_dead_r:
            return None

        sector = calc_sector(dx, dy, self._preview_n)

        if dist < self._preview_inner_r:
            return ("inner", sector)
        elif dist < self._preview_outer_r:
            return ("outer", sector)
        elif dist < self._preview_ext_r:
            return ("extension", sector)
        return None

    def _on_canvas_motion(self, event):
        """圆盘 hover 事件（节流 45ms，避免拖动窗口时预览全量重绘风暴卡顿）"""
        ex, ey = event.x, event.y
        if self._hover_after_id is not None:
            return

        def update():
            self._hover_after_id = None
            x, y = self.preview_canvas.canvasx(ex), self.preview_canvas.canvasy(ey)
            new_hover = self._calc_sector_at(x, y)
            if new_hover != self._hovered_sector:
                self._hovered_sector = new_hover
                self._draw_preview()
                if new_hover:
                    self.preview_canvas.config(cursor="hand2")
                else:
                    self.preview_canvas.config(cursor="")

        self._hover_after_id = self.root.after(45, update)

    def _on_canvas_leave(self, event):
        """鼠标离开圆盘"""
        if self._hover_after_id is not None:
            self.root.after_cancel(self._hover_after_id)
            self._hover_after_id = None
        if self._hovered_sector is not None:
            self._hovered_sector = None
            self._draw_preview()
            self.preview_canvas.config(cursor="")

    def _on_canvas_click(self, event):
        """圆盘点击事件"""
        x, y = self.preview_canvas.canvasx(event.x), self.preview_canvas.canvasy(event.y)
        sector = self._calc_sector_at(x, y)

        if sector is None:
            return

        self._selected_sector = sector
        self._updating_detail = True
        self._update_detail_panel()
        self._updating_detail = False
        self._draw_preview()

        layer_name = _layer_display_name(sector[0])
        self.status_label.configure(
            text=f"已选择{layer_name}扇区 {sector[1]}，可编辑或拖放预设命令")

    def _on_canvas_double_click(self, event):
        """双击 → 聚焦编辑面板"""
        x, y = self.preview_canvas.canvasx(event.x), self.preview_canvas.canvasy(event.y)
        sector = self._calc_sector_at(x, y)
        if sector:
            self._selected_sector = sector
            self._updating_detail = True
            self._update_detail_panel()
            self._updating_detail = False
            self._draw_preview()
            self.detail_label_entry.focus_set()

    def _update_detail_panel(self):
        """更新详情面板"""
        if self._selected_sector is None:
            self.layer_label.configure(text="未选择")
            self.detail_label_var.set("")
            self.detail_key_var.set("")
            self.detail_desc_var.set("")
            self.selected_info.configure(text="点击圆盘选择扇区")
            return

        layer, idx = self._selected_sector
        layer_name = _layer_display_name(layer)
        self.layer_label.configure(text=f"{layer_name} · 扇区 {idx}")
        self.selected_info.configure(text=f"正在编辑: {layer_name}扇区 {idx}")

        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        sectors_key = _layer_to_sectors_key(layer)
        cfg = profile.get(sectors_key, {}).get(str(idx), {})

        self.detail_label_var.set(cfg.get("label", ""))
        self.detail_key_var.set(cfg.get("key", ""))
        self.detail_desc_var.set(cfg.get("description", ""))

    def _on_detail_change(self, *args):
        """编辑框内容变化时自动保存（连续输入合并重绘）"""
        if self._updating_detail:
            return
        if self._selected_sector is None:
            return

        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        sectors_key = _layer_to_sectors_key(layer)
        sectors = profile.setdefault(sectors_key, {})

        label_val = self.detail_label_var.get().strip()
        key_val = self.detail_key_var.get().strip()
        desc_val = self.detail_desc_var.get().strip()

        sectors[str(idx)] = {
            "label": label_val,
            "key": key_val,
            "description": desc_val
        }

        self._set_changed()
        # 连续输入合并为一次重绘，避免每敲一个字符全量重画圆盘
        if self._detail_debounce_id is not None:
            self.root.after_cancel(self._detail_debounce_id)
        self._detail_debounce_id = self.root.after(150, self._flush_detail_preview)

    def _flush_detail_preview(self):
        """去抖后的预览重绘"""
        self._detail_debounce_id = None
        self._draw_preview()

    def _clear_sector(self):
        """清空扇区"""
        if self._selected_sector is None:
            _dark_msgbox(self.root, "提示", "请先在圆盘上点击选择一个扇区", "warning")
            return

        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        sectors_key = _layer_to_sectors_key(layer)
        sectors = profile.get(sectors_key, {})

        if str(idx) in sectors:
            del sectors[str(idx)]
            self._set_changed()
            self._updating_detail = True
            self._update_detail_panel()
            self._updating_detail = False
            self._draw_preview()
            self.status_label.configure(text=f"已清空扇区 {idx}")

    def _copy_sector_to(self):
        """复制当前扇区配置到其他位置"""
        if self._selected_sector is None:
            _dark_msgbox(self.root, "提示", "请先在圆盘上点击选择一个扇区", "warning")
            return

        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        sectors_key = _layer_to_sectors_key(layer)
        cfg = profile.get(sectors_key, {}).get(str(idx), {})
        if not cfg:
            _dark_msgbox(self.root, "提示", "当前扇区为空，无需复制", "info")
            return

        # 弹出对话框选择目标扇区
        dialog = _DarkDialog(self.root, "复制到...", "选择目标位置：",
                             kind="question", buttons=(), width=340)
        win = dialog.top
        for w in win.winfo_children():
            w.destroy()
        win.geometry("340x300")

        body = ctk.CTkFrame(win, fg_color=BG, corner_radius=0)
        body.pack(fill=tk.BOTH, expand=True, padx=22, pady=16)

        ctk.CTkLabel(body, text=f"将「{cfg.get('label', '')}」复制到:",
                     text_color=TEXT, font=_FONT).pack(pady=(4, 10))

        target_var = tk.StringVar(value="inner")
        for val, name in (("inner", "内层"), ("outer", "外层"),
                          ("extension", "扩展圈")):
            ctk.CTkRadioButton(body, text=name, value=val,
                               variable=target_var, text_color=TEXT,
                               fg_color=ACCENT, hover_color=ACCENT_DIM,
                               border_color=BORDER_LIGHT, font=_FONT_SMALL
                               ).pack(anchor="w", padx=16, pady=2)

        idx_var = tk.StringVar(value=str(idx))
        ctk.CTkLabel(body, text="目标扇区编号:", text_color=TEXT_DIM,
                     font=_FONT_SMALL).pack(pady=(8, 4))
        ctk.CTkEntry(body, textvariable=idx_var, width=80, height=32,
                     corner_radius=8, fg_color=PANEL, border_color=BORDER,
                     text_color=TEXT).pack()

        btn_row = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        btn_row.pack(pady=(14, 4))

        def do_copy():
            target_layer = target_var.get()
            try:
                target_idx = int(idx_var.get())
            except (ValueError, TypeError):
                _dark_msgbox(self.root, "错误", "扇区编号必须是数字", "error")
                return
            sector_count = self.config.get("settings", {}).get("sector_count", 8)
            if not (0 <= target_idx < sector_count):
                _dark_msgbox(self.root, "错误",
                             f"扇区编号需在 0~{sector_count - 1} 之间", "error")
                return
            target_key = _layer_to_sectors_key(target_layer)
            target_sectors = profile.setdefault(target_key, {})
            target_sectors[str(target_idx)] = cfg.copy()
            self._set_changed()
            self._draw_preview()
            win.destroy()
            layer_name = _layer_display_name(target_layer)
            self.status_label.configure(text=f"已复制到{layer_name}扇区 {target_idx}")

        ctk.CTkButton(btn_row, text="复制", height=30, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", font=_FONT_SMALL,
                      command=do_copy).pack(side=tk.LEFT, padx=6)
        ctk.CTkButton(btn_row, text="取消", height=30, corner_radius=8,
                      fg_color=CARD, hover_color=PRESET_HOVER,
                      border_width=1, border_color=BORDER_LIGHT,
                      text_color=TEXT, font=_FONT_SMALL,
                      command=win.destroy).pack(side=tk.LEFT, padx=6)

        dialog.top.wait_window()

    def _export_profile(self):
        """导出当前 Profile 为 JSON 文件"""
        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        if not profile:
            _dark_msgbox(self.root, "提示", "没有可导出的配置", "warning")
            return

        path = filedialog.asksaveasfilename(
            defaultextension=".json",
            filetypes=[("JSON 文件", "*.json")],
            initialfile=f"{self.current_profile_name}.json"
        )
        if path:
            with open(path, "w", encoding="utf-8") as f:
                json.dump(profile, f, ensure_ascii=False, indent=2)
            self.status_label.configure(text=f"已导出到: {path}")

    def _import_profile(self):
        """从 JSON 文件导入 Profile"""
        path = filedialog.askopenfilename(
            filetypes=[("JSON 文件", "*.json")]
        )
        if not path:
            return

        try:
            with open(path, "r", encoding="utf-8") as f:
                data = json.load(f)
            if not isinstance(data, dict):
                _dark_msgbox(self.root, "错误", "无效的配置文件格式", "error")
                return

            # 先校验结构，再合并：避免坏数据污染内存配置后被保存
            for key in ("sectors", "outer_sectors", "extension_sectors"):
                if key in data:
                    if not isinstance(data[key], dict):
                        _dark_msgbox(self.root, "错误",
                                     f"导入失败：{key} 格式无效（应为对象）", "error")
                        return
                    for v in data[key].values():
                        if not isinstance(v, dict):
                            _dark_msgbox(self.root, "错误",
                                         f"导入失败：{key} 中存在无效的扇区数据", "error")
                            return

            # 校验通过后合并到当前 profile
            profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
            for key in ("sectors", "outer_sectors", "extension_sectors"):
                if key in data:
                    profile[key] = data[key]
            self._set_changed()
            self._draw_preview()
            self._update_detail_panel()
            self.status_label.configure(text=f"已从 {path} 导入配置")
        except Exception as e:
            _dark_msgbox(self.root, "错误", f"导入失败: {e}", "error")

    # ========== 拖放系统 ==========

    def _start_drag(self, preset_info: Dict[str, str], event):
        """开始拖放"""
        self._drag_preset = preset_info

        proxy = tk.Toplevel(self.root)
        proxy.overrideredirect(True)
        proxy.attributes("-topmost", True)
        proxy.attributes("-alpha", 0.85)
        proxy.configure(bg=DRAG_PROXY_BG)

        # Windows: 让代理窗口穿透鼠标事件
        try:
            hwnd = proxy.winfo_id()
            while True:
                parent = ctypes.windll.user32.GetParent(hwnd)
                if parent == 0:
                    break
                hwnd = parent
            GWL_EXSTYLE = -20
            WS_EX_TRANSPARENT = 0x00000020
            WS_EX_LAYERED = 0x00080000
            WS_EX_NOACTIVATE = 0x08000000
            style = ctypes.windll.user32.GetWindowLongW(hwnd, GWL_EXSTYLE)
            ctypes.windll.user32.SetWindowLongW(
                hwnd, GWL_EXSTYLE,
                style | WS_EX_TRANSPARENT | WS_EX_LAYERED | WS_EX_NOACTIVATE)
        except Exception:
            pass

        label_text = preset_info.get("label", "")
        lbl = tk.Label(proxy, text=label_text, bg=DRAG_PROXY_BG,
                       fg="#ffffff", font=("Microsoft YaHei", 10, "bold"),
                       padx=14, pady=8)
        lbl.pack()

        screen_x = event.x_root
        screen_y = event.y_root
        proxy.geometry(f"+{screen_x + 10}+{screen_y + 10}")

        self._drag_proxy = proxy
        self.root.bind_all("<B1-Motion>", self._on_drag_motion)
        self.root.bind_all("<ButtonRelease-1>", self._on_drag_release)

    def _on_drag_motion(self, event):
        """拖动中"""
        if not self._drag_proxy:
            return
        self._drag_proxy.geometry(f"+{event.x_root + 10}+{event.y_root + 10}")

        canvas_widget = self.preview_canvas
        canvas_x = canvas_widget.winfo_rootx()
        canvas_y = canvas_widget.winfo_rooty()
        rel_x = event.x_root - canvas_x
        rel_y = event.y_root - canvas_y
        cx = canvas_widget.canvasx(rel_x)
        cy = canvas_widget.canvasy(rel_y)

        if 0 <= cx <= self.preview_size and 0 <= cy <= self.preview_size:
            new_hover = self._calc_sector_at(cx, cy)
            if new_hover != self._hovered_sector:
                self._hovered_sector = new_hover
                self._draw_preview()
        else:
            if self._hovered_sector is not None:
                self._hovered_sector = None
                self._draw_preview()

    def _on_drag_release(self, event):
        """释放"""
        self.root.unbind_all("<B1-Motion>")
        self.root.unbind_all("<ButtonRelease-1>")

        if self._drag_proxy:
            self._drag_proxy.destroy()
            self._drag_proxy = None

        canvas_widget = self.preview_canvas
        canvas_x = canvas_widget.winfo_rootx()
        canvas_y = canvas_widget.winfo_rooty()
        rel_x = event.x_root - canvas_x
        rel_y = event.y_root - canvas_y
        cx = canvas_widget.canvasx(rel_x)
        cy = canvas_widget.canvasy(rel_y)

        if 0 <= cx <= self.preview_size and 0 <= cy <= self.preview_size:
            sector = self._calc_sector_at(cx, cy)
            if sector and self._drag_preset:
                layer, idx = sector
                profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
                sectors_key = _layer_to_sectors_key(layer)
                sectors = profile.setdefault(sectors_key, {})
                sectors[str(idx)] = self._drag_preset.copy()

                self._selected_sector = sector
                self._set_changed()
                self._updating_detail = True
                self._update_detail_panel()
                self._updating_detail = False
                self._draw_preview()

                label = self._drag_preset.get("label", "")
                layer_name = _layer_display_name(layer)
                self.status_label.configure(
                    text=f"已将「{label}」放置到{layer_name}扇区 {idx}")

        self._drag_preset = None
        self._drag_pending = None
        self._hovered_sector = None
        self._draw_preview()

    def _cancel_drag(self):
        """取消拖放"""
        if self._drag_proxy:
            self._drag_proxy.destroy()
            self._drag_proxy = None
        self.root.unbind_all("<B1-Motion>")
        self.root.unbind_all("<ButtonRelease-1>")
        self._drag_preset = None
        self._drag_pending = None
        self._hovered_sector = None
        self._draw_preview()

    # ========== 预设命令库 ==========

    def _on_search_change(self):
        """搜索框内容变化（重建去抖，合并连续输入）"""
        if self._search_debounce_id is not None:
            self.root.after_cancel(self._search_debounce_id)
        text = self.search_var.get()
        self._search_debounce_id = self.root.after(180, lambda: self._apply_search(text))

    def _apply_search(self, text: str):
        """去抖后的命令库重建"""
        self._search_debounce_id = None
        self._populate_presets(text)

    def _populate_presets(self, filter_text: str = ""):
        """填充预设命令库"""
        for widget in self.preset_container.winfo_children():
            widget.destroy()

        filter_text = filter_text.lower().strip()

        for cat_index, (category, commands) in enumerate(self.preset_commands.items()):
            if filter_text:
                filtered = {name: data for name, data in commands.items()
                           if filter_text in name.lower()
                           or filter_text in data.get("label", "").lower()
                           or filter_text in data.get("key", "").lower()
                           or filter_text in data.get("description", "").lower()}
                if not filtered:
                    continue
            else:
                filtered = commands

            # 分类容器
            cat_frame = ctk.CTkFrame(self.preset_container, fg_color=PANEL,
                                     corner_radius=10)
            cat_frame.pack(fill=tk.X, padx=2, pady=3)

            # 无搜索词时默认展开前 3 个常用类别，有搜索词时展开全部命中类
            is_expanded = bool(filter_text) or cat_index < 3
            cat_state = {"expanded": is_expanded}

            # 分类标题（胶囊，可折叠）
            header = ctk.CTkButton(
                cat_frame, text=f"{'▾' if is_expanded else '▸'} {category} ({len(filtered)})",
                height=28, corner_radius=8, anchor="w",
                fg_color=PANEL, hover_color=SIDEBAR,
                text_color=TEXT, font=("Microsoft YaHei", 11, "bold"))
            header.pack(fill=tk.X, padx=4, pady=2)

            # 命令容器
            cmd_container = ctk.CTkFrame(cat_frame, fg_color=PANEL, corner_radius=8)
            if is_expanded:
                cmd_container.pack(fill=tk.X, padx=4, pady=(0, 4))

            for name, cmd_data in filtered.items():
                self._create_preset_button(cmd_container, name, cmd_data)

            def toggle_container(cf=cmd_container, state=cat_state, h=header,
                                 cat=category, fl=filtered):
                if state["expanded"]:
                    cf.pack_forget()
                    state["expanded"] = False
                    h.configure(text=f"▸ {cat} ({len(fl)})")
                else:
                    cf.pack(fill=tk.X, padx=4, pady=(0, 4))
                    state["expanded"] = True
                    h.configure(text=f"▾ {cat} ({len(fl)})")

            header.configure(command=toggle_container)

    def _create_preset_button(self, parent, name, cmd_data):
        """创建预设命令按钮（点击应用 + 拖放 + hover tooltip）"""
        label_text = cmd_data.get("label", name)
        key_text = cmd_data.get("key", "")
        desc_text = cmd_data.get("description", "")

        btn = ctk.CTkFrame(parent, fg_color=PRESET_BG, corner_radius=8,
                           border_width=1, border_color=BORDER)
        btn.pack(fill=tk.X, padx=2, pady=2)

        display = label_text
        if key_text:
            display += f"  ({key_text})"

        lbl = tk.Label(btn, text=display, bg=PRESET_BG, fg=TEXT,
                       font=("Microsoft YaHei", 11), anchor="w",
                       padx=12, pady=6)
        lbl.pack(side=tk.LEFT, fill=tk.X, expand=True)

        desc_lbl = None
        if desc_text:
            desc_lbl = tk.Label(btn, text=desc_text, bg=PRESET_BG, fg=TEXT_DIM,
                                font=("Microsoft YaHei", 10), anchor="e", padx=10)
            desc_lbl.pack(side=tk.RIGHT)

        preset_info = {"label": label_text, "key": key_text, "description": desc_text}

        def on_press(e, pi=preset_info):
            self._drag_start_x = e.x
            self._drag_start_y = e.y
            self._drag_pending = pi

        def on_motion(e, pi=preset_info):
            if self._drag_pending:
                dx = abs(e.x - self._drag_start_x)
                dy = abs(e.y - self._drag_start_y)
                if dx > 5 or dy > 5:
                    self._start_drag(self._drag_pending, e)
                    self._drag_pending = None

        def on_release(e):
            if self._drag_pending:
                self._apply_preset_to_selected(self._drag_pending)
                self._drag_pending = None

        def on_enter(e):
            btn.configure(fg_color=PRESET_HOVER, border_color=BORDER_LIGHT)
            lbl.configure(bg=PRESET_HOVER)
            if desc_lbl is not None:
                desc_lbl.configure(bg=PRESET_HOVER)

        def on_leave(e):
            btn.configure(fg_color=PRESET_BG, border_color=BORDER)
            lbl.configure(bg=PRESET_BG)
            if desc_lbl is not None:
                desc_lbl.configure(bg=PRESET_BG)

        btn.configure(cursor="hand2")
        bind_widgets = [btn, lbl]
        if desc_lbl is not None:
            bind_widgets.append(desc_lbl)
        for w in bind_widgets:
            w.bind("<Button-1>", on_press)
            w.bind("<B1-Motion>", on_motion)
            w.bind("<ButtonRelease-1>", on_release)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

        # tooltip 提示
        tip_lines = [f"命令: {label_text}"]
        if key_text:
            tip_lines.append(f"快捷键: {key_text}")
        if desc_text:
            tip_lines.append(f"CAD 命令: {desc_text}")
        tip_lines.append("单击: 应用到当前选中扇区")
        tip_lines.append("拖动: 放到圆盘指定扇区")
        _ToolTip(btn, "\n".join(tip_lines))

    def _apply_preset_to_selected(self, preset_info: Dict[str, str]):
        """将预设命令应用到当前选中的扇区"""
        if self._selected_sector is None:
            self.status_label.configure(
                text="请先在左侧圆盘上点击选择一个扇区，再应用命令")
            return

        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        sectors_key = _layer_to_sectors_key(layer)
        sectors = profile.setdefault(sectors_key, {})
        sectors[str(idx)] = preset_info.copy()

        self._set_changed()
        self._updating_detail = True
        self._update_detail_panel()
        self._updating_detail = False
        self._draw_preview()

        label = preset_info.get("label", "")
        layer_name = _layer_display_name(layer)
        self.status_label.configure(
            text=f"已将「{label}」应用到{layer_name}扇区 {idx}")

    # ========== Profile 操作 ==========

    def _add_profile(self):
        """新增 Profile"""
        dialog = _InputDialog(self.root, "新增配置方案", "请输入方案名称:")
        self.root.wait_window(dialog.top)
        name = dialog.result
        if not name:
            return

        if name in self.config.get("profiles", {}):
            _dark_msgbox(self.root, "错误", f"方案「{name}」已存在", "error")
            return

        target = self._ask_target()
        if not target:
            return

        n = self.config.get("settings", {}).get("sector_count", 8)
        sectors = {str(i): {"label": "", "key": "", "description": ""} for i in range(n)}

        self.config.setdefault("profiles", {})[name] = {
            "name": name, "target": target,
            "sectors": sectors, "outer_sectors": {}
        }

        self._set_changed()
        self._refresh_profile_list()
        self._load_profile(name)

    def _copy_profile(self):
        """复制当前 Profile"""
        new_name = f"{self.current_profile_name}-副本"
        dialog = _InputDialog(self.root, "复制配置方案", "请输入新方案名称:", initial=new_name)
        self.root.wait_window(dialog.top)
        name = dialog.result
        if not name:
            return

        if name in self.config.get("profiles", {}):
            _dark_msgbox(self.root, "错误", f"方案「{name}」已存在", "error")
            return

        current = self.config.get("profiles", {}).get(self.current_profile_name, {})
        new_profile = copy.deepcopy(current)
        new_profile["name"] = name
        self.config["profiles"][name] = new_profile

        self._set_changed()
        self._refresh_profile_list()
        self._load_profile(name)

    def _delete_profile(self):
        """删除当前 Profile"""
        profile_names = get_profile_names(self.config)
        if len(profile_names) <= 1:
            _dark_msgbox(self.root, "错误", "至少保留一个配置方案", "error")
            return

        if not _dark_yesno(self.root, "确认", f"确定要删除「{self.current_profile_name}」吗?"):
            return

        del self.config["profiles"][self.current_profile_name]
        remaining = get_profile_names(self.config)
        self.current_profile_name = remaining[0]
        self.config["settings"]["active_profile"] = self.current_profile_name

        self._set_changed()
        self._refresh_profile_list()
        self._load_profile(self.current_profile_name)

    def _rename_profile(self):
        """重命名当前 Profile"""
        dialog = _InputDialog(self.root, "重命名配置方案", "请输入新名称:",
                              initial=self.current_profile_name)
        self.root.wait_window(dialog.top)
        new_name = dialog.result
        if not new_name or new_name == self.current_profile_name:
            return

        if new_name in self.config.get("profiles", {}):
            _dark_msgbox(self.root, "错误", f"方案「{new_name}」已存在", "error")
            return

        profile = self.config["profiles"].pop(self.current_profile_name)
        profile["name"] = new_name
        self.config["profiles"][new_name] = profile

        if self.config.get("settings", {}).get("active_profile") == self.current_profile_name:
            self.config["settings"]["active_profile"] = new_name

        self.current_profile_name = new_name
        self._set_changed()
        self._refresh_profile_list()

    def _ask_target(self) -> Optional[str]:
        """询问 Profile 目标软件"""
        dialog = _TargetDialog(self.root)
        self.root.wait_window(dialog.top)
        return dialog.result

    # ========== 保存/重置 ==========

    def _collect_config(self):
        """从界面收集配置"""
        self.config["settings"]["active_profile"] = self.current_profile_name

    def _save(self) -> bool:
        """保存配置（非模态：成功仅状态栏提示，窗口保持可继续编辑）

        Returns:
            True 表示保存成功。
        """
        self._collect_config()
        if getattr(self, "_autosave_after", None) is not None:
            self.root.after_cancel(self._autosave_after)
            self._autosave_after = None
        if not save_config(self.config):
            _dark_msgbox(self.root, "错误", "保存失败，请检查配置目录是否有写入权限", "error")
            return False
        self._clear_changed()
        now = time.strftime("%H:%M:%S")
        self.status_label.configure(text=f"已保存 {now}")
        if self.on_save:
            self.on_save()
        return True

    def _reset(self):
        """重置为默认配置"""
        if not _dark_yesno(self.root, "确认", "确定要重置所有配置为默认值吗?\n\n这将丢失所有自定义设置。"):
            return
        self.config = _default_config()
        self.current_profile_name = "AutoCAD-常用"
        self._menu_theme_name = "azure"
        self._set_changed()
        self._show_editor()
        self._refresh_profile_list()
        self._load_profile(self.current_profile_name)
        self.status_label.configure(text="已重置为默认配置")

    def _on_close(self):
        """关闭窗口：改动已自动保存，关闭前兜底落盘并通知主程序重载"""
        if getattr(self, "_autosave_after", None) is not None:
            self.root.after_cancel(self._autosave_after)
            self._autosave_after = None
            self._do_autosave()
        if self.on_save:
            self.on_save()
        self.root.destroy()

    def run(self):
        """运行配置界面（嵌入模式由主程序 mainloop 驱动，不阻塞）"""
        if self._embedded:
            return
        self.root.mainloop()


# ========== 对话框 ==========


class _DarkDialog:
    """深色风格对话框（CTkToplevel）"""

    ICON = {"info": "ℹ", "warning": "⚠", "error": "✕", "question": "?"}
    ICON_COLOR = {"info": ACCENT, "warning": WARN,
                  "error": DANGER, "question": ACCENT}

    def __init__(self, parent, title, message, kind="info",
                 buttons=("确定",), default_index=0, cancel_index=None,
                 width=440):
        self.result = None
        self._cancel_index = cancel_index
        self._default_index = default_index

        self.top = ctk.CTkToplevel(parent)
        self.top.title(title)
        self.top.configure(fg_color=BG)
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()
        _enable_dark_titlebar(self.top)

        parent.update_idletasks()
        pw, ph = parent.winfo_width(), parent.winfo_height()
        px, py = parent.winfo_rootx(), parent.winfo_rooty()
        height = 172 + (message.count("\n")) * 6
        self.top.geometry(f"{width}x{height}+{px + (pw - width) // 2}"
                          f"+{py + (ph - height) // 2}")

        top_row = ctk.CTkFrame(self.top, fg_color=BG, corner_radius=0)
        top_row.pack(fill=tk.X, padx=26, pady=(26, 10))
        ctk.CTkLabel(top_row, text=self.ICON.get(kind, "ℹ"),
                     text_color=self.ICON_COLOR.get(kind, ACCENT),
                     font=("Segoe UI Emoji", 18, "bold")).pack(
            side=tk.LEFT, padx=(0, 14))
        ctk.CTkLabel(top_row, text=message, text_color=TEXT,
                     font=_FONT, justify="left", anchor="w",
                     wraplength=width - 90).pack(
            side=tk.LEFT, fill=tk.X, expand=True)

        btn_frame = ctk.CTkFrame(self.top, fg_color=BG, corner_radius=0)
        btn_frame.pack(fill=tk.X, padx=26, pady=(6, 18))
        for i, label in enumerate(buttons):
            ctk.CTkButton(btn_frame, text=label,
                          fg_color=ACCENT if i == default_index else CARD,
                          hover_color=(ACCENT_HOVER if i == default_index
                                       else PRESET_HOVER),
                          border_width=0 if i == default_index else 1,
                          border_color=BORDER_LIGHT if i != default_index else "#000000",
                          text_color="#ffffff" if i == default_index else TEXT,
                          height=30, corner_radius=8, font=_FONT_SMALL,
                          command=lambda i=i: self._choose(i)
                          ).pack(side=tk.RIGHT, padx=(6, 0))

        self.top.bind("<Escape>", lambda e: self._on_cancel())
        self.top.bind("<Return>", lambda e: self._choose(self._default_index))
        self.top.protocol("WM_DELETE_WINDOW", self._on_cancel)

    def _choose(self, index):
        self.result = index
        self.top.destroy()

    def _on_cancel(self):
        if self._cancel_index is not None:
            self._choose(self._cancel_index)
        else:
            self._choose(self._default_index)

    def show(self):
        self.top.wait_window()
        return self.result


def _dark_msgbox(parent, title, message, kind="info"):
    """信息/警告/错误提示框，返回 None"""
    dlg = _DarkDialog(parent, title, message, kind=kind,
                      buttons=("确定",), default_index=0, cancel_index=0)
    dlg.show()


def _dark_yesno(parent, title, message, default=False):
    """是/否确认框，返回 bool"""
    dlg = _DarkDialog(parent, title, message, kind="question",
                      buttons=("否", "是"), default_index=1 if default else 0,
                      cancel_index=0)
    idx = dlg.show()
    return idx == 1


def _dark_yesnocancel(parent, title, message):
    """是/否/取消框，返回 True / False / None"""
    dlg = _DarkDialog(parent, title, message, kind="question",
                      buttons=("取消", "否", "是"), default_index=2,
                      cancel_index=0)
    idx = dlg.show()
    if idx == 2:
        return True
    if idx == 1:
        return False
    return None


class _InputDialog:
    """输入对话框"""

    def __init__(self, parent, title, prompt, initial=""):
        self.result = None

        self.top = ctk.CTkToplevel(parent)
        self.top.title(title)
        self.top.configure(fg_color=BG)
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()
        _enable_dark_titlebar(self.top)
        self.top.geometry("420x220")

        body = ctk.CTkFrame(self.top, fg_color=BG, corner_radius=0)
        body.pack(fill=tk.BOTH, expand=True, padx=26, pady=(26, 18))

        ctk.CTkLabel(body, text=prompt, text_color=TEXT,
                     font=_FONT).pack(pady=(0, 14))

        self.entry = ctk.CTkEntry(body, height=36, corner_radius=8,
                                  fg_color=PANEL, border_color=BORDER,
                                  text_color=TEXT, font=_FONT)
        self.entry.pack(fill=tk.X)
        self.entry.insert(0, initial)
        self.entry.focus_set()

        btn_frame = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        btn_frame.pack(pady=(18, 0))
        ctk.CTkButton(btn_frame, text="确定", height=30, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", font=_FONT_SMALL,
                      command=self._ok).pack(side=tk.LEFT, padx=10)
        ctk.CTkButton(btn_frame, text="取消", height=30, corner_radius=8,
                      fg_color=CARD, hover_color=PRESET_HOVER,
                      border_width=1, border_color=BORDER_LIGHT,
                      text_color=TEXT, font=_FONT_SMALL,
                      command=self._cancel).pack(side=tk.LEFT, padx=10)

        self.top.bind("<Return>", lambda e: self._ok())
        self.top.bind("<Escape>", lambda e: self._cancel())

    def _ok(self):
        self.result = self.entry.get().strip()
        self.top.destroy()

    def _cancel(self):
        self.top.destroy()


class _TargetDialog:
    """目标软件选择对话框"""

    def __init__(self, parent):
        self.result = None

        self.top = ctk.CTkToplevel(parent)
        self.top.title("选择目标软件")
        self.top.configure(fg_color=BG)
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()
        _enable_dark_titlebar(self.top)
        self.top.geometry("380x230")

        body = ctk.CTkFrame(self.top, fg_color=BG, corner_radius=0)
        body.pack(fill=tk.BOTH, expand=True, padx=26, pady=(26, 16))

        ctk.CTkLabel(body, text="选择配置方案适用的 CAD 软件:",
                     text_color=TEXT, font=_FONT).pack(pady=(0, 16))

        btn_frame = ctk.CTkFrame(body, fg_color=BG, corner_radius=0)
        btn_frame.pack(pady=(0, 8))
        ctk.CTkButton(btn_frame, text="AutoCAD", height=32, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", font=_FONT_SMALL,
                      command=lambda: self._select("autocad")
                      ).pack(side=tk.LEFT, padx=15)
        ctk.CTkButton(btn_frame, text="中望CAD", height=32, corner_radius=8,
                      fg_color=ACCENT, hover_color=ACCENT_HOVER,
                      text_color="#ffffff", font=_FONT_SMALL,
                      command=lambda: self._select("zwcad")
                      ).pack(side=tk.LEFT, padx=15)

        ctk.CTkButton(body, text="取消", height=30, corner_radius=8,
                      fg_color=CARD, hover_color=PRESET_HOVER,
                      border_width=1, border_color=BORDER_LIGHT,
                      text_color=TEXT, font=_FONT_SMALL,
                      command=self._cancel).pack(pady=(8, 0))

        self.top.bind("<Escape>", lambda e: self._cancel())

    def _select(self, target):
        self.result = target
        self.top.destroy()

    def _cancel(self):
        self.top.destroy()


def open_config_gui(on_save: Optional[Callable[[], None]] = None,
                    master: Optional[ctk.CTk] = None):
    """打开配置界面（master 提供时嵌入主程序主线程，否则独立窗口）"""
    gui = ConfigGUI(on_save=on_save, master=master)
    gui.run()
