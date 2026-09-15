# OutWarp

Herramienta multiplataforma (cliente + servidor) para levantar un túnel **WireGuard sobre WebSocket** usando [wstunnel](https://github.com/erebe/wstunnel) como transporte. Pensada para entornos donde UDP está bloqueado pero HTTPS/WebSocket pasa (redes corporativas, Wi-Fi cautivos, móvil tras CGNAT, etc.).

## Origen del proyecto

Nace como reescritura de un script PowerShell portable (`C:\Users\ferra\Documents\wstunnel_10.5.2_windows_amd64.tar\script portable\`) que funcionaba solo en Windows y estaba atado al servidor personal del autor. Los problemas del script original que OutWarp resuelve:

- **Valores hardcodeados en el código** (URL del servidor `vpn.fcrespo.tech`, IP interna `10.43.9.43`, secreto `ClaveSegura123`, IPs de Cloudflare, nombre del túnel WireGuard del autor).
- **Solo Windows**, PowerShell + WinForms. Frágil y difícil de mantener.
- **Sin wizard de configuración**: el usuario editaba el código.
- **Sin componente de servidor**: había que montar wstunnel a mano en el VPS.

El script original se mantiene intacto como referencia. **No lo modifiques** — es la versión que usa actualmente el autor en producción.

## Alcance

OutWarp es una herramienta **genérica**: cualquier persona con un servidor propio debe poder usarla. No está atada a ninguna infraestructura concreta.

- **Cliente**: app de bandeja del sistema (tray) que lanza wstunnel y gestiona el túnel WireGuard asociado.
- **Servidor**: wizard (CLI o GUI) que instala y configura wstunnel como servicio en Windows o Linux.
- **Cliente y servidor pueden estar en OS distintos** (ej. servidor Linux + cliente Windows).

### Plataformas soportadas (cliente y servidor)

- Windows 10/11
- Linux (distros con systemd). Desde 2026-09-14, **Omarchy** (Arch + Hyprland/Wayland) es distro de referencia junto a Ubuntu/Mint: todo cambio en el cliente Linux (instalador, tray, GUI, notificaciones, servicio) tiene que funcionar ahí también. Ver "Criterio de 1.0.0".

> **macOS queda fuera de alcance.** No se publicará ninguna versión para macOS. El dispatch por `sys.platform` solo contempla Windows y Linux; un arranque en Darwin lanza `PlatformError("Unsupported platform")`.

## Stack técnico

**Lenguaje**: Python 3.11+

Se valoró C# + WinForms (descartado: no cross-platform sin reescribir UI entera) y Electron (descartado: instaladores de 150+ MB). Python ofrece el mejor equilibrio entre portabilidad, velocidad de desarrollo y tamaño del binario final.

### Cliente

| Rol | Librería |
|---|---|
| Tray icon | `pystray` |
| UI (ventana principal + wizard) | HTML/CSS/React 18 + `pywebview` (bridge `window.pywebview.api`) |
| Packaging | `PyInstaller` (one-folder) |
| Installer Windows | PyInstaller + Inno Setup → `.exe` wizard |
| Installer Linux | `install.sh` (bootstrap + venv + `pip install`) |

El HTML se sirve **desde el filesystem** (`file://…/ui/index.html`) directamente a la ventana pywebview, no por HTTP. La clase `Api` (`outwarp/api.py`) se expone con `js_api=api` al crear la ventana; el JS la invoca como `window.pywebview.api.<método>` y recibe eventos vía `window.addEventListener('outwarp:<name>', …)` (Python emite con `window.evaluate_js`). Sin FastAPI ni uvicorn — el JS bridge directo es el modelo definitivo.

**TUI Textual** (ya implementada): cliente y servidor exponen además `outwarp tui` / `outwarp-server tui`, una interfaz en terminal basada en [`textual`](https://textual.textualize.io/). Comparte el mismo `TunnelManager` / `ServerManager` que la GUI y el CLI headless, así que las tres rutas se cruzan sin duplicar lógica. La paleta TCSS replica los design tokens de `styles.css`; los glyphs son BMP-only (caja, bloques sparkline, formas, flechas) para correr en cualquier terminal — incluidos tmux, screen y SSH. La especificación visual vive en `design_handoff_outwarp/tui_linux/` (mockup HTML + `IMPLEMENTATION_PLAN.md`).

### Servidor

- Wizard CLI interactivo (`rich` + `prompt_toolkit`) — sigue siendo el flujo recomendado en VPS headless (`sudo outwarp-server setup`).
- Wizard GUI con la misma estética que el cliente (pywebview + HTML) accesible como subcomando `outwarp-server gui` (era un binario aparte `outwarp-server-gui` hasta 0.4.x) para administradores con escritorio.
- Instalación como servicio nativo: **systemd** (Linux) y **Windows Service Manager** (Windows). También despliegue **Docker/Kubernetes** vía manifests.
- Genera un `.owcfg` por cliente, listo para importar.

## Arquitectura

```
OutWarp/
├── client/
│   ├── outwarp/
│   │   ├── app.py            # Entry point: crea Api, abre pywebview, arranca tray
│   │   ├── api.py            # Clase Api expuesta como window.pywebview.api
│   │   ├── cli.py            # outwarp (única binary del cliente: subcomandos import/connect/status/profile/logs/forget-profile/uninstall/tui/gui/update)
│   │   ├── tray.py           # pystray + menú contextual
│   │   ├── tunnel.py         # Gestión del proceso wstunnel + watchdog + reconexión
│   │   ├── wireguard.py      # Fachada WireGuard (delega en platforms/)
│   │   ├── network.py        # TCP probe + TLS fingerprint pinning
│   │   ├── config.py         # Schema + I/O del .owcfg / config.json
│   │   ├── logs.py           # Logger + rotación + MemoryLogHandler
│   │   ├── uninstall.py      # Lógica del subcomando `outwarp uninstall` (purga venv pipx + helper + sudoers + autostart)
│   │   ├── ui/               # HTML/JS de la UI (Claude Design — pywebview)
│   │   │   ├── index.html    # Carga react + scripts (bundle JSX pre-compilado)
│   │   │   ├── app.jsx       # Shell interactivo cableado al Api
│   │   │   ├── var-a.jsx     # Variante "consumer" del diseño (referencia)
│   │   │   ├── var-b.jsx     # Variante "developer/instrument" (referencia)
│   │   │   ├── shared.jsx    # i18n (STR) + atoms (Btn/Pill/StatusDot/Toggle)
│   │   │   ├── brand.jsx     # Logo + wordmark "OutWarp"
│   │   │   └── styles.css    # Design tokens (light/dark)
│   │   ├── tui/              # Textual TUI (Linux, terminal-only — sin GTK/WebKit)
│   │   │   ├── app.py        # OutWarpClientTUI(App) — entry point de `outwarp tui`
│   │   │   ├── styles.tcss   # TCSS (paleta mirror de styles.css, glyphs BMP-only)
│   │   │   ├── screens/      # empty / connecting / dashboard / logs / failed / profile
│   │   │   ├── modals/       # import_owcfg / settings / help
│   │   │   └── widgets/      # status_card / traffic_card / tunnel_card / live_log
│   │   ├── tunnel_stats.py   # StatsSampler — rx/tx rate + ping para el dashboard TUI
│   │   ├── resources/        # app_icon.{ico,png}
│   │   └── platforms/
│   │       ├── base.py       # Interfaz abstracta
│   │       ├── windows.py
│   │       └── linux.py
│   ├── requirements.txt
│   └── pyproject.toml
│
├── server/
│   ├── outwarp_server/
│   │   ├── cli.py            # outwarp-server (única binary del servidor: setup/init/serve/add-client/list-clients/revoke-client/rotate-client/prune-expired/status/restart/doctor/uninstall/tui/gui/update)
│   │   ├── server_app.py     # Lógica del subcomando `outwarp-server gui` (pywebview)
│   │   ├── api.py            # Clase Api del lado servidor
│   │   ├── server_manager.py # ServerManager (start/stop/add-client/revoke)
│   │   ├── server_tray.py    # Tray del modo GUI
│   │   ├── setup_wizard.py   # Wizard rich del CLI
│   │   ├── operations.py     # add/revoke/restart "puros" (sin rich) que reusa el TUI
│   │   ├── traffic_history.py# SQLite snapshots de transfer rx/tx (60s, retención 7 días)
│   │   ├── diagnostics.py    # Doctor checks (common + win32 + linux) + fix_kind + fix_callable
│   │   ├── crypto.py         # TLS cert self-signed + fingerprint + WG keypairs
│   │   ├── ip_pool.py        # Asignación de IPs del pool de clientes
│   │   ├── wireguard.py      # build_server_wg_conf + add/remove peer (hot-reload)
│   │   ├── owcfg.py          # build_owcfg / write_owcfg
│   │   ├── ui/               # HTML/JS del servidor (Claude Design — pywebview)
│   │   ├── tui/              # Textual TUI (Linux): dashboard, clients, doctor, logs + modals
│   │   └── platforms/        # systemd (linux) / SCM (windows) / k8s manifests (kubernetes)
│   └── pyproject.toml
│
├── installer/
│   ├── windows/             # outwarp.iss (Inno Setup) + build/ (PyInstaller specs) + bundle/
│   └── linux/install.sh
│
├── config.example.owcfg
├── README.md
└── CLAUDE.md                 # (este archivo)
```

### Abstracción por plataforma

El patrón: `platforms/base.py` define la interfaz; cada OS tiene su implementación. `wireguard.py` y `network.py` no contienen lógica específica de OS, solo importan el módulo correcto según `sys.platform`.

| Operación | Windows | Linux |
|---|---|---|
| Levantar tunnel WG | `wireguard.exe /installtunnelservice` | `wg-quick up` + systemd |
| Rutas estáticas | `route add X MASK Y Z` | `ip route add X via Y` |
| Config WG | `.conf.dpapi` (DPAPI) | `.conf` plano (`/etc/wireguard/`) |
| Servicio del servidor | SCM (pywin32) | systemd unit |

## Distribución e instalación

- **Windows (cliente o servidor)**: instalador `.exe` (PyInstaller one-folder + Inno Setup) desde GitHub Releases. El wizard pregunta si instala cliente, servidor o ambos. WireGuard for Windows y `wstunnel.exe` van bundleados — el usuario no necesita Python.
- **Linux (cliente o servidor)**: `curl -fsSL <url>/install.sh | sudo bash`. El script pregunta cliente o servidor, instala Python 3.11+ si falta, crea un venv, instala las deps y lanza el wizard correspondiente.

**Modelo de empaquetado**: en Windows, cliente y servidor se distribuyen como un único instalador `.exe`; el usuario no necesita Python. En Linux, instalación desde fuente vía `install.sh` (crea venv + `pip install`, non-editable).

**Registro como servicio**: el instalador registra automáticamente el binario como servicio del SO al final del wizard (Windows Service / systemd unit). El usuario no tiene que hacer nada extra para que arranque al iniciar sesión.

Hosting del script: pendiente de decidir entre dominio propio y `raw.githubusercontent.com`. No bloquea el desarrollo (el `install.sh` ya apunta a `raw.githubusercontent.com`).

## TLS y endpoint del servidor

El servidor está pensado para correr **sin dominio**. Implicaciones:

- El wizard del servidor **detecta la IP pública** (consultando un servicio tipo `api.ipify.org`), la propone como endpoint y permite override por si el usuario sí tiene dominio.
- El servidor **genera un certificado TLS auto-firmado** durante la instalación. wstunnel sigue usando WSS (necesario para atravesar firewalls corporativos).
- El cliente **no valida contra una CA**: hace **pinning del fingerprint SHA256** del cert, embebido en el `.owcfg`. Cero dependencia de Let's Encrypt / DuckDNS / dominios.
- Ramas Let's Encrypt + dynamic DNS pueden añadirse más adelante como opción del wizard, pero no son la vía por defecto.

## Bypass routing (¿necesario siempre?)

Sí. Cuando WireGuard captura todo el tráfico (`AllowedIPs = 0.0.0.0/0`), el propio tráfico de wstunnel también caería dentro del túnel → loop. La excepción de routing hacia las IPs del endpoint es **obligatoria en cualquier setup**, no algo específico de Cloudflare.

- Si el servidor está detrás de Cloudflare/CDN, son las IPs del proxy (varias).
- Si el servidor es directo, es **una sola IP** (la pública del servidor).
- El servidor calcula sus propias IPs de bypass durante la instalación y las **embebe en el `.owcfg`** — el cliente las aplica tal cual, sin pedirlas al usuario. Si el endpoint es un hostname, el cliente lo resuelve a IPs antes de añadir las rutas de bypass.

## Apertura de puertos

Sí, el servidor necesita un puerto público abierto (default **443** para mimetizarse con HTTPS). El wizard del servidor:

1. Pregunta qué puerto usar.
2. Tras instalar, ejecuta un **probe de conectividad desde fuera** (servicio externo) y avisa si no llega.
3. Imprime instrucciones específicas según el caso (router doméstico con port-forward vs. firewall de VPS).

Para usuarios sin homelab: necesitan VPS (Oracle Free Tier, Hetzner, etc.). No hay forma de evitarlo manteniendo el modelo self-hosted.

## Configuración

El servidor genera **un fichero `.owcfg` por cliente** (formato JSON). Cada `.owcfg` contiene todo lo necesario para conectarse — el cliente solo importa el fichero y arranca, sin más preguntas.

```json
{
  "server": {
    "endpoint": "203.0.113.42",
    "port": 443,
    "http_upgrade_path_prefix": "<secreto-aleatorio>"
  },
  "tls": {
    "cert_fingerprint_sha256": "AB:CD:EF:..."
  },
  "tunnel": {
    "local_port": 51820,
    "remote_host": "10.0.0.1",
    "remote_port": 51820
  },
  "wireguard": {
    "tunnel_name": "OutWarp",
    "client_address": "10.0.0.42/32",
    "client_private_key": "<base64>",
    "server_public_key": "<base64>",
    "dns": ["1.1.1.1"]
  },
  "routing": {
    "bypass_ips": ["203.0.113.42"]
  },
  "reconnect": {
    "max_attempts": 5,
    "delays_seconds": [5, 10, 20, 30, 60]
  }
}
```

**El `.owcfg` es sensible**: contiene la clave privada WireGuard del cliente. Quien tenga el fichero ES ese cliente. Tratarlo como una credencial.

El cliente, al importar el `.owcfg`, lo guarda como `config.json` en la ruta de configuración del usuario (`%APPDATA%\OutWarp\` en Windows, `~/.config/outwarp/` en Linux).

### Comandos del servidor

Tras la instalación, el ejecutable del servidor expone subcomandos:

- `outwarp-server add-client <nombre>` — genera nuevo par de claves WG, asigna IP del pool, escribe `<nombre>.owcfg` en el directorio actual.
- `outwarp-server list-clients` — lista clientes registrados.
- `outwarp-server revoke-client <nombre>` — elimina cliente del peer-list de WireGuard.
- `outwarp-server rotate-client <nombre>` — genera nuevo keypair WG + PSK para un cliente existente; preserva su IP y expiración. Escribe un nuevo `<nombre>.owcfg` que hay que redistribuir al cliente.
- `outwarp-server status` — estado del servicio wstunnel y de WireGuard.

## Funcionalidades heredadas del script original (a mantener)

- Mutex para evitar doble instancia.
- Watchdog que reinicia wstunnel si cae (backoff exponencial: 5s→10s→20s→30s→60s, max 5 intentos).
- Timer de estabilidad: si la conexión aguanta 30s, el contador se resetea.
- Rotación de log (limite 512 KB).
- Menú de bandeja: Ver logs, Reconectar, Acceso directo, Desconectar.
- Ventana de logs en vivo (tail -f style).
- Notificaciones al conectar / reconectar / fallar.
- Limpieza de rutas estáticas al desconectar.
- Desinstalación del servicio WireGuard al salir.

## Licencia

**OutWarp** se distribuye bajo **[PolyForm Noncommercial 1.0.0](https://polyformproject.org/licenses/noncommercial/1.0.0)**
(`LICENSE`, raíz) — uso libre para fines no comerciales; uso comercial requiere
acuerdo aparte con el autor. Decisión explícita del autor (no MIT/Apache-2.0,
que sí permiten uso comercial): quería prohibirlo. `THIRD_PARTY_LICENSES`
(raíz) recoge las licencias de todo lo que se bundlea o de lo que depende
(tabla abajo) — esas licencias de terceros no cambian por el cambio de
licencia de OutWarp.

### Dependencias y sus licencias

| Componente | Licencia | Notas |
|---|---|---|
| wstunnel | BSD-3-Clause | Bundleable con atribución. No usar el nombre "wstunnel" para promover OutWarp. |
| WireGuard (kernel/tools/Windows) | GPL-2.0 | Invocado vía subprocess, no linked → no contamina. Instalado por el OS package manager, no bundleado. Sin obligaciones GPL mientras no se incluya el binario en el instalador. |
| Protocolo WireGuard | Sin patente | Libre. |
| pystray | LGPL-3.0 | ⚠️ En binarios PyInstaller usar modo **one-folder** (no one-file) para que el usuario pueda reemplazar la lib. Incluir texto LGPL en `THIRD_PARTY_LICENSES`. |
| pywebview | BSD-3-Clause | UI host. Sin restricciones relevantes. |
| Pillow | MIT-CMU (HPND) | Sin restricciones. |
| platformdirs | MIT | Sin restricciones. |
| Python (CPython) | PSF (BSD-style) | Sin restricciones. |
| Geist / Geist Mono (fuente UI) | SIL OFL-1.1 | Bundleada como woff2 variable en `*/ui/fonts/`. Texto de licencia en `fonts/OFL.txt` junto a los ficheros. |

### Marcas registradas

- **"WireGuard"** es trademark de Jason Donenfeld. No usar en el nombre del proyecto ni para implicar endorsement.
- **"wstunnel"** — misma restricción (BSD-3-Clause cláusula 3). Por eso el proyecto se llama OutWarp.

### Criterio de 1.0.0 — qué tiene que estar hecho antes de publicarla

**Decidido por el autor el 2026-09-14. Fuente de verdad: esta sección. `ROADMAP.md` → "Before 1.0" la replica en inglés. 1.0.0 NO sale sin todo lo de "Bloqueante" en verde; ningún agente la publica ni la propone sin comprobarlo.**

Qué significa 1.0 aquí: no "perfecto", sino *"a partir de aquí, romper esto es cambio mayor"*. Queda congelado (cambiarlo = `feat!:` → 2.0, o migración y se queda en 1.x): el formato `.owcfg` v3, el protocolo de enrolamiento (`POST /enroll`, token de un solo uso), los subcomandos y flags documentados de `outwarp` (cliente, ver renombrado más abajo) / `outwarp-server`, el canal de actualización (`SHA256SUMS.txt` + `.minisig`, clave `3E1FCD8BF652EC28`) y la forma de `config.json` / config del servidor. NO queda congelado: UI, TUI, escalera de fallback, mensajes, internos.

Legado (hecho):
- [x] Licencia PolyForm Noncommercial 1.0.0 confirmada; `LICENSE` y `THIRD_PARTY_LICENSES` en la raíz.
- [x] Sin referencias del autor (`vpn.fcrespo.tech`, `ClaveSegura123`, `10.43.9.43`, `PortatilDesbloqueado`, IPs) en el código.

**Bloqueante** (cada punto = una rama y un PR; orden recomendado):

- [ ] **Prueba end-to-end en CI, bloqueante.** Cuarto job en `ci.yml` (solo Linux): dos contenedores Docker — `server` = la imagen real de `server/Dockerfile`, `client` = `python-slim` + `wireguard-tools` + wstunnel pinneado + wheel del cliente, como root (`platforms/linux.py` omite `sudo` con euid 0; helper vía `OUTWARP_HELPER`), ambos con `NET_ADMIN` + `/dev/net/tun`. Flujo: `add-client` → `import` (enrola por 443) → `connect` → handshake → `curl` a un HTTP que solo escucha en la IP de túnel del servidor + contadores de `wg show` suben → `ip route get 1.1.1.1` sale por `wg0` → token reutilizado rechazado → `disconnect` deja rutas e interfaz limpias. Cubre lo que se coló con CI en verde: B-017, B-018, B-019 y el drift de versión de wstunnel. No cubre Windows, systemd, k8s ni GUI (y se dice así en la doc). **Antes: spike de 1 h** para confirmar `wg-quick up` en Docker dentro de un runner de GitHub; si no funciona, plan B = network namespaces en el runner. Ficheros previstos: `e2e/compose.yml`, `e2e/client.Dockerfile`, `e2e/run.sh`.
- [ ] **Kill switch + endpoint por hostname.** Con el kill switch enganchado, la reconexión resuelve el hostname por el DNS de la LAN, que está bloqueado → `FAILED` y el usuario sin red. Hay que decidir e implementar cómo se permite la resolución (UDP/53 a los resolvers mientras está enganchado, o resolver y cachear la IP antes de enganchar). Es un fallo en una feature de seguridad; no se firma "estable" con esto abierto.
- [x] **Renombrar el comando del cliente: `outwarp-cli` → `outwarp`.** *(Hecho 2026-09-15: `outwarp` es la entrada principal, `outwarp-cli` queda como alias deprecado hasta 1.0.0; `install.sh` migra unit/completions y `doctor` avisa de restos.)* Decisión del autor (2026-09-14): el cliente es lo que usa la mayoría y tiene que ser lo más fácil; el servidor ya lleva su sufijo (`outwarp-server`), así que el cliente no necesita ninguno. En Windows el ejecutable **ya** es `outwarp.exe` (`installer/windows/outwarp.iss`); solo Linux/pip arrastra `-cli` desde 0.5.0 (cuando `outwarp` era el binario de la GUI y se colapsó todo en uno). Tiene que ir **antes de 1.0** porque la superficie CLI se congela ahí. Plan:
  - `[project.scripts]` del cliente: `outwarp = "outwarp.cli:main"` como entrada principal; **mantener `outwarp-cli` una release como alias** que funciona igual y avisa una línea por stderr ("use `outwarp`"). Retirarlo en 1.0.0. Es una compatibilidad justificada: hay unidades systemd, `.desktop` y completions **en disco** en instalaciones existentes que apuntan al nombre viejo; el updater in-app (`updater.py`, `pip install` dentro del venv pipx) no las reescribe.
  - `service.py` (`ExecStart=`, `shutil.which`), `install.sh` (`CLIENT_BIN_LINK` vuelve a ser el link real, `.desktop` `Exec=`, completions bash/zsh, mensajes), `uninstall.py`, `diagnostics.py` (remedios), TUI/GUI (textos de ayuda, `FailedScreen`, settings), `updater.py`, `release.yml`/`release.sh`, `outwarp-client.spec` de PyInstaller (comprobar que el exe sigue siendo `outwarp.exe`), README, CHANGELOG, `docs/RELEASE_SIGNING.md`, y este fichero. ~220 referencias en ~45 ficheros: hacerlo con `grep`, no de memoria, y revisar `bundle.js` regenerado.
  - `service install` y `install.sh` tienen que **migrar** una unit/`.desktop`/completions existentes al nombre nuevo al actualizar (idempotente), y `doctor` avisar si aún apuntan a `outwarp-cli`.
  - Tests: `test_cli.py`, `test_service.py`, `test_wheel_contents.py` (los dos entry points presentes durante la release de transición; solo `outwarp` después).
- [ ] **Cliente Linux con GUI de primera clase, no solo TUI.** Hoy la GUI pywebview en Linux es opt-in (`install.sh` → `OUTWARP_CLIENT_GUI=1`, extra `gui-linux`; `app.py` la excluye por marker PEP 508). Criterio: en una sesión de escritorio (`$WAYLAND_DISPLAY`/`$DISPLAY`) el instalador ofrece la GUI por defecto y la TUI sigue siendo el camino headless; `outwarp gui` arranca sin pasos manuales; tray + ventana probados en X11 (GNOME/KDE) y Wayland (Hyprland, GNOME); `doctor` comprueba las deps de GUI y el backend del tray; README/`install.sh --help` lo documentan. Propuesta técnica (a confirmar al implementar): mantener el marker y el extra `gui-linux` (los wheels Linux no arrastran webkit2gtk) y cambiar el **default del instalador**, no el `pyproject`.
- [ ] **Compatibilidad total con Omarchy** (Arch Linux + Hyprland/Wayland + waybar + mako + systemd + pacman). **No es solo que instale: es que, una vez instalado, se sienta parte del sistema** (petición literal del autor: "que salga arriba con los iconos y se integre bien una vez instalado"). Criterio de aceptación, verificado en una instalación limpia de Omarchy:
  - *Instalación:* `install.sh` completa por la ruta `pacman` (paquetes: `python-pipx`, `wireguard-tools`, `python-gobject`, `webkit2gtk-4.1`, `libayatana-appindicator`) e instala la GUI por defecto (ver punto anterior).
  - *Barra superior (waybar):* el icono de OutWarp aparece en el tray de waybar (StatusNotifierItem vía appindicator — el backend Xorg de pystray no vale en Wayland) y **cambia con el estado** (desconectado / conectando / conectado / reconectando / fallo), con iconos legibles al tamaño de waybar y coherentes en tema claro y oscuro; el menú del tray funciona con clic y todas sus entradas (conectar, desconectar, abrir GUI, logs, salir). Si el tray no puede arrancar, la GUI lo dice en pantalla en vez de fallar en silencio.
  - *Ventana:* la ventana pywebview abre bajo Wayland (GTK) sin X11, con título e icono propios (`app_id`/clase estable para que Hyprland le aplique reglas), tamaño sensato y **flotante** por defecto — documentar la `windowrule` de Hyprland recomendada, o instalarla si Omarchy tiene un sitio para ello.
  - *Escritorio:* el `.desktop` aparece en el lanzador de Omarchy con icono y nombre correctos y abre la GUI, no una terminal; el icono se instala en el tema (`hicolor`, varios tamaños) y no depende de una ruta absoluta.
  - *Notificaciones:* `notify-send` llega a mako con icono y con un resumen útil (conectado/desconectado/fallo), sin duplicados.
  - *Arranque y servicio:* opción de autoarranque con la sesión (unit de usuario systemd + linger, o el mecanismo de autostart de Hyprland — decidir e implementar uno, documentar el otro); kill switch nftables funciona.
  - *Diagnóstico:* `doctor` devuelve todo PASS en Omarchy e incluye un check del tray/backend en Wayland con remedio concreto.
  - **Arch es rolling:** Omarchy lleva la Python más nueva (3.13/3.14) → la matriz de CI debe incluir la versión que Arch tenga en el momento del release, y `requires-python` no puede excluirla.
  - Un `PKGBUILD` para AUR es el camino nativo, pero va como 1.x (ver `ROADMAP.md` "Native Linux packages"), no bloquea.
- [ ] **Test runner de JS (vitest) + guardia de bundle.** Opción mínima: `package.json` en la raíz solo con devDeps (vitest, jsdom); helper de test que transpila un `.jsx` con esbuild y lo evalúa en un `window` falso; tests de lógica pura (`makeBoundedPeak` fija B-022; `fmtBytes`/`fmtBps`/`fmtAgo` con `now` inyectado). Más un test que reconstruye `bundle.js` con `scripts/build_ui.py` y falla si difiere del commiteado. Job `ui-tests` en CI (Node ya hace falta para `build_ui.py`). NO convertir la UI a módulos ES para esto: solo si algún día hacen falta tests de componentes.
- [ ] **Retirar el fallback de manifiesto sin firmar.** `verify_download` en ambos updaters pasa a fail-closed: una release sin `SHA256SUMS.txt` + `.minisig` válidos se rechaza siempre.
- [ ] **README y wizard honestos con el anti-DPI.** Sustituir la promesa de `README.md` ("corporate networks, captive Wi-Fi…") por la tabla de adversarios: la rama autofirmada pasa "UDP bloqueado / solo 443"; la rama Caddy+dominio pasa además inspección de certificado; **ninguna** pasa huella TLS (JA3/JA4) ni DPI del Upgrade (caso WIFI_EDU). En `setup`, presentar "tengo un dominio" como camino principal y el autofirmado como "sin dominio, solo contra UDP bloqueado". Añadir "Plataformas soportadas" y "Limitaciones conocidas" (DPI, SmartScreen sin firmar) y **quitar el banner "not yet ready for production"**. Descartado y no reabrir: uTLS/imitación de ClientHello (reescribir el transporte). Como spike futuro, solo con una red DPI real para probarlo: ECH (`--tls-ech-enable` de wstunnel + Caddy ≥ 2.10), que oculta el SNI pero no cambia la huella JA3.
- [ ] **Release firmada y un ciclo sin hotfix.** 1.0.0 sale con `SHA256SUMS.txt.minisig` el mismo día (la clave está offline, en la máquina del autor; ver `docs/RELEASE_SIGNING.md`) y después de que la última 0.x lleve 2–4 semanas en producción (el pod k3s del autor) sin hotfix.

**NO bloqueante** (tentación de creer que sí; no reabrir):
- Certificado Authenticode para el instalador Windows: es dinero, no calidad. El aviso de SmartScreen se documenta en "Limitaciones conocidas".
- Multi-perfil, split tunnelling, DDNS, auto-update del servidor, Prometheus, más idiomas: features; caben en 1.x sin romper nada.
- Cliente móvil: otro producto.

## Convenciones de código

- Python 3.11+, type hints obligatorios.
- `ruff` es el gate de lint del repo (no se corre `black`). Hay deuda de lint preexistente; no introducir violaciones nuevas.
- Docstrings solo cuando el "por qué" no sea obvio del nombre (regla estándar del repo).
- Sin comentarios inline triviales.
- Tests donde tenga sentido (lógica de config, parser de logs, abstracciones de plataforma mockeables).

## Estado actual

**Versión actual: `0.13.0`** (en código). Changelog de cara al usuario en `CHANGELOG.md` (raíz).

### Cambios en 0.13.0 — auditoría "qué sigue bloqueando"

Auditoría del 2026-09-12 sobre `9c255f2` (código + el pod k3s real como
evidencia, no como objetivo: OutWarp se mantiene igual para Windows,
Linux/systemd, Docker y k8s). Detalle en `CHANGELOG.md` (Unreleased) y
`KNOWN_BUGS.md` B-018…B-021. Lo estructural:

- **Enrolamiento por el puerto del túnel (`.owcfg` v4).** El listener
  (`enroll_server.py`) solo escucha en loopback; el cliente llega como
  forward TCP de wstunnel (`--restrict-to 127.0.0.1:<enroll_port>` además
  del de WG) por el mismo puerto y la misma escalera que el túnel
  (`client/outwarp/enroll.py::_redeem_via_transport`). En Linux/systemd hay
  `outwarp-enroll.service` (`outwarp-server enroll-listener`); en
  Windows/Docker/k8s lo aloja `ServerManager`. `ServerPlatform` gana
  `manages_enroll_service` y `os_managed_transport`. `restart` re-renderiza
  las units (es el paso post-`update`). Caddy ya no lleva ruta `-enroll`.
  Test e2e con wstunnel real: `server/tests/test_enroll_transport_e2e.py`.
- **Resolución antes de WG.** `tunnel._with_addresses()` resuelve cada rung
  (sistema / `1.1.1.1` en crudo para hostiles / host del proxy) antes de
  instalar WG; `ConnectionStrategy.connect_host` hace que wstunnel marque la
  IP con SNI/Host = hostname. `escape_set()` ya no excluye `1.1.1.1`.
- **`daemon`/`serve` salen con código 3** en FAILED/ERROR.
- **Panel:** `ServerManager.refresh_config()`, estado `pending`,
  `service_control` (`full`/`restart`/`none`), `add_client` sin fichero en
  cwd.
- **k8s:** liveness `exec` (pgrep wstunnel + wg0), `OUTWARP_ENROLL_PORT`
  opcional, `OUTWARP_PLATFORM=kubernetes` en la imagen.

Seguimientos apuntados (no hechos): kill switch + endpoint por hostname (la
allowlist no cubre el DNS que la reconexión necesita); TOCTOU del pin en el
enrolamiento (pin en una conexión, POST en otra — mismo modelo que el
transporte); rate limiter del enrolamiento es un cubo global tras el forward.

### Cambios en 0.12.0 (auditoría de seguridad completa + refactors de arquitectura)

`OutWarp-fix-plan.md` (auditoría sobre `70b2214`, 13 hallazgos en 3 grupos de
severidad + 6 propuestas CONCEPTO-*) resuelto casi entero — todo salvo
CONCEPTO-A/D en su forma "sacarlo todo a SQLite" completa (sí se hizo, ver
abajo) y CONCEPTO-E's client-side kill-switch UI toggle en la TUI (el dato ya
se respeta, falta el row del modal).

- **FIX-01 a FIX-13**: validación de todo campo de `.owcfg`/`server_config.json`
  antes de que llegue a un `.conf`, comando `iptables` o filename;
  `enroll.py` deja de desactivar TLS verify incondicionalmente; `rotate-client`
  ya no deja la clave privada en `Path.cwd()`; `--config-dir` ya no salta el
  check de root fuera de `OUTWARP_TEST_MODE`; kill switch allowlist completo
  (ver CONCEPTO-B abajo); lock cross-proceso en add/revoke/rotate-client
  (superado después por CONCEPTO-A); `uninstall` ya no se mata a sí mismo;
  NAT de Windows se recrea tras `restart_wg()`; timeout en `add/remove_peer_live`;
  rate limiter de enrolment lee `X-Forwarded-For` tras Caddy; timeout +
  idle-heartbeat en el panel SSE (slowloris); `install-from-release.ps1`
  verifica SHA256 antes de ejecutar; varios menores (Caddyfile injection,
  `tarfile filter="data"`, `GITHUB_TOKEN` scoping).
- **CONCEPTO-B — un solo dueño de "qué escapa del túnel".**
  `client/outwarp/routing.py::escape_set(config, ladder)` es ahora la única
  función que calcula ese conjunto; la usan `build_wg_conf`, la escalera de
  fallback y las dos rutas del kill switch (antes cada una lo recalculaba
  distinto y el kill switch olvidaba el endpoint del servidor).
- **CONCEPTO-C prop.2 — firma de `.owcfg` con minisign.**
  `server/outwarp_server/minisign.py` ganó la mitad de firma (Ed25519,
  formato minisign real — cross-verificado contra el binario `minisign` 0.12,
  que encontró un bug real: el contenedor de clave pública siempre lleva el
  tag `Ed`, nunca `ED`, aunque la firma sea prehashed). La firma va embebida
  en el propio `.owcfg` (no un `.minisig` aparte) bajo `signing.{public_key,
  signature}`. `client/outwarp/profile_trust.py` (nuevo) verifica al importar
  y hace **pinning TOFU** de la clave del servidor por endpoint en
  `known_servers.json` — perfil sin firma solo avisa (mismo fail-open que el
  updater de releases); firma inválida aborta el import; clave distinta a la
  pinned avisa pero no bloquea (rotación de clave admin-iniciada).
- **CONCEPTO-C prop.1 — declarar la frontera de confianza.** Regla explícita
  en la cabecera de `_parse()` (ambos `config.py`): el `.owcfg` es hostil,
  `server_config.json` semi-confiable pero se valida igual. Cierra los campos
  que quedaban con `str(...)` sin check: `server.endpoint`, `tunnel.remote_host`,
  `http_upgrade_path_prefix` (hostname/IP + charset), y los campos libres de
  cada rung de fallback (`sni_override`/`host_header`/`user_agent`/`proxy`,
  rechazan caracteres de control — viajan como argv/cabecera HTTP a wstunnel).
  `caddy.py` importa `_HOSTNAME_RE`/`_EMAIL_RE` desde `config.py` en vez de
  mantener su propia copia.
- **CONCEPTO-D — ciclo de vida real de `ClientEntry`.** Nuevos campos `state`
  (`active`/`revoked`) y `enrolled_at`. Revocar ya no borra la fila (soft
  delete) — "nunca se enroló" y "se enroló y se revocó" vuelven a ser
  distinguibles. La expiración la aplica el servidor: `wireguard.py` excluye
  peers caducados de cada `wg0.conf` regenerado, y `ServerManager._do_start()`
  poda expirados en cada arranque — antes solo lo aplicaba `prune-expired` (a
  mano) o el propio cliente al que se le caducaba el acceso.
- **CONCEPTO-A — registro de clientes a SQLite.** Nuevo
  `server/outwarp_server/client_store.py` (modelado en `traffic_history.py`):
  tabla `clients` en `clients.sqlite`, junto a `server_config.json`.
  `transaction()` abre con `BEGIN IMMEDIATE` — toma el lock de escritura antes
  del primer `SELECT`, cerrando la carrera de FIX-04 **por construcción**, no
  por serialización con flock. `ServerConfig.load()` migra el array JSON una
  vez y repuebla `.clients` desde SQLite en cada load — los 9 sitios que leían
  `config.clients` (`cli.py`, `wireguard.py`, `api.py`, `server_manager.py`...)
  no cambiaron.
- **CONCEPTO-E — dueño del estado de red del sistema.**
  `ServerPlatform.reconcile()` (concreto en `platforms/base.py`) sustituye la
  secuencia manual `prepare_system()`/`install_wg_config()`/`restart_wg()` —
  siempre prepara NAT/forwarding antes de instalar o reiniciar. En el cliente,
  el kill switch se extrajo a `client/outwarp/killswitch.py` y lo dispara
  `TunnelManager._set_state` directamente (propiedad `kill_switch_enabled`,
  igual patrón que `allow_tls_intercept`) — antes solo vivía en `api.py` (el
  bridge pywebview), así que el TUI y `outwarp daemon` (el target real de
  systemd) nunca lo activaban ni liberaban.
- **CONCEPTO-F** — tests de regresión extraídos de `KNOWN_BUGS.md` (B-005,
  B-012, B-016, B-017) para que las invariantes sobrevivan a un refactor.
- Windows: la pregunta del wizard sobre dominio/Caddy ahora es solo Linux —
  ofrecerla en Windows generaba una config de Caddy que nada en el host podía
  leer (`/etc/caddy` no existe ahí).
- Linux: el `.conf` de WireGuard del cliente ya no vive en `/etc/wireguard`
  (ahora `/etc/wireguard-outwarp`) — otros gestores de WireGuard como
  omarchy-vpn escanean ese directorio y adoptan/tumban cualquier túnel que
  encuentren, incluido el de OutWarp.

- **Pre-release (2026-09-11), tras diagnóstico en vivo + revisión senior**:
  `get_tunnel_stats()` leía `wg show` sin privilegios → en Linux no-root la
  escalera nunca veía el handshake y el cliente no conectaba desde 0.10.0
  (ahora pasa por `outwarp-priv dump`, como `tunnel_stats.py`); `Tunnel.cancel()`
  cooperativo para que `TunnelManager.stop()` no desmonte el túnel bajo una
  escalera en curso (dejaba un wstunnel huérfano que moría con `Broken pipe`);
  kill switch reescrito en ambos OS (Linux: regla `oifname <iface>`, helper
  v2 `killswitch-on <iface> <ip|cidr>...`; Windows: `DefaultOutboundAction
  Block` + allows por `remoteip`/`localip` en vez de una regla block — sin
  probar en máquina real), allowlist resuelta a IPv4 (los dominios nunca
  enganchaban), engancha antes del teardown; endpoints pre-resueltos antes de
  subir WG (el DNS del túnel bloqueaba el pin check ~49 s); `doctor` sudoers
  vía `sudo -l` + check de versión del helper; servidor: nombre revocado
  reutilizable en `add-client`, GUI guarda bajo `locked_config` sin pisar la
  clave de firma, perfil sin firma para endpoint ya pinneado se rechaza.

- **0.12.1 (2026-09-11), bugs reales encontrados usando el producto**:
  `--config-dir` era ignorado por `ServerManager`/GUI/panel/enrolment fuera
  de la carga inicial (detectado por el propio autor + su agente de homelab
  contra el despliegue k3s real) — el CLI exporta ahora `OUTWARP_CONFIG_DIR`
  y `ServerManager` conserva el path con el que arrancó; `EnrollError` sin
  capturar escapaba como traceback crudo en vez de un `ConfigError` accionable
  (puerto de enrolment inalcanzable); `add-client` avisa de que ese puerto
  hay que abrirlo aparte del túnel. Bugs de diseño encontrados en la propia
  revisión de estos cambios: sudoers del helper sin `!syslog,!pam_session` →
  el poll a 1Hz del dashboard TUI inundaba auth.log; `ServerConfig.load()`
  tomaba el lock de escritura de `clients.sqlite` en cada carga para
  comprobar una migración que ya estaba hecha (pre-check sin lock antes de
  `BEGIN IMMEDIATE`); el resolver DNS del rung hostil (`1.1.1.1`) no estaba
  en `escape_set()`, así que con WG arriba y el túnel caído la resolución de
  wstunnel se colaba dentro del túnel muerto y se quedaba colgada; el
  veredicto de `verify_and_pin()` (verificado/sin firmar/clave rotada) sólo
  llegaba al log — ahora es un `TrustVerdict` devuelto por
  `import_owcfg_with_verdict()`/`import_owcfg_text_with_verdict()` (los
  wrappers `import_owcfg`/`import_owcfg_text` sin sufijo siguen igual) que
  CLI/GUI/TUI muestran al usuario.

- **Auditoría del panel web/GUI del servidor (2026-09-11), "el dashboard va
  raro"**: el badge running/stopped mentía siempre que el proceso que lo
  renderizaba no era el que arrancó el servicio — exactamente el caso del pod
  de k3s (`outwarp-server serve` + `outwarp-panel web` en contenedores
  separados, ninguno de los dos llama a `start()` del otro). Nuevo
  `ServerManager.effective_state`: si `state` es el default STOPPED nunca
  tocado, lo reconcilia contra el SO (`is_wstunnel_running()`/`is_wg_active()`,
  los mismos probes que ya usaba `outwarp-server status`) — un `state`
  RUNNING/STARTING/ERROR puesto por este mismo proceso no se toca. `start()`
  adopta el servicio externo en vez de competir por el mismo puerto. Requiere
  `shareProcessNamespace: true` en el pod (añadido a
  `deploy/kubernetes/deployment.yaml`) para que el `pgrep` del contenedor
  panel vea el proceso wstunnel del contenedor server. Además: gráfica de
  tráfico y sparklines por cliente reescalaban el eje Y al máximo exacto de
  la ventana en cada tick (parecía "respirar" con tráfico estable) → ahora
  peak-hold con decaimiento lento; el cálculo de bps usaba `Date.now()` del
  navegador en vez de un timestamp del servidor (`list_clients()` añade
  `sampled_at`) — frágil con pestañas en segundo plano / SSE con retraso;
  `get_app_info()` (cliente y servidor) y dos strings de UI decían
  `"license": "MIT"`, desactualizado desde el cambio a PolyForm Noncommercial.

Cliente: 596 tests. Servidor: 531 tests (+2 e2e con wstunnel real, se saltan sin el binario). `ruff` limpio en ambos paquetes.

### Cambios en 0.11.0 (arquitectura de seguridad)

Tres fallos corregidos, en el orden en que importan:

1. **Rama con dominio para el transporte del servidor.** `setup` bifurca: con
   dominio, **Caddy** ocupa el 443 con cert Let's Encrypt y sitio señuelo, y el
   túnel vive en el path secreto detrás; wstunnel pasa a `ws://127.0.0.1:8080`.
   OutWarp genera y recarga la config de Caddy de forma **aditiva** — es dueño de
   `/etc/caddy/conf.d/outwarp.caddyfile` y nunca reescribe un Caddyfile ajeno.
   Módulo `server/outwarp_server/caddy.py`; campos nuevos en `ServerConfig`:
   `tls_mode` (`self-signed` | `acme`), `internal_ws_port`, `acme_email`,
   `enroll_port`.
   - El autofirmado sigue siendo válido donde el único obstáculo es UDP
     bloqueado, pero **no** contra DPI que inspecciona TLS (caso WIFI_EDU).
2. **`tls.verify` (`pin` | `ca`) en el `.owcfg` (schema v2).** En modo `ca` el
   cliente valida cadena contra el almacén del sistema **y pasa
   `--tls-verify-certificate` a wstunnel** — antes el pin se comprobaba en una
   conexión aparte mientras wstunnel aceptaba cualquier certificado (el pin era
   advisory). Añadido también `tls.spki_sha256`: pin de **clave pública**, que
   sobrevive a reemitir el cert → nuevo `outwarp-server renew-cert` (reusa la
   clave; `--new-key` la reemplaza e invalida todo). El extractor SPKI del
   cliente es un walk DER a mano (`network._spki_der`) porque el cliente no
   depende de `cryptography`.
3. **Enrolamiento: el servidor ya no genera claves privadas de cliente.**
   `add-client` reserva el slot y emite un **token de un solo uso (15 min)**;
   el cliente genera su par localmente (`outwarp/keygen.py` vía `wg genkey`) y
   canjea el token enviando solo la pública (`outwarp/enroll.py` →
   `POST /enroll`). Listener en `enroll_server.py` (loopback + Caddy en la rama
   acme; HTTPS público en `enroll_port` en la autofirmada). Store de tokens con
   scrypt en `enrollment.py`, reusando `web_auth.hash_secret` + `RateLimiter`.
   `.owcfg` v3 sin `client_private_key`. `--embed-key` mantiene el formato viejo.
4. **Firma de releases (minisign)** en ambos updaters. `client/outwarp/minisign.py`
   implementa Ed25519 a mano (RFC 8032 §6, solo verificación) para no meter
   `cryptography` en el bundle; el del servidor usa `cryptography`. La pubkey va
   **compilada**, la privada **offline, nunca en un secret de CI**. Proceso en
   `docs/RELEASE_SIGNING.md`. **Inerte hasta que se genere la clave**
   (`_MINISIGN_PUBLIC_KEY = ""`).
5. **Escalera**: el rung S2 `direct-camouflage` desaparece; el User-Agent de
   navegador va ahora en **todos** los rungs directos (ahorra ~20 s y llega a los
   filtros L7 al primer intento). Nuevo orden: S0 direct → S1 DNS público →
   S2 proxy → S3 puertos alternativos → S4.. provisionados.
6. **Cert autofirmado endurecido**: basicConstraints, keyUsage, EKU serverAuth,
   SKI/AKI, y validez 3650 → 825 días.
7. `build_wstunnel_command()` es ahora la **única** definición de la invocación de
   wstunnel (proceso + unit systemd la renderizan de ahí; antes estaban
   duplicadas y podían divergir).

Resumen de 0.8.0 (Linux UX + TUI feature pass + fixes de code review): notificaciones de escritorio vía `notify-send` (`outwarp/notify.py`, cableado en GUI/TUI/daemon), launcher `.desktop` + icono + completions bash/zsh instalados por `install.sh`, toggles de servicio systemd + linger en el settings modal de la TUI, `outwarp doctor` + DoctorScreen del cliente (`outwarp/diagnostics.py`: wstunnel/pin/wg/helper/sudoers/kmod/systemd/notify-send), `outwarp-server rotate-client` (CLI + TUI con QR), filtros del log screen (`/` búsqueda, `e`/`w` nivel, `p` pausa), auto-scan de `.owcfg` en el import modal, sparklines rx/tx, hints de error + log inline en FailedScreen, columna expires + prune (`P`) en la tabla de clientes del servidor, copy endpoint (`c`). Seguridad: `add_client()` valida el nombre antes de construir el path del `.owcfg` (path traversal vía `../`). Resumen de 0.7.1: el `install.sh` de Linux instala la versión de wstunnel **pinneada** (antes bajaba la última de GitHub y aceptaba en silencio cualquier binario preexistente del PATH → un cliente derivó a 10.5.5 contra un servidor 10.5.2; el formato del WS upgrade cambió entre versiones → HTTP 400 y túnel sin tráfico, "conecta" pero solo sube). Versión centralizada en `installer/wstunnel-version.txt` (la leen `fetch_bundled_binaries.py` y el workflow de Docker; `install.sh` y `server/Dockerfile` la replican), con `server/tests/test_wstunnel_version_pin.py` como guardia anti-drift. Resumen de 0.7.0 (hardening tras auditoría de código + UX + CI del instalador Windows):
- **Seguridad de secretos**: `ClientConfig.save()` (y `config.original.json`) ahora escriben atómicamente a 0o600 (`_atomic_write_secret`) — antes `config.json` con la clave privada WG quedaba a la umask (world-readable en Linux). La WG conf del servidor (linux/kubernetes/windows) pasa por el mismo helper (sin ventana 0o644→chmod). Txn ID de la sonda DNS de `detect_hostile_network()` ahora aleatorio (`secrets`), no fijo.
- **TUI responsiva**: el dashboard del cliente corre `StatsSampler.sample()` (subprocess `wg`/`ping`) en executor en vez de bloquear el event loop; `disconnect`/`reconnect`/`quit` ya no congelan la TUI mientras `mgr.stop()` hace join. Indicador de estado del túnel visible en `StatusCard` (antes el dashboard era idéntico conectado vs desconectado). Stepper de conexión con 5º paso "ready" como la GUI.
- **Robustez**: validación de `reconnect.max_attempts`/`delays_seconds` en el parser (un `max_attempts=0` ya no provoca fallo instantáneo silencioso). `top_talkers()` usa `LAG()`+clamp (no `MAX-MIN`) para no inflar tras un reset de contador. Race de `_replace_manager` cerrado con `TunnelManager.remove_listener()`. Stats/latency loops hacen join al pararse. Lock en `_last_failure_message` del servidor.
- **UX/coherencia**: tokens de color centralizados en `tui/tokens.py` (cliente + servidor) y alineados al CSS canónico (`warn #ff8a3d`, `bad #ff4d6d`) — antes divergían entre GUI y TUI. `HostileBanner` diferenciado del `IntegrityBanner` (azul/info + escudo en modo `auto`). LogsScreen del servidor incluye `wg-quick@wg0`. Validaciones de perfil migradas a inglés (toda la TUI es inglés). Doctor: binding `f` y `remediation_command` según gestor de paquetes (apt/dnf/pacman/zypper/apk). HelpModal + `_NoConfigScreen` más accionables.
- **Tests**: +2 para `run_daemon` (sin perfil → exit 2; start→stop→0). Cliente 349 / servidor 283 en verde, ruff limpio.

### Cambios desde 0.5.x (0.6.0):
- **Daemon mode**: nuevo subcomando `outwarp daemon` — el `TunnelManager` headless que el `ExecStart=` de systemd/SCM invoca, silente en stdout (todo va al log file). Complementa: `outwarp service install|uninstall|status` gestiona la unit user-level `~/.config/systemd/user/outwarp-client.service`. Windows queda con stub (el SCM wrapper llegará en un release posterior). Lógica en `outwarp/service.py`.
- **Anti-DPI infra (parcial)**: `--websocket-ping-frequency 25s` siempre, omitir `:443` del `wss://` cuando es el puerto por defecto, y un toggle `hostile_mode` (auto/on/off) por perfil que activa `--dns-resolver dns://1.1.1.1 --dns-resolver-prefer-ipv4`. El modo `auto` corre `detect_hostile_network()` (compara DNS del sistema vs Cloudflare directo) en `Tunnel.connect()` y emite el evento `outwarp:hostile`. **No es suficiente para pasar redes con DPI agresivo como WIFI_EDU** — el firewall del instituto sigue devolviendo 400 al WS Upgrade aunque la huella TLS coincida con el cert real del server. Se considerará uTLS / Cloudflare-front en un release futuro.
- **GUI `HostileBanner`**: pywebview muestra un banner cuando llega el evento `outwarp:hostile`, similar al `IntegrityBanner` pero con copy distinto según `mode`.
- **TUI dashboard reactivity fix**: `TunnelCard` y `StatusCard` ya repintan tras editar el perfil. Causa: las screens registradas en `App.SCREENS` por clase se cachean → `compose()` corre una sola vez. Fix: `update_config()` en ambas tarjetas + `on_screen_resume()` en `DashboardScreen` que les pasa la config actual; el `StatsSampler` también se reconstruye si cambian `iface` o `endpoint`.
- **Fix de `import_profile`**: `outwarp/api.py:import_profile` ahora pasa `dest=default_config_path()` explícito a `import_owcfg_text`. Antes, los tests que sólo parcheaban `outwarp.api.default_config_path` filtraban escrituras a `~/.config/OutWarp/config.json` real durante la suite completa.

### Cambios desde 0.5.0:
- **Docker + Kubernetes oficiales**: imagen multi-arch (`linux/amd64` + `linux/arm64`) publicada en `ghcr.io/<owner>/outwarp-server` desde `.github/workflows/docker-publish.yml`. Manifests listos en `deploy/kubernetes/` + helper `deploy/build-pi.sh` para k3s en Raspberry Pi 5. Guía end-to-end en `deploy/README.md`.
- **TUI como UI primaria en Linux**: el `install.sh` ya no exige `libwebkit2gtk`; el autostart apunta a `outwarp tui` por defecto y la GUI pywebview es opt-in. Editor de perfil completo dentro del TUI del cliente.
- **CI completo**: `.github/workflows/ci.yml` corre pytest + ruff + wheel build en `ubuntu-latest` y `windows-latest`; `docker-publish.yml` publica imágenes en cada push a main y en cada tag `v*`.
- **Fixes contenedor**: el `wg-quick` PostUp ya no falla en pods sin `SYS_ADMIN` (sysctl despojado del PostUp) y la imagen incluye `procps` para que `wg-quick` encuentre `/usr/sbin/sysctl` cuando se ejecuta con `SYS_ADMIN`.
- **Linux wheels + pipx** (desde 0.5.0): `/opt/pipx/venvs/outwarp-{client,server}/`. El `install.sh` migra desde la layout legacy `/opt/outwarp-*/.venv` y detecta el layout pipx 0.5.0+/1.12 al desinstalar.
- **CLI unificada** (desde 0.5.0): solo `outwarp` y `outwarp-server`. Subcomandos `gui` / `tui` / `uninstall` / `forget-profile` consolidados.
- **Hardening de secretos** (desde 0.5.0): `.owcfg`, `server_config.json` y clave privada TLS con permisos 0o600. `install.sh` valida SHA256 de `wstunnel` contra el manifest de erebe.

### Cliente

- **Windows**: ✅ completo y en producción. Instalador `.exe` (PyInstaller + Inno Setup) que bundlea WireGuard for Windows y `wstunnel.exe`. GUI pywebview + tray.
- **Linux**: ✅ completo, validado end-to-end. `install.sh` con bootstrap (detecta/instala Python, crea venv, recrea venv corrupto, registra systemd unit). Incluye `outwarp` headless para máquinas sin escritorio.
- **macOS**: ❌ fuera de alcance, no se implementará.

Fases originales del cliente (todas ✅): scaffolding, schema/loader del `.owcfg`, abstracción de plataforma, orquestador del túnel (`tunnel.py`/`wireguard.py`/`network.py` con TLS pinning en Python), watchdog + reconexión (`TunnelManager` con máquina de estados `DISCONNECTED/CONNECTING/CONNECTED/RECONNECTING/FAILED`), tray + logs (rotación 512 KB + `MemoryLogHandler`), app.py end-to-end con mutex de instancia única (`CreateMutexW` en Windows, `fcntl.flock` en POSIX).

### Servidor

- **Linux**: ✅ completo (systemd + `wg-quick`/`wg syncconf`, setup wizard rich, detección de IP pública, cert self-signed EC P-256, probe de conectividad, `is_wg_active` sin root).
- **Windows**: ✅ implementado (SCM vía pywin32; single-bundle GUI-first con CLI opt-in).
- **Docker/Kubernetes**: ✅ añadido (`platforms/kubernetes.py` + manifests) — no estaba en el plan original.
- **macOS**: ❌ fuera de alcance.

Fases del servidor (todas ✅): scaffolding + config, crypto (`crypto.py`), IP pool + WG server config (`ip_pool.py`/`wireguard.py` con hot-reload), `owcfg` + comandos de gestión, plataforma Linux + setup wizard, status command. Subcomandos: `setup`, `add-client`, `list-clients`, `revoke-client`, `status`.

### UI (Claude Design)

✅ Mergeada a `main` (la rama `new-uidesign` ya no existe). customtkinter sustituido por HTML/React 18 + pywebview con JS bridge directo (sin FastAPI/uvicorn). Los bundles JSX se pre-compilan (se eliminó Babel in-browser + React por CDN). Añadidos posteriores: **editor de perfil en la UI** (editar nombre, MTU, DNS, IP, routing, reconnect sin re-importar el `.owcfg`), **gráfica de throughput en vivo** en Home, About screen, stepper de "connecting", logs seleccionables con botón jump-to-bottom.

### Tests

**~245 tests del cliente + ~174 del servidor** pasando (subprocess/socket/ssl/pywebview mockeado en el cliente; `cryptography` real + subprocess/urllib/pywebview mockeado en el servidor; corren en cualquier OS).

### Pendiente para la primera versión estable

La lista completa y vinculante está en **"Criterio de 1.0.0"** (sección Licencia, más arriba). Resumen: e2e en CI · kill switch + hostname · renombrar `outwarp-cli` → `outwarp` (hecho) · GUI Linux de primera clase · compatibilidad Omarchy · vitest + guardia de bundle · fallback sin firma retirado · README/wizard honestos sin el banner "not ready" · release firmada tras un ciclo sin hotfix. El instalador Windows sin firmar **no** bloquea.

El repo está en GitHub como privado: https://github.com/fcrespo07/OutWarp

## Optimizaciones de rendimiento (aplicadas ✅)

El túnel funciona end-to-end (speed test de referencia: Download 34.76 Mbps / Upload 24.16 Mbps, Ping 62–118 ms en LAN). Las dos optimizaciones que estaban pendientes ya están en código:

1. **Connection pooling**: `--connection-min-idle 3` en `client/outwarp/tunnel.py` (`build_wstunnel_command()`). Mantiene 3 conexiones TLS pre-establecidas, evitando el handshake de ~30–50 ms por cada sesión UDP nueva.
2. **MTU correcto**: el MTU del config WireGuard ya **no está hardcodeado** — es **editable por perfil** desde la UI. `wireguard.py` → `build_wg_conf()` lee `wg.mtu`, validado a 576–1500 en `config.py`. El cálculo de referencia para WG-over-TCP/TLS sigue siendo ~1380 (1500 − 40 IP/TCP − 40 TLS − 8 WS − 4 wstunnel − 28 WG); el default 1420 está calibrado para WG-over-UDP y sobre TCP/TLS provoca fragmentación y jitter.

---

## Nueva UI (Claude Design) — mergeada a `main`

La UI customtkinter se sustituyó por los HTML/JSX exportados de **Claude Design**, con un rebrand del proyecto a **OutWarp** (`.warpcfg` → `.owcfg`). El backend Python (tunnel, wireguard, network, config, logs, platforms, server_manager, crypto) **no cambia** — los cambios se concentran en la capa de presentación.

### Arquitectura final

```
cliente:  pystray ── "Abrir" ──► pywebview window (file://ui/index.html)
                                       │
                                       │  window.pywebview.api.<método>
                                       │  window.addEventListener('outwarp:<event>', …)
                                       ▼
                                  outwarp.api.Api ──► TunnelManager (tunnel.py)

servidor: idéntico, con outwarp_server.api.Api ──► ServerManager (server_manager.py)
```

Sin FastAPI ni uvicorn: el JS bridge de pywebview es la integración Python ↔ JS. Esto reduce ~600 líneas de plumbing HTTP, elimina el token de auth y simplifica el packaging.

### Lo que se eliminó

- `wizard.py` (ventana customtkinter de importación).
- `main_window.py` / `server_window.py` (dashboards customtkinter).
- Dependencias `customtkinter`, `fastapi`, `uvicorn[standard]`, `websockets`, `python-multipart`.

### Lo que se añadió

| Archivo | Rol |
|---|---|
| `outwarp/api.py` | Clase `Api` con métodos JS-callable. Envuelve `TunnelManager`, gestiona settings persistentes en `settings.json`, retransmite eventos del MemoryLogHandler como `outwarp:log`. |
| `outwarp/ui/` | `index.html` + `styles.css` + `app.jsx` (shell cableado) + `var-a.jsx` + `var-b.jsx` (referencia de diseño) + `shared.jsx` (i18n + atoms) + `brand.jsx` (logo). |
| `outwarp_server/api.py` | Equivalente para el servidor: status, start/stop/restart, add/revoke client, run_setup (wizard), detect_public_ip, list_clients con get_live_peers. |
| `outwarp_server/ui/` | Mismo skeleton para el servidor + `srv-data.jsx` con SRV_STR (i18n) y los componentes `srv-a/b.jsx`. |

### Bridge protocol

**JS → Python**: `await window.pywebview.api.<método>(args…)`. Todos los métodos devuelven JSON-serialisable. Operaciones bloqueantes (stop / restart) se despachan en `threading.Thread(daemon=True)` para no congelar el bridge.

**Python → JS**: `Api._emit(name, payload)` ejecuta `window.evaluate_js("window.dispatchEvent(new CustomEvent('outwarp:NAME', {detail: …}))")`. El JS escucha con `window.addEventListener('outwarp:NAME', …)`.

Eventos:
- `outwarp:status` — cambio de estado del túnel/servicio.
- `outwarp:stats` (cliente) — heartbeat de tráfico a 1Hz mientras está conectado.
- `outwarp:log` — cada línea nueva del `MemoryLogHandler`.
- `outwarp:settings` — cambio persistido de preferencias.
- `outwarp:clients` (servidor) — alguien hizo add/revoke.

### Persistencia de settings

`outwarp.api` guarda `settings.json` junto al `config.json` del usuario (`%APPDATA%\OutWarp\` o `~/.config/OutWarp/`). `outwarp_server.api` usa `gui_settings.json` dentro de `default_config_dir()`.

### Modo dev (VarB)

`settings.advanced = true` cambia la estética del shell: sidebar con borde duro y numeración monoespaciada, tarjetas con bordes mate, panel extra "Detalles técnicos" en Home (endpoint, fingerprint, allowed IPs). El shell respeta los design tokens de `styles.css`, así que el toggle no requiere recargar.

---

## Notas para futuras sesiones

- El directorio hermano `C:\Users\ferra\Documents\wstunnel_10.5.2_windows_amd64.tar\script portable\` contiene el script PowerShell original. Úsalo como referencia funcional (flujo de reconexión, estructura de menú, manejo de errores), pero **no** copies literales — la arquitectura Python es distinta.
- El autor prefiere iterar: no diseñar todo de golpe. El orden seguido fue: cliente Windows end-to-end → Linux → servidor. macOS queda descartado.
- Antes de publicar el repo (privado primero, público después): revisar que no queden referencias a `vpn.fcrespo.tech`, `ClaveSegura123`, `10.43.9.43`, `PortatilDesbloqueado` ni IPs específicas del autor.
