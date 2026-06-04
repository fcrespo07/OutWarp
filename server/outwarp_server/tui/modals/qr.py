from __future__ import annotations

from pathlib import Path

from textual.app import ComposeResult
from textual.containers import Container
from textual.screen import ModalScreen
from textual.widgets import Static

from outwarp_server.tui.tokens import DIM


def _render_qr_ascii(data: bytes) -> str:
    """Half-block QR — two QR rows per terminal line, fits in ~85 cols at v25."""
    try:
        import qrcode
    except ImportError:
        return "[qrcode] library not installed. pip install qrcode."

    qr = qrcode.QRCode(border=1, error_correction=qrcode.constants.ERROR_CORRECT_L)
    qr.add_data(data)
    try:
        qr.make()
    except qrcode.exceptions.DataOverflowError:
        return (
            "Profile too large to encode in a single QR. "
            "Transfer the .owcfg file directly."
        )
    matrix = qr.get_matrix()
    if not matrix:
        return "(empty QR)"
    # Pad to even number of rows so half-blocks always pair up.
    if len(matrix) % 2:
        matrix.append([False] * len(matrix[0]))

    lines: list[str] = []
    for y in range(0, len(matrix), 2):
        chars: list[str] = []
        for x in range(len(matrix[0])):
            top = matrix[y][x]
            bot = matrix[y + 1][x]
            if top and bot:
                chars.append("█")
            elif top and not bot:
                chars.append("▀")
            elif not top and bot:
                chars.append("▄")
            else:
                chars.append(" ")
        lines.append("".join(chars))
    return "\n".join(lines)


class QrModal(ModalScreen[None]):
    BINDINGS = [
        ("escape", "dismiss", "Back"),
        ("q", "dismiss", "Back"),
    ]

    def __init__(self, owcfg_path: Path) -> None:
        super().__init__()
        self._path = Path(owcfg_path)

    def compose(self) -> ComposeResult:
        try:
            data = self._path.read_bytes()
        except OSError as exc:
            body = f"Cannot read {self._path}: {exc}"
        else:
            body = _render_qr_ascii(data)
        with Container(id="qr-modal"):
            yield Static(f"[bold]QR for {self._path.name}[/bold]")
            yield Static(body)
            yield Static(f"[{DIM}]Esc to close.[/]")

    def action_dismiss(self) -> None:
        self.dismiss()
