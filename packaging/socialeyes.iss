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
