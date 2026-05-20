; OutWarp – Windows installer
; Build with:  ISCC /DAppVersion=0.1.0 installer\windows\outwarp.iss
; (or just run installer\windows\build\build.py — it invokes ISCC for you).
;
; Requires Inno Setup 6+ — https://jrsoftware.org/isinfo.php
;
; Layout the script expects (produced by build.py beforehand):
;   dist\outwarp-client\           PyInstaller one-folder for the client GUI
;   dist\outwarp-server\           PyInstaller one-folder for the server
;                                  (outwarp-server-gui.exe + dormant
;                                   outwarp-server.exe sharing one _internal)
;   installer\windows\bundle\wstunnel.exe
;   installer\windows\bundle\wireguard-installer.exe   (optional, prompts if missing)

#ifndef AppVersion
  #define AppVersion "0.1.0"
#endif

#define AppName        "OutWarp"
#define AppPublisher   "Ferran Crespo"
#define AppURL         "https://github.com/fcrespo07/OutWarp"
#define ClientExeName  "outwarp.exe"
#define ServerGuiExe   "outwarp-server-gui.exe"

#define RepoRoot       "..\.."
#define DistDir        RepoRoot + "\dist"
#define BundleDir      ".\bundle"

[Setup]
AppId={{C2C8C58A-9C8A-4B0E-9D29-7D6F8B6F0A11}
AppName={#AppName}
AppVersion={#AppVersion}
AppPublisher={#AppPublisher}
AppPublisherURL={#AppURL}
AppSupportURL={#AppURL}/issues
AppUpdatesURL={#AppURL}/releases
DefaultDirName={autopf}\OutWarp
DefaultGroupName=OutWarp
DisableProgramGroupPage=no
DisableDirPage=no
OutputDir=output
OutputBaseFilename=OutWarpSetup-{#AppVersion}
Compression=lzma2/ultra
SolidCompression=yes
WizardStyle=modern
PrivilegesRequired=admin
ArchitecturesAllowed=x64compatible
ArchitecturesInstallIn64BitMode=x64compatible
SetupIconFile={#RepoRoot}\client\outwarp\resources\app_icon.ico
UninstallDisplayIcon={app}\client\{#ClientExeName}
UninstallDisplayName={#AppName} {#AppVersion}

; If either the client or the server is running, Inno Setup pops a modal
; asking the user to close them before continuing — applies to install,
; upgrade and uninstall. Mutex names match the ones each app creates at
; startup for single-instance detection (see app.py / server_app.py).
AppMutex=Global\OutWarpClient,Global\OutWarpServer
; Same hint for the uninstaller phase specifically.
CloseApplications=yes
RestartApplications=no
WizardSmallImageFile=
LicenseFile=
; The PS1 one-liner downloads us; let it pass component/skip-wizard hints.
; e.g. OutWarpSetup-0.1.0.exe /COMPONENTS="server" /SUPPRESSMSGBOXES

[Languages]
Name: "english"; MessagesFile: "compiler:Default.isl"
Name: "spanish"; MessagesFile: "compiler:Languages\Spanish.isl"

[Types]
Name: "client";  Description: "Solo cliente (conecta a un servidor OutWarp existente)"
Name: "server";  Description: "Solo servidor (acepta conexiones de clientes OutWarp)"
Name: "full";    Description: "Cliente + servidor"

[Components]
Name: "client";        Description: "OutWarp Client (tray app)";                 Types: client full
Name: "server";        Description: "OutWarp Server (interfaz gráfica)";         Types: server full
Name: "wstunnel";      Description: "wstunnel.exe (transporte WebSocket)";       Types: client server full; Flags: fixed
Name: "wireguard";     Description: "WireGuard for Windows (driver + tools)";    Types: client server full

[Tasks]
Name: "desktopicon";     Description: "Crear acceso directo en el escritorio"; GroupDescription: "Accesos directos:"; Flags: checkablealone
Name: "startupclient";   Description: "Iniciar OutWarp Client al arrancar Windows"; GroupDescription: "Arranque automatico:"; Components: client
Name: "startupserver";   Description: "Iniciar OutWarp Server al arrancar Windows"; GroupDescription: "Arranque automatico:"; Components: server
Name: "runwizard";       Description: "Ejecutar el asistente de configuracion al finalizar"; GroupDescription: "Post-instalacion:"; Components: server

[Files]
; ── Client ───────────────────────────────────────────────────────────────
Source: "{#DistDir}\outwarp-client\*"; DestDir: "{app}\client"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; Components: client

; ── Server (GUI + dormant CLI share one bundle / one _internal) ──────────
Source: "{#DistDir}\outwarp-server\*"; DestDir: "{app}\server"; \
    Flags: ignoreversion recursesubdirs createallsubdirs; Components: server

; ── wstunnel binary (shared, lives in {app} so both client & server find it) ─
Source: "{#BundleDir}\wstunnel.exe"; DestDir: "{app}"; \
    Flags: ignoreversion; Components: wstunnel

; ── WireGuard installer (run on demand, see [Run]) ───────────────────────
Source: "{#BundleDir}\wireguard-installer.exe"; DestDir: "{tmp}"; \
    Flags: deleteafterinstall; Components: wireguard; Check: HasWireGuardBundle

[Icons]
Name: "{group}\OutWarp Client";        Filename: "{app}\client\{#ClientExeName}"; WorkingDir: "{app}\client"; \
    IconFilename: "{app}\client\_internal\resources\app_icon.ico"; Components: client
Name: "{group}\OutWarp Server";        Filename: "{app}\server\{#ServerGuiExe}";  WorkingDir: "{app}\server"; \
    IconFilename: "{app}\server\_internal\resources\app_icon.ico"; Components: server
Name: "{group}\{cm:UninstallProgram,{#AppName}}"; Filename: "{uninstallexe}"

Name: "{autodesktop}\OutWarp Client"; Filename: "{app}\client\{#ClientExeName}"; \
    WorkingDir: "{app}\client"; Tasks: desktopicon; Components: client; \
    IconFilename: "{app}\client\_internal\resources\app_icon.ico"
Name: "{autodesktop}\OutWarp Server"; Filename: "{app}\server\{#ServerGuiExe}"; \
    WorkingDir: "{app}\server"; Tasks: desktopicon; Components: server; \
    IconFilename: "{app}\server\_internal\resources\app_icon.ico"

; Startup shortcuts — point to Startup folder so the apps launch on login.
Name: "{autostartup}\OutWarp Client"; Filename: "{app}\client\{#ClientExeName}"; \
    WorkingDir: "{app}\client"; Tasks: startupclient; \
    IconFilename: "{app}\client\_internal\resources\app_icon.ico"
Name: "{autostartup}\OutWarp Server"; Filename: "{app}\server\{#ServerGuiExe}"; \
    WorkingDir: "{app}\server"; Tasks: startupserver; Components: server; \
    IconFilename: "{app}\server\_internal\resources\app_icon.ico"

; No [Registry] PATH entry by default: the server finds wstunnel.exe next to
; its bundle (see server_manager._find_wstunnel) without needing PATH, and the
; console CLI stays dormant. The user opts the CLI onto their per-user PATH from
; Settings → "Habilitar CLI de consola" (Api.set_cli_enabled), which writes
; HKCU\Environment — no admin, no system-wide pollution.

[Run]
; Install WireGuard if the user opted in and it's not already present.
Filename: "{tmp}\wireguard-installer.exe"; Parameters: "/S"; \
    StatusMsg: "Instalando WireGuard for Windows..."; \
    Components: wireguard; Check: NeedsWireGuardInstall; Flags: waituntilterminated

; Launch the server GUI at the end of setup (which kicks the setup wizard
; on first run if there's no server_config.json yet).
; shellexec (not the default CreateProcess): both apps ship a
; requireAdministrator manifest, and Inno runs postinstall entries with a
; non-elevated token — CreateProcess of an elevation-requiring exe fails with
; "code 740 (operation requires elevation)". ShellExecuteEx honours the
; manifest and elevates. shellexec also implies no-wait, so `nowait` is dropped.
Filename: "{app}\server\{#ServerGuiExe}"; \
    Description: "Lanzar OutWarp Server y abrir el asistente"; \
    Flags: postinstall skipifsilent shellexec; \
    Tasks: runwizard

; Launch the client at the end of setup if only the client was selected.
Filename: "{app}\client\{#ClientExeName}"; \
    Description: "Lanzar OutWarp Client"; \
    Flags: postinstall skipifsilent shellexec; \
    Components: client; Check: NotInstallingServer

[UninstallRun]
; Best-effort: stop the WireGuard tunnel service the server creates.
Filename: "sc.exe"; Parameters: "stop WireGuardTunnel$OutWarp-Server"; \
    Flags: runhidden; RunOnceId: "StopWGServer"
Filename: "sc.exe"; Parameters: "delete WireGuardTunnel$OutWarp-Server"; \
    Flags: runhidden; RunOnceId: "DeleteWGServer"

[UninstallDelete]
Type: filesandordirs; Name: "{app}\bundle"
; Logs + configs live under per-user %LOCALAPPDATA%\OutWarp and are kept
; intentionally so reinstalling preserves the user's profile / clients.

[Code]
function HasWireGuardBundle: Boolean;
begin
  Result := FileExists(ExpandConstant('{src}\bundle\wireguard-installer.exe'))
         or FileExists(ExpandConstant('{tmp}\wireguard-installer.exe'));
end;

function IsWireGuardInstalled: Boolean;
begin
  Result := FileExists(ExpandConstant('{commonpf}\WireGuard\wireguard.exe'))
         or FileExists(ExpandConstant('{commonpf32}\WireGuard\wireguard.exe'));
end;

function NeedsWireGuardInstall: Boolean;
begin
  Result := HasWireGuardBundle and (not IsWireGuardInstalled);
end;

function NotInstallingServer: Boolean;
begin
  Result := not WizardIsComponentSelected('server');
end;
