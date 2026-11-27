# Upgrading to 1.0

1.0 is not a rewrite. It freezes what already exists: the `.owcfg` format, the
enrolment protocol, the documented `outwarp` / `outwarp-server` commands and
flags, the signed update channel and the shape of `config.json` and the server
config (the contracts are pinned by tests, see `docs/contracts/`). Profiles,
client databases and tunnels from 0.x keep working. This page lists the few
things you do have to do.

## Before you start

- **Servers and clients can be upgraded in any order.** A 0.x client talks to a
  1.0 server and the other way round; the `.owcfg` and the enrolment protocol
  did not change.
- **You do not need to re-import profiles or re-issue client files.** The client
  migrates a single-profile `config.json` to the `profiles/` layout the first
  time it runs (idempotent, since 0.16).
- **Release candidates are pre-releases.** `outwarp update` and the in-app
  updater only follow the latest *stable* release, so they never offer an RC.
  To try one, install it by hand (the `.exe` from the release page on Windows,
  `install.sh` or the wheel on Linux). An RC install is offered the final 1.0.0
  when it ships.
- Coming from **0.11–0.14**? Those builds trust an older release key and cannot
  verify new releases: update once by hand (installer or `install.sh`), after
  that the in-app updater works again.

## The one breaking change: `outwarp-cli` is gone

`outwarp-cli` was the pre-1.0 name of the client command, deprecated since
0.15.0. Use `outwarp`. Nothing else was renamed.

Where it can still bite:

| What | What to do |
|---|---|
| **Linux systemd user unit** (`outwarp-client.service`) written before 0.15 still runs `outwarp-cli daemon`. After an in-place update (`sudo outwarp update`) the unit fails to start. | Run `outwarp service install` once; it rewrites the unit. `outwarp doctor` and `outwarp service status` flag it. Re-running `install.sh` migrates it by itself. |
| Your own scripts, cron jobs, desktop launchers or shell completions calling `outwarp-cli` | Replace the name with `outwarp`. `install.sh` removes the old completions. |
| **Windows** | Nothing. The executables were already `outwarp.exe` (CLI) and `outwarp-gui.exe` (GUI). |

## Upgrading

### Windows client or server

Run the new `OutWarpSetup-*.exe` (or use *Settings → Updates* once a stable 1.0
is published). Your profiles and settings stay in `%APPDATA%\OutWarp\`.

### Linux client

```
sudo outwarp update
outwarp service install      # only if you run the background service (see above)
outwarp doctor               # should report nothing pointing at outwarp-cli
```

or re-run the installer:
`curl -fsSL https://raw.githubusercontent.com/fcrespo07/OutWarp/main/installer/linux/install.sh | sudo bash -s -- --client`.

Installed from the Arch package? Update it with your package manager instead.

### Linux server

```
sudo outwarp-server update
sudo outwarp-server doctor
```

### Docker / Kubernetes server

Pull the new image tag and restart. The config directory (`/data`) is read as it
is; no migration step. Connected clients drop and reconnect during the restart.

## After upgrading

- `outwarp --version` / `outwarp-server --version` show the new version.
- `outwarp doctor` and `outwarp-server doctor` are clean.
- Connect, and check *Settings → About* (GUI) or `outwarp status`.

## If something goes wrong

Releases are immutable and every one stays on the releases page, so you can
reinstall the previous version at any time. Report problems with `outwarp doctor` output and the log
(`outwarp logs`) at <https://github.com/fcrespo07/OutWarp/issues>, with
anything private (endpoint, path prefix, keys) removed.
