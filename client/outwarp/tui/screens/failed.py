from __future__ import annotations

from textual.app import ComposeResult
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Static

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
        return (
            "TLS fingerprint mismatch — the server cert may have changed. "
            "Re-import the .owcfg or enable TLS-intercept in Settings."
        )
    if "timeout" in low or "timed out" in low:
        return "Connection timed out — check that the server is reachable and the port is open."
    if "refused" in low or "connection refused" in low:
        return "Connection refused — wstunnel may not be running on the server."
    if "permission" in low or "operation not permitted" in low:
        return "Permission denied — run 'outwarp-cli service install' or check sudo/sudoers."
    if "wstunnel" in low and ("not found" in low or "no such" in low):
        return "wstunnel binary missing — reinstall OutWarp or run 'outwarp-cli doctor'."
    if "wireguard" in low or "wg-quick" in low:
        return "WireGuard error — check 'outwarp-cli doctor' for kernel module and tool status."
    return "Run 'outwarp-cli doctor' or press [b]l[/b] to view full logs."


class FailedScreen(Screen):
    """Terminal state after max_attempts retries — offers a manual retry."""

    BINDINGS = [
        ("r", "retry", "Retry"),
        ("q", "quit", "Quit"),
        ("l", "open_logs", "Logs"),
    ]

    def action_open_logs(self) -> None:
        self.app.push_screen("logs")

    def compose(self) -> ComposeResult:
        yield Header()
        with Vertical(id="empty-shell"):
            yield Static("[bold]Tunnel failed[/bold]")
            err = (
                getattr(self.app, "_startup_error", None)
                or (self.app.manager and self.app.manager.last_error)
                or "unknown error"
            )
            yield Static(f"[{BAD}]{err}[/]")
            yield Static(f"[{DIM}]{_error_hint(err)}[/]")
            yield Static(
                f"[{DIM}]Press [b]r[/b] to retry, [b]l[/b] to view logs, [b]q[/b] to quit.[/]"
            )
            recent = _last_log_lines(8)
            if recent:
                yield Static("")
                yield Static(f"[{DIM}]— recent log —[/]")
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
        self.notify("Retrying...", severity="information")
        self.app.start_manager()
