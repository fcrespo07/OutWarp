# OutWarp roadmap

Where OutWarp is going. This file tracks the larger improvements that did **not**
fit into a single release — either because they are big reworks, need external
resources (a paid certificate, an app-store account), or need hardware/network
setups we can't validate in CI.

## Before 1.0 — release gate

Decided by the author on 2026-09-14. **1.0.0 does not ship until every item
below is done.** The binding, more detailed version (acceptance criteria,
proposed implementation, what is explicitly *not* blocking) lives in
`CLAUDE.md` → "Criterio de 1.0.0"; keep the two in sync.

What 1.0 freezes: the `.owcfg` v3 format, the enrolment protocol, the
documented CLI surface (`outwarp` / `outwarp-server`), the signed update
channel and the config file shapes.
Breaking any of those after 1.0 is a `feat!:` → 2.0, or ships with a migration.

- [x] **End-to-end job in CI, blocking.** *(Landed 2026-09-15: `e2e/run.sh`; first GitHub-runner pass pending.)* Two Docker containers (the real
      `server/Dockerfile` image + a root client), full user flow: enrol over
      443 → connect → traffic through the tunnel → DNS routed inside →
      reused token rejected → clean disconnect. Spike first: `wg-quick up`
      inside Docker on a GitHub runner.
- [x] **Kill switch + hostname endpoint.** *(Done 2026-09-15 via a last-known-address cache; DNS stays blocked while engaged.)* Reconnect can't resolve the
      endpoint through the blocked LAN DNS → `FAILED` with no network.
- [x] **Rename the client command `outwarp-cli` → `outwarp`.** *(Done 2026-09-15; alias kept until 1.0.0.)* The client is
      what most people use, so it gets the short name; the server already
      carries its suffix, and the Windows executable is already
      `outwarp.exe`. Must land before 1.0 because the CLI surface freezes
      there. Ship `outwarp-cli` as a deprecated alias for one release (units,
      `.desktop` files and completions on existing installs point at it) and
      have `install.sh` / `service install` migrate them; drop the alias in
      1.0.0.
- [~] **Linux client GUI as a first-class option.** *(Code landed 2026-09-15 — installer default, `gui --install`, `ui`, `launch`, doctor check; real-desktop testing on X11/Wayland still pending.)* Installer offers the
      pywebview GUI by default on desktop sessions (TUI stays the headless
      path); tested on X11 and Wayland; `doctor` checks the GUI stack.
- [~] **Full Omarchy compatibility** *(2026-09-15: window app_id + Hyprland rule, SNI tray with state icon, notification icon, system-site-packages venv, doctor checks, Python 3.14 in CI — all verified on a live Omarchy 4 session; clean-install run still pending.)* (Arch + Hyprland/Wayland + waybar +
      mako + systemd + pacman). Not just "it installs" — once installed it
      has to feel native: clean install via the `pacman` path; tray icon in
      waybar (SNI/appindicator) that **changes with tunnel state** and reads
      well at bar size in light and dark themes, with a working menu; GTK
      window under Wayland with a stable `app_id`, own icon, floating by
      default (documented Hyprland `windowrule`); launcher entry with icon
      that opens the GUI; mako notifications with icon; session autostart
      (user unit + linger or Hyprland autostart — pick one); nftables kill
      switch; `doctor` all green including a Wayland tray check. CI matrix
      must cover the Python version Arch ships at release time. An AUR
      `PKGBUILD` is the native follow-up (1.x, see "Native Linux packages"),
      not a blocker.
- [ ] **JS test runner (vitest) + bundle guard.** Pure-logic tests for the
      dashboard helpers (`makeBoundedPeak`, formatters) and a test that fails
      when `bundle.js` is stale. No ES-module rewrite of the UI.
- [x] **Retire the unsigned-manifest fallback** *(done in 0.15.0)* in both updaters
      (fail-closed; see "Security follow-ups").
- [ ] **Honest README and wizard about DPI.** Replace the "corporate
      networks / captive Wi-Fi" claim with the adversary table (self-signed:
      UDP-blocked only; ACME branch: also certificate inspection; neither:
      TLS fingerprint / Upgrade DPI). ACME as the recommended path in `setup`.
      Add "Supported platforms" and "Known limitations"; drop the "not yet
      ready for production" banner.
*Added by the author on 2026-09-25:*

- [ ] **No open 🔴 bugs in `KNOWN_BUGS.md`** on release day (today: none; B-023 and B-025 fixed 2026-09-26).
      The 0.14.0 partial-audit findings move into `KNOWN_BUGS.md` so this
      gate covers them.
- [ ] **Enable/disable clients from the dashboard.** A reversible `disabled`
      state, distinct from the final `revoked`: the peer leaves `wg0.conf`
      but keeps name, IP, keys, PSK and expiry. GUI, web panel, TUI and CLI
      (`disable-client` / `enable-client`, names TBC).
- [x] **Study: handshakes vs. remote-desktop drops.** *(Closed 2026-09-26
      with no change: RDP is stable, and Sunshine/Moonlight through OutWarp
      measured 31 ms average network latency.)* Find out whether
      handshake frequency drops long RDP sessions and lower it if so. WG's
      ~120 s rekey is protocol-fixed; ours to look at: `PersistentKeepalive`,
      the WebSocket ping, the wstunnel watchdog, proxy idle timeouts, TCP
      head-of-line blocking. Reproduce with a real RDP session first.
- [ ] **General UI/UX polish** across client/server GUI, web panel and TUIs.
- [x] **Less painful dashboard login.** *(Done 2026-09-26: the admin token
      stays; "keep this session" now really persists — cookie Max-Age +
      hashed sessions on disk bound to the current token — and the form works
      with password managers.)*
- [ ] **Windows server via Docker as the recommended path.** Docker Desktop
      (WSL2) + the `server/Dockerfile` image, a ready `compose.yml` and a
      guide in `deploy/README.md`; native SCM stays as the alternative. The
      image is already published to ghcr.io — make sure it is pullable.
- [ ] **Multiple (non-simultaneous) profiles in one client.** Moved out of
      "not blocking": it changes the `config.json` shape that 1.0 freezes.
      See "Multi-profile support" below.
- [ ] **UI in 5 languages**, not just Spanish and English: English,
      Mandarin Chinese (Simplified), Spanish, French and Portuguese. All
      surfaces (GUIs, web panel, TUIs, CLI, notifications), system-language
      detection plus a manual picker, CJK fallback font (Geist has no CJK
      glyphs), native-speaker review. Moved out of "not blocking".
- [ ] **General audit right before 1.0** (security, UI/UX, bugs,
      robustness) on the release candidate; critical/high findings fixed
      before shipping, the rest explicitly deferred to 1.x.
- [ ] **Signed release after a quiet cycle.** `SHA256SUMS.txt.minisig` on
      release day, after the last 0.x has run 2–4 weeks in production without
      a hotfix.

### Execution order (agreed 2026-09-26)

Each phase ends in a published 0.x release (draft → sign → publish). Three rules decide the order:
- whatever 1.0 freezes lands first;
- infrastructure (tests, i18n) comes before content;
- translations come after the polish pass, once the strings are final.

Items marked *(added)* joined the gate with this plan. 👤 marks a task for the maintainer: real hardware, signing or native speakers.

- **Phase 0 — Clean base → 0.15.0.**
  - Move the 0.14.0 audit findings into `KNOWN_BUGS.md` and fix the critical and high ones.
  - vitest plus the bundle guard.
  - Retire the unsigned-manifest fallback.
  - *(added)* Public-repo hygiene: `SECURITY.md`, secret scanning and push protection, Dependabot, SHA-pinned actions in the release workflows, `pip-audit` in CI.
  - *(added)* Use 0.15.0 as the rehearsal of the immutable-release flow.
- **Phase 1 — What freezes → 0.16.0**, in this order:
  1. Enable/disable clients, with an e2e case.
  2. i18n infrastructure, en/es only.
  3. Multi-profile.
- **Phase 2 — Product → 0.17.0/0.18.0.**
  - UI/UX polish, ending in a string freeze.
  - Windows server via Docker, which can run in parallel with any phase.
  - Honest README and wizard.
  - 👤 Real-desktop Linux GUI testing and a clean Omarchy install.
- **Phase 3 — Languages → 0.19.0.**
  - zh-Hans, fr and pt.
  - *(added)* A missing-key test and long-string layout screenshots.
  - 👤 Native review.
- **Phase 4 — Freeze → 1.0.0-rc.1.**
  - *(added)* Contract reference docs and **contract tests**: CLI surface snapshot and JSON schemas.
  - Drop the `outwarp-cli` alias; *(added)* review the remaining 0.x shims.
  - *(added)* 0.x → 1.0 upgrade tests in e2e.
  - *(added)* Windows installer smoke test in CI.
  - General audit on the RC commit, with an rc.N release for each critical fix.
  - *(added)* Upgrade guide.
- **Phase 5 — 1.0.0.**
  - 👤 The last RC runs 2–4 weeks in production without a hotfix.
  - No open critical bugs.
  - 👤 The maintainer signs and publishes.

Explicitly **not** blocking 1.0: the Authenticode certificate (money, not
quality — SmartScreen is documented as a known limitation),
split tunnelling, DDNS, server auto-update, metrics, mobile.

## Shipped in 0.7.x

- **Textual TUI** (`outwarp-cli tui` / `outwarp-server tui`): full terminal
  UI for client and server, sharing the same `TunnelManager` / `ServerManager`
  backend. Shipped in 0.5.0, hardened in 0.7.0.
- **Daemon mode + systemd user unit** (`outwarp-cli daemon` / `service
  install|uninstall|status`): headless background client managed as a
  systemd user service. Shipped in 0.6.0.
- **`rotate-client` subcommand**: generates a new WireGuard keypair + PSK
  for an existing client without changing its IP or expiry. Shipped in 0.7.2.

## Shipped in 0.3.0

These landed as code with tests:

- **WireGuard preshared keys (PSK).** Per-client symmetric key generated by the
  server, carried in the `.owcfg` and both `[Peer]` blocks. Optional and
  backward compatible. Hardens the handshake against record-now/decrypt-later.
- **Expiring profiles.** `add-client --days N` stamps an expiry into the
  `.owcfg`; the client refuses to import or connect an expired profile and
  `prune-expired` revokes them server-side.
- **Update integrity check.** `build.py` publishes `SHA256SUMS.txt`; the in-app
  updater verifies the downloaded installer's SHA-256 before launching it.
- **Transport fallback ports.** The client tries the primary WSS port, then any
  `server.fallback_ports`, using the first reachable one.
- **Connect-on-launch is now opt-out.** `auto_connect` setting (default on),
  skipped for expired profiles.
- **Linux kill switch.** nftables-backed parity with the existing Windows one.
- **Code-signing hook (scaffold).** `build.py` signs the installers when a cert
  is configured via `OUTWARP_SIGN_PFX`/`OUTWARP_SIGN_PASS` or
  `OUTWARP_SIGN_SHA1`; a logged no-op otherwise.

## Planned — larger reworks

### Multi-profile support
**Part of the 1.0 gate since 2026-09-25** (non-simultaneous: one active
tunnel at a time).
Today the client holds a single active `config.json`. The API methods
(`list_profiles`, `set_active_profile`, `remove_profile`) exist as single-profile
stubs so the UI renders uniformly; the real work is a profile store on disk
(a `profiles/` subdirectory with one `config_<id>.json` per entry), a
per-profile `TunnelManager`, a switcher in the UI and tray, and a migration for
the current single-profile layout.

### Split tunnelling (per-app / per-domain)
Bypass IPs already carve routes out of the tunnel. True per-application routing
is OS-specific and substantial: WFP app-ID filters on Windows, cgroup/`fwmark`
+ policy routing on Linux. Per-domain needs a resolver hook.

### More languages
i18n lives in `ui/shared.jsx` (`STR`) and `ui/srv-data.jsx` (`SRV_STR`),
currently `es`/`en`. Adding a language is a full key translation per file.

## Planned — server side

### Dynamic DNS in the domain branch
The ACME branch shipped in 0.11.0: with a domain, Caddy fronts port 443 with a
real certificate and OutWarp generates and reloads its configuration. What is
still missing is the dynamic-DNS half — a server on a residential connection has
to keep its A record pointing at a changing IP by itself. Deferred because every
DDNS provider has a different API and the branch is fully usable today for
anyone with a static IP or an existing DDNS client.

### Server auto-update
The client auto-updates; the server (a system service) does not. Auto-applying a
service update is riskier and needs a tested rollback path.

### Prometheus / metrics endpoint
`wg show` already exposes per-peer transfer counters (surfaced in `list-clients`
and the GUI). An opt-in `/metrics` text endpoint would let Grafana scrape them.
Deferred because it adds a listening socket = extra attack surface to design
carefully (bind address, auth).

## Planned — security follow-ups

### Retire the unsigned-manifest fallback
Done in 0.15.0: both updaters are fail-closed. Every release since 0.11.0 is
signed, so a release without a signed `SHA256SUMS.txt` is always rejected.

### uTLS / ClientHello mimicry
The domain branch fixes what the certificate looks like, and the browser
`User-Agent` covers L7 header rules, but the TLS fingerprint itself is still
rustls' — a JA3/JA4 that matches no browser. Fixing it means replacing the
transport, since wstunnel does not do ClientHello mimicry. That is a rewrite of
a layer, not an increment, so it is deliberately not scheduled. Note that the
`--tls-ech-enable` flag wstunnel already exposes would hide the SNI when the
front supports ECH, which is a cheaper partial step worth evaluating first —
but only against a real DPI network; CI cannot simulate one, and ECH does not
change the JA3 either. Decision (2026-09-14): the transport rewrite stays
unscheduled; the 1.0 answer is an honest README (see "Before 1.0").

### Signature verification in `install.sh`
The Linux bootstrap checks the wheel against `SHA256SUMS.txt` but not its
signature — it would need `minisign` present before OutWarp is installed. Low
priority: that path is `curl … | sudo bash`, so it already extends full trust to
GitHub. The in-app updaters, which run unattended, do verify.

## Distribution — needs external resources

- **Release signing (minisign).** ✅ Done in 0.11.0 — key ID
  `3E1FCD8BF652EC28`, public half committed as `outwarp-release.pub` and
  compiled into both updaters. Every release from 0.11.0 on must ship a
  `SHA256SUMS.txt.minisig`; see `docs/RELEASE_SIGNING.md` for the per-release
  step. This is *not* a substitute for the Authenticode certificate below —
  it authenticates the update channel, not the installer SmartScreen sees.
- **Code signing (a real certificate).** The build hook exists; an OV/EV
  Authenticode cert (paid, identity-verified) is needed to actually kill the
  SmartScreen/UAC warning. Tracked in the pre-1.0 checklist in `CLAUDE.md`.
- **Native Linux packages (`.deb`/`.rpm`/AUR).** Today Linux installs from
  source via `install.sh`. Producing distro packages (e.g. with `nfpm`) is
  doable; hosting a repo is the extra step. An AUR `PKGBUILD` is the natural
  follow-up to the Omarchy work in the 1.0 gate — planned for 1.x, not a
  blocker.
- **winget / scoop / choco manifests.** Each needs a manifest plus a PR to an
  external community repository and stable release-asset URLs + hashes (the
  `SHA256SUMS.txt` we now publish helps here).

## Out of scope

- **macOS** — explicitly not supported (see `CLAUDE.md`).
- **Mobile (Android/iOS) client.** The biggest gap for the CGNAT use case, and
  the biggest effort: a separate platform and stack, and the official WireGuard
  apps don't speak the wstunnel transport. Not planned for the foreseeable
  future.
