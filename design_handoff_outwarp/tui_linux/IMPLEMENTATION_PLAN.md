# OutWarp · TUI Linux — Plan de implementación (Claude Code)

> **Para Claude Code.** Este documento describe paso a paso cómo añadir una **TUI Textual** a OutWarp para Linux, reusando el código que ya existe en el repo. La especificación visual de las 8 pantallas vive en `OutWarp TUI.html` (mockup HTML) y este plan traduce cada pantalla a clases Textual concretas con las rutas, símbolos y dependencias correctas.
>
> **Orden:** sigue las fases en orden. Detente al final de cada fase para que el humano la revise antes de continuar. **No** empieces la Fase 2 hasta que la Fase 1 esté mergeada.

---

## 0. Objetivo y alcance

### Goal
Sustituir la GUI React/pywebview en Linux por una **TUI Textual** persistente con dos comandos:

- `outwarp-cli tui` — cliente (dashboard del túnel en vivo, logs, import de `.owcfg`)
- `outwarp-server tui` — servidor (dashboard, lista de clientes, add/revoke, doctor)

### Out of scope
- macOS y Windows siguen usando la GUI pywebview existente — no tocar.
- No tocar el wizard `outwarp-server setup` (sigue siendo flujo curses-like con `rich`).
- No reescribir los comandos no interactivos (`connect`, `add-client`, …) — la TUI los **compone**, no los reemplaza.

### Restricciones
- Compatible con la mayoría de terminales Linux: GNOME Terminal, Konsole, xterm, Alacritty, kitty, foot, tmux, screen, SSH. Textual detecta capacidades en runtime.
- Glyphs **BMP únicamente** (sin emoji): caja (`─│┌┐└┘├┤`), bloques sparkline (`▁▂▃▄▅▆▇█`), formas (`●○◐`), flechas (`↑↓→←↵▸`).
- Tamaño mínimo: **80 × 24** (los splits colapsan a una columna). Óptimo: **100 × 30**.

### Referencias visuales
Mockup pixel-perfecto: `OutWarp TUI.html` en este mismo repo de diseño. Las pantallas a implementar son:

| # | Pantalla | Clase |
|---|---|---|
| 01 | Cliente · Empty state | `EmptyScreen` |
| 02 | Cliente · Connecting (fases en vivo) | `ConnectingScreen` |
| 03 | Cliente · Connected (split status / tail) ★ | `DashboardScreen` |
| 04 | Cliente · Logs fullscreen | `LogsScreen` |
| 05 | Servidor · Dashboard (3-up cards) ★ | `DashboardScreen` |
| 06 | Servidor · Clients (tabla con búsqueda) | `ClientsScreen` |
| 07 | Servidor · Add client (modal) | `AddClientModal` |
| 08 | Servidor · Doctor (con fixes inline) | `DoctorScreen` |

---

## 1. Convenciones globales

### Keybinds (lockstep cliente y server)
| Tecla | Acción |
|---|---|
| `q` | Quit |
| `?` | Help (modal) |
| `Esc` | Back / cancel |
| `↑↓` / `j k` | Move |
| `↵` | Activate |
| `/` | Search |
| `:` | Command palette |
| `Tab` | Swap focus entre paneles |

Verbos primarios (mnemotécnico = inicial del verbo):

| Tecla | Cliente | Servidor |
|---|---|---|
| `i` | **i**mport .owcfg | — |
| `k` | **k**ill (disconnect) | — |
| `r` | **r**econnect | **r**evoke |
| `a` | — | **a**dd client |
| `c` | — | **c**lients screen |
| `d` | — | **d**octor |
| `l` | **l**ogs | **l**ogs |
| `R` | — | **R**estart (mayúscula, peligroso) |
| `F` | — | apply **F**ix (en doctor) |

### Paleta (colores Textual TCSS)
Hereda de la marca OutWarp. Define como variables en `styles.tcss`:

```css
$brand: #2563ff;       /* warp blue — header, focus */
$ok: #2ee0b3;          /* signal cyan — online, pass */
$warn: #ff9b4a;        /* orange — idle, warn */
$bad: #ff5c7a;         /* red — offline, fail */
$dim: #6e747e;         /* secondary text */
$dim2: #4a4f57;        /* tertiary text */
$bright: #f4f5f7;      /* primary text */
$bg: #0a0c10;          /* background */
$bg-2: #11141a;        /* section bg */
```

---

## 2. Dependencias y packaging

### `client/pyproject.toml`
Añade un extra `tui`:

```toml
[project.optional-dependencies]
tui = [
    "textual>=0.85",
    "qrcode>=7.4",
    "rich>=13.0",            # textual ya lo trae, pero lo dejamos explícito
]
```

Y añade el subcomando:

```toml
[project.scripts]
outwarp-cli = "outwarp.cli:main"
# (no nuevo entry-point: la TUI se monta como `outwarp-cli tui`)
```

### `server/pyproject.toml`
Añade el mismo extra:

```toml
[project.optional-dependencies]
tui = [
    "textual>=0.85",
    "qrcode>=7.4",
]
```

> `rich` ya está en deps base del server.

### Instalación en el `install.sh` de Linux
Edita `installer/linux/install.sh` para que el venv del cliente y el del server instalen el extra `[tui]` cuando el OS sea Linux:

```sh
"$VENV_PYTHON" -m pip install --upgrade "outwarp-client[tui] @ ${CLIENT_WHEEL}"
"$VENV_PYTHON" -m pip install --upgrade "outwarp-server[tui] @ ${SERVER_WHEEL}"
```

---

## 3. Arquitectura del código nuevo

### Estructura de directorios

```
client/outwarp/
├── tui/                              # ←─ NUEVO
│   ├── __init__.py
│   ├── app.py                        # OutWarpClientTUI(App)
│   ├── styles.tcss                   # Textual CSS global
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── empty.py                  # EmptyScreen
│   │   ├── connecting.py             # ConnectingScreen
│   │   ├── dashboard.py              # DashboardScreen ★ home
│   │   ├── logs.py                   # LogsScreen
│   │   └── profile.py                # ProfileScreen (opcional, [p])
│   ├── modals/
│   │   ├── __init__.py
│   │   ├── import_owcfg.py           # ImportModal
│   │   └── help.py                   # HelpModal
│   └── widgets/
│       ├── __init__.py
│       ├── status_card.py            # Card "EXIT IP"
│       ├── traffic_card.py           # Card "TRAFFIC"
│       ├── tunnel_card.py            # Card "TUNNEL"
│       └── live_log.py               # RichLog con tail asyncio
├── tunnel_stats.py                   # ←─ NUEVO — bytes/s + latencia
└── ...

server/outwarp_server/
├── tui/                              # ←─ NUEVO
│   ├── __init__.py
│   ├── app.py                        # OutWarpServerTUI(App)
│   ├── styles.tcss
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── dashboard.py              # DashboardScreen ★ home
│   │   ├── clients.py                # ClientsScreen
│   │   ├── doctor.py                 # DoctorScreen
│   │   └── logs.py                   # LogsScreen (server-side)
│   ├── modals/
│   │   ├── __init__.py
│   │   ├── add_client.py             # AddClientModal
│   │   ├── revoke_client.py          # RevokeConfirmModal
│   │   ├── qr.py                     # QrModal (renderiza .owcfg como QR)
│   │   └── help.py
│   └── widgets/
│       ├── __init__.py
│       ├── services_card.py
│       ├── network_card.py
│       ├── tls_card.py
│       ├── clients_summary.py
│       └── traffic_chart.py
├── operations.py                     # ←─ NUEVO — add/revoke/restart compartido
├── traffic_history.py                # ←─ NUEVO — sqlite snapshots
└── ...
```

---

## 4. Fase 1 — Backend changes (sin TUI todavía)

> **No empieces la TUI hasta tener esto verde.** Es trabajo aislado, testeable, y reduce mucho el riesgo cuando la TUI lo consume.

### 1.1 Extraer `operations.py` en el server

**Por qué:** `_cmd_add_client`, `_cmd_revoke_client` y `_cmd_restart` en `server/outwarp_server/cli.py` mezclan lógica de negocio (generar keys, allocate IP, escribir config, hot-add a wireguard) con presentación (`rich.Console`). La TUI necesita la lógica sin la presentación.

**Crea** `server/outwarp_server/operations.py`:

```python
from __future__ import annotations
from dataclasses import dataclass
from pathlib import Path
from outwarp_server.config import ServerConfig, ClientEntry

@dataclass
class AddClientResult:
    client: ClientEntry
    owcfg_path: Path
    owcfg_sha256: str  # 7a:bf:…:09 (hex pairs, full)
    hot_added: bool    # True si wg syncconf funcionó
    wg_persist_warning: str | None  # mensaje si install_wg_config falló

def add_client(
    config: ServerConfig,
    name: str,
    *,
    output_dir: Path | None = None,  # default: Path.cwd()
) -> AddClientResult:
    """Idempotency: raises ValueError si el nombre ya existe."""
    ...

@dataclass
class RevokeResult:
    name: str
    hot_removed: bool
    wg_persist_warning: str | None

def revoke_client(config: ServerConfig, name: str) -> RevokeResult:
    """Raises KeyError si no existe."""
    ...

@dataclass
class RestartResult:
    wg_conf_written: bool
    wg_restarted: bool
    wstunnel_restarted: bool
    errors: list[str]

def restart_services(config: ServerConfig) -> RestartResult:
    ...
```

**Refactor:** `cli.py::_cmd_add_client/_cmd_revoke_client/_cmd_restart` pasan a ser wrappers que llaman a estas funciones puras y formatean el output con `rich`. **Mantén el output textual exactamente igual** — los tests de `tests/test_server_cli.py` no deben fallar.

### 1.2 Añadir checks Linux a `diagnostics.py`

**Por qué:** ahora mismo `diagnostics.py` solo tiene 4 checks `common` + 10 checks `win32`. La TUI del Doctor (pantalla 08) muestra 12 checks que requieren añadir los siguientes para Linux:

| Check key | Detalle |
|---|---|
| `linux_binaries` | `which wstunnel` + `wg --version` |
| `linux_kmod` | `modinfo wireguard` |
| `linux_systemd` | `systemctl is-active wstunnel.service` + `wg-quick@wg0.service` |
| `linux_listen_443` | `ss -tlnp 'sport = :443'` |
| `linux_listen_wg` | `ss -ulnp 'sport = :51820'` (verifica que escuche solo en 127.0.0.1) |
| `linux_ip_forward` | runtime: `sysctl net.ipv4.ip_forward` · persistente: `find /etc/sysctl.d -name "*outwarp*"` |
| `linux_nat_masquerade` | `iptables -t nat -S POSTROUTING` busca `-s 10.13.13.0/24 -j MASQUERADE` |
| `linux_fail2ban` | `which fail2ban-client` (Status.WARN si missing) |
| `linux_reverse_dns` | `socket.gethostbyaddr(public_ip)` y verifica que devuelva el endpoint |

Sigue el patrón de las `check_win_*`: función que recibe `ServerConfig`, devuelve `CheckResult` con `name`, `status`, `detail`, `remediation` y `remediation_command`. Registra en `gather_checks()` bajo la rama `if sys.platform.startswith("linux"):`.

### 1.3 Añadir `fix_kind` a `CheckResult`

**Por qué:** la pantalla 08 del Doctor tiene un keybind `F` que aplica el fix sin abrir un sub-shell. Solo para fixes seguros e idempotentes.

**Modifica** `server/outwarp_server/diagnostics.py`:

```python
from typing import Callable, Literal

@dataclass
class CheckResult:
    name: str
    status: Status
    detail: str = ""
    remediation: str | None = None
    remediation_command: str | None = None
    # ↓ NUEVOS
    fix_kind: Literal["auto", "interactive", "manual"] | None = None
    fix_callable: Callable[[ServerConfig], None] | None = None
    # "auto" → la TUI puede ejecutar fix_callable() tras confirmación
    # "interactive" → requiere shell (apt install, etc.) — muestra cmd y abre shell
    # "manual" → solo informativo, mostrar cmd para copy
    # None (default) → no hay fix
```

Marca como `fix_kind="auto"` con su `fix_callable`:
- `linux_ip_forward` → escribe `/etc/sysctl.d/99-outwarp.conf` y ejecuta `sysctl -p`
- `linux_nat_masquerade` → llama a `get_server_platform().install_wg_config(...)`
- `linux_systemd` (cuando algún service esté `inactive`) → `systemctl restart <svc>`

Los demás quedan como `interactive` (apt install) o `manual`.

### 1.4 Añadir `traffic_history.py` al server

**Por qué:** la sparkline de 24h y el "top talkers" del Dashboard (pantalla 05) requieren histórico. No existe en el repo.

**Crea** `server/outwarp_server/traffic_history.py`:

```python
"""Persiste snapshots de transfer rx/tx por peer cada 60 s en SQLite.

Schema:
  CREATE TABLE snapshot (
    ts INTEGER NOT NULL,           -- unix seconds
    public_key TEXT NOT NULL,
    rx_bytes INTEGER NOT NULL,
    tx_bytes INTEGER NOT NULL,
    PRIMARY KEY (ts, public_key)
  );
  CREATE INDEX idx_ts ON snapshot(ts);

DB path: $XDG_STATE_HOME/outwarp/traffic.sqlite (default ~/.local/state/outwarp/)
Retención: 7 días (DELETE WHERE ts < now - 7*86400 en cada write).
"""

from pathlib import Path

class TrafficHistory:
    def __init__(self, db_path: Path | None = None): ...
    def snapshot(self) -> None: ...               # lee get_live_peers() y guarda
    def hourly_buckets(self, hours: int = 24) -> list[tuple[int, int, int]]:
        """Devuelve [(hour_ts, sum_rx_delta, sum_tx_delta), ...] — usa LAG()."""
    def top_talkers(self, since_seconds: int = 3600, limit: int = 5) -> list[dict]:
        """Devuelve [{name, rx_delta, tx_delta}, ...]."""
```

**Integración:** en `server_manager.py::ServerManager.start()`, arranca un `threading.Timer` que llama a `TrafficHistory.snapshot()` cada 60 s. Para tests, expón `_tick()` para forzar un snapshot.

### 1.5 Añadir `tunnel_stats.py` al cliente

**Por qué:** el Dashboard del cliente (pantalla 03) muestra `down 8.4 MB/s` y `ping 42 ms` con sparkline — no existe el cálculo.

**Crea** `client/outwarp/tunnel_stats.py`:

```python
"""Sample WireGuard transfer counters and ICMP latency for the TUI."""

from dataclasses import dataclass

@dataclass
class TunnelStats:
    rx_bytes_total: int
    tx_bytes_total: int
    rx_rate_bps: float          # bytes/s desde el último sample
    tx_rate_bps: float
    last_handshake_age_s: int | None
    latency_ms: float | None    # ping a la IP del peer; None si no se puede

class StatsSampler:
    """Mantén una serie de hasta N samples y devuelve el último delta."""
    def __init__(self, iface: str, peer_endpoint_host: str, history: int = 60): ...
    def sample(self) -> TunnelStats: ...   # llámalo cada 1 s
    def history_rx_bps(self) -> list[float]: ...  # para Sparkline
    def history_ping_ms(self) -> list[float]: ...
```

**Implementación:**
- rx/tx: parse `wg show <iface> transfer` (peer_pubkey rx tx por línea). Necesita root o capability — usa el helper privilegiado existente (`outwarp-helper`).
- handshake age: `wg show <iface> latest-handshakes`.
- latency: `ping -c 1 -W 1 <peer_host>` con timeout corto. Si falla, devuelve `None` y el sparkline omite el punto.

### 1.6 Añadir `logs.tail_follow()` reusable

**Por qué:** el cliente CLI ya tiene tail-with-rotation en `_cmd_logs --follow`. La TUI necesita la misma lógica como async iterator.

**Modifica** `client/outwarp/logs.py` añadiendo:

```python
import asyncio
from collections.abc import AsyncIterator
from pathlib import Path

async def tail_follow(path: Path, *, poll_interval: float = 0.25) -> AsyncIterator[str]:
    """Yield lines as they're appended. Re-opens on inode change.
    Cancelar con asyncio.CancelledError limpia el handle."""
    ...
```

**Refactor:** `cli.py::_cmd_logs` con `--follow` pasa a usar esta función vía un `asyncio.run()` wrapper (o se queda con su implementación sync — no es bloqueante para esta fase).

### 1.7 Tests de Fase 1

Añade tests en:
- `server/tests/test_operations.py` — add/revoke/restart end-to-end con un config temp.
- `server/tests/test_diagnostics_linux.py` — mockea `subprocess.run` para cada nuevo check.
- `server/tests/test_traffic_history.py` — snapshot, hourly_buckets, top_talkers.
- `client/tests/test_tunnel_stats.py` — mockea `wg show` y verifica rates.
- `client/tests/test_logs_tail.py` — escribe a un tmpfile, verifica que el async iterator emite las líneas.

**Acceptance criteria Fase 1:**
- [ ] `cd server && pytest` pasa
- [ ] `cd client && pytest` pasa
- [ ] `outwarp-server doctor` ejecutado en Linux muestra los nuevos checks
- [ ] Los outputs textuales de `add-client`, `revoke-client`, `restart`, `list-clients` son **idénticos** a antes (no romper scripts del usuario)

---

## 5. Fase 2 — TUI cliente

### 2.1 Añadir subcomando `tui` a `client/outwarp/cli.py`

En `build_parser()`:

```python
sub.add_parser("tui", help="Launch the interactive TUI (Linux/headless)")
```

En `_COMMANDS`:

```python
"tui": _cmd_tui,
```

Implementación de `_cmd_tui`:

```python
def _cmd_tui(args: argparse.Namespace) -> int:
    try:
        from outwarp.tui.app import OutWarpClientTUI
    except ImportError:
        _err("TUI not installed. Reinstall with: pip install 'outwarp-client[tui]'")
        return 1
    return OutWarpClientTUI().run() or 0
```

### 2.2 `outwarp/tui/app.py`

```python
from textual.app import App
from outwarp.config import ClientConfig, ConfigError, default_config_path
from outwarp.logs import setup_logging
from outwarp.tunnel import TunnelManager

class OutWarpClientTUI(App):
    CSS_PATH = "styles.tcss"
    TITLE = "OutWarp · client"
    BINDINGS = [
        ("q", "quit", "Quit"),
        ("question_mark", "help", "Help"),
        ("colon", "command_palette", "Cmd"),
    ]
    SCREENS = {
        "empty": EmptyScreen,
        "connecting": ConnectingScreen,
        "dashboard": DashboardScreen,
        "logs": LogsScreen,
    }

    def on_mount(self) -> None:
        setup_logging()
        path = default_config_path()
        try:
            self.config = ClientConfig.load(path)
        except ConfigError:
            self.push_screen("empty")
            return
        self.manager = TunnelManager(self.config)
        self.manager.add_listener(self._on_state)
        self.push_screen("connecting")
        self.manager.start()

    def _on_state(self, state):
        # routing entre Connecting / Dashboard / FailedScreen según TunnelState
        ...

    def on_unmount(self) -> None:
        if hasattr(self, "manager"):
            self.manager.stop()
```

### 2.3 `screens/connecting.py`

Consume **`manager.phase`** (que ya existe — valores: `""`, `"resolve"`, `"tls"`, `"wg"`, `"ws"`, `"done"`):

```python
PHASE_LABELS = [
    ("resolve", "dns + tcp connect"),
    ("tls",     "tls handshake"),
    ("wg",      "wireguard interface up"),
    ("ws",      "wstunnel websocket upgrade"),
]
PHASE_ORDER = [k for k, _ in PHASE_LABELS]

class PhaseRow(Static):
    """One row in the stepper."""
    state = reactive("pending")  # "done" | "active" | "pending"
    ...

class ConnectingScreen(Screen):
    def on_mount(self):
        self.set_interval(0.25, self.refresh_phases)
    def refresh_phases(self):
        current = self.app.manager.phase
        idx = PHASE_ORDER.index(current) if current in PHASE_ORDER else len(PHASE_ORDER)
        for i, row in enumerate(self.phase_rows):
            row.state = "done" if i < idx else "active" if i == idx else "pending"
        # también muestra manager.attempt y manager.last_error
```

**Nota:** el mockup muestra 6 fases (DNS, TCP, TLS, WS, WG, EXIT IP). Los **valores reales** son 4 (`resolve, tls, wg, ws`). Implementa el real, no el mockup — y actualiza el screenshot del mockup cuando termines si quieres mantenerlo.

### 2.4 `screens/dashboard.py` ★ (pantalla principal)

Layout: dos columnas iguales, izquierda = StatusCol (3 cards), derecha = `RichLog` siguiendo el fichero de log.

```python
class DashboardScreen(Screen):
    BINDINGS = [
        ("k", "disconnect", "Disconnect"),
        ("r", "reconnect", "Reconnect"),
        ("L", "push_screen('logs')", "Logs fullscreen"),
        ("p", "push_screen('profile')", "Profile"),
        ("tab", "focus_next", "Swap focus"),
    ]
    def compose(self):
        yield Header()
        with Horizontal():
            with Vertical(classes="status-col"):
                yield StatusCard(self.app.config)       # widget custom
                yield TrafficCard(self.app.manager)     # consume StatsSampler
                yield TunnelCard(self.app.config)
            yield LiveLog(default_log_path())            # widget custom
        yield Footer()

    def on_mount(self):
        self.sampler = StatsSampler(
            iface=self.app.config.wireguard.tunnel_name,
            peer_endpoint_host=self.app.config.server.endpoint,
        )
        self.set_interval(1.0, self.refresh_stats)

    def refresh_stats(self):
        stats = self.sampler.sample()
        self.query_one(TrafficCard).update_stats(stats)
```

**Widgets a crear** (`widgets/`):

- `StatusCard` — muestra exit IP, ubicación (ipapi.co lookup cacheado), endpoint.
- `TrafficCard` — 4 filas: down / up / ping / handshake. Una `Sparkline` (Textual built-in) para `ping`.
- `TunnelCard` — iface, peer pubkey (truncado XaB…3kJ=), remote, MTU, DNS.
- `LiveLog` — extiende `RichLog`. En `on_mount`, lanza un task: `asyncio.create_task(self._follow())` que itera sobre `logs.tail_follow()` y hace `self.write(line)` por cada línea, coloreando INFO/WARN/ERROR.

### 2.5 `screens/logs.py`

```python
class LogsScreen(Screen):
    BINDINGS = [
        ("f", "toggle_filter", "Filter"),
        ("slash", "focus_search", "Search"),
        ("g", "scroll_home", "Top"),
        ("G", "scroll_end", "Bottom"),
        ("c", "copy_selection", "Copy"),
        ("F", "toggle_follow", "Follow"),
        ("escape", "pop_screen", "Back"),
    ]
    def compose(self):
        yield Header()
        yield Static("filter ▌ all info warn error    search _", id="filterbar")
        yield RichLog(id="log", highlight=True, markup=True, max_lines=10000)
        yield Footer()
```

### 2.6 `modals/import_owcfg.py`

```python
class ImportModal(ModalScreen[Path | None]):
    def compose(self):
        with Container(id="import-modal"):
            yield Input(placeholder="~/Downloads/your-name.owcfg", id="path")
            yield DirectoryTree(Path.home(), id="tree")
        # tree muestra solo .owcfg gracias a filter_paths()
```

Al confirmar: `outwarp.config.import_owcfg(path)` y `app.push_screen("dashboard")`.

### 2.7 `styles.tcss`

```css
Screen {
    background: $bg;
    color: $bright;
}
Header {
    background: $brand;
    color: white;
}
Footer {
    background: $bg-2;
}
.status-col {
    width: 50%;
    padding: 1 2;
}
.status-col > * {
    margin-bottom: 1;
    border: tall $dim2;
    padding: 1 2;
}
RichLog#log {
    background: $bg;
    scrollbar-color: $dim2 $bg-2;
}
TrafficCard .label {
    color: $dim;
}
TrafficCard .value {
    color: $bright;
    text-style: bold;
}
TrafficCard .spark {
    color: $ok;
}
PhaseRow.done .ico { color: $ok; }
PhaseRow.active .ico { color: $brand; }
PhaseRow.active { text-style: bold; }
PhaseRow.pending { color: $dim; }
```

### Acceptance criteria Fase 2
- [ ] `outwarp-cli tui` arranca sin error en GNOME Terminal, Konsole, Alacritty, kitty.
- [ ] Funciona dentro de tmux (`tmux new -s test 'outwarp-cli tui'`).
- [ ] Funciona vía SSH (`ssh user@host -t outwarp-cli tui`).
- [ ] Sin perfil → muestra EmptyScreen, `i` abre el modal de import.
- [ ] Con perfil → muestra ConnectingScreen mientras conecta, transiciona a DashboardScreen.
- [ ] DashboardScreen actualiza las stats cada 1 s sin parpadear.
- [ ] `k` desconecta, `r` reconecta, `L` abre logs fullscreen, `q` sale limpio.
- [ ] Resize a 80×24: split colapsa a una columna, todo sigue legible.

---

## 6. Fase 3 — TUI servidor

### 3.1 Subcomando `tui` en `server/outwarp_server/cli.py`

```python
sub.add_parser("tui", help="Launch the interactive admin TUI")

_COMMANDS["tui"] = _cmd_tui

def _cmd_tui(args):
    _require_root("tui")
    try:
        from outwarp_server.tui.app import OutWarpServerTUI
    except ImportError:
        console.print("[red]TUI not installed.[/red] Reinstall with: pip install 'outwarp-server[tui]'")
        return 1
    return OutWarpServerTUI(args.config_dir).run() or 0
```

Añade `"tui"` a `_PRIVILEGED_COMMANDS`.

### 3.2 `tui/app.py`

```python
class OutWarpServerTUI(App):
    CSS_PATH = "styles.tcss"
    TITLE = "OutWarp · server"
    BINDINGS = [("q", "quit", "Quit"), ("question_mark", "help", "Help")]
    SCREENS = {
        "dashboard": DashboardScreen,
        "clients": ClientsScreen,
        "doctor": DoctorScreen,
        "logs": LogsScreen,
    }
    def on_mount(self):
        self.config_path = _resolve_config_path(...)
        self.config = ServerConfig.load(self.config_path)
        self.history = TrafficHistory()
        self.push_screen("dashboard")
```

### 3.3 `screens/dashboard.py` ★

Layout: dos columnas iguales. Izquierda = ServicesCard + NetworkCard + TlsCard. Derecha = ClientsSummary + TrafficChart + TopTalkers.

```python
class DashboardScreen(Screen):
    BINDINGS = [
        ("c", "push_screen('clients')", "Clients"),
        ("a", "add", "Add"),
        ("d", "push_screen('doctor')", "Doctor"),
        ("l", "push_screen('logs')", "Logs"),
        ("R", "restart", "Restart"),
        ("s", "settings", "Settings"),
    ]
    def on_mount(self):
        self.set_interval(2.0, self.refresh)
    def refresh(self):
        # services: platform.is_wstunnel_running() + is_wg_active()
        # network: ServerConfig + cryptography.x509 para fingerprint/expiry
        # clients: get_live_peers() + count online/idle/offline
        # traffic: history.hourly_buckets(24)
        # top: history.top_talkers(3600)
        ...
    def action_add(self):
        self.app.push_screen(AddClientModal(self.app.config),
                             self._on_add_result)
    def action_restart(self):
        # confirm con ModalScreen → operations.restart_services(...)
        ...
```

### 3.4 `screens/clients.py`

```python
class ClientsScreen(Screen):
    BINDINGS = [
        ("a", "add", "Add"),
        ("r", "revoke", "Revoke"),
        ("enter", "details", "Details"),
        ("slash", "focus_search", "Search"),
        ("e", "export_owcfg", "Export"),
        ("escape", "pop_screen", "Back"),
    ]
    def compose(self):
        yield Header()
        yield Input(placeholder="search…", id="search")
        yield DataTable(id="table", cursor_type="row")
        yield Footer()
    def on_mount(self):
        t = self.query_one(DataTable)
        t.add_columns("●", "name", "address", "status", "last hs", "rx", "tx", "endpoint")
        self.set_interval(2.0, self.refresh)
```

### 3.5 `modals/add_client.py`

```python
class AddClientModal(ModalScreen[AddClientResult | None]):
    BINDINGS = [("escape", "cancel", "Cancel"), ("enter", "submit", "Create")]
    def compose(self):
        with Container(id="add-modal"):
            yield Label("add client")
            yield Input(placeholder="client name (e.g. felix-laptop)", id="name")
            yield Static("", id="preview")
            yield Static("", id="result")
            yield Static("⚠  envía el .owcfg de forma segura…", classes="warn")
    def on_input_changed(self, ev):
        # actualiza preview con la próxima IP disponible
        ip = next_available_ip(self.config.subnet, self.config.server_address,
                               [c.address for c in self.config.clients])
        self.query_one("#preview").update(f"address  {ip}  auto-assigned")
    async def action_submit(self):
        try:
            result = add_client(self.config, self.query_one("#name").value.strip())
        except ValueError as e:
            self.query_one("#result").update(f"[red]{e}[/red]")
            return
        self.query_one("#result").update(
            f"[green]✓[/green]  {result.owcfg_path.name}  "
            f"sha256 {result.owcfg_sha256[:5]}…\n"
            f"  written to {result.owcfg_path}\n"
            f"[green]✓[/green]  hot-added to wireguard"
        )
```

### 3.6 `modals/revoke_client.py`

Modal de confirmación: "Revoke felix-laptop? This client will lose access immediately. [y/N]". Si `y`: `operations.revoke_client(config, name)`.

### 3.7 `modals/qr.py`

Para el keybind `Q` en AddClientModal: lee el `.owcfg`, lo renderiza como QR ASCII y lo muestra en un `RichLog`. Usa la lib `qrcode`:

```python
import qrcode
qr = qrcode.QRCode(border=1)
qr.add_data(owcfg_bytes)
qr.make()
# render como ASCII con ▀ y ▄ (half-blocks) — cabe en 80 cols si el contenido < 2 KB
```

### 3.8 `screens/doctor.py`

```python
class DoctorScreen(Screen):
    BINDINGS = [
        ("r", "rerun", "Re-run"),
        ("enter", "expand", "Expand"),
        ("F", "apply_fix", "Apply fix"),
        ("c", "copy_report", "Copy"),
        ("escape", "pop_screen", "Back"),
    ]
    def on_mount(self):
        self.rerun()
    def rerun(self):
        self.results = run_all(self.app.config)
        self._render()
    def action_apply_fix(self):
        idx = self.cursor_row
        r = self.results[idx]
        if r.fix_kind != "auto":
            self.notify(f"Fix is {r.fix_kind} — open a shell and run:\n{r.remediation_command}",
                        severity="warning")
            return
        # confirm modal → r.fix_callable(self.app.config) → self.rerun()
```

### Acceptance criteria Fase 3
- [ ] `sudo outwarp-server tui` arranca.
- [ ] Dashboard muestra services activos en verde, traffic 24h con sparkline (puede estar vacío si no hay datos aún — mostrar `no data yet`).
- [ ] `a` abre AddClientModal, escribir un nombre y `↵` genera el `.owcfg`, muestra el resultado, cierra el modal y el nuevo cliente aparece en el dashboard a los 2 s.
- [ ] `Q` en AddClientModal abre QrModal con un QR escaneable.
- [ ] `c` desde el dashboard navega a ClientsScreen con DataTable.
- [ ] `r` en una fila pide confirmación y revoca al peer.
- [ ] `d` abre DoctorScreen, todos los checks se muestran, `F` sobre `ip_forwarding` warn lo arregla y al re-correr aparece como pass.

---

## 7. Fase 4 — Eliminar GUI Linux

> Solo cuando las fases 2 y 3 estén verdes y validadas en uso real durante al menos 1 semana.

### 4.1 Hacer pywebview opcional

En `client/pyproject.toml`:

```toml
dependencies = [
    "pystray>=0.19",
    "Pillow>=10.0",
    "platformdirs>=4.0",
    "pywebview>=5.0 ; sys_platform != 'linux'",  # ← marker
]
```

En `server/pyproject.toml` (el extra `gui`):

```toml
[project.optional-dependencies]
gui = [
    "pillow>=10.0",
    "pystray>=0.19",
    "pywebview>=5.0 ; sys_platform != 'linux'",
]
```

### 4.2 Hacer que `outwarp` (GUI script) caiga a la TUI en Linux

`client/outwarp/app.py::main()`:

```python
def main() -> int:
    if sys.platform.startswith("linux"):
        from outwarp.cli import main as cli_main
        return cli_main(["tui"])
    # ... resto del código GUI actual ...
```

Mismo patrón para `server/outwarp_server/server_app.py::main()`.

### 4.3 Actualizar `installer/linux/install.sh`
- Elimina los `apt install` de deps GTK / Qt (webkit2gtk-4.1, etc.) que solo usaba pywebview.
- Mantén instalación de wstunnel, wireguard-tools, sudoers, helper.
- Ajusta el atajo `.desktop`:
  - Cliente: `Exec=x-terminal-emulator -e outwarp-cli tui`
  - Server: no se necesita atajo (es admin tool).

### 4.4 Borrar archivos no usados en Linux
Después de validar, marca para borrado **en una commit aparte** (no en la misma que añade la TUI):
- `client/outwarp/ui/` y `server/outwarp_server/ui/` (la React UI) — pero **solo** quitarlas de los wheels Linux vía `[tool.hatch.build.targets.wheel.exclude]`. macOS / Windows las siguen necesitando.

---

## 8. Fase 5 — Tests y CI

### Tests TUI
Textual incluye un `Pilot` para tests:

```python
# client/tests/test_tui_dashboard.py
import pytest
from outwarp.tui.app import OutWarpClientTUI

@pytest.mark.asyncio
async def test_empty_state_shows_when_no_profile(tmp_path, monkeypatch):
    monkeypatch.setenv("XDG_CONFIG_HOME", str(tmp_path))
    app = OutWarpClientTUI()
    async with app.run_test() as pilot:
        await pilot.pause()
        assert app.screen.id == "empty"
        await pilot.press("i")
        await pilot.pause()
        assert isinstance(app.screen, ImportModal)
```

Cubre:
- Routing entre screens según `TunnelState`.
- Keybinds en cada screen.
- AddClientModal genera el `.owcfg` cuando se confirma.
- DoctorScreen ejecuta `fix_callable` cuando se pulsa `F` en un check `auto`.

### GitHub Actions
Añade en `.github/workflows/ci.yml`:

```yaml
- name: TUI tests
  run: |
    cd client && pip install '.[tui,dev]' && pytest
    cd ../server && pip install '.[tui,dev]' && pytest
```

---

## 9. Fase 6 — Documentación

### `README.md`
Añade sección "Linux TUI" con screenshot animado (asciinema cast) y los comandos:

```
outwarp-cli tui          # cliente
sudo outwarp-server tui  # servidor
```

### `CLAUDE.md`
Añade un párrafo a la sección "Layout del proyecto" describiendo `client/outwarp/tui/` y `server/outwarp_server/tui/`.

### `installer/linux/install.sh`
Mensaje final: "Run `outwarp-cli tui` to get started" en vez del actual.

---

## 10. Checklist final

Antes de mergear el PR final:

- [ ] Fases 1, 2, 3 completas con sus acceptance criteria verdes.
- [ ] Tests pasan en CI.
- [ ] Validación manual en GNOME Terminal, Konsole, Alacritty, kitty.
- [ ] Validación en tmux y vía SSH.
- [ ] Validación con `TERM=xterm-256color` (terminal antigua).
- [ ] Sin emoji en el código (grep en `tui/` para confirmar).
- [ ] Sin regresiones en `outwarp-cli connect` / `outwarp-server add-client` (outputs idénticos).
- [ ] `outwarp-cli --version` y `outwarp-server --version` no cambian.
- [ ] README actualizado.

---

## 11. Preguntas abiertas para humano antes de empezar

1. **Histórico de tráfico**: ¿quieres que el snapshot del server lo arranque `ServerManager.start()` automáticamente, o como servicio systemd separado (`outwarp-traffic-history.service`)? Recomendación: dentro de `ServerManager` para no añadir otro servicio que mantener.

2. **Ubicación del .sqlite del histórico**: ¿`/var/lib/outwarp/traffic.sqlite` (FHS-correcto, requiere root al crear) o `~/.local/state/outwarp/traffic.sqlite` (per-user)? Recomendación: `/var/lib/outwarp/` ya que el server corre como root.

3. **Geolocalización**: para que el dashboard del cliente muestre "Frankfurt, DE" hace falta llamar a un servicio externo (ipapi.co, ip-api.com). ¿OK con esto, o omitir y mostrar solo la IP?

4. **TUI server: lanzar desde la GUI**: en Linux la GUI cae a la TUI. ¿En macOS/Windows quieres añadir un botón "Open TUI" para que el admin pueda abrirla también? Probablemente no — son OS donde hay GUI nativa decente.

Cuando respondas estas, Claude Code puede empezar por la Fase 1.
