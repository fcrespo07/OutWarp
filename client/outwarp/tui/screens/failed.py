from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

from outwarp.i18n import t as tr
from outwarp.logs import default_log_path
from outwarp.tui.tokens import BAD, DIM


def _last_log_lines(n: int = 10) -> list[str]:
    path = default_log_path()
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return []
    lines = [ln for ln in text.splitlines() if ln.strip()]
    return lines[-n:]


def _error_hint(err: str) -> str:
    low = err.lower()
    if "fingerprint" in low or "cert" in low or "tls" in low:
        return tr("tui.failed.hint_tls")
    if "timeout" in low or "timed out" in low:
        return tr("tui.failed.hint_timeout")
    if "refused" in low or "connection refused" in low:
        return tr("tui.failed.hint_refused")
    if "expired" in low:
        return tr("tui.failed.hint_expired")
    if "permission" in low or "operation not permitted" in low:
        return tr("tui.failed.hint_permission")
    if "wstunnel" in low and ("not found" in low or "no such" in low):
        return tr("tui.failed.hint_wstunnel")
    if "wireguard" in low or "wg-quick" in low:
        return tr("tui.failed.hint_wireguard")
    return tr("tui.failed.hint_generic")


class FailedScreen(Screen):
    """Terminal state after max_attempts retries — offers a manual retry."""

    BINDINGS = [
        ("r", "retry", tr("tui.key.retry")),
        ("q", "quit", tr("tui.key.quit")),
        ("l", "open_logs", tr("tui.key.logs")),
    ]

    def action_open_logs(self) -> None:
        self.app.push_screen("logs")

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="empty-shell"):
            yield Static(f"[bold]{tr('tui.failed.title')}[/bold]")
            err = (
                getattr(self.app, "_startup_error", None)
                or (self.app.manager and self.app.manager.last_error)
                or "unknown error"
            )
            yield Static(f"[{BAD}]{err}[/]")
            yield Static(f"[{DIM}]{_error_hint(err)}[/]")
            yield Static(
                f"[{DIM}]{tr('tui.failed.keys')}[/]"
            )
            recent = _last_log_lines(8)
            if recent:
                yield Static("")
                yield Static(f"[{DIM}]— {tr('tui.failed.recent_log')} —[/]")
                for line in recent:
                    upper = line[:60].upper()
                    if "[ERROR]" in upper or "ERROR " in upper or "[CRITICAL]" in upper:
                        yield Static(f"[{BAD}]{line}[/]")
                    elif "[WARN" in upper or "WARN " in upper:
                        from outwarp.tui.tokens import WARN
                        yield Static(f"[{WARN}]{line}[/]")
                    else:
                        yield Static(f"[{DIM}]{line}[/]")
        yield Footer()

    def action_retry(self) -> None:
        self.notify(tr("tui.failed.retrying"), severity="information")
        self.app.start_manager()
