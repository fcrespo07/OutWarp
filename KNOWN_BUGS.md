# Bugs conocidos — OutWarp

Catálogo vivo de bugs detectados durante el desarrollo, con su estado, causa raíz, fix aplicado y notas para no repetirlos.

Leyenda de estado:

- ✅ Resuelto
- 🟡 Resuelto parcialmente / pendiente verificar
- 🔴 Abierto, bloquea 1.0 (crítico o alto)
- 🟢 Abierto, menor: no bloquea, planificado

---

## Resueltos

### ✅ B-001 — `uninstall` no existía y faltaban métodos en la ABC de plataforma
**Síntomas:** No había forma limpia de revertir `setup`. La interfaz `ServerPlatform` tampoco exponía la operación.
**Causa raíz:** Comando y métodos no implementados.
**Fix:** Añadido `_cmd_uninstall` con confirmación + `uninstall_wg_config()` y `uninstall_wstunnel_service()` en la ABC y en `LinuxServerPlatform`. (commit `5376bed`)
**Prevención:** Cuando se añade un `setup`/`install`, planificar el inverso desde el principio y cubrirlo con tests.

### ✅ B-002 — Wizard del servidor moría con `EOFError` al lanzarse vía `curl | bash`
**Síntomas:** Al usar el one-liner, el primer `input()` del wizard recibía EOF y abortaba.
**Causa raíz:** `stdin` del proceso era el contenido del pipe, no el TTY del usuario.
**Fix:** El instalador lanza el wizard con `</dev/tty` para reabrir entrada interactiva. (commit `802e80e`)
**Prevención:** Cualquier wizard interactivo invocado desde un instalador `curl|bash` debe redirigir explícitamente a `/dev/tty`.

### ✅ B-003 — `ModuleNotFoundError` ejecutando `warpsocket-server` como usuario no-root
**Síntomas:** Tras `sudo install.sh`, el binario fallaba al importarse para usuarios distintos de root.
**Causa raíz:** Instalación editable (`pip install -e`) dejaba el código en `/root/WarpSocket` (perms 700), inaccesible para otros usuarios. El symlink en `/usr/local/bin` apuntaba a un venv que cargaba `sys.path` desde esa ruta.
**Fix:** El instalador usa `pip install` sin `-e` (copia los paquetes al venv). (commit `3977d75`)
**Prevención:** Nunca usar instalación editable para deploys de producción cuando el repo de origen vive en un home con permisos restrictivos.

### ✅ B-004 — Cliente Windows: `route add` requería elevación, fallaba silencioso
**Síntomas:** El cliente arrancaba sin admin, no podía añadir la ruta de bypass al endpoint y la conexión moría.
**Causa raíz:** `route add` en Windows necesita admin. La app no se auto-elevaba.
**Fix:** `_ensure_elevated()` en `app.py` que detecta falta de admin y relanza vía `ShellExecuteW("runas", ...)`. (commit `2364894`)
**Prevención:** Toda operación que toque la tabla de rutas o servicios del SO debe verificarse al arranque de la app y forzar elevación si falta.

### ✅ B-005 — Servidor: clientes WG conectados pero sin internet
**Síntomas:** El handshake WireGuard funcionaba, los pings al servidor también, pero el cliente no salía a internet.
**Causa raíz:** Faltaba `net.ipv4.ip_forward=1` persistente y reglas iptables NAT MASQUERADE / FORWARD.
**Fix:** `build_server_wg_conf` añade `PostUp`/`PostDown` con sysctl + iptables, y el wizard escribe `/etc/sysctl.d/99-warpsocket.conf` para persistencia. (commit `8285ec7`)
**Prevención:** Para cualquier servidor WireGuard que actúe de gateway, verificar siempre los tres ingredientes: ip_forward, FORWARD ACCEPT y NAT POSTROUTING.

### ✅ B-006 — Visor de logs roto en el cliente (thread-safety tkinter/pystray)
**Síntomas:** Click en "Ver logs" desde el menú del tray congelaba la app o no abría nada.
**Causa raíz:** pystray ejecuta callbacks en su propio thread; tkinter sólo admite operaciones desde el thread principal.
**Fix:** Patrón cola + polling — los callbacks del tray hacen `ui_queue.put(...)` y un `root.after(50, _pump_ui_queue)` consume desde el main thread. Tray usa `run_detached()` para no bloquear el loop principal. (commits `e664a8f`, `f016b71`)
**Prevención:** Cualquier integración tray ↔ tkinter debe pasar por una cola; nunca llamar widgets directamente desde callbacks de pystray.

### ✅ B-007 — `add-client` escribía `wg0.conf` en el path equivocado
**Síntomas:** Tras `add-client`, el peer no aparecía en WireGuard hasta editar a mano.
**Causa raíz:** El comando escribía la conf en `/etc/warpsocket/` en vez de delegar en `platform.install_wg_config()`, que sabe que la ruta correcta es `/etc/wireguard/wg0.conf`.
**Fix:** `add-client` y `revoke-client` ahora llaman a `platform.install_wg_config()`. (commit `f016b71`)
**Prevención:** Nunca duplicar paths del SO en `cli.py`; toda escritura de configuración del sistema pasa por el módulo `platforms/`.

### ✅ B-008 — `list-clients` no mostraba estado en vivo
**Síntomas:** Sólo listaba nombre/IP del fichero de config, sin saber quién está realmente conectado.
**Causa raíz:** Faltaba parsear `wg show wg0 dump`.
**Fix:** Añadido `LivePeer` + `get_live_peers()` y nuevas columnas (online/offline/idle, último handshake, RX/TX). (commit `8da9432`)
**Prevención:** Para cualquier comando "list" sobre un servicio runtime, separar siempre estado declarado (config) de estado real (runtime).

### ✅ B-009 — Instalador Linux fallaba con `ensurepip is not available`
**Síntomas:** En sistemas con Python pero sin el paquete `pythonX.Y-venv`, `python -m venv` rompía.
**Causa raíz:** Las distros Debian/Ubuntu separan `venv` en su propio paquete y no lo incluyen con la build mínima de Python.
**Fix:** `ensure_python_venv()` valida `python -m venv --help` y, si falla, instala `pythonX.Y-venv` vía apt. (commit `4369aa0`)
**Prevención:** Detectar capacidades reales (probar el comando) en vez de asumir que `python` instalado implica venv funcional.

### ✅ B-010 — Comandos privilegiados crasheaban sin `sudo`
**Síntomas:** `add-client`/`revoke-client`/etc. lanzaban tracebacks crípticos al intentar escribir en `/etc/`.
**Causa raíz:** No se validaba EUID antes de ejecutar comandos que requieren root.
**Fix:** `_require_root()` + `_PRIVILEGED_COMMANDS` frozenset. Mensaje claro pidiendo `sudo`. (commit `658c623`)
**Prevención:** Cada comando que toca `/etc/` o servicios del SO debe declarar explícitamente que necesita root.

### ✅ B-011 — `uninstall` dejaba huérfanos (venv, symlink, sysctl drop-in)
**Síntomas:** Tras `uninstall`, `/opt/warpsocket-server`, `/usr/local/bin/warpsocket-server` y `/etc/sysctl.d/99-warpsocket.conf` seguían en disco.
**Causa raíz:** El comando sólo limpiaba la conf de WG y el unit de systemd.
**Fix:** `uninstall_wg_config()` borra el sysctl drop-in y reaplica `sysctl --system`; `_spawn_deferred_cleanup()` lanza un script bash separado que borra el venv y el symlink tras salir el proceso (no se puede borrar el venv que estás ejecutando). (commit `3516456`)
**Prevención:** Cuando un proceso se desinstala a sí mismo, la limpieza del propio binario tiene que diferirse a otro proceso.

### ✅ B-012 — Servidor Linux Mint pierde su propia conexión a internet tras `setup`
**Síntomas:** Al instalar WarpSocket en Mint (VirtualBox, Red NAT), la VM servidor pierde acceso a internet (no sólo el cliente: el propio servidor).
**Causa raíz confirmada:** Dos problemas combinados:
1. `wg-quick` con `Table = auto` (por defecto) modifica la tabla de rutas del kernel al levantar `wg0`, pudiendo dejar la ruta default inaccesible en setups con NetworkManager o VirtualBox NAT.
2. Las reglas `iptables -A FORWARD` se añadían al final de la cadena; si `ufw` tiene política DROP por defecto, su regla DROP precede a nuestro ACCEPT y bloquea el tráfico de forwarding del cliente (y en algunos setups también afecta al servidor).
**Fix:**
- Añadido `Table = off` en la sección `[Interface]` del servidor: wg-quick ya no toca la tabla de rutas; el routing lo gestiona iptables vía MASQUERADE. La ruta directa `10.0.0.0/24 dev wg0` la crea el kernel al asignar la IP a la interfaz.
- Cambiado `-A FORWARD` por `-I FORWARD 1` y `-I FORWARD 2` en PostUp: las reglas ACCEPT se insertan al principio de la cadena, antes de cualquier DROP de ufw u otras políticas.
- Añadida función `_configure_ufw_if_active()` en el wizard: si ufw está activo, abre el puerto wstunnel y pone `DEFAULT_FORWARD_POLICY="ACCEPT"` en `/etc/default/ufw`.
**Prevención:** Para cualquier servidor WG gateway: siempre `Table = off` + `-I` en lugar de `-A` para reglas FORWARD. El wizard debe detectar ufw automáticamente.

### ✅ B-013 — `list-clients` no refleja cambios entre ejecuciones rápidas
**Síntomas:** Tras conectar/desconectar un cliente, varias ejecuciones consecutivas devuelven el mismo estado.
**Causa raíz:** Comportamiento esperado de WireGuard. `wg show dump` devuelve el último handshake conocido. WireGuard renegocia sesiones cada ~2 minutos cuando hay tráfico, o cuando una sesión lleva ~3 minutos sin actividad. El threshold `_ONLINE_WINDOW_SECONDS = 180` refleja este TTL: un peer no puede marcarse como "offline" en menos de 3 minutos desde el último handshake porque WireGuard mantiene la sesión abierta ese tiempo.
**No hay fix de código**: es una limitación de la API de WireGuard. El estado se actualiza dentro de la ventana de 3 minutos para peers con tráfico activo.
**Prevención:** Documentar en `--help` de `list-clients` que el estado offline puede tardar hasta 3 minutos en reflejarse.

### ✅ B-014 — Cliente Windows: la auto-elevación no dispara UAC
**Síntomas:** Pese a `_ensure_elevated()`, ejecutando como usuario no-admin la app arranca sin pedir UAC y luego falla en `route add`.
**Causa raíz:** Cuando pip instala el entry point en Windows, crea `warpsocket.exe` en `Scripts/`. Al ejecutarlo, `sys.argv[0]` apuntaba a ese `.exe`, pero el código usaba siempre `sys.executable` (python.exe) + script path. Llamar a `ShellExecuteW("runas", "python.exe", "warpsocket.exe")` relanzaba Python sin los argumentos correctos para activar la app.
**Fix:** Añadida detección del caso pip entry point: si `sys.argv[0].endswith(".exe")`, se relanza ese `.exe` directamente elevado con `params=None`. Tres ramas: PyInstaller (frozen), pip .exe, y python directo.
**Prevención:** Cualquier app con auto-elevación en Windows debe distinguir los tres casos de arranque (frozen / pip exe / python script) explícitamente.

### ✅ B-015 — Botón "Ver logs" sigue sin abrir nada en Windows
**Síntomas:** Tras el fix de thread-safety (B-006), el botón sigue sin responder en algunos casos.
**Causa raíz:** Dos problemas:
1. Múltiples clicks abrían ventanas huérfanas sin enfocar porque la ventana previa podía seguir abierta pero no visible (detrás de otras).
2. `CTkToplevel` en algunas versiones de customtkinter/Windows no se renderiza correctamente si el root no ha procesado sus primeras tareas de idle (`update_idletasks` no llamado antes de crear la ventana hija).
**Fix:**
- Singleton: `_log_window` dict en módulo guarda referencia a la ventana activa; si ya existe y `winfo_exists()` devuelve True, se hace `deiconify()` + `lift()` + `focus_force()` en vez de abrir otra.
- Llamada a `root.update_idletasks()` antes de crear `CTkToplevel`.
- `win.deiconify()` explícito tras crear la ventana para garantizar que no arranque minimizada.
**Prevención:** Toda ventana secundaria en una app de bandeja debe ser singleton con mecanismo de re-raise.

### ✅ B-016 — Cliente Windows: WireGuard no se cierra del todo al desconectar
**Síntomas:** Tras pulsar "Salir" (o reconectar), el túnel WireGuard queda visible en WireGuard for Windows o el servicio sigue apareciendo activo en `sc query`. Los reintentos de conexión fallaban en `tcp_probe` porque el adaptador WG (con `AllowedIPs=0.0.0.0/0`) seguía activo cuando ya se había borrado la ruta de bypass.
**Causa raíz:** Tres problemas combinados en `platforms/windows.py`:
1. `wireguard.exe /uninstalltunnelservice <name>` es **asíncrono**: el proceso retorna inmediatamente pero el SCM sigue parando el servicio en background. `disconnect()` no esperaba a que desapareciera.
2. El fichero `.conf` en `%LOCALAPPDATA%\WarpSocket\wireguard\<name>.conf` **no se borraba** tras el uninstall. WireGuard for Windows lo detecta y lo lista como "tunnel disponible" aunque el servicio esté parado.
3. Sin polling posterior, la ruta de bypass se borraba mientras el adaptador WG aún enrutaba tráfico → `tcp_probe` fallaba en el siguiente intento.
**Fix:** `uninstall_wg_tunnel` ahora hace polling de `sc query WireGuardTunnel$<name>` tras el uninstall (timeout 8 s, polling 250 ms) y borra el `.conf` una vez confirmado que el servicio ha desaparecido. Warning en log si se agota el timeout.
**Prevención:** Cualquier operación con SCM de Windows debe asumir asincronía y esperar confirmación explícita antes de modificar rutas o ficheros dependientes.

### ✅ B-017 — wstunnel muere <1 segundo: no verifica cert auto-firmado correctamente
**Síntomas:** El log del cliente muestra "Starting wstunnel" seguido de "Tunnel died unexpectedly" ~700 ms después. El servidor no registra ninguna conexión WebSocket tras el fingerprint check. Los reintentos fallan en `tcp_probe` (B-016 cascada).
**Causa raíz:** wstunnel valida el certificado TLS del servidor contra el CA store del sistema operativo. El certificado auto-firmado generado por el wizard no está en ningún CA store → wstunnel sale inmediatamente con error de verificación TLS.
**Fix:** Añadido `--dangerous-disable-certificate-verification` al comando de wstunnel en `build_wstunnel_command`. La seguridad de identidad del servidor la proporciona el pinning SHA-256 (`verify_tls_fingerprint`) que se ejecuta antes de arrancar wstunnel, por lo que omitir la validación CA de wstunnel no introduce vulnerabilidades adicionales.
**Prevención:** Al integrar cualquier binario externo que haga TLS, verificar siempre cómo gestiona certs auto-firmados. No asumir que el flujo Python y el binario heredan la misma configuración de confianza TLS.

### ✅ B-018 — Enrolamiento imposible: el listener estaba en un segundo puerto público, y en Linux/systemd nadie lo arrancaba
**Síntomas:** Todo perfil de enrolamiento (el formato por defecto desde 0.11.0) fallaba al importar con "Could not reach the enrolment endpoint"; `list-clients` mostraba clientes en "enrolment expired". En el despliegue k3s real: 443 reenviado, ningún peer con handshake en 17 h. `doctor` en verde.
**Causa raíz:** Dos problemas: (1) en la rama autofirmada el listener (`enroll_server.py`) escuchaba en `0.0.0.0:8444` con su propio TLS: un segundo puerto que ni `deploy/README.md`, ni el configmap, ni el panel, ni `doctor` mencionaban, y que ningún router doméstico tenía abierto; (2) en la instalación Linux con systemd el listener solo existía dentro de `ServerManager._do_start()`, que solo `serve`/GUI/Windows mantienen vivo — el wizard escribe las units de wstunnel y wg-quick y sale, así que nada lo ejecutaba jamás.
**Fix:** El listener solo escucha en loopback (HTTP plano) y el cliente lo alcanza como forward TCP de wstunnel por el propio puerto del túnel (`--restrict-to 127.0.0.1:<enroll_port>` además del de WireGuard; `.owcfg` v4 con `enrollment.remote_port`). En Linux, nueva `outwarp-enroll.service` (setup/restart/uninstall/status/doctor). Verificado e2e con el wstunnel 10.5.2 real (`server/tests/test_enroll_transport_e2e.py`).
**Prevención:** Cualquier superficie que un cliente deba alcanzar "antes del túnel" tiene que (a) ir por el puerto que ya está abierto y (b) tener un supervisor en **cada** plataforma (`ServerPlatform.manages_enroll_service`). `doctor` debe cubrirla: un check verde con enrolamiento imposible es lo que ocultó esto.

### ✅ B-019 — DNS del túnel y ping de verificación fuera del túnel
**Síntomas:** Con el túnel "conectado", los nombres no resolvían en redes hostiles (o resolvían por fuera, a la vista de la red); un servidor sin NAT (B-005) aparecía como conectado con tráfico.
**Causa raíz:** Desde 0.12.1 `escape_set()` excluía `1.1.1.1` de `AllowedIPs` para que el rung `direct-hostile` pudiera resolver el endpoint con WG ya instalado. Pero `1.1.1.1` es también el DNS por defecto de todo perfil (`owcfg.py`) y el destino del ping "handshake pero sin tráfico por el túnel" (`Tunnel._await_ping`). Fuga de DNS + verificación que nunca podía fallar.
**Fix:** `tunnel._with_addresses()` resuelve cada rung (resolver del sistema; `1.1.1.1` en crudo para los rungs hostiles; también el host del proxy) **antes** de levantar WG y le pasa a wstunnel la IP con `--tls-sni-override`/`Host:` = hostname (comprobado en el fuente de wstunnel 10.5.2: el SNI override es el `ServerName` contra el que rustls verifica). `escape_set()` excluye las IPs resueltas, no el resolver.
**Prevención:** Nada que vaya en `AllowedIPs`/allowlist del kill switch puede coincidir con un destino que **debe** ir por el túnel. Un test lo fija (`test_the_tunnel_dns_and_the_verification_ping_stay_inside_the_tunnel`).

### ✅ B-020 — `outwarp-cli daemon` y `outwarp-server serve` se rendían sin salir
**Síntomas:** Portátil arrancado antes de tener Wi-Fi: sin túnel hasta reiniciar la unit a mano. Pod/contenedor con wstunnel muerto: proceso vivo, nada escuchando, solo el liveness probe (si coincidía el puerto) lo reiniciaba.
**Causa raíz:** Ambos esperaban en un `Event` que solo una señal ponía; `FAILED`/`ERROR` no lo tocaban → `Restart=on-failure` y la restart policy nunca actuaban.
**Fix:** Salida con código 3 en `FAILED`/`ERROR`. El daemon solo notifica una conexión **perdida** (no un fallo de arranque) y, con kill switch activado, no libera al arrancar la regla que dejó la ejecución anterior.
**Prevención:** Un proceso supervisado que ha llegado a un estado terminal debe **salir**: idle ≠ vivo.

### ✅ B-021 — Panel web con estado congelado y botones que peleaban con el transporte
**Síntomas:** Clientes enrolados por el contenedor `serve` (o añadidos por `kubectl exec`) no aparecían, o seguían como "offline", hasta reiniciar el panel. "Parar" desde el panel tumbaba la VPN del contenedor `serve` (`wg-quick down`) sin que este se enterase; "Iniciar" después lanzaba un segundo wstunnel que moría por puerto ocupado.
**Causa raíz:** `Api` leía la config cargada al arrancar y nunca la recargaba; `ServerManager.stop()/start()` actuaban sobre un transporte que no era suyo.
**Fix:** `ServerManager.refresh_config()` (mtime de `server_config.json` y `clients.sqlite`); estado `pending` para slots sin clave; `get_status().service_control` (`full`/`restart`/`none`) y la API rechaza lo que no aplica.
**Prevención:** Cualquier surface "companion" (panel, GUI junto a systemd) debe asumir que el estado lo escriben otros procesos y que el transporte puede no ser suyo.

### ✅ B-022 — La gráfica de tráfico podía dejar de reflejar tráfico real tras un pico
**Síntomas:** Reproducido en vivo: un speed test genera un pico de tráfico y, minutos después, ver un vídeo (tráfico real, confirmado con `wg show wg0 transfer` subiendo) se dibujaba como una línea plana en el sparkline del cliente y en la gráfica de Home.
**Causa raíz:** El sparkline por cliente (`app.jsx`) y la gráfica de tráfico del Home (`AreaChart`, `dash-atoms.jsx`) escalaban su eje con un pico que decaía un 5% por muestra (2 s) sin límite ligado a la ventana visible. Cuanto mayor el pico, más tarda el decaimiento en caer por debajo del valor real actual — con un speed test contra un cliente normal, minutos. Mientras tanto, tráfico real pero menor se dibuja plano contra esa escala vieja.
**Fix:** `window.DSfmt.makeBoundedPeak` (`dash-data.jsx`): en vez de decaer sin límite, recuerda el máximo de las últimas N muestras del máximo de la ventana. El tiempo de recuperación queda acotado (ventana + memoria, ~66 s con los valores por defecto) **independientemente de lo grande que fuera el pico**, y sigue suavizando tráfico realista con ráfagas (vídeo/descargas) sin "respirar" — verificado con simulación numérica de ambos escenarios antes de aplicar el cambio.
**Prevención:** Cualquier "peak-hold" para escalar un eje debe tener una cota de memoria ligada al tamaño de la ventana que se muestra, nunca un decaimiento puramente exponencial sin límite — si no, el tiempo de recuperación crece con la magnitud del pico, que es exactamente el caso que un pico grande (una prueba de velocidad) hace peor.


### ✅ B-023 — Windows: el servicio del túnel queda en `Automatic` y WireGuard se levanta solo en el siguiente arranque
**Síntomas:** Tras apagar, suspender o reiniciar Windows con OutWarp conectado, en el arranque siguiente WireGuard aparece activo sin haber abierto OutWarp — incluso con "Iniciar al iniciar sesión" desactivado, y antes de iniciar sesión. `Get-Service *ireguard*` muestra:


**Causa raíz:** `wireguard.exe /installtunnelservice` registra el servicio del túnel con `StartType = Automatic` — es el comportamiento de wireguard-windows (`manager.InstallTunnel`), no un parámetro que OutWarp pase. `WindowsPlatform.install_wg_tunnel` lo invoca tal cual y nunca reajusta el tipo de arranque; el servicio sólo desaparece en `uninstall_wg_tunnel`, es decir, en un `disconnect()` limpio. Si el equipo se apaga con el túnel levantado, el servicio sobrevive registrado y el SCM lo arranca en el siguiente boot. Es un mecanismo **distinto** del autostart de la app (`HKCU\Software\Microsoft\Windows\CurrentVersion\Run`, ajuste `start_at_boot`): desactivar ese toggle no impide nada de esto, que es lo que hace el diagnóstico confuso.

**Impacto:** El adaptador WG queda activo con `AllowedIPs` ≈ `0.0.0.0/0` y `Endpoint = 127.0.0.1:<local_port>`, pero sin wstunnel escuchando en ese puerto: no hay handshake y, como el driver WireGuard-NT captura el tráfico antes de consultar la tabla de rutas (ver comentario en `_allowed_ips_excluding`), el equipo se queda efectivamente sin salida a internet hasta abrir OutWarp — que detecta el servicio stale, lo desinstala y lo reinstala — o parar el servicio a mano. Para el usuario esto se ve como "WireGuard se enciende solo y no tengo red".

**Mitigación (usuario):**

```powershell
# quitar el arranque automático sin cortar la conexión actual
Set-Service -Name 'WireGuardTunnel$OutWarp' -StartupType Manual

# o eliminar el servicio residual por completo
& "C:\Program Files\WireGuard\wireguard.exe" /uninstalltunnelservice OutWarp
```

Ambas son temporales: la siguiente conexión recrea el servicio y vuelve a dejarlo en `Automatic`.

**Fix propuesto:** en `client/outwarp/platforms/windows.py`, tras el `/installtunnelservice` correcto, forzar arranque bajo demanda. El servicio lo arranca siempre el propio `install_wg_tunnel` (que además ya limpia cualquier servicio stale antes de reinstalar), así que no se depende en ningún momento del autoarranque del SCM:

```python
# /installtunnelservice lo registra como Automatic: un túnel que quede
# instalado tras un apagado sucio vuelve solo en el siguiente boot, sin
# OutWarp y sin wstunnel debajo. Lo (re)instalamos y arrancamos nosotros en
# cada connect, así que demand start es suficiente.
_run(["sc.exe", "config", f"WireGuardTunnel${name}", "start=", "demand"])
```

Cubrirlo con un test en `client/tests/test_platforms.py`, con la misma estructura que los `test_windows_install_autostart_*`: verificar que la secuencia de llamadas incluye el `sc.exe config ... start= demand` después del install.

**Fix (2026-09-26):** `WindowsPlatform.install_wg_tunnel` ejecuta `sc config WireGuardTunnel$<name> start= demand` justo después de `/installtunnelservice` (un fallo solo se registra en el log, no aborta la conexión). Tests: `test_install_wg_tunnel_sets_demand_start_after_install` y `..._survives_demand_start_failure` en `client/tests/test_platforms.py`. Un servicio que ya esté en `Automatic` por una versión anterior se corrige en la siguiente conexión, porque se reinstala.
**Nota:** el servidor Windows (`server/outwarp_server/platforms/windows.py`) usa la misma llamada, pero allí el arranque automático **sí** es el comportamiento deseado — el fix es sólo para el cliente.

**Prevención:** Al delegar la creación de un servicio en un binario de terceros, no asumir su tipo de arranque por defecto. Si el ciclo de vida lo gestiona la app (instalar al conectar / desinstalar al desconectar), el servicio debe quedar en `demand`, para que un apagado sucio no lo convierta de facto en un servicio de arranque del sistema. Mismo razonamiento que B-016: el estado que deja el SCM sobrevive al proceso que lo creó.

### ✅ B-025 — Windows: cualquier usuario local podía leer la clave privada WireGuard del cliente
**Síntomas:** Hallazgo de la auditoría parcial de 0.14.0. Mientras el túnel está activo (y tras un cierre sucio, hasta la siguiente conexión) `C:\ProgramData\WireGuard\<túnel>.conf` contiene `PrivateKey` en claro, y la carpeta hereda de `C:\ProgramData` lectura para `Users`: cualquier cuenta del equipo, sin ser administradora, podía copiar la clave y suplantar al cliente. La documentación interna decía además que el `.conf` iba cifrado con DPAPI, y no era así.
**Causa raíz:** `install_wg_tunnel` creaba la carpeta y el fichero sin tocar su ACL.
**Fix (2026-09-26):** `WindowsPlatform._restrict_conf_dir()` (`client/outwarp/platforms/windows.py`) aplica a la carpeta, antes de escribir la clave, un DACL sin herencia con solo SYSTEM (el servicio del túnel) y Administradores (el cliente elevado), heredable por los ficheros (`icacls /inheritance:r /grant:r *S-1-5-18:(OI)(CI)F *S-1-5-32-544:(OI)(CI)F`, por SID porque los nombres se traducen). El `.conf` se borra y se vuelve a crear para que tome ese ACL aunque viniera de una versión anterior. Si `icacls` falla, no se escribe la clave y la conexión falla con `PlatformError`. DPAPI se descartó (decisión del autor): el servicio corre como SYSTEM, así que un blob cifrado por el usuario no le serviría, y uno con alcance de máquina lo puede descifrar cualquier proceso del equipo.
**Prevención:** `test_install_wg_tunnel_locks_conf_dir_before_writing_key` y `test_install_wg_tunnel_refuses_to_write_key_when_acl_fails` en `client/tests/test_platforms.py`.

### ✅ B-026 — Windows: desinstalar con el kill switch enganchado dejaba el equipo sin red
**Síntomas:** Hallazgo de la auditoría de 0.14.0. Si el cliente moría (crash, taskkill, apagón) con el kill switch activo y luego se desinstalaba OutWarp, la política de salida del firewall de Windows seguía en `Block`: el equipo se quedaba sin red y sin ningún OutWarp que lo deshiciera.
**Causa raíz:** `[UninstallRun]` de `installer/windows/outwarp.iss` solo paraba el servicio WireGuard del servidor. Nada restauraba el firewall ni quitaba las reglas `OutWarp-KillSwitch-*`, y el cliente, a propósito, no suelta un switch al arrancar si el ajuste está activo.
**Fix (2026-09-26):** el desinstalador ejecuta `Set-NetFirewallProfile -All -DefaultOutboundAction Allow` **solo si** queda alguna regla `OutWarp-KillSwitch-*` (una política puesta por el usuario no se toca), borra las tres reglas, quita el servicio `WireGuardTunnel$OutWarp` del cliente y borra `{commonappdata}\WireGuard\*.conf` (la clave, B-025).
**Prevención:** `client/tests/test_installer_iss.py` comprueba esas órdenes en el `.iss` y que los nombres de las reglas coinciden con `platforms/windows.py`. Pendiente: probarlo con el instalador real de 0.15.0.

### ✅ B-027 — Windows: `outwarp.exe` ignoraba sus argumentos, no había CLI
**Síntomas:** Hallazgo de la auditoría de 0.14.0. `outwarp.exe status`, `connect`, etc. abrían la GUI y no imprimían nada: en Windows no existía la CLI que documentan README y `--help`.
**Causa raíz:** `outwarp-client.spec` construía un único exe de subsistema GUI (`console=False`) cuyo punto de entrada (`__main__.py` → `app.main`) nunca leía `sys.argv`.
**Fix (2026-09-26):** el mismo esquema que el servidor: `outwarp-gui.exe` (GUI, `uac_admin`, `outwarp/gui_main.py`) y `outwarp.exe` de consola (`asInvoker`, `outwarp.cli:main`) compartiendo `_internal`. Compatibilidad: `outwarp.exe` sin argumentos lanza `outwarp-gui.exe` (accesos directos viejos); la GUI reescribe al arrancar una entrada de autoarranque que aún apunte a `outwarp.exe`; los accesos directos del instalador apuntan a la GUI; `outwarp uninstall` ya no mata con `taskkill` el proceso que lo ejecuta. `python -m outwarp` pasa a ser la CLI. Sin PATH por defecto (como el servidor); la opción de añadirlo desde Ajustes queda para el pulido de UI.
**Prevención:** tests de dispatch en `client/tests/test_cli.py` y de la migración del autoarranque en `test_app.py`. Pendiente: probarlo con el instalador real de 0.15.0.

### ✅ B-028 — Servidor: cambiar `wg_listen_port` desde el panel cortaba a todos los clientes
**Síntomas:** Hallazgo de la auditoría de 0.14.0. Tras cambiar el puerto de WireGuard en el panel, ningún cliente volvía a conectar.
**Causa raíz:** dos fallos. (1) `api.update_server_config` solo reescribía la unit de wstunnel si cambiaba el puerto WSS; con un puerto WG nuevo, systemd reiniciaba wstunnel con el `--restrict-to` viejo. (2) `ServerPlatform.reconcile(force_restart=True)` reiniciaba WireGuard desde el fichero en disco **sin escribir antes el nuevo**, así que seguía con el `ListenPort` viejo (el re-run del wizard pasaba por el mismo sitio). Además, `_save_config_patch` guardaba en la ruta por defecto: un panel con `--config-dir` (el contenedor) perdía el cambio.
**Fix (2026-09-26):** `reconcile` escribe la conf (`ServerPlatform.write_wg_config`, que el contenedor sobrescribe para quitar el `sysctl`) antes del reinicio forzado; cualquier cambio de puerto reescribe la unit desde la config nueva; se refresca el sello de config del manager; el panel guarda en `manager._config_path`.
**Prevención:** `test_wg_port_change_rewrites_the_wstunnel_unit`, `test_update_server_config_saves_to_the_managers_config_path` y los tests de `reconcile` en `server/tests/test_platforms.py`.

### ✅ B-029 — Servidor Windows: `add-client`, `revoke-client`, `rotate-client` y `restart` escribían un `wg0.conf` de Linux
**Síntomas:** Hallazgo de la auditoría de 0.14.0. En un servidor Windows, `restart` fallaba siempre, y las operaciones de clientes (también desde la GUI, que delega en `operations.py`) instalaban una conf que WireGuard for Windows rechaza.
**Causa raíz:** `operations.py` usaba `build_server_wg_conf` (con `PostUp`/`PostDown` de iptables) en vez del builder de Windows. `restart` además desmontaba el túnel dos veces y el paso de wstunnel lanzaba siempre `PlatformError`, porque en Windows wstunnel vive dentro de la app del servidor.
**Fix (2026-09-26):** `wireguard.build_platform_wg_conf` es el único builder para la conf del SO y lo usan `operations.py` y `server_manager._get_wg_conf`. `restart_services` hace un solo `reconcile(force_restart=True)`, y cuando otro proceso es dueño del transporte (`ServerPlatform.transport_owner_note`, Windows) lo dice como aviso, no como error.
**Prevención:** `test_windows_writes_the_windows_wg_conf` y `test_restart_on_windows_points_at_the_app_instead_of_failing`.

### ✅ B-030 — Docker/Kubernetes: `outwarp-server restart` no reiniciaba nada y decía ✓
**Síntomas:** Hallazgo de la auditoría de 0.14.0. `docker exec … outwarp-server restart` reiniciaba WireGuard pero informaba de wstunnel y del listener de enrolamiento como reiniciados sin tocarlos; un cambio de puerto o de argv nunca llegaba al proceso `serve`.
**Causa raíz:** `KubernetesServerPlatform.restart_wstunnel_service` y `restart_enroll_service` eran `pass`; `serve` solo atendía `SIGTERM`/`SIGINT`.
**Fix (2026-09-26):** `serve` atiende `SIGHUP` (bandera; el hilo principal recarga la config y llama a `manager.restart()`); la plataforma del contenedor busca `outwarp-server … serve` con `pgrep` y le manda `SIGHUP`, o falla con un error claro si no hay; el `CMD` del `Dockerfile` hace `exec` para que `serve` sea PID 1.
**Prevención:** `TestServeReload` y `TestContainerRestart` en `server/tests/test_cli.py`.

### ✅ B-031 — Servidor Linux: el setup desde la GUI no instalaba los servicios
**Síntomas:** Hallazgo de la auditoría de 0.14.0. Tras configurar el servidor desde `outwarp-server gui` en Linux, el túnel se paraba al cerrar la ventana, no arrancaba con el sistema y el enrolamiento no tenía listener.
**Causa raíz:** `api.run_setup` solo guardaba la config y dejaba que la GUI ejecutara wstunnel como subproceso; se saltaba todo lo que hace el wizard CLI (forwarding persistente, ufw, units de wstunnel y de enrolamiento).
**Fix (2026-09-26):** esos pasos pasan a `outwarp_server/service_install.install_services()`, sin `rich`, y los usan el wizard CLI y la GUI (cuando `platform.os_managed_transport`). La GUI exige root en Linux y sigue ofreciendo solo la rama autofirmada; dominio + Caddy es del wizard CLI.
**Prevención:** `server/tests/test_service_install.py` y `test_run_setup_installs_the_services_on_linux`.

### ✅ B-032 — TUI: `k` salía de la TUI en vez de desconectar
**Síntomas:** Hallazgo de la auditoría de 0.14.0. En el dashboard, `k` (Disconnect según la ayuda) paraba el túnel y cerraba la TUI; en la pantalla de conexión, `k` (Cancel) también salía, y además bloqueaba el bucle de eventos durante el `stop()`.
**Causa raíz:** `app.exit(0)` tras `mgr.stop()` en `tui/screens/dashboard.py` y `tui/screens/connecting.py`.
**Fix (2026-09-26):** ambos se quedan en la TUI, en el dashboard desconectado; el cancel ejecuta `stop()` fuera del bucle; una transición a `DISCONNECTED` lleva al dashboard.
**Prevención:** tres tests en `client/tests/test_tui_client.py`.

---

## Abiertos

### 🟢 B-033 — GUI del cliente: textos fijos en español
**Síntomas:** Hallazgo de la auditoría de 0.14.0. Parte de la GUI del cliente muestra textos en español aunque el idioma sea inglés.
**Causa:** strings literales en los `.jsx` fuera de `STR`.
**Plan:** se resuelve con la infraestructura de i18n (fase 1 del plan de 1.0, criterio "Interfaz en 5 idiomas"). No bloquea por sí solo.

### 🟡 B-024 — Windows: dos iconos en la bandeja tras una cuarentena de `wstunnel.exe` (mitigado, sin reproducir)
**Síntomas:** Reportado por el autor (2026-09-26): Microsoft Defender / Smart App Control quitó `wstunnel.exe` de repente; al volver a abrir OutWarp aparecieron dos iconos de OutWarp en la bandeja.
**Hipótesis (sin reproducir, varias causas posibles):**
1. **Mutex de instancia única poco fiable.** `TunnelOwnerLock._acquire_windows` leía el error con `ctypes.windll.kernel32.GetLastError()` en una llamada aparte; el intérprete puede ejecutar llamadas Win32 propias entre medias y resetearlo, y entonces la segunda instancia cree que ha creado el mutex → dos GUIs, dos trays, dos `TunnelManager` sobre la misma interfaz.
2. **La segunda instancia salía en silencio.** Con la primera oculta en la bandeja, abrir el acceso directo no mostraba nada, invitando a abrirlo otra vez.
3. **Icono fantasma.** Si un proceso muere sin quitar su icono, Windows lo deja pintado hasta pasar el ratón por encima; no se puede limpiar desde otro proceso.
4. **Relacionado:** `TunnelManager(config)` resolvía `wstunnel.exe` al construirse, así que con el binario en cuarentena la GUI moría al arrancar ("Fatal error in client main()") en vez de enseñar el banner de integridad.
**Fix (2026-09-26):** (1) `ctypes.WinDLL("kernel32", use_last_error=True)` + `ctypes.get_last_error()` y firmas `argtypes`/`restype` (`client/outwarp/ownership.py`). (2) Evento con nombre `Global\OutWarpClientShow`: la segunda instancia lo señala y sale; la primera muestra su ventana (`request_show_existing` / `listen_for_show_requests`). (4) `Tunnel` resuelve `wstunnel` de forma perezosa y lo vuelve a comprobar en cada `connect()`, antes de subir WireGuard; si falta o Windows impide ejecutarlo (`winerror` 2/3/225/1260/4551), lanza `TransportUnavailableError` con un mensaje que apunta a Defender / Smart App Control, y `TunnelManager` pasa a `FAILED` sin recorrer el backoff. (3) no tiene arreglo desde la app.
**Pendiente:** confirmar en Windows real. Si vuelve a pasar, mirar en `%APPDATA%\OutWarp\outwarp.log` si hay dos líneas `starting` seguidas sin `shut down` entre ellas (dos instancias vivas → causa 1) o una sola (icono fantasma → causa 3). Defender en sí no se puede evitar sin firmar el binario (Authenticode, fuera del criterio de 1.0) — Smart App Control bloquea ejecutables sin firma ni reputación.

---

## Cómo añadir un bug nuevo

1. Asignar `B-XXX` consecutivo.
2. Rellenar: síntomas, causa raíz (o hipótesis si abierto), fix con commit, prevención.
3. Mover a la sección correcta cuando cambie de estado.
