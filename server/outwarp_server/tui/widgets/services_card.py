from __future__ import annotations

from textual.containers import Container
from textual.widgets import Static


class ServicesCard(Container):
    DEFAULT_CSS = "ServicesCard { layout: vertical; }"

    def compose(self):
        yield Static("SERVICES", classes="card-title")
        yield Static("wstunnel  —", id="svc-wstunnel", classes="value")
        yield Static("wireguard —", id="svc-wg", classes="value")

    def update(self, wstunnel: bool | None, wg: bool | None) -> None:
        def _label(name: str, active: bool | None) -> str:
            if active is True:
                return f"{name}  [#2ee0b3]running[/]"
            if active is False:
                return f"{name}  [#ff5c7a]stopped[/]"
            return f"{name}  [#6e747e]unknown[/]"
        try:
            self.query_one("#svc-wstunnel", Static).update(_label("wstunnel", wstunnel))
            self.query_one("#svc-wg", Static).update(_label("wireguard", wg))
        except Exception:
            pass
