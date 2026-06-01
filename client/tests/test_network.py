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
    with patch("socket.create_connection", return_value=sock_cm):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value.wrap_socket.return_value = ssl_cm
            fp = get_tls_fingerprint("1.2.3.4", 443)

    # Format check: 32 pairs of hex separated by colons
    parts = fp.split(":")
    assert len(parts) == 32
    assert all(len(p) == 2 for p in parts)
    assert all(c in "0123456789ABCDEF" for p in parts for c in p)


def test_get_tls_fingerprint_raises_when_no_cert_presented():
    sock_cm, ssl_cm = _fake_tls_session(der=None)
    with patch("socket.create_connection", return_value=sock_cm):
        with patch("ssl.create_default_context") as mock_ctx:
            mock_ctx.return_value.wrap_socket.return_value = ssl_cm
            with pytest.raises(NetworkError, match="did not present a TLS certificate"):
                get_tls_fingerprint("1.2.3.4", 443)


def test_get_tls_fingerprint_raises_on_connection_error():
    with patch("socket.create_connection", side_effect=ConnectionRefusedError("nope")):
        with pytest.raises(NetworkError, match="Could not establish TLS connection"):
            get_tls_fingerprint("1.2.3.4", 443)


# --- verify_tls_fingerprint ---

def test_verify_tls_fingerprint_passes_on_match():
    with patch("outwarp.network.get_tls_fingerprint", return_value="AB:CD"):
        verify_tls_fingerprint("h", 443, "ab:cd")  # case-insensitive


def test_verify_tls_fingerprint_raises_on_mismatch():
    with patch("outwarp.network.get_tls_fingerprint", return_value="AB:CD"):
        with pytest.raises(NetworkError, match="fingerprint mismatch"):
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


def test_measure_latency_ms_returns_none_on_empty_host():
    # Don't even shell out for an empty host.
    with patch("outwarp.network.subprocess.run") as run:
        assert measure_latency_ms("") is None
        run.assert_not_called()
