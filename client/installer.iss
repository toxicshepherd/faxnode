; FaxNode Client – Inno Setup Installer
; Erstellt ein klassisches Windows-Installationsfenster.

#define MyAppName "FaxNode"
#define MyAppVersion "2.1.0"
#define MyAppPublisher "FaxNode"
#define MyAppExeName "FaxNode.exe"

[Setup]
AppId={{A7F3B2C1-9D4E-4F5A-8B6C-1D2E3F4A5B6C}
AppName={#MyAppName}
AppVersion={#MyAppVersion}
AppPublisher={#MyAppPublisher}
DefaultDirName={autopf}\{#MyAppName}
DefaultGroupName={#MyAppName}
OutputBaseFilename=FaxNode-Setup
OutputDir=output
Compression=lzma
SolidCompression=yes
WizardStyle=modern
SetupIconFile=faxnode.ico
UninstallDisplayIcon={app}\{#MyAppExeName}
PrivilegesRequired=admin
ArchitecturesInstallIn64BitMode=x64compatible

[Languages]
Name: "german"; MessagesFile: "compiler:Languages\German.isl"

[CustomMessages]
german.WelcomeLabel1=Willkommen bei FaxNode
german.WelcomeLabel2=Dieses Programm installiert den FaxNode-Client auf Ihrem Computer.%n%nDer Client verbindet sich automatisch mit dem FaxNode-Server in Ihrem Netzwerk und zeigt eingehende Faxe an.%n%nKlicken Sie auf Weiter, um fortzufahren.

[Tasks]
Name: "desktopicon"; Description: "Desktop-Verknuepfung erstellen"; GroupDescription: "Zusaetzliche Optionen:"
Name: "autostart"; Description: "Beim Windows-Start automatisch starten"; GroupDescription: "Zusaetzliche Optionen:"

[Files]
Source: "dist\{#MyAppExeName}"; DestDir: "{app}"; Flags: ignoreversion
Source: "faxnode.ico"; DestDir: "{app}"; Flags: ignoreversion

[Icons]
Name: "{group}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\faxnode.ico"
Name: "{group}\{#MyAppName} deinstallieren"; Filename: "{uninstallexe}"
Name: "{autodesktop}\{#MyAppName}"; Filename: "{app}\{#MyAppExeName}"; IconFilename: "{app}\faxnode.ico"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "FaxNode"; ValueData: """{app}\{#MyAppExeName}"""; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\{#MyAppExeName}"; Description: "FaxNode jetzt starten"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
Type: filesandordirs; Name: "{app}"
