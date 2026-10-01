from __future__ import annotations

from pathlib import Path

from textual.containers import Container
from textual.widgets import Static

from outwarp_server.config import ServerConfig
from outwarp_server.i18n import cell_width, pad
from outwarp_server.i18n import t as tr


def _short_fp(fp: str) -> str:
    if len(fp) <= 20:
        return fp
    return f"{fp[:20]}…"


def _cert_expiry(path: str) -> str | None:
    """Best-effort: cryptography may not be importable at runtime."""
    try:
        from cryptography import x509
    except ImportError:
        return None
    try:
        data = Path(path).read_bytes()
        cert = x509.load_pem_x509_certificate(data)
        return cert.not_valid_after_utc.date().isoformat()
    except Exception:
        return None


class TlsCard(Container):
    DEFAULT_CSS = "TlsCard { layout: vertical; height: auto; }"

    def __init__(self, config: ServerConfig) -> None:
        super().__init__()
        self._config = config

    def compose(self):
        c = self._config
        yield Static("TLS", classes="card-title")
        labels = [tr("tui.tls.fingerprint"), tr("tui.tls.expires")]
        w = max(cell_width(x) for x in labels) + 2
        yield Static(f"{pad(labels[0], w)}{_short_fp(c.cert_fingerprint_sha256)}", classes="value")
        expiry = _cert_expiry(c.cert_path) or tr("tui.tls.unknown")
        yield Static(f"{pad(labels[1], w)}{expiry}", classes="value")
