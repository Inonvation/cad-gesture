"""GUI配置界面 - ttkbootstrap 深色主题配置编辑器"""

import math
import copy
import ctypes
import tkinter as tk
from tkinter import messagebox
import ttkbootstrap as ttk
from ttkbootstrap.constants import *
from typing import Dict, Any, Optional, Callable, List, Tuple

from src.config_manager import (
    load_config, save_config, get_active_profile,
    get_profile_names, set_active_profile, _default_config,
    get_preset_commands
)
from src.gesture_engine import calc_sector


# ========== 配色方案 - ttkbootstrap darkly 主题变量 ==========
# 用于 Canvas 和手动配色区域
COLORS = {
    "bg": "#222222",
    "sidebar_bg": "#2a2a2a",
    "panel_bg": "#303030",
    "card_bg": "#3c3c3c",
    "accent": "#375a7f",
    "accent_hover": "#4a7fb5",
    "accent_dim": "#2e4d6e",
    "text": "#ffffff",
    "text_dim": "#999999",
    "text_bright": "#ffffff",
    "border": "#444444",
    "success": "#00bc8c",
    "warning": "#f39c12",
    "danger": "#e74c3c",
    "preset_bg": "#353535",
    "preset_hover": "#454545",
    "inner_sector": "#3c6e91",
    "inner_sector_hover": "#4a8ab5",
    "inner_sector_hl": "#375a7f",
    "outer_sector": "#2e4d6e",
    "outer_sector_hover": "#3c6e91",
    "outer_sector_hl": "#375a7f",
    "dead_zone": "#1a1a1a",
    "selected_border": "#4a7fb5",
    "drag_proxy_bg": "#375a7f",
}


class ConfigGUI:
    """配置界面主类"""

    def __init__(self, on_save: Optional[Callable[[], None]] = None):
        self.on_save = on_save
        self.config = load_config()
        self.current_profile_name = self.config.get("settings", {}).get("active_profile", "AutoCAD-常用")
        self.preset_commands = get_preset_commands()

        # 选中的预设命令
        self._selected_preset: Optional[Dict[str, str]] = None
        # 当前选中的扇区 (layer, index)
        self._selected_sector: Optional[Tuple[str, int]] = None
        # 当前 hover 的扇区 (layer, index)
        self._hovered_sector: Optional[Tuple[str, int]] = None
        # 预览圆盘参数
        self._preview_cx = 0
        self._preview_cy = 0
        self._preview_inner_r = 100
        self._preview_outer_r = 180
        self._preview_dead_r = 30
        self._preview_n = 8
        # 拖放状态
        self._drag_proxy: Optional[tk.Toplevel] = None
        self._drag_preset: Optional[Dict[str, str]] = None
        # hover 节流
        self._hover_after_id: Optional[str] = None
        # 自动保存标志（防止 trace 回调循环）
        self._updating_detail = False

        self.root = ttk.Window(
            title="CAD鼠标手势 - 设置",
            themename="darkly",
            size=(1200, 800),
            minsize=(1000, 700)
        )
        # 防止窗口切换/最小化时闪黑（Windows 特有问题）
        # 设置所有层级的背景色，确保重绘时不会露出黑色
        self.root.configure(bg="#222222")
        self.root.option_add("*background", "#222222")
        self.root.option_add("*foreground", "#ffffff")
        self.root.update_idletasks()
        self._fix_window_flicker()

        # 标记是否有未保存的修改
        self._has_changes = False

        self._setup_styles()
        self._create_widgets()
        self._load_profile(self.current_profile_name)

        # 绑定快捷键
        self.root.bind("<Control-s>", lambda e: self._save())
        self.root.bind("<Escape>", lambda e: self._cancel_drag())

    def _fix_window_flicker(self):
        """修复 Windows 窗口切换/最小化时闪黑问题
        
        原理：用 ctypes 设置窗口类背景刷为深色，这样 Windows 在重绘窗口时
        会用深色填充而不是默认的黑色/白色，避免闪烁。
        """
        try:
            import ctypes
            from ctypes import wintypes

            # 获取窗口句柄
            hwnd = self.root.winfo_id()
            while True:
                parent = ctypes.windll.user32.GetParent(hwnd)
                if parent == 0:
                    break
                hwnd = parent

            # 创建深色画刷 (#222222 = RGB(34, 34, 34))
            dark_color = ctypes.windll.gdi32.CreateSolidBrush(
                ctypes.c_uint32(0x00222222)  # COLORREF 格式: 0x00BBGGRR
            )

            # 设置窗口类背景刷 (GCLP_HBRBACKGROUND = -10)
            GCLP_HBRBACKGROUND = -10
            ctypes.windll.user32.SetClassLongPtrW(hwnd, GCLP_HBRBACKGROUND, dark_color)

            # 强制重绘窗口
            ctypes.windll.user32.InvalidateRect(hwnd, None, True)
            ctypes.windll.user32.UpdateWindow(hwnd)
        except Exception as e:
            print(f"[ConfigGUI] 无法设置窗口背景刷: {e}")

    def _setup_styles(self):
        """设置样式 - ttkbootstrap darkly 主题自动处理大部分样式"""
        # ttkbootstrap darkly 主题已提供深色样式
        # 仅需微调特殊组件
        style = self.root.style
        
        # Treeview 行高
        style.configure("Treeview", rowheight=36, font=("Microsoft YaHei", 10))
        style.configure("Treeview.Heading", font=("Microsoft YaHei", 9, "bold"))

    def _create_widgets(self):
        """创建界面组件"""
        # 主容器
        main_frame = ttk.Frame(self.root)
        main_frame.pack(fill=tk.BOTH, expand=True)

        # ===== 左侧：Profile 导航 =====
        sidebar = ttk.Frame(main_frame, width=240)
        sidebar.pack(side=tk.LEFT, fill=tk.Y)
        sidebar.pack_propagate(False)

        # Logo/标题
        header_frame = ttk.Frame(sidebar)
        header_frame.pack(fill=tk.X, padx=20, pady=(25, 20))

        ttk.Label(header_frame, text="CAD 手势",
                  font=("Microsoft YaHei", 13, "bold")).pack(anchor=tk.W)
        ttk.Label(header_frame, text="配置管理器",
                  bootstyle="secondary").pack(anchor=tk.W, pady=(3, 0))

        # 分隔线
        ttk.Separator(sidebar).pack(fill=tk.X, padx=20, pady=10)

        # Profile 列表标题
        ttk.Label(sidebar, text="配置方案",
                  bootstyle="primary",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor=tk.W, padx=20, pady=(0, 10))

        # Profile 列表
        list_frame = ttk.Frame(sidebar)
        list_frame.pack(fill=tk.BOTH, expand=True, padx=15, pady=(0, 10))

        self.profile_tree = ttk.Treeview(list_frame, show="tree", selectmode="browse")
        tree_scroll = ttk.Scrollbar(list_frame, orient=tk.VERTICAL, command=self.profile_tree.yview)
        self.profile_tree.configure(yscrollcommand=tree_scroll.set)
        self.profile_tree.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)
        tree_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        self.profile_tree.bind("<<TreeviewSelect>>", self._on_tree_select)

        # Profile 操作按钮
        btn_frame = ttk.Frame(sidebar)
        btn_frame.pack(fill=tk.X, padx=15, pady=(0, 15))

        btn_row1 = ttk.Frame(btn_frame)
        btn_row1.pack(fill=tk.X, pady=3)
        ttk.Button(btn_row1, text="新增", bootstyle="outline",
                   command=self._add_profile).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        ttk.Button(btn_row1, text="复制", bootstyle="outline",
                   command=self._copy_profile).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        btn_row2 = ttk.Frame(btn_frame)
        btn_row2.pack(fill=tk.X, pady=3)
        ttk.Button(btn_row2, text="重命名", bootstyle="outline",
                   command=self._rename_profile).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(0, 3))
        ttk.Button(btn_row2, text="删除", bootstyle="outline danger",
                   command=self._delete_profile).pack(side=tk.LEFT, fill=tk.X, expand=True, padx=(3, 0))

        # 分隔线
        ttk.Separator(sidebar).pack(fill=tk.X, padx=20, pady=10)

        # 全局设置区
        ttk.Label(sidebar, text="设置",
                  bootstyle="primary",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor=tk.W, padx=20, pady=(0, 10))

        # 启动时打开配置
        self.open_config_var = tk.BooleanVar(
            value=self.config.get("settings", {}).get("open_config_on_start", True))
        ttk.Checkbutton(sidebar, text="启动时打开此界面",
                        variable=self.open_config_var,
                        command=self._on_setting_change).pack(anchor=tk.W, padx=25, pady=4)

        # 自动切换Profile
        self.auto_switch_var = tk.BooleanVar(
            value=self.config.get("settings", {}).get("auto_switch_profile", True))
        ttk.Checkbutton(sidebar, text="根据 CAD 窗口自动切换",
                        variable=self.auto_switch_var,
                        command=self._on_setting_change).pack(anchor=tk.W, padx=25, pady=4)

        # ===== 右侧：内容区域 =====
        content = ttk.Frame(main_frame)
        content.pack(side=tk.LEFT, fill=tk.BOTH, expand=True, padx=20, pady=20)

        # 上部：圆盘预览 + 详情编辑
        top_frame = ttk.Frame(content)
        top_frame.pack(fill=tk.X, pady=(0, 20))

        # 圆盘预览区（无边框，背景融入窗口）
        preview_frame = ttk.Frame(top_frame)
        preview_frame.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 提示文字
        ttk.Label(preview_frame, text="圆盘预览",
                  bootstyle="secondary",
                  font=("Microsoft YaHei", 9, "bold")).pack(anchor=tk.W, pady=(0, 2))
        ttk.Label(preview_frame, text="点击扇区编辑 | 拖放预设命令到扇区",
                  bootstyle="secondary").pack(anchor=tk.W, pady=(0, 8))

        self.preview_size = 420
        self.preview_canvas = tk.Canvas(
            preview_frame, width=self.preview_size, height=self.preview_size,
            bg=COLORS["bg"], highlightthickness=0, borderwidth=0)
        self.preview_canvas.pack(expand=True)
        self.preview_canvas.bind("<Button-1>", self._on_canvas_click)
        self.preview_canvas.bind("<Double-Button-1>", self._on_canvas_double_click)
        self.preview_canvas.bind("<Motion>", self._on_canvas_motion)
        self.preview_canvas.bind("<Leave>", self._on_canvas_leave)

        # 右侧：扇区详情编辑
        detail_frame = ttk.Labelframe(top_frame, text=" 扇区编辑 ", padding=20, width=320)
        detail_frame.pack(side=tk.RIGHT, fill=tk.Y, padx=(20, 0))
        detail_frame.pack_propagate(False)

        # 当前选中提示
        self.selected_info = ttk.Label(detail_frame, text="点击左侧圆盘选择扇区",
                                        bootstyle="secondary", wraplength=280)
        self.selected_info.pack(anchor=tk.W, pady=(0, 20))

        # 编辑表单
        form_frame = ttk.Frame(detail_frame)
        form_frame.pack(fill=tk.X)

        # 扇区层
        ttk.Label(form_frame, text="所在层",
                  bootstyle="info",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.layer_label = ttk.Label(form_frame, text="未选择",
                                      bootstyle="primary",
                                      font=("Microsoft YaHei", 10, "bold"))
        self.layer_label.pack(anchor=tk.W, pady=(0, 15))

        # 标签
        ttk.Label(form_frame, text="显示名称",
                  bootstyle="info",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.detail_label_var = tk.StringVar()
        self.detail_label_entry = ttk.Entry(form_frame, textvariable=self.detail_label_var,
                                font=("Microsoft YaHei", 11))
        self.detail_label_entry.pack(fill=tk.X, pady=(0, 15))

        # 快捷键
        ttk.Label(form_frame, text="快捷键",
                  bootstyle="info",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.detail_key_var = tk.StringVar()
        self.detail_key_entry = ttk.Entry(form_frame, textvariable=self.detail_key_var,
                              font=("Microsoft YaHei", 11))
        self.detail_key_entry.pack(fill=tk.X, pady=(0, 15))

        # CAD命令
        ttk.Label(form_frame, text="CAD 命令",
                  bootstyle="info",
                  font=("Microsoft YaHei", 10, "bold")).pack(anchor=tk.W, pady=(0, 5))
        self.detail_desc_var = tk.StringVar()
        self.detail_desc_entry = ttk.Entry(form_frame, textvariable=self.detail_desc_var,
                               font=("Microsoft YaHei", 11))
        self.detail_desc_entry.pack(fill=tk.X, pady=(0, 20))

        # 自动保存：监听变量变化
        self.detail_label_var.trace_add("write", self._on_detail_change)
        self.detail_key_var.trace_add("write", self._on_detail_change)
        self.detail_desc_var.trace_add("write", self._on_detail_change)

        # 操作按钮
        btn_frame_detail = ttk.Frame(detail_frame)
        btn_frame_detail.pack(fill=tk.X, pady=(0, 10))

        ttk.Button(btn_frame_detail, text="清空扇区", bootstyle="outline danger",
                   command=self._clear_sector).pack(fill=tk.X)

        # 下部：预设命令库
        preset_frame = ttk.Labelframe(content, text=" 预设命令库 ", padding=15)
        preset_frame.pack(fill=tk.BOTH, expand=True)

        # 搜索框
        search_frame = ttk.Frame(preset_frame)
        search_frame.pack(fill=tk.X, pady=(0, 10))

        self.search_var = tk.StringVar()
        self.search_var.trace_add("write", self._on_search_change)
        search_entry = ttk.Entry(search_frame, textvariable=self.search_var,
                                 font=("Microsoft YaHei", 10))
        search_entry.pack(fill=tk.X)
        self._add_placeholder(search_entry, "搜索命令名称或快捷键...")

        # 预设命令滚动区域（只在本区域绑定滚轮）
        preset_canvas = tk.Canvas(preset_frame, bg=COLORS["panel_bg"],
                                  highlightthickness=0, height=200)
        self._preset_canvas = preset_canvas
        preset_scroll = ttk.Scrollbar(preset_frame, orient=tk.VERTICAL,
                                       command=preset_canvas.yview)
        self.preset_container = ttk.Frame(preset_canvas)

        self.preset_container.bind(
            "<Configure>",
            lambda e: preset_canvas.configure(scrollregion=preset_canvas.bbox("all"))
        )
        preset_canvas.create_window((0, 0), window=self.preset_container, anchor="nw")
        preset_canvas.configure(yscrollcommand=preset_scroll.set)

        preset_scroll.pack(side=tk.RIGHT, fill=tk.Y)
        preset_canvas.pack(side=tk.LEFT, fill=tk.BOTH, expand=True)

        # 只在预设区域绑定滚轮
        preset_canvas.bind("<MouseWheel>",
                           lambda e: preset_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))
        self.preset_container.bind("<MouseWheel>",
                                    lambda e: preset_canvas.yview_scroll(int(-1 * (e.delta / 120)), "units"))

        self._populate_presets()

        # ===== 底部：状态栏 =====
        bottom_frame = ttk.Frame(content)
        bottom_frame.pack(fill=tk.X, pady=(20, 0))

        # 左侧：状态提示
        self.status_label = ttk.Label(bottom_frame, text="点击圆盘扇区可直接编辑命令配置",
                                       bootstyle="secondary")
        self.status_label.pack(side=tk.LEFT)

        # 右侧：操作按钮
        action_frame = ttk.Frame(bottom_frame)
        action_frame.pack(side=tk.RIGHT)

        ttk.Button(action_frame, text="重置默认", bootstyle="outline danger",
                   command=self._reset).pack(side=tk.LEFT, padx=(0, 15))

        self.save_btn = ttk.Button(action_frame, text="保存并关闭 (Ctrl+S)", bootstyle="success",
                                    command=self._save)
        self.save_btn.pack(side=tk.LEFT)

        # 初始化 Profile 树
        self._refresh_profile_tree()

    def _add_placeholder(self, entry, placeholder):
        """添加输入框占位符"""
        def on_focus_in(event):
            if entry.get() == placeholder:
                entry.delete(0, tk.END)
                entry.configure(foreground=COLORS["text"])

        def on_focus_out(event):
            if not entry.get():
                entry.insert(0, placeholder)
                entry.configure(foreground=COLORS["text_dim"])

        entry.insert(0, placeholder)
        entry.configure(foreground=COLORS["text_dim"])
        entry.bind("<FocusIn>", on_focus_in)
        entry.bind("<FocusOut>", on_focus_out)

    def _on_setting_change(self):
        """设置改变"""
        self._has_changes = True
        self.config.setdefault("settings", {})["open_config_on_start"] = self.open_config_var.get()
        self.config["settings"]["auto_switch_profile"] = self.auto_switch_var.get()

    # ========== Profile 树管理 ==========

    def _refresh_profile_tree(self):
        """刷新 Profile 树"""
        self.profile_tree.delete(*self.profile_tree.get_children())

        # 按 CAD 软件分组
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

        if autocad_profiles:
            autocad_node = self.profile_tree.insert("", tk.END, text="AutoCAD", open=True)
            for name, display in autocad_profiles:
                self.profile_tree.insert(autocad_node, tk.END, text=display, values=(name,))

        if zwcad_profiles:
            zwcad_node = self.profile_tree.insert("", tk.END, text="中望CAD", open=True)
            for name, display in zwcad_profiles:
                self.profile_tree.insert(zwcad_node, tk.END, text=display, values=(name,))

        if other_profiles:
            other_node = self.profile_tree.insert("", tk.END, text="其他", open=True)
            for name, display in other_profiles:
                self.profile_tree.insert(other_node, tk.END, text=display, values=(name,))

        # 选中当前活跃 profile
        for parent in self.profile_tree.get_children():
            for child in self.profile_tree.get_children(parent):
                values = self.profile_tree.item(child, "values")
                if values and values[0] == self.current_profile_name:
                    self.profile_tree.selection_set(child)
                    self.profile_tree.see(child)
                    break

    def _on_tree_select(self, event):
        """Profile 树选择事件"""
        selection = self.profile_tree.selection()
        if not selection:
            return
        item = self.profile_tree.item(selection[0])
        values = item.get("values", [])
        if values:
            profile_name = values[0]
            self._load_profile(profile_name)

    def _load_profile(self, profile_name: str):
        """加载 Profile"""
        self.current_profile_name = profile_name
        self._selected_sector = None
        self._hovered_sector = None
        self._selected_preset = None
        self._updating_detail = True
        self._update_detail_panel()
        self._updating_detail = False
        self._draw_preview()

        # 获取 Profile 显示名
        profile = self.config.get("profiles", {}).get(profile_name, {})
        display_name = profile.get("name", profile_name)
        self.status_label.config(text=f"当前方案: {display_name}")

    # ========== 圆盘绘制 ==========

    def _draw_preview(self):
        """绘制圆盘预览"""
        self.preview_canvas.delete("all")

        cx = self.preview_size // 2
        cy = self.preview_size // 2
        inner_r = 85
        outer_r = 160
        dead_r = 28

        self._preview_cx = cx
        self._preview_cy = cy
        self._preview_inner_r = inner_r
        self._preview_outer_r = outer_r
        self._preview_dead_r = dead_r

        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        n = self.config.get("settings", {}).get("sector_count", 8)
        self._preview_n = n

        # 绘制外层扇区
        for i in range(n):
            start_angle = i * 360 / n - 90 - 360 / (2 * n)
            extent = 360 / n
            is_selected = self._selected_sector == ("outer", i)
            is_hovered = self._hovered_sector == ("outer", i)

            if is_selected:
                fill_color = COLORS["outer_sector_hl"]
                outline_color = COLORS["selected_border"]
                outline_width = 2
            elif is_hovered:
                fill_color = COLORS["outer_sector_hover"]
                outline_color = COLORS["accent_dim"]
                outline_width = 1
            else:
                fill_color = COLORS["outer_sector"]
                outline_color = COLORS["border"]
                outline_width = 1

            self.preview_canvas.create_arc(
                cx - outer_r, cy - outer_r, cx + outer_r, cy + outer_r,
                start=start_angle, extent=extent, fill=fill_color,
                outline=outline_color, width=outline_width)

            # 外层标签
            mid_angle = math.radians(i * 360 / n - 90)
            label_r = (inner_r + outer_r) / 2
            lx = cx + label_r * math.cos(mid_angle)
            ly = cy + label_r * math.sin(mid_angle)

            cfg = profile.get("outer_sectors", {}).get(str(i), {})
            label = cfg.get("label", "")
            if label:
                text_fill = COLORS["text_bright"] if (is_selected or is_hovered) else COLORS["text"]
                self.preview_canvas.create_text(lx, ly, text=label, fill=text_fill,
                                                font=("Microsoft YaHei", 9), anchor=tk.CENTER)

        # 绘制内层扇区
        for i in range(n):
            start_angle = i * 360 / n - 90 - 360 / (2 * n)
            extent = 360 / n
            is_selected = self._selected_sector == ("inner", i)
            is_hovered = self._hovered_sector == ("inner", i)

            if is_selected:
                fill_color = COLORS["inner_sector_hl"]
                outline_color = COLORS["selected_border"]
                outline_width = 2
            elif is_hovered:
                fill_color = COLORS["inner_sector_hover"]
                outline_color = COLORS["accent_dim"]
                outline_width = 1
            else:
                fill_color = COLORS["inner_sector"]
                outline_color = COLORS["border"]
                outline_width = 1

            self.preview_canvas.create_arc(
                cx - inner_r, cy - inner_r, cx + inner_r, cy + inner_r,
                start=start_angle, extent=extent, fill=fill_color,
                outline=outline_color, width=outline_width)

            # 内层标签
            mid_angle = math.radians(i * 360 / n - 90)
            label_r = (dead_r + inner_r) / 2
            lx = cx + label_r * math.cos(mid_angle)
            ly = cy + label_r * math.sin(mid_angle)

            cfg = profile.get("sectors", {}).get(str(i), {})
            label = cfg.get("label", "")
            if label:
                text_fill = COLORS["text_bright"] if (is_selected or is_hovered) else COLORS["text"]
                self.preview_canvas.create_text(lx, ly, text=label, fill=text_fill,
                                                font=("Microsoft YaHei", 8, "bold"), anchor=tk.CENTER)

        # 中心死区 — 显示当前选中扇区的信息
        self.preview_canvas.create_oval(
            cx - dead_r, cy - dead_r, cx + dead_r, cy + dead_r,
            fill=COLORS["dead_zone"], outline=COLORS["border"], width=1)

        if self._selected_sector:
            layer, idx = self._selected_sector
            sectors_key = "outer_sectors" if layer == "outer" else "sectors"
            cfg = profile.get(sectors_key, {}).get(str(idx), {})
            center_text = cfg.get("label", "")
            if not center_text:
                center_text = f"扇区{idx}"
        else:
            center_text = "释放"
        self.preview_canvas.create_text(cx, cy, text=center_text, fill=COLORS["text_dim"],
                                        font=("Microsoft YaHei", 8), anchor=tk.CENTER)

    def _calc_sector_at(self, canvas_x: int, canvas_y: int) -> Optional[Tuple[str, int]]:
        """计算 canvas 坐标所在的扇区，返回 (layer, index) 或 None"""
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
        return None

    def _on_canvas_motion(self, event):
        """圆盘 hover 事件（节流到 16ms）"""
        # 立即捕获坐标（event 对象可能被后续事件覆盖）
        ex, ey = event.x, event.y
        if self._hover_after_id is not None:
            return  # 已有待处理的更新

        def update():
            self._hover_after_id = None
            x, y = self.preview_canvas.canvasx(ex), self.preview_canvas.canvasy(ey)
            new_hover = self._calc_sector_at(x, y)
            if new_hover != self._hovered_sector:
                self._hovered_sector = new_hover
                self._draw_preview()
                # 更新光标
                if new_hover:
                    self.preview_canvas.config(cursor="hand2")
                else:
                    self.preview_canvas.config(cursor="")

        self._hover_after_id = self.root.after(16, update)

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

        layer_name = "外层" if sector[0] == "outer" else "内层"
        self.status_label.config(text=f"已选择{layer_name}扇区 {sector[1]}，可编辑或拖放预设命令")

    def _on_canvas_double_click(self, event):
        """双击圆盘扇区 → 聚焦到编辑面板"""
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
            self.layer_label.config(text="未选择")
            self.detail_label_var.set("")
            self.detail_key_var.set("")
            self.detail_desc_var.set("")
            self.selected_info.config(text="点击左侧圆盘选择扇区")
            return

        layer, idx = self._selected_sector
        layer_name = "外层" if layer == "outer" else "内层"
        self.layer_label.config(text=f"{layer_name} - 扇区 {idx}")
        self.selected_info.config(text=f"正在编辑: {layer_name}扇区 {idx}")

        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        sectors_key = "outer_sectors" if layer == "outer" else "sectors"
        cfg = profile.get(sectors_key, {}).get(str(idx), {})

        self.detail_label_var.set(cfg.get("label", ""))
        self.detail_key_var.set(cfg.get("key", ""))
        self.detail_desc_var.set(cfg.get("description", ""))

    def _on_detail_change(self, *args):
        """编辑框内容变化时自动保存到内存"""
        if self._updating_detail:
            return
        if self._selected_sector is None:
            return

        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        sectors_key = "outer_sectors" if layer == "outer" else "sectors"
        sectors = profile.setdefault(sectors_key, {})

        label_val = self.detail_label_var.get().strip()
        key_val = self.detail_key_var.get().strip()
        desc_val = self.detail_desc_var.get().strip()

        sectors[str(idx)] = {
            "label": label_val,
            "key": key_val,
            "description": desc_val
        }

        self._has_changes = True
        self._draw_preview()

    def _clear_sector(self):
        """清空扇区"""
        if self._selected_sector is None:
            messagebox.showwarning("提示", "请先点击圆盘选择一个扇区")
            return

        layer, idx = self._selected_sector
        profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
        sectors_key = "outer_sectors" if layer == "outer" else "sectors"
        sectors = profile.get(sectors_key, {})

        if str(idx) in sectors:
            del sectors[str(idx)]
            self._has_changes = True
            self._updating_detail = True
            self._update_detail_panel()
            self._updating_detail = False
            self._draw_preview()
            self.status_label.config(text=f"已清空扇区 {idx}")

    # ========== 拖放系统 ==========

    def _start_drag(self, preset_info: Dict[str, str], event):
        """开始拖放：创建半透明代理窗口"""
        self._drag_preset = preset_info

        # 创建拖动代理
        proxy = tk.Toplevel(self.root)
        proxy.overrideredirect(True)
        proxy.attributes("-topmost", True)
        proxy.attributes("-alpha", 0.8)
        proxy.configure(bg=COLORS["drag_proxy_bg"])

        # Windows: 让代理窗口穿透鼠标事件（不拦截 canvas hover）
        try:
            # 向上遍历找到真正的顶层窗口 HWND
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
        lbl = tk.Label(proxy, text=label_text, bg=COLORS["drag_proxy_bg"],
                       fg=COLORS["text_bright"], font=("Microsoft YaHei", 10, "bold"),
                       padx=12, pady=6)
        lbl.pack()

        # 获取屏幕坐标（偏移 40px 避免代理挡住光标）
        screen_x = event.x_root
        screen_y = event.y_root
        proxy.geometry(f"+{screen_x + 10}+{screen_y + 10}")

        self._drag_proxy = proxy

        # 绑定全局拖动和释放（用 bind_all 确保跨 widget 捕获）
        self.root.bind_all("<B1-Motion>", self._on_drag_motion)
        self.root.bind_all("<ButtonRelease-1>", self._on_drag_release)

    def _on_drag_motion(self, event):
        """拖动中：更新代理位置，检测圆盘 hover"""
        if not self._drag_proxy:
            return
        self._drag_proxy.geometry(f"+{event.x_root + 10}+{event.y_root + 10}")

        # 检测是否在圆盘上方
        canvas_widget = self.preview_canvas
        canvas_x = canvas_widget.winfo_rootx()
        canvas_y = canvas_widget.winfo_rooty()
        rel_x = event.x_root - canvas_x
        rel_y = event.y_root - canvas_y

        # 用 canvasx/canvasy 转换（兼容 scrollregion）
        cx = canvas_widget.canvasx(rel_x)
        cy = canvas_widget.canvasy(rel_y)

        # 调试：显示坐标到状态栏
        self.status_label.config(
            text=f"拖动: x_root={event.x_root} y_root={event.y_root} "
                 f"canvas@=({canvas_x},{canvas_y}) rel=({rel_x},{rel_y}) "
                 f"canvas=({cx:.0f},{cy:.0f})")

        # 检查是否在 canvas 范围内
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
        """释放：检测是否在圆盘扇区内，应用命令"""
        # 解绑全局事件
        self.root.unbind_all("<B1-Motion>")
        self.root.unbind_all("<ButtonRelease-1>")

        # 销毁代理
        if self._drag_proxy:
            self._drag_proxy.destroy()
            self._drag_proxy = None

        # 检测释放位置
        canvas_widget = self.preview_canvas
        canvas_x = canvas_widget.winfo_rootx()
        canvas_y = canvas_widget.winfo_rooty()
        rel_x = event.x_root - canvas_x
        rel_y = event.y_root - canvas_y

        # 用 canvasx/canvasy 转换（兼容 scrollregion）
        cx = canvas_widget.canvasx(rel_x)
        cy = canvas_widget.canvasy(rel_y)

        # 检查是否在 canvas 范围内
        if 0 <= cx <= self.preview_size and 0 <= cy <= self.preview_size:
            sector = self._calc_sector_at(cx, cy)
            if sector and self._drag_preset:
                # 应用命令到扇区
                layer, idx = sector
                profile = self.config.get("profiles", {}).get(self.current_profile_name, {})
                sectors_key = "outer_sectors" if layer == "outer" else "sectors"
                sectors = profile.setdefault(sectors_key, {})
                sectors[str(idx)] = self._drag_preset.copy()

                self._selected_sector = sector
                self._has_changes = True
                self._updating_detail = True
                self._update_detail_panel()
                self._updating_detail = False
                self._draw_preview()

                label = self._drag_preset.get("label", "")
                layer_name = "外层" if layer == "outer" else "内层"
                self.status_label.config(text=f"已将「{label}」放置到{layer_name}扇区 {idx}")

        self._drag_preset = None
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
        self._hovered_sector = None
        self._draw_preview()

    # ========== 预设命令库 ==========

    def _populate_presets(self, filter_text: str = ""):
        """填充预设命令库（垂直布局，可折叠）"""
        for widget in self.preset_container.winfo_children():
            widget.destroy()

        filter_text = filter_text.lower().strip()

        for category, commands in self.preset_commands.items():
            # 过滤命令
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
            cat_frame = tk.Frame(self.preset_container, bg=COLORS["card_bg"])
            cat_frame.pack(fill=tk.X, padx=3, pady=3)

            # 分类标题（可折叠）
            is_expanded = not bool(filter_text)  # 搜索时全部展开
            cat_state = {"expanded": is_expanded}

            header = tk.Frame(cat_frame, bg=COLORS["card_bg"], cursor="hand2")
            header.pack(fill=tk.X)

            arrow_text = "\u25bc" if is_expanded else "\u25b6"
            arrow_lbl = tk.Label(header, text=arrow_text, bg=COLORS["card_bg"],
                                 fg=COLORS["text_dim"], font=("Microsoft YaHei", 8),
                                 width=2)
            arrow_lbl.pack(side=tk.LEFT, padx=(8, 0))

            count = len(filtered)
            title_lbl = tk.Label(header, text=f"{category} ({count})", bg=COLORS["card_bg"],
                                 fg=COLORS["accent"], font=("Microsoft YaHei", 9, "bold"),
                                 padx=6, pady=6)
            title_lbl.pack(side=tk.LEFT)

            # 命令容器
            cmd_container = tk.Frame(cat_frame, bg=COLORS["panel_bg"])

            if is_expanded:
                cmd_container.pack(fill=tk.X)

            # 命令网格（4列）
            col = 0
            row_frame = None
            for name, cmd_data in filtered.items():
                if col == 0:
                    row_frame = tk.Frame(cmd_container, bg=COLORS["panel_bg"])
                    row_frame.pack(fill=tk.X, padx=3, pady=1)

                self._create_preset_button_grid(row_frame, name, cmd_data)
                col = (col + 1) % 4

            # 折叠/展开切换
            def toggle_container(cf=cmd_container, state=cat_state, al=arrow_lbl):
                if state["expanded"]:
                    cf.pack_forget()
                    state["expanded"] = False
                    al.config(text="\u25b6")
                else:
                    cf.pack(fill=tk.X)
                    state["expanded"] = True
                    al.config(text="\u25bc")

            for w in [header, arrow_lbl, title_lbl]:
                w.bind("<Button-1>", lambda e: toggle_container())

    def _create_preset_button_grid(self, parent, name, cmd_data):
        """创建网格布局的预设命令按钮"""
        label_text = cmd_data.get("label", name)
        key_text = cmd_data.get("key", "")
        desc_text = cmd_data.get("description", "")

        btn = tk.Frame(parent, bg=COLORS["preset_bg"], cursor="hand2", padx=6, pady=4)
        btn.pack(side=tk.LEFT, fill=tk.X, expand=True, padx=2, pady=2)

        # 显示标签 + 快捷键
        display = label_text
        if key_text:
            display += f" ({key_text})"

        lbl = tk.Label(btn, text=display, bg=COLORS["preset_bg"],
                       fg=COLORS["text"], font=("Microsoft YaHei", 8),
                       anchor=tk.W, width=14)
        lbl.pack(fill=tk.X)

        preset_info = {"label": label_text, "key": key_text, "description": desc_text}

        def on_press(e, pi=preset_info):
            self._start_drag(pi, e)

        def on_enter(e, f=btn, l=lbl):
            f.config(bg=COLORS["preset_hover"])
            l.config(bg=COLORS["preset_hover"])

        def on_leave(e, f=btn, l=lbl):
            f.config(bg=COLORS["preset_bg"])
            l.config(bg=COLORS["preset_bg"])

        for w in [btn, lbl]:
            w.bind("<Button-1>", on_press)
            w.bind("<Enter>", on_enter)
            w.bind("<Leave>", on_leave)

    def _on_search_change(self, *args):
        """搜索框内容变化时过滤预设命令"""
        if not hasattr(self, "preset_container"):
            return
        val = self.search_var.get()
        if val == "搜索命令名称或快捷键...":
            self._populate_presets("")
        else:
            self._populate_presets(val)

    # ========== Profile 操作 ==========

    def _add_profile(self):
        """新增 Profile"""
        dialog = _InputDialog(self.root, "新增配置方案", "请输入方案名称:")
        self.root.wait_window(dialog.top)
        name = dialog.result
        if not name:
            return

        if name in self.config.get("profiles", {}):
            messagebox.showerror("错误", f"方案「{name}」已存在")
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

        self._has_changes = True
        self._refresh_profile_tree()
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
            messagebox.showerror("错误", f"方案「{name}」已存在")
            return

        current = self.config.get("profiles", {}).get(self.current_profile_name, {})
        new_profile = copy.deepcopy(current)
        new_profile["name"] = name
        self.config["profiles"][name] = new_profile

        self._has_changes = True
        self._refresh_profile_tree()
        self._load_profile(name)

    def _delete_profile(self):
        """删除当前 Profile"""
        profile_names = get_profile_names(self.config)
        if len(profile_names) <= 1:
            messagebox.showerror("错误", "至少保留一个配置方案")
            return

        if not messagebox.askyesno("确认", f"确定要删除「{self.current_profile_name}」吗?"):
            return

        del self.config["profiles"][self.current_profile_name]
        remaining = get_profile_names(self.config)
        self.current_profile_name = remaining[0]
        self.config["settings"]["active_profile"] = self.current_profile_name

        self._has_changes = True
        self._refresh_profile_tree()
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
            messagebox.showerror("错误", f"方案「{new_name}」已存在")
            return

        profile = self.config["profiles"].pop(self.current_profile_name)
        profile["name"] = new_name
        self.config["profiles"][new_name] = profile

        if self.config.get("settings", {}).get("active_profile") == self.current_profile_name:
            self.config["settings"]["active_profile"] = new_name

        self.current_profile_name = new_name
        self._has_changes = True
        self._refresh_profile_tree()

    def _ask_target(self) -> Optional[str]:
        """询问 Profile 目标软件"""
        dialog = _TargetDialog(self.root)
        self.root.wait_window(dialog.top)
        return dialog.result

    # ========== 保存/重置 ==========

    def _collect_config(self):
        """从界面收集配置"""
        self.config["settings"]["active_profile"] = self.current_profile_name
        self.config["settings"]["auto_switch_profile"] = self.auto_switch_var.get()
        self.config["settings"]["open_config_on_start"] = self.open_config_var.get()

    def _save(self):
        """保存配置"""
        self._collect_config()
        save_config(self.config)
        self._has_changes = False
        messagebox.showinfo("成功", "配置已保存！")
        if self.on_save:
            self.on_save()
        self.root.destroy()

    def _reset(self):
        """重置为默认配置"""
        if not messagebox.askyesno("确认", "确定要重置所有配置为默认值吗?\n\n这将丢失所有自定义设置。"):
            return
        self.config = _default_config()
        self.current_profile_name = "AutoCAD-常用"
        self.open_config_var.set(True)
        self.auto_switch_var.set(True)
        self._has_changes = True
        self._refresh_profile_tree()
        self._load_profile(self.current_profile_name)
        self.status_label.config(text="已重置为默认配置")

    def run(self):
        """运行配置界面"""
        self.root.mainloop()


# ========== 辅助类 ==========


class _InputDialog:
    """输入对话框"""

    def __init__(self, parent, title, prompt, initial=""):
        self.result = None

        self.top = ttk.Toplevel(parent)
        self.top.title(title)
        self.top.geometry("420x180")
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()

        ttk.Label(self.top, text=prompt,
                  font=("Microsoft YaHei", 11)).pack(pady=(25, 10))

        self.entry = ttk.Entry(self.top, width=38, font=("Microsoft YaHei", 11))
        self.entry.pack(pady=5)
        self.entry.insert(0, initial)
        self.entry.select_range(0, tk.END)
        self.entry.focus_set()

        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(pady=20)

        ttk.Button(btn_frame, text="确定", bootstyle="primary",
                   command=self._ok).pack(side=tk.LEFT, padx=10)
        ttk.Button(btn_frame, text="取消", bootstyle="outline",
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

        self.top = ttk.Toplevel(parent)
        self.top.title("选择目标软件")
        self.top.geometry("380x200")
        self.top.resizable(False, False)
        self.top.transient(parent)
        self.top.grab_set()

        ttk.Label(self.top, text="选择配置方案适用的 CAD 软件:",
                  font=("Microsoft YaHei", 11)).pack(pady=(25, 15))

        btn_frame = ttk.Frame(self.top)
        btn_frame.pack(pady=10)

        ttk.Button(btn_frame, text="AutoCAD", bootstyle="primary",
                   width=15,
                   command=lambda: self._select("autocad")).pack(side=tk.LEFT, padx=15)
        ttk.Button(btn_frame, text="中望CAD", bootstyle="info",
                   width=15,
                   command=lambda: self._select("zwcad")).pack(side=tk.LEFT, padx=15)

        ttk.Button(self.top, text="取消", bootstyle="outline",
                   command=self._cancel).pack(pady=15)

        self.top.bind("<Escape>", lambda e: self._cancel())

    def _select(self, target):
        self.result = target
        self.top.destroy()

    def _cancel(self):
        self.top.destroy()


def open_config_gui(on_save: Optional[Callable[[], None]] = None):
    """打开配置界面"""
    gui = ConfigGUI(on_save=on_save)
    gui.run()
