# -*- mode: python ; coding: utf-8 -*-
"""
CAD鼠标手势工具 - PyInstaller 打包配置 (onefile 单文件版)
打包命令：pyinstaller cad_gesture.spec
"""

import sys
import os

block_cipher = None

# ========== 入口文件 ==========
entry_point = 'main.py'

# ========== 隐式导入 ==========
hidden_imports = [
    'PIL',
    'PIL.Image',
    'PIL.ImageDraw',
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
    # PySide6 由 PyInstaller 内置 hook 自动收集（Qt 插件/DLL）
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
        'tkinter', '_tkinter',  # 程序不用 tkinter，排除可省 tcl/tk DLL
        'unittest', 'pydoc', 'doctest', 'pydoc_data',
        'sqlite3', 'mailbox', 'venv', 'ensurepip', 'lib2to3',
        'http.server', 'http.cookiejar',
        'xmlrpc.client', 'xmlrpc.server',
        # PySide6 用不到的 Qt 模块（每个 DLL 数 MB，排除可显著减小体积）
        'PySide6.QtQml', 'PySide6.QtQuick', 'PySide6.QtQmlMeta',
        'PySide6.QtQmlModels', 'PySide6.QtQmlWorkerScript',
        'PySide6.QtQuickWidgets', 'PySide6.QtQuickControls2',
        'PySide6.QtPdf', 'PySide6.QtPdfWidgets',
        'PySide6.QtVirtualKeyboard',
        'PySide6.QtNetwork', 'PySide6.QtNetworkAuth', 'PySide6.QtWebSockets',
        'PySide6.QtSvg', 'PySide6.QtSvgWidgets',
        'PySide6.QtMultimedia', 'PySide6.QtMultimediaWidgets',
        'PySide6.QtCharts', 'PySide6.QtDataVisualization', 'PySide6.QtGraphs',
        'PySide6.QtSql', 'PySide6.QtBluetooth', 'PySide6.QtNfc',
        'PySide6.QtSerialPort', 'PySide6.QtPositioning', 'PySide6.QtLocation',
        'PySide6.QtSensors', 'PySide6.Qt3DCore', 'PySide6.Qt3DRender',
        'PySide6.QtDesigner', 'PySide6.QtHelp', 'PySide6.QtTest',
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

# ========== 排除用不到的 Qt 模块 DLL ==========
# PySide6 hook 会全量收集 Qt 模块 DLL（Qml/Quick/Pdf/Network 等我们用不到），
# excludes 拦不住 hook 收集的二进制，须在此按文件名过滤。
import os as _os
_EXCLUDE_QT_DLLS = {
    "Qt6Qml.dll", "Qt6QmlMeta.dll", "Qt6QmlModels.dll",
    "Qt6QmlWorkerScript.dll", "Qt6Quick.dll", "Qt6QuickControls2.dll",
    "Qt6QuickWidgets.dll", "Qt6QmlDebug.dll",
    "Qt6Pdf.dll", "Qt6PdfWidgets.dll",
    "Qt6Network.dll", "Qt6NetworkAuth.dll", "Qt6WebSockets.dll",
    "Qt6VirtualKeyboard.dll",
    "Qt6Svg.dll", "Qt6SvgWidgets.dll",
    "Qt6Multimedia.dll", "Qt6MultimediaWidgets.dll",
    "Qt6Charts.dll", "Qt6DataVisualization.dll", "Qt6Graphs.dll",
    "Qt6Sql.dll", "Qt6Test.dll", "Qt6Designer.dll",
    "Qt6Help.dll", "Qt6Bluetooth.dll", "Qt6Nfc.dll",
    "Qt6SerialPort.dll", "Qt6Positioning.dll", "Qt6Location.dll",
    "Qt6Sensors.dll", "Qt6WebEngineCore.dll", "Qt6WebEngineWidgets.dll",
    # 软件渲染后备库（20MB+）：Qt 在无 GPU 环境会自动退回 raster 软绘，无需打包
    "opengl32sw.dll",
    # Qt6OpenGL 仅被已排除的 Quick/OpenGLWidgets 引用（Qt6Gui 的 GL 走系统 opengl32.dll）
    "Qt6OpenGL.dll", "Qt6OpenGLWidgets.dll",
}
a.binaries = [b for b in a.binaries
              if _os.path.basename(b[0]) not in _EXCLUDE_QT_DLLS]
# 同步排除对应的 PySide6 二进制绑定（.pyd），避免残留无用模块
a.binaries = [b for b in a.binaries
              if not (_os.path.basename(b[0]).startswith(("QtQml", "QtQuick",
                          "QtPdf", "QtNetwork", "QtVirtualKeyboard", "QtSvg",
                          "QtMultimedia", "QtCharts", "QtSql", "QtTest",
                          "QtDesigner", "QtHelp", "QtWebEngine"))
                      and _os.path.basename(b[0]).endswith(".pyd"))]

# ========== 排除冗余二进制（孤儿 DLL / 用不到的扩展） ==========
_EXCLUDE_EXTRA = {
    "tcl86t.dll", "tk86t.dll", "tcl87t.dll", "tk87t.dll",  # tkinter 依赖
    # 注意：libcrypto-3.dll / libssl-3.dll 不能排除——Python 的 ssl 模块（_ssl.pyd）
    # 依赖它们，排除了会导致打包版 https 请求全部失败（unknown url type: https）
}
a.binaries = [b for b in a.binaries
              if _os.path.basename(b[0]) not in _EXCLUDE_EXTRA
              and not _os.path.basename(b[0]).startswith("_avif")]  # Pillow AVIF 插件(8MB)

# ========== 排除 Qt 翻译文件（界面为自定义中文绘制，无需多语言 .qm） ==========
a.datas = [d for d in a.datas if not d[0].endswith(".qm")]

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