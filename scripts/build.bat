@echo off
echo ========================================
echo   CAD鼠标手势 - 一键打包脚本（Inno Setup）
echo ========================================
echo.

:: 切换到项目根目录
cd /d "%~dp0.."

:: Python312 环境（本机实测可用，缺 PyInstaller 会报错）
set "PY312=C:\Users\cy\AppData\Local\Programs\Python\Python312\python.exe"
:: Inno Setup 6 编译器（安装向导打包用）
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" if exist "D:\Inno Setup 6\ISCC.exe" set "ISCC=D:\Inno Setup 6\ISCC.exe"

:: 清理旧的构建文件
echo [1/5] 清理旧的构建文件...
if exist "build" (
    rmdir /s /q "build"
    echo       已删除 build 目录
)
if exist "dist" (
    rmdir /s /q "dist"
    echo       已删除 dist 目录
)
if exist "Releases" (
    rmdir /s /q "Releases"
    echo       已删除 Releases 目录
)
echo.

:: 执行 PyInstaller 打包
echo [2/5] 正在打包（首次可能需要 1-2 分钟）...
"%PY312%" -m PyInstaller cad_gesture.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] 打包失败，请查看错误信息！
    pause
    exit /b 1
)
echo       打包完成！
echo.

:: 复制配置文件到输出目录
echo [3/5] 复制配置文件...
if not exist "dist\config" (
    mkdir "dist\config"
)
if exist "config\config.example.json" (
    copy "config\config.example.json" "dist\config\config.example.json" >nul
    echo       已复制 config\config.example.json
) else (
    echo [WARNING] config\config.example.json 不存在，已跳过
)
echo.

:: 提取版本号并编译 Inno 安装向导
echo [4/5] 编译安装向导...
for /f %%v in ('%PY312% scripts\read_version.py') do set VERSION=%%v
if errorlevel 1 (
    echo [ERROR] 读取版本号失败！
    pause
    exit /b 1
)
echo       版本号: %VERSION%
"%ISCC%" /DMyAppVersion=%VERSION% cad_gesture.iss
if errorlevel 1 (
    echo [ERROR] 安装向导编译失败！
    pause
    exit /b 1
)
echo       完成：Releases\Setup-CADGesture-v%VERSION%.exe
echo.

:: 压缩绿色版 zip
echo [5/5] 压缩绿色版...
powershell -NoProfile -Command ^
  "$zip = 'Releases\CADGesture-v%VERSION%-portable.zip';" ^
  "if (Test-Path $zip) { Remove-Item $zip -Force };" ^
  "Compress-Archive -Path 'dist\CADGesture-x64' -DestinationPath $zip -Force;"
if errorlevel 1 (
    echo [ERROR] 绿色版压缩失败！
    pause
    exit /b 1
)
echo       完成：Releases\CADGesture-v%VERSION%-portable.zip
echo.

:: 完成
echo ========================================
echo   输出目录:  Releases\
echo   安装版:    Releases\Setup-CADGesture-v%VERSION%.exe
echo   绿色版:    Releases\CADGesture-v%VERSION%-portable.zip
echo   配置模板:  dist\config\config.example.json
echo ========================================
echo.
echo   上传 GitHub Release 时一并上传上述两个包 + config.example.json
echo ========================================
echo.

:: 询问是否打开目录
set /p OPEN_DIR="是否打开目录？(Y/N): "
if /i "%OPEN_DIR%"=="Y" (
    explorer "Releases"
)

pause
