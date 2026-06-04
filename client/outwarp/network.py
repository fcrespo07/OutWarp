from __future__ import annotations

import hashlib
import re
import secrets
import socket
import ssl
import struct
import subprocess
import sys
from dataclasses import dataclass


class NetworkError(RuntimeError):
    pass


class FingerprintMismatchError(NetworkError):
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
        with socket.create_connection((host, port), timeout=timeout) as sock, \
                ctx.wrap_socket(sock, server_hostname=host) as ssock:
            der = ssock.getpeercert(binary_form=True)
    except OSError as exc:
        raise NetworkError(
            f"Could not establish TLS connection to {host}:{port}: {exc}"
        ) from exc
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


@dataclass(frozen=True)
class HostileDetection:
    """Result of probing the local network for tunnel-hostile behaviour."""

    hostile: bool
    reason: str  # short human-readable phrase; empty when not hostile

    def __bool__(self) -> bool:  # convenience for `if detect_hostile_network(...):`
        return self.hostile


def _query_dns_a_record_via(server_ip: str, hostname: str, timeout: float = 2.0) -> str | None:
    """Send a minimal DNS-over-UDP A query directly to `server_ip` (port 53).

    Bypasses the system resolver entirely so we can compare what the OS DNS
    sees with what an authoritative public resolver (Cloudflare) sees. Returns
    the first A record, or None on any error/no record. Best-effort: a None
    return is not the same as "not hostile", just "couldn't tell".
    """
    try:
        labels = [bytes([len(part)]) + part.encode("ascii") for part in hostname.split(".")]
    except UnicodeEncodeError:
        return None
    qname = b"".join(labels) + b"\x00"
    # Randomised txn id: a fixed value let an on-path attacker who knows the
    # OutWarp signature pre-forge a matching response and skew the heuristic.
    txn = secrets.token_bytes(2)
    header = txn + struct.pack(">HHHHH", 0x0100, 1, 0, 0, 0)
    question = qname + struct.pack(">HH", 1, 1)  # QTYPE=A, QCLASS=IN
    packet = header + question
    sock = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
    try:
        sock.settimeout(timeout)
        sock.sendto(packet, (server_ip, 53))
        data, _ = sock.recvfrom(4096)
    except OSError:
        return None
    finally:
        sock.close()
    if len(data) < 12 or data[:2] != txn:
        return None
    # Skip header + question section to reach answers. Question = qname + 4 bytes.
    i = 12 + len(qname) + 4
    ancount = struct.unpack(">H", data[6:8])[0]
    for _ in range(ancount):
        # Each RR starts with a NAME (compressed pointer 2 bytes here in practice).
        if i + 12 > len(data):
            return None
        # Skip NAME (compressed: 0xC0 + offset = 2 bytes; otherwise walk it).
        if data[i] & 0xC0 == 0xC0:
            i += 2
        else:
            while i < len(data) and data[i] != 0:
                i += data[i] + 1
            i += 1
        rtype, _rclass, _ttl, rdlength = struct.unpack(">HHIH", data[i:i + 10])
        i += 10
        if rtype == 1 and rdlength == 4:  # A record
            return socket.inet_ntoa(data[i:i + 4])
        i += rdlength
    return None


def detect_hostile_network(
    endpoint: str,
    public_resolver: str = "1.1.1.1",
    timeout: float = 2.0,
) -> HostileDetection:
    """Probe whether the local network looks tunnel-hostile.

    Two signals, in order of confidence:

    1. **DNS mismatch.** Resolve `endpoint` via the system stub resolver AND via
       a direct UDP query to a public resolver. Different IPs is strong evidence
       of DNS interception (captive portal, edu MITM resolver, ISP hijack).
    2. **System DNS failure where public works.** System says NXDOMAIN/timeout
       but the public resolver answers — same conclusion.

    Network failures (no internet at all) return ``hostile=False`` so we don't
    misfire on a genuinely-offline machine. The detector is best-effort; callers
    treat ``hostile=False`` as "no evidence" rather than "definitely safe".
    """
    # Skip the lookup entirely if the endpoint is already a literal IP — there
    # is nothing for the resolver to lie about.
    try:
        socket.inet_aton(endpoint)
        return HostileDetection(hostile=False, reason="")
    except OSError:
        pass

    try:
        system_ip = socket.gethostbyname(endpoint)
    except OSError:
        system_ip = None

    public_ip = _query_dns_a_record_via(public_resolver, endpoint, timeout=timeout)

    if system_ip and public_ip and system_ip != public_ip:
        return HostileDetection(
            hostile=True,
            reason=(
                f"DNS interception detected: system says {system_ip}, "
                f"{public_resolver} says {public_ip}"
            ),
        )
    if not system_ip and public_ip:
        return HostileDetection(
            hostile=True,
            reason=f"system DNS cannot resolve {endpoint} but {public_resolver} can",
        )
    return HostileDetection(hostile=False, reason="")


def verify_tls_fingerprint(host: str, port: int, expected: str, timeout: float = 5.0) -> None:
    actual = get_tls_fingerprint(host, port, timeout)
    if actual.upper() != expected.upper():
        raise FingerprintMismatchError(
            f"TLS certificate fingerprint mismatch for {host}:{port}.\n"
            f"  Expected: {expected.upper()}\n"
            f"  Got:      {actual}\n"
            "The server certificate has changed (possible MITM, server reinstall, "
            "or wrong .owcfg). Re-import a fresh .owcfg from the server admin."
        )
