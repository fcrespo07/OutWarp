"""Screenshot of the client TUI with the real screens and a fake tunnel manager.

    python scripts/dev/tui_client_shot.py STATE SCREEN OUT.png \
        [--lang es|en] [--size 110x34] [--extra-profiles]

STATE:  connected | connecting | disconnected | failed | empty
SCREEN: home | logs | profile | settings | profiles | help | doctor | import

Textual renders to SVG; Chromium (Playwright) turns it into a PNG. Needs
``pip install playwright`` and ``pip install -e 'client[tui]'``.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import re
import sys
import tempfile
from unittest.mock import patch

from _common import REPO, launch_chromium

ap = argparse.ArgumentParser()
ap.add_argument("state", choices=["connected", "connecting", "disconnected", "failed", "empty"])
ap.add_argument(
    "screen",
    choices=["home", "logs", "profile", "settings", "profiles", "help", "doctor", "import"],
)
ap.add_argument("out")
ap.add_argument("--lang", default="es")
ap.add_argument("--size", default="110x34")
ap.add_argument("--extra-profiles", action="store_true", help="add two fake profiles")
args = ap.parse_args()

home = tempfile.mkdtemp(prefix="owc-tui-shot-")
os.environ["XDG_CONFIG_HOME"] = home + "/cfg"
os.environ["XDG_STATE_HOME"] = home + "/state"
os.environ["XDG_DATA_HOME"] = home + "/data"
os.environ["APPDATA"] = home + "/appdata"
os.environ["OUTWARP_LANG"] = args.lang
sys.path.insert(0, str(REPO / "client"))

from outwarp import profiles  # noqa: E402
from outwarp.tui.app import OutWarpClientTUI  # noqa: E402
from outwarp.tunnel_stats import StatsSampler  # noqa: E402
from outwarp.tunnel import TunnelState  # noqa: E402

fake_key = base64.b64encode(bytes(range(32))).decode()


def _fill_keys(o: object) -> None:
    if isinstance(o, dict):
        for k, v in o.items():
            if isinstance(v, str) and "key" in k and k != "http_upgrade_path_prefix":
                o[k] = fake_key
            else:
                _fill_keys(v)


def _profile_text(name: str, endpoint: str) -> str:
    raw = json.loads((REPO / "config.example.owcfg").read_text())
    _fill_keys(raw)
    raw["name"] = name
    raw["server"]["endpoint"] = endpoint
    return json.dumps(raw)


STATE = {
    "connected": TunnelState.CONNECTED,
    "connecting": TunnelState.CONNECTING,
    "disconnected": TunnelState.DISCONNECTED,
    "failed": TunnelState.FAILED,
}


class FakeManager:
    """Just enough of TunnelManager for the screens."""

    def __init__(self, config, **_kw) -> None:
        self.config = config
        self.state = STATE.get(args.state, TunnelState.DISCONNECTED)
        self.phase = "tls" if args.state == "connecting" else ""
        self.attempt = 2 if args.state in ("connecting", "failed") else 0
        self.last_error = (
            "TLS fingerprint mismatch (expected AB:CD…)" if args.state == "failed" else None
        )
        self.active_route = {"id": "direct", "label": "Direct", "port": 443}
        self.is_active = args.state == "connected"
        self._listeners = []

    def add_listener(self, cb) -> None:
        self._listeners.append(cb)

    def remove_listener(self, cb) -> None:
        pass

    def start(self) -> None:
        pass

    def stop(self) -> None:
        pass


_tick = {"n": 0}


def _fake_sampler(iface: str, peer_endpoint_host: str, **_kw) -> StatsSampler:
    def transfer():
        _tick["n"] += 1
        n = _tick["n"]
        import time

        return (n * 900_000 + 40_000_000, n * 120_000 + 3_000_000, int(time.time()) - 17)

    return StatsSampler(iface, "127.0.0.1", transfer_source=transfer, latency_source=lambda: 31.0)


def _add_profile(pid: str, name: str, endpoint: str) -> None:
    path = profiles.config_path(pid)
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_profile_text(name, endpoint), encoding="utf-8")


if args.state != "empty":
    _add_profile("laptop", "laptop", "vpn.example.com")
    if args.extra_profiles:
        _add_profile("office", "office", "198.51.100.7")
        _add_profile("travel", "travel", "203.0.113.9")
    profiles.set_active("laptop")

KEYS = {
    "logs": "l", "profile": "p", "settings": "s", "profiles": "P", "help": "question_mark",
    "doctor": "d", "import": "i",
}


async def main() -> str:
    w, h = (int(x) for x in args.size.split("x"))
    app = OutWarpClientTUI()
    svg = ""
    with (
        patch("outwarp.tui.app.TunnelManager", FakeManager),
        patch("outwarp.tui.screens.dashboard.StatsSampler", _fake_sampler),
        patch("outwarp.tui.screens.dashboard.DashboardScreen._fetch_geo",
              lambda self: "Frankfurt, Germany (203.0.113.42)"),
        patch("outwarp.tui.screens.doctor.run_all", lambda: _doctor_results()),
        patch("outwarp.notify.notify", lambda *a, **k: None),
    ):
        try:
          async with app.run_test(size=(w, h)) as pilot:
              await pilot.pause(0.5)
              if args.state in ("connected", "failed"):
                  app._route_state(STATE[args.state])
                  await pilot.pause(1.6)
              if args.screen != "home":
                  key = KEYS[args.screen]
                  if args.screen in ("logs", "profile") and args.state == "empty":
                      pass
                  await pilot.press(key)
                  await pilot.pause(0.8)
              if os.environ.get("OWC_DUMP"):
                  for w in app.screen.query("*"):
                      print(type(w).__name__, w.id, w.region)
              svg = app.export_screenshot()
        except asyncio.CancelledError:
            pass  # Textual's shutdown cancels the live-log tail; the SVG is already taken
    return svg


def _doctor_results():
    from outwarp.diagnostics import CheckResult, Status

    return [
        CheckResult("wstunnel", Status.PASS, "/usr/local/bin/wstunnel (wstunnel 10.5.2)"),
        CheckResult("sudoers", Status.FAIL, "sudo -n outwarp-priv failed", "Add a rule",
                    fix_kind="interactive"),
        CheckResult("tray", Status.WARN, "no StatusNotifier watcher", "Install an AppIndicator",
                    fix_kind="manual"),
        CheckResult("hyprland", Status.SKIP, "Not a Hyprland session."),
    ]


svg = asyncio.run(main())
# Textual's SVG pulls Fira Code from a CDN; offline, the screenshot waits on it forever.
svg = re.sub(r"@font-face\s*\{.*?\}", "", svg, flags=re.S).replace('"Fira Code"', "monospace")
svg_path = args.out.rsplit(".", 1)[0] + ".svg"
open(svg_path, "w", encoding="utf-8").write(svg)

from playwright.sync_api import sync_playwright  # noqa: E402

with sync_playwright() as p:
    b = launch_chromium(p)
    page = b.new_page(viewport={"width": 1400, "height": 900})
    page.set_content(f"<body style='margin:0;background:#111'>{svg}</body>")
    page.locator("svg").first.screenshot(path=args.out)
    b.close()
print("wrote", args.out)
