# OutWarp

> **⚠️ This project is under active development and not yet ready for production use.**

OutWarp is a cross-platform tool (client + server) that creates a **WireGuard tunnel over WebSocket** using [wstunnel](https://github.com/erebe/wstunnel) as the transport layer. It is for networks that block UDP (so plain WireGuard does not work) but let HTTPS out: hotel and guest Wi-Fi, mobile data behind CGNAT, firewalls that only open port 443.

It is **not** a censorship-circumvention tool. It does not hide that you are running a tunnel from a network that looks closely; see [What it gets through](#what-it-gets-through) before you rely on it.

A domain name is optional. Without one, the server uses a self-signed TLS certificate and the client pins it. With one, Caddy fronts the server with a Let's Encrypt certificate, which gets through more networks.

## What it gets through

What a network does to your traffic decides whether OutWarp works there:

| The network… | No domain (self-signed) | With a domain (Caddy + Let's Encrypt) |
|---|---|---|
| Blocks UDP / only allows TCP 443 | ✅ | ✅ |
| Filters by port only | ✅ | ✅ |
| Inspects the TLS certificate (rejects self-signed or unknown ones) | ❌ | ✅ |
| Intercepts TLS with its own CA (corporate TLS inspection) | ❌ the pinned certificate does not match | ⚠️ only on a device that trusts that CA (a managed work laptop); WireGuard still encrypts everything inside |
| Fingerprints the TLS client (JA3/JA4) and allows only browsers | ❌ | ❌ |
| Inspects the WebSocket upgrade or traffic patterns (deep packet inspection) | ❌ | ❌ |

"❌" means the connection fails; OutWarp never falls back to an unprotected one. Imitating a browser's TLS handshake is out of scope. Encrypted Client Hello may be explored later, but only against a real DPI network to test it on.

## Supported platforms

| | Client | Server |
|---|---|---|
| Windows 10 / 11 | ✅ installer (GUI + tray, CLI) | ✅ Docker Desktop ([recommended](deploy/README.md#windows-docker-desktop)) or the installer's native server |
| Linux with systemd (Ubuntu and Mint are the reference) | ✅ `install.sh` (GUI with a desktop, TUI, CLI) | ✅ `install.sh` (systemd), Docker or Kubernetes |
| macOS | ❌ out of scope | ❌ out of scope |

Client and server can run on different operating systems.

## Known limitations

- **Deep packet inspection**: see the table above. On a network that fingerprints TLS clients or inspects WebSocket upgrades, OutWarp does not connect.
- **Unsigned Windows installer**: SmartScreen and UAC warn about an unknown publisher (details below). Releases are signed with minisign instead, and the in-app updater verifies that signature.
- **TCP inside TCP**: WireGuard rides a TCP connection, so on a lossy link one lost packet stalls everything behind it. It is slower than plain WireGuard over UDP wherever UDP is allowed.
- **One tunnel at a time** per client, and no split tunnelling yet.
- **The server needs one public TCP port** reachable from the internet (a VPS, or port forwarding at home). CGNAT on the server side does not work.

---

## Installation

### Windows (client or server)

1. Go to the [latest release](https://github.com/fcrespo07/OutWarp/releases/latest) and download **`OutWarpSetup-x.y.z.exe`**.
2. Double-click the installer. Accept the UAC prompt.
3. In the wizard, pick **client**, **server**, or **both**, then click *Install*.

That's it. Shortcuts land on your desktop and in the Start menu; WireGuard for Windows and `wstunnel.exe` ship inside the installer.

> **First-launch warnings** — until the installer is code-signed, Windows shows two prompts:
> 1. **SmartScreen**: a blue "Windows protected your PC" panel. Click *More info → Run anyway*.
> 2. **UAC**: an "Unknown publisher" dialog (yellow header instead of blue). Click *Yes*.
>
> These go away once we ship a signed build. They do not indicate malware — they're Windows' default behaviour for any executable without a trusted code-signing certificate.

For automated / unattended deploys (Intune, Ansible, …) see [`scripts/install-from-release.ps1`](scripts/install-from-release.ps1).

### Linux (client or server)

```bash
curl -fsSL https://raw.githubusercontent.com/fcrespo07/OutWarp/main/installer/linux/install.sh | sudo bash
```

The installer will ask whether you want to set up the **client** or the **server** and guide you through the rest. With a desktop session it installs the graphical client (window + tray icon); every install also gets a **Textual TUI** that runs in any terminal (GNOME Terminal, Konsole, Alacritty, kitty, foot, tmux, SSH), which is the interface on headless machines.

```bash
outwarp tui          # client dashboard: live status, traffic, logs, profile editor
sudo outwarp-server tui  # server admin: clients table, add/revoke, doctor checks
```

Both TUIs share the same backend as the headless CLI subcommands (`connect`, `add-client`, etc.) so any scripts you already have keep working unchanged.

### macOS

> macOS support is out of scope. The dispatch tables only cover Windows and Linux.

### Docker / Kubernetes (server only)

If you'd rather run the server in a container — VPS, home server, a Windows
PC with Docker Desktop, k3s on a Raspberry Pi 5 — there's a public multi-arch
image (`linux/amd64` + `linux/arm64`) on GHCR and ready-to-use files in
`deploy/`:

```bash
# Docker Compose (Linux or Docker Desktop on Windows): tunnel + web panel.
cd deploy/docker && cp .env.example .env   # set OUTWARP_ENDPOINT
docker compose up -d
docker compose logs outwarp-panel     # the panel's admin token, printed once
# then open https://localhost:9443

# Kubernetes: edit deploy/kubernetes/configmap.yaml then:
kubectl apply -k deploy/kubernetes/
```

Full guide — Docker Compose, Windows with Docker Desktop, Kubernetes (k3s and
upstream), Pi 5 specifics, image tagging policy, troubleshooting — lives in
[`deploy/README.md`](deploy/README.md).

The client is desktop / TUI software and is **not** meant to run in a
container; install it on the machine that needs the tunnel.

---

## Linux client at a glance

After `outwarp import path/to/profile.owcfg`:

| Action | How |
|---|---|
| Foreground connect (Ctrl+C to stop) | `outwarp connect` |
| List profiles / switch / remove one (one active at a time) | `outwarp profile list` / `outwarp profile use <id>` / `outwarp profile remove <id>` |
| Headless status probe | `outwarp status` |
| Tail the log file (`tail -f` style) | `outwarp logs --follow` |
| Interactive TUI | `outwarp tui` |
| Window + tray icon (desktop sessions) | `outwarp gui` |
| Edit MTU / DNS / address / routing | TUI → **s** Settings → **p** Profile (or **p** from the dashboard) |
| Check for updates | `sudo outwarp update` |

### GUI or TUI on Linux — your call, before or after installing

The terminal UI (`outwarp tui`) is always installed. The graphical window +
tray icon (`outwarp gui`, the same pywebview UI as Windows) is offered by
`install.sh` when it detects a desktop session, and skipped on headless boxes
(`OUTWARP_CLIENT_GUI=1|0` answers the question for scripted installs).

Nothing is final:

| I want to… | Run |
|---|---|
| Add the graphical window to a TUI-only install | `sudo outwarp gui --install` (distro GTK/WebKit packages + pywebview into the existing venv) |
| Make the app-menu entry open the window / the terminal UI | `outwarp ui gui` / `outwarp ui tui` (`outwarp ui auto` = GUI when installed and a display is present) |
| See what is installed and what the launcher will open | `outwarp ui` or `outwarp doctor` |

On **Hyprland / Omarchy** the window floats and centres itself through a rule
that `install.sh` (or `outwarp ui --hyprland-rule`) writes to
`~/.config/hypr/outwarp.lua` (`outwarp.conf` on hyprlang setups); the tray
icon lives in the bar as a StatusNotifierItem and follows the tunnel state.
`outwarp doctor` tells you if either piece is missing.

The application launcher runs `outwarp launch`, which honours that choice and
opens the TUI in your terminal emulator (`$TERMINAL`, then the usual
suspects) when the GUI is not wanted. Both UIs expose the same toggle in
their Settings screen.

---

## Server commands

After running the server installer, the following commands are available:

| Command | Description |
|---|---|
| `outwarp-server setup` | Interactive setup wizard — asks whether you have a domain and configures the transport accordingly |
| `outwarp-server add-client <name>` | Issue a `.owcfg` for a new client (one-time enrolment token; add `--embed-key` for the legacy format) |
| `outwarp-server list-clients` | List registered clients with their live status (online/offline, last handshake, transfer) |
| `outwarp-server revoke-client <name>` | Remove a client and kill any outstanding enrolment token |
| `outwarp-server disable-client <name>` | Take a client off the tunnel, reversibly: it keeps its IP, keys, expiry and `.owcfg` |
| `outwarp-server enable-client <name>` | Put a disabled client back on the tunnel, no re-enrolment needed |
| `outwarp-server rotate-client <name>` | Re-issue a client's keys, keeping its IP and expiry |
| `outwarp-server renew-cert` | Reissue the self-signed TLS certificate, reusing the key so clients keep validating |
| `outwarp-server prune-expired` | Drop clients past their `expires_at` date |
| `outwarp-server status` | Show service status |
| `outwarp-server restart` | Regenerate config and fully restart wg-quick + wstunnel |
| `outwarp-server doctor` | Run diagnostic checks (binaries, kmod, services, listen ports, IP forward, NAT) |
| `outwarp-server tui` | Open the interactive admin TUI (Linux) |
| `outwarp-server uninstall` | Remove OutWarp server completely |

---

## How it works

1. The **server** wizard installs wstunnel as a systemd service, generates WireGuard keys, and configures the public port according to which transport branch you chose (below).
2. For each client, `add-client` writes a `.owcfg` containing everything needed to connect — endpoint, server public key, routing rules, and a one-time enrolment token.
3. The **client** imports the `.owcfg`, **generates its own WireGuard keypair locally**, and redeems the token to register the public half — through the same public port the tunnel uses (a wstunnel TCP forward to the server's loopback enrolment listener), so nothing else has to be opened. Its private key never leaves the machine and the server never sees it.
4. The client then brings up the WireGuard interface, excludes the server's address from the tunnel so wstunnel traffic does not loop, and maintains the connection with automatic reconnection and exponential backoff.

### Two transport branches

The setup wizard asks one question that decides how the server presents itself on
its public port. Pick based on the networks your clients need to work from.

| | **With a domain** (recommended) | **No domain** |
|---|---|---|
| Port 443 held by | Caddy, with a Let's Encrypt certificate | wstunnel, with a self-signed certificate |
| What a visitor sees at `/` | An ordinary web page | A wstunnel error |
| Client authenticates the server by | Validating the chain against the system CA store — wstunnel enforces it in-band too | Pinning the certificate's public key |
| Works on a network that inspects TLS | **Yes** | No — a self-signed certificate is trivially spotted |
| Needs | A domain pointing at the server | Nothing |
| Extra open port for enrolment | No | No |

The self-signed branch is enough where the only obstacle is blocked UDP — hotel
Wi-Fi, CGNAT, a firewall that allows 443/tcp. It is *not* enough against a
network that inspects the TLS handshake, because no self-signed certificate has a
chain to validate. That is what the domain branch is for.

Both branches carry the same WireGuard tunnel with the same end-to-end
encryption; the difference is only in how much the transport blends in.

### Client profiles are not permanent credentials

A `.owcfg` used to contain the client's WireGuard private key, which made the
file a complete, permanent credential for as long as it existed — including
while it sat in a chat app or an inbox. It now carries a **single-use enrolment
token valid for 15 minutes** instead. Consequences worth knowing:

- Send the file promptly. After the window, ask the admin for a new one.
- The client needs WireGuard tools installed at import time, because it generates
  its own key there.
- Enrolment goes through the tunnel port itself, so if the tunnel port is
  reachable, enrolment is. Profiles issued by a server ≥ 0.13 need a client
  ≥ 0.13 (older clients report an unsupported profile version).
- If the client reports *"this token was already redeemed"*, the file was
  intercepted. Revoke the client and issue a new profile.
- `--embed-key` restores the old behaviour for clients too old to enrol. It is
  supported, but the file is then a permanent credential again.

---

## Requirements

| Component | Notes |
|---|---|
| Python 3.11+ | Installed automatically by the installer if missing |
| WireGuard | Installed automatically by the installer |
| wstunnel | Downloaded automatically by the installer |
| A VPS or server with a public port open (default: 443) | Required for the server role |
| Caddy | Only for the domain branch; the wizard writes its configuration and tells you how to install it |
| A domain name | Optional, but the only way to work on networks that inspect TLS |

---

## License

[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0) —
see [LICENSE](LICENSE) for details. Free for personal, educational and other
noncommercial use; commercial use requires a separate agreement with the author.
Third-party components OutWarp bundles or depends on keep their own licenses —
see [THIRD_PARTY_LICENSES](THIRD_PARTY_LICENSES).

WireGuard is a registered trademark of Jason A. Donenfeld. wstunnel is licensed under BSD-3-Clause.
