"""Client half of the enrolment handshake.

An enrolment .owcfg arrives without a private key: it carries a one-time token
and where to redeem it. This module generates the keypair locally, posts only
the public half, and hands back a profile that is complete — with a private key
that has never left this machine.

The redemption happens before the tunnel exists, so it is the one request the
client makes over the open network. Since schema v4 it goes *through the tunnel
port*: wstunnel opens a TCP forward to the server's loopback listener over the
same WSS front (and, if that is blocked, the same fallback ladder) the tunnel
itself will use, so enrolment needs no port of its own and inherits the
transport's trust model — the system CA store behind a real certificate, the
profile's own pin for a self-signed server. v3 profiles carried a public HTTPS
URL on a second port instead; that path is kept so a profile issued by an older
server still imports.
"""

from __future__ import annotations

import contextlib
import json
import logging
import socket
import ssl
import subprocess
import sys
import time
import urllib.error
import urllib.request
from collections.abc import Iterator
from dataclasses import replace
from pathlib import Path
from urllib.parse import urlsplit

from outwarp.config import ClientConfig, ConfigError
from outwarp.fallback import ConnectionStrategy, build_ladder, strategy_to_command
from outwarp.keygen import KeygenError, generate_keypair
from outwarp.network import (
    CertificateNotTrustedError,
    FingerprintMismatchError,
    NetworkError,
    verify_tls_fingerprint,
    verify_tls_spki,
)

log = logging.getLogger(__name__)

_TIMEOUT = 20.0
_USER_AGENT = "OutWarp-Enroll"
# How long to give wstunnel to open its local listener. It binds before dialling
# the server, so this only covers process start-up, not the network.
_FORWARD_READY_TIMEOUT = 5.0


class EnrollError(RuntimeError):
    """User-facing enrolment failure.

    ``terminal`` marks the ones another transport rung cannot fix — the server
    answered and refused, or it is not the server the profile was issued for —
    so the ladder stops instead of spending a retry per rung.
    """

    def __init__(self, message: str, *, terminal: bool = False) -> None:
        super().__init__(message)
        self.terminal = terminal


def needs_enrollment(config: ClientConfig) -> bool:
    return bool(config.enrollment.token) and not config.wireguard.client_private_key


def enroll(config: ClientConfig) -> ClientConfig:
    """Redeem `config`'s token and return the completed profile.

    Raises EnrollError with a message meant for the user — this runs during
    import, where the only useful outcome is either a working profile or a clear
    reason why not.
    """
    if not needs_enrollment(config):
        return config

    enrollment = config.enrollment
    if not (enrollment.remote_port or enrollment.url):
        raise EnrollError("This profile has an enrolment token but no endpoint to use it at.")

    try:
        private_key, public_key = generate_keypair()
    except KeygenError as exc:
        raise EnrollError(str(exc)) from exc

    body = {"token": enrollment.token, "client_public_key": public_key}
    if enrollment.remote_port:
        payload = _redeem_via_transport(config, body)
    else:
        _verify_endpoint(config, enrollment.url)
        payload = _post(enrollment.url, body, config)

    # The server is authoritative for the address it reserved; trust its answer
    # over the copy baked into the file in case the pool shifted.
    address = str(payload.get("client_address") or config.wireguard.client_address)
    server_public_key = str(
        payload.get("server_public_key") or config.wireguard.server_public_key
    )

    wg = replace(
        config.wireguard,
        client_private_key=private_key,
        client_address=address,
        server_public_key=server_public_key,
    )
    if not payload.get("peer_live", True):
        log.warning(
            "Enrolled, but the server could not add the peer to a running interface "
            "yet — the first connection may need the admin to restart the server."
        )
    # Drop the whole block rather than keeping a spent credential on disk; a
    # profile that has enrolled is indistinguishable from a legacy one from here
    # on, which is exactly what the rest of the client expects.
    from outwarp.config import EnrollmentConfig
    return replace(config, wireguard=wg, enrollment=EnrollmentConfig())


def _redeem_via_transport(config: ClientConfig, body: dict) -> dict:
    """Post the token through a wstunnel forward on the tunnel port.

    Walks the same rungs the tunnel would (direct, public-DNS, proxy, alternate
    ports — everything that dials the profile's own endpoint) so a network that
    needs the second rung to carry WireGuard also gets to enrol. Each rung is
    pinned the way the tunnel pins it before wstunnel is started.
    """
    from outwarp.tunnel import find_wstunnel

    try:
        wstunnel_bin = find_wstunnel()
    except Exception as exc:  # TunnelError, kept out of the import graph
        raise EnrollError(str(exc)) from exc

    rungs = [r for r in build_ladder(config) if r.endpoint == config.server.endpoint]
    failures: list[str] = []
    for rung in rungs:
        try:
            if rung.scheme == "wss" and not rung.proxy and rung.pin_mode != "none":
                _verify_endpoint(config, f"https://{rung.endpoint}:{rung.port}/")
            with _open_forward(config, rung, wstunnel_bin) as local_port:
                return _post(f"http://127.0.0.1:{local_port}/enroll", body, config)
        except EnrollError as exc:
            if exc.terminal:
                raise
            log.warning("Enrolment via rung '%s' failed: %s", rung.id, exc)
            failures.append(f"{rung.label}: {exc}")
    raise EnrollError(
        "Could not reach the enrolment endpoint through the tunnel port:\n  "
        + "\n  ".join(failures)
    )


def _forward_command(
    rung: ConnectionStrategy, wstunnel_bin: Path, local_port: int, remote_port: int,
) -> list[str]:
    """wstunnel argv for a TCP forward to the server's loopback listener."""
    return strategy_to_command(
        rung, wstunnel_bin, f"tcp://127.0.0.1:{local_port}:127.0.0.1:{remote_port}"
    )


@contextlib.contextmanager
def _open_forward(
    config: ClientConfig, rung: ConnectionStrategy, wstunnel_bin: Path,
) -> Iterator[int]:
    """Run a wstunnel forward for the duration of the block; yields its local port."""
    local_port = _free_port()
    cmd = _forward_command(rung, wstunnel_bin, local_port, config.enrollment.remote_port)
    log.info("Enrolment forward via rung '%s': %s", rung.id, rung.url)
    proc = subprocess.Popen(
        cmd,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        creationflags=subprocess.CREATE_NO_WINDOW if sys.platform == "win32" else 0,
    )
    try:
        _wait_for_local_port(proc, local_port)
        yield local_port
    finally:
        proc.terminate()
        try:
            proc.wait(timeout=5)
        except subprocess.TimeoutExpired:
            proc.kill()
            proc.wait()


def _free_port() -> int:
    with socket.socket() as s:
        s.bind(("127.0.0.1", 0))
        return s.getsockname()[1]


def _wait_for_local_port(proc: subprocess.Popen, port: int) -> None:
    deadline = time.monotonic() + _FORWARD_READY_TIMEOUT
    while time.monotonic() < deadline:
        if proc.poll() is not None:
            raise EnrollError(
                f"wstunnel exited before opening its local port (code {proc.returncode})"
            )
        try:
            with socket.create_connection(("127.0.0.1", port), timeout=0.5):
                return
        except OSError:
            time.sleep(0.1)
    raise EnrollError("wstunnel did not open its local forward port in time")


def _verify_endpoint(config: ClientConfig, url: str) -> None:
    """Apply the profile's trust model to the enrolment host before posting.

    Skipped for a loopback URL, which only happens in tests and manual
    debugging: there is no certificate to pin there.
    """
    parts = urlsplit(url)
    host, port = parts.hostname or "", parts.port or 443
    if not host or host in ("localhost", "127.0.0.1", "::1"):
        return

    tls = config.tls
    try:
        if tls.verify == "ca":
            # Nothing to do beyond what urlopen's default context already
            # enforces; probing separately would only add a round trip.
            return
        if tls.spki_sha256:
            verify_tls_spki(host, port, tls.spki_sha256)
        elif tls.cert_fingerprint_sha256:
            verify_tls_fingerprint(host, port, tls.cert_fingerprint_sha256)
    except FingerprintMismatchError as exc:
        raise EnrollError(
            "Refusing to enrol: the server at the enrolment endpoint is not the one "
            f"this profile was issued for.\n{exc}",
            terminal=True,
        ) from exc
    except NetworkError as exc:
        raise EnrollError(f"Could not reach the enrolment endpoint {host}:{port}: {exc}") from exc


def _post(url: str, body: dict, config: ClientConfig) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
    )
    ctx = None
    if url.startswith("https://"):
        ctx = ssl.create_default_context()
        if config.tls.verify != "ca":
            # A pinned (self-signed) endpoint cannot satisfy the default
            # context, so relax it here — but only once _verify_endpoint above
            # has actually authenticated the host against the profile's pin.
            # In "ca" mode the default context above is left intact: it is the
            # only thing standing between this POST (token + client public
            # key) and a MITM, since _verify_endpoint does no pin check there.
            ctx.check_hostname = False
            ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        # The server answered: the token, not the transport, is the problem.
        raise EnrollError(_http_error_message(exc), terminal=True) from exc
    except ssl.SSLCertVerificationError as exc:
        raise EnrollError(
            "The enrolment endpoint's certificate is not trusted: "
            f"{exc.verify_message or exc}"
        ) from exc
    except (urllib.error.URLError, OSError, TimeoutError) as exc:
        raise EnrollError(f"Could not reach the enrolment endpoint: {exc}") from exc
    except (json.JSONDecodeError, UnicodeDecodeError) as exc:
        raise EnrollError("The enrolment endpoint returned a malformed response") from exc


def _http_error_message(exc: urllib.error.HTTPError) -> str:
    detail = ""
    try:
        body = json.loads(exc.read().decode("utf-8", "replace"))
        detail = str(body.get("error") or "")
    except Exception:
        detail = ""
    if exc.code == 429:
        return "The server is rate-limiting enrolment attempts. Wait a minute and retry."
    if detail:
        return f"Enrolment was refused: {detail}"
    return f"Enrolment was refused (HTTP {exc.code})."


def enroll_and_save(config: ClientConfig, dest) -> ClientConfig:
    """Complete enrolment and persist the finished profile over `dest`.

    Called by the import paths after the file has been parsed, so a profile is
    only ever written out once it can actually connect.
    """
    completed = enroll(config)
    try:
        completed.save(dest)
    except OSError as exc:
        raise EnrollError(f"Could not save the enrolled profile: {exc}") from exc
    return completed


# Re-exported so callers can catch one type from either half of the flow.
__all__ = [
    "CertificateNotTrustedError",
    "ConfigError",
    "EnrollError",
    "enroll",
    "enroll_and_save",
    "needs_enrollment",
]
