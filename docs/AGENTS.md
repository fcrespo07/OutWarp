# Guía de trabajo para agentes

Complemento de `CLAUDE.md`. `CLAUDE.md` dice **qué** es OutWarp y qué decisiones no se deshacen. Este fichero dice **cómo se trabaja** en el repo y **dónde se quedó** el trabajo. Está pensado para que un agente nuevo, sin la conversación anterior, siga sin preguntar lo que ya se sabe.

Última actualización: 2026-10-01, con la 0.19.0 publicada.

---

## 1. Dónde está cada cosa

| Qué | Dónde |
|---|---|
| Producto, arquitectura y decisiones vigentes | `CLAUDE.md` |
| Criterio de 1.0 y plan por fases | `CLAUDE.md` → "Criterio de 1.0.0" (fuente de verdad); `ROADMAP.md` → "Before 1.0" (réplica en inglés) |
| Qué trae cada versión | `CHANGELOG.md` (en inglés; `## [Unreleased]` arriba) |
| Bugs abiertos y resueltos (B-001…) | `KNOWN_BUGS.md` (en español) |
| Firma y publicación de releases | `docs/RELEASE_SIGNING.md` |
| Auditorías antiguas, citadas desde el código | `docs/history/` |
| Herramientas de capturas de la UI | `scripts/dev/` (sección 5) |
| Contexto privado del autor | `CLAUDE.local.md`. **No está en el repo** y nunca debe estarlo. Si no lo tienes, pídeselo al autor antes de tocar nada que pueda llevar datos personales. |

---

## 2. Estado a 2026-10-01

- **Publicadas y firmadas hasta la 0.19.0.** `main` = `0a9a10d`. En el código, la versión es `0.19.0` en cuatro sitios: `client/pyproject.toml`, `server/pyproject.toml`, `client/outwarp/__init__.py` y `server/outwarp_server/__init__.py`.
- **La numeración del plan se ha desplazado.** La fase 2 (producto) ocupó la 0.17.0, la 0.18.0 y la 0.19.0. La fase 3 (idiomas) ya no sale como 0.19.0, sino como la primera versión después de cerrar la fase 2 (0.20.0 o posterior). El contenido y el orden de las fases no cambian.
- Qué llevó cada versión reciente, en resumen (el detalle está en `CHANGELOG.md`):
  - **0.17.0**: pantalla Tráfico del panel con datos reales (B-041), primera pasada de pulido (B-042), servidor Windows vía Docker Compose y README y wizard honestos con el anti-DPI.
  - **0.18.0**: inicio del cliente rediseñado (dial con anillo cerrado, B-043; detalles de conexión, ruta y kill switch; selector de perfil), pistas por tipo de error y logo del `.ico` en las tres interfaces.
  - **0.19.0**:
    - cliente: gráfica de 3 min, nivel de las líneas del registro (B-044), Acerca de, detalles en Perfiles y ancho máximo en ventana grande;
    - panel: gráfica en vivo que se desliza sin saltos;
    - Windows: relanzamiento tras actualizar (B-045) y sin la página vacía de componentes en el instalador (B-046);
    - aura del dial (B-047) y el redraft de la release mueve el commit destino.

---

## 3. Pendiente, por orden

### Fase 2 (antes de cerrar la fase y pasar a idiomas)

1. **B-048: la X de la ventana cierra el cliente en Windows** en vez de dejarlo en la bandeja (lo dice el autor; ver `KNOWN_BUGS.md`). Se está **esperando a que el autor pase** las líneas `window close: close_to_tray=… tray_icon=… -> hide|quit` de `%LOCALAPPDATA%\OutWarp\OutWarp\Logs\outwarp.log`. Esa línea dice cuál de las dos condiciones falla. No arreglar a ciegas: pedir la línea si no ha llegado.
2. **Ajustes del cliente: orden y agrupación.** Es lo único que queda de la auditoría de la GUI del cliente (`CLAUDE.md` → Fase 2, punto 9 de la lista de hallazgos). Antes de implementar, enseñar una propuesta con capturas.
3. **Segunda pasada de pulido**:
   - TUIs (cliente y servidor);
   - mensajes de la CLI y textos del wizard `setup` (siguen en inglés fijo y tienen que pasar a i18n);
   - paridad de funciones entre GUI, panel, TUI y CLI.

   *Hecho 2026-10-01 (rama por bloque, PR #10–#14 y el de la matriz): textos de la CLI, wizard y doctor en i18n; las dos TUIs sin inglés suelto, con selector de idioma y la TUI del cliente con ruta/kill switch. La matriz de paridad y sus huecos abiertos están en `docs/PARIDAD.md`; los que ensanchan la CLI esperan decisión del autor.*

   Termina con la **congelación de textos**, que es condición para empezar las traducciones.
4. **Pruebas que hace el autor (👤), sin cerrar aún**:
   - Windows real:
     - actualizar desde 0.19.0 a la siguiente (B-045 solo se ve desde 0.19.0 en adelante, porque la 0.18.0 llevaba el helper viejo);
     - instalador sin la página de componentes;
     - `--show-window`;
     - inicio nuevo;
     - B-034 con inicio rápido;
     - B-024.
   - `deploy/docker/compose.yml` en Docker Desktop.
   - Pantalla Tráfico en su pod.
   - GUI de Linux en X11 y Wayland (cierra el `[~]` de "Cliente Linux con GUI").
   
   Si el autor reporta algo de esto, va a `KNOWN_BUGS.md` con número nuevo.

### Fases siguientes

Las fases 3, 4 y 5 están tal cual en `CLAUDE.md`:
- **Fase 3**: zh-Hans, fr y pt, con un test de claves que faltan, capturas con los textos más largos y revisión de nativos.
- **Fase 4**: contratos y tests de contrato, retirar el alias `outwarp-cli`, tests de actualización en el e2e, smoke test del instalador Windows en CI y auditoría de la RC.
- **Fase 5**: 1.0.0.

---

## 4. Cómo se trabaja

### Con el autor

- **Respuestas en español**, claras y sin jerga innecesaria. El código, los commits, el CHANGELOG y el ROADMAP van en inglés; `CLAUDE.md`, `KNOWN_BUGS.md` y este fichero, en español.
- **Iterar.** No hacer un plan para cada petición ni diseñarlo todo de golpe: hacer, enseñar y ajustar. En cambios visuales grandes, enseñar capturas antes y después.
- Cuando el autor reporta un fallo con una captura, el arreglo va a la versión en curso si lo pide ("arréglalo para esta versión").
- **El repo es público.** Antes de cada commit, comprobar que no entra nada personal (ver `CLAUDE.local.md`). En los ejemplos, usar `203.0.113.x`, `198.51.100.x` y `vpn.example.com`.

### Ramas, CI y `main`

- El trabajo va en la rama que asigne la sesión. Cuando está validado, se hace push a la rama y fast-forward de `main` (`git push origin HEAD:main`). Después hay que esperar al CI de `main` en verde (`ci.yml`: pytest Linux/Windows, `ui-tests`, `pip-audit`, `e2e`; ruff es informativo).
- Antes de cada push:
  - `ruff check` sin violaciones nuevas;
  - `pytest -q` en `client/` y `server/`;
  - `npx vitest run` si se ha tocado la UI;
  - `python scripts/build_ui.py --check`.
- **Tras editar cualquier `.jsx`**: `python scripts/build_ui.py`, y commitear los `bundle.js` regenerados. Si no, el job `ui-tests` falla.
- Si se cambia algo de cara al usuario, se añade al `CHANGELOG.md` (`[Unreleased]`). Un bug va a `KNOWN_BUGS.md` con síntomas, causa, fix y prevención. Si cambia una decisión, se actualiza `CLAUDE.md` → "Decisiones de arquitectura vigentes".

### Releases (los agentes nunca publican)

1. Subir la versión en los cuatro sitios, convertir `[Unreleased]` en `## [x.y.z] — fecha` y actualizar "Versión actual" en `CLAUDE.md`. Commit `release: x.y.z — …`, fast-forward de `main` y CI en verde.
2. Lanzar el workflow **Release** (`release.yml`) por `workflow_dispatch` sobre `main` con `tag=vX.Y.Z`. Con el MCP de GitHub es `actions_run_trigger` → `run_workflow`. El workflow crea o refresca el **borrador** (wheels + `SHA256SUMS.txt` + los `.exe` de `windows-installer.yml`). Se puede relanzar mientras siga siendo borrador: refresca los assets y el commit destino.
3. Comprobar el borrador con `list_releases` o `get_release_by_tag`. Por la API anónima no se ven los borradores.
4. Decirle al autor que ejecute en su Windows:
   ```
   git pull
   python scripts\sign_release.py vX.Y.Z
   python scripts\publish_release.py vX.Y.Z
   ```
   Una release publicada es inmutable: cualquier arreglo posterior sale como versión nueva.

---

## 5. Entorno (sandbox de Claude Code en la nube)

### Particularidades conocidas

- **Tests del cliente sin proxy**:
  ```
  env -u HTTPS_PROXY -u HTTP_PROXY -u https_proxy -u http_proxy pytest -q
  ```
  Algunos tests abren sockets locales y el proxy del sandbox los rompe.
- Fallos conocidos **solo en el sandbox** (en CI pasan): dos en `client/tests/test_service.py` y `server/tests/test_crypto.py::test_validity_is_not_a_decade` (versión vieja de `cryptography`). No intentar arreglarlos.
- **`pkill -f` / `pgrep -f` con un patrón que aparezca en tu propio comando matan tu shell** (exit 144). Usar un patrón que no coincida consigo mismo (`"ui_panel_[d]emo"`) y en una llamada aparte de cualquier otro comando que contenga ese texto.
- `sleep` en primer plano está bloqueado: para esperar a algo, usar `timeout N bash -c 'until …; do sleep 0.5; done'`.
- Chromium está en `/opt/pw-browsers/`. Si la versión de Playwright no casa con él, `export OUTWARP_CHROMIUM=/opt/pw-browsers/chromium-1194/chrome-linux/chrome`.
- Docker no está arrancado de serie. Para la réplica del pod hay que lanzar `dockerd` a mano en segundo plano.
- GitHub va por las herramientas MCP (`mcp__github__*`); no hay `gh`.

### Capturas de la UI (`scripts/dev/`)

Sin capturas no se da un cambio visual por bueno. Las herramientas usan la UI real y la `Api` real con un manager simulado:

```bash
export OUTWARP_CHROMIUM=/opt/pw-browsers/chromium-1194/chrome-linux/chrome   # si hace falta
# Cliente: STATE = connected|connecting|disconnected|failed|empty; SCREEN = home|import|logs|settings|about
python scripts/dev/ui_client_shot.py connected home /tmp/home.png --lang es --scheme dark --width 1000
python scripts/dev/ui_client_shot.py connected home /tmp/menu.png --extra-profiles --open menu
# Panel del servidor: un proceso sirve el panel, otro hace la captura
python scripts/dev/ui_panel_demo.py /tmp/panel --port 18777 &      # imprime READY <token>
python scripts/dev/ui_panel_shot.py http://127.0.0.1:18777/ "$(cat /tmp/panel/token.txt)" /tmp/traffic.png --screen traffic --window "24 h"
```

Comprobar como mínimo claro y oscuro, ventana ancha (≥1300) y estrecha (≈420), y es y en.

### Réplica del pod (cambios del panel en contenedor)

`ui_panel_demo.py` es el panel en **un solo proceso**. En producción (pod k3s, Docker Compose), `serve` y `web` son **dos procesos** que comparten `/data`, la red y el espacio de PIDs, normalmente detrás de un proxy. Varios fallos solo se vieron así (B-036 → B-037, B-039, B-040, B-041). Un cambio del panel que dependa de estado, logs, eventos o historial de tráfico se verifica con:

- `deploy/docker/compose.yml` (con su `.env.example`), que replica el pod;
- un Caddy delante (`reverse_proxy https://<ip del server>:<puerto del panel>` con `tls_insecure_skip_verify`), más un segundo sitio que responda `502` en `/events` para probar el modo sin SSE (sondeo cada 2 s);
- si hace falta tráfico real, el cliente de `e2e/client.Dockerfile` en la misma red.

Si para construir detrás del proxy del sandbox hace falta un Dockerfile temporal, se llama `zz-*.Dockerfile` y **no se commitea nunca**.

### Medir la gráfica en vivo del panel

La gráfica se valida midiendo, no a ojo. Con Playwright, en cada `requestAnimationFrame`, se lee el `transform` de la capa `svg g[transform]` y la x del último punto del path. La velocidad de la capa debe ser constante, y el último punto no debe saltar a la derecha al llegar una muestra. Así se validó en 0.19.0 (ver `CLAUDE.md` → "La gráfica en vivo del panel no da saltos").

---

## 6. Trampas que ya costaron un bug

- Un ajuste de la UI del panel probado solo contra un panel local (B-036 → B-037). Ver la réplica del pod.
- Datos inventados en la UI (QR decorativo, sparklines falsas, "todo sano" fijo; B-042). Si no hay dato real, estado vacío honesto.
- Rutas fijas del servidor fuera del directorio de config (B-041).
- Probar una feature en la maqueta sin `api.bind_window(...)`: el registro sale vacío y parece otro bug (B-044). Las herramientas de `scripts/dev/` ya lo llaman.
- Un arranque que el usuario espera ver, pero que sale oculto en la bandeja (B-045): usar `--show-window`.
- SVG con efectos (glow, blur) que se salen de su `viewBox`: `overflow: visible` (B-047).
- Redraft de una release sin mover el commit destino (arreglado en `release.yml`, 0.19.0).
