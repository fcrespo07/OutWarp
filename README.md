# OutWarp

> **⚠️ This project is under active development and not yet ready for production use.**

OutWarp is a cross-platform tool (client + server) that creates a **WireGuard tunnel over WebSocket** using [wstunnel](https://github.com/erebe/wstunnel) as the transport layer. Designed for environments where UDP is blocked but HTTPS/WebSocket traffic is allowed — corporate networks, captive Wi-Fi, mobile behind CGNAT, etc.

No domain name required. The server generates a self-signed TLS certificate and the client pins its fingerprint — zero dependency on Let's Encrypt or dynamic DNS.

---

## Installation

### Linux (client or server)

```bash
curl -fsSL https://raw.githubusercontent.com/fcrespo07/OutWarp/main/installer/linux/install.sh | sudo bash
```

The installer will ask whether you want to set up the **client** or the **server** and guide you through the rest.

### Windows (client or server)

Open PowerShell as Administrator and run:

```powershell
irm https://raw.githubusercontent.com/fcrespo07/OutWarp/main/installer/windows/install.ps1 | iex
```

### macOS

> macOS support is planned but not yet implemented.

---

## Server commands

After running the server installer, the following commands are available:

| Command | Description |
|---|---|
| `outwarp-server setup` | Interactive setup wizard |
| `outwarp-server add-client <name>` | Generate a `.owcfg` file for a new client |
| `outwarp-server list-clients` | List registered clients with their live status (online/offline, last handshake, transfer) |
| `outwarp-server revoke-client <name>` | Remove a client |
| `outwarp-server status` | Show service status |
| `outwarp-server restart` | Regenerate config and fully restart wg-quick + wstunnel |
| `outwarp-server uninstall` | Remove OutWarp server completely |

---

## How it works

1. The **server** wizard installs wstunnel as a systemd service, generates WireGuard keys and a self-signed TLS certificate, and detects its public IP.
2. For each client, `add-client` generates a `.owcfg` file containing everything needed to connect (keys, endpoint, certificate fingerprint, routing rules).
3. The **client** imports the `.owcfg` file, sets up the WireGuard interface, adds a static route to bypass the tunnel for wstunnel traffic, and maintains the connection with automatic reconnection and exponential backoff.

---

## Requirements

| Component | Notes |
|---|---|
| Python 3.11+ | Installed automatically by the installer if missing |
| WireGuard | Installed automatically by the installer |
| wstunnel | Downloaded automatically by the installer |
| A VPS or server with a public port open (default: 443) | Required for the server role |

---

## License

MIT — see [LICENSE](LICENSE) for details.

WireGuard is a registered trademark of Jason A. Donenfeld. wstunnel is licensed under BSD-3-Clause.
