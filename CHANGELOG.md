# Changelog

All notable changes to OutWarp are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: minor bumps may carry user-visible changes).

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
