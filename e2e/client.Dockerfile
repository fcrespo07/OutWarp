# A root OutWarp client for the end-to-end run: python-slim + wireguard-tools
# + the pinned wstunnel + the client wheel from this checkout, with the
# privileged helper taken verbatim from install.sh (so the e2e exercises the
# same script real installs get). Build context is the repo root.
FROM python:3.11-slim

ARG WSTUNNEL_VERSION

RUN apt-get update && apt-get install -y --no-install-recommends \
        wireguard-tools iproute2 iptables nftables openresolv \
        procps curl ca-certificates iputils-ping \
    && rm -rf /var/lib/apt/lists/*

COPY installer/wstunnel-version.txt /tmp/wstunnel-version.txt
RUN set -eux; \
    VERSION="${WSTUNNEL_VERSION:-$(tr -d '[:space:]' < /tmp/wstunnel-version.txt)}"; \
    case "$(uname -m)" in \
        x86_64)  ARCH="amd64" ;; \
        aarch64) ARCH="arm64" ;; \
        *) echo "Unsupported arch" && exit 1 ;; \
    esac; \
    curl -fsSL "https://github.com/erebe/wstunnel/releases/download/v${VERSION}/wstunnel_${VERSION}_linux_${ARCH}.tar.gz" \
        | tar -xz -C /usr/local/bin wstunnel; \
    chmod +x /usr/local/bin/wstunnel; \
    wstunnel --version

# The privileged helper: the heredoc body between the HELPER_EOF markers.
COPY installer/linux/install.sh /tmp/install.sh
RUN set -eux; \
    mkdir -p /usr/local/libexec; \
    sed -n "/<<'HELPER_EOF'\$/,/^HELPER_EOF\$/p" /tmp/install.sh | sed '1d;$d' \
        > /usr/local/libexec/outwarp-priv; \
    chmod 0755 /usr/local/libexec/outwarp-priv; \
    head -1 /usr/local/libexec/outwarp-priv | grep -q bash; \
    bash -n /usr/local/libexec/outwarp-priv

COPY client /src/client
RUN pip install --no-cache-dir /src/client && outwarp --version
