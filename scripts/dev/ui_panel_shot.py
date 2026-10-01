"""Log into a running panel and screenshot one screen.

    python scripts/dev/ui_panel_shot.py URL TOKEN OUT.png \
        [--scheme dark|light] [--width 1300] \
        [--screen dashboard|traffic|clients|service|logs|settings|doctor] [--window "24 h"]

URL is e.g. http://127.0.0.1:18777/ (ui_panel_demo.py) or a proxy in front of it.
"""

from __future__ import annotations

import argparse

from _common import launch_chromium
from playwright.sync_api import sync_playwright

ap = argparse.ArgumentParser()
ap.add_argument("url")
ap.add_argument("token")
ap.add_argument("out")
ap.add_argument("--scheme", default="dark", choices=["dark", "light"])
ap.add_argument("--width", type=int, default=1300)
ap.add_argument("--screen", default="dashboard")
ap.add_argument("--window", default="", help="Traffic window button label, e.g. '24 h'")
ap.add_argument("--wait-ms", type=int, default=1500)
args = ap.parse_args()

NAV = {"traffic": "Traffic", "service": "Service", "logs": "Logs", "settings": "Settings",
       "clients": "Clients", "doctor": "Doctor"}

with sync_playwright() as p:
    b = launch_chromium(p)
    pg = b.new_page(viewport={"width": args.width, "height": 1200}, color_scheme=args.scheme,
                    ignore_https_errors=True)
    pg.on("pageerror", lambda e: print("pageerror:", e))
    pg.on("console", lambda m: print("console:", m.text) if m.type == "error" else None)
    pg.goto(args.url)
    pg.wait_for_selector("input[type=password]")
    pg.fill("input[type=password]", args.token)
    pg.keyboard.press("Enter")
    pg.wait_for_timeout(1500)
    if args.screen != "dashboard":
        if args.width < 860:
            pg.get_by_role("button", name="Menu").first.click()
            pg.wait_for_timeout(400)
        pg.get_by_role("button", name=NAV[args.screen]).first.click()
    pg.wait_for_timeout(args.wait_ms)
    if args.window:
        pg.get_by_role("button", name=args.window, exact=True).first.click()
        pg.wait_for_timeout(800)
    pg.screenshot(path=args.out, full_page=True)
    b.close()
print("wrote", args.out)
