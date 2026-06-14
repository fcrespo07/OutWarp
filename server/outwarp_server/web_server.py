"""Embedded HTTPS admin panel for the OutWarp server.

Stdlib only (``http.server`` + ``ssl`` + Server-Sent Events) — the project is
deliberately light on dependencies and the VPS may have no outbound HTTP, so we
don't pull an ASGI stack or a CDN. The same ``Api`` that backs the pywebview
GUI backs this panel; this module only **routes** to it and **pushes** its
events. If you find yourself reaching for systemd/wg/wstunnel here, stop — that
lives behind ``Api``.

Transport split:
* ``POST /api/<method>`` — JSON args in, JSON out. Method must be in
  :data:`ALLOWED_METHODS`; reflection is never blind.
* ``GET /events`` — SSE stream re-dispatched on the client as the same
  ``outwarp:<name>`` CustomEvents the GUI already listens for.
* ``POST /auth`` / ``POST /logout`` — token login + session teardown.
* ``GET /<static>`` — the vendored UI bundle.

Security: TLS (reuses the server's self-signed cert), session cookie
(HttpOnly+Secure+SameSite=Strict), a custom-header CSRF guard, scrypt-hashed
admin token with rate-limited login, and a strict CSP. The panel runs as root,
so this is treated as a first-class attack surface.
"""

from __future__ import annotations

import json
import logging
import queue
import ssl
import threading
import time
from http import HTTPStatus
from http.cookies import SimpleCookie
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any

from outwarp_server.api import Api
from outwarp_server.web_auth import RateLimiter, SessionStore, verify_token

log = logging.getLogger(__name__)

# Methods of ``Api`` reachable over the network. Anything touching the
# pywebview window, the Windows PATH toggle, or native file dialogs is omitted:
# window chrome is meaningless in a browser, and save_owcfg/export_logs are
# handled client-side by the transport shim (download from the base64 the API
# already returns, instead of writing to the *server's* disk).
ALLOWED_METHODS = frozenset({
    "get_status", "get_deps", "detect_public_ip", "get_app_info",
    "run_diagnostics", "apply_remediation",
    "start_service", "stop_service", "restart_service",
    "list_clients", "add_client", "get_client",
    "regenerate_owcfg", "rotate_client_keys", "revoke_client",
    "prune_expired_clients",
    "run_setup", "update_server_config", "rotate_tls_cert", "probe_external_port",
    "get_logs", "clear_logs", "get_settings", "set_settings",
    "get_traffic_history",
    "notify_ready", "report_ui_error",
})

_SESSION_COOKIE = "ow_session"
_CSRF_HEADER = "x-outwarp-panel"

_CONTENT_TYPES = {
    ".html": "text/html; charset=utf-8",
    ".js": "text/javascript; charset=utf-8",
    ".css": "text/css; charset=utf-8",
    ".json": "application/json; charset=utf-8",
    ".svg": "image/svg+xml",
    ".png": "image/png",
    ".woff2": "font/woff2",
    ".woff": "font/woff",
    ".ico": "image/x-icon",
    ".map": "application/json; charset=utf-8",
}

_SECURITY_HEADERS = {
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Content-Security-Policy": (
        "default-src 'self'; "
        "style-src 'self' 'unsafe-inline'; "
        "img-src 'self' data:; "
        "font-src 'self' data:; "
        "connect-src 'self'; "
        "object-src 'none'; "
        "base-uri 'none'; "
        "frame-ancestors 'none'"
    ),
}


class EventBroker:
    """Fan-out hub between ``Api._emit`` (one sink) and N SSE subscribers."""

    def __init__(self) -> None:
        self._lock = threading.Lock()
        self._subscribers: set[queue.Queue[tuple[str, Any]]] = set()

    def subscribe(self) -> queue.Queue[tuple[str, Any]]:
        q: queue.Queue[tuple[str, Any]] = queue.Queue(maxsize=1000)
        with self._lock:
            self._subscribers.add(q)
        return q

    def unsubscribe(self, q: queue.Queue[tuple[str, Any]]) -> None:
        with self._lock:
            self._subscribers.discard(q)

    def publish(self, name: str, payload: Any) -> None:
        """Api sink. Never blocks the emitter: a slow/stuck subscriber that
        fills its queue just drops events rather than back-pressuring the
        whole server."""
        with self._lock:
            subs = list(self._subscribers)
        for q in subs:
            try:
                q.put_nowait((name, payload))
            except queue.Full:
                log.debug("SSE subscriber queue full — dropping event %s", name)


class _PanelServer(ThreadingHTTPServer):
    daemon_threads = True
    allow_reuse_address = True

    def __init__(
        self,
        addr: tuple[str, int],
        api: Api,
        ui_dir: Path,
        config_dir: Path,
        sessions: SessionStore,
        rate_limiter: RateLimiter,
        broker: EventBroker,
    ) -> None:
        super().__init__(addr, _PanelHandler)
        self.api = api
        self.ui_dir = ui_dir.resolve()
        self.config_dir = config_dir
        self.sessions = sessions
        self.rate_limiter = rate_limiter
        self.broker = broker


class _PanelHandler(BaseHTTPRequestHandler):
    server_version = "OutWarpPanel"
    protocol_version = "HTTP/1.1"

    # ── plumbing ──────────────────────────────────────────────────────────────

    @property
    def ctx(self) -> _PanelServer:
        return self.server  # type: ignore[return-value]

    def log_message(self, fmt: str, *args: Any) -> None:  # noqa: A002
        log.debug("web %s - " + fmt, self.address_string(), *args)

    def _client_ip(self) -> str:
        return self.client_address[0] if self.client_address else "unknown"

    def _session_id(self) -> str | None:
        raw = self.headers.get("Cookie")
        if not raw:
            return None
        try:
            cookie = SimpleCookie(raw)
        except Exception:
            return None
        morsel = cookie.get(_SESSION_COOKIE)
        return morsel.value if morsel else None

    def _authed(self) -> bool:
        return self.ctx.sessions.validate(self._session_id())

    def _read_body(self) -> bytes:
        try:
            length = int(self.headers.get("Content-Length", 0))
        except (TypeError, ValueError):
            return b""
        if length <= 0:
            return b""
        # Cap request bodies — nothing the panel accepts is large, and an
        # unbounded read is a trivial memory-exhaustion vector.
        if length > 1_000_000:
            return b""
        return self.rfile.read(length)

    def _send_headers(
        self,
        status: HTTPStatus,
        content_type: str,
        length: int,
        extra: dict[str, str] | None = None,
    ) -> None:
        self.send_response(status)
        self.send_header("Content-Type", content_type)
        self.send_header("Content-Length", str(length))
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        if extra:
            for k, v in extra.items():
                self.send_header(k, v)
        self.end_headers()

    def _send_json(
        self, payload: Any, status: HTTPStatus = HTTPStatus.OK,
        extra: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload).encode("utf-8")
        self._send_headers(status, "application/json; charset=utf-8", len(body), extra)
        self.wfile.write(body)

    def _send_error_json(self, status: HTTPStatus, message: str) -> None:
        self._send_json({"ok": False, "error": message}, status=status)

    # ── routing ───────────────────────────────────────────────────────────────

    def do_GET(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/events":
            self._handle_events()
            return
        self._serve_static(path)

    def do_POST(self) -> None:  # noqa: N802
        path = self.path.split("?", 1)[0]
        if path == "/auth":
            self._handle_auth()
            return
        if path == "/logout":
            self._handle_logout()
            return
        if path.startswith("/api/"):
            self._handle_api(path[len("/api/"):])
            return
        self._send_error_json(HTTPStatus.NOT_FOUND, "not found")

    # ── auth ──────────────────────────────────────────────────────────────────

    def _handle_auth(self) -> None:
        ip = self._client_ip()
        wait = self.ctx.rate_limiter.retry_after(ip)
        if wait > 0:
            self._send_json(
                {"ok": False, "error": "too many attempts, try again later"},
                status=HTTPStatus.TOO_MANY_REQUESTS,
                extra={"Retry-After": str(int(wait) + 1)},
            )
            return
        try:
            data = json.loads(self._read_body() or b"{}")
            token = str(data.get("token", ""))
            remember = bool(data.get("remember", False))
        except (ValueError, AttributeError):
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid body")
            return

        if not verify_token(self.ctx.config_dir, token):
            self.ctx.rate_limiter.register_failure(ip)
            self._send_error_json(HTTPStatus.UNAUTHORIZED, "invalid token")
            return

        self.ctx.rate_limiter.reset(ip)
        sid = self.ctx.sessions.create(remember=remember)
        cookie = (
            f"{_SESSION_COOKIE}={sid}; HttpOnly; Secure; SameSite=Strict; Path=/"
        )
        self._send_json({"ok": True}, extra={"Set-Cookie": cookie})

    def _handle_logout(self) -> None:
        self.ctx.sessions.destroy(self._session_id())
        expired = (
            f"{_SESSION_COOKIE}=; HttpOnly; Secure; SameSite=Strict; Path=/; Max-Age=0"
        )
        self._send_json({"ok": True}, extra={"Set-Cookie": expired})

    def _require_csrf(self) -> bool:
        """Custom-header guard. A cross-site form/img can't set this header
        without a CORS preflight we never allow, so combined with the
        SameSite=Strict cookie it blocks CSRF on every mutation."""
        return self.headers.get(_CSRF_HEADER) is not None

    # ── api dispatch ──────────────────────────────────────────────────────────

    def _handle_api(self, method: str) -> None:
        if not self._authed():
            self._send_error_json(HTTPStatus.UNAUTHORIZED, "not authenticated")
            return
        if not self._require_csrf():
            self._send_error_json(HTTPStatus.FORBIDDEN, "missing panel header")
            return
        if method not in ALLOWED_METHODS:
            self._send_error_json(HTTPStatus.NOT_FOUND, f"unknown method: {method}")
            return
        fn = getattr(self.ctx.api, method, None)
        if not callable(fn):
            self._send_error_json(HTTPStatus.NOT_FOUND, f"unsupported method: {method}")
            return
        try:
            raw = self._read_body()
            args = json.loads(raw) if raw else []
            if not isinstance(args, list):
                args = [args]
        except ValueError:
            self._send_error_json(HTTPStatus.BAD_REQUEST, "invalid JSON args")
            return
        try:
            result = fn(*args)
        except TypeError as exc:
            self._send_error_json(HTTPStatus.BAD_REQUEST, f"bad arguments: {exc}")
            return
        except Exception as exc:
            log.exception("web api method %s failed", method)
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, str(exc))
            return
        self._send_json(result)

    # ── SSE ───────────────────────────────────────────────────────────────────

    def _handle_events(self) -> None:
        if not self._authed():
            self._send_error_json(HTTPStatus.UNAUTHORIZED, "not authenticated")
            return
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", "text/event-stream; charset=utf-8")
        self.send_header("Cache-Control", "no-cache, no-transform")
        self.send_header("Connection", "keep-alive")
        self.send_header("X-Accel-Buffering", "no")
        for k, v in _SECURITY_HEADERS.items():
            self.send_header(k, v)
        self.end_headers()

        q = self.ctx.broker.subscribe()
        try:
            self.wfile.write(b": connected\n\n")
            self.wfile.flush()
            while True:
                try:
                    name, payload = q.get(timeout=15.0)
                except queue.Empty:
                    self.wfile.write(b": ping\n\n")
                    self.wfile.flush()
                    continue
                chunk = (
                    f"event: outwarp:{name}\n"
                    f"data: {json.dumps(payload)}\n\n"
                ).encode()
                self.wfile.write(chunk)
                self.wfile.flush()
        except (BrokenPipeError, ConnectionResetError, OSError):
            pass
        finally:
            self.ctx.broker.unsubscribe(q)

    # ── static files ──────────────────────────────────────────────────────────

    def _serve_static(self, path: str) -> None:
        rel = path.lstrip("/") or "index.html"
        target = (self.ctx.ui_dir / rel).resolve()
        # Defeat path traversal: the resolved target must stay inside ui_dir.
        if target != self.ctx.ui_dir and self.ctx.ui_dir not in target.parents:
            self._send_error_json(HTTPStatus.FORBIDDEN, "forbidden")
            return
        if not target.is_file():
            # SPA-ish fallback: unknown non-asset routes get index.html so a
            # browser refresh on a client-routed path still loads the panel.
            if "." not in Path(rel).name:
                target = self.ctx.ui_dir / "index.html"
            if not target.is_file():
                self._send_error_json(HTTPStatus.NOT_FOUND, "not found")
                return
        try:
            data = target.read_bytes()
        except OSError:
            self._send_error_json(HTTPStatus.INTERNAL_SERVER_ERROR, "read failed")
            return
        ctype = _CONTENT_TYPES.get(target.suffix.lower(), "application/octet-stream")
        self._send_headers(HTTPStatus.OK, ctype, len(data))
        self.wfile.write(data)


def serve(
    api: Api,
    ui_dir: Path,
    config_dir: Path,
    host: str = "0.0.0.0",
    port: int = 8443,
    certfile: str | None = None,
    keyfile: str | None = None,
) -> _PanelServer:
    """Build, TLS-wrap and start the panel server in a background thread.

    Returns the server so the caller can ``shutdown()`` it. The admin ``Api``
    must already be constructed; this wires the SSE broker as one of its sinks.
    """
    sessions = SessionStore()
    rate_limiter = RateLimiter()
    broker = EventBroker()

    httpd = _PanelServer(
        (host, port), api, ui_dir, config_dir, sessions, rate_limiter, broker,
    )

    if certfile and keyfile:
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.load_cert_chain(certfile=certfile, keyfile=keyfile)
        httpd.socket = ctx.wrap_socket(httpd.socket, server_side=True)

    api.register_sink(broker.publish)
    api.start_background()

    thread = threading.Thread(
        target=httpd.serve_forever, name="outwarp-web", daemon=True,
    )
    thread.start()

    # Periodic session GC so a long-lived daemon doesn't accumulate dead
    # sessions. Cheap; runs every few minutes.
    def _gc() -> None:
        while True:
            time.sleep(300)
            sessions.purge_expired()

    threading.Thread(target=_gc, name="outwarp-web-gc", daemon=True).start()
    return httpd
