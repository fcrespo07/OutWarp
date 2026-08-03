from __future__ import annotations

from unittest.mock import MagicMock, patch

import pytest

from outwarp.network import (
    NetworkError,
    get_tls_fingerprint,
    measure_latency_ms,
    tcp_probe,
    verify_tls_fingerprint,
)

# --- tcp_probe ---

def test_tcp_probe_returns_true_on_success():
    with patch("socket.create_connection") as mock_conn:
        mock_conn.return_value.__enter__.return_value = MagicMock()
        assert tcp_probe("1.2.3.4", 443) is True


def test_tcp_probe_returns_false_on_connection_refused():
    with patch("socket.create_connection", side_effect=ConnectionRefusedError):
        assert tcp_probe("1.2.3.4", 443) is False


def test_tcp_probe_returns_false_on_timeout():
    with patch("socket.create_connection", side_effect=TimeoutError):
        assert tcp_probe("1.2.3.4", 443) is False


# --- get_tls_fingerprint ---

def _fake_tls_session(der: bytes) -> MagicMock:
    sock_cm = MagicMock()
    sock_cm.__enter__.return_value = MagicMock()

    ssock = MagicMock()
    ssock.getpeercert.return_value = der
    ssl_cm = MagicMock()
    ssl_cm.__enter__.return_value = ssock

    return sock_cm, ssl_cm


def test_get_tls_fingerprint_returns_colon_separated_sha256():
    sock_cm, ssl_cm = _fake_tls_session(der=b"some-cert-bytes")
    with patch("socket.create_connection", return_value=sock_cm), \
            patch("ssl.create_default_context") as mock_ctx:
        mock_ctx.return_value.wrap_socket.return_value = ssl_cm
        fp = get_tls_fingerprint("1.2.3.4", 443)

    # Format check: 32 pairs of hex separated by colons
    parts = fp.split(":")
    assert len(parts) == 32
    assert all(len(p) == 2 for p in parts)
    assert all(c in "0123456789ABCDEF" for p in parts for c in p)


def test_get_tls_fingerprint_raises_when_no_cert_presented():
    sock_cm, ssl_cm = _fake_tls_session(der=None)
    with patch("socket.create_connection", return_value=sock_cm), \
            patch("ssl.create_default_context") as mock_ctx:
        mock_ctx.return_value.wrap_socket.return_value = ssl_cm
        with pytest.raises(NetworkError, match="did not present a TLS certificate"):
            get_tls_fingerprint("1.2.3.4", 443)


def test_get_tls_fingerprint_raises_on_connection_error():
    with patch("socket.create_connection", side_effect=ConnectionRefusedError("nope")), \
            pytest.raises(NetworkError, match="Could not establish TLS connection"):
        get_tls_fingerprint("1.2.3.4", 443)


# --- verify_tls_fingerprint ---

def test_verify_tls_fingerprint_passes_on_match():
    with patch("outwarp.network.get_tls_fingerprint", return_value="AB:CD"):
        verify_tls_fingerprint("h", 443, "ab:cd")  # case-insensitive


def test_verify_tls_fingerprint_raises_on_mismatch():
    with patch("outwarp.network.get_tls_fingerprint", return_value="AB:CD"), \
            pytest.raises(NetworkError, match="fingerprint mismatch"):
        verify_tls_fingerprint("h", 443, "FF:FF")


# --- measure_latency_ms ---

def _ping_result(stdout: str, returncode: int = 0) -> MagicMock:
    r = MagicMock()
    r.stdout = stdout
    r.returncode = returncode
    return r


def test_measure_latency_ms_parses_linux_iputils_output():
    out = (
        "PING 10.0.0.1 (10.0.0.1) 56(84) bytes of data.\n"
        "64 bytes from 10.0.0.1: icmp_seq=1 ttl=64 time=12.3 ms\n"
    )
    with patch("outwarp.network.subprocess.run", return_value=_ping_result(out)):
        assert measure_latency_ms("10.0.0.1") == 12


def test_measure_latency_ms_parses_windows_english_output():
    out = "Reply from 10.0.0.1: bytes=32 time=8ms TTL=64\n"
    with patch("outwarp.network.subprocess.run", return_value=_ping_result(out)):
        assert measure_latency_ms("10.0.0.1") == 8


def test_measure_latency_ms_parses_windows_spanish_output():
    out = "Respuesta desde 10.0.0.1: bytes=32 tiempo=42ms TTL=64\n"
    with patch("outwarp.network.subprocess.run", return_value=_ping_result(out)):
        assert measure_latency_ms("10.0.0.1") == 42


def test_measure_latency_ms_parses_sub_millisecond_reply():
    out = "Reply from 10.0.0.1: bytes=32 time<1ms TTL=64\n"
    with patch("outwarp.network.subprocess.run", return_value=_ping_result(out)):
        assert measure_latency_ms("10.0.0.1") == 1


def test_measure_latency_ms_returns_none_when_ping_fails():
    with patch("outwarp.network.subprocess.run",
               return_value=_ping_result("Request timed out.\n", returncode=1)):
        assert measure_latency_ms("10.0.0.1") is None


def test_measure_latency_ms_returns_none_when_output_unparseable():
    with patch("outwarp.network.subprocess.run", return_value=_ping_result("garbage\n")):
        assert measure_latency_ms("10.0.0.1") is None


def test_measure_latency_ms_returns_none_when_ping_binary_missing():
    with patch("outwarp.network.subprocess.run", side_effect=FileNotFoundError):
        assert measure_latency_ms("10.0.0.1") is None


def test_detect_hostile_network_skips_literal_ip():
    # An endpoint that is already an IP literal can't suffer DNS interception,
    # so the probe short-circuits without touching the network.
    from outwarp.network import detect_hostile_network
    with patch("outwarp.network.socket.gethostbyname") as gh:
        result = detect_hostile_network("203.0.113.42")
    assert result.hostile is False
    gh.assert_not_called()


def test_detect_hostile_network_detects_dns_mismatch():
    from outwarp.network import detect_hostile_network
    with (
        patch("outwarp.network.socket.gethostbyname", return_value="10.99.99.99"),
        patch("outwarp.network._query_dns_a_record_via", return_value="79.112.138.17"),
    ):
        result = detect_hostile_network("wg.example.com")
    assert result.hostile is True
    assert "10.99.99.99" in result.reason
    assert "79.112.138.17" in result.reason


def test_detect_hostile_network_detects_system_nxdomain_when_public_resolves():
    from outwarp.network import detect_hostile_network
    with (
        patch("outwarp.network.socket.gethostbyname", side_effect=OSError("NXDOMAIN")),
        patch("outwarp.network._query_dns_a_record_via", return_value="79.112.138.17"),
    ):
        result = detect_hostile_network("wg.example.com")
    assert result.hostile is True
    assert "system DNS cannot resolve" in result.reason


def test_detect_hostile_network_silent_when_both_agree():
    from outwarp.network import detect_hostile_network
    with (
        patch("outwarp.network.socket.gethostbyname", return_value="79.112.138.17"),
        patch("outwarp.network._query_dns_a_record_via", return_value="79.112.138.17"),
    ):
        result = detect_hostile_network("wg.example.com")
    assert result.hostile is False


def test_detect_hostile_network_silent_when_offline():
    # No internet at all: system fails AND public probe fails. Don't false-fire
    # — there's nothing the hostile-mode flags can do about being offline.
    from outwarp.network import detect_hostile_network
    with (
        patch("outwarp.network.socket.gethostbyname", side_effect=OSError("no net")),
        patch("outwarp.network._query_dns_a_record_via", return_value=None),
    ):
        result = detect_hostile_network("wg.example.com")
    assert result.hostile is False


def test_measure_latency_ms_returns_none_on_empty_host():
    # Don't even shell out for an empty host.
    with patch("outwarp.network.subprocess.run") as run:
        assert measure_latency_ms("") is None
        run.assert_not_called()


# --- SPKI extraction / CA verification (schema v2 pinning) ---

# Fixtures rather than generated certificates: the client deliberately has no
# `cryptography` dependency, so there is nothing in its test environment that
# could produce one. Both were issued offline with known SubjectPublicKeyInfo
# digests, which is exactly what _spki_der has to reproduce.
EC_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIBQDCB56ADAgECAgRJlgLSMAoGCCqGSM49BAMCMBkxFzAVBgNVBAMMDmVjLmV4
YW1wbGUuY29tMB4XDTI2MDEwMTAwMDAwMFoXDTI4MDQwNTAwMDAwMFowGTEXMBUG
A1UEAwwOZWMuZXhhbXBsZS5jb20wWTATBgcqhkjOPQIBBggqhkjOPQMBBwNCAAQc
30tRkf17i1jiZUzll7QD2xY4TaGZhZEzbcbPR1PPGtoFTBbnbIiAjbpBrjva4Cly
wvQ7VtyvDPeNGlJaTp4kox0wGzAZBgNVHREEEjAQgg5lYy5leGFtcGxlLmNvbTAK
BggqhkjOPQQDAgNIADBFAiEAzRJVmBdEdT07HEFZQDYVi9XW0blJ5MQQW433JsSS
nb8CIBBNa6HX9nFUCCRSJkUpUUOrI4Ysxv4lkmylFNoFH7AI
-----END CERTIFICATE-----"""
EC_SPKI = (
    "2E:DD:6C:C8:77:36:57:19:7B:94:90:44:99:36:67:73:"
    "F7:DF:00:6E:B7:4E:0B:01:38:FE:91:D5:87:F0:58:B6"
)

# A 2048-bit RSA cert crosses the DER long-form length boundary that the EC one
# never reaches, which is where a hand-rolled TLV walk goes wrong.
RSA_CERT_PEM = """-----BEGIN CERTIFICATE-----
MIIC0DCCAbigAwIBAgIESZYC0jANBgkqhkiG9w0BAQsFADAaMRgwFgYDVQQDDA9y
c2EuZXhhbXBsZS5jb20wHhcNMjYwMTAxMDAwMDAwWhcNMjgwNDA1MDAwMDAwWjAa
MRgwFgYDVQQDDA9yc2EuZXhhbXBsZS5jb20wggEiMA0GCSqGSIb3DQEBAQUAA4IB
DwAwggEKAoIBAQCpzN69Uzy8hIrJP/+rbWrK6NDLPR6zu0JMx7IkeYvcUwl16hNB
+cVLKn8ENk6POZnuD1A2uFmnl6tZYAZPih3Xaz09BY0w+Udb6k+QLvpcHEmaR74i
hrrH4R3QrZY1nSkdYUPq9q/kCyhDHif6rU+J1yyaSEiNr4pBb390inNS3wQUg6KJ
rI3NZcUKLcq9fCpx06N7DgkWRbZ6ZAym+OOmeGJi52ptT8C6j2eoynT+P9iOVXCv
PxLzZQXgol6+pC5OL7MuOwHG50l+h5RCoU6kHsDs9BlLoRFw+DCS4bERB3rS2Sae
kGvfipGO3uyob5o4qg4ndfUS2nOPUbRy8YjbAgMBAAGjHjAcMBoGA1UdEQQTMBGC
D3JzYS5leGFtcGxlLmNvbTANBgkqhkiG9w0BAQsFAAOCAQEAiI0r6o2mBEQbDVEh
Q6Cmh8CkzQxQRlfynJVWaLm9lF40gElzsJpPt76r4qP/HGVrPFauip7UaivYDjkz
lsLyA4uM4w/nsJ9dLnyGeUOXnRJxYj/ULm6JJ17DbMWwgoy5g5sN+BcBx3UwV0LR
tVslAohutcv2mFdPCz/c4JHpQhv4yqW+mSm2h91EwU+GMgPk1ndLigEo4ZoMmI4k
mMZRSkiE7w8+49EiPWG8+kZReKb8VvfduqXjqgZ+YcIpO+g2gKcIF/JzmYjT0Ttn
zBGFIfj1DdXNLTupzRDqyVNY1J06cwEaGVxKNtTeKWwoGkiQWGOopbLHBRDuvy8M
/AvaQA==
-----END CERTIFICATE-----"""
RSA_SPKI = (
    "B3:C7:65:0B:37:EB:2B:FF:AB:21:95:B9:4A:C9:DA:69:"
    "D5:DF:EA:B5:E2:37:7B:CA:BB:4A:29:A9:9F:37:98:60"
)


def _der(pem: str) -> bytes:
    import base64
    body = "".join(
        line for line in pem.splitlines() if not line.startswith("-----")
    )
    return base64.b64decode(body)


@pytest.mark.parametrize("pem,expected", [
    (EC_CERT_PEM, EC_SPKI),
    (RSA_CERT_PEM, RSA_SPKI),
])
def test_spki_fingerprint_matches_reference(pem, expected):
    import hashlib

    from outwarp.network import _spki_der
    spki = _spki_der(_der(pem))
    digest = hashlib.sha256(spki).digest()
    assert ":".join(f"{b:02X}" for b in digest) == expected


def test_spki_der_is_a_well_formed_sequence():
    from outwarp.network import _spki_der
    spki = _spki_der(_der(EC_CERT_PEM))
    assert spki[0] == 0x30  # SEQUENCE, tag included as RFC 7469 requires
    assert len(spki) == spki[1] + 2  # short-form length for a P-256 SPKI


@pytest.mark.parametrize("bad", [b"", b"\x30", b"\x30\x82\xff\xff", b"not-der-at-all"])
def test_spki_der_rejects_garbage(bad):
    from outwarp.network import NetworkError, _spki_der
    with pytest.raises(NetworkError):
        _spki_der(bad)


def test_verify_tls_spki_accepts_matching_pin():
    from outwarp.network import verify_tls_spki
    with patch("outwarp.network.get_tls_spki_fingerprint", return_value=EC_SPKI):
        verify_tls_spki("wg.example.com", 443, EC_SPKI.lower())


def test_verify_tls_spki_rejects_other_key():
    from outwarp.network import FingerprintMismatchError, verify_tls_spki
    with (
        patch("outwarp.network.get_tls_spki_fingerprint", return_value=RSA_SPKI),
        pytest.raises(FingerprintMismatchError, match="public-key pin mismatch"),
    ):
        verify_tls_spki("wg.example.com", 443, EC_SPKI)


def test_verify_tls_ca_raises_not_trusted_on_verification_error():
    import ssl

    from outwarp.network import CertificateNotTrustedError, verify_tls_ca

    exc = ssl.SSLCertVerificationError("self-signed certificate")
    exc.verify_message = "self-signed certificate"
    ctx = MagicMock()
    ctx.wrap_socket.side_effect = exc
    with (
        patch("outwarp.network.ssl.create_default_context", return_value=ctx),
        patch("outwarp.network.socket.create_connection", return_value=MagicMock()),
        pytest.raises(CertificateNotTrustedError, match="not trusted"),
    ):
        verify_tls_ca("wg.example.com", 443)


def test_verify_tls_ca_reports_plain_network_errors_separately():
    from outwarp.network import CertificateNotTrustedError, NetworkError, verify_tls_ca

    with (
        patch("outwarp.network.socket.create_connection", side_effect=OSError("refused")),
        pytest.raises(NetworkError) as excinfo,
    ):
        verify_tls_ca("wg.example.com", 443)
    # An unreachable port must not be reported as an untrusted certificate —
    # the ladder shows the two as different failures.
    assert not isinstance(excinfo.value, CertificateNotTrustedError)


def test_verify_tls_ca_passes_when_chain_validates():
    from outwarp.network import verify_tls_ca

    ctx = MagicMock()
    with (
        patch("outwarp.network.ssl.create_default_context", return_value=ctx),
        patch("outwarp.network.socket.create_connection", return_value=MagicMock()),
    ):
        verify_tls_ca("wg.example.com", 443)
    ctx.wrap_socket.assert_called_once()
    # create_default_context() already means CERT_REQUIRED + hostname checking.
    # Unlike the fingerprint path, this one must never relax either.
    assert not any(
        call[0] in ("check_hostname", "verify_mode")
        for call in getattr(ctx, "method_calls", [])
    )
