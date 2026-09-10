; CAD鼠标手势 - Inno Setup 安装脚本（纯直装向导）
; ============================================================
; 形态与 0.0.8 相同：Inno 原生中文向导直接把程序装到所选目录。
; 自动更新（0.0.10 起）：本直装形态不支持 Velopack 增量更新，
; 应用内"检查更新"改为提示到 GitHub Releases 手动下载新版安装包。
; （绿色版 *-portable.zip 仍由 vpk 产出，保留 Velopack 自更新能力。）
;
; 用法：ISCC.exe /DMyAppVersion=X.Y.Z cad_gesture.iss  (build.bat 自动注入)
; 产物：Releases\Setup-CADGesture-vX.Y.Z.exe
;
; 兼容：AppId 沿用 0.0.8 的固定 GUID → 老 Inno 安装版（含 0.0.8 自研 updater
;       静默下载本包）可无缝覆盖升级，配置在 %APPDATA% 不受影响。

; 版本号由 build.bat 经 /DMyAppVersion 注入
#ifndef MyAppVersion
#define MyAppVersion "0.0.10"
#endif
#define MyAppName "CAD鼠标手势"
#define MyAppExeName "CADGesture-x64.exe"
; AppId 固定不可更改（0.0.8 起沿用）：改了就变成"另一个软件"，覆盖安装失效
#define MyAppId "{{8E1F2A3B-4C5D-4E6F-8A7B-9C0D1E2F3A4B}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=CAD Gesture
AppPublisherURL=https://github.com/Inonvation/cad-gesture
DefaultDirName={localappdata}\Programs\CADGesture
; 显示目录选择页，允许用户更改安装位置（默认每用户目录，免 UAC）
DisableDirPage=no
DefaultGroupName={#MyAppName}
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=assets\icon.ico
Compression=lzma2/max
SolidCompression=yes
OutputDir=Releases
OutputBaseFilename=Setup-CADGesture-v{#MyAppVersion}
CloseApplications=yes
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
; onedir 打包：整个 dist\CADGesture-x64 目录（exe + _internal）递归装入 {app}
Source: "dist\CADGesture-x64\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs
Source: "config\config.example.json"; DestDir: "{app}\config"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: startmenu
Name: "{group}\卸载 {#MyAppName}"; Filename: "{uninstallexe}"; Tasks: startmenu
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; Tasks: desktopicon

; 静默安装时 skipifsilent 会跳过启动；自动更新需要静默安装后拉起新版，
; 因此不带 skipifsilent，仅 nowait + postinstall。
[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "立即启动"; Flags: nowait postinstall

; 安装/卸载前终止运行中的主程序，否则 exe 被锁删不掉
[Code]
function PrepareToInstall(var NeedsRestart: Boolean): String;
var
  ResultCode: Integer;
begin
  Result := '';
  Exec('taskkill.exe', '/IM {#MyAppExeName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
  Exec('taskkill.exe', '/F /T /IM {#MyAppExeName}', '', SW_HIDE,
       ewWaitUntilTerminated, ResultCode);
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
