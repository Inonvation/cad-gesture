; CAD Gesture - Inno Setup 安装脚本
; ============================================================
; 简洁中文向导：欢迎 → 选目录 → 快捷方式 → 安装 → 完成。
; 每用户安装（免 UAC）；配置在 %APPDATA%，卸载不删。
;
; 用法：ISCC.exe /DMyAppVersion=X.Y.Z cad_gesture.iss  (build.bat 自动注入)
; 产物：Releases\Setup-CADGesture-vX.Y.Z.exe
;
; AppId 固定不可更改：改了就变成"另一个软件"，覆盖安装失效

; 版本号由 build.bat 经 /DMyAppVersion 注入
#ifndef MyAppVersion
#define MyAppVersion "0.0.11"
#endif
#define MyAppName "CAD Gesture"
#define MyAppExeName "CADGesture-x64.exe"
#define MyAppId "{{8E1F2A3B-4C5D-4E6F-8A7B-9C0D1E2F3A4B}}"

[Setup]
AppId={#MyAppId}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher=CAD Gesture
AppPublisherURL=https://github.com/Inonvation/cad-gesture
AppSupportURL=https://github.com/Inonvation/cad-gesture/issues
DefaultDirName={localappdata}\Programs\CADGesture
; 显示目录选择页，允许用户更改安装位置（默认每用户目录，免 UAC）
DisableDirPage=no
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
UninstallDisplayIcon={app}\{#MyAppExeName}
SetupIconFile=assets\icon.ico
; 左侧品牌图（深蓝底 + 八扇区圆环，generate_wizard_image.py 生成）
WizardImageFile=assets\installer_wizard.bmp
; 现代化向导样式（Inno 6+）
WizardStyle=modern
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
{ 用带「新建文件夹」的系统文件夹对话框替换 Inno 默认 Browse。
  Shell.Application.BrowseForFolder + BIF_NEWDIALOGSTYLE：
  现代对话框自带「新建文件夹」，在当前打开的位置下创建并选中。 }

const
  BIF_RETURNONLYFSDIRS = $00000001;
  BIF_NEWDIALOGSTYLE   = $00000040;

function BrowseForFolderW(const Title: string; var Folder: string): Boolean;
var
  Shell: Variant;
  FolderItem: Variant;
begin
  Result := False;
  try
    Shell := CreateOleObject('Shell.Application');
    FolderItem := Shell.BrowseForFolder(
      0, Title, BIF_RETURNONLYFSDIRS or BIF_NEWDIALOGSTYLE);
    if (not VarIsEmpty(FolderItem)) and (FolderItem <> Null) then
    begin
      Folder := FolderItem.Self.Path;
      Result := Folder <> '';
    end;
  except
    Result := False;
  end;
end;

procedure DirBrowseButtonClick(Sender: TObject);
var
  Dir: string;
begin
  Dir := Trim(WizardForm.DirEdit.Text);
  if (Dir = '') or not DirExists(Dir) then
  begin
    if Dir <> '' then
      Dir := ExtractFileDir(Dir);
    if Dir = '' then
      Dir := ExpandConstant('{localappdata}\Programs');
  end;
  if not DirExists(Dir) then
    Dir := 'C:\';
  if BrowseForFolderW('请选择安装文件夹（对话框内可新建文件夹）', Dir) then
    WizardForm.DirEdit.Text := Dir;
end;

procedure InitializeWizard();
begin
  { 覆盖「浏览」：系统对话框内可直接新建文件夹，建完即选中 }
  WizardForm.DirBrowseButton.OnClick := @DirBrowseButtonClick;
end;

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
