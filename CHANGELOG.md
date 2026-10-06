# Changelog

All notable changes to OutWarp are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: minor bumps may carry user-visible changes).

## [Unreleased]

## [0.20.2] — 2026-10-06

### Changed
- **Client: sidebar.** Connection, Profiles and Log stay on top; Settings and
  About move to the bottom, apart. The profile card at the bottom now opens a
  menu to switch profile without leaving the screen (it asks first if the
  tunnel is up). Small badges on the icons: tunnel state on Connection, new
  errors on the Log (cleared on opening it), and a pending update on Settings,
  which replaces the separate "version available" button. In the narrow icon
  rail every entry has a tooltip. No existing text changed.
- **Client: Updates are back at the top of Settings**, above Appearance. The
  rest of the order from the regrouping (Appearance, Connection, Security,
  Startup and window, Advanced) is unchanged.

## [0.20.1] — 2026-10-05

### Fixed
- **Windows: "Update" closed the app without installing anything or reopening
  it** (B-050). The helper that runs the installer is now a `.cmd` that confirms
  it is alive before the client quits; if it does not, PowerShell is tried and,
  failing that, the app stays open and shows the error instead of vanishing.
  The installed client launches that helper, so from 0.19.0 or 0.20.0 the
  in-app update can still fail: install 0.20.1 by hand with the `.exe`; the fix
  takes effect on the update after that.

## [0.20.0] — 2026-10-02

### Added
- **Client window: health checks in About.** The checks behind `outwarp
  doctor` (profile, wstunnel, WireGuard tools, and on Linux the helper, tray and
  the rest) can be run from About and show what to do about each failure, with
  the command to copy. It only reports; nothing is fixed from the window.
- **Client TUI: check for updates (`u`).** It looks for a newer release and
  tells you to run `sudo outwarp update` (installing needs root, so, like the
  GUI on Linux, it does not do it for you).
- **Client TUI logs: export and clear the view.** `x` saves the lines the
  filters show to `outwarp-logs-<date>.txt` in the current directory and `c`
  empties the screen, like the GUI's export and clear (the log file itself is
  never touched).

### Fixed
- **Server enrolment: a rate-limited or oversized request got "connection
  aborted" instead of the answer** (B-049). The listener replied before reading
  the request body; it now reads and discards it first, so the client sees the
  429 or 400.
- **Client TUI: the logs screen showed nothing with recent Textual versions.**
  It passed `markup=` to `RichLog.write()`, which newer Textual no longer
  accepts (markup is a property of the widget, already on), so every line
  raised and was dropped. It also broke the filters.

### Changed
- **Client: Settings regrouped.** Appearance (language, theme), Connection
  (connect on launch, reconnect if it drops), Security (kill switch, allow
  TLS-intercepting networks), Startup and window, Updates, and Advanced
  (advanced mode, terminal UI and background service on Linux). Updates moved
  down, "advanced mode" moved out of Appearance, the technical subtitle became
  "Changes apply right away.", and a few labels were reworded (es/en). No
  setting or `settings.json` key changed.
- **Client TUI: the dashboard says what the GUI says.** The connection card
  now shows the profile, the route the connection took (direct, public DNS,
  proxy, alternate port: the same wording as the window) and whether the kill
  switch is on, and it fits a 24-row terminal better: one line per fact instead
  of a title plus a value. The header shows the version. The command palette
  (`^p`, English-only and unused) is gone from the footer. Settings gains a
  language picker (it was only reachable from the window), and its status line
  and the "Connecting…" / "attempt N" texts, which were still English, follow
  the language.
- **Client CLI: every message follows the interface language.** `outwarp`'s
  output (`import`, `connect`, `status`, `profile`, `logs`, `update`, `ui`,
  `service`, `uninstall`, `gui --install`), its `--help` texts and the whole
  of `outwarp doctor` (check names, details and remediation hints) were fixed
  English; they now go through the same tables as the tray and the TUI
  (English and Spanish, `OUTWARP_LANG` or the `language` setting decide).
  Commands to copy and paste stay literal. argparse's own words (`usage:`,
  `options:`, `-h`) are still the standard library's.
- **Server CLI and `setup` wizard: every message follows the interface
  language.** `outwarp-server`'s output (`add-client`, `list-clients`,
  `rotate-client`, `renew-cert`, `restart`, `status`, `uninstall`, `update`,
  `admin-token`, `web`, …), its `--help` texts and the whole of the interactive
  `setup` wizard (the transport explanation, every prompt and the final
  summary) were fixed English; they now go through the same tables as the
  tray and the TUI (English and Spanish; `OUTWARP_LANG` or the `language`
  setting decide). `outwarp-server doctor` (and the TUI's doctor screen) now
  does too: every check name, finding and suggested fix is translated; the
  commands to copy and paste are not. Logs stay in English. Error text raised
  from inside the library (a malformed config file, say) still arrives as
  written.
- **Server TUI: the leftovers are translated.** The QR window, the doctor
  screen's messages, the clients search box and the TLS, network and traffic
  cards still had fixed English; they follow the language now, and the card
  labels line up whatever the language. The command palette (`^p`, whose own
  text is English-only and which nothing relied on) is off and the header shows
  the version.
- **Server TUI: language picker.** The GUI and the panel had a language
  setting and the server TUI did not (only `OUTWARP_LANG`). `s` opens Settings
  with the same choice (automatic, English, Español), saved to the setting the
  other interfaces share.
- **Server TUI: test the port from the internet.** `p` on the dashboard asks a
  third-party host to connect back to the WSS port and says whether it is
  reachable (the GUI and the panel already could). The check lives in
  `operations.probe_external_port`, which the GUI now calls too.

## [0.19.0] — 2026-09-30

### Fixed
- **Windows: after "Update" the app closed and did not come back** (B-045).
  Setup relaunched the client, but the client starts hidden in the tray when
  "minimize to tray" is on (the default), so the window never reappeared. The
  relaunch now passes `--show-window`, and so does the "Launch OutWarp Client"
  step of a first install. The update helper also keeps a log
  (`%TEMP%\outwarp-update.log`), has Setup write its own (`Setup Log … .txt` in
  `%TEMP%`), and starts the client itself if Setup's relaunch did not.
- **Client: the connect button's glow was cut off by a square edge** (B-047).
  The connected ring's glow reaches past the 200 px box of the drawing, and an
  SVG clips what leaves its box; it now fades out freely.
- Release workflow: re-drafting an existing draft now moves its target commit
  too, so publishing it tags the commit the assets were built from.
- **Windows installer: a "Select Components" page with an empty drop-down**
  (B-046). The client-only and server-only installers have a single install type
  and nothing to choose; that page is skipped there. The full installer keeps
  it (client / server / both is a real choice).
- **Client: the log lines from before the window opened all showed as INFO**
  (B-044); an error logged during start-up looked routine. The level is now
  read from each line.
- Client: log rows no longer repeat the date and level inside the text (they
  have their own columns).

### Changed
- **Web panel and server GUI: the live throughput chart glides instead of
  stepping.** Same look as before, but the curve is laid out once per sample
  and slid left with the clock every frame; its right edge shows the moment
  1.5 s ago, always between two samples already received, so nothing waits
  for data and nothing jumps when a sample arrives. Measured in a browser:
  60 frames a second, a constant 12.65 px/s slide. (0.16.2's sliding chart
  felt slow: 2 s samples and a 4 s delay.)
- Client: the home chart keeps three minutes (was one) and shows its frame
  from the first second instead of a text placeholder. On a wide window the
  content keeps a readable width and centres. Profiles show the certificate
  model and expiry of each profile. About shows the version as a badge and has
  "What's new" and "Copy info" (version, system and Python in one line, for a
  bug report).

## [0.18.0] — 2026-09-30

### Fixed
- **The logo in the interfaces now matches the app icon.** The client GUI,
  the server GUI and the web panel drew thinner, steeper chevrons tinted with
  the text colour; the mark is now the `.ico` redrawn as SVG (right-angled
  chevrons, its light grey / dark grey / blue), 98 % pixel overlap with the
  512 px icon. The panel login's background mark uses it too, and no longer
  shows a bare `v` before the version loads.
- **Client: the connect dial's ring is closed when connected** (B-043). It drew
  a fixed 78 % arc left over from the design mock, which read as half-done
  progress. It is now a full ring with a slow glow.

### Changed
- **Client home screen redesigned** (first part of the GUI audit):
  - Connected: the profile is the headline, the exit IP and place go under it,
    the session time sits next to the state. Chips say which route carried the
    connection (direct, direct with public DNS, HTTP proxy, alternate port),
    the certificate model and whether the kill switch is on. A new
    "Switch profile" menu changes profile without going through Profiles.
  - Disconnected: the three static tiles (one of them false for profiles
    verified by a CA) become a "This connection" list: server, security, kill
    switch (with a link to Settings) and expiry.
  - Error: a plain-language hint for the kind of failure (server unreachable,
    certificate mismatch, expired or used token, wstunnel blocked, a network
    that lets none of the routes through); the raw message is folded under
    "Technical details"; a "View log" button; "Import a new .owcfg" only when
    it helps.
  - Narrow window: the dial goes above the text. Sidebar: a recognisable
    Settings icon, and the profile box opens Profiles. Texts speak to the user
    ("All your traffic leaves encrypted through your own server") instead of
    naming wstunnel and WireGuard.
- The client's status now carries the route that carried the connection
  (`route`) and the kill switch state, for the home screen.

## [0.17.0] — 2026-09-29

### Fixed
- **Web panel: the Traffic screen showed all zeros in Docker/Kubernetes**
  (B-041). The history database lived in `/var/lib/outwarp`, inside the
  `serve` container: the panel read an empty database of its own, and the
  pod lost the real one on every restart. It now lives next to the server
  config (`<config dir>/traffic.sqlite`, `/data` in the image), shared by
  `serve`, the panel and the TUI; an existing database is copied over once.
- **Web panel: things it showed that were not true** (B-042): a decorative QR
  code nobody could scan (removed), the client drawer's upload sparkline
  (the download one drawn backwards), "Top talkers · last hour" (it ranked
  lifetime counters), "All services healthy" even with the tunnel stopped,
  hard-coded `TLS 1.3 · ws`, `NAT MASQUERADE`, systemd unit names and
  `journalctl` inside a container or on Windows, and an "Add client" text
  saying the server generates the client's keys (it issues a one-time token;
  the client makes its own keys).
- Client: "Check for updates on startup" only checked when Settings was
  opened. It now checks once at start-up and flags a newer version in the
  sidebar.

### Changed
- **Web panel: Traffic screen redone.** A time chart per window (1 h: one bar
  a minute, 24 h: every 15 min, 7 d: hourly) with axis, tooltip and the time
  before the first sample shaded; peak is the real highest rate between two
  samples and the average covers only the time with data. With nothing
  recorded yet it says so instead of showing `0 B`. Per-client rows show
  sent/received and their share, and open the client.
- Web panel: the dashboard and Service screen say where the tunnel runs (this
  process, the `serve` container, systemd units or the Windows app) and what
  the page may do with it; the TLS card shows the mode (self-signed or Let's
  Encrypt via Caddy); empty states explain instead of `—`; errors from
  service actions and config changes are shown; focus outlines and ARIA
  states for keyboard and screen-reader use.
- Server: the traffic history takes its first sample when the tunnel starts,
  not a minute later.

### Added
- **Windows server via Docker Desktop, the recommended way**:
  `deploy/docker/compose.yml` + `.env.example` run the tunnel and the web
  panel like the Kubernetes pod (shared `/data`, network and process
  namespaces), with bridge networking so the same file works on Linux and on
  Docker Desktop (WSL 2). Guide in `deploy/README.md`.
- README: what OutWarp gets through and what it does not (a table per kind of
  network filtering, including deep packet inspection, which neither transport
  passes), supported platforms and known limitations. The server's setup
  wizard says the same when you pick the transport.

## [0.16.4] — 2026-09-29

### Fixed
- **Web panel updates did not reach the browser** (B-040). The panel served
  its files with no cache header, so Cloudflare and the browser kept running
  an old `bundle.js` after an update (0.16.3's fixes were invisible behind
  it). Everything is now `Cache-Control: no-store` and the page loads
  `bundle.js?v=<version>`, so an update is picked up at once.
- **The upgrade-path secret was still in wstunnel's own log line** for every
  accepted tunnel; it is now redacted where it is written (`serve.log`, the
  container log) and in the panel.
- Routine wstunnel lines (a client's idle pre-opened connections recycled
  every minute, probes that drop the TLS handshake) show as debug instead of
  flooding the Logs screen with ERRORs.
- Client: every close of the window now logs what it decided and why
  (`window close: close_to_tray=… tray_icon=… -> hide|quit`).

## [0.16.3] — 2026-09-29

### Fixed
- **Web panel: "Keep this session" works** (B-039). The page never checked for
  an existing session and always opened on the login screen, whatever the
  cookie said; it now goes straight to the dashboard while the session is
  valid. Behind a reverse proxy that reuses connections (Caddy, Cloudflare), a
  rejected request also left its body on the connection and made the next
  one — the login — fail with 501; every request now reads its body first.
- **Server dashboard: the live chart is the client's.** 0.16.2's scrolling
  chart ran several seconds behind and felt slow. It is now the client GUI's
  chart as is: one sample a second, drawn as it arrives, with a 64 KB/s scale
  floor. The panel samples every second (was 2 s).
- Small rates showed unrounded (`303.17889579135374 B/s`).

## [0.16.2] — 2026-09-28

### Fixed
- **Server panel in Docker/Kubernetes: flicker, empty Logs and a jerky chart**
  (B-037; 0.16.1 did not fix them). Every 2 s a partial status event blanked
  the endpoint, subnet and TLS cards until the next full fetch; the panel now
  merges status and the events carry all of it. In a container the panel is a
  separate process from `serve`, which only logged to stdout: `serve` now also
  writes `<config dir>/logs/serve.log` and the panel's Logs screen follows it,
  each line with its own time and level (wstunnel's too), colours stripped.
  The live chart places each sample at its own time and scrolls with the
  clock, so late or bunched samples (a proxy in front of the panel) no longer
  make it jump; readings a few ms apart no longer draw dips or spikes. When no
  live event arrives for 5 s (a proxy buffering or blocking the event stream)
  the page fetches the same data every 2 s instead of freezing.
- **The tunnel's upgrade-path secret was written to the log** in the
  "Starting wstunnel" line; it is now redacted there and in anything the panel
  shows.
- **Closing the client window still quit OutWarp** (B-038). 0.16.1 only
  handled the title bar's X: now Alt+F4 and the taskbar's "Close window" also
  leave it in the tray, and the first time it says so with a notification
  (on Windows 11 a new tray icon is hidden behind the ^ arrow). A Windows
  shutdown or sign-out still closes it. The client's Logs screen also stopped
  showing new lines after 2000; fixed.

## [0.16.1] — 2026-09-28

### Added
- **Closing the client window keeps OutWarp running in the background.** The
  window's X now hides it to the tray instead of quitting, so the tunnel stays
  up without keeping a window open; open it again from the tray icon, and
  choose "Quit" in the tray menu to exit completely. Turn it off in Settings →
  System → "Keep running when the window is closed". With no tray icon to come
  back from, the X still quits.

### Fixed
- **Server panel: flicker, missing logs and a jerky chart** (B-036). The page
  re-ran its whole start-up about 17 times a second, the live event stream
  stayed closed after logging in (so no logs, clients or status arrived), and
  the log watcher stopped after 2000 lines. The throughput chart now scrolls
  continuously instead of stepping every sample.
- **The server could fail to start** when its random upgrade-path secret
  began with `-`: wstunnel read it as an option (`unexpected argument '-v'`).
  The secret now goes to wstunnel as `--option=value` on both the server and
  the client, which also fixes installs that already have such a secret, and
  new secrets never start with `-` (B-035).

## [0.16.0] — 2026-09-28

### Added
- **Several connection profiles in one client**, one active at a time.
  Importing an .owcfg adds a profile and makes it active (re-importing the
  same one, for the same server and tunnel address, replaces it). Switch from
  the Profiles screen of the window, the tray's Profiles submenu, `P` in the
  TUI or `outwarp profile use <id>`; `outwarp profile list` and `outwarp
  profile remove <id>` complete the set. Switching disconnects the current
  tunnel and leaves the new profile disconnected. Existing installs are
  migrated automatically: the single `config.json` becomes the first
  profile under `profiles/`. Settings stay shared by every profile.
- **Language follows the system, and everything is translatable.** The
  `language` setting is now `auto` by default (the system's language, or the
  browser's in the web panel) or an explicit language; any text a language
  lacks falls back to English. Beyond the two web UIs, the tray, desktop
  notifications, the messages the app shows in its window and both TUIs
  (client and server) are translated, English and Spanish for now. Set
  `OUTWARP_LANG=en|es` to force one. The UIs name CJK fallback fonts and the
  TUIs pad columns by terminal cells, ready for Chinese.

### Fixed
- **Client GUI showed Spanish text with English selected** (B-033): some
  messages from the app and the tray menu were not translated.
- **Windows: after shutting down with OutWarp connected, WireGuard came back
  at boot with nothing behind it and the machine had no network** until
  WireGuard was killed by hand (B-034). Demand start (0.15.0) was not
  enough: Fast Startup restores running services, and nothing removed a
  leftover tunnel except the next connect. Now a leftover client tunnel is
  removed at boot and at every logon (two SYSTEM scheduled tasks the
  installer registers, running the internal `outwarp recover-tunnel`) and
  when the app starts. The server's tunnel and tunnels of your own
  WireGuard setup are never touched.

### Added
- **Disable a client without revoking it.** `outwarp-server disable-client
  <name>` takes the peer off the tunnel at once (hot-removed and dropped from
  `wg0.conf`) but keeps its name, IP, keys, PSK and expiry;
  `enable-client <name>` puts it back, with no re-enrolment and no new
  `.owcfg`. Also in the server GUI and web panel (a Disable/Enable button in
  the client detail and a "Disabled" filter), in the TUI (`d`) and in
  `list-clients`. A disabled client that redeems its enrolment token or has
  its keys rotated stays off until enabled. The config's client `state` gains
  the value `disabled`.

### Changed
- **Server dashboard: the live throughput chart and the per-client sparklines
  draw smooth curves**, like the client GUI's traffic chart, instead of a
  spiky polyline. The 2 s samples are drawn through a light moving average
  (the rates shown as numbers stay raw) and a Catmull-Rom curve whose control
  points cannot overshoot the centre axis. The chart's time label now says
  what it shows (`-120s`, 60 samples × 2 s) instead of `-60s`.

## [0.15.0] — 2026-09-26

### ⚠️ Update by hand once from 0.11–0.14
The release signing key changed: the previous one (`3E1FCD8BF652EC28`) was
lost. 0.11–0.14 only trust that key, so their built-in updater **refuses**
0.15.0 ("signature was made with a different key"). Install 0.15.0 by hand
once — the Windows installer over the existing install, or `install.sh` on
Linux; containers just pull the new image. From 0.15.0 on, updates verify
against a primary and an offline backup key, so losing one key no longer
blocks updates.

### Changed
- **Two trusted release keys.** Both updaters accept a signature from the
  primary key (`outwarp-release.pub`) or the offline backup
  (`outwarp-release-backup.pub`).
- **Signing and publishing work on Windows.** `scripts/sign_release.py` and
  `scripts/publish_release.py` (Python) replace the manual `minisign`/`gh`
  steps and `publish-release.sh`; `scripts/setup-release-signing.ps1` prepares
  a Windows machine. `install-from-release.ps1` is now plain ASCII, so Windows
  PowerShell 5.1 no longer misreads it.
- **Windows: a real command line.** The client now installs two programs,
  like the server: `outwarp-gui.exe` (the tray app, what the shortcuts open)
  and `outwarp.exe`, a console CLI (`outwarp status`, `outwarp connect`, …).
  Until now `outwarp.exe` was the tray app and silently ignored every
  argument (B-027). A bare `outwarp.exe` still opens the tray app, so old
  shortcuts keep working, and a start-at-boot entry from an older version is
  re-pointed at the GUI the first time it runs. `python -m outwarp` is the CLI.
- **Updates refuse releases without a signed manifest.** The fallback that
  accepted a release publishing no `SHA256SUMS.txt` is gone from both
  updaters; every release since 0.11.0 is signed, so nothing legitimate is
  affected.
- `outwarp-server restart` inside a Docker/Kubernetes container now reloads
  the running server (the `serve` process handles `SIGHUP`); the image runs
  `serve` as PID 1.
- The server's desktop GUI setup on Linux now installs the same system
  services as `sudo outwarp-server setup` and needs root (`sudo
  outwarp-server gui`). The domain + Caddy branch remains CLI-only.
- Development: UI tests (vitest) with a guard that fails when a committed
  `bundle.js` is stale, a pinned esbuild, SHA-pinned GitHub Actions,
  Dependabot, a `pip-audit` job, and `SECURITY.md` with the private reporting
  channel.
- The client UI bundle is about a third smaller: two unused design previews
  were still being compiled into it. No visible change.
- **Releases are drafted, then published once complete and signed.** GitHub
  release immutability is on, so wheels, Windows installers, `SHA256SUMS.txt`
  and its signature all go into a draft first; the Release workflow now also
  builds the Windows installers itself (no manual dispatch). The new
  `scripts/publish-release.sh` publishes only after checking every asset
  against the signed manifest.
- Repository cleanup now that it is public: old release notes, design specs
  and superseded plans removed; the resolved 0.12 audit moved to
  `docs/history/`.

### Fixed
- **Windows: uninstalling no longer strands a machine offline** (B-026). If
  the client had died with the kill switch engaged, the firewall kept
  blocking all outbound traffic after uninstall. The uninstaller now restores
  the policy (only when an OutWarp rule is still present), removes the rules,
  the client tunnel service and its key file.
- **Server: changing the WireGuard port from the panel no longer cuts every
  client off** (B-028). wstunnel kept forwarding to the old port and
  WireGuard was restarted on the old config file. Changes made from a panel
  started with `--config-dir` (the container) are also saved to that
  directory now instead of being lost.
- **Windows server: adding, revoking or rotating a client and `restart` wrote
  a Linux WireGuard config** (B-029), which WireGuard for Windows refuses.
  They now write the Windows one; `restart` no longer tears the tunnel down
  twice and, since wstunnel runs inside the server app, says to restart it
  from the tray instead of failing.
- **Docker/Kubernetes: `outwarp-server restart` really restarts** (B-030) —
  it used to report wstunnel and the enrolment listener as restarted without
  touching them.
- **Linux server GUI setup** (B-031): the tunnel no longer stops when the
  window closes, comes back at boot, and enrolment works.
- **TUI: `k` disconnects (or cancels a connection attempt) instead of
  quitting** (B-032).
- **Windows: other local users could read the client's WireGuard private
  key** (B-025). The tunnel's `.conf` under `C:\ProgramData\WireGuard`
  inherited read access for every user on the machine; the folder is now
  restricted to SYSTEM and Administrators before the key is written, and the
  client refuses to connect if that fails.
- **Web panel: "Keep this session in this browser" now keeps it.** The
  session cookie had no expiry, so the browser dropped it on close, and
  sessions only lived in the panel's memory, so any panel restart (an update,
  a pod reschedule) logged you out. Sessions are now stored on disk (only a
  hash of each session id, `panel_sessions.json`, 0600) and the cookie lasts
  30 days when the box is ticked. Rotating the admin token
  (`outwarp-server admin-token --rotate`) still ends every open session.
- **Web panel: the login form works with password managers.** Browsers and
  password managers now offer to save the admin token and fill it in.
- **Windows: WireGuard no longer comes back on its own after an unclean
  shutdown** (B-023). The tunnel service is now set to demand start right
  after it is installed; before, a machine switched off while connected
  booted with the tunnel up, no transport under it and no internet until
  OutWarp was opened.
- **Windows: a second launch no longer starts a second OutWarp** (B-024).
  The single-instance check read the Win32 error code unreliably, which could
  let two copies (and two tray icons) run at once. Opening OutWarp while it
  already runs now brings the existing window to the front instead of exiting
  silently.
- **A quarantined or blocked `wstunnel.exe` is reported, not crashed on.** The
  GUI used to die at startup when Defender had removed the binary; now it
  opens and shows the integrity banner. Connecting checks the binary before
  bringing WireGuard up and fails at once with a message pointing at
  Defender / Smart App Control, instead of retrying for about two minutes.
  The check runs before any network work, so the error shows straight away
  rather than after a "connecting" screen.

## [0.14.0] — 2026-09-15

### Changed
- **The client command is now `outwarp`** (Linux/pip; Windows already shipped
  `outwarp.exe`). `outwarp-cli` keeps working for **one release** as a
  deprecated alias that prints a single stderr line, because systemd units,
  launchers and shell completions on existing installs point at it and the
  in-venv updater does not rewrite them. `install.sh` migrates the user unit's
  `ExecStart=`, replaces the `outwarp-cli` completions with `outwarp` ones,
  and `outwarp service install` re-renders the unit; `outwarp doctor` gains an
  **Install** section that flags anything still on the old name and any
  second client install answering on `PATH` (a stale `/opt/pipx` venv at an
  older version was found doing exactly that). **The alias is removed in
  1.0.0.**
- `outwarp uninstall` now also removes the shell completions and the
  system-wide launcher/icon that `install.sh` writes.
- **Linux: GUI or TUI is a choice you can change after installing.**
  `install.sh` offers the graphical window + tray by default when it detects
  a desktop session (X11/Wayland socket) and skips it on headless boxes;
  `OUTWARP_CLIENT_GUI=1|0` answers for scripted installs. New subcommands:
  `sudo outwarp gui --install` adds the GTK/WebKit packages and pywebview to
  an existing install, `outwarp ui [auto|gui|tui]` shows/sets what the app
  menu opens, and `outwarp launch` (what the `.desktop` entry now runs)
  honours it — opening the TUI in your terminal emulator when the GUI is not
  wanted. `outwarp gui` without the stack says why and opens the TUI instead
  of failing at `webview.start()`. Both Settings screens expose the toggle
  (`preferred_ui` in `settings.json`); `outwarp doctor` gains a `gui` check.

### Added
- **End-to-end test in CI (`e2e/`), blocking.** Two Docker containers — the
  real `server/Dockerfile` image and a root client built from the checkout
  (pinned wstunnel, the privileged helper taken verbatim from `install.sh`) —
  walk the full user flow over the wire: `add-client` → `outwarp import`
  (enrolment through the tunnel port) → `connect` → WireGuard handshake →
  an HTTP page that only listens on the server's tunnel address → default
  route inside the tunnel → counters moving → the same token rejected a
  second time → SIGTERM leaves no interface or route behind. Runs locally
  with `e2e/run.sh` (`KEEP=1` keeps the containers). Not covered: Windows,
  systemd units, Kubernetes, the GUI.

- **Omarchy / Hyprland / Wayland integration for the Linux GUI**, verified on
  a live Omarchy 4 session (Hyprland 0.56, omarchy-shell):
  - The window gets a stable `app_id` (`outwarp`) — it used to be the Python
    script name, so no window rule or `StartupWMClass` could target it.
  - `outwarp ui --hyprland-rule` (run by `install.sh` as the desktop user)
    writes `~/.config/hypr/outwarp.lua` (`o.window(...)`, Hyprland ≥ 0.55) or
    `outwarp.conf` (`windowrulev2`, hyprlang) and hooks it from your config:
    the window opens floating and centred instead of tiled.
  - The tray is a StatusNotifierItem via pystray's AppIndicator backend and
    its icon/tooltip follow tunnel state in the Omarchy bar. For that the
    venv must see the distro's GObject bindings: `install.sh` now creates the
    pipx venv with `--system-site-packages` when the GUI is chosen, and
    `outwarp gui --install` flips the flag on an existing venv.
  - `notify-send` gets the app icon (`-i`); `libnotify` joins the GUI
    package set on every distro.
  - hicolor icons at 16–512 px (was a single 128 px file) and
    `StartupWMClass=outwarp` in the launcher entry.
  - `outwarp doctor` gains `tray` (backend + StatusNotifierWatcher on the
    bus) and `hyprland` (rule present) checks; `outwarp ui` reports both.
  - GUI `start_at_boot` on Linux registers `outwarp launch` (honours the
    GUI/TUI preference); XDG autostart is honoured by uwsm sessions.
  - CI matrix adds Python 3.14 (what Arch ships).

### Fixed
- **"Run as background daemon" no longer fights the UI that enabled it.**
  The TUI toggle ran `systemctl --user enable --now` next to its own live
  tunnel; the daemon's `wg-quick up` tore the TUI's interface down, the TUI
  reconnected and tore the daemon's down, and the link flapped every few
  seconds. Enabling is now a hand-over: the UI stops its manager, installs
  the unit, and becomes a viewer (status read from the interface); disabling
  gives the tunnel back. The GUI gets the same toggle (Settings → System);
  turning the service on also turns off the GUI's login autostart, and the
  reverse is refused, so there is never a second owner at login.
- **One tunnel owner at a time, on every surface.** The GUI's single-instance
  mutex is now shared by the TUI, `outwarp connect` and the daemon
  (`outwarp/ownership.py`): a second owner is told who has the tunnel (pid or
  the service) instead of bouncing its interface. A GUI/TUI opened while the
  service runs shows its status instead of starting a second tunnel. The unit
  gains `RestartPreventExitStatus=2 4` (no profile / owned elsewhere) so a
  misconfigured service no longer restarts every 10 s.
- The TUI service toggle now shows the real `systemctl` error (it truncated
  at 120 chars, hiding it behind the "Wrote …" lines), refuses without a
  profile, as root, or without a user session, and `loginctl` runs with
  `--no-ask-password` and no stdin so polkit can never paint a password
  prompt over the dashboard. `ExecStart=` now prefers the running venv's own
  `outwarp` over whatever `PATH` finds (an in-place update never creates a
  new shim, so the unit kept pointing at `outwarp-cli`).
- **`outwarp connect` honours settings.json** (kill switch, auto-reconnect,
  TLS-intercept tolerance) like the GUI/TUI/daemon; the daemon also honours
  the TLS-intercept toggle (the unit carries no flags). GUI/TUI keep an
  engaged kill switch across a restart when the switch is on, as the daemon
  already did.
- **Expired profiles fail fast everywhere.** Only the GUI checked; the TUI,
  `outwarp import/connect` and the daemon walked the whole reconnect ladder
  against a server that had pruned the peer. Import refuses an expired
  `.owcfg`, the manager goes straight to FAILED with the expiry date, and the
  TUI's failed screen says so.
- **Closing the GUI window now stops the tunnel** like the tray's Quit did;
  it used to exit leaving WireGuard, wstunnel and an engaged kill switch
  behind with no UI to undo them. On Wayland the title-bar minimise button
  hides to the tray (compositors have no iconify; on Hyprland it did
  nothing).
- TUI Settings gains the **kill switch** toggle (TUI-only installs had no way
  to enable it) and reports a corrupt `config.json` instead of "no profile
  imported yet". `install.sh` installs `nftables` for the client and
  `doctor` checks for `nft`, since the kill switch cannot engage without it.
- GUI settings are re-read from disk before each change, so a toggle flipped
  in the TUI or with `outwarp ui` while the window is open is no longer
  reverted. `install.sh` keeps a login-autostart entry the GUI wrote
  (`outwarp launch`) instead of deleting it on every upgrade.
- **Kill switch + hostname endpoint: reconnects no longer die at DNS.** With
  the switch engaged only the escape set is allowed out, so a profile whose
  endpoint (or proxy) is a hostname could not resolve it on the next attempt
  and ended in `FAILED` with no network. Every successful resolution is now
  remembered (`resolved_hosts.json`, next to the sticky-rung store) and used
  when the lookup fails, both for the rung's dial address and for the kill
  switch allowlist itself. DNS is deliberately *not* opened through the
  switch — that would leak every application's queries while the tunnel is
  down. Known limit: if the server's IP changes while the switch is engaged,
  the reconnect keeps failing until the switch is released.
- **Enrolment rate limiter: one client's bad token no longer locks everyone
  out.** Behind wstunnel's forward every request is the loopback peer, so the
  per-IP bucket was one shared bucket: a client retrying an expired token a
  few times pushed other clients' valid enrolments into `429` for a minute.
  Failures are now counted per presented token (3 strikes → 60 s
  `Retry-After` for that token only) with a wider global ceiling (20 distinct
  failures / 5 min) as the brute-force bound.
- **Tests no longer touch the developer's real client.** Both suites point
  platformdirs at a temp dir and the single-instance lock at a per-test
  name; `app.main()` tests used to append lines to
  `~/.local/state/OutWarp/log/outwarp.log` and bail on the lock of a running
  client.
- **The wstunnel command line is logged without its secrets.** The upgrade
  path prefix (the server's access credential) and any proxy password were
  written verbatim to `outwarp.log`, shown in the GUI/TUI log views and
  copied into diagnostic dumps.
- **Server dashboard: the per-client sparkline and the Home traffic chart
  could hide real traffic for minutes after a one-off spike.** Both used a
  peak-hold that decayed 5% per 2 s tick with no bound tied to how much
  history was actually on screen — a large transient (a speed test) could
  keep the Y-axis pinned high long after it ended, since how long the decay
  took to fall below the current rate grew with how much bigger the spike
  had been. Smaller-but-real ongoing traffic (a video stream, a call) then
  drew as a flat line even though the byte counters were genuinely moving.
  Replaced with a bounded peak-hold (`window.DSfmt.makeBoundedPeak`): it
  remembers the maximum of a fixed number of recent window-max samples
  instead of decaying indefinitely, so recovery time is capped (~66 s in the
  default per-client sparkline, regardless of the spike's size) while still
  smoothing genuinely bursty-but-steady traffic the same as before.

## [0.13.0] — 2026-09-12

### Changed
- **Enrolment goes through the tunnel port.** A v4 `.owcfg` no longer names
  a separate HTTPS enrolment URL: the client opens a wstunnel TCP forward to
  the server's loopback enrolment listener over the same public port the
  tunnel uses (walking the same fallback ladder), and wstunnel is restricted
  to exactly that destination on top of WireGuard's. One open port, in both
  transport branches, and the enrolment endpoint is no longer publicly
  discoverable — reaching it requires the secret upgrade path. The Caddy
  front drops its `/<prefix>-enroll` route. **Compatibility:** profiles
  issued by a server ≥ this release need a client ≥ this release (older
  clients report an unsupported profile version); `--embed-key` still works
  for old clients, and a new client still imports v3 profiles from an older
  server.
- **Linux (systemd): new `outwarp-enroll.service`**, installed by `setup`,
  (re)written by `restart`, removed by `uninstall`, shown by `status` and
  checked by `doctor`. **Migration:** after updating, run
  `sudo outwarp-server restart` once — it now re-renders both units from the
  current code, so a new wstunnel argv or a unit that did not exist before
  actually reaches systemd.
- **Client daemon / server `serve` exit when they give up.** `outwarp-cli
  daemon` exits 3 once the reconnect schedule is exhausted (FAILED) and
  `outwarp-server serve` exits 3 when the manager reaches ERROR, so
  `Restart=on-failure` / the container restart policy take over. The daemon
  only notifies a *lost* connection, not a boot-time miss, and with the kill
  switch enabled it no longer releases an engaged rule at startup.
- **Admin panel / GUI service controls follow who owns the transport.**
  `get_status().service_control` is `full` (this process runs wstunnel),
  `restart` (systemd units — restart only, via the same path as
  `outwarp-server restart`) or `none` (a panel next to a `serve` container);
  the Service screen disables what does not apply and says why.
- **Kubernetes manifests:** the liveness probe no longer hard-codes port 443
  (an `exec` probe checks wstunnel + wg0 instead — no more `tls handshake
  eof` line every 30 s in the pod log); `service.yaml` publishes the same
  port as the ConfigMap; optional `OUTWARP_ENROLL_PORT` (loopback only, never
  forwarded). The image sets `OUTWARP_PLATFORM=kubernetes` so a plain
  `docker run` no longer falls into the systemd platform.

### Fixed
- **Enrolment was dead on arrival in two common setups.** Self-signed
  branch: the listener bound a second public port (8444) that no home router
  forwarded — and nothing in the deploy docs, the ConfigMap, the panel or
  `doctor` mentioned it. Native systemd install: nothing ran the listener at
  all after the wizard exited. See "Changed" above; `doctor` now checks the
  listener on Linux and Windows.
- **Client: the tunnel's DNS and the connectivity ping went around the
  tunnel.** Since 0.12.1 `1.1.1.1` was excluded from `AllowedIPs` so a
  hostile-DNS rung could resolve the endpoint with WireGuard already up — but
  it is also every profile's default DNS and the target of the "handshake but
  no traffic through the tunnel" ping. Endpoints (and proxies) are now
  resolved in Python before WireGuard comes up and wstunnel is handed the
  address with the hostname kept as SNI/Host; nothing about the resolver
  escapes the tunnel any more.
- **Admin panel showed its start-up snapshot forever.** Clients enrolled by
  the `serve` container's listener (or added over `kubectl exec`) never
  appeared, or stayed "offline", until the panel restarted; it now reloads
  when the config or the client store changes on disk. Unenrolled slots are
  reported as `pending` rather than folded into "offline".
- **Admin panel "stop" next to a `serve` container took the live tunnel
  down** (`wg-quick down` under a process that never noticed) and "start"
  then spawned a second wstunnel that died on the taken port.
- **`ServerManager.add_client` left a token-bearing `.owcfg` in the process
  cwd** (`/` under systemd, `/data` in the pod); it returns the bytes from a
  temp dir, as `rotate_client_keys` already did.
- **`doctor` warned about an exposed loopback wstunnel on every domain-branch
  server**: `ss` prints the peer column as `0.0.0.0:*`, which a substring
  check mistook for the local bind.
- **`init` (Docker/Kubernetes) derived the server address assuming a /24.**

## [0.12.1] — 2026-09-11

### Fixed
- **Server: `--config-dir` was ignored by everything except the initial
  load.** `ServerManager`, the GUI bridge, the web panel and the enrolment
  listener re-resolved the config as `/etc/outwarp/server_config.json`, so a
  Docker/Kubernetes deployment (`--config-dir /data`) failed every
  add/revoke/rotate from the panel with "Config file not found" — a native
  systemd install never noticed. The CLI now exports `OUTWARP_CONFIG_DIR` for
  every component, and `ServerManager` keeps the path it was launched with.
  (Found by the author's homelab agent; the temporary volume-mount workaround
  at `/etc/outwarp` is no longer needed.)
- **Client: a failed enrolment printed a raw traceback** (CLI) or crashed the
  import modal/bridge (TUI, GUI) — `EnrollError` was not a `ConfigError`. It
  is now reported like any other import error, with the likely cause: the
  enrolment port (default 8444, separate from the tunnel port) not being
  reachable, and the `--embed-key` alternative.
- **Server: `add-client` now says that the enrolment port must be open** on
  the firewall/router alongside the tunnel port (self-signed branch), and how
  to fall back to `--embed-key` when it cannot be.
- **Linux: the TUI dashboard's 1Hz `wg show` poll flooded auth.log.** Every
  sample went through `sudo -n outwarp-priv dump <iface>`, and sudo logs a
  syslog line plus a PAM session open/close per invocation by default —
  thousands of lines an hour for as long as the dashboard stayed open. The
  installer's sudoers rule now scopes `!syslog, !pam_session` to just that
  helper invocation. **Migration**: re-run `install.sh client` to pick up the
  new sudoers rule.
- **Server: `ServerConfig.load()` took a write lock on `clients.sqlite` on
  every load**, not just the one-time JSON migration it exists for — `save()`
  always round-trips the client list back into the JSON `clients` array, so
  every load after the first re-triggered the migration's `BEGIN IMMEDIATE`
  transaction purely to find out it was already done. That serialized every
  read (every CLI command, every panel poll) against concurrent
  add/revoke/rotate writers for no reason. A lock-free pre-check now skips it
  in the overwhelmingly common case.
- **Client: wstunnel's own DNS bootstrap could stall on a dead tunnel.** A
  hostile-network rung tells wstunnel to resolve its endpoint via
  `--dns-resolver dns://1.1.1.1`, a query wstunnel makes itself — but with
  WireGuard already up and `AllowedIPs=0.0.0.0/0` capturing the whole host,
  that packet went into the tunnel the rung was trying to (re)build instead
  of out the normal route, and hung until timeout. `1.1.1.1` is now part of
  `escape_set()`'s exclusions whenever a hostile rung is in the ladder (always,
  by default), so it (and the kill switch allowlist) stay in sync with what
  wstunnel actually needs to reach.
- **Signature verdict was invisible outside the log file.** `verify_and_pin()`
  now returns a `TrustVerdict` (verified / unverified / key rotated) instead
  of only logging it; the CLI prints it after every `import`, the GUI bridge
  returns it from `import_profile()` and logs it to the in-app log panel, and
  the TUI import modal shows it as a toast.
- **Server web/GUI panel: the status badge lied whenever it wasn't the
  process that started the service.** `ServerManager.state` only changes via
  this instance's own `start()`/`stop()`; a companion admin process — the
  `outwarp-panel` container next to `outwarp-server serve` in the Kubernetes
  deployment, or `outwarp-server web`/`gui` run alongside a systemd-installed
  wstunnel unit with no `serve` daemon at all — never calls `start()`, so its
  dashboard reported "stopped" forever no matter how healthy the tunnel
  actually was. `ServerManager.effective_state` now reconciles that ambiguous
  default against the OS (`is_wstunnel_running()` / `is_wg_active()`, the
  same probes `outwarp-server status` already used) instead of trusting only
  this process's own history; `start()` also adopts an externally-running
  service instead of racing it for the same port. **Migration**: the
  Kubernetes manifest now sets `shareProcessNamespace: true` so the panel
  container's `pgrep -x wstunnel` can actually see the sibling container's
  process — re-apply `deploy/kubernetes/deployment.yaml`.
- **Server dashboard: the live throughput graph and per-client sparklines
  visibly "breathed"** even under steady traffic — both rescaled their Y axis
  to the exact instantaneous max on every 2s tick, so a sample scrolling out
  of the window constantly shrank or grew the whole chart. Both now use a
  peak-hold-with-decay ceiling (jumps up instantly for a real spike, only
  decays slowly) instead of the raw sliding-window max.
- **Server dashboard: per-client rx/tx rate used the browser's clock**
  against the server's polled counters — a backgrounded tab throttling timer
  delivery, or a batch of delayed SSE events landing in the same tick, could
  divide by a near-zero or huge `dt` and show a bogus spike or trough.
  `list_clients()` now stamps each sample with `sampled_at` (when the server
  actually took it), and the dashboard uses that instead of `Date.now()`.
- **Server dashboard/API and client GUI both still reported `"license":
  "MIT"`** (`get_app_info()` in both `api.py`, plus a hardcoded string in the
  server login screen and the client's About disclaimer) — stale since the
  project moved to PolyForm Noncommercial 1.0.0.

## [0.12.0] — 2026-09-11

A full security audit (13 findings across three severity groups) plus five of
its six proposed architecture refactors.

### Security
- **`.owcfg` profiles are now signed by the issuing server.** Every
  self-hosted server signs each profile it issues with its own Ed25519 key
  (minisign format, embedded in the profile itself); the client verifies on
  import and pins the server's key on first use — the same trust-on-first-use
  model an SSH host key fingerprint uses. A profile tampered with in transit
  (it travels by email, USB, messaging — channels this project doesn't
  control) now fails to import instead of silently connecting through
  whatever it was changed to. A server predating this feature just gets a
  warning, matching the release updater's existing fail-open precedent.
- **Every field of a `.owcfg` / `server_config.json` now has an explicit
  validation decision.** Previously only WireGuard keys, a handful of IPs and
  a few enums were checked; free-text fields — the server endpoint, the
  wstunnel upgrade-path prefix, and the fallback ladder's SNI override, Host
  header, User-Agent and proxy — reached a subprocess argument or HTTP header
  with nothing more than a bare string conversion. They're now checked for
  hostname/IP shape, or rejected outright if they carry an embedded control
  character (closing a header/argument-injection class, not just tightening
  hygiene).
- **The kill switch now actually works outside the desktop GUI.** It was
  wired only into the pywebview bridge — the Linux TUI and `outwarp-cli
  daemon` (the process systemd's `ExecStart=` actually runs) never engaged or
  released it at all. It's now owned by `TunnelManager` itself, so every
  surface gets it for free, and a rule left over from a crash is released on
  every startup rather than only the GUI's.
- **The kill switch allowlist was missing the server's own endpoint and every
  fallback-ladder rung.** Engaging it with an incomplete allowlist could trap
  a client unable to reconnect or even reach the server to fix it — the
  allowlist and the WireGuard tunnel's own bypass routes now come from the
  same single function.
- **`add-client` / `revoke-client` / `rotate-client` can no longer race.** Two
  near-simultaneous calls used to be able to read the same client list,
  allocate the same pool IP, and have the second silently clobber the first's
  new peer. The client registry moved off the server's main JSON config into
  its own SQLite table with real write-locked transactions — the race is
  closed by construction now, not by hoping every caller remembers to hold a
  lock.
- The unattended Windows install script (`install-from-release.ps1`) verifies
  the downloaded installer's SHA256 against the release manifest before
  running it — it previously elevated and ran whatever it downloaded with no
  integrity check at all.
- The admin panel gained a per-connection socket timeout and an SSE
  idle-heartbeat limit, closing a pre-authentication slow-loris-style denial
  of service where a client could hold a thread open indefinitely.
- The enrolment rate limiter now reads the last hop of `X-Forwarded-For` when
  the server is behind the Caddy front, instead of rate-limiting every client
  behind the proxy as if they shared one IP — previously five failed
  enrolments from any one client locked out everyone else.
- `rotate-client` no longer leaves the freshly rotated private key sitting in
  whatever directory the daemon happened to start in, unread and undeleted.
- `outwarp-cli uninstall` no longer kills its own process before it finishes
  — its `pkill` pattern matched its own argv, so it used to die mid-cleanup
  without touching the config, shortcuts, sudoers rule or venv.
- `outwarp-cli connect --config-dir` can no longer be used to bypass the
  root/Administrator check outside test mode.

### Added
- **Revoking a client now keeps its history.** Instead of deleting the row
  outright, a revoked client is marked as such — "never enrolled" and
  "enrolled, then revoked" are distinguishable again, and the freed IP is
  still immediately reusable.
- **Expiry is now enforced by the server, not the client.** A client whose
  `expires_at` has passed is excluded from every WireGuard config the server
  regenerates, and pruned automatically on every server startup. Previously
  the only enforcement was the `prune-expired` command (which someone had to
  remember to run) and the client's own refusal to import an expired profile
  — i.e. the party losing access enforced its own expiry.
- The server's platform layer (Windows / Linux / Kubernetes) now exposes one
  idempotent `reconcile()` instead of requiring every caller to sequence NAT
  setup, IP forwarding and the WireGuard install/restart in the right order
  by hand — the exact class of mistake that let the Windows NAT rule silently
  disappear on a restart.
- Regression tests extracted from `KNOWN_BUGS.md`'s resolved-bug prose (the
  NAT/forwarding invariants, a service-teardown race, and a TLS-verify-flag
  check) so they survive a refactor instead of only living in a comment.

### Fixed
- **Windows**: the domain/Caddy setup question is now asked on Linux only —
  offering it on Windows produced a Caddy configuration nothing on the host
  could read (`/etc/caddy/conf.d` doesn't exist there).
- **Linux**: the client's WireGuard config no longer lives in
  `/etc/wireguard`, where other WireGuard-aware VPN managers (e.g.
  omarchy-vpn) scan, adopt, and tear down anything they find — including
  OutWarp's own active tunnel.
- **Linux: the client could never connect as a regular user** (since 0.10.0).
  The handshake check behind the fallback ladder read `wg show … dump`
  directly, which needs `CAP_NET_ADMIN`; from the desktop user it silently
  returned nothing, so every rung was rejected with "no WireGuard handshake"
  while the tunnel was in fact up — and, because WireGuard had already
  captured `0.0.0.0/0`, the machine was left without internet until the
  attempt gave up. The read now goes through the privileged helper, like the
  TUI's stats sampler always did. The GUI throughput chart used the same call
  and was likewise blank.
- **Disconnecting during a connection attempt could orphan `wstunnel`.**
  `stop()` waited a bounded time for the ladder and then tore the tunnel
  down underneath it; the ladder went on to launch the next rung's `wstunnel`
  with nobody left to stop it, and that process later aborted with
  `failed printing to stderr: Broken pipe` (the "Process crashed: wstunnel"
  desktop notification). An in-flight connect is now cancelled cooperatively
  and cleans up on its own thread before `stop()` returns.
- **`outwarp-cli doctor` reported "sudoers rule ✗" on every Linux install.**
  It probed by running a `version` subcommand the helper never had; it now
  asks `sudo -l` whether the helper is allowed without a password, which
  executes nothing. A new "helper version" check warns when the privileged
  helper predates the client (wheel upgrades don't refresh it).
- **Kill switch: it blocked the tunnel itself.** On Linux the nftables chain
  never accepted output on the WireGuard interface — plaintext packets are
  filtered *before* WireGuard wraps them — so with the switch engaged no rung
  could ever verify and the user stayed offline until they disconnected by
  hand. On Windows a blanket "block outbound" rule was paired with an allow
  rule for the endpoint, but Windows evaluates block rules first, so even
  the reconnect was blocked. The Linux helper (`killswitch-on`) now takes
  the tunnel interface and accepts it (re-run the installer to refresh the
  helper; `doctor` tells you if it is stale); Windows now flips the firewall
  profile's default outbound action to Block and allows the endpoint(s) plus
  traffic from the tunnel's own address instead of adding a block rule.
  *The Windows path is untested on a real machine in this release.*
- **Kill switch never engaged for domain-based profiles.** The endpoint
  hostname was handed to the firewall unresolved and rejected, so the switch
  silently stayed open; the allowlist is now resolved with the same resolver
  the tunnel's own exclusions use, and CIDR bypass entries are accepted. The
  HTTP proxy host of a proxy rung is now part of the escape set too.
- **Kill switch engaged too late after a dropped tunnel.** The manager tore
  WireGuard down and slept the reconnect backoff (5–60 s) while still in
  `CONNECTED`; the switch only engaged on the next loop. It now engages
  before the teardown.
- **Connecting to a domain endpoint stalled ~49 s per rung.** Once WireGuard
  is up its DNS is routed into the tunnel, which carries nothing until a rung
  succeeds, so the pin check's hostname lookup hung until the resolver gave
  up. Direct endpoints are now resolved before WireGuard comes up and the
  pin check connects by address (hostname kept as SNI). wstunnel's own
  lookup can still hit this when the resolver cache is cold — tracked for
  0.12.1.
- **Server: `add-client` refused a name that had been revoked.** Soft-delete
  (0.12.0) kept the row, so re-issuing a device under its old name failed
  with "already exists"; a revoked name is free again (fresh keys, fresh IP).
- **Server GUI could erase secrets written by another process.** Changing
  the port or rotating the certificate from the GUI saved an in-memory
  snapshot of the config; an `add-client` run meanwhile (e.g. `kubectl exec`)
  had backfilled the `.owcfg` signing key on disk, which the GUI save then
  wiped — every client that had pinned it saw a bogus key rotation. Both
  saves now patch the freshest on-disk config under the cross-process lock.
- **Unsigned profile for an already-trusted server is now refused.** Once a
  server's signing key is pinned, an unsigned `.owcfg` for the same endpoint
  imported with only a log warning — stripping the signature off a tampered
  profile bypassed the pin. Profiles from never-seen servers (0.11.0 issues
  unsigned ones) still import with a warning.

### Migration
No breaking changes for existing installs. Profiles and server configs from
every prior version keep working; the client registry migrates automatically
from `server_config.json` into its own SQLite table the first time a 0.12.0
server loads it.

**Linux clients: re-run the installer** (`install.sh client`) after
upgrading. The privileged helper gained a new kill-switch contract
(interface argument, CIDR allowlist, `version` subcommand); a wheel-only
upgrade leaves the old helper in place, the kill switch then fails to engage
(fail-open, logged), and `outwarp-cli doctor` reports the stale helper.

## [0.11.0] — 2026-08-03

Three fixes to the security architecture, in the order they matter.

### Added
- **A domain branch for the server transport.** `outwarp-server setup` now asks
  whether you have a domain. If you do, Caddy holds port 443 with a real Let's
  Encrypt certificate and serves an ordinary web page, and the tunnel lives on a
  secret path behind it; wstunnel moves to a loopback listener. OutWarp writes
  and reloads the Caddy configuration itself, additively — it owns
  `/etc/caddy/conf.d/outwarp.caddyfile` and never rewrites a Caddyfile it did
  not write, so a box already serving other sites keeps working.

  This is the branch that survives a network inspecting TLS. The self-signed
  certificate is fine where the only obstacle is blocked UDP, but it has no
  chain to validate and is recognisable from the handshake alone — which is
  exactly the "corporate Wi-Fi, captive portals" case OutWarp exists for.

- **`tls.verify` in the profile format.** A profile behind a real certificate
  validates the chain against the system CA store instead of pinning, which is
  the only thing that survives a Let's Encrypt renewal — and it lets the client
  pass `--tls-verify-certificate` to wstunnel, so for the first time the
  transport is authenticated **in-band**. Until now the pin was checked on a
  separate probe connection while wstunnel itself connected to any certificate
  at all.

- **Public-key pinning (`tls.spki_sha256`).** The self-signed branch now pins the
  server's key rather than its certificate, so the certificate can be reissued
  without invalidating profiles already distributed. New
  `outwarp-server renew-cert` does exactly that (`--new-key` to replace the key
  too, which does invalidate everything).

- **Client enrolment — the server no longer generates client private keys.**
  `add-client` reserves the slot and mints a **single-use token valid for 15
  minutes**; the client generates its own WireGuard keypair on import and posts
  only the public half. A `.owcfg` stops being a permanent credential in transit,
  a server compromise no longer yields every client's identity, and an
  intercepted profile is *detectable* — the legitimate client's enrolment then
  fails with "already redeemed" instead of quietly succeeding for both.
  `--embed-key` keeps the old behaviour for clients too old to enrol.
  `--enroll-ttl` adjusts the window.

- **Signed update manifests (minisign).** `SHA256SUMS.txt` proves a download
  arrived intact, not who published it — it ships in the same GitHub release as
  the binary. Both updaters now verify a minisign signature over the manifest
  against a public key compiled into the client, and treat a missing signature
  exactly like a bad one. The private key is kept offline, never in a CI secret:
  a key CI can reach is a key an attacker who owns CI can reach. Process in
  `docs/RELEASE_SIGNING.md`.

  **0.11.0 is the first signed release** — key ID `3E1FCD8BF652EC28`, public
  half committed as `outwarp-release.pub`. Clients from this version on refuse
  an unsigned manifest; older ones have no key to check against and keep
  accepting one, which is why the fail-open path stays until they are out of
  circulation. Verify a download by hand with
  `minisign -V -p outwarp-release.pub -m SHA256SUMS.txt`.

- **New doctor checks**: the Caddy front's configuration validates, and the
  public endpoint actually serves a certificate the world will trust.

### Changed
- **The self-signed certificate looks like a certificate.** It now carries
  basicConstraints, keyUsage, extKeyUsage serverAuth and subject/authority key
  identifiers, and its validity dropped from 3650 days to 825. A CN-only,
  extension-free, decade-long certificate was a single-rule giveaway to anything
  parsing the handshake.
- **The browser `User-Agent` moved from its own ladder rung to every direct
  rung.** As a rung it cost a full failed attempt — handshake timeout plus ping
  probes, roughly 20 seconds — for a header that only reaches an L7 filter on the
  third try. Sending it everywhere is free and gets it in front of those filters
  immediately. It is camouflage against header rules, not against TLS
  fingerprinting; the ClientHello is still rustls'.
- The wstunnel server invocation is now defined in one place and rendered into
  both the foreground process and the systemd unit, which previously duplicated
  it and could drift.
- `revoke-client` also kills any outstanding enrolment token for that client.
- `list-clients` shows clients awaiting enrolment as such instead of "unknown".

### Fixed
- Profiles are only written after enrolment succeeds, so a failed import leaves
  the previous profile intact rather than a half-written one with no key.
- `wg0.conf` skips peers with no public key, so a reserved-but-not-yet-enrolled
  client cannot take the interface down.

### Migration
Existing installations keep working: v1/v2 profiles still import and connect,
and servers that predate the key pin keep issuing v1 profiles. To move to the
domain branch, re-run `outwarp-server setup` and re-issue client profiles.

## [0.10.0] — 2026-07-09

### Added
- **Automatic connection fallback ladder** — instead of a single connect
  attempt, the client now tries an ordered sequence of transport *strategies*
  until one actually carries traffic, then sticks with it. This hardens OutWarp
  on aggressive-DPI networks (captive/edu/corp Wi-Fi) where a single fixed
  transport gets silently blocked. WireGuard is brought up once and only the
  wstunnel front is cycled between rungs, so switching strategies is cheap.
  - Default rungs, tried in order: **direct** → **direct + public-DNS/IPv4-only
    flags** (`--dns-resolver dns://1.1.1.1 --dns-resolver-prefer-ipv4`, matching
    the proven legacy behaviour) → **direct + browser `User-Agent`** → **via HTTP
    proxy** (when one is configured in the environment) → **alternate WSS ports**
    (`server.fallback_ports`) → **server-provisioned rungs** (CDN front with
    `--tls-sni-override` + `Host` header, alternate cert-pin policy, etc.).
  - **Honest success check**: a rung is only accepted when a WireGuard handshake
    completes *and* a ping reaches the internet through the tunnel — a live
    wstunnel process alone is no longer treated as "connected" (that was the
    exact "connects but no traffic" failure on hostile networks).
  - **Per-network memory**: the rung that worked is remembered per network
    (SSID + gateway + resolver signature) and tried first next time, so a repeat
    visit connects on the first attempt instead of re-walking the ladder.
  - New optional `fallback` block in the `.owcfg` lets a server admin provision
    extra rungs (e.g. a CDN-fronted hostname); the client always generates its
    own default rungs on top, so existing profiles keep working unchanged.
  - Per-rung TLS pin policy (`pin` / `tolerate` / `none`) so a CDN-fronted rung
    whose cert rotates can rely on WireGuard key authentication instead of a
    pinned fingerprint.

## [0.9.0] — 2026-06-14

### Added
- **Remote web admin panel** — `outwarp-server web` serves the server dashboard
  over HTTPS so a headless VPS can be managed from a browser, not just the local
  console. It runs the same `Api` as the desktop GUI behind a token login: live
  status/throughput, client management (add/rotate/regenerate/revoke with
  `.owcfg` download), service control, live logs, Doctor with one-click
  auto-fixes, traffic history and TLS rotation. See `server/WEB_PANEL.md`.
  - `outwarp-server admin-token [--rotate]` mints the login token (only a salted
    scrypt hash is stored, `0600`).
  - Stdlib transport only (`http.server` + SSE) — no new runtime dependency, no
    CDN. Session cookie (`HttpOnly`+`Secure`+`SameSite=Strict`), CSRF header
    guard, rate-limited login with lockout, method allow-list, strict CSP.
  - The desktop GUI and the web panel now share **one** UI bundle and a
    transport shim, so the dashboard is identical in both; the pywebview window
    uses the native OS frame.
  - `apply_remediation` runs only the code-defined fix for a named Doctor check,
    never a free-text command. `get_traffic_history` exposes the existing
    SQLite snapshots.

## [0.8.0] — 2026-06-10

Linux UX overhaul + a major TUI feature pass on both client and server, plus
security fixes from a full code review.

### Security
- `operations.add_client()` now validates the client name before building the
  `.owcfg` path — a crafted name like `../evil` could previously escape the
  output directory when running as root via the CLI.

### Added
- **`outwarp-server rotate-client <name>`**: replaces a client's WireGuard
  keypair + PSK while preserving its IP and expiry, and writes a fresh
  `.owcfg` to redistribute. Also available in the server TUI (`t` on the
  clients screen, with QR modal for the new profile).
- **`outwarp-cli doctor`** + client TUI doctor screen (`d`): health checks for
  the wstunnel binary and version pin, WireGuard tools and kernel module, the
  privileged helper and its sudoers rule, the systemd user unit, and
  `notify-send` — with per-check remediation commands and auto-fix where safe
  (mirrors the server's doctor).
- **Desktop notifications on Linux** (`notify-send`, non-blocking): connected,
  connection failed, and connection dropped — wired into the GUI, the TUI and
  the headless daemon.
- **Application launcher on Linux**: `install.sh` now installs an
  `outwarp.desktop` entry (opens the TUI in your terminal) plus the app icon
  into hicolor/pixmaps, so OutWarp shows up in GNOME Shell, KDE, Rofi, etc.
- **Shell completions**: bash/zsh completions for `outwarp-cli` and
  `outwarp-server` via argcomplete, registered by `install.sh`.
- **Background service toggles in the client TUI settings** (Linux): enable or
  disable the user-level systemd daemon and `loginctl` linger
  (start-before-login) without leaving the TUI. `outwarp-cli service install`
  now auto-enables linger.
- **Log screen filters** (client TUI): `/` live text search, `e` errors-only,
  `w` warnings-and-up, `p` pause/resume the tail.
- **Import auto-scan** (client TUI): the import modal now scans `~/Downloads`,
  `~/Desktop` and `~` for `.owcfg` files and offers them as a list — typing an
  absolute path is the fallback, not the default.
- **rx/tx sparklines** in the client TUI traffic card (ping already had one).
- **Failed screen diagnosis** (client TUI): the last log lines are shown
  inline with an error-specific hint (TLS fingerprint mismatch, timeout,
  connection refused, missing wstunnel, …).
- **Expiry column + prune** (server TUI): the clients table shows each
  client's expiry date, and `P` revokes all expired clients in one action.
- **Clipboard copy** (client TUI): `c` on the dashboard copies the server
  endpoint.

### Fixed
- wstunnel `Popen` now uses `text=True` with explicit encoding (removes a
  manual decode path) and reader-thread exceptions are logged instead of
  swallowed; `add_peer_live()`/`remove_peer_live()` pass `CREATE_NO_WINDOW`
  on Windows like the rest of the wg subprocess calls.
- The tray icon failing to start on Linux (GNOME without the AppIndicator
  extension) now logs an actionable hint instead of crashing the process.

## [0.7.1] — 2026-06-10

### Fixed
- The Linux installer (`install.sh`) now installs the **pinned** wstunnel
  version instead of the latest GitHub release. Client and server must run the
  same wstunnel: the WebSocket-upgrade handshake format changed between releases,
  so a version mismatch fails the upgrade with HTTP 400 and the tunnel carries no
  traffic (the symptom is a tunnel that "connects" but only sends, never
  receives). `install.sh` previously fetched `latest` by default and silently
  kept whatever wstunnel was already on `PATH` — exactly how a client drifted to
  10.5.5 against a 10.5.2 server. It now installs the pinned version, and warns
  about (and re-heals) `/usr/local/bin/wstunnel` when it finds a different one.

### Changed
- The pinned wstunnel version now has a single source of truth,
  `installer/wstunnel-version.txt`, consumed by `scripts/fetch_bundled_binaries.py`
  (the Windows bundle) and by the docker-publish workflow (the server image
  build-arg); `installer/linux/install.sh` and `server/Dockerfile` mirror it.
  `server/tests/test_wstunnel_version_pin.py` fails the build if any path drifts.

## [0.7.0] — 2026-06-04

Hardening pass after a full code + UX audit, plus CI automation for the Windows
installer.

### Security
- `config.json` and `config.original.json` (which hold the client's WireGuard
  private key) are now written atomically at `0o600`. Previously they were
  created at the process umask — world-readable on a typical Linux box.
- The server's WireGuard config (Linux, Kubernetes and Windows platforms) goes
  through the same atomic `0o600` helper — no `0o644`→`chmod` window where the
  server private key is exposed.
- The DNS probe in `detect_hostile_network()` uses a random transaction ID
  instead of a fixed one, so an on-path attacker can't pre-forge a match.

### Fixed
- TUI no longer freezes: the client dashboard runs `StatsSampler.sample()`
  (subprocess `wg`/`ping`) in an executor instead of on the event loop, and
  `disconnect`/`reconnect`/`quit` off-load `manager.stop()` so the UI stays
  responsive during the watchdog-thread join.
- `reconnect.max_attempts` / `delays_seconds` are validated when parsing the
  `.owcfg` (a `max_attempts=0` no longer causes a silent instant failure).
- `top_talkers()` computes per-step `LAG()` deltas with reset-clamping instead
  of `MAX-MIN`, so an interface restart no longer shows a phantom multi-GB spike.
- Closed a race in `Api._replace_manager` (profile swap) via the new
  `TunnelManager.remove_listener()` — the old manager is detached before it can
  emit state changes that contradict the new one.
- The stats/latency loops join on stop instead of dropping the thread reference,
  preventing two loops from writing `self._stats` after a quick reconnect.
- Server `get_live_peers` failure-dedup state is guarded by a lock (was a bare
  module global, not thread-safe across the GUI/TUI pollers).

### Changed
- Tunnel state is now shown on the TUI dashboard's `StatusCard` — a disconnected
  (e.g. `auto_connect=off`) tunnel is no longer visually identical to a
  connected one.
- TUI colour tokens are centralised in `tui/tokens.py` (client + server) and
  aligned to the canonical `ui/styles.css` palette (`warn #ff8a3d`,
  `bad #ff4d6d`) — GUI and TUI no longer drift.
- The GUI `HostileBanner` is visually distinct from the `IntegrityBanner`
  (brand/info colour + shield icon in `auto` mode) so an automatic DNS-bypass
  doesn't read as an error the user must fix.
- The server TUI Logs screen tails `wg-quick@wg0` alongside `wstunnel`, so
  WireGuard handshake/interface failures are visible without leaving the TUI.
- Profile-validation messages are unified to English across config/TUI/GUI.
- The connecting stepper gains a final "ready" step to match the GUI; Doctor's
  "apply fix" binding is `f` (not `F`); the Doctor remediation command adapts to
  the host package manager (apt/dnf/pacman/zypper/apk); Help modal and the
  server's no-config screen are more actionable.

### Added
- `.github/workflows/windows-installer.yml`: on a published Release (or via
  `workflow_dispatch` against a tag) a `windows-latest` runner builds the
  full/client/server `OutWarpSetup-*.exe` editions and attaches them — plus a
  merged `SHA256SUMS.txt` covering wheels and installers — to the Release. The
  Windows `.exe` is no longer a manual step. Code-signing stays opt-in via
  `build.py`'s `OUTWARP_SIGN_*` env vars.
- Two tests for `run_daemon` (no profile → exit 2; start→stop→0).

## [0.6.0] — earlier

Daemon mode (`outwarp-cli daemon` + `service install|uninstall|status`), ~97×
faster connect (connection pooling + MTU), and anti-DPI groundwork
(`hostile_mode`, websocket keepalive, `:443` omission). See the project history
in git and the "Estado actual" section of `CLAUDE.md` for releases before 0.7.0.
