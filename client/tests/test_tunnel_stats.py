from __future__ import annotations

from outwarp.tunnel_stats import StatsSampler, TunnelStats


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
