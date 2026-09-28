from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Input, Static

from outwarp_server import operations
from outwarp_server.config import validate_client_name
from outwarp_server.i18n import t as tr
from outwarp_server.ip_pool import PoolExhaustedError, next_available_ip
from outwarp_server.tui.tokens import BAD, DIM, OK, WARN


class AddClientModal(ModalScreen[operations.AddClientResult | None]):
    BINDINGS = [
        ("enter", "submit", tr("tui.add.key_create")),
        ("escape", "cancel", tr("tui.key.cancel")),
        ("Q", "show_qr", "QR"),
    ]

    def __init__(self) -> None:
        super().__init__()
        self._result: operations.AddClientResult | None = None

    def compose(self) -> ComposeResult:
        with Container(id="add-modal"):
            yield Static(f"[bold]{tr('tui.help.add_client')}[/bold]")
            yield Input(placeholder=tr("tui.add.name_ph"), id="name")
            yield Static("", id="preview", classes="info")
            yield Static("", id="result")
            yield Static(
                f"[{WARN}]⚠  {tr('tui.add.secure')}[/]"
            )
            yield Static(
                f"[{DIM}]{tr('tui.add.keys')}[/]"
            )

    def on_mount(self) -> None:
        self._refresh_preview("")

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "name":
            self._refresh_preview(event.value)

    def _refresh_preview(self, name: str) -> None:
        config = self.app.config
        allocated = [c.address for c in config.clients]
        try:
            ip = next_available_ip(config.subnet, config.server_address, allocated)
        except PoolExhaustedError as exc:
            self.query_one("#preview", Static).update(f"[{BAD}]{exc}[/]")
            return
        msg = tr("tui.add.next_ip", ip=ip)
        if name.strip():
            try:
                validate_client_name(name)
            except ValueError as exc:
                msg = f"[{BAD}]{exc}[/]"
        self.query_one("#preview", Static).update(msg)

    def action_submit(self) -> None:
        raw = self.query_one("#name", Input).value
        try:
            name = validate_client_name(raw)
        except ValueError as exc:
            self.query_one("#result", Static).update(f"[{BAD}]{exc}[/]")
            return
        try:
            self._result = operations.add_client(
                self.app.config, name, config_path=self.app.config_path, enroll=True,
            )
        except ValueError as exc:
            self.query_one("#result", Static).update(f"[{BAD}]{exc}[/]")
            return
        except Exception as exc:
            self.query_one("#result", Static).update(f"[{BAD}]{tr('tui.error', error=exc)}[/]")
            return

        self.app.reload_config()
        result = self._result
        short_fp = result.owcfg_sha256.replace(":", "")[:10].lower()
        if result.enrollment_expires_at:
            import datetime as _dt
            deadline = _dt.datetime.fromtimestamp(
                result.enrollment_expires_at, _dt.UTC
            ).strftime("%H:%M UTC")
            status = (
                f"  {tr('tui.add.token', deadline=f'[{WARN}]{deadline}[/]')}\n"
                f"  {tr('tui.add.no_key')}"
            )
        else:
            status = (
                f"  {tr('tui.add.hot_added')}: "
                f"{f'[{OK}]' + tr('tui.yes') + '[/]' if result.hot_added else f'[{WARN}]no[/]'}"
            )
        msg = (
            f"[{OK}]✓[/]  {result.owcfg_path.name}  sha256 {short_fp}…\n"
            f"  {tr('tui.add.written', path=result.owcfg_path)}\n"
            f"{status}\n"
            f"[{DIM}]{tr('tui.add.after')}[/]"
        )
        self.query_one("#result", Static).update(msg)

    def action_show_qr(self) -> None:
        if self._result is None:
            return
        from outwarp_server.tui.modals.qr import QrModal
        self.app.push_screen(QrModal(self._result.owcfg_path))

    def action_cancel(self) -> None:
        self.dismiss(self._result)
