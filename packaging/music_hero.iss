; Instalador de Music Hero (Inno Setup 6). Lo compila packaging/build.py después de PyInstaller.
; Sin permisos de administrador: va a %LOCALAPPDATA%\Programs\Music Hero. El motor de generación no va aquí: la app
; lo instala la primera vez que hace falta en %LOCALAPPDATA%\MusicHero\engine (app/installer.py).

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

[Setup]
AppId={{6F3D2A91-4C5E-4B7A-9E21-7C8D5B0A1F42}
AppName=Music Hero
AppVersion={#AppVersion}
AppPublisher=Kobayashi82
AppPublisherURL=https://github.com/Kobayashi82/Music-Hero
DefaultDirName={localappdata}\Programs\Music Hero
DisableProgramGroupPage=yes
PrivilegesRequired=lowest
OutputDir=..\build\installer
OutputBaseFilename=MusicHero-Setup-{#AppVersion}
SetupIconFile=..\build\stage\music_hero.ico
UninstallDisplayIcon={app}\Music Hero.exe
Compression=lzma2/max
SolidCompression=yes
WizardStyle=modern
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
; la app no puede estar abierta al actualizar o desinstalar (win32.single_instance)
AppMutex=Local\MusicHero.play
CloseApplications=yes

[Languages]
Name: "es"; MessagesFile: "compiler:Languages\Spanish.isl"

[Tasks]
Name: "desktopicon"; Description: "Icono en el escritorio"; Flags: unchecked
Name: "autostart"; Description: "Abrir Music Hero al iniciar Windows (oculto: Ctrl+Alt+H lo muestra)"; Flags: unchecked

[Files]
Source: "..\build\dist\Music Hero\*"; DestDir: "{app}"; Flags: recursesubdirs createallsubdirs ignoreversion

[Icons]
Name: "{userprograms}\Music Hero"; Filename: "{app}\Music Hero.exe"
Name: "{userdesktop}\Music Hero"; Filename: "{app}\Music Hero.exe"; Tasks: desktopicon

[Registry]
Root: HKCU; Subkey: "Software\Microsoft\Windows\CurrentVersion\Run"; ValueType: string; ValueName: "Music Hero"; \
  ValueData: """{app}\Music Hero.exe"" --hidden"; Flags: uninsdeletevalue; Tasks: autostart

[Run]
Filename: "{app}\Music Hero.exe"; Description: "Abrir Music Hero"; Flags: nowait postinstall skipifsilent

[UninstallDelete]
; el motor (varios GB) se puede volver a instalar desde la app
Type: filesandordirs; Name: "{localappdata}\MusicHero\engine"

[Code]
procedure CurUninstallStepChanged(CurUninstallStep: TUninstallStep);
begin
  // abrir al iniciar Windows también se activa desde la app (Ajustes): quitarlo aunque no lo pusiera el instalador
  if CurUninstallStep = usUninstall then
    RegDeleteValue(HKEY_CURRENT_USER, 'Software\Microsoft\Windows\CurrentVersion\Run', 'Music Hero');
  if (CurUninstallStep = usPostUninstall) and not UninstallSilent then
    if MsgBox('¿Borrar también las charts generadas, los récords y los ajustes?' + #13#10 +
              '(Si vas a volver a instalarlo, mejor no: así no hay que generarlas otra vez.)',
              mbConfirmation, MB_YESNO or MB_DEFBUTTON2) = IDYES then
    begin
      DelTree(ExpandConstant('{localappdata}\MusicHero'), True, True, True);
      DelTree(ExpandConstant('{userappdata}\MusicHero'), True, True, True);
    end;
end;
