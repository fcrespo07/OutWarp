FROM python:3.11-slim

ARG WSTUNNEL_VERSION=10.5.2

RUN apt-get update && apt-get install -y --no-install-recommends \
        wireguard-tools \
        iproute2 \
        iptables \
        curl \
    && rm -rf /var/lib/apt/lists/*

RUN curl -fsSL \
    "https://github.com/erebe/wstunnel/releases/download/v${WSTUNNEL_VERSION}/wstunnel_${WSTUNNEL_VERSION}_linux_amd64.tar.gz" \
    | tar -xz -C /usr/local/bin wstunnel \
    && chmod +x /usr/local/bin/wstunnel

WORKDIR /app

COPY requirements.txt ./
RUN pip install --no-cache-dir -r requirements.txt

COPY . .
RUN pip install --no-cache-dir -e .

EXPOSE 443

# init → serve in one shot so a single container image works without an init container.
# In K8s the init container pattern is preferred (see deploy/kubernetes/).
CMD ["sh", "-c", \
     "outwarp-server --config-dir /etc/outwarp init && \
      outwarp-server --config-dir /etc/outwarp serve"]
