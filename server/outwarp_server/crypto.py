from __future__ import annotations

import contextlib
import datetime
import hashlib
import ipaddress
import logging
import os
import shutil
import subprocess
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import ExtendedKeyUsageOID, NameOID

log = logging.getLogger(__name__)

# 825 days — the CA/Browser Forum maximum before it dropped to 398, and still a
# value real certificates carry. The previous 3650 was a single-field giveaway
# to anything parsing the Certificate message on port 443. Renewal is not an
# operational cliff because renew_tls_cert() reuses the key, so clients pinning
# tls.spki_sha256 ride straight through it.
_CERT_VALIDITY_DAYS = 825


class CryptoError(RuntimeError):
    pass


def _build_self_signed(
    private_key: ec.EllipticCurvePrivateKey, common_name: str
) -> x509.Certificate:
    """Issue a self-signed leaf for `common_name`.

    The extension set deliberately mirrors what a public CA puts on an ECDSA
    leaf — basicConstraints, keyUsage digitalSignature, extKeyUsage serverAuth,
    subject/authority key identifiers. None of it makes the certificate *trusted*
    anywhere, but their absence was a free structural signal for anything
    inspecting the handshake, and adding them costs nothing. What still marks
    this certificate as self-signed is the issuer and the missing chain; that is
    what the Caddy + ACME branch of the wizard exists to solve.
    """
    subject = issuer = x509.Name([
        x509.NameAttribute(NameOID.COMMON_NAME, common_name),
    ])
    public_key = private_key.public_key()
    now = datetime.datetime.now(datetime.UTC)

    try:
        san = x509.SubjectAlternativeName([x509.IPAddress(ipaddress.ip_address(common_name))])
    except ValueError:
        san = x509.SubjectAlternativeName([x509.DNSName(common_name)])

    return (
        x509.CertificateBuilder()
        .subject_name(subject)
        .issuer_name(issuer)
        .public_key(public_key)
        .serial_number(x509.random_serial_number())
        .not_valid_before(now)
        .not_valid_after(now + datetime.timedelta(days=_CERT_VALIDITY_DAYS))
        .add_extension(san, critical=False)
        .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
        .add_extension(
            x509.KeyUsage(
                digital_signature=True,
                content_commitment=False,
                key_encipherment=False,
                data_encipherment=False,
                key_agreement=False,
                key_cert_sign=False,
                crl_sign=False,
                encipher_only=False,
                decipher_only=False,
            ),
            critical=True,
        )
        .add_extension(
            x509.ExtendedKeyUsage([ExtendedKeyUsageOID.SERVER_AUTH]), critical=False
        )
        .add_extension(x509.SubjectKeyIdentifier.from_public_key(public_key), critical=False)
        .add_extension(
            x509.AuthorityKeyIdentifier.from_issuer_public_key(public_key), critical=False
        )
        .sign(private_key, hashes.SHA256())
    )


def _write_key(private_key: ec.EllipticCurvePrivateKey, key_path: Path) -> None:
    # Key is at-rest unencrypted (NoEncryption) so wstunnel can boot
    # unattended via systemd; defense-in-depth lives in the 0o600 perms.
    # mkstemp opens with 0o600 on POSIX, os.replace renames atomically — the
    # key never exists at 0o644 even for a microsecond.
    _atomic_write_secret_bytes(
        key_path,
        private_key.private_bytes(
            encoding=serialization.Encoding.PEM,
            format=serialization.PrivateFormat.PKCS8,
            encryption_algorithm=serialization.NoEncryption(),
        ),
    )


def generate_tls_cert(
    common_name: str,
    dest_dir: Path,
    cert_name: str = "cert.pem",
    key_name: str = "key.pem",
) -> tuple[Path, Path, str, str]:
    """Generate a self-signed EC P-256 TLS certificate.

    Returns (cert_path, key_path, sha256_fingerprint, spki_sha256).
    """
    dest_dir.mkdir(parents=True, exist_ok=True)
    cert_path = dest_dir / cert_name
    key_path = dest_dir / key_name

    private_key = ec.generate_private_key(ec.SECP256R1())
    cert = _build_self_signed(private_key, common_name)

    _write_key(private_key, key_path)
    # The cert is public; default 0o644 is fine.
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))

    fingerprint = compute_cert_fingerprint(cert_path)
    spki = compute_spki_fingerprint(cert_path)
    log.info("Generated TLS cert: %s (fingerprint: %s)", cert_path, fingerprint)
    return cert_path, key_path, fingerprint, spki


def renew_tls_cert(cert_path: Path, key_path: Path, common_name: str) -> tuple[str, str]:
    """Reissue the certificate at `cert_path` against the *existing* private key.

    Reusing the key is the whole point: the SubjectPublicKeyInfo is unchanged, so
    every profile pinning ``tls.spki_sha256`` keeps validating. Profiles issued
    before that field existed pin the certificate itself and do need a fresh
    .owcfg — the CLI says so when it prints the new fingerprint.

    Returns the new (sha256_fingerprint, spki_sha256).
    """
    try:
        key = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
    except (OSError, ValueError, TypeError) as exc:
        raise CryptoError(
            f"Could not load the existing TLS private key at {key_path}: {exc}"
        ) from exc
    if not isinstance(key, ec.EllipticCurvePrivateKey):
        raise CryptoError(
            f"TLS private key at {key_path} is not an EC key; renewal expects the "
            "EC P-256 key generated at setup."
        )

    cert = _build_self_signed(key, common_name)
    cert_path.write_bytes(cert.public_bytes(serialization.Encoding.PEM))
    fingerprint = compute_cert_fingerprint(cert_path)
    spki = compute_spki_fingerprint(cert_path)
    log.info("Renewed TLS cert: %s (fingerprint: %s)", cert_path, fingerprint)
    return fingerprint, spki


def compute_cert_fingerprint(cert_path: Path) -> str:
    """Read a PEM certificate and return its SHA-256 fingerprint as colon-separated hex."""
    cert_pem = cert_path.read_bytes()
    cert = x509.load_pem_x509_certificate(cert_pem)
    return _colon_hex(cert.fingerprint(hashes.SHA256()))


def compute_spki_fingerprint(cert_path: Path) -> str:
    """SHA-256 over the certificate's DER SubjectPublicKeyInfo, colon-separated hex.

    This is the value clients pin as ``tls.spki_sha256``; it survives reissuing
    the certificate, which the certificate fingerprint does not.
    """
    cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
    spki = cert.public_key().public_bytes(
        encoding=serialization.Encoding.DER,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    return _colon_hex(hashlib.sha256(spki).digest())


def _colon_hex(digest: bytes) -> str:
    return ":".join(f"{b:02X}" for b in digest)


def find_wg_binary() -> Path:
    """Locate the `wg` binary on PATH."""
    wg = shutil.which("wg")
    if wg is None:
        raise CryptoError(
            "WireGuard tools not found. Install wireguard-tools "
            "(e.g. 'apt install wireguard-tools' or 'brew install wireguard-tools')"
        )
    return Path(wg)


def generate_wg_keypair(wg_bin: Path | None = None) -> tuple[str, str]:
    """Generate a WireGuard keypair via `wg genkey` / `wg pubkey`.

    Returns (private_key, public_key) as base64 strings.
    """
    wg = str(wg_bin or find_wg_binary())

    try:
        genkey = subprocess.run(
            [wg, "genkey"],
            capture_output=True,
            text=True,
            check=True,
        )
        private_key = genkey.stdout.strip()

        pubkey = subprocess.run(
            [wg, "pubkey"],
            input=private_key,
            capture_output=True,
            text=True,
            check=True,
        )
        public_key = pubkey.stdout.strip()
    except FileNotFoundError as exc:
        raise CryptoError(f"wg binary not found at {wg}") from exc
    except subprocess.CalledProcessError as exc:
        raise CryptoError(f"WireGuard key generation failed: {exc.stderr.strip()}") from exc

    return private_key, public_key


def generate_psk(wg_bin: Path | None = None) -> str:
    """Generate a WireGuard preshared key via `wg genpsk`.

    A PSK is a per-peer symmetric secret mixed into the handshake on top of the
    public-key crypto. It is the standard WireGuard hardening against a future
    quantum attacker who records traffic now and breaks Curve25519 later — the
    PSK is never transmitted, so such an attacker still can't derive the session
    keys. Returns a base64 string.
    """
    wg = str(wg_bin or find_wg_binary())
    try:
        result = subprocess.run(
            [wg, "genpsk"],
            capture_output=True,
            text=True,
            check=True,
        )
    except FileNotFoundError as exc:
        raise CryptoError(f"wg binary not found at {wg}") from exc
    except subprocess.CalledProcessError as exc:
        raise CryptoError(f"WireGuard PSK generation failed: {exc.stderr.strip()}") from exc
    return result.stdout.strip()


def _atomic_write_secret_bytes(path: Path, payload: bytes) -> None:
    """Bytes-payload variant of the atomic secret-writer used by config.py.

    Duplicated here (rather than imported) so crypto.py stays free of a
    runtime dep on outwarp_server.config — keeps the dependency graph
    flowing one direction (config → crypto, never the reverse).
    """
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(
        prefix=f".{path.name}.", suffix=".tmp", dir=str(path.parent)
    )
    try:
        with os.fdopen(fd, "wb") as fh:
            fh.write(payload)
            fh.flush()
            os.fsync(fh.fileno())
        os.replace(tmp_name, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp_name)
        raise
