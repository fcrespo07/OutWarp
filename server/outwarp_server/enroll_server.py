"""HTTPS listener that redeems enrolment tokens.

A client importing a v3 .owcfg has to reach the server *before* the tunnel
exists, so this is the one OutWarp surface that has to be publicly dialable
without WireGuard. It is deliberately tiny: one route, one verb, no sessions, no
static files. The only credential it accepts is a single-use token with a short
TTL, checked against a salted scrypt hash, behind the same sliding-window rate
limiter the admin panel uses.

Exposure follows the transport branch. Behind Caddy it binds loopback and is
published on the public port under the secret path prefix, so it adds no new
open port. In the self-signed branch it binds publicly with the server's own
certificate — the same one the transport uses, so the client validates it with
the pin it already has in the profile.
"""

from __future__ import annotations

import json
import logging
import re
import ssl
import threading
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from outwarp_server import enrollment, operations
from outwarp_server.config import ServerConfig
from outwarp_server.web_auth import RateLimiter

log = logging.getLogger(__name__)

# A WireGuard public key is 32 bytes of base64: 43 chars plus '='.
_WG_KEY_RE = re.compile(r"^[A-Za-z0-9+/]{42}[AEIMQUYcgkosw048]=$")
_MAX_BODY = 4096


class _EnrollServer(ThreadingHTTPServer):
    daemon_threads = True
    # Without this a restart within TIME_WAIT fails to bind, which for a
    # loopback service that restarts with wstunnel is a routine event.
    allow_reuse_address = True

    def __init__(
        self,
        address: tuple[str, int],
        config_path: Path,
        rate_limiter: RateLimiter,
        on_enrolled: Any = None,
    ) -> None:
        super().__init__(address, _EnrollHandler)
        self.config_path = config_path
        self.rate_limiter = rate_limiter
        self.on_enrolled = on_enrolled
        # Redeem-then-register must not interleave: two clients enrolling at the
        # same moment would otherwise read the same config and one write would
        # lose the other's peer.
        self.enroll_lock = threading.Lock()


class _EnrollHandler(BaseHTTPRequestHandler):
    server_version = "nginx"  # don't advertise what this is
    sys_version = ""

    @property
    def ctx(self) -> _EnrollServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        log.debug("enroll: " + fmt, *args)

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "?"

    def _send_json(self, status: HTTPStatus, payload: dict[str, Any]) -> None:
        body = json.dumps(payload).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(body)))
        self.send_header("Cache-Control", "no-store")
        self.end_headers()
        self.wfile.write(body)

    def do_GET(self) -> None:  # noqa: N802
        # Nothing to see. A prober should not be able to tell this apart from
        # any other 404 on the host.
        self.send_error(HTTPStatus.NOT_FOUND)

    def do_POST(self) -> None:  # noqa: N802
        if self.path.split("?", 1)[0].rstrip("/") not in ("/enroll", ""):
            self.send_error(HTTPStatus.NOT_FOUND)
            return

        ip = self._client_ip()
        wait = self.ctx.rate_limiter.retry_after(ip)
        if wait > 0:
            self.send_response(HTTPStatus.TOO_MANY_REQUESTS)
            self.send_header("Retry-After", str(int(wait) + 1))
            self.send_header("Content-Length", "0")
            self.end_headers()
            return

        try:
            length = int(self.headers.get("Content-Length") or 0)
        except ValueError:
            length = 0
        if length <= 0 or length > _MAX_BODY:
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid request body"})
            return
        try:
            data = json.loads(self.rfile.read(length).decode("utf-8"))
        except (OSError, UnicodeDecodeError, json.JSONDecodeError):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid request body"})
            return
        if not isinstance(data, dict):
            self._send_json(HTTPStatus.BAD_REQUEST, {"error": "invalid request body"})
            return

        token = str(data.get("token") or "")
        public_key = str(data.get("client_public_key") or "")
        if not _WG_KEY_RE.match(public_key):
            self._send_json(
                HTTPStatus.BAD_REQUEST,
                {"error": "client_public_key is not a WireGuard public key"},
            )
            return

        with self.ctx.enroll_lock:
            self._redeem(ip, token, public_key)

    def _redeem(self, ip: str, token: str, public_key: str) -> None:
        config_path = self.ctx.config_path
        config_dir = config_path.parent
        try:
            record = enrollment.redeem(config_dir, token)
        except enrollment.EnrollmentError as exc:
            # Counted as a failure so a token cannot be brute-forced over the
            # wire; the message is kept because "already used" is exactly the
            # signal a legitimate client needs to see.
            self.ctx.rate_limiter.register_failure(ip)
            log.warning("enrolment refused from %s: %s", ip, exc)
            self._send_json(HTTPStatus.FORBIDDEN, {"error": str(exc)})
            return

        try:
            config = ServerConfig.load(config_path)
            result = operations.complete_enrollment(
                config, record.client_name, public_key, config_path=config_path
            )
        except (KeyError, ValueError) as exc:
            log.warning("enrolment for '%s' could not be completed: %s", record.client_name, exc)
            self._send_json(HTTPStatus.CONFLICT, {"error": str(exc)})
            return
        except Exception as exc:  # noqa: BLE001 — never leak internals to the client
            log.exception("enrolment for '%s' failed", record.client_name)
            self._send_json(
                HTTPStatus.INTERNAL_SERVER_ERROR,
                {"error": "the server could not complete enrolment"},
            )
            del exc
            return

        self.ctx.rate_limiter.reset(ip)
        log.info(
            "Client '%s' enrolled from %s (%s)",
            record.client_name, ip,
            "peer live" if result.hot_added else "peer written, WireGuard not running",
        )
        if self.ctx.on_enrolled is not None:
            try:
                self.ctx.on_enrolled(result.client.name)
            except Exception:
                log.exception("enrolment notification callback failed")

        # Everything else the client needs is already in the .owcfg it imported;
        # this only confirms the registration took and echoes the fields the
        # server is authoritative for.
        self._send_json(
            HTTPStatus.OK,
            {
                "ok": True,
                "name": result.client.name,
                "client_address": result.client.address,
                "server_public_key": result.config.wg_public_key,
                "peer_live": result.hot_added,
            },
        )


def serve(
    config: ServerConfig,
    config_path: Path,
    *,
    on_enrolled: Any = None,
) -> _EnrollServer:
    """Start the listener in a background thread and return it for shutdown().

    Binds loopback (and speaks plain HTTP) when Caddy fronts it, because Caddy
    already terminated TLS; binds publicly with the server certificate
    otherwise.
    """
    host = "127.0.0.1" if config.behind_reverse_proxy else "0.0.0.0"  # noqa: S104
    httpd = _EnrollServer(
        (host, config.enroll_port), config_path, RateLimiter(), on_enrolled
    )

    if not config.behind_reverse_proxy:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=config.cert_path, keyfile=config.key_path)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    threading.Thread(
        target=httpd.serve_forever, name="outwarp-enroll", daemon=True
    ).start()
    log.info("Enrolment listener on %s:%s", host, config.enroll_port)
    return httpd
