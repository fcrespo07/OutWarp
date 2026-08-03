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


class CertificateNotTrustedError(NetworkError):
    """A CA-mode endpoint's chain did not validate against the system trust store.

    Kept apart from FingerprintMismatchError because the remediation differs: a
    CA-mode profile has no pinned fingerprint to re-import, and the usual cause
    is a TLS-intercepting middlebox whose root isn't installed locally."""


def tcp_probe(host: str, port: int, timeout: float = 5.0) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def get_tls_fingerprint(host: str, port: int, timeout: float = 5.0) -> str:
    return _colon_hex(hashlib.sha256(_peer_cert_der(host, port, timeout)).digest())


def get_tls_spki_fingerprint(host: str, port: int, timeout: float = 5.0) -> str:
    """SHA-256 over the peer's DER SubjectPublicKeyInfo, colon-hex uppercase.

    Pinning the key rather than the whole certificate (RFC 7469's model) is what
    lets the server reissue its certificate — a shorter, less anomalous validity
    period, or a rebuild — without invalidating every .owcfg already handed out,
    as long as the key is reused.
    """
    der = _peer_cert_der(host, port, timeout)
    return _colon_hex(hashlib.sha256(_spki_der(der)).digest())


def verify_tls_ca(host: str, port: int, timeout: float = 5.0) -> None:
    """Validate the peer's chain and hostname against the system trust store.

    Mirrors, out of band, what wstunnel does in-band once it is passed
    --tls-verify-certificate. Running it first turns an untrusted chain into a
    readable ladder reason instead of an opaque "wstunnel started but no
    handshake" a minute later.
    """
    ctx = ssl.create_default_context()
    try:
        with socket.create_connection((host, port), timeout=timeout) as sock:
            ctx.wrap_socket(sock, server_hostname=host).close()
    except ssl.SSLCertVerificationError as exc:
        raise CertificateNotTrustedError(
            f"TLS certificate for {host}:{port} is not trusted: {exc.verify_message or exc}.\n"
            "This profile authenticates the server against the system CA store. "
            "The usual causes are a network that intercepts TLS with its own root, "
            "an expired server certificate, or a clock that is badly out of sync."
        ) from exc
    except OSError as exc:
        raise NetworkError(
            f"Could not establish TLS connection to {host}:{port}: {exc}"
        ) from exc


def _colon_hex(digest: bytes) -> str:
    return ":".join(f"{b:02X}" for b in digest)


def _peer_cert_der(host: str, port: int, timeout: float) -> bytes:
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
    return der


def _der_tlv(buf: bytes, off: int) -> tuple[int, int, int]:
    """Read one DER tag-length-value at `off`. Returns (tag, value_start, next_off).

    Only the forms X.509 actually uses are handled: low-tag-number tags and
    definite lengths. Anything else is a malformed certificate as far as we're
    concerned.
    """
    try:
        tag = buf[off]
        length = buf[off + 1]
        pos = off + 2
        if length & 0x80:
            n = length & 0x7F
            if n == 0 or n > 4:
                raise NetworkError("Unsupported DER length encoding in certificate")
            length = int.from_bytes(buf[pos:pos + n], "big")
            pos += n
        end = pos + length
        if end > len(buf):
            raise NetworkError("Truncated DER structure in certificate")
    except IndexError as exc:
        raise NetworkError("Truncated DER structure in certificate") from exc
    return tag, pos, end


def _spki_der(cert_der: bytes) -> bytes:
    """Extract the DER SubjectPublicKeyInfo (tag included) from an X.509 cert.

    Hand-rolled because the client deliberately has no `cryptography` dependency
    — it would pull a compiled wheel into every PyInstaller bundle for this one
    field. The walk is positional, which DER makes unambiguous:
    Certificate → tbsCertificate → [0] version?, serial, sigAlg, issuer,
    validity, subject, subjectPublicKeyInfo.
    """
    _, cert_body, _ = _der_tlv(cert_der, 0)
    tag, tbs_body, _ = _der_tlv(cert_der, cert_body)
    if tag != 0x30:
        raise NetworkError("Certificate does not start with a tbsCertificate SEQUENCE")

    off = tbs_body
    tag, _, nxt = _der_tlv(cert_der, off)
    if tag == 0xA0:  # [0] EXPLICIT version — absent in v1 certs
        off = nxt
    for _ in range(5):  # serial, signature, issuer, validity, subject
        _, _, off = _der_tlv(cert_der, off)

    tag, _, end = _der_tlv(cert_der, off)
    if tag != 0x30:
        raise NetworkError("Could not locate SubjectPublicKeyInfo in certificate")
    return cert_der[off:end]


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


def verify_tls_spki(host: str, port: int, expected: str, timeout: float = 5.0) -> None:
    """Key-level counterpart of verify_tls_fingerprint.

    A mismatch here is strictly stronger evidence of a different server than a
    certificate mismatch is: reissuing a certificate is routine, swapping the
    key underneath it is not.
    """
    actual = get_tls_spki_fingerprint(host, port, timeout)
    if actual.upper() != expected.upper():
        raise FingerprintMismatchError(
            f"TLS public-key pin mismatch for {host}:{port}.\n"
            f"  Expected: {expected.upper()}\n"
            f"  Got:      {actual}\n"
            "The server is presenting a different key than the one this profile "
            "was issued for (possible MITM, server reinstall, or wrong .owcfg). "
            "Re-import a fresh .owcfg from the server admin."
        )
