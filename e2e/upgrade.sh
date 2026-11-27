#!/usr/bin/env bash
# Upgrade run: a release that real users have (OLD_VERSION, default 0.20.2)
# sets everything up, then the images are swapped for this checkout's while the
# data volumes stay. What must survive: the server's client registry, keys and
# cert, and the client's imported profile, with no re-import and no new
# enrolment.
#
#   OLD server + OLD client: add-client → import → connect → traffic → disconnect
#   swap both to the checkout (volumes kept)
#   NEW server: starts on the old data, still lists the client and its peer
#   NEW client: profile still active, doctor runs, connect → handshake →
#   HTTP over the tunnel → clean disconnect
#
# Not covered: Windows installer upgrades (see installer-smoke.yml), systemd
# units, Kubernetes, the in-app updater itself.
#
# Usage: e2e/upgrade.sh                    (docker + docker compose, ~5 min cold)
#        OLD_VERSION=0.19.0 e2e/upgrade.sh
#        KEEP=1 e2e/upgrade.sh             (leave the containers up)
set -euo pipefail

cd "$(dirname "$0")/upgrade"
export OLD_VERSION="${OLD_VERSION:-0.20.2}"
OLD=(docker compose -f compose.yml -f compose.old.yml)
NEW=(docker compose -f compose.yml -f compose.new.yml)
COMPOSE=("${OLD[@]}")
CLIENT_NAME="laptop"
SERVER_TUNNEL_IP="10.98.0.1"
HTTP_PORT=8080

log()  { printf '\n\033[1;34m[upgrade]\033[0m %s\n' "$*"; }
fail() { printf '\n\033[1;31m[upgrade] FAIL:\033[0m %s\n' "$*" >&2; exit 1; }
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

wait_server() {
    for i in $(seq 1 60); do
        if srv sh -c 'pgrep -x wstunnel >/dev/null && [ -d /sys/class/net/wg0 ]' 2>/dev/null; then return 0; fi
        sleep 1
    done
    fail "server did not come up in 60 s"
}

serve_page() {
    srv sh -c "mkdir -p /srv/e2e && echo outwarp-upgrade-ok > /srv/e2e/index.html"
    "${COMPOSE[@]}" exec -T -d server \
        python3 -m http.server --bind "${SERVER_TUNNEL_IP}" --directory /srv/e2e "${HTTP_PORT}"
}

# connect in the background, wait for the handshake, fetch the page, disconnect
tunnel_roundtrip() {
    local what="$1" hs="" body="" iface
    cli sh -c 'pkill -TERM -f "[o]utwarp connect" || true' || true
    "${COMPOSE[@]}" exec -T -d client sh -c 'outwarp connect > /tmp/connect.out 2>&1'
    iface=$(cli python3 -c "from outwarp.config import ClientConfig, default_config_path; print(ClientConfig.load(default_config_path()).wireguard.tunnel_name)")
    for i in $(seq 1 60); do
        hs=$(cli sh -c "wg show ${iface} latest-handshakes 2>/dev/null | awk '{print \$2}'" || echo 0)
        [[ -n "${hs:-}" && "${hs}" != "0" ]] && break
        [[ $i -eq 60 ]] && { cli cat /tmp/connect.out || true; fail "${what}: no WireGuard handshake in 60 s"; }
        sleep 1
    done
    body=$(cli curl -fsS --max-time 10 "http://${SERVER_TUNNEL_IP}:${HTTP_PORT}/") || fail "${what}: HTTP over the tunnel failed"
    [[ "$body" == "outwarp-upgrade-ok" ]] || fail "${what}: unexpected body: $body"
    cli sh -c 'pkill -TERM -f "[o]utwarp connect" || true'
    for i in $(seq 1 30); do
        cli sh -c "[ -d /sys/class/net/${iface} ]" || return 0
        sleep 1
    done
    fail "${what}: ${iface} still present 30 s after SIGTERM"
}

# ── before: the old release ────────────────────────────────────────────────
log "building the v${OLD_VERSION} images"
"${OLD[@]}" build --quiet
"${OLD[@]}" up -d
wait_server
OLD_SERVER=$(srv outwarp-server --version); OLD_CLIENT=$(cli outwarp --version)
log "before: ${OLD_SERVER} / ${OLD_CLIENT}"
serve_page

srv sh -c "cd /shared && outwarp-server --config-dir /data add-client ${CLIENT_NAME}" || fail "old add-client failed"
cli outwarp import "/shared/${CLIENT_NAME}.owcfg" || fail "old import/enrolment failed"
tunnel_roundtrip "old release"
srv outwarp-server --config-dir /data list-clients | grep -q "${CLIENT_NAME}" || fail "client not listed on the old server"

# ── the swap: same volumes, this checkout's images ─────────────────────────
log "building the checkout's images and swapping them in (volumes kept)"
"${NEW[@]}" build --quiet
COMPOSE=("${NEW[@]}")
"${NEW[@]}" up -d --force-recreate
wait_server
NEW_SERVER=$(srv outwarp-server --version); NEW_CLIENT=$(cli outwarp --version)
log "after: ${NEW_SERVER} / ${NEW_CLIENT}"
[[ "$NEW_SERVER" != "$OLD_SERVER" ]] || fail "server image was not swapped (${NEW_SERVER})"
[[ "$NEW_CLIENT" != "$OLD_CLIENT" ]] || fail "client image was not swapped (${NEW_CLIENT})"

# ── after: the data of the old release, read by the new one ────────────────
log "server: client registry, peer and keys survived"
srv outwarp-server --config-dir /data list-clients | grep -q "${CLIENT_NAME}" || fail "client lost on upgrade"
[[ "$(srv sh -c 'wg show wg0 peers | wc -l')" -eq 1 ]] || fail "peer missing from wg0 after upgrade"
srv outwarp-server --config-dir /data doctor >/tmp/upgrade-server-doctor.log 2>&1 || true
grep -q Traceback /tmp/upgrade-server-doctor.log && { cat /tmp/upgrade-server-doctor.log; fail "server doctor crashed"; }

log "client: the profile is still there and active (no re-import)"
cli outwarp profile list | grep -q '^\* ' || fail "no active profile after upgrade"
cli outwarp status >/dev/null 2>&1 || true
rc=0; cli outwarp doctor >/tmp/upgrade-client-doctor.log 2>&1 || rc=$?
grep -q Traceback /tmp/upgrade-client-doctor.log && { cat /tmp/upgrade-client-doctor.log; fail "client doctor crashed"; }
[[ $rc -le 1 ]] || fail "client doctor exited with $rc"

log "traffic over the tunnel with the old profile and the new software"
serve_page
tunnel_roundtrip "after upgrade"

log "UPGRADE CHECKS PASSED (${OLD_VERSION} -> $(cli outwarp --version))"
