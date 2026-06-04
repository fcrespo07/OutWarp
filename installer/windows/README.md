# OutWarp — Windows installer

This folder produces a single `OutWarpSetup-<version>.exe` that installs
the OutWarp client, server, or both on Windows 10/11.

It replaces the previous "install from source via `install.ps1`" flow.
The `install.ps1` here is now a thin downloader that fetches the latest
`OutWarpSetup-*.exe` from GitHub Releases and runs it with elevation.

## Layout

```
installer/windows/
├── README.md                 ← this file
├── install.ps1               ← bootstrapper: downloads + runs the .exe
├── outwarp.iss               ← Inno Setup script
├── bundle/                   ← (gitignored) wstunnel.exe + WireGuard installer
├── output/                   ← (gitignored) generated OutWarpSetup-*.exe
└── build/
    ├── build.py              ← orchestrator (UI → PyInstaller → ISCC)
    ├── outwarp-client.spec
    ├── outwarp-server.spec   ← GUI + dormant CLI in one bundle
    ├── version_info_client.txt
    └── version_info_server.txt
```

## Build prerequisites

Install on the build machine (any Windows 10/11 box):

- **Python 3.11+** — bring `python.exe` and `pip` onto `PATH`.
- **Node.js 18+** — only needed to compile the React UI with `esbuild`
  (via `npx`, downloaded transparently).
- **Inno Setup 6** — <https://jrsoftware.org/isinfo.php>. The orchestrator
  finds `ISCC.exe` automatically in its default install path.
- (Once, no extra step) PyInstaller — `build.py` installs it into the
  active interpreter if missing.

Optional:

- A code-signing certificate. The build script does not invoke `signtool`
  yet — when you have a cert, hook it into `build.py` between the
  `PyInstaller` and `ISCC` steps.

## End-to-end build

From the repo root:

```powershell
python installer\windows\build\build.py
```

That does, in order:

1. `scripts/build_ui.py` — pre-compiles the React/JSX UIs into
   `bundle.js` (client + server).
2. `scripts/fetch_bundled_binaries.py` — downloads `wstunnel.exe` and
   the WireGuard installer into `installer/windows/bundle/`.
3. `PyInstaller` × 2 — produces `dist/outwarp-client/` and
   `dist/outwarp-server/` (the latter holds both `outwarp-server-gui.exe`
   and the dormant `outwarp-server.exe` CLI sharing one `_internal/`).
   One-folder mode, mandatory because pystray is LGPL.
4. `ISCC outwarp.iss` — packs everything into
   `installer/windows/output/OutWarpSetup-<version>.exe`.

Skip steps individually if you're iterating:

```powershell
python installer\windows\build\build.py --skip-ui --skip-fetch
python installer\windows\build\build.py --no-installer       # stop after PyInstaller
```

## Bumping the version

The version surfaces in three places — keep them aligned:

1. `installer/windows/build/version_info_client.txt` and
   `version_info_server.txt` — PE metadata embedded in each `.exe`.
2. `installer/windows/build/build.py --version <new>` (or
   `$env:OUTWARP_VERSION = '0.1.1'`) — Inno Setup picks it up via
   `/DAppVersion`.
3. `client/pyproject.toml` and `server/pyproject.toml` — Python
   packages keep their own version; bump in sync.

## Publishing a release

Automated. `.github/workflows/windows-installer.yml` runs on every published
GitHub Release: it spins up a `windows-latest` runner, executes
`installer/windows/build/build.py` against the released tag, and uploads the
three `OutWarpSetup-*.exe` editions plus a merged `SHA256SUMS.txt` (wheel +
installer hashes) to the Release. So the normal flow is just:

1. `bash scripts/release.sh` (Linux) — builds wheels, tags, and creates the
   Release. Publishing the Release triggers the Windows installer build.

To build the installer for an existing tag (or rerun after a hiccup):

```bash
gh workflow run windows-installer.yml -f tag=v0.6.1
```

Manual fallback (on a Windows box, no Actions):

1. Tag the commit: `git tag v0.1.0 && git push origin v0.1.0`.
2. Run `python installer\windows\build\build.py --version 0.1.0`.
3. Upload `installer\windows\output\OutWarpSetup-*.exe` to the
   GitHub Release named `v0.1.0`.

End users download the `.exe` from the Release page and double-click
it. UAC asks for permission, Inno Setup takes over from there — no
PowerShell, no terminal commands, no `irm | iex`.

For unattended deployments (Intune, Ansible, kiosk imaging) the helper
script `scripts/install-from-release.ps1` automates the download +
silent-install flow. Regular users should not need it.

## What ends up installed

```
C:\Program Files\OutWarp\
├── wstunnel.exe                    ← shared transport binary
├── client\
│   ├── outwarp.exe                 ← tray app
│   └── _internal\…                 ← Python runtime + ui/ + resources/
└── server\
    ├── outwarp-server-gui.exe      ← admin GUI + tray (the default)
    ├── outwarp-server.exe          ← console CLI (dormant; not on PATH
    │                                  until enabled in Settings)
    └── _internal\…
```

The server install is GUI-first: nothing is added to PATH and no CLI shortcut
is created. The `outwarp-server.exe` console build ships alongside the GUI but
stays dormant until the user flips **Settings → "CLI de consola"**, which adds
`{app}\server` to the *per-user* PATH (HKCU, no admin). The GUI itself never
needs PATH — it finds `wstunnel.exe` in `{app}` and `wg.exe` in the WireGuard
install dir directly.

User data (config, logs, settings) stays under
`%LOCALAPPDATA%\OutWarp\` and survives upgrades / uninstalls.

## Smoke-testing the bundle without ISCC

If you want to verify a PyInstaller build before running Inno Setup:

```powershell
python installer\windows\build\build.py --no-installer
.\dist\outwarp-client\outwarp.exe
.\dist\outwarp-server\outwarp-server-gui.exe
.\dist\outwarp-server\outwarp-server.exe --help
```

Drop a `wstunnel.exe` next to the `.exe` (or set
`$env:OUTWARP_WSTUNNEL`) so the tunnel can start.
