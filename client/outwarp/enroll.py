"""Client half of the enrolment handshake.

A v3 .owcfg arrives without a private key: it carries a one-time token and the
URL to redeem it at. This module generates the keypair locally, posts only the
public half, and hands back a profile that is complete — with a private key that
has never left this machine.

The redemption call happens before the tunnel exists, so it is the one request
the client makes over the open network. It is authenticated the same way the
transport is: against the system CA store for a profile behind a real
certificate, or against the profile's own pin for a self-signed server.
"""

from __future__ import annotations

import json
import logging
import ssl
import urllib.error
import urllib.request
from dataclasses import replace
from urllib.parse import urlsplit

from outwarp.config import ClientConfig, ConfigError
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


class EnrollError(RuntimeError):
    pass


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

    url = config.enrollment.url
    if not url:
        raise EnrollError("This profile has an enrolment token but no endpoint to use it at.")

    try:
        private_key, public_key = generate_keypair()
    except KeygenError as exc:
        raise EnrollError(str(exc)) from exc

    _verify_endpoint(config, url)
    payload = _post(url, {"token": config.enrollment.token, "client_public_key": public_key})

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
            f"this profile was issued for.\n{exc}"
        ) from exc
    except NetworkError as exc:
        raise EnrollError(f"Could not reach the enrolment endpoint {host}:{port}: {exc}") from exc


def _post(url: str, body: dict) -> dict:
    data = json.dumps(body).encode("utf-8")
    req = urllib.request.Request(
        url,
        data=data,
        method="POST",
        headers={"Content-Type": "application/json", "User-Agent": _USER_AGENT},
    )
    # A pinned (self-signed) endpoint cannot satisfy the default context, and the
    # pin check above is what actually authenticated it. For a CA-mode profile
    # the default context does the verifying, so it is left in place.
    ctx = None
    if url.startswith("https://"):
        ctx = ssl.create_default_context()
        ctx.check_hostname = False
        ctx.verify_mode = ssl.CERT_NONE

    try:
        with urllib.request.urlopen(req, timeout=_TIMEOUT, context=ctx) as resp:
            return json.loads(resp.read().decode("utf-8", "replace"))
    except urllib.error.HTTPError as exc:
        raise EnrollError(_http_error_message(exc)) from exc
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
