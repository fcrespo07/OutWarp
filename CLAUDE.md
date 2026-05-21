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
- Linux (distros con systemd)

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

**Versión TUI futura**: hay un acuerdo de hacer una segunda versión del cliente como TUI (probablemente con [`textual`](https://textual.textualize.io/)) cuando la versión GUI sea estable. Encajaría como cliente alternativo del mismo `TunnelManager` — la lógica de túnel ya está separada de la UI y puede compartirse. (Ya existe `outwarp-cli`, un cliente headless por consola para Linux sin escritorio.)

### Servidor

- Wizard CLI interactivo (`rich` + `prompt_toolkit`) — sigue siendo el flujo recomendado en VPS headless (`sudo outwarp-server setup`).
- Wizard GUI con la misma estética que el cliente (pywebview + HTML) en `outwarp-server-gui` para administradores con escritorio.
- Instalación como servicio nativo: **systemd** (Linux) y **Windows Service Manager** (Windows). También despliegue **Docker/Kubernetes** vía manifests.
- Genera un `.owcfg` por cliente, listo para importar.

## Arquitectura

```
OutWarp/
├── client/
│   ├── outwarp/
│   │   ├── app.py            # Entry point: crea Api, abre pywebview, arranca tray
│   │   ├── api.py            # Clase Api expuesta como window.pywebview.api
│   │   ├── cli.py            # outwarp-cli (cliente headless para Linux)
│   │   ├── tray.py           # pystray + menú contextual
│   │   ├── tunnel.py         # Gestión del proceso wstunnel + watchdog + reconexión
│   │   ├── wireguard.py      # Fachada WireGuard (delega en platforms/)
│   │   ├── network.py        # TCP probe + TLS fingerprint pinning
│   │   ├── config.py         # Schema + I/O del .owcfg / config.json
│   │   ├── logs.py           # Logger + rotación + MemoryLogHandler
│   │   ├── uninstall.py      # outwarp-uninstall CLI
│   │   ├── ui/               # HTML/JS de la UI (Claude Design)
│   │   │   ├── index.html    # Carga react + scripts (bundle JSX pre-compilado)
│   │   │   ├── app.jsx       # Shell interactivo cableado al Api
│   │   │   ├── var-a.jsx     # Variante "consumer" del diseño (referencia)
│   │   │   ├── var-b.jsx     # Variante "developer/instrument" (referencia)
│   │   │   ├── shared.jsx    # i18n (STR) + atoms (Btn/Pill/StatusDot/Toggle)
│   │   │   ├── brand.jsx     # Logo + wordmark "OutWarp"
│   │   │   └── styles.css    # Design tokens (light/dark)
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
│   │   ├── cli.py            # outwarp-server (rich CLI)
│   │   ├── server_app.py     # outwarp-server-gui (pywebview)
│   │   ├── api.py            # Clase Api del lado servidor
│   │   ├── server_manager.py # ServerManager (start/stop/add-client/revoke)
│   │   ├── server_tray.py    # Tray del modo GUI
│   │   ├── setup_wizard.py   # Wizard rich del CLI
│   │   ├── crypto.py         # TLS cert self-signed + fingerprint + WG keypairs
│   │   ├── ip_pool.py        # Asignación de IPs del pool de clientes
│   │   ├── wireguard.py      # build_server_wg_conf + add/remove peer (hot-reload)
│   │   ├── owcfg.py          # build_owcfg / write_owcfg
│   │   ├── ui/               # HTML/JS del servidor (Claude Design)
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

**OutWarp** se distribuye bajo **MIT**. Confirmar antes de publicar la primera versión estable.

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

### Marcas registradas

- **"WireGuard"** es trademark de Jason Donenfeld. No usar en el nombre del proyecto ni para implicar endorsement.
- **"wstunnel"** — misma restricción (BSD-3-Clause cláusula 3). Por eso el proyecto se llama OutWarp.

### Checklist antes de publicar la primera versión estable

- [ ] Confirmar licencia MIT (o cambiar a Apache-2.0 si se esperan contribuciones corporativas).
- [ ] Añadir fichero `LICENSE` en la raíz con el texto MIT.
- [ ] Añadir fichero `THIRD_PARTY_LICENSES` con BSD-3-Clause de wstunnel + LGPL-3.0 de pystray + BSD-3-Clause de pywebview.
- [x] Verificar que no queden referencias a `vpn.fcrespo.tech`, `ClaveSegura123`, `10.43.9.43`, `PortatilDesbloqueado` ni IPs del autor. *(El código está limpio; las únicas menciones viven en este checklist.)*
- [ ] Firmar el instalador Windows (eliminar warnings de SmartScreen/UAC en primer arranque).

## Convenciones de código

- Python 3.11+, type hints obligatorios.
- `ruff` es el gate de lint del repo (no se corre `black`). Hay deuda de lint preexistente; no introducir violaciones nuevas.
- Docstrings solo cuando el "por qué" no sea obvio del nombre (regla estándar del repo).
- Sin comentarios inline triviales.
- Tests donde tenga sentido (lógica de config, parser de logs, abstracciones de plataforma mockeables).

## Estado actual

**Versión actual: `0.1.4`** (en código; instaladores `.exe` publicados de 0.1.0 a 0.1.4, tags hasta `v0.1.2`). El proyecto pasó de las fases de scaffolding a **releases versionados y bugfixing post-lanzamiento** (~130 commits en `main`).

### Cliente

- **Windows**: ✅ completo y en producción. Instalador `.exe` (PyInstaller + Inno Setup) que bundlea WireGuard for Windows y `wstunnel.exe`. GUI pywebview + tray.
- **Linux**: ✅ completo, validado end-to-end. `install.sh` con bootstrap (detecta/instala Python, crea venv, recrea venv corrupto, registra systemd unit). Incluye `outwarp-cli` headless para máquinas sin escritorio.
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

- ❌ Faltan los ficheros `LICENSE` y `THIRD_PARTY_LICENSES` en la raíz (ver checklist de licencias).
- ⚠️ Instalador Windows sin firmar → warnings de SmartScreen/UAC en primer arranque.
- ⚠️ README aún marcado como "under active development, not yet ready for production".
- ✅ Sin referencias del autor (`vpn.fcrespo.tech`, `ClaveSegura123`, etc.) en el código.

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
