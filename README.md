# OutWarp

> **⚠️ This project is under active development and not yet ready for production use.**

OutWarp is a cross-platform tool (client + server) that creates a **WireGuard tunnel over WebSocket** using [wstunnel](https://github.com/erebe/wstunnel) as the transport layer. Designed for environments where UDP is blocked but HTTPS/WebSocket traffic is allowed — corporate networks, captive Wi-Fi, mobile behind CGNAT, etc.

No domain name required. The server generates a self-signed TLS certificate and the client pins its fingerprint — zero dependency on Let's Encrypt or dynamic DNS.

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

The installer will ask whether you want to set up the **client** or the **server** and guide you through the rest. On Linux the primary interface is a **Textual TUI** that runs in any terminal (GNOME Terminal, Konsole, Alacritty, kitty, foot, tmux, SSH) — no GUI dependencies, no display server required.

```bash
outwarp-cli tui          # client dashboard: live status, traffic, logs, profile editor
sudo outwarp-server tui  # server admin: clients table, add/revoke, doctor checks
```

Both TUIs share the same backend as the headless CLI subcommands (`connect`, `add-client`, etc.) so any scripts you already have keep working unchanged.

### macOS

> macOS support is out of scope. The dispatch tables only cover Windows and Linux.

### Docker / Kubernetes (server only)

If you'd rather run the server in a container — VPS, home server, k3s on a
Raspberry Pi 5 — there's a published multi-arch image (`linux/amd64` +
`linux/arm64`) on GHCR and ready-to-apply manifests in `deploy/`:

```bash
# Docker / Compose: pull, run with NET_ADMIN, expose /data as a volume.
docker run -d --name outwarp-server --network host \
  --cap-add NET_ADMIN --cap-add NET_RAW \
  -e OUTWARP_ENDPOINT="your-server.example.com" \
  -v outwarp-data:/data \
  ghcr.io/<repo-owner>/outwarp-server:latest

# Kubernetes: edit deploy/kubernetes/configmap.yaml then:
kubectl apply -k deploy/kubernetes/
```

Full guide — Docker, Docker Compose, Kubernetes (k3s and upstream), Pi 5
specifics, image tagging policy, troubleshooting — lives in
[`deploy/README.md`](deploy/README.md).

The client is desktop / TUI software and is **not** meant to run in a
container; install it on the machine that needs the tunnel.

---

## Linux client at a glance

After `outwarp-cli import path/to/profile.owcfg`:

| Action | How |
|---|---|
| Foreground connect (Ctrl+C to stop) | `outwarp-cli connect` |
| Headless status probe | `outwarp-cli status` |
| Tail the log file (`tail -f` style) | `outwarp-cli logs --follow` |
| Interactive TUI (recommended) | `outwarp-cli tui` |
| Tray window (still available via webkitgtk) | `outwarp-cli gui` |
| Edit MTU / DNS / address / routing | TUI → **s** Settings → **p** Profile (or **p** from the dashboard) |
| Check for updates | `sudo outwarp-cli update` |

The autostart entry installed by `install.sh` launches the GUI tray by default; switch it to the TUI by pointing `Exec=` at `outwarp-cli tui` in `~/.config/autostart/outwarp.desktop`.

---

## Server commands

After running the server installer, the following commands are available:

| Command | Description |
|---|---|
| `outwarp-server setup` | Interactive setup wizard — asks whether you have a domain and configures the transport accordingly |
| `outwarp-server add-client <name>` | Issue a `.owcfg` for a new client (one-time enrolment token; add `--embed-key` for the legacy format) |
| `outwarp-server list-clients` | List registered clients with their live status (online/offline, last handshake, transfer) |
| `outwarp-server revoke-client <name>` | Remove a client and kill any outstanding enrolment token |
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
3. The **client** imports the `.owcfg`, **generates its own WireGuard keypair locally**, and redeems the token to register the public half. Its private key never leaves the machine and the server never sees it.
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
| Extra open port for enrolment | No (published on 443 under the secret path) | Yes (default 8444/tcp) |

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

MIT — see [LICENSE](LICENSE) for details.

WireGuard is a registered trademark of Jason A. Donenfeld. wstunnel is licensed under BSD-3-Clause.
