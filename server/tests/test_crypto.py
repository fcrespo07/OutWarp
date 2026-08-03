from __future__ import annotations

import re
import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp_server.crypto import (
    CryptoError,
    compute_cert_fingerprint,
    compute_spki_fingerprint,
    generate_psk,
    generate_tls_cert,
    generate_wg_keypair,
    renew_tls_cert,
)

_FINGERPRINT_RE = re.compile(r"^([0-9A-Fa-f]{2}:){31}[0-9A-Fa-f]{2}$")


class TestTlsCert:
    def test_generates_cert_and_key_files(self, tmp_path: Path) -> None:
        cert_path, key_path, fp, _ = generate_tls_cert("203.0.113.42", tmp_path)
        assert cert_path.exists()
        assert key_path.exists()
        assert cert_path.read_text().startswith("-----BEGIN CERTIFICATE-----")
        assert key_path.read_text().startswith("-----BEGIN")

    @pytest.mark.skipif(sys.platform == "win32", reason="POSIX perm bits not enforced on NTFS")
    def test_key_file_is_0600(self, tmp_path: Path) -> None:
        """The TLS private key is unencrypted at rest (so wstunnel can boot
        unattended via systemd). 0o600 is the only thing standing between a
        local attacker and the key — must hold under a default 0o022 umask."""
        import os
        old_umask = os.umask(0o022)
        try:
            cert_path, key_path, _, _ = generate_tls_cert("203.0.113.42", tmp_path)
        finally:
            os.umask(old_umask)
        assert key_path.stat().st_mode & 0o777 == 0o600
        # The cert is the public half — keep it world-readable so the existing
        # `cat cert.pem` / curl flows keep working without sudo.
        assert cert_path.stat().st_mode & 0o004 == 0o004

    def test_fingerprint_format(self, tmp_path: Path) -> None:
        _, _, fp, _ = generate_tls_cert("example.com", tmp_path)
        assert _FINGERPRINT_RE.match(fp), f"Fingerprint format invalid: {fp}"

    def test_compute_fingerprint_matches(self, tmp_path: Path) -> None:
        cert_path, _, fp, _ = generate_tls_cert("10.0.0.1", tmp_path)
        fp2 = compute_cert_fingerprint(cert_path)
        assert fp == fp2

    def test_ip_san_for_ip_address(self, tmp_path: Path) -> None:
        from cryptography import x509

        cert_path, _, _, _ = generate_tls_cert("203.0.113.42", tmp_path)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        ips = san.value.get_values_for_type(x509.IPAddress)
        assert len(ips) == 1

    def test_dns_san_for_domain(self, tmp_path: Path) -> None:
        from cryptography import x509

        cert_path, _, _, _ = generate_tls_cert("vpn.example.com", tmp_path)
        cert = x509.load_pem_x509_certificate(cert_path.read_bytes())
        san = cert.extensions.get_extension_for_class(x509.SubjectAlternativeName)
        names = san.value.get_values_for_type(x509.DNSName)
        assert "vpn.example.com" in names

    def test_creates_dest_dir(self, tmp_path: Path) -> None:
        dest = tmp_path / "nested" / "dir"
        cert_path, key_path, _, _ = generate_tls_cert("10.0.0.1", dest)
        assert cert_path.exists()


class TestWgKeypair:
    def test_generates_keypair_with_mocked_wg(self) -> None:
        mock_genkey = MagicMock()
        mock_genkey.stdout = "cHJpdmF0ZWtleQ==\n"
        mock_pubkey = MagicMock()
        mock_pubkey.stdout = "cHVibGlja2V5\n"

        with patch("outwarp_server.crypto.subprocess.run") as mock_run:
            mock_run.side_effect = [mock_genkey, mock_pubkey]
            priv, pub = generate_wg_keypair(wg_bin=Path("/usr/bin/wg"))

        assert priv == "cHJpdmF0ZWtleQ=="
        assert pub == "cHVibGlja2V5"
        assert mock_run.call_count == 2

    def test_raises_on_missing_binary(self) -> None:
        with patch("outwarp_server.crypto.shutil.which", return_value=None), \
                pytest.raises(CryptoError, match="WireGuard tools not found"):
            generate_wg_keypair()

    def test_raises_on_subprocess_failure(self) -> None:
        import subprocess

        with patch("outwarp_server.crypto.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(
                1, "wg", stderr="error"
            )
            with pytest.raises(CryptoError, match="key generation failed"):
                generate_wg_keypair(wg_bin=Path("/usr/bin/wg"))


class TestPsk:
    def test_generates_psk_with_mocked_wg(self) -> None:
        mock = MagicMock()
        mock.stdout = "cHJlc2hhcmVka2V5MDAwMDAwMDAwMDAwMDAwMDAwMDA=\n"
        with patch("outwarp_server.crypto.subprocess.run", return_value=mock) as run:
            psk = generate_psk(wg_bin=Path("/usr/bin/wg"))
        assert psk == "cHJlc2hhcmVka2V5MDAwMDAwMDAwMDAwMDAwMDAwMDA="
        cmd = run.call_args[0][0]
        assert cmd[-1] == "genpsk" and len(cmd) == 2

    def test_raises_on_subprocess_failure(self) -> None:
        import subprocess

        with patch("outwarp_server.crypto.subprocess.run") as mock_run:
            mock_run.side_effect = subprocess.CalledProcessError(1, "wg", stderr="boom")
            with pytest.raises(CryptoError, match="PSK generation failed"):
                generate_psk(wg_bin=Path("/usr/bin/wg"))


class TestCertHardening:
    """A CN-only, 10-year, extension-free certificate was a one-rule giveaway to
    anything parsing the Certificate message on 443. These assertions pin the
    structure that makes it look like an ordinary leaf."""

    def _cert(self, tmp_path: Path):
        from cryptography import x509

        cert_path, _, _, _ = generate_tls_cert("vpn.example.com", tmp_path)
        return x509.load_pem_x509_certificate(cert_path.read_bytes())

    def test_is_marked_as_an_end_entity(self, tmp_path: Path) -> None:
        from cryptography import x509

        ext = self._cert(tmp_path).extensions.get_extension_for_class(x509.BasicConstraints)
        assert ext.critical is True
        assert ext.value.ca is False

    def test_key_usage_matches_an_ecdsa_leaf(self, tmp_path: Path) -> None:
        from cryptography import x509

        ext = self._cert(tmp_path).extensions.get_extension_for_class(x509.KeyUsage)
        assert ext.critical is True
        assert ext.value.digital_signature is True
        assert ext.value.key_cert_sign is False

    def test_declares_server_auth(self, tmp_path: Path) -> None:
        from cryptography import x509
        from cryptography.x509.oid import ExtendedKeyUsageOID

        ext = self._cert(tmp_path).extensions.get_extension_for_class(x509.ExtendedKeyUsage)
        assert ExtendedKeyUsageOID.SERVER_AUTH in ext.value

    def test_carries_key_identifiers(self, tmp_path: Path) -> None:
        from cryptography import x509

        exts = self._cert(tmp_path).extensions
        ski = exts.get_extension_for_class(x509.SubjectKeyIdentifier).value
        aki = exts.get_extension_for_class(x509.AuthorityKeyIdentifier).value
        # Self-signed: the authority key *is* the subject key.
        assert aki.key_identifier == ski.digest

    def test_validity_is_not_a_decade(self, tmp_path: Path) -> None:
        cert = self._cert(tmp_path)
        days = (cert.not_valid_after_utc - cert.not_valid_before_utc).days
        assert days == 825


class TestSpkiPinAndRenewal:
    def test_spki_fingerprint_format(self, tmp_path: Path) -> None:
        _, _, _, spki = generate_tls_cert("example.com", tmp_path)
        assert _FINGERPRINT_RE.match(spki), f"SPKI format invalid: {spki}"

    def test_spki_differs_from_the_cert_fingerprint(self, tmp_path: Path) -> None:
        _, _, fp, spki = generate_tls_cert("example.com", tmp_path)
        assert fp != spki

    def test_compute_spki_matches_generate(self, tmp_path: Path) -> None:
        cert_path, _, _, spki = generate_tls_cert("example.com", tmp_path)
        assert compute_spki_fingerprint(cert_path) == spki

    def test_renewal_keeps_the_key_pin_and_changes_the_cert(self, tmp_path: Path) -> None:
        """The whole reason renew-cert exists: clients pin the key, so reissuing
        must not invalidate profiles already in the wild."""
        cert_path, key_path, old_fp, old_spki = generate_tls_cert("example.com", tmp_path)
        key_before = key_path.read_bytes()

        new_fp, new_spki = renew_tls_cert(cert_path, key_path, "example.com")

        assert new_spki == old_spki
        assert new_fp != old_fp
        assert key_path.read_bytes() == key_before
        assert compute_cert_fingerprint(cert_path) == new_fp

    def test_regenerating_from_scratch_breaks_the_key_pin(self, tmp_path: Path) -> None:
        # The --new-key path is meant to invalidate everything; assert it does.
        _, _, _, first = generate_tls_cert("example.com", tmp_path)
        _, _, _, second = generate_tls_cert("example.com", tmp_path)
        assert first != second

    def test_renewal_rejects_a_missing_key(self, tmp_path: Path) -> None:
        with pytest.raises(CryptoError, match="Could not load"):
            renew_tls_cert(tmp_path / "c.pem", tmp_path / "nope.pem", "example.com")

    def test_renewal_rejects_a_non_ec_key(self, tmp_path: Path) -> None:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric import rsa

        key_path = tmp_path / "rsa.pem"
        key_path.write_bytes(
            rsa.generate_private_key(public_exponent=65537, key_size=2048).private_bytes(
                encoding=serialization.Encoding.PEM,
                format=serialization.PrivateFormat.PKCS8,
                encryption_algorithm=serialization.NoEncryption(),
            )
        )
        with pytest.raises(CryptoError, match="not an EC key"):
            renew_tls_cert(tmp_path / "c.pem", key_path, "example.com")
