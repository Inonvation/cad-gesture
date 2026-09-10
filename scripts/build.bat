@echo off
echo ========================================
echo   CAD鼠标手势工具 - 一键打包脚本（Velopack）
echo ========================================
echo.

:: 切换到项目根目录
cd /d "%~dp0.."

:: Python312 环境（打包必须用它，其他环境可能缺 PyInstaller）
set "PY312=C:\Users\cy\AppData\Local\Programs\Python\Python312\python.exe"
:: Velopack 工具链：dotnet + vpk（用户目录安装，vpk.cmd 为 shim）。
set "DOTNET=%USERPROFILE%\.dotnet\dotnet.exe"
:: Inno Setup 6.3+ 编译器（向导壳编译用）
set "ISCC=C:\Program Files (x86)\Inno Setup 6\ISCC.exe"
if not exist "%ISCC%" if exist "D:\Inno Setup 6\ISCC.exe" set "ISCC=D:\Inno Setup 6\ISCC.exe"
set "PATH=%USERPROFILE%\.dotnet\tools;%PATH%"

:: 清理旧的构建文件
echo [1/6] 清理旧的构建文件...
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
echo [2/6] 正在打包（首次可能需要 1-2 分钟）...
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
echo [3/6] 复制配置文件...
if not exist "dist\config" (
    mkdir "dist\config"
)
if exist "config\config.example.json" (
    copy "config\config.example.json" "dist\config\config.example.json" >nul
    echo       已复制 config\config.example.json
) else (
    echo [WARNING] config\config.example.json 不存在，跳过复制
)
echo.

:: vpk 打包 Velopack release
echo [4/6] vpk 打包 Velopack release...
:: %PY312% 无空格，for /f 命令替换中不能带引号（会导致解析失败）
for /f %%v in ('%PY312% scripts\read_version.py') do set VERSION=%%v
if errorlevel 1 (
    echo [ERROR] 读取版本号失败！
    pause
    exit /b 1
)
echo       版本号: %VERSION%
:: 检查 vpk 命令（首次需手动装 dotnet SDK + dotnet tool install -g vpk）
where vpk >nul 2>&1
if errorlevel 1 (
    echo [ERROR] 未找到 vpk 命令，请先安装 dotnet SDK 与 vpk:
    echo        1. dotnet-install.ps1 -Channel 8.0 -InstallDir "%USERPROFILE%\.dotnet"
    echo        2. "%DOTNET%" tool install vpk --version %VERSION:~0,5% --tool-path "%USERPROFILE%\.dotnet\tools"
    pause
    exit /b 1
)
:: vpk pack：一次产出 Setup.exe + portable zip + nupkg + delta + releases.win.json
vpk pack --packId CADGesture ^
         --packVersion %VERSION% ^
         --packDir dist\CADGesture-x64 ^
         --mainExe CADGesture-x64.exe ^
         --icon assets\icon.ico ^
         --instWelcome docs\installer-welcome.txt ^
         --instConclusion docs\installer-conclusion.txt ^
         --packTitle "CAD鼠标手势" ^
         --outputDir Releases
if errorlevel 1 (
    echo [ERROR] vpk 打包失败！
    pause
    exit /b 1
)
:: 编译 Inno 向导壳（内嵌 Velopack Setup）：产出 Setup-CADGesture-vX.exe
:: —— 新用户得到传统中文向导（选目录/确认/完成）；老 Inno updater
::     下载同名资产以 /VERYSILENT 运行时，Inno 自动静默执行，完成无感迁移。
echo       [5/6] 编译安装向导壳...
"%ISCC%" /DMyAppVersion=%VERSION% cad_gesture.iss
if errorlevel 1 (
    echo [ERROR] 安装向导壳编译失败！
    pause
    exit /b 1
)
echo       完成：Releases\Setup-CADGesture-v%VERSION%.exe
echo.

:: 完成
echo [6/6] 打包完成！
echo.
echo ========================================
echo   输出目录:  Releases\
echo   安装向导壳: Releases\Setup-CADGesture-v%VERSION%.exe  (中文向导 + 内嵌 Velopack 引擎)
echo   安装引擎:   Releases\CADGesture-win-Setup.exe
echo   绿色版:      Releases\CADGesture-win-Portable.zip
echo   配置模板:  dist\config\config.example.json
echo   更新源:    Releases\releases.win.json
echo ========================================
echo.
echo   发布到 GitHub Release：手动上传 Releases\ 下全部资产
echo           或 vpk upload github --repoUrl ... --token ...
echo ========================================
echo.

:: 询问是否打开输出目录
set /p OPEN_DIR="是否打开输出目录？(Y/N): "
if /i "%OPEN_DIR%"=="Y" (
    explorer "Releases"
)

pause
