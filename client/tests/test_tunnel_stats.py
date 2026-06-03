from __future__ import annotations

import sys
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from outwarp.tunnel_stats import StatsSampler, TunnelStats, _wg_dump_stdout


def test_sampler_returns_zero_rates_when_wg_missing() -> None:
    s = StatsSampler(
        iface="wg0",
        peer_endpoint_host="vpn.example.com",
        transfer_source=lambda: None,
        latency_source=lambda: None,
    )
    stats = s.sample()
    assert isinstance(stats, TunnelStats)
    assert stats.rx_rate_bps == 0.0
    assert stats.tx_rate_bps == 0.0
    assert stats.latency_ms is None


def test_sampler_computes_rate_between_samples() -> None:
    transfers = iter([(100, 200, 1_700_000_000), (1100, 1200, 1_700_000_001)])
    pings = iter([10.0, 12.0])
    t = iter([0.0, 1.0])

    s = StatsSampler(
        iface="wg0",
        peer_endpoint_host="x",
        transfer_source=lambda: next(transfers),
        latency_source=lambda: next(pings),
        clock=lambda: next(t),
    )
    first = s.sample()
    second = s.sample()
    assert first.rx_rate_bps == 0.0
    assert second.rx_rate_bps == 1000.0
    assert second.tx_rate_bps == 1000.0
    assert s.history_ping_ms() == [10.0, 12.0]


def test_sampler_clamps_negative_delta() -> None:
    transfers = iter([(5000, 5000, None), (10, 10, None)])
    s = StatsSampler(
        iface="wg0",
        peer_endpoint_host="x",
        transfer_source=lambda: next(transfers),
        latency_source=lambda: None,
        clock=iter([0.0, 1.0]).__next__,
    )
    s.sample()
    second = s.sample()
    assert second.rx_rate_bps == 0.0
    assert second.tx_rate_bps == 0.0


def test_sampler_history_window() -> None:
    transfers = iter([(0, 0, None), (1, 1, None), (2, 2, None), (3, 3, None)])
    s = StatsSampler(
        iface="wg0",
        peer_endpoint_host="x",
        history=2,
        transfer_source=lambda: next(transfers),
        latency_source=lambda: None,
        clock=iter([0.0, 1.0, 2.0, 3.0]).__next__,
    )
    for _ in range(4):
        s.sample()
    assert len(s.history_rx_bps()) == 2


# ─── _wg_dump_stdout: helper bridge for `wg show <iface> dump` ───────────────


_DUMP = (
    "srvpriv\tsrvpub\t33801\toff\n"
    "peerpub\tpsk\t1.2.3.4:443\t10.0.0.2/32\t1780000000\t9999\t1111\toff\n"
)


@pytest.mark.skipif(sys.platform == "win32", reason="Linux-only helper bridge")
def test_dump_uses_helper_when_non_root(tmp_path: Path) -> None:
    """On Linux as a regular user, the helper path is the first attempt."""
    fake_helper = tmp_path / "outwarp-priv"
    fake_helper.write_text("#!/bin/sh\nexit 0\n")
    fake_helper.chmod(0o755)
    with patch("outwarp.tunnel_stats.os.geteuid", return_value=1000), \
         patch("outwarp.tunnel_stats.subprocess.run") as mock_run, \
         patch.dict("os.environ", {"OUTWARP_HELPER": str(fake_helper)}):
        mock_run.return_value = MagicMock(returncode=0, stdout=_DUMP, stderr="")
        out = _wg_dump_stdout("OutWarp")
        assert out == _DUMP
        # Confirm we actually went through the helper, not the direct wg call.
        cmd = mock_run.call_args[0][0]
        assert cmd[:3] == ["sudo", "-n", str(fake_helper)]
        assert cmd[3:] == ["dump", "OutWarp"]


@pytest.mark.skipif(sys.platform == "win32", reason="Linux-only helper bridge")
def test_dump_falls_back_to_direct_when_helper_lacks_dump(tmp_path: Path) -> None:
    """An older helper (pre-0.5.8) exits non-zero on `dump` → fall through
    to a direct `wg show` call rather than reporting silence."""
    fake_helper = tmp_path / "outwarp-priv"
    fake_helper.write_text("#!/bin/sh\nexit 2\n")
    fake_helper.chmod(0o755)
    fake_wg = tmp_path / "wg"
    fake_wg.write_text("#!/bin/sh\nexit 0\n")
    fake_wg.chmod(0o755)

    def run_side_effect(cmd: list, **kwargs):
        # First call: helper returns 2 (unknown command on old helper).
        # Second call: direct wg show returns the dump.
        if cmd[0] == "sudo":
            return MagicMock(returncode=2, stdout="", stderr="unknown command")
        return MagicMock(returncode=0, stdout=_DUMP, stderr="")

    with patch("outwarp.tunnel_stats.os.geteuid", return_value=1000), \
         patch("outwarp.tunnel_stats._find_wg", return_value=fake_wg), \
         patch("outwarp.tunnel_stats.subprocess.run", side_effect=run_side_effect) as mock_run, \
         patch.dict("os.environ", {"OUTWARP_HELPER": str(fake_helper)}):
        out = _wg_dump_stdout("OutWarp")
        assert out == _DUMP
        assert mock_run.call_count == 2  # helper then direct


@pytest.mark.skipif(sys.platform == "win32", reason="Linux-only helper bridge")
def test_dump_skips_helper_when_root(tmp_path: Path) -> None:
    """Running as root (e.g. `sudo outwarp-cli tui`) bypasses the helper."""
    fake_wg = tmp_path / "wg"
    fake_wg.write_text("#!/bin/sh\necho ok\n")
    fake_wg.chmod(0o755)
    with patch("outwarp.tunnel_stats.os.geteuid", return_value=0), \
         patch("outwarp.tunnel_stats._find_wg", return_value=fake_wg), \
         patch("outwarp.tunnel_stats.subprocess.run") as mock_run:
        mock_run.return_value = MagicMock(returncode=0, stdout=_DUMP, stderr="")
        out = _wg_dump_stdout("OutWarp")
        assert out == _DUMP
        # Single call: the direct wg one. The helper branch was skipped.
        assert mock_run.call_count == 1
        assert mock_run.call_args[0][0][0] == str(fake_wg)
