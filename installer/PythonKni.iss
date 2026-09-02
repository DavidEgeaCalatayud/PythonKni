#define MyAppName "PythonKni"

#ifndef AppVersion
  #error AppVersion must be supplied by scripts/build_windows_installer.ps1
#endif

#ifndef SourceDir
  #error SourceDir must be supplied by scripts/build_windows_installer.ps1
#endif

#ifndef OutputBaseFilename
  #error OutputBaseFilename must be supplied by scripts/build_windows_installer.ps1
#endif

[Setup]
AppId={{A2F8C86B-77F6-4C90-A0D6-36B38C4C1F56}
AppName={#MyAppName}
AppVersion={#AppVersion}
AppVerName={#MyAppName} {#AppVersion}
AppPublisher=PythonKni contributors
DefaultDirName={localappdata}\Programs\{#MyAppName}
DefaultGroupName={#MyAppName}
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputBaseFilename={#OutputBaseFilename}
Compression=lzma2
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
UninstallDisplayIcon={app}\PythonKni.exe

[Files]
Source: "{#SourceDir}\*"; DestDir: "{app}"; Flags: ignoreversion recursesubdirs createallsubdirs

[Icons]
Name: "{group}\PythonKni"; Filename: "{app}\PythonKni.exe"; WorkingDir: "{app}"
Name: "{group}\Uninstall PythonKni"; Filename: "{uninstallexe}"
