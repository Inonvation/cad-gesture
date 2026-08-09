@echo off
chcp 65001 >nul
echo ========================================
echo   CAD鼠标手势工具 - 一键打包脚本
echo ========================================
echo.

:: 切换到脚本所在目录
cd /d "%~dp0"

:: 清理旧的构建文件
echo [1/4] 清理旧的构建文件...
if exist "build" (
    rmdir /s /q "build"
    echo       已删除 build 目录
)
if exist "dist" (
    rmdir /s /q "dist"
    echo       已删除 dist 目录
)
echo.

:: 执行 PyInstaller 打包
echo [2/4] 正在打包（首次可能需要 1-2 分钟）...
pyinstaller cad_gesture.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] 打包失败！请检查错误信息。
    pause
    exit /b 1
)
echo       打包完成！
echo.

:: 复制配置文件到输出目录
echo [3/4] 复制配置文件...
if not exist "dist\config" (
    mkdir "dist\config"
)
if exist "config\config.json" (
    copy "config\config.json" "dist\config\config.json" >nul
    echo       已复制 config\config.json
) else (
    echo [WARNING] config\config.json 不存在，跳过复制
)
echo.

:: 完成
echo [4/4] 打包完成！
echo.
echo ========================================
echo   输出目录: dist\
echo   主程序:   dist\CADGesture-x64.exe
echo   配置文件: dist\config\config.json
echo ========================================
echo.
echo   使用方法: 将 dist 文件夹整个复制到任意位置
echo             双击 CADGesture-x64.exe 即可运行
echo ========================================
echo.

:: 询问是否打开输出目录
set /p OPEN_DIR="是否打开输出目录？(Y/N): "
if /i "%OPEN_DIR%"=="Y" (
    explorer "dist"
)

pause