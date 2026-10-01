"""Real server web panel on localhost, backed by a fake manager with moving traffic.

    python scripts/dev/ui_panel_demo.py WORKDIR [--history-minutes 300 | --empty] [--port 18777]

Prints ``READY <admin token>`` and serves http://127.0.0.1:PORT/ until killed
(the token is also in WORKDIR/token.txt). Pair it with ui_panel_shot.py.

This is the single-process panel. The pod/Docker deployment runs ``serve`` and
``web`` as two processes sharing /data (and often sits behind a proxy); UI
changes to the panel must also be checked that way (B-037), see
docs/AGENTS.md → "Pod replica".
"""

from __future__ import annotations

import argparse
import logging
import math
import random
import sqlite3
import sys
import threading
import time
from unittest.mock import MagicMock

from _common import REPO

ap = argparse.ArgumentParser()
ap.add_argument("workdir")
ap.add_argument("--history-minutes", type=int, default=300)
ap.add_argument("--empty", action="store_true", help="no traffic history at all")
ap.add_argument("--port", type=int, default=18777)
args = ap.parse_args()

sys.path.insert(0, str(REPO / "server"))
sys.path.insert(0, str(REPO / "server/tests"))

from pathlib import Path  # noqa: E402

from test_api import _make_config  # noqa: E402

from outwarp_server import web_server  # noqa: E402
from outwarp_server.api import Api  # noqa: E402
from outwarp_server.config import ClientEntry  # noqa: E402
from outwarp_server.logs import setup_logging  # noqa: E402
from outwarp_server.server_manager import ServerState  # noqa: E402
from outwarp_server.traffic_history import TrafficHistory  # noqa: E402
from outwarp_server.web_auth import generate_and_store_token  # noqa: E402

NAMES = ["ana-laptop", "movil-ana", "nas-casa"]
tmp = Path(args.workdir)
tmp.mkdir(parents=True, exist_ok=True)
token = generate_and_store_token(tmp)
handler = setup_logging(log_path=tmp / "s.log")
cfg = _make_config(clients=[
    ClientEntry(name=n, public_key=f"k{i}", address=f"10.0.0.{i + 2}/32") for i, n in enumerate(NAMES)
])

if not args.empty:
    hist = TrafficHistory.for_config_dir(tmp)
    now = int(time.time())
    totals = {f"k{i}": [0, 0] for i in range(len(NAMES))}
    rows = []
    for m in range(args.history_minutes, 0, -1):
        ts = now - m * 60
        for j, key in enumerate(totals):
            busy = 1 + math.sin(ts / 3600 + j) + (3 if (m // 17 + j) % 7 == 0 else 0)
            totals[key][0] += int(random.random() * 2e6 * busy * (j + 1))
            totals[key][1] += int(random.random() * 6e6 * busy / (j + 1))
            rows.append((ts, key, totals[key][0], totals[key][1]))
    with sqlite3.connect(hist.db_path) as c:
        c.executemany("INSERT OR REPLACE INTO snapshot VALUES (?,?,?,?)", rows)

mgr = MagicMock()
mgr.state = mgr.effective_state = ServerState.RUNNING
mgr.config = cfg
mgr._config_path = tmp / "server_config.json"
api = Api(handler, mgr)
tick = {"n": 0}


def fake_clients():
    tick["n"] += 1
    t = time.time()
    return [{
        "name": NAMES[i], "status": "online", "ip": f"10.0.0.{i + 2}",
        "rx_bytes": int(t * 1e5 * (i + 1) + (tick["n"] % 5) * 3e5), "tx_bytes": int(t * 4e4),
        "sampled_at": t, "public_key": f"k{i}", "enrolled": True, "last_handshake": t - 5,
        "expires_at": None, "created_at": t - 1000, "endpoint": "198.51.100.9:51000",
    } for i in range(len(NAMES))]


api.list_clients = fake_clients
web_server.serve(api, ui_dir=REPO / "server/outwarp_server/ui", config_dir=tmp,
                 host="127.0.0.1", port=args.port)
api._start_live_poll()
(tmp / "token.txt").write_text(token)


def chatter() -> None:
    lg = logging.getLogger("demo")
    i = 0
    while True:
        i += 1
        lg.info("demo log line %d", i)
        time.sleep(3)


threading.Thread(target=chatter, daemon=True).start()
print("READY", token, flush=True)
while True:
    time.sleep(1)
