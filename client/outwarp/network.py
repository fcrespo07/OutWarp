from __future__ import annotations

import hashlib
import re
import socket
import ssl
import subprocess
import sys


class NetworkError(RuntimeError):
    pass


class FingerprintMismatch(NetworkError):
    """The endpoint presented a certificate other than the pinned one.

    Distinct from a plain NetworkError (unreachable / no cert) so callers can
    choose to tolerate it on TLS-intercepting networks, where WireGuard's own
    encryption is still the real security boundary."""


def tcp_probe(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_tls_fingerprint(host: str, port: int, timeout: float = 5.0) -> str:
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            with ctx.wrap_socket(sock, server_hostname=host) as ssock:
                der = ssock.getpeercert(binary_form=True)
    except OSError as exc:
        raise NetworkError(f"Could not establish TLS connection to {host}:{port}: {exc}")
    if not der:
        raise NetworkError(f"Server at {host}:{port} did not present a TLS certificate")
    digest = hashlib.sha256(der).hexdigest().upper()
    return ":".join(digest[i:i + 2] for i in range(0, len(digest), 2))


# Matches both English ("time=12.3 ms", "time<1ms") and Spanish-Windows
# ("tiempo=12ms") output of system `ping`.
_PING_TIME_RE = re.compile(r"(?:time|tiempo)[<=]\s*(\d+(?:\.\d+)?)\s*ms", re.IGNORECASE)


def measure_latency_ms(host: str, timeout_ms: int = 2000) -> int | None:
    """Send a single ICMP echo to `host` and return the round-trip time in
    milliseconds, or None if the ping fails / times out / can't be parsed.

    Used to surface tunnel latency in the UI. Best-effort: any failure
    returns None and the caller renders a dash.
    """
    if not host:
        return None
    extra: dict = {}
    if sys.platform == "win32":
        # `-n 1` = one echo, `-w` is in ms on Windows.
        cmd = ["ping", "-n", "1", "-w", str(timeout_ms), host]
        extra["creationflags"] = subprocess.CREATE_NO_WINDOW
    elif sys.platform == "darwin":
        # macOS BSD ping: `-W` is in ms.
        cmd = ["ping", "-c", "1", "-W", str(timeout_ms), host]
    else:
        # iputils ping on Linux: `-W` is in seconds (rounded up).
        seconds = max(1, (timeout_ms + 999) // 1000)
        cmd = ["ping", "-c", "1", "-W", str(seconds), host]
    try:
        result = subprocess.run(
            cmd, capture_output=True, text=True, check=False,
            timeout=(timeout_ms / 1000) + 1.0, **extra,
        )
    except (FileNotFoundError, subprocess.TimeoutExpired):
        return None
    if result.returncode != 0:
        return None
    match = _PING_TIME_RE.search(result.stdout)
    if not match:
        return None
    try:
        return int(round(float(match.group(1))))
    except ValueError:
        return None


def verify_tls_fingerprint(host: str, port: int, expected: str, timeout: float = 5.0) -> None:
    actual = get_tls_fingerprint(host, port, timeout)
    if actual.upper() != expected.upper():
        raise FingerprintMismatch(
            f"TLS certificate fingerprint mismatch for {host}:{port}.\n"
            f"  Expected: {expected.upper()}\n"
            f"  Got:      {actual}\n"
            "The server certificate has changed (possible MITM, server reinstall, "
            "or wrong .owcfg). Re-import a fresh .owcfg from the server admin."
        )
