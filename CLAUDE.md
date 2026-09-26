# OutWarp

Herramienta multiplataforma (cliente + servidor) para levantar un túnel **WireGuard sobre WebSocket** usando [wstunnel](https://github.com/erebe/wstunnel) como transporte. Pensada para entornos donde UDP está bloqueado pero HTTPS/WebSocket pasa (redes corporativas, Wi-Fi cautivos, móvil tras CGNAT, etc.).

## Origen del proyecto

Nace como reescritura de un script PowerShell portable del autor que funcionaba solo en Windows y estaba atado a su servidor personal. Problemas del script original que OutWarp resuelve:

- **Valores hardcodeados en el código** (URL del servidor, IPs, secreto de upgrade, nombre del túnel).
- **Solo Windows**, PowerShell + WinForms. Frágil y difícil de mantener.
- **Sin wizard de configuración**: el usuario editaba el código.
- **Sin componente de servidor**: había que montar wstunnel a mano en el VPS.

> **El repo es público.** Nada personal del autor (rutas locales, dominios, IPs, secretos, detalles de su infraestructura) va a ficheros versionados. Ese contexto vive en `CLAUDE.local.md`, que está en `.gitignore` y solo existe en la máquina del autor.

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

**TUI Textual** (ya implementada): cliente y servidor exponen además `outwarp tui` / `outwarp-server tui`, una interfaz en terminal basada en [`textual`](https://textual.textualize.io/). Comparte el mismo `TunnelManager` / `ServerManager` que la GUI y el CLI headless, así que las tres rutas se cruzan sin duplicar lógica. La paleta TCSS replica los design tokens de `styles.css`; los glyphs son BMP-only (caja, bloques sparkline, formas, flechas) para correr en cualquier terminal — incluidos tmux, screen y SSH.

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
│   │   │   ├── app.jsx       # Shell interactivo cableado al Api (aspecto normal y "advanced")
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
├── docs/                     # RELEASE_SIGNING.md + history/ (auditorías ya resueltas, citadas desde el código)
├── e2e/                      # Prueba end-to-end en Docker (job `e2e` de CI)
├── deploy/                   # Kubernetes + guía Docker
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
- [x] Sin referencias a la infraestructura personal del autor en el código (la lista de literales a vigilar está en `CLAUDE.local.md`).

**Bloqueante** (cada punto = una rama y un PR; orden recomendado):

- [x] **Prueba end-to-end en CI, bloqueante.** *(Hecho 2026-09-15: `e2e/compose.yml` + `e2e/client.Dockerfile` + `e2e/run.sh`, job `e2e` en `ci.yml`. Pasa en local con Docker 29 / kernel 7.2; el primer run en el runner de GitHub confirma el spike de `wg-quick` en Docker.)* Cuarto job en `ci.yml` (solo Linux): dos contenedores Docker — `server` = la imagen real de `server/Dockerfile`, `client` = `python-slim` + `wireguard-tools` + wstunnel pinneado + wheel del cliente, como root (`platforms/linux.py` omite `sudo` con euid 0; helper vía `OUTWARP_HELPER`), ambos con `NET_ADMIN` + `/dev/net/tun`. Flujo: `add-client` → `import` (enrola por 443) → `connect` → handshake → `curl` a un HTTP que solo escucha en la IP de túnel del servidor + contadores de `wg show` suben → `ip route get 1.1.1.1` sale por `wg0` → token reutilizado rechazado → `disconnect` deja rutas e interfaz limpias. Cubre lo que se coló con CI en verde: B-017, B-018, B-019 y el drift de versión de wstunnel. No cubre Windows, systemd, k8s ni GUI (y se dice así en la doc). **Antes: spike de 1 h** para confirmar `wg-quick up` en Docker dentro de un runner de GitHub; si no funciona, plan B = network namespaces en el runner. Ficheros previstos: `e2e/compose.yml`, `e2e/client.Dockerfile`, `e2e/run.sh`.
- [x] **Kill switch + endpoint por hostname.** *(Hecho 2026-09-15: caché de última resolución (`outwarp/dnscache.py`, `resolved_hosts.json`) usada por `_resolve_endpoints` y `_resolve_bypass_networks` cuando el DNS falla; no se abre UDP/53 por el switch (fugaría el DNS de todas las apps). Límite conocido: si la IP del servidor cambia con el switch enganchado, hay que soltarlo.)* Con el kill switch enganchado, la reconexión resuelve el hostname por el DNS de la LAN, que está bloqueado → `FAILED` y el usuario sin red. Hay que decidir e implementar cómo se permite la resolución (UDP/53 a los resolvers mientras está enganchado, o resolver y cachear la IP antes de enganchar). Es un fallo en una feature de seguridad; no se firma "estable" con esto abierto.
- [x] **Renombrar el comando del cliente: `outwarp-cli` → `outwarp`.** *(Hecho 2026-09-15: `outwarp` es la entrada principal, `outwarp-cli` queda como alias deprecado hasta 1.0.0; `install.sh` migra unit/completions y `doctor` avisa de restos.)* Decisión del autor (2026-09-14): el cliente es lo que usa la mayoría y tiene que ser lo más fácil; el servidor ya lleva su sufijo (`outwarp-server`), así que el cliente no necesita ninguno. En Windows el ejecutable **ya** es `outwarp.exe` (`installer/windows/outwarp.iss`); solo Linux/pip arrastra `-cli` desde 0.5.0 (cuando `outwarp` era el binario de la GUI y se colapsó todo en uno). Tiene que ir **antes de 1.0** porque la superficie CLI se congela ahí. Plan:
  - `[project.scripts]` del cliente: `outwarp = "outwarp.cli:main"` como entrada principal; **mantener `outwarp-cli` una release como alias** que funciona igual y avisa una línea por stderr ("use `outwarp`"). Retirarlo en 1.0.0. Es una compatibilidad justificada: hay unidades systemd, `.desktop` y completions **en disco** en instalaciones existentes que apuntan al nombre viejo; el updater in-app (`updater.py`, `pip install` dentro del venv pipx) no las reescribe.
  - `service.py` (`ExecStart=`, `shutil.which`), `install.sh` (`CLIENT_BIN_LINK` vuelve a ser el link real, `.desktop` `Exec=`, completions bash/zsh, mensajes), `uninstall.py`, `diagnostics.py` (remedios), TUI/GUI (textos de ayuda, `FailedScreen`, settings), `updater.py`, `release.yml`/`release.sh`, `outwarp-client.spec` de PyInstaller (comprobar que el exe sigue siendo `outwarp.exe`), README, CHANGELOG, `docs/RELEASE_SIGNING.md`, y este fichero. ~220 referencias en ~45 ficheros: hacerlo con `grep`, no de memoria, y revisar `bundle.js` regenerado.
  - `service install` y `install.sh` tienen que **migrar** una unit/`.desktop`/completions existentes al nombre nuevo al actualizar (idempotente), y `doctor` avisar si aún apuntan a `outwarp-cli`.
  - Tests: `test_cli.py`, `test_service.py`, `test_wheel_contents.py` (los dos entry points presentes durante la release de transición; solo `outwarp` después).
- [~] **Cliente Linux con GUI de primera clase, no solo TUI.** *(Código hecho 2026-09-15: `install.sh` ofrece la GUI por defecto en sesión de escritorio, `sudo outwarp gui --install` la añade después, `outwarp ui gui|tui` elige lo que abre el lanzador (`outwarp launch`), `doctor` check `gui`. Pendiente: probar tray + ventana en X11 (GNOME/KDE) y Wayland (Hyprland, GNOME) en máquina real.)* Hoy la GUI pywebview en Linux es opt-in (`install.sh` → `OUTWARP_CLIENT_GUI=1`, extra `gui-linux`; `app.py` la excluye por marker PEP 508). Criterio: en una sesión de escritorio (`$WAYLAND_DISPLAY`/`$DISPLAY`) el instalador ofrece la GUI por defecto y la TUI sigue siendo el camino headless; `outwarp gui` arranca sin pasos manuales; tray + ventana probados en X11 (GNOME/KDE) y Wayland (Hyprland, GNOME); `doctor` comprueba las deps de GUI y el backend del tray; README/`install.sh --help` lo documentan. Propuesta técnica (a confirmar al implementar): mantener el marker y el extra `gui-linux` (los wheels Linux no arrastran webkit2gtk) y cambiar el **default del instalador**, no el `pyproject`.
- [~] **Compatibilidad total con Omarchy** *(2026-09-15, verificado en vivo en la Omarchy 4 del autor: tray SNI con icono por estado en omarchy-shell (Omarchy 4 no usa waybar/mako sino omarchy-shell/Quickshell; notificaciones con icono vía notify-send), ventana GTK nativa Wayland con `app_id` `outwarp` flotante 1080×720 por regla Lua instalada en `~/.config/hypr/outwarp.lua`, XDG autostart honrado por uwsm, `doctor` con checks `tray`/`hyprland`, CI con 3.14. Pendiente: probar `install.sh` completo en una Omarchy limpia y el kill switch nftables allí.)* (Arch Linux + Hyprland/Wayland + waybar + mako + systemd + pacman). **No es solo que instale: es que, una vez instalado, se sienta parte del sistema** (petición literal del autor: "que salga arriba con los iconos y se integre bien una vez instalado"). Criterio de aceptación, verificado en una instalación limpia de Omarchy:
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
*Añadidos por el autor el 2026-09-25:*

- [ ] **Sin bugs 🔴 abiertos en `KNOWN_BUGS.md`.** Ningún bug marcado 🔴 en "Abiertos" el día del release (hoy: B-023, servicio WG del cliente Windows en `Automatic`). Los hallazgos de la auditoría parcial de 0.14.0 (ver "Estado actual") se pasan a `KNOWN_BUGS.md` con su severidad, en vez de vivir en una memoria de sesión, para que este criterio los cubra.
- [ ] **Activar/desactivar clientes desde el dashboard.** Estado `disabled` **reversible**, distinto de `revoked` (definitivo, soft delete de CONCEPTO-D): el peer sale de `wg0.conf` (hot-reload) mientras está desactivado, pero conserva nombre, IP, claves, PSK y expiración; reactivarlo lo devuelve sin reenrolar ni redistribuir `.owcfg`. En las cuatro superficies: GUI del servidor, panel web, TUI y CLI (`outwarp-server disable-client` / `enable-client`, nombres a confirmar). Va antes de 1.0 porque añade subcomandos y un valor de `state` que se congelan.
- [ ] **Estudio: handshakes y cortes en escritorio remoto.** Investigar si la frecuencia de handshakes corta sesiones largas tipo RDP y, si procede, bajarla. Contexto para quien lo coja: el rekey de WireGuard cada ~120 s (`REKEY_AFTER_TIME`) es del protocolo, no configurable en `wireguard-tools`, y por sí solo no corta sesiones TCP internas; lo que sí es nuestro es `PersistentKeepalive = 25` (`client/outwarp/wireguard.py`), `--websocket-ping-frequency 25s` (`fallback.py`), el watchdog/reconexión de wstunnel, timeouts de inactividad de proxies intermedios y el head-of-line blocking de TCP. Entregable: reproducir con una sesión RDP real, medir (logs del watchdog, `wg show latest-handshakes`, captura), identificar la causa y decidir el cambio. Si el resultado toca el `.owcfg` o `config.json`, tiene que entrar antes de 1.0.
- [ ] **Pulido general de UI/UX.** Pasada de coherencia y acabado en GUI cliente, GUI servidor, panel web y TUIs (estados vacíos/error, textos, i18n — hay strings en español fijo en la GUI —, accesibilidad, paridad de funciones entre superficies).
- [x] **Login del dashboard más cómodo.** *(Hecho 2026-09-26 — decisión del autor: se queda el token de admin, sin usuario/contraseña, passkeys ni acceso por el túnel.)* Dos arreglos: (A) "Mantener la sesión" funcionaba mal por partida doble — la cookie no llevaba `Max-Age` (el navegador la borraba al cerrarse) y las sesiones vivían solo en memoria (cualquier reinicio del panel echaba al admin). Ahora `SessionStore` persiste en `panel_sessions.json` (0600, solo `sha256(session id)`), cada sesión va atada al token vigente (rotarlo con `admin-token --rotate` las mata todas) y la cookie dura 30 días con la casilla marcada. (B) El formulario de login lleva `username` fijo + `autocomplete="current-password"` para que navegador y gestores de contraseñas guarden y rellenen el token. Opciones evaluadas y descartadas por ahora: acceso sin login para clientes admin dentro del túnel, enlace de un solo uso por CLI, usuario+contraseña+TOTP, passkeys (no funcionan con IP ni cert autofirmado).
- [ ] **Servidor Windows vía Docker como camino recomendado.** Documentar el despliegue en Windows con Docker Desktop (backend WSL2) usando la imagen de `server/Dockerfile`, con un `compose.yml` listo para arrancar el servicio (volumen de config, `NET_ADMIN`, `/dev/net/tun`, puerto 443) y la guía en `deploy/README.md`. El SCM nativo queda como alternativa. La imagen ya se publica en `ghcr.io` (`docker-publish.yml`): verificar que el paquete es público/descargable sin login cuando el repo lo sea y referenciarla en la guía.
- [ ] **Varios perfiles en un mismo cliente (no simultáneos).** Sale de "NO bloqueante": cambia la forma de `config.json` (store `profiles/` con un fichero por perfil + perfil activo), que se congela en 1.0. Selector en GUI, tray, TUI y CLI (`outwarp profile list|use|remove`, a confirmar), migración idempotente del layout de un solo perfil, un solo túnel activo a la vez (cambiar de perfil desconecta el actual). Los stubs `list_profiles`/`set_active_profile`/`remove_profile` de `api.py` ya existen. Ver `ROADMAP.md` → "Multi-profile support".
- [ ] **Interfaz en 5 idiomas: inglés, chino mandarín (simplificado), español, francés y portugués.** Decisión del autor (2026-09-25), no solo español e inglés. Cubre GUI cliente/servidor (`STR`/`SRV_STR` en `shared.jsx`/`srv-data.jsx`), panel web, TUIs, mensajes de CLI y notificaciones, con selección automática por idioma del sistema y selector manual. Implica: sacar a i18n los strings hoy fijos; fuentes de respaldo para chino, porque Geist no tiene glifos CJK; en las TUIs, anchura doble de CJK; textos más largos en francés/portugués que no rompan layouts. Traducciones revisadas por un hablante nativo, no solo automáticas. Sale de "NO bloqueante" ("más idiomas").
- [ ] **Auditoría general justo antes de 1.0.** Cuando todo lo anterior esté en verde y sobre el commit candidato: seguridad, UI/UX, bugs y robustez, en cliente y servidor y en todas las plataformas. Los hallazgos van a `KNOWN_BUGS.md`; los críticos/altos se corrigen antes de publicar (criterio "sin bugs 🔴"), el resto se clasifica explícitamente como 1.x.
- [ ] **Release firmada y un ciclo sin hotfix.** 1.0.0 sale con `SHA256SUMS.txt.minisig` el mismo día (la clave está offline, en la máquina del autor; ver `docs/RELEASE_SIGNING.md`) y después de que la última 0.x lleve 2–4 semanas en producción (el pod k3s del autor) sin hotfix.

**Plan de ejecución** *(aprobado por el autor el 2026-09-26)*. Orden en que se ataca lo "Bloqueante". Cada fase cierra con una release 0.x publicada con el flujo borrador → firma → publicar. Hay tres reglas: primero va lo que se congela en 1.0; la infraestructura (tests, i18n) va antes del contenido; las traducciones van después del pulido, con los textos ya congelados. Los puntos *(añadido)* entraron con el plan y también son bloqueantes. 👤 = lo hace el autor (máquina real, firma, nativos).

- **Fase 0 — Base limpia → 0.15.0.**
  - Pasar la auditoría de 0.14.0 a `KNOWN_BUGS.md` y corregir los 🔴 y los altos. Hay una decisión del autor pendiente: DPAPI, que se implementa o se quita de la doc.
  - Vitest más la guardia de `bundle.js`.
  - Retirar el fallback sin firmar, tras comprobar que todas las releases desde 0.11.0 están firmadas.
  - *(añadido)* Seguridad del repo público: `SECURITY.md`, secret scanning y push protection, Dependabot, actions fijadas por SHA en los workflows de release, `pip-audit` en CI.
  - *(añadido)* 0.15.0 como ensayo del flujo de releases inmutables: el job de Windows adjunta los `.exe` al borrador y `publish-release.sh` funciona de principio a fin.
  - 👤 Confirmar B-024 en Windows real.
  - 👤 Empezar a medir el estudio de RDP.
- **Fase 1 — Lo que se congela → 0.16.0 (quizá también 0.17.0)**, en este orden:
  1. Activar y desactivar clientes, con un caso en el e2e.
  2. Infraestructura de i18n solo en/es: extraer los textos fijos, detección del idioma más selector, fallback a inglés, fuente CJK, anchura doble en las TUIs.
  3. Varios perfiles, con migración idempotente; revisar el kill switch, el sticky store, `dnscache` y `known_servers.json` por perfil.
  4. Estudio de RDP: decidir y aplicar. Si toca el `.owcfg` o `config.json`, entra aquí. *(añadido)* Evaluar también `bbr`, `fq` y `tcp_notsent_lowat` en el servidor Linux.
- **Fase 2 — Producto → 0.17.0/0.18.0.**
  - Pulido de UI/UX, que termina con los **textos congelados**.
  - Servidor Windows vía Docker; se puede hacer en paralelo con cualquier fase.
  - README y wizard honestos con el anti-DPI. El banner "not yet ready" se quita en la RC.
  - 👤 Pruebas reales de la GUI de Linux (X11/Wayland) y de una Omarchy limpia, que cierran los dos `[~]`.
- **Fase 3 — Idiomas → 0.19.0.**
  - zh-Hans, fr y pt.
  - *(añadido)* Test que falla si a un idioma le falta una clave.
  - *(añadido)* Capturas con Playwright usando los textos más largos.
  - 👤 Revisión por hablantes nativos.
- **Fase 4 — Congelación → 1.0.0-rc.1.**
  - *(añadido)* Referencia de los contratos (`.owcfg` v3, `config.json`, config del servidor, CLI) y **tests de contrato** en CI: snapshot de los subcomandos y flags, y esquemas JSON.
  - Retirar el alias `outwarp-cli`. *(añadido)* Revisar los shims de migración 0.x que quedan.
  - *(añadido)* Tests de actualización 0.x → 1.0 en el e2e: perfiles, base de clientes y updater.
  - *(añadido)* Smoke test del instalador Windows en CI: instalación silenciosa, `--version`, `doctor`, desinstalación.
  - Auditoría general sobre el commit de la RC; cada corrección crítica o alta saca una rc.N.
  - *(añadido)* Guía "Actualizar a 1.0" y CHANGELOG consolidado.
- **Fase 5 — 1.0.0.**
  - 👤 La última RC pasa 2–4 semanas en producción sin hotfix. Si hay hotfix, sale otra rc y el periodo vuelve a empezar.
  - Sin 🔴 abiertos y todas las casillas en verde.
  - 👤 Firma y publicación con `scripts/publish-release.sh`.

**NO bloqueante** (tentación de creer que sí; no reabrir):
- Certificado Authenticode para el instalador Windows: es dinero, no calidad. El aviso de SmartScreen se documenta en "Limitaciones conocidas".
- Split tunnelling, DDNS, auto-update del servidor, Prometheus: features; caben en 1.x sin romper nada. (Multi-perfil y "más idiomas" salieron de esta lista el 2026-09-25 por decisión del autor.)
- Cliente móvil: otro producto.

## Convenciones de código

- Python 3.11+, type hints obligatorios.
- `ruff` es el gate de lint del repo (no se corre `black`). Hay deuda de lint preexistente; no introducir violaciones nuevas.
- Docstrings solo cuando el "por qué" no sea obvio del nombre (regla estándar del repo).
- Sin comentarios inline triviales.
- Tests donde tenga sentido (lógica de config, parser de logs, abstracciones de plataforma mockeables).

## Estado actual

**Versión actual: `0.14.0`** (en código). El detalle de cada versión está en `CHANGELOG.md` (raíz); los bugs, abiertos y resueltos, en `KNOWN_BUGS.md`. Esta sección solo recoge lo que un agente necesita saber **hoy** para no romper decisiones ya tomadas.

- **Cliente**: Windows (instalador `.exe`, GUI pywebview + tray) y Linux (`install.sh`, GUI por defecto con escritorio, TUI y `outwarp` headless) completos.
- **Servidor**: Linux/systemd, Windows (SCM) y Docker/Kubernetes (`platforms/kubernetes.py`, `deploy/`).
- **macOS**: fuera de alcance.

### Decisiones de arquitectura vigentes (no deshacer sin motivo)

**Cliente**
- **Un solo dueño del túnel** (`client/outwarp/ownership.py`, `TunnelOwnerLock`): GUI, TUI, `connect` y `daemon` comparten el mutex/lock. Activar el servicio desde GUI/TUI es una cesión: la UI para su manager y pasa a visor (`service_managed`). La unit lleva `RestartPreventExitStatus=2 4`. Una segunda GUI en Windows pide a la primera que muestre su ventana (evento `Global\OutWarpClientShow`).
- **Qué escapa del túnel lo decide solo `routing.escape_set()`**: lo usan `build_wg_conf`, la escalera y el kill switch.
- **Kill switch** en `killswitch.py`, reconciliado desde `TunnelManager._set_state` (no desde la UI). Con hostname de endpoint usa la caché `dnscache.py`; no abre UDP/53.
- **Resolución antes de WireGuard** (`tunnel._with_addresses`): cada rung se resuelve antes de instalar WG; wstunnel marca la IP con SNI/Host = hostname (`connect_host`).
- **Escalera de fallback** (`fallback.py`): S0 directo → S1 DNS público → S2 proxy → S3 puertos alternativos → S4.. provisionados por el servidor; User-Agent de navegador en todos los directos; el rung ganador se recuerda por red (sticky store).
- **wstunnel se resuelve de forma perezosa** y se re-comprueba en cada `connect()`; si falta o está bloqueado (Defender / Smart App Control) → `TransportUnavailableError`, `FAILED` sin backoff.
- **`.owcfg` es entrada hostil**: todo campo se valida en `config._parse()` antes de llegar a un `.conf`, argv o fichero. Firmado con minisign (Ed25519) embebido; `profile_trust.py` verifica y hace pinning TOFU por endpoint (`known_servers.json`).
- **TLS**: `tls.verify` `pin` (fingerprint + SPKI) o `ca` (`--tls-verify-certificate` a wstunnel).
- **Enrolamiento**: el servidor no genera claves privadas. `add-client` emite un token de un solo uso (15 min); el cliente genera su par y canjea el token por el **mismo puerto del túnel** (forward TCP de wstunnel a `127.0.0.1:<enroll_port>`). Rate limit por token + techo global.
- En Linux el `.conf` del cliente vive en `/etc/wireguard-outwarp` (otros gestores escanean `/etc/wireguard`).
- `daemon`/`serve` salen con código 3 en `FAILED`/`ERROR`.
- Versión de wstunnel **pinneada** en `installer/wstunnel-version.txt`, con guardia anti-drift en `server/tests/test_wstunnel_version_pin.py`.
- **Releases inmutables** (ajuste del repo): una release publicada no admite cambios de assets ni de tag. `release.yml` / `release.sh` solo crean **borradores** (wheels + instaladores Windows vía `windows-installer.yml` como workflow reutilizable); el autor firma `SHA256SUMS.txt` y publica con `scripts/publish-release.sh`, que verifica assets, hashes y firma antes. Ningún agente publica una release. Detalle en `docs/RELEASE_SIGNING.md`.

**Servidor**
- `build_wstunnel_command()` es la **única** definición de la invocación de wstunnel (proceso y unit systemd).
- `tls_mode`: `self-signed` (por defecto, sin dominio) o `acme` (Caddy en el 443 con Let's Encrypt; OutWarp solo escribe `/etc/caddy/conf.d/outwarp.caddyfile`, nunca un Caddyfile ajeno).
- **Registro de clientes en SQLite** (`client_store.py`, `BEGIN IMMEDIATE`). `ClientEntry.state` `active`/`revoked` (revocar es soft delete); la expiración la aplica el servidor al regenerar `wg0.conf` y al arrancar.
- `ServerPlatform.reconcile()` prepara NAT/forwarding antes de instalar o reiniciar WG.
- `ServerManager.effective_state` reconcilia contra el SO cuando otro proceso lleva el servicio (pod k3s: `shareProcessNamespace: true`); `refresh_config()` recarga si otro proceso cambió la config.
- **Panel web**: token de admin (hash scrypt) + sesiones persistidas hasheadas en `panel_sessions.json`, atadas al token vigente.

### Pendiente conocido (auditoría parcial de 0.14.0, sin pasar aún a `KNOWN_BUGS.md`)

Cliente Windows: exe solo GUI, el desinstalador no suelta el kill switch, clave WG en claro frente al DPAPI prometido. Servidor: `wg_listen_port` desde el panel reinicia wstunnel con el `--restrict-to` viejo, `restart` en Windows, `restart` en Docker no-op, `run_setup` de la GUI incompleto en Linux. TUI: `k` sale en vez de desconectar. GUI: strings en español fijo.

### Pendiente para la primera versión estable

La lista vinculante está en **"Criterio de 1.0.0"** (sección Licencia). El instalador Windows sin firmar **no** bloquea.

El repo es **público**: https://github.com/fcrespo07/OutWarp

## Rendimiento

Speed test de referencia: Download 34.76 Mbps / Upload 24.16 Mbps. Ajustes ya en código:

1. **Connection pooling**: `--connection-min-idle 3` (`fallback.strategy_to_command`). Como WireGuard usa una sola sesión UDP, solo ahorra el handshake TLS al reconectar.
2. **MTU por perfil** (576–1500, default 1380): referencia WG sobre TCP/TLS ≈ 1500 − 40 IP/TCP − 40 TLS − 8 WS − 4 wstunnel − 28 WG. El 1420 típico es para WG sobre UDP y aquí fragmenta.

Revisado 2026-09-25: ningún ajuste perjudica la latencia. Posibles mejoras (no aplicadas): `bbr` + `fq` + `tcp_notsent_lowat` en el servidor Linux para la latencia con la línea cargada, y un escalón UDP directo cuando la red lo permite.

## UI (pywebview + React)

```
cliente:  pystray ── "Abrir" ──► pywebview window (file://ui/index.html)
                                       │  window.pywebview.api.<método>
                                       │  window.addEventListener('outwarp:<event>', …)
                                       ▼
                                  outwarp.api.Api ──► TunnelManager (tunnel.py)

servidor: idéntico, con outwarp_server.api.Api ──► ServerManager; el mismo UI se sirve también como panel web (web_server.py)
```

Los `.jsx` se pre-compilan a `bundle.js` con `python scripts/build_ui.py` (esbuild vía `npx`); **hay que regenerarlo y commitearlo** tras editar cualquier `.jsx`.

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

### Modo avanzado

`settings.advanced = true` cambia la estética del shell: sidebar con borde duro y numeración monoespaciada, tarjetas con bordes mate, panel extra "Detalles técnicos" en Home (endpoint, fingerprint, allowed IPs). El shell respeta los design tokens de `styles.css`, así que el toggle no requiere recargar.

---

## Notas para futuras sesiones

- **El repo es público.** Antes de commitear, que no entre nada personal del autor (rutas, dominios, IPs, secretos, su infraestructura); los datos de ejemplo usan `203.0.113.x` / `vpn.example.com`. Lo personal va en `CLAUDE.local.md` (ignorado por git).
- El autor prefiere iterar: no diseñar todo de golpe.
- Trabajo en ramas de vida corta: se borran al mezclarse.
