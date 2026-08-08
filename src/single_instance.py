"""单实例保护与覆盖更新

通过 Windows 命名互斥体 + 命名事件实现：
- 互斥体：判断是否已有实例在运行
- 事件：新实例通知旧实例优雅退出（实现"覆盖更新"，避免托盘多图标）

关键点：持有互斥体的主实例必须同时持有事件句柄，
否则事件对象会因句柄全部关闭而被系统销毁，旧实例将收不到退出信号。

注：本项目运行于 uv 创建的 venv，其 python.exe 是 launcher，会再 spawn
真实解释器执行 main.py。真正执行业务逻辑的是被 spawn 的解释器进程，
单实例锁由其持有，launcher 不参与。
"""

import ctypes
import time
from ctypes import wintypes

_MUTEX_NAME = "CADGesture_SingleInstance"
_EXIT_EVENT = "CADGesture_ExitRequest"
_ERROR_ALREADY_EXISTS = 183
_EVENT_ALL_ACCESS = 0x001F0003

_held_mutex = None
_held_exit_event = None

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]


def _mutex_exists() -> bool:
    """判断互斥体是否已被其他进程持有"""
    h = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    exists = ctypes.get_last_error() == _ERROR_ALREADY_EXISTS
    if h:
        _kernel32.CloseHandle(h)
    return exists


def _acquire():
    """本进程成为唯一实例：持有互斥体，并创建/持有退出事件"""
    global _held_mutex, _held_exit_event
    _held_mutex = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    # 创建并持有事件句柄，保证事件对象存活，使其他实例能通知到我们
    _held_exit_event = _kernel32.CreateEventW(None, True, False, _EXIT_EVENT)
    if _held_exit_event:
        _kernel32.ResetEvent(_held_exit_event)


def ensure_single_instance(wait_timeout: float = 15.0) -> bool:
    """确保本进程成为唯一实例。

    若已有实例在运行，则请求其优雅退出并等待其释放互斥体（覆盖更新）。
    返回 True 表示本进程应继续运行；False 表示应退出。
    """
    if not _mutex_exists():
        _acquire()
        return True

    # 已有旧实例 → 通知其退出并等待
    request_old_exit()
    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        if not _mutex_exists():
            _acquire()
            return True
        time.sleep(0.2)
    return False


def request_old_exit():
    """请求已运行的旧实例优雅退出（置位命名事件）"""
    ev = _kernel32.OpenEventW(_EVENT_ALL_ACCESS, False, _EXIT_EVENT)
    if not ev:
        # 旧实例可能尚未创建事件，直接创建并置位
        ev = _kernel32.CreateEventW(None, True, False, _EXIT_EVENT)
    if ev:
        _kernel32.SetEvent(ev)
        _kernel32.CloseHandle(ev)


def is_exit_requested() -> bool:
    """当前实例是否收到退出请求（供主循环低频轮询）"""
    ev = _held_exit_event
    close_after = False
    if not ev:
        ev = _kernel32.OpenEventW(_EVENT_ALL_ACCESS, False, _EXIT_EVENT)
        close_after = True
    if not ev:
        return False
    try:
        return _kernel32.WaitForSingleObject(ev, 0) == 0
    finally:
        if close_after:
            _kernel32.CloseHandle(ev)
