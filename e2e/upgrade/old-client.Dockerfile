# The client of an older release (OLD_VERSION, default 0.20.2) with that
# release's own privileged helper: the "before" half of e2e/upgrade.sh.
# Build context is the repo root, like e2e/client.Dockerfile.
FROM python:3.11-slim

ARG OLD_VERSION=0.20.2

RUN apt-get update && apt-get install -y --no-install-recommends \
        wireguard-tools iproute2 iptables nftables openresolv \
        procps curl ca-certificates iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY installer/wstunnel-version.txt /tmp/wstunnel-version.txt
RUN set -eux; \
    VERSION="$(tr -d '[:space:]' < /tmp/wstunnel-version.txt)"; \
    case "$(uname -m)" in x86_64) ARCH=amd64 ;; aarch64) ARCH=arm64 ;; *) exit 1 ;; esac; \
    curl -fsSL "https://github.com/erebe/wstunnel/releases/download/v${VERSION}/wstunnel_${VERSION}_linux_${ARCH}.tar.gz" \
        | tar -xz -C /usr/local/bin wstunnel; \
    chmod +x /usr/local/bin/wstunnel

# The helper as that release's install.sh shipped it (heredoc body).
RUN set -eux; \
    mkdir -p /usr/local/libexec; \
    curl -fsSL "https://raw.githubusercontent.com/fcrespo07/OutWarp/v${OLD_VERSION}/installer/linux/install.sh" -o /tmp/install.sh; \
    sed -n "/<<'HELPER_EOF'\$/,/^HELPER_EOF\$/p" /tmp/install.sh | sed '1d;$d' \
        > /usr/local/libexec/outwarp-priv; \
    chmod 0755 /usr/local/libexec/outwarp-priv; \
    bash -n /usr/local/libexec/outwarp-priv

RUN pip install --no-cache-dir \
    "https://github.com/fcrespo07/OutWarp/releases/download/v${OLD_VERSION}/outwarp_client-${OLD_VERSION}-py3-none-any.whl" \
    && outwarp --version
