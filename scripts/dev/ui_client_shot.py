"""Screenshot of the client GUI with the real ``Api`` and a fake tunnel manager.

The page is the real ``client/outwarp/ui/index.html``; ``window.pywebview.api``
is a Proxy that forwards every call to ``outwarp.api.Api`` in this process, so
what you see is what pywebview would show (minus native window chrome).

    python scripts/dev/ui_client_shot.py STATE SCREEN OUT.png \
        [--scheme dark|light] [--lang es|en] [--width 1000] \
        [--extra-profiles] [--open menu|details]

STATE:  connected | connecting | disconnected | failed | empty
SCREEN: home | import | logs | settings | about

Needs ``pip install playwright`` and the client's deps (``pip install -e client``).
"""

from __future__ import annotations

import argparse
import base64
import json
import logging
import math
import os
import random
import sys
import tempfile
import time
from unittest.mock import MagicMock

from _common import REPO, launch_chromium

ap = argparse.ArgumentParser()
ap.add_argument("state", choices=["connected", "connecting", "disconnected", "failed", "empty"])
ap.add_argument("screen", choices=["home", "import", "logs", "settings", "about"])
ap.add_argument("out")
ap.add_argument("--scheme", default="dark", choices=["dark", "light"])
ap.add_argument("--lang", default="es")
ap.add_argument("--width", type=int, default=1000)
ap.add_argument("--height", type=int, default=700)
ap.add_argument("--extra-profiles", action="store_true", help="add two fake profiles")
ap.add_argument("--open", choices=["menu", "details", "diag"], help="open the profile menu / details, or run the health checks")
args = ap.parse_args()

# Isolated config dirs: never touch the real profile store.
home = tempfile.mkdtemp(prefix="owc-shot-")
os.environ["XDG_CONFIG_HOME"] = home + "/cfg"
os.environ["XDG_STATE_HOME"] = home + "/state"
os.environ["APPDATA"] = home + "/appdata"
sys.path.insert(0, str(REPO / "client"))

from playwright.sync_api import sync_playwright  # noqa: E402

from outwarp.api import Api  # noqa: E402
from outwarp.config import ClientConfig  # noqa: E402
from outwarp.logs import _DEFAULT_FORMAT, MemoryLogHandler  # noqa: E402
from outwarp.tunnel import TunnelState  # noqa: E402

raw = json.loads((REPO / "config.example.owcfg").read_text())
fake_key = base64.b64encode(bytes(range(32))).decode()


def _fill_keys(o: object) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and "key" in k and k != "http_upgrade_path_prefix":
                o[k] = fake_key
            else:
                _fill_keys(v)


_fill_keys(raw)
cfg = ClientConfig.loads(json.dumps(raw))

handler = MemoryLogHandler()
handler.setFormatter(logging.Formatter(_DEFAULT_FORMAT))
demo = logging.getLogger("outwarp.demo")
demo.addHandler(handler)
demo.setLevel(logging.INFO)
for i in range(4):
    demo.info("demo line %d: wstunnel up", i)
demo.warning("route direct slow: 480 ms")
demo.error("wstunnel exited (code 1), retrying in 5 s")

mgr = None
if args.state != "empty":
    mgr = MagicMock()
    mgr.state = {
        "connected": TunnelState.CONNECTED,
        "disconnected": TunnelState.DISCONNECTED,
        "failed": TunnelState.FAILED,
        "connecting": TunnelState.CONNECTING,
    }[args.state]
    mgr.config = cfg
    mgr.last_error = (
        "Cannot reach 203.0.113.42 on any configured port (443). The server may be down, "
        "the port(s) may not be open in the server firewall."
        if args.state == "failed" else None
    )
    mgr.attempt = 2 if args.state == "connecting" else 0
    mgr.phase = "tls" if args.state == "connecting" else ""
    mgr.is_active = args.state == "connected"
    mgr.active_route = (
        {"id": "direct-hostile", "label": "Direct (public DNS)", "port": 443}
        if args.state == "connected" else None
    )

api = Api(handler, mgr)
api.bind_window(MagicMock())  # without it the log backfill never runs
api.set_settings({"language": args.lang, "theme": args.scheme, "kill_switch": True})

if args.extra_profiles:
    _orig = api.list_profiles

    def _profiles():
        ps = _orig()
        return ps + [
            {**ps[0], "id": "casa", "name": "casa", "endpoint": "vpn.example.com:443", "active": False},
            {**ps[0], "id": "oficina", "name": "oficina", "endpoint": "198.51.100.7:8443", "active": False},
        ]

    api.list_profiles = _profiles

t0 = time.time()


def call(method: str, payload: str):
    a = json.loads(payload)
    if method == "get_status":
        s = api.get_status()
        if args.state == "connected":
            t = time.time() - t0
            s["stats"] = {
                "rx_bps": 400000 + 300000 * math.sin(t / 3) + random.random() * 1e5,
                "tx_bps": 90000 + random.random() * 4e4,
                "rx_total": int(2.3e9), "tx_total": int(4.1e8),
                "latency_ms": int(31 + random.random() * 4),
                "session_start": time.time() - 5234, "last_handshake": time.time() - 40,
                "exit_ip": "203.0.113.42", "exit_location": "Madrid, ES",
            }
        return s
    fn = getattr(api, method, None)
    if fn is None:
        return None
    try:
        return fn(*a)
    except Exception as e:  # surface it in the page instead of hanging the promise
        return {"ok": False, "error": repr(e)}


NAV = {"import": ["Perfiles", "Profiles"], "logs": ["Registro", "Logs"],
       "settings": ["Ajustes", "Settings"], "about": ["Acerca de", "About"]}

with sync_playwright() as p:
    b = launch_chromium(p)
    pg = b.new_page(viewport={"width": args.width, "height": args.height}, color_scheme=args.scheme)
    pg.on("pageerror", lambda e: print("pageerror:", e))
    pg.expose_function("__owcall", lambda m, a: json.dumps(call(m, a), default=str))
    pg.add_init_script(
        "window.pywebview = { api: new Proxy({}, { get: (_, m) => (m === 'then' ? undefined :"
        " (...a) => window.__owcall(m, JSON.stringify(a)).then((r) => JSON.parse(r))) }) };"
    )
    pg.goto((REPO / "client/outwarp/ui/index.html").as_uri())
    pg.wait_for_timeout(2500)
    for label in NAV.get(args.screen, []):
        loc = pg.get_by_role("button", name=label)
        if loc.count():
            loc.first.click()
            pg.wait_for_timeout(800)
            break
    if args.open == "menu":
        name = "Cambiar de perfil" if args.lang == "es" else "Switch profile"
        pg.get_by_role("button", name=name).first.click()
        pg.wait_for_timeout(400)
    elif args.open == "diag":
        name = "Comprobar" if args.lang == "es" else "Run checks"
        pg.get_by_role("button", name=name).first.click()
        pg.wait_for_timeout(2500)
    elif args.open == "details":
        pg.locator("details summary").first.click()
        pg.wait_for_timeout(300)
    if args.state == "connected":
        # pywebview pushes outwarp:stats at 1 Hz; 4 Hz here fills the chart faster.
        pg.evaluate(
            "() => setInterval(async () => { const s = await window.pywebview.api.get_status();"
            " window.dispatchEvent(new CustomEvent('outwarp:stats', { detail: s.stats })); }, 250)"
        )
        pg.wait_for_timeout(8000)
    pg.screenshot(path=args.out, full_page=True)
    b.close()
print("wrote", args.out)
