# Deploying OutWarp Server with Docker / Kubernetes

The OutWarp server runs perfectly fine on bare metal via the standard installer
(`curl … install.sh | sudo bash`). This document covers the two containerised
paths instead:

- **Docker / Docker Compose** — single-host deployments (VPS, home server).
- **Kubernetes (k3s / k8s)** — clusters with persistent storage and the rolling
  `ghcr.io/<owner>/outwarp-server:main` image.

> The OutWarp **client** is a desktop / TUI application. Don't containerise it —
> install it on the machine that needs the tunnel.

---

## Prerequisites

In every scenario you need:

- A public IPv4 address (or a DNS name resolving to one) that clients can
  reach. CGNAT and double-NAT setups will not work without an external
  reverse proxy.
- One TCP port reachable from the public internet (default `443`). Open it on
  your firewall / router / cloud security group **before** running the
  installer's probe.
- Linux kernel ≥ 5.6 on the **host** (kernel WireGuard module). The container
  itself does not need to ship `wireguard.ko`; it just calls into the host
  kernel via `wg-quick`.
- `NET_ADMIN` + `NET_RAW` capabilities for the container (configured in the
  manifests below — Docker compose and the k8s Deployment already grant
  them).

---

## Docker (single host)

The published image lives at:

```
ghcr.io/<repo-owner>/outwarp-server:latest    # rolling, follows main
ghcr.io/<repo-owner>/outwarp-server:0.5.5     # pinned to a release tag
ghcr.io/<repo-owner>/outwarp-server:main      # alias of latest while main is default branch
```

Multi-arch: `linux/amd64` + `linux/arm64` (Raspberry Pi 5 included).

### One-shot `docker run`

```bash
docker volume create outwarp-data

docker run -d \
  --name outwarp-server \
  --restart unless-stopped \
  --network host \
  --cap-add NET_ADMIN \
  --cap-add NET_RAW \
  -e OUTWARP_ENDPOINT="your-server.example.com" \
  -e OUTWARP_PORT="443" \
  -e OUTWARP_WG_PORT="51820" \
  -e OUTWARP_SUBNET="10.0.0.0/24" \
  -e OUTWARP_SERVER_ADDRESS="10.0.0.1/24" \
  -v outwarp-data:/data \
  ghcr.io/<repo-owner>/outwarp-server:latest
```

Notes:

- `--network host` is the simplest correct choice: wstunnel binds the WSS
  port directly to the host NIC and the WireGuard interface lives in the host
  netns, which is where traffic ultimately needs to flow. Bridge networking
  with `-p 443:443` works for wstunnel but adds a NAT hop and breaks the WG
  ↔ host routing.
- `OUTWARP_ENDPOINT` is baked into every `.owcfg` you later generate, so make
  sure it's the address clients should connect to.
- The first launch runs `outwarp-server init`, which generates TLS keys,
  WireGuard keys and writes `server_config.json` into `/data`. Subsequent
  restarts skip init (idempotent) and jump straight to `serve`.

### Adding clients

```bash
# Generate a profile for a new client and copy it out of the container:
docker exec outwarp-server outwarp-server --config-dir /data add-client laptop
docker cp outwarp-server:/data/laptop.owcfg ./laptop.owcfg
# laptop.owcfg now contains the private key — treat as a credential.
```

Other useful subcommands inside the container:

```bash
docker exec outwarp-server outwarp-server --config-dir /data list-clients
docker exec outwarp-server outwarp-server --config-dir /data revoke-client laptop
docker exec outwarp-server outwarp-server --config-dir /data status
docker exec outwarp-server outwarp-server --config-dir /data doctor
```

### Docker Compose

Save as `docker-compose.yml`:

```yaml
services:
  outwarp-server:
    image: ghcr.io/<repo-owner>/outwarp-server:latest
    container_name: outwarp-server
    restart: unless-stopped
    network_mode: host
    cap_add:
      - NET_ADMIN
      - NET_RAW
    environment:
      OUTWARP_ENDPOINT: "your-server.example.com"
      OUTWARP_PORT: "443"
      OUTWARP_WG_PORT: "51820"
      OUTWARP_SUBNET: "10.0.0.0/24"
      OUTWARP_SERVER_ADDRESS: "10.0.0.1/24"
    volumes:
      - outwarp-data:/data

volumes:
  outwarp-data:
```

Bring it up:

```bash
docker compose up -d
docker compose logs -f outwarp-server          # follow startup
docker compose exec outwarp-server outwarp-server --config-dir /data add-client phone
docker compose cp outwarp-server:/data/phone.owcfg ./phone.owcfg
```

---

## Kubernetes (k3s / k8s)

Manifests live in `deploy/kubernetes/`:

```
namespace.yaml      # creates ns/outwarp
configmap.yaml      # OUTWARP_* env vars (EDIT before applying)
pvc.yaml            # 256 Mi persistent storage for /data
deployment.yaml     # the actual workload — initContainer + main container
service.yaml        # ClusterIP for in-cluster name resolution
kustomization.yaml  # bundles everything for `kubectl apply -k`
```

### 1. Edit the ConfigMap

Open `deploy/kubernetes/configmap.yaml` and replace at least:

| Key | What to set it to |
|---|---|
| `OUTWARP_ENDPOINT` | Public IP or DNS name clients will dial. Baked into `.owcfg`. |
| `OUTWARP_PORT` | Public TCP/WSS port. Must be reachable from the internet. |
| `OUTWARP_WG_PORT` | Loopback UDP port; change only if it collides with another wg-* service on the node. |
| `OUTWARP_SUBNET` | A subnet that does **not** overlap your LAN, pod CIDR or service CIDR. |
| `OUTWARP_SERVER_ADDRESS` | First usable address of that subnet (e.g. `10.0.0.1/24`). |

### 2. Apply with kustomize

```bash
kubectl apply -k deploy/kubernetes/
kubectl -n outwarp get pods -w
kubectl -n outwarp logs -f deployment/outwarp-server -c outwarp-init
kubectl -n outwarp logs -f deployment/outwarp-server
```

The init container runs `outwarp-server init`, which is idempotent —
re-applying or restarting the pod will not regenerate keys once
`/data/server_config.json` exists.

### 3. Add a client

```bash
POD=$(kubectl -n outwarp get pod -l app=outwarp-server -o name | head -1)

kubectl -n outwarp exec "$POD" -- \
  outwarp-server --config-dir /data add-client laptop

kubectl -n outwarp cp "${POD#pod/}:/data/laptop.owcfg" ./laptop.owcfg
```

Other admin commands work the same way:

```bash
kubectl -n outwarp exec "$POD" -- outwarp-server --config-dir /data list-clients
kubectl -n outwarp exec "$POD" -- outwarp-server --config-dir /data revoke-client laptop
kubectl -n outwarp exec "$POD" -- outwarp-server --config-dir /data doctor
```

### Why `hostNetwork: true`?

`hostNetwork: true` (set in `deployment.yaml`) binds wstunnel directly to the
node's NIC and lets WireGuard create `wg0` in the host network namespace —
which is what you want for a VPN gateway: clients reach the node's public IP
directly, no kube-proxy DNAT or LoadBalancer needed. The trade-off is that
the port (`OUTWARP_PORT`) must be free on every node that could schedule the
pod; combined with `replicas: 1` this is fine because WireGuard is stateful
and must not scale horizontally anyway.

### Raspberry Pi 5 / k3s

The published image is multi-arch (`linux/amd64` + `linux/arm64`) so the same
manifests work on a Pi 5 cluster. There's also `deploy/build-pi.sh` which
builds the image on-device and imports it straight into the k3s containerd —
useful if you don't want to rely on GHCR. After the image is loaded, switch
`spec.template.spec.containers[*].image` in `deployment.yaml` to the local
tag (e.g. `outwarp-server:v0.5.5`) and set `imagePullPolicy: Never`.

### Storage

The PVC uses `storageClassName: local-path`, which is the default on k3s
(provisions a directory under `/var/lib/rancher/k3s/storage/`). On full
upstream Kubernetes you'll need to change that to whatever your cluster
exposes (`standard`, `gp2`, …). 256 Mi is more than enough — the persistent
data is just `server_config.json` plus the per-client `.owcfg` files.

---

## Image tags published from CI

`.github/workflows/docker-publish.yml` pushes to `ghcr.io` on every push to
`main` and every `v*` tag:

| Trigger | Tags pushed |
|---|---|
| push to `main` | `main`, `latest`, `sha-<short>` |
| git tag `v0.5.5` | `0.5.5`, `0.5`, `sha-<short>` |
| any | the SHA tag is always pushed |

For production prefer a pinned `0.5.5` tag and an explicit
`imagePullPolicy: IfNotPresent`. The bundled k8s manifests use `:main` +
`imagePullPolicy: Always` because they're aimed at a homelab where rolling
on every push is the point.

---

## Troubleshooting

| Symptom | Likely cause |
|---|---|
| `outwarp-server init` exits with "OUTWARP_ENDPOINT is required" | ConfigMap not applied or env var typo. |
| Pod stuck `CrashLoopBackOff` and `wg-quick up wg0` logs `sysctl: not found` | Old image — `procps` was added in 0.5.5. Re-pull `:latest` / use `:0.5.5+`. |
| Client connects via WSS but gets no IP / handshake never completes | `OUTWARP_SUBNET` clashes with the client's LAN, OR `NET_ADMIN` capability missing. |
| Clients connect but cannot reach the internet | IP forwarding disabled on the host (`sysctl net.ipv4.ip_forward`) or NAT/MASQUERADE rule missing — `outwarp-server doctor` will tell you which. |
| `exec format error` on Raspberry Pi | Image was pulled as `amd64`. Confirm with `docker image inspect` and re-pull on the Pi so it picks the `arm64` manifest. |

When in doubt run `outwarp-server --config-dir /data doctor` inside the
container — it inspects binaries, kernel modules, listen ports, IP forwarding
and NAT rules and prints actionable fix hints.
