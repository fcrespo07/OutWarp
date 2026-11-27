# The server of an older release (OLD_VERSION, default 0.20.2), installed from
# its GitHub release wheel: the "before" half of e2e/upgrade.sh. Mirrors
# server/Dockerfile (same base, same wstunnel pin, same CMD) except that the
# package comes from the release instead of the checkout.
FROM python:3.11-slim

ARG OLD_VERSION=0.20.2
ARG WSTUNNEL_VERSION=10.5.2

RUN apt-get update && apt-get install -y --no-install-recommends \
        wireguard-tools iproute2 iptables procps curl ca-certificates \
    && rm -rf /var/lib/apt/lists/*

RUN set -eux; \
    case "$(uname -m)" in x86_64) ARCH=amd64 ;; aarch64) ARCH=arm64 ;; *) exit 1 ;; esac; \
    curl -fsSL "https://github.com/erebe/wstunnel/releases/download/v${WSTUNNEL_VERSION}/wstunnel_${WSTUNNEL_VERSION}_linux_${ARCH}.tar.gz" \
        | tar -xz -C /usr/local/bin wstunnel; \
    chmod +x /usr/local/bin/wstunnel

RUN pip install --no-cache-dir \
    "https://github.com/fcrespo07/OutWarp/releases/download/v${OLD_VERSION}/outwarp_server-${OLD_VERSION}-py3-none-any.whl" \
    && outwarp-server --version

ENV OUTWARP_PLATFORM=kubernetes
WORKDIR /data
EXPOSE 443
CMD ["sh", "-c", \
     "outwarp-server --config-dir /data init && \
      exec outwarp-server --config-dir /data serve"]
