; Inno Setup script for the SocialEyes desktop app. Run by packaging/build.py, which
; passes AppVersion, SourceDir (the PyInstaller folder), OutDir, Icon and Suffix.
;
; Installs per user (no administrator rights needed, e.g. on university laptops) into
; %LOCALAPPDATA%\Programs\SocialEyes. Uninstalling removes the program only: studies and
; data in Documents\SocialEyes are never touched.

[Setup]
AppId={{6C1E9A43-2B7F-4C3E-9C55-0F6B7E2D8A11}
AppName=SocialEyes
AppVersion={#AppVersion}
AppVerName=SocialEyes {#AppVersion}
AppPublisher=SocialEyes
DefaultDirName={autopf}\SocialEyes
DefaultGroupName=SocialEyes
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
PrivilegesRequiredOverridesAllowed=dialog
OutputDir={#OutDir}
OutputBaseFilename=SocialEyes-Setup-{#AppVersion}{#Suffix}
SetupIconFile={#Icon}
UninstallDisplayIcon={app}\SocialEyes.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible

[Tasks]
Name: "desktopicon"; Description: "Create a desktop shortcut"; Flags: unchecked

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{autoprograms}\SocialEyes"; Filename: "{app}\SocialEyes.exe"
Name: "{autodesktop}\SocialEyes"; Filename: "{app}\SocialEyes.exe"; Tasks: desktopicon

[Run]
Filename: "{app}\SocialEyes.exe"; Description: "Open SocialEyes"; Flags: nowait postinstall skipifsilent

[Code]
// The app's window is drawn by the Microsoft Edge WebView2 Runtime. It comes with
// Windows 11 and up-to-date Windows 10; without it the window can't open. Registry
// keys as documented by Microsoft ("Detect if a WebView2 Runtime is already installed").
const
  WebView2Client = '\Microsoft\EdgeUpdate\Clients\{F3017226-FE2A-4295-8BDF-00C3A9A7E4C5}';
  WebView2Download = 'https://go.microsoft.com/fwlink/p/?LinkId=2124703';

function WebView2Found(Root: Integer; Key: String): Boolean;
var
  Version: String;
begin
  Result := RegQueryStringValue(Root, Key, 'pv', Version) and (Version <> '') and (Version <> '0.0.0.0');
end;

function InitializeSetup(): Boolean;
var
  ErrorCode: Integer;
begin
  Result := True;
  if WebView2Found(HKLM, 'SOFTWARE\WOW6432Node' + WebView2Client) or
     WebView2Found(HKLM, 'SOFTWARE' + WebView2Client) or
     WebView2Found(HKCU, 'Software' + WebView2Client) then
    Exit;
  if WizardSilent() then
    Exit;
  if MsgBox('SocialEyes needs the Microsoft Edge WebView2 Runtime, which is not installed on ' +
            'this computer (it comes with Windows 11 and up-to-date Windows 10).' + #13#10#13#10 +
            'Open Microsoft''s download page now? Install it, then run SocialEyes. ' +
            'SocialEyes itself will still be installed.', mbConfirmation, MB_YESNO) = IDYES then
    ShellExec('open', WebView2Download, '', '', SW_SHOWNORMAL, ewNoWait, ErrorCode);
end;
