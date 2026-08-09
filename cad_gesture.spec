# -*- mode: python ; coding: utf-8 -*-
"""
CAD鼠标手势工具 - PyInstaller 打包配置 (onefile 单文件版)
打包命令：pyinstaller cad_gesture.spec
"""

import sys
import os
from PyInstaller.utils.hooks import collect_data_files, collect_submodules

block_cipher = None

# ========== 入口文件 ==========
entry_point = 'main.py'

# ========== 隐式导入 ==========
hidden_imports = [
    'tkinter',
    'tkinter.ttk',
    'tkinter.messagebox',
    'tkinter.filedialog',
    'customtkinter',
    'darkdetect',
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
    'PIL.ImageTk',
    'pystray',
    'pystray._win32',
    'win32com',
    'win32com.client',
    'pythoncom',
    'pywintypes',
    'ctypes',
    'ctypes.wintypes',
    'json',
    'math',
    'threading',
    'queue',
    'time',
    'os',
    'sys',
]

# ========== pywin32 DLL 路径 ==========
import site
pywin32_dll_dir = None
for sp in site.getsitepackages():
    dll_path = os.path.join(sp, 'pywin32_system32')
    if os.path.isdir(dll_path):
        pywin32_dll_dir = dll_path
        break

if pywin32_dll_dir is None:
    possible_paths = [
        os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Programs', 'Python', 'Python311', 'Lib', 'site-packages', 'pywin32_system32'),
        os.path.join(os.path.expanduser('~'), 'AppData', 'Local', 'Programs', 'Python', 'Python312', 'Lib', 'site-packages', 'pywin32_system32'),
    ]
    for p in possible_paths:
        if os.path.isdir(p):
            pywin32_dll_dir = p
            break

datas = []
binaries = []
if pywin32_dll_dir:
    py_ver = f"{sys.version_info.major}{sys.version_info.minor}"
    for dll_prefix in ['pywintypes', 'pythoncom']:
        dll_name = f"{dll_prefix}{py_ver}.dll"
        dll_path = os.path.join(pywin32_dll_dir, dll_name)
        if os.path.exists(dll_path):
            binaries.append((dll_path, '.'))
    print(f"[INFO] Found pywin32 DLLs at: {pywin32_dll_dir}")
else:
    print("[WARNING] pywin32_system32 directory not found!")

# 收集 tkinter 数据文件 (tcl/tk runtime)
from PyInstaller.utils.hooks import collect_data_files as _cdf
try:
    tk_data = _cdf('tkinter')
    datas.extend(tk_data)
except Exception:
    pass

# 收集 customtkinter 主题数据文件
try:
    ctk_data = _cdf('customtkinter')
    datas.extend(ctk_data)
except Exception:
    pass

# 不打包 config 目录（放在 exe 外部供用户编辑）

# ========== 版本信息 ==========
version_info = os.path.join(SPECPATH, 'version.txt')

# ========== 分析阶段 ==========
a = Analysis(
    [entry_point],
    pathex=[],
    binaries=binaries,
    datas=datas,
    hiddenimports=hidden_imports,
    hookspath=[],
    hooksconfig={},
    runtime_hooks=[],
    excludes=[
        'matplotlib', 'numpy', 'scipy', 'pandas',
        'cv2', 'torch', 'tensorflow',
    ],
    win_no_prefer_redirects=False,
    win_private_assemblies=False,
    cipher=block_cipher,
    noarchive=False,
)

# ========== 排除误收集的系统 API set DLL ==========
# PATH 中若装有 JDK 等，PyInstaller 会误收集 api-ms-win-core-*.dll / ext-ms-*.dll。
# 这些是 Windows 运行时解析的 API set，无需打包，排除可显著减小体积。
import re as _re
a.binaries = [b for b in a.binaries
              if not _re.search(r'(api-ms-win-|ext-ms-)', b[0].lower())]

pyz = PYZ(a.pure, a.zipped_data, cipher=block_cipher)

# ========== onefile 单文件打包 ==========
exe = EXE(
    pyz,
    a.scripts,
    a.binaries,      # 所有二进制文件打包进 exe
    a.zipfiles,      # 所有 zip 文件打包进 exe
    a.datas,         # 所有数据文件打包进 exe
    name='CADGesture-x64',
    debug=False,
    bootloader_ignore_signals=False,
    strip=False,
    upx=True,
    upx_exclude=[],
    runtime_tmpdir=None,
    console=False,
    disable_windowed_traceback=False,
    target_arch=None,
    codesign_identity=None,
    entitlements_file=None,
    icon='assets/icon.ico',
    version=version_info,
)