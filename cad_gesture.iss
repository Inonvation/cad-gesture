; CAD鼠标手势 - Inno Setup 安装脚本
; 要求: Inno Setup 6.3+（x64compatible / CloseApplications 需要）
; 用法: ISCC.exe /DMyAppVersion=0.0.2 cad_gesture.iss
;       （scripts\build.bat 自动注入版本号）

#ifndef MyAppVersion
#define MyAppVersion "0.0.2"
#endif
#define MyAppName "CAD鼠标手势"
#define MyAppExeName "CADGesture-x64.exe"
; AppId 固定不可更改，改了就变成"另一个软件"，覆盖安装失效
#define MyAppId "{{8E1F2A3B-4C5D-4E6F-8A7B-9C0D1E2F3A4B}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=CAD Gesture
AppPublisherURL=https://github.com/Inonvation/cad-gesture
DefaultDirName={localappdata}\Programs\CADGesture
; 显示目录选择页，允许用户更改安装位置（默认位置是用户目录，免 UAC）
DisableDirPage=no
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
OutputDir=dist
OutputBaseFilename=Setup-CADGesture-v{#MyAppVersion}
CloseApplications=yes
; 注意：CloseApplicationFilter 是"检查哪些文件被占用"的通配符，默认 *.exe 已覆盖主程序，
; 无需显式设置。旧版安装器不认识该指令，已移除。
PrivilegesRequired=lowest
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; 用户配置在 %APPDATA%\CADGesture，与安装目录无关，卸载不删配置
UsePreviousAppDir=yes

[Languages]
Name: "chinesesimplified"; MessagesFile: "compiler:Languages\ChineseSimplified.isl"

[Tasks]
Name: "startmenu"; Description: "创建开始菜单快捷方式"; GroupDescription: "快捷方式:"
Name: "desktopicon"; Description: "创建桌面快捷方式"; GroupDescription: "快捷方式:"

[Files]
Source: "dist\CADGesture-x64.exe"; DestDir: "{app}"; Flags: ignoreversion
Source: "config\config.example.json"; DestDir: "{app}\config"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; 静默安装时 skipifsilent 会跳过启动；自动更新需要静默安装后拉起新版，
; 因此不带 skipifsilent，仅 nowait + postinstall。
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动"; Flags: nowait postinstall

; 卸载前终止运行中的主程序，否则 exe 被锁定删不掉（卸载残留）
[Code]
// 安装前自动结束运行中的主程序：解决 Restart Manager 关不掉托盘进程、
// 导致"文件被占用"无法覆盖安装的问题（先请求正常退出，再强制兜底）
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  // 第一遍：请求正常退出，给程序保存状态的机会
  Exec('taskkill.exe', '/IM {#MyAppExeName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  // 第二遍：强制结束（含子进程树），确保 exe 文件解锁可覆盖
  Exec('taskkill.exe', '/F /T /IM {#MyAppExeName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  // 0=已结束；128=本来就没有该进程；其他（如 1）=权限不足等原因
  if (ResultCode <> 0) and (ResultCode <> 128) then
    Result := '无法自动结束正在运行的 ' + '{#MyAppExeName}' + '（错误码 ' +
              IntToStr(ResultCode) + '）。请先手动关闭该程序后再安装。';
end;

procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
var
  ResultCode: Integer;
begin
  if CurUninstallStep = usUninstall then
    Exec('taskkill.exe', '/F /IM {#MyAppExeName}', '', SW_HIDE,
         ewWaitUntilTerminated, ResultCode);
end;
