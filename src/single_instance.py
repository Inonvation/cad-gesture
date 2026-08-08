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
_MUTEX_ALL_ACCESS = 0x001F0001

_held_mutex = None
_held_exit_event = None

_kernel32 = ctypes.WinDLL("kernel32", use_last_error=True)
_kernel32.CreateMutexW.restype = wintypes.HANDLE
_kernel32.CreateMutexW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenMutexW.restype = wintypes.HANDLE
_kernel32.OpenMutexW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.CreateEventW.restype = wintypes.HANDLE
_kernel32.CreateEventW.argtypes = [wintypes.LPVOID, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.OpenEventW.restype = wintypes.HANDLE
_kernel32.OpenEventW.argtypes = [wintypes.DWORD, wintypes.BOOL, wintypes.LPCWSTR]
_kernel32.SetEvent.argtypes = [wintypes.HANDLE]
_kernel32.ResetEvent.argtypes = [wintypes.HANDLE]
_kernel32.CloseHandle.argtypes = [wintypes.HANDLE]
_kernel32.WaitForSingleObject.restype = wintypes.DWORD
_kernel32.WaitForSingleObject.argtypes = [wintypes.HANDLE, wintypes.DWORD]


def _acquire() -> bool:
    """尝试成为唯一实例。

    采用"OpenMutexW 前置检测 + CreateMutexW 获取"两步：
    - OpenMutexW 成功打开说明已有其他实例持有，直接返回失败；
    - CreateMutexW 成功路径的 GetLastError 可能残留无关值（如进程启动
      时遗留的 183），因此不依赖它做唯一判断，仅用作竞态兜底。

    Returns:
        True 表示本进程成功持有互斥体；False 表示已有其他实例在运行。
    """
    global _held_mutex, _held_exit_event
    # 前置检测：互斥体已存在 → 其他实例在运行
    existing = _kernel32.OpenMutexW(_MUTEX_ALL_ACCESS, False, _MUTEX_NAME)
    if existing:
        _kernel32.CloseHandle(existing)
        return False

    _held_mutex = _kernel32.CreateMutexW(None, False, _MUTEX_NAME)
    if not _held_mutex:
        return False
    # 竞态兜底：OpenMutexW 之后、CreateMutexW 之前被其他进程抢先创建。
    # 此时 CreateMutexW 确实会设置 ERROR_ALREADY_EXISTS，此判断可靠。
    if ctypes.get_last_error() == _ERROR_ALREADY_EXISTS:
        _kernel32.CloseHandle(_held_mutex)
        _held_mutex = None
        return False
    _held_exit_event = _kernel32.CreateEventW(None, True, False, _EXIT_EVENT)
    if _held_exit_event:
        _kernel32.ResetEvent(_held_exit_event)
    return True


def ensure_single_instance(wait_timeout: float = 15.0) -> bool:
    """确保本进程成为唯一实例。

    若已有实例在运行，则请求其优雅退出并等待其释放互斥体（覆盖更新）。
    返回 True 表示本进程应继续运行；False 表示应退出。
    """
    if _acquire():
        return True

    # 已有旧实例 → 通知其退出并等待
    request_old_exit()
    deadline = time.time() + wait_timeout
    while time.time() < deadline:
        time.sleep(0.2)
        if _acquire():
            return True
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
        signaled = _kernel32.WaitForSingleObject(ev, 0) == 0
        if signaled and not close_after:
            # 复位手动重置事件，避免同一退出请求被主循环重复处理
            _kernel32.ResetEvent(ev)
        return signaled
    finally:
        if close_after:
            _kernel32.CloseHandle(ev)
