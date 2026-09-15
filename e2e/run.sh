#!/usr/bin/env bash
# End-to-end run: real server image + root client container, the full user
# flow over the wire. Exit 0 only when every check passes.
#
#   add-client → import (enrols over :443 through wstunnel's forward)
#   → connect → WireGuard handshake → HTTP fetched over the tunnel
#   → default route inside the tunnel → counters moving
#   → reused token rejected → clean disconnect (no interface, no routes).
#
# Covers what green unit tests let through before: B-017 (self-signed cert
# handling), B-018 (unreachable enrolment listener), B-019 (verification
# traffic outside the tunnel) and the wstunnel version drift. Does NOT cover
# Windows, systemd units, Kubernetes or the GUI.
#
# Usage: e2e/run.sh            (needs docker + docker compose, ~3 min cold)
#        KEEP=1 e2e/run.sh     (leave the containers up for poking around)
set -euo pipefail

cd "$(dirname "$0")"
COMPOSE=(docker compose -f compose.yml)
CLIENT_NAME="laptop"
SERVER_TUNNEL_IP="10.99.0.1"
HTTP_PORT=8080

log()  { printf '\n\033[1;34m[e2e]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[e2e] FAIL:\033[0m %s\n' "$*" >&2; exit 1; }
srv()  { "${COMPOSE[@]}" exec -T server "$@"; }
cli()  { "${COMPOSE[@]}" exec -T client "$@"; }

cleanup() {
    local rc=$?
    if [[ $rc -ne 0 ]]; then
        log "server logs (last 60 lines)"; "${COMPOSE[@]}" logs --no-color --tail=60 server || true
        log "client log";                  cli sh -c 'cat /root/.local/state/OutWarp/log/outwarp.log 2>/dev/null | tail -80' || true
    fi
    if [[ "${KEEP:-0}" != "1" ]]; then
        "${COMPOSE[@]}" down -v --remove-orphans >/dev/null 2>&1 || true
    fi
    exit $rc
}
trap cleanup EXIT

log "building images"
"${COMPOSE[@]}" build --quiet

log "starting server + client"
"${COMPOSE[@]}" up -d

log "waiting for the server (wstunnel on :443 + wg0)"
for i in $(seq 1 60); do
    if srv sh -c 'pgrep -x wstunnel >/dev/null && [ -d /sys/class/net/wg0 ]' 2>/dev/null; then
        break
    fi
    [[ $i -eq 60 ]] && fail "server did not come up in 60 s"
    sleep 1
done
srv outwarp-server --config-dir /data status || true

log "serving a page on the server's tunnel address only (${SERVER_TUNNEL_IP}:${HTTP_PORT})"
srv sh -c "mkdir -p /srv/e2e && echo outwarp-e2e-ok > /srv/e2e/index.html"
"${COMPOSE[@]}" exec -T -d server \
    python3 -m http.server --bind "${SERVER_TUNNEL_IP}" --directory /srv/e2e "${HTTP_PORT}"

log "add-client ${CLIENT_NAME} → /shared/${CLIENT_NAME}.owcfg"
srv sh -c "cd /shared && outwarp-server --config-dir /data add-client ${CLIENT_NAME}" \
    || fail "add-client failed"
srv test -s "/shared/${CLIENT_NAME}.owcfg" || fail "no .owcfg written"
srv sh -c "python3 -c \"import json;d=json.load(open('/shared/${CLIENT_NAME}.owcfg'));assert 'client_private_key' not in d['wireguard'], 'private key in profile'\""

log "client: the page must NOT be reachable before the tunnel"
if cli curl -fsS --max-time 3 "http://${SERVER_TUNNEL_IP}:${HTTP_PORT}/" >/dev/null 2>&1; then
    fail "tunnel address reachable without the tunnel — the check below would be meaningless"
fi

log "client: import (enrols through the tunnel port)"
cli outwarp import "/shared/${CLIENT_NAME}.owcfg" || fail "import/enrolment failed"

log "client: the same token must be rejected a second time"
if cli outwarp import "/shared/${CLIENT_NAME}.owcfg" >/tmp/e2e-reimport.log 2>&1; then
    cat /tmp/e2e-reimport.log; fail "re-importing a redeemed profile succeeded"
fi
grep -qiE "used|redeemed|expired|enrol" /tmp/e2e-reimport.log \
    || { cat /tmp/e2e-reimport.log; fail "re-import failed for an unexpected reason"; }

log "client: connect (background) and wait for the handshake"
"${COMPOSE[@]}" exec -T -d client sh -c 'outwarp connect > /tmp/connect.out 2>&1'
IFACE=$(cli python3 -c "import json;print(json.load(open('/root/.config/OutWarp/config.json'))['wireguard']['tunnel_name'])")
for i in $(seq 1 60); do
    hs=$(cli sh -c "wg show ${IFACE} latest-handshakes 2>/dev/null | awk '{print \$2}'" || echo 0)
    if [[ -n "${hs:-}" && "${hs}" != "0" ]]; then break; fi
    [[ $i -eq 60 ]] && { cli cat /tmp/connect.out || true; fail "no WireGuard handshake in 60 s"; }
    sleep 1
done
log "handshake at epoch ${hs}"

log "client: HTTP over the tunnel"
body=$(cli curl -fsS --max-time 10 "http://${SERVER_TUNNEL_IP}:${HTTP_PORT}/") || fail "HTTP over the tunnel failed"
[[ "$body" == "outwarp-e2e-ok" ]] || fail "unexpected body: $body"

log "client: default route goes through the tunnel"
route=$(cli ip route get 1.1.1.1)
echo "  $route"
grep -q "dev ${IFACE}" <<<"$route" || fail "1.1.1.1 is not routed via ${IFACE}"

log "client: counters move"
rx=$(cli sh -c "wg show ${IFACE} transfer | awk '{print \$2}'")
[[ "${rx:-0}" -gt 0 ]] || fail "rx counter is 0"

log "client: disconnect (SIGTERM) and verify cleanup"
cli sh -c 'pkill -TERM -f "[o]utwarp connect" || true'
for i in $(seq 1 30); do
    if ! cli sh -c "[ -d /sys/class/net/${IFACE} ]"; then break; fi
    [[ $i -eq 30 ]] && fail "${IFACE} still present 30 s after SIGTERM"
    sleep 1
done
if cli ip route | grep -qE "172\.30\.0\.10/32|dev ${IFACE}"; then
    cli ip route; fail "leftover routes after disconnect"
fi
cli sh -c "ip route get 1.1.1.1 | grep -q 'dev eth0'" || fail "default route not restored"

log "ALL CHECKS PASSED"
