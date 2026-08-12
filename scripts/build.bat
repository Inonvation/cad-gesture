@echo off
echo ========================================
echo   CAD鼠标手势工具 - 一键打包脚本
echo ========================================
echo.

:: 切换到项目根目录（脚本在 scripts\ 子目录）
cd /d "%~dp0.."

:: Python312 环境（打包必须用它，其他环境可能缺 PyInstaller）
set "PY312=C:\Users\cy\AppData\Local\Programs\Python\Python312\python.exe"
:: Inno Setup 6.3+（需要 x64compatible / CloseApplications 特性）
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" (
    if exist "D:\Inno Setup 6\ISCC.exe" set "ISCC=D:\Inno Setup 6\ISCC.exe"
)

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
echo.

:: 执行 PyInstaller 打包
echo [2/5] 正在打包（首次可能需要 1-2 分钟）...
"%PY312%" -m PyInstaller cad_gesture.spec --clean --noconfirm
if errorlevel 1 (
    echo.
    echo [ERROR] 打包失败！请检查错误信息。
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
if exist "config\config.json" (
    copy "config\config.json" "dist\config\config.json" >nul
    echo       已复制 config\config.json
) else (
    echo [WARNING] config\config.json 不存在，跳过复制
)
echo.

:: 编译安装包（版本号从 version.txt 自动提取注入）
echo [4/5] 编译安装包...
:: %PY312% 无空格，for /f 命令替换中不能带引号（会导致解析失败）
for /f %%v in ('%PY312% scripts\read_version.py') do set VERSION=%%v
if errorlevel 1 (
    echo [ERROR] 读取版本号失败！
    pause
    exit /b 1
)
echo       版本号: %VERSION%
echo [4/5] 正在打包绿色版 zip...
powershell -NoProfile -Command "Compress-Archive -Path 'dist\CADGesture-x64' -DestinationPath 'dist\CADGesture-v%VERSION%.zip' -Force"
if errorlevel 1 (
    echo [WARNING] 绿色版 zip 打包失败，请手动压缩 dist\CADGesture-x64
) else (
    echo       绿色版 zip: dist\CADGesture-v%VERSION%.zip
)
if exist "%ISCC%" (
    "%ISCC%" /DMyAppVersion=%VERSION% cad_gesture.iss
    if errorlevel 1 (
        echo [ERROR] 安装包编译失败！
        pause
        exit /b 1
    )
    echo       安装包编译完成！
) else (
    echo [WARNING] 未找到 Inno Setup（%ISCC%），跳过安装包编译
)
echo.

:: 完成
echo [5/5] 打包完成！
echo.
echo ========================================
echo   输出目录: dist\
echo   绿色版:   dist\CADGesture-v%VERSION%.zip
echo   安装版:   dist\Setup-CADGesture-v%VERSION%.exe
echo   配置文件: dist\config\config.json
echo ========================================
echo.
echo   使用方法: 将 dist 文件夹整个复制到任意位置
echo             解压绿色版 zip 后运行 CADGesture-x64.exe
echo ========================================
echo.

:: 询问是否打开输出目录
set /p OPEN_DIR="是否打开输出目录？(Y/N): "
if /i "%OPEN_DIR%"=="Y" (
    explorer "dist"
)

pause
