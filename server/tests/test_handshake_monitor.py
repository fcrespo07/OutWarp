import logging

from outwarp_server.handshake_monitor import STALE_AFTER_S, HandshakeMonitor
from outwarp_server.wireguard import LivePeer

KEY = "K" * 43 + "="


def _peer(hs):
    return LivePeer(public_key=KEY, endpoint=None, allowed_ips="10.0.0.2/32",
                    latest_handshake=hs, transfer_rx=0, transfer_tx=0)


def _monitor(state):
    return HandshakeMonitor(
        lambda: state["peers"], lambda: [("laptop", KEY)], lambda: state["now"],
    )


def test_logs_each_transition_once(caplog):
    state = {"now": 10_000, "peers": {KEY: _peer(None)}}
    m = _monitor(state)
    with caplog.at_level(logging.INFO):
        m.poll()
        assert "no handshake yet" in caplog.text
        caplog.clear()

        state["peers"] = {KEY: _peer(state["now"] - 5)}
        m.poll()
        m.poll()
        assert caplog.text.count("handshake completed") == 1
        caplog.clear()

        state["now"] += STALE_AFTER_S + 60
        m.poll()
        m.poll()
        assert caplog.text.count("handshake lost") == 1


def test_no_live_data_is_not_a_verdict(caplog):
    state = {"now": 10_000, "peers": {KEY: _peer(9_990)}}
    m = _monitor(state)
    with caplog.at_level(logging.INFO):
        m.poll()
        caplog.clear()
        state["peers"] = {}  # wg unavailable
        state["now"] += 10_000
        m.poll()
    assert "handshake lost" not in caplog.text
