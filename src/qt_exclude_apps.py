# -*- coding: utf-8 -*-
"""「不弹圆盘的应用」名单管理控件（对齐 Quicker 的禁用应用列表交互）

存储格式不变：settings.gesture_exclude_apps 仍是逗号分隔 exe 关键字字符串，
gesture_engine.parse_exclude_apps / match_exclude_exe 的匹配逻辑不受影响；
本模块只负责设置页里的编辑体验：
- 逐条列表（行内 tooltip 说明匹配语义），空名单显示占位提示，每行 ✕ 删除
- 「添加应用…」对话框：实时归一化校验（空名 / 重复时禁用确定键），回车提交
- 「拾取窗口」：按住拖到目标窗口上松手，读取该窗口所属进程的 exe 加入名单
  （Qt 按住期间鼠标事件持续投给按钮，无需全局钩子）
- 添加 / 重复 / 未能识别等操作结果以浮层提示显示在列表框内，4 秒自动消失
"""

import os
import re

from PySide6.QtCore import QPoint, QSize, Qt, QTimer, Signal
from PySide6.QtGui import QCursor
from PySide6.QtWidgets import (QApplication, QDialog, QFrame, QHBoxLayout,
                               QLabel, QLineEdit, QListWidget, QListWidgetItem,
                               QPushButton, QVBoxLayout, QWidget)

from src.i18n import T
from src.theme import get_ui

IS_WINDOWS = os.name == "nt"
if IS_WINDOWS:
    import ctypes
    import ctypes.wintypes as wintypes

    _user32 = ctypes.windll.user32
    _kernel32 = ctypes.windll.kernel32
    # 64 位下 HWND/HANDLE 返回值必须显式声明，默认 c_int 会截断指针
    _user32.GetCursorPos.argtypes = [ctypes.POINTER(wintypes.POINT)]
    _user32.GetCursorPos.restype = wintypes.BOOL
    _user32.WindowFromPoint.argtypes = [wintypes.POINT]
    _user32.WindowFromPoint.restype = wintypes.HWND
    _user32.GetAncestor.argtypes = [wintypes.HWND, ctypes.c_uint]
    _user32.GetAncestor.restype = wintypes.HWND
    _user32.GetWindowThreadProcessId.argtypes = [
        wintypes.HWND, ctypes.POINTER(wintypes.DWORD)]
    _user32.GetWindowThreadProcessId.restype = wintypes.DWORD
    _kernel32.OpenProcess.argtypes = [wintypes.DWORD, wintypes.BOOL,
                                      wintypes.DWORD]
    _kernel32.OpenProcess.restype = wintypes.HANDLE
    _kernel32.QueryFullProcessImageNameW.argtypes = [
        wintypes.HANDLE, wintypes.DWORD, wintypes.LPWSTR,
        ctypes.POINTER(wintypes.DWORD)]
    _kernel32.QueryFullProcessImageNameW.restype = wintypes.BOOL
    _kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
    _kernel32.CloseHandle.restype = wintypes.BOOL

_GA_ROOT = 2
_PROCESS_QUERY_LIMITED_INFORMATION = 0x1000

_TOAST_MS = 4000   # 操作反馈浮层的停留时长


# ---- 纯函数（可单测） ----

def parse_entries(text) -> list:
    """逗号/分号/空白分隔字符串 → 去空、小写、去重（保持顺序）的条目列表"""
    seen, out = set(), []
    for x in re.split(r"[,，;；\s]+", str(text or "")):
        x = x.strip().lower()
        if x and x not in seen:
            seen.add(x)
            out.append(x)
    return out


def join_entries(entries) -> str:
    """条目列表 → 存储用的逗号分隔字符串"""
    return ",".join(entries)


def normalize_entry(name) -> str:
    """用户输入 / 窗口拾取到的 exe → 名单关键字。

    去引号与路径、转小写、去掉 .exe 后缀（匹配是包含匹配，
    与默认名单 sldworks 这类无后缀关键字保持同一风格）。
    """
    s = str(name or "").strip().strip('"').replace("/", "\\").lower()
    if "\\" in s:
        s = s.rsplit("\\", 1)[-1]
    if s.endswith(".exe"):
        s = s[:-4]
    return s.strip()


# ---- Win32 窗口识别（物理像素坐标） ----

def cursor_phys():
    """光标位置（Win32 物理像素）；非 Windows 返回 (0, 0)"""
    if not IS_WINDOWS:
        return 0, 0
    pt = wintypes.POINT()
    _user32.GetCursorPos(ctypes.byref(pt))
    return pt.x, pt.y


def root_hwnd_at(x: float, y: float):
    """物理像素坐标处最顶层窗口的根句柄；取不到返回 None"""
    if not IS_WINDOWS:
        return None
    hwnd = _user32.WindowFromPoint(wintypes.POINT(int(x), int(y)))
    if not hwnd:
        return None
    return _user32.GetAncestor(hwnd, _GA_ROOT) or hwnd


def window_pid_from_hwnd(hwnd) -> int:
    """窗口所属进程 id；识别失败返回 0"""
    if not (IS_WINDOWS and hwnd):
        return 0
    pid = wintypes.DWORD()
    _user32.GetWindowThreadProcessId(hwnd, ctypes.byref(pid))
    return pid.value


def window_exe_from_hwnd(hwnd) -> str:
    """窗口所属进程的 exe 文件名（原样大小写，如 SLDWORKS.exe）；失败返回空串"""
    pid = window_pid_from_hwnd(hwnd)
    if not pid:
        return ""
    h = _kernel32.OpenProcess(
        _PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
    if not h:   # 管理员权限进程读不到，视为无法识别
        return ""
    try:
        buf = ctypes.create_unicode_buffer(1024)
        size = wintypes.DWORD(1024)
        if _kernel32.QueryFullProcessImageNameW(h, 0, buf, ctypes.byref(size)):
            return os.path.basename(buf.value)
        return ""
    finally:
        _kernel32.CloseHandle(h)


# ---- 拖动拾取 ----

class _PickTip(QLabel):
    """拖动拾取时跟随光标的浮层提示（鼠标穿透，不影响 WindowFromPoint）"""

    def __init__(self):
        super().__init__(None)
        self.setWindowFlags(Qt.Tool | Qt.FramelessWindowHint
                            | Qt.WindowStaysOnTopHint
                            | Qt.WindowTransparentForInput)
        self.setAttribute(Qt.WA_ShowWithoutActivating)
        self.setAttribute(Qt.WA_TransparentForMouseEvents)
        self.setAttribute(Qt.WA_TranslucentBackground)
        self.setStyleSheet(
            "QLabel { background: #2a3340; color: #f2f5f9;"
            " border: 1px solid #4a5568; border-radius: 6px;"
            " padding: 6px 12px; font-size: 13px; }")

    def show_text(self, text: str, pos: QPoint):
        """在光标旁显示提示（pos 为 Qt 逻辑像素全局坐标）"""
        self.setText(text)
        self.adjustSize()
        self.move(pos + QPoint(18, 18))
        if not self.isVisible():
            self.show()


class _PickButton(QPushButton):
    """「拾取窗口」：按住拖到目标窗口上松手识别 exe。

    Qt 在按下后会把后续 move/release 持续投给本按钮（隐式 grab），
    不需要全局鼠标钩子；拖动中其它窗口只会收到 hover，不会被激活。
    三种松手结果分别发信号，由列表控件统一给出反馈。
    """

    picked = Signal(str)        # 识别到的 exe 文件名（原文，交给归一化）
    cancelled = Signal()        # 松手在本工具自己的窗口上 = 用户取消
    unrecognized = Signal()     # 松手处没有可识别的窗口 / 进程

    def __init__(self, parent=None):
        super().__init__(T("拾取窗口"), parent)
        self.setCursor(Qt.PointingHandCursor)
        self.setToolTip(T("按住并拖到目标程序窗口上，松手后自动读取其进程名"
                          "加入名单；拖回本工具窗口松手则取消"))
        self._picking = False
        self._tip = None

    def mousePressEvent(self, e):
        if e.button() == Qt.LeftButton:
            self._start_pick()
        super().mousePressEvent(e)

    def mouseMoveEvent(self, e):
        if self._picking:
            self._update_pick()
        super().mouseMoveEvent(e)

    def mouseReleaseEvent(self, e):
        if self._picking:
            self._end_pick()
        super().mouseReleaseEvent(e)

    def _start_pick(self):
        self._picking = True
        QApplication.setOverrideCursor(Qt.CrossCursor)
        self._tip = _PickTip()
        self._update_pick()

    def _update_pick(self):
        x, y = cursor_phys()
        hwnd = root_hwnd_at(x, y)
        if hwnd and window_pid_from_hwnd(hwnd) == os.getpid():
            text = T("松手取消（这里是本工具自己的窗口）")
        elif hwnd:
            exe = window_exe_from_hwnd(hwnd)
            text = (T("松手添加：{exe}").format(exe=exe) if exe
                    else T("无法识别的窗口"))
        else:
            text = T("无法识别的窗口")
        self._tip.show_text(text, QCursor.pos())

    def _end_pick(self):
        self._picking = False
        QApplication.restoreOverrideCursor()
        if self._tip:
            self._tip.close()
            self._tip = None
        x, y = cursor_phys()
        hwnd = root_hwnd_at(x, y)
        if not hwnd:
            self.unrecognized.emit()
            return
        if window_pid_from_hwnd(hwnd) == os.getpid():
            self.cancelled.emit()   # 松手在自己窗口上 = 取消
            return
        exe = window_exe_from_hwnd(hwnd)
        if exe:
            self.picked.emit(exe)
        else:
            self.unrecognized.emit()


# ---- 手动添加对话框 ----

class _AddDialog(QDialog):
    """手动添加对话框：输入实时归一化校验，空名 / 重复时禁用确定键"""

    def __init__(self, existing: set, parent=None):
        super().__init__(parent)
        self._existing = existing
        self.setWindowTitle(T("添加应用"))
        self.setModal(True)
        self.setMinimumWidth(380)

        lay = QVBoxLayout(self)
        lay.setSpacing(8)
        lay.addWidget(QLabel(T("进程名（可带路径或 .exe 后缀，自动归一化）：")))
        self.edit = QLineEdit()
        self.edit.setPlaceholderText(
            T("如 excel 或 C:\\Program Files\\X\\EXCEL.EXE"))
        lay.addWidget(self.edit)
        self._err = QLabel("")
        self._err.setWordWrap(True)
        lay.addWidget(self._err)

        btns = QHBoxLayout()
        btns.addStretch(1)
        cancel = QPushButton(T("取消"))
        cancel.clicked.connect(self.reject)
        btns.addWidget(cancel)
        self._ok = QPushButton(T("添加"))
        self._ok.setProperty("class", "primary")
        self._ok.setDefault(True)
        self._ok.clicked.connect(self.accept)
        btns.addWidget(self._ok)
        lay.addLayout(btns)

        self.edit.textChanged.connect(self._validate)
        self.edit.returnPressed.connect(self._submit)
        self._validate()

    def _validate(self):
        n = normalize_entry(self.edit.text())
        if not n:
            self._err.setText("")
            self._err.setStyleSheet("")
            self._ok.setEnabled(False)
        elif n in self._existing:
            self._err.setText(T("「{name}」已在名单中").format(name=n))
            self._err.setStyleSheet(f"color: {get_ui().danger};")
            self._ok.setEnabled(False)
        else:
            self._err.setText("")
            self._err.setStyleSheet("")
            self._ok.setEnabled(True)

    def _submit(self):
        if self._ok.isEnabled():
            self.accept()

    def entry(self) -> str:
        return normalize_entry(self.edit.text())


# ---- 名单列表控件 ----

class ExcludeAppsWidget(QWidget):
    """不弹圆盘应用名单：列表 + 添加 + 拾取，改动经 changed(str) 上报。

    本控件只含列表本体；「添加应用…」与「拾取窗口」按钮作为 btn_add /
    btn_pick 暴露给设置页放进标题行（布局更紧凑，页面只多占一行列表的高度）。
    操作结果（已添加 / 已在名单中 / 未能识别 / 已取消）以浮层提示显示在
    列表框内，短暂停留后自动消失；空名单时同一位置显示占位提示。
    """

    changed = Signal(str)   # 发出归一化后的逗号分隔存储串

    _ROW_H = 28   # 行高需容纳 ✕ 按钮 24px + 上下边距 2px，否则按钮被裁切偏移
    _MIN_VISIBLE = 4   # 列表框最小高度（行）：条目少时盒子也不能太瘪
    _MAX_VISIBLE = 8   # 超过后列表内部滚动，页面高度不再增长

    def __init__(self, text="", parent=None):
        super().__init__(parent)
        self._entries = parse_entries(text)
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 0, 0, 0)
        lay.setSpacing(0)

        self.list = QListWidget()
        self.list.setObjectName("excludeList")   # 样式见 theme.py：干净卡片框
        self.list.setSelectionMode(QListWidget.NoSelection)
        self.list.setFocusPolicy(Qt.NoFocus)
        self.list.setFrameShape(QFrame.NoFrame)
        lay.addWidget(self.list)

        # 浮层：空名单占位提示 + 操作反馈提示（都盖在列表框上居中）
        self._empty_lbl = QLabel(self.list)
        self._empty_lbl.setObjectName("excludeHint")
        self._empty_lbl.setWordWrap(True)
        self._empty_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._empty_lbl.setText(
            T("暂无应用 —— 点击「添加应用…」或「拾取窗口」添加"))
        self._toast_lbl = QLabel(self.list)
        self._toast_lbl.setObjectName("excludeToast")
        self._toast_lbl.setWordWrap(True)
        self._toast_lbl.setAttribute(Qt.WA_TransparentForMouseEvents)
        self._toast_lbl.hide()
        self._toast_timer = QTimer(self)
        self._toast_timer.setSingleShot(True)
        self._toast_timer.setInterval(_TOAST_MS)
        self._toast_timer.timeout.connect(self._update_overlays)

        # 操作按钮：由设置页摆进「不弹圆盘的应用」标题行右侧
        self.btn_pick = _PickButton()
        self.btn_pick.picked.connect(self._add_with_feedback)
        self.btn_pick.cancelled.connect(
            lambda: self._show_toast("已取消拾取"))
        self.btn_pick.unrecognized.connect(
            lambda: self._show_toast("未能识别该窗口的程序"))
        self.btn_add = QPushButton(T("添加应用…"))
        self.btn_add.setToolTip(T("输入进程名（可带路径或 .exe 后缀）加入名单"))
        self.btn_add.clicked.connect(self._on_add_clicked)

        self._reload()

    # ---- 对外 API ----

    def text(self) -> str:
        return join_entries(self._entries)

    def set_text(self, text: str):
        """按存储串重建列表（进页面刷新用，不发 changed）"""
        self._entries = parse_entries(text)
        self._reload()

    def add_entry(self, name) -> bool:
        """归一化后追加；空名或重复返回 False（反馈由交互层负责）"""
        n = normalize_entry(name)
        if not n or n in self._entries:
            return False
        self._entries.append(n)
        self._reload()
        self.changed.emit(self.text())
        return True

    def remove_entry(self, name) -> bool:
        if name not in self._entries:
            return False
        self._entries.remove(name)
        self._reload()
        self.changed.emit(self.text())
        return True

    # ---- 内部 ----

    def retranslate(self):
        """语言切换后刷新按钮/提示文案（列表整体重建，行内 tooltip 一并更新）"""
        self.btn_pick.setText(T("拾取窗口"))
        self.btn_pick.setToolTip(T("按住并拖到目标程序窗口上，松手后自动读取"
                                   "其进程名加入名单；拖回本工具窗口松手则取消"))
        self.btn_add.setText(T("添加应用…"))
        self.btn_add.setToolTip(T("输入进程名（可带路径或 .exe 后缀）加入名单"))
        self._empty_lbl.setText(
            T("暂无应用 —— 点击「添加应用…」或「拾取窗口」添加"))
        self._toast_timer.stop()
        self._reload()

    def _on_add_clicked(self):
        dlg = _AddDialog(set(self._entries), self)
        if dlg.exec():
            self._add_with_feedback(dlg.entry())

    def _add_with_feedback(self, raw):
        """归一化后入名单，并把结果（已添加 / 已在名单中）提示出来"""
        n = normalize_entry(raw)
        if not n:
            return
        if self.add_entry(n):
            self._show_toast(T("已添加应用 {name}").format(name=n))
        else:
            self._show_toast(T("{name} 已在名单中").format(name=n))

    def _show_toast(self, text: str):
        self._toast_lbl.setText(text)
        self._toast_timer.start()
        self._update_overlays()

    def _update_overlays(self):
        """按「是否有条目 / 反馈是否在展示」切换两个浮层的可见性"""
        toast_on = self._toast_timer.isActive()
        self._toast_lbl.setVisible(toast_on)
        self._empty_lbl.setVisible(not self._entries and not toast_on)
        self._place_overlays()

    def _place_overlays(self):
        """两个浮层都居中盖在列表框上"""
        for lbl in (self._empty_lbl, self._toast_lbl):
            lbl.setMaximumWidth(max(120, self.list.width() - 24))
            lbl.adjustSize()
            lbl.move(max(8, (self.list.width() - lbl.width()) // 2),
                     max(4, (self.list.height() - lbl.height()) // 2))

    def resizeEvent(self, e):
        super().resizeEvent(e)
        self._place_overlays()

    def _reload(self):
        self.list.clear()
        for name in self._entries:
            item = QListWidgetItem()
            item.setSizeHint(QSize(10, self._ROW_H))
            self.list.addItem(item)
            row = QWidget()
            row_lay = QHBoxLayout(row)
            row_lay.setContentsMargins(2, 2, 6, 2)
            row_lay.setSpacing(6)
            lb = QLabel(name)
            lb.setToolTip(T("进程名包含 {name} 的程序将不弹出圆盘")
                          .format(name=name))
            row_lay.addWidget(lb)
            row_lay.addStretch(1)
            btn = QPushButton("✕")
            btn.setProperty("class", "iconBtn")
            btn.setToolTip(T("从名单移除"))
            btn.setCursor(Qt.PointingHandCursor)
            btn.setFixedSize(24, 24)
            btn.clicked.connect(lambda _=False, n=name: self.remove_entry(n))
            row_lay.addWidget(btn)
            self.list.setItemWidget(item, row)
        self.list.setFixedHeight(
            min(max(len(self._entries), self._MIN_VISIBLE), self._MAX_VISIBLE)
            * self._ROW_H + 4)
        self._update_overlays()
