# OutWarp — Remote web admin panel

`outwarp-server web` serves the **same admin dashboard** as the desktop GUI, but
over HTTPS so you can manage a headless VPS from a browser. It runs the real
`Api` behind a token login — it does not duplicate any server logic.

> The panel runs as **root** and (by default) binds **all interfaces**. Treat it
> as a first-class attack surface: keep the token secret, firewall the port to
> trusted networks, or bind `127.0.0.1` and reach it over an SSH tunnel.

## 1. Create an admin token

The token is shown **once** — only a salted scrypt hash is stored on disk
(`/etc/outwarp/admin_token.json`, mode `0600`).

```bash
sudo outwarp-server admin-token
# → ow_admin_xxxxxxxxxxxxxxxxxxxxxxxx   (copy it now)
```

Rotate it any time (invalidates the previous one):

```bash
sudo outwarp-server admin-token --rotate
```

## 2. Run the panel

```bash
# default: HTTPS on 0.0.0.0:8443, reusing the server's self-signed TLS cert
sudo outwarp-server web

# bind localhost only (recommended) — reach it via SSH tunnel
sudo outwarp-server web --host 127.0.0.1 --port 8443
```

The browser will warn about the **self-signed certificate** — that's expected;
OutWarp pins by fingerprint, not a CA. Accept it once (or front the panel with a
reverse proxy that terminates a real cert).

### Access over an SSH tunnel (recommended)

```bash
# on your laptop
ssh -L 8443:127.0.0.1:8443 user@your-vps
# then open https://127.0.0.1:8443
```

This keeps the panel off the public internet entirely.

### Exposing it directly

If you bind `0.0.0.0`, open the port **only** to trusted source IPs. OutWarp does
**not** touch your firewall — do it yourself, e.g.:

```bash
sudo ufw allow from <your.ip.here> to any port 8443 proto tcp
```

## 3. Run it as a systemd service

Create `/etc/systemd/system/outwarp-web.service`:

```ini
[Unit]
Description=OutWarp web admin panel
After=network-online.target
Wants=network-online.target

[Service]
Type=simple
ExecStart=/usr/local/bin/outwarp-server web --host 127.0.0.1 --port 8443
Restart=on-failure
RestartSec=5
# Hardening: the panel needs root to drive wg/systemd, but you can still
# narrow its filesystem view if your deployment allows it.
NoNewPrivileges=false

[Install]
WantedBy=multi-user.target
```

Adjust `ExecStart` to the actual `outwarp-server` path (`which outwarp-server`;
pipx installs land under `/opt/pipx/bin/outwarp-server`). Then:

```bash
sudo systemctl daemon-reload
sudo systemctl enable --now outwarp-web.service
sudo journalctl -u outwarp-web -f
```

## What the panel can do

Live service health and throughput · client management (add with `.owcfg`,
detail drawer, rotate keys, regenerate, revoke) · service start/stop/restart ·
live logs with filter · Doctor diagnostics with one-click auto-fixes · traffic
history · server config + TLS rotation. Destructive actions confirm first and
are written to the server log for audit.

## Security model (summary)

- **TLS** on every connection (self-signed cert, same one wstunnel uses).
- **Token login** → scrypt-hashed, rate-limited with lockout on brute force.
- **Session cookie**: `HttpOnly` + `Secure` + `SameSite=Strict`.
- **CSRF**: every mutating request must carry the `X-OutWarp-Panel` header — a
  cross-site page can't set it without a CORS preflight we never allow.
- **Method allow-list**: `/api/<method>` only reaches a curated set of `Api`
  methods; there is no blind reflection.
- **Auto-fixes** (`apply_remediation`) run only the *code-defined* fix for a named
  Doctor check — never a free-text command — and are logged.
- **Strict CSP**, `nosniff`, `X-Frame-Options: DENY`, path-traversal guard on
  static files.
