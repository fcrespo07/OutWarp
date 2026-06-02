FROM python:3.11-slim

ARG WSTUNNEL_VERSION=10.5.2

RUN apt-get update && apt-get install -y --no-install-recommends \
        wireguard-tools \
        iproute2 \
        iptables \
        procps \
        curl \
    && rm -rf /var/lib/apt/lists/*
# procps ships /usr/sbin/sysctl, which wg-quick's PostUp hook needs to set
# net.ipv4.ip_forward=1 — without it `wg-quick up` aborts and the WireGuard
# interface is rolled back.

# wstunnel: arch-aware download. uname -m returns 'aarch64' on Raspberry Pi 5
# (arm64); install.sh maps that to 'arm64' — the filename convention erebe uses
# in releases. x86_64 maps to 'amd64' for dev/CI builds on amd64 hosts.
RUN set -eux; \
    RAW_ARCH=$(uname -m); \
    case "${RAW_ARCH}" in \
        x86_64)  ARCH="amd64"  ;; \
        aarch64) ARCH="arm64"  ;; \
        armv7l)  ARCH="armv7"  ;; \
        *) echo "Unsupported arch: ${RAW_ARCH}" && exit 1 ;; \
    esac; \
    TARBALL="wstunnel_${WSTUNNEL_VERSION}_linux_${ARCH}.tar.gz"; \
    curl -fsSL \
        "https://github.com/erebe/wstunnel/releases/download/v${WSTUNNEL_VERSION}/${TARBALL}" \
        | tar -xz -C /usr/local/bin wstunnel; \
    chmod +x /usr/local/bin/wstunnel

WORKDIR /app

COPY . .
# Production (non-editable) install — no extras needed in a container:
# Textual TUI and pywebview are desktop-only features.
RUN pip install --no-cache-dir .

# /data is mounted from the PersistentVolumeClaim. Using it as WORKDIR means
# `outwarp-server add-client <name>` drops <name>.owcfg here so it survives
# pod restarts and is easy to retrieve with `kubectl cp`.
WORKDIR /data

EXPOSE 443

# init is idempotent — reads env vars and generates keys+cert on first boot,
# exits in <1 s on subsequent restarts (config already exists).
CMD ["sh", "-c", \
     "outwarp-server --config-dir /data init && \
      outwarp-server --config-dir /data serve"]
