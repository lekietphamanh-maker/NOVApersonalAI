; Nova's Windows installer (Inno Setup 6). CI builds it from the Desktop Edition folder:
;   ISCC.exe /DAppVersion=2.2.0 /DSourceDir=..\editions\Nova-Desktop packaging\nova.iss
; Installs for this Windows user only (no admin prompt) into %LOCALAPPDATA%\Programs\Nova. Nova's own data
; (memory, settings, models) lives in %LOCALAPPDATA%\Alfred and is kept by updates and by uninstalling.
; A silent install (/SILENT, what Nova's updater runs) closes the running Nova, replaces it and starts it again.

#ifndef AppVersion
  #define AppVersion "0.0.0"
#endif
#ifndef SourceDir
  #define SourceDir "..\editions\Nova-Desktop"
#endif

[Setup]
AppId={{4F6B57DC-1C3D-4292-903B-6E9363D187EC}
AppName=Nova
AppVersion={#AppVersion}
AppVerName=Nova {#AppVersion}
AppPublisher=Nova
DefaultDirName={localappdata}\Programs\Nova
DefaultGroupName=Nova
DisableProgramGroupPage=yes
DisableDirPage=yes
PrivilegesRequired=lowest
OutputDir=..
OutputBaseFilename=Nova-Setup
SetupIconFile=nova.ico
UninstallDisplayIcon={app}\Nova.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
CloseApplications=force
RestartApplications=no

[Tasks]
Name: "desktopicon"; Description: "Put Nova on the desktop"; GroupDescription: "Shortcuts:"

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[INI]
; Tells Nova's updater it was installed by this setup, so it may update itself in place.
Filename: "{app}\install.ini"; Section: "Nova"; Key: "version"; String: "{#AppVersion}"

[Icons]
Name: "{group}\Nova"; Filename: "{app}\Nova.exe"
Name: "{group}\Uninstall Nova"; Filename: "{uninstallexe}"
Name: "{userdesktop}\Nova"; Filename: "{app}\Nova.exe"; Tasks: desktopicon

[Run]
; Also after a silent update (no skipifsilent): Nova comes back by itself.
Filename: "{app}\Nova.exe"; Description: "Start Nova"; Flags: nowait postinstall
