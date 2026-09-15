# Changelog

All notable changes to OutWarp are documented here.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html)
(pre-1.0: minor bumps may carry user-visible changes).

## [Unreleased]

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

### Fixed
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
