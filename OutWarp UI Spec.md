# OutWarp — Especificación de cambios pendientes en la UI

Este documento describe, sección por sección, todo el trabajo de frontend que queda por hacer en la rama `new-uidesign` de [`fcrespo07/OutWarp`](https://github.com/fcrespo07/OutWarp). Está pensado para entregárselo a Claude Code: cada tarea incluye **archivos a tocar**, **contrato del bridge `window.pywebview.api`**, **forma del componente React**, y **copy en `es` / `en`**.

Convenciones del repo (ya establecidas — no inventar):
- Sin TypeScript. JSX plano servido por Babel-standalone desde `index.html`.
- Componentes globales se exponen como `window.Btn`, `window.Pill`, `window.StatusDot`, `window.Toggle`, `window.WSWordmark`, `window.WSLogoMark`.
- Tokens en `styles.css` (`--bg`, `--bg-2`, `--bg-sunk`, `--line`, `--line-strong`, `--text`, `--text-2`, `--text-3`, `--brand`, `--brand-2`, `--brand-warn`, `--brand-bad`, `--chip`, `--shadow`, `--font-sans`, `--font-mono`).
- Estados de túnel: `empty | disconnected | connecting | connected | reconnecting | error`.
- Eventos Python → JS: `outwarp:status`, `outwarp:stats`, `outwarp:log`, `outwarp:settings`, `outwarp:clients`. **No** inventar nombres con otro prefijo; usar `outwarp:*` siempre.

---

## A. CLIENTE (`client/outwarp/ui/`)

### A.1 — Limpieza y decisión sobre strings huérfanas en `shared.jsx`

Actualmente `STR.es` / `STR.en` declaran claves que ningún componente renderiza. Hay que **decidir por cada una**: cablearla (implementarla) o **borrarla** del diccionario para no engañar a quien lea el código. La decisión recomendada está en la última columna.

| Clave | Hoy | Recomendación |
|---|---|---|
| `importPaste` | Sin UI | **Implementar** (ver A.4). |
| `importQR` | Sin UI | **Borrar**. Pywebview no expone cámara fiable en Linux/macOS; mejor no prometerlo. |
| `nav_about` | Sin UI | **Implementar** (ver A.5). |
| `set_killSwitch`, `set_killSwitchSub` | Sin UI; backend no lo consume | **Implementar** (ver A.2). |
| `set_autoconnect`, `set_autoconnectSub` | Sin UI; backend no lo consume | **Implementar** (ver A.2). |
| `set_splitTunnel`, `set_splitTunnelSub` | Sin UI; backend no lo consume | **Borrar**. Split tunnel cross-platform es una feature mayúscula; no procede prometerlo en v0.1. |
| `set_startup` | Sin UI; backend no lo consume | **Implementar** (ver A.2). |
| `set_minimizeTray` | Sin UI; backend no lo consume | **Implementar** (ver A.2). |
| `set_dns`, `set_mtu` (globales) | Sin UI | **Borrar de Settings**. Ya están por perfil en *Edit Profile*. Mantener las strings sólo si se reusan en otro sitio; si no, borrar. |
| `location`, `latency` | Sin UI en Home | **Implementar** (ver A.7). |
| `lastHandshake` | Sin UI en Home (sí en server) | **Implementar** como stat-card extra en Home conectado (ver A.7). |
| `step_resolve … step_done` | Sin UI | **Implementar** (ver A.3). |
| `showAdvanced` / `hideAdvanced` | Sin UI | **Borrar**. El toggle vive ya en Settings; no hace falta un botón extra. |

> **Acción concreta**: tras aplicar A.2–A.7, hacer un *grep* `grep -rn "STR\." client/outwarp/ui/` y otro `grep -rn "T\." client/outwarp/ui/` para confirmar que cada clave restante se usa al menos una vez.

---

### A.2 — Settings: cablear toggles funcionales

#### Backend (no es estrictamente "UI" pero la UI depende de esto)

**`client/outwarp/api.py`**

1. En `_default_settings()` añadir las nuevas claves:
   ```python
   return {
       "language": "es",
       "theme": "auto",
       "advanced": False,
       "kill_switch": False,
       "auto_reconnect": True,
       "start_at_boot": False,
       "minimize_to_tray": True,
   }
   ```
2. En `set_settings` ya hay un loop `for k, v in patch.items(): if k in self._settings: …`, así que con añadirlas a `_default_settings` ya se persisten. **No** hay que tocar `_load_settings`.
3. Añadir consumidores reales:
   - `kill_switch=True` → cuando `TunnelManager` pasa a `FAILED` / `DISCONNECTED` por error, llamar a `platform.block_all_traffic_until_tunnel_back()` (nuevo método en `platforms/base.py`; implementación stub en Linux/macOS, real en Windows con un perfil de firewall temporal). Si está en `False`, comportamiento actual.
   - `auto_reconnect=False` → cuando el watchdog detecta caída, **no** reintentar; entrar directamente a `FAILED`. Hoy siempre reintenta.
   - `start_at_boot` → al cambiar de `False`→`True`, llamar a `platform.install_autostart()`; al revés, `platform.uninstall_autostart()`. Implementación por OS:
     - Windows: clave en `HKCU\Software\Microsoft\Windows\CurrentVersion\Run\OutWarp` apuntando al `.exe` con `--silent`.
     - Linux: archivo `~/.config/autostart/outwarp.desktop`.
     - macOS: `~/Library/LaunchAgents/dev.outwarp.client.plist`.
   - `minimize_to_tray=True` (default) → `app.py` no muestra la ventana al arrancar (sólo el tray). Si `False`, abre la ventana en cada lanzamiento.

#### Frontend

**`client/outwarp/ui/app.jsx`** — componente `Settings`:

```jsx
const Settings = ({ T, settings, onSetting }) => {
  // … Row, Select como ahora …
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 720 }}>
      <Header title={T.nav_settings} sub="outwarp-client · v0.0.1"/>

      {/* Bloque 1: apariencia */}
      <SettingsCard>
        <Row title={T.set_language} control={…}/>
        <Row title={T.set_theme} control={…}/>
        <Row title={T.set_advanced} sub={T.set_advancedSub}
             control={<window.Toggle on={!!settings.advanced} onChange={v => onSetting("advanced", v)}/>}/>
      </SettingsCard>

      {/* Bloque 2: comportamiento de la conexión */}
      <SettingsCard title={T.set_groupConnection}>
        <Row title={T.set_autoconnect} sub={T.set_autoconnectSub}
             control={<window.Toggle on={!!settings.auto_reconnect}
                                     onChange={v => onSetting("auto_reconnect", v)}/>}/>
        <Row title={T.set_killSwitch} sub={T.set_killSwitchSub}
             control={<window.Toggle on={!!settings.kill_switch}
                                     onChange={v => onSetting("kill_switch", v)}/>}/>
      </SettingsCard>

      {/* Bloque 3: arranque del sistema */}
      <SettingsCard title={T.set_groupSystem}>
        <Row title={T.set_startup} sub={T.set_startupSub}
             control={<window.Toggle on={!!settings.start_at_boot}
                                     onChange={v => onSetting("start_at_boot", v)}/>}/>
        <Row title={T.set_minimizeTray} sub={T.set_minimizeTraySub}
             control={<window.Toggle on={!!settings.minimize_to_tray}
                                     onChange={v => onSetting("minimize_to_tray", v)}/>}/>
      </SettingsCard>
    </section>
  );
};
```

`SettingsCard` es un wrapper nuevo:
```jsx
const SettingsCard = ({ title, children }) => (
  <div>
    {title && (
      <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-3)",
                    letterSpacing: ".06em", textTransform: "uppercase",
                    margin: "0 4px 8px" }}>{title}</div>
    )}
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)",
                  borderRadius: 14, padding: "0 18px" }}>{children}</div>
  </div>
);
```

#### Copy a añadir a `shared.jsx` (`STR.es` / `STR.en`)

```js
// es
set_groupConnection: "Conexión",
set_groupSystem: "Sistema",
set_autoconnectSub: "Reintentar automáticamente si la conexión se cae.",
set_killSwitchSub: "Bloquea todo el tráfico de internet si la VPN se cae.",
set_startupSub: "Arrancar OutWarp al iniciar el sistema.",
set_minimizeTraySub: "Al cerrar la ventana, quedarse en la bandeja del sistema.",

// en
set_groupConnection: "Connection",
set_groupSystem: "System",
set_autoconnectSub: "Automatically retry if the connection drops.",
set_killSwitchSub: "Block all internet traffic if the VPN drops.",
set_startupSub: "Start OutWarp when the system boots.",
set_minimizeTraySub: "When closing the window, keep running in the tray.",
```

> Ojo: las claves `set_killSwitch`, `set_autoconnect`, `set_startup`, `set_minimizeTray` ya existen en `STR`. **Reusarlas** — no duplicar. Solo añadir las `*Sub` y los `set_group*`.

---

### A.3 — Stepper de la pantalla "Connecting"

Hoy `ConnectingHome` muestra un dial pulsante + `T.handshake`. Hay que reemplazarlo por un stepper con 6 fases.

#### Backend

**`client/outwarp/tunnel.py`** — `TunnelManager`:
1. Añadir un atributo `self.phase: str = ""` y un método `_set_phase(phase: str)` que actualice y notifique listeners.
2. Insertar `_set_phase` en los puntos clave de `connect()`:
   ```python
   self._set_phase("resolve")    # antes de DNS lookup
   self._set_phase("tls")        # antes de verify_tls_fingerprint
   self._set_phase("ws")         # antes de lanzar wstunnel
   self._set_phase("wg")         # antes de wireguard.connect()
   self._set_phase("route")      # antes de añadir bypass routes
   self._set_phase("done")       # al transitar a CONNECTED
   ```
3. Listener notification: en lugar de añadir un canal nuevo, reusar `outwarp:status`. El payload queda:
   ```python
   {"status": "connecting", "phase": "tls", "active_profile_id": …, "error": …, "attempt": …, "max_attempts": …}
   ```

**`client/outwarp/api.py`** — `_status_payload()` debe incluir `phase`:
```python
return {
    "status": self._status_str(),
    "active_profile_id": self._active_profile_id(),
    "error": self._error_str(),
    "attempt": attempt,
    "max_attempts": max_attempts,
    "phase": getattr(self._manager, "phase", "") if self._manager else "",
}
```

#### Frontend

**`client/outwarp/ui/app.jsx`**:

1. Añadir al state del `App`: `const [phase, setPhase] = useState("");`
2. En `useBridgeEvent("status", …)` y en `bootstrap`: `setPhase(d.phase || "");`
3. Pasarlo a `Home`:
   ```jsx
   <Home … phase={phase} … />
   ```
4. Sustituir `ConnectingHome` por:

```jsx
const STEPS = [
  ["resolve", "step_resolve"],
  ["tls",     "step_tls"],
  ["ws",      "step_ws"],
  ["wg",      "step_wg"],
  ["route",   "step_route"],
  ["done",    "step_done"],
];

const ConnectingHome = ({ T, active, busyMsg, reconnecting, attemptInfo, phase }) => {
  const showAttempt = reconnecting && attemptInfo && attemptInfo.attempt > 0;
  const currentIdx = Math.max(0, STEPS.findIndex(([k]) => k === phase));
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Header title={T.nav_home} sub={T.home_ribbon}/>
      <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)",
                        borderRadius: 18, padding: 28 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <window.StatusDot tone="warn"/>
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-warn)",
                             letterSpacing: ".06em", textTransform: "uppercase" }}>
                {reconnecting ? T.reconnecting : T.connecting}
              </span>
            </div>
            <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.02em" }}>{active.name}</div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>{active.endpoint}</div>
            {showAttempt && (
              <div style={{ fontSize: 12, color: "var(--brand-warn)", marginTop: 8,
                            fontFamily: "var(--font-mono)" }}>
                {T.reconnectAttempt} {attemptInfo.attempt}/{attemptInfo.max_attempts}
              </div>
            )}
          </div>
          <Dial pulsing/>
        </div>

        <Stepper T={T} currentIdx={currentIdx}/>
        {busyMsg && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 12,
                                  fontFamily: "var(--font-mono)" }}>{busyMsg}</div>}
      </section>
    </div>
  );
};

const Stepper = ({ T, currentIdx }) => (
  <ol style={{ listStyle: "none", padding: 0, margin: "24px 0 0",
               display: "flex", flexDirection: "column", gap: 10 }}>
    {STEPS.map(([key, strKey], i) => {
      const state = i < currentIdx ? "done" : i === currentIdx ? "active" : "pending";
      return (
        <li key={key} style={{ display: "grid", gridTemplateColumns: "20px 1fr",
                               gap: 12, alignItems: "center" }}>
          <StepIcon state={state}/>
          <div style={{
            fontSize: 13,
            fontWeight: state === "active" ? 600 : 500,
            color: state === "pending" ? "var(--text-3)"
                 : state === "active"  ? "var(--text)"
                 :                       "var(--text-2)",
          }}>
            {T[strKey]}
          </div>
        </li>
      );
    })}
  </ol>
);

const StepIcon = ({ state }) => {
  if (state === "done") return (
    <svg width="20" height="20" viewBox="0 0 24 24" fill="none"
         stroke="var(--brand-2)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" fill="color-mix(in srgb, var(--brand-2) 12%, transparent)" stroke="none"/>
      <path d="M7 12 L11 16 L17 9"/>
    </svg>
  );
  if (state === "active") return (
    <span style={{ position: "relative", display: "inline-block", width: 20, height: 20 }}>
      <span style={{ position: "absolute", inset: 0, borderRadius: 999,
                     border: "2px solid var(--brand-warn)", borderTopColor: "transparent",
                     animation: "ws-spin 0.9s linear infinite" }}/>
    </span>
  );
  return (
    <svg width="20" height="20" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="9" fill="none" stroke="var(--line-strong)" strokeWidth="1.5"/>
    </svg>
  );
};
```

5. Añadir en `styles.css`:
   ```css
   @keyframes ws-spin { from { transform: rotate(0); } to { transform: rotate(360deg); } }
   ```

---

### A.4 — Pantalla *Import* enriquecida

Hoy sólo file picker + drop. Añadir:

1. **Pestaña / sección "Pegar texto"** con un `<textarea>` que admita el contenido JSON del `.owcfg`.
2. **Drop-zone también activa cuando ya existe un perfil** (en la lista). Hoy la lista no acepta drop.
3. **Quitar** todo lo de `importQR`.

#### Cambios en `Import`

Reemplazar el actual switch `if (!active)` … `return` por una vista con dos pestañas siempre visibles:

```jsx
const Import = ({ T, api, active, confirm, onImported, onRemove, onProfilesChanged }) => {
  const fileRef = useRef(null);
  const [mode, setMode]   = useState("file"); // "file" | "paste"
  const [paste, setPaste] = useState("");
  const [msg, setMsg]     = useState("");
  const [error, setError] = useState("");
  const [showEditor, setShowEditor] = useState(false);

  const submit = async (text) => { /* igual que handleFile pero con texto */ };

  const onDrop = (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files[0];
    if (f) handleFile(f);
  };

  return (
    <div onDragOver={(e) => e.preventDefault()} onDrop={onDrop}
         style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 720 }}>
      <Header title={active ? T.profiles_title : T.welcomeTitle}
              sub={T.welcomeSub}
              right={active && <window.Btn kind="primary" size="md" onClick={onAddClick}>
                                 {T.profiles_add}
                               </window.Btn>}/>

      {/* Tabs */}
      <div style={{ display: "inline-flex", gap: 4, padding: 4,
                    background: "var(--bg-sunk)", borderRadius: 10, width: "fit-content" }}>
        <TabBtn active={mode === "file"}  onClick={() => setMode("file")}>{T.import_tabFile}</TabBtn>
        <TabBtn active={mode === "paste"} onClick={() => setMode("paste")}>{T.import_tabPaste}</TabBtn>
      </div>

      {mode === "file" && (
        <DropZone T={T} fileRef={fileRef} onPick={handleFile}/>
      )}
      {mode === "paste" && (
        <PasteArea T={T} value={paste} onChange={setPaste}
                   onSubmit={() => submit(paste)} disabled={!paste.trim()}/>
      )}

      {/* mensaje y error igual que ahora */}

      {active && (
        <ProfileCard active={active} onEdit={() => setShowEditor(v => !v)} onRemove={onRemove}
                     editLabel={T.edit_open} removeLabel={T.profiles_remove}/>
      )}
      {showEditor && active && (
        <ProfileEditor T={T} api={api} active={active} confirm={confirm}
                       onUpdated={onProfilesChanged} onClose={() => setShowEditor(false)}/>
      )}
    </div>
  );
};
```

Subcomponentes:

```jsx
const TabBtn = ({ active, onClick, children }) => (
  <button onClick={onClick} className="ow-btn"
    style={{
      all: "unset", padding: "6px 14px", borderRadius: 8, cursor: "pointer",
      fontSize: 12, fontWeight: 600,
      background: active ? "var(--bg)" : "transparent",
      color: active ? "var(--text)" : "var(--text-3)",
      boxShadow: active ? "0 1px 2px rgba(0,0,0,.12)" : "none",
    }}>{children}</button>
);

const PasteArea = ({ T, value, onChange, onSubmit, disabled }) => (
  <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)",
                borderRadius: 14, padding: 18 }}>
    <div style={{ fontSize: 13, fontWeight: 600 }}>{T.importPaste}</div>
    <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{T.importHint}</div>
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      spellCheck={false}
      placeholder='{ "server": { … }, "wireguard": { … } }'
      style={{
        marginTop: 12, width: "100%", height: 220, resize: "vertical",
        background: "var(--bg)", color: "var(--text)",
        border: "1px solid var(--line-strong)", borderRadius: 10,
        padding: "10px 12px", outline: "none",
        fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.55,
      }}/>
    <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end" }}>
      <window.Btn kind="primary" size="md" disabled={disabled} onClick={onSubmit}>
        {T.import_loadFromPaste}
      </window.Btn>
    </div>
  </div>
);
```

`DropZone` es el bloque que ya está en `EmptyHome` / `Import` (no-active) — extraerlo a una función nombrada y reusarlo.

#### Copy nuevo

```js
// es
import_tabFile: "Desde archivo",
import_tabPaste: "Pegar texto",
import_loadFromPaste: "Importar",

// en
import_tabFile: "From file",
import_tabPaste: "Paste text",
import_loadFromPaste: "Import",
```

`importPaste` ya existe en `STR` — reusarla como título de la pestaña Pegar.

#### Borrar
- La clave `importQR` de `STR.es` y `STR.en`.

---

### A.5 — Pantalla "Acerca de"

#### Backend

Añadir en `client/outwarp/api.py`:

```python
def get_app_info(self) -> dict[str, Any]:
    import platform, sys
    from outwarp import __version__  # ya existe; si no, crear en __init__.py
    return {
        "version": __version__,
        "python": sys.version.split()[0],
        "platform": platform.platform(),
        "repo_url": "https://github.com/fcrespo07/OutWarp",
        "license": "MIT",
        "third_party": [
            {"name": "wstunnel",  "license": "BSD-3-Clause",
             "url": "https://github.com/erebe/wstunnel"},
            {"name": "WireGuard", "license": "GPL-2.0",
             "url": "https://www.wireguard.com/"},
            {"name": "pystray",   "license": "LGPL-3.0",
             "url": "https://github.com/moses-palmer/pystray"},
            {"name": "pywebview", "license": "BSD-3-Clause",
             "url": "https://pywebview.flowrl.com/"},
        ],
    }

def open_url(self, url: str) -> dict[str, Any]:
    import webbrowser
    webbrowser.open(url, new=2)
    return {"ok": True}
```

#### Frontend

**`client/outwarp/ui/app.jsx`** — añadir entrada en `Sidebar.items`:

```js
["about", T.nav_about, "M12 8 V13 M12 16 V16.01 M3 12 a9 9 0 1 1 18 0 a9 9 0 1 1 -18 0"],
```

Añadir el switch en `<main>`:

```jsx
{screen === "about" && <About T={T} api={api}/>}
```

Componente:

```jsx
const About = ({ T, api }) => {
  const [info, setInfo] = useState(null);
  useEffect(() => { api?.get_app_info().then(setInfo); }, [api]);
  if (!info) return null;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 720 }}>
      <Header title={T.nav_about} sub={T.about_sub}/>

      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)",
                    borderRadius: 14, padding: 24 }}>
        <window.WSWordmark size={22} color="var(--text)" accent="var(--brand)"/>
        <div style={{ marginTop: 16, fontFamily: "var(--font-mono)", fontSize: 12,
                      color: "var(--text-3)" }}>
          v{info.version} · {info.platform} · Python {info.python}
        </div>
        <div style={{ marginTop: 14, fontSize: 13, color: "var(--text-2)", lineHeight: 1.6 }}>
          {T.about_blurb}
        </div>
        <div style={{ marginTop: 16, display: "flex", gap: 8 }}>
          <window.Btn kind="primary" size="md" onClick={() => api.open_url(info.repo_url)}>
            {T.about_openRepo}
          </window.Btn>
        </div>
      </div>

      <div>
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-3)",
                      letterSpacing: ".06em", textTransform: "uppercase", margin: "0 4px 8px" }}>
          {T.about_thirdParty}
        </div>
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)",
                      borderRadius: 14, overflow: "hidden" }}>
          {info.third_party.map((p, i) => (
            <div key={p.name} style={{
              display: "grid", gridTemplateColumns: "1fr auto auto",
              gap: 16, alignItems: "center", padding: "14px 18px",
              borderTop: i === 0 ? "none" : "1px solid var(--line)",
            }}>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</div>
              <window.Pill tone="neutral">{p.license}</window.Pill>
              <button onClick={() => api.open_url(p.url)} className="ow-link">
                {T.about_openUrl}
              </button>
            </div>
          ))}
        </div>
      </div>

      <div style={{ fontSize: 11, color: "var(--text-3)", lineHeight: 1.6 }}>
        {T.about_disclaimer}
      </div>
    </section>
  );
};
```

Añadir `.ow-link` a `styles.css`:
```css
.ow-link {
  all: unset; cursor: pointer; font-size: 12px; color: var(--brand);
  font-family: var(--font-mono);
}
.ow-link:hover { text-decoration: underline; }
```

#### Copy

```js
// es
nav_about: "Acerca de",                          // ← ya existe, mantenerla
about_sub: "Versión, licencias y créditos.",
about_blurb: "OutWarp tunela WireGuard sobre WebSocket usando wstunnel como transporte. " +
             "No requiere dominio: la identidad del servidor se verifica por huella TLS pineada en el .owcfg.",
about_openRepo: "Abrir repositorio",
about_thirdParty: "Componentes de terceros",
about_openUrl: "Abrir →",
about_disclaimer: "WireGuard es marca registrada de Jason A. Donenfeld. " +
                  "wstunnel se distribuye bajo BSD-3-Clause. " +
                  "OutWarp se distribuye bajo licencia MIT.",

// en
about_sub: "Version, licenses and credits.",
about_blurb: "OutWarp tunnels WireGuard over WebSocket using wstunnel as the transport. " +
             "No domain required: the server identity is verified by a TLS fingerprint pinned in the .owcfg.",
about_openRepo: "Open repository",
about_thirdParty: "Third-party components",
about_openUrl: "Open →",
about_disclaimer: "WireGuard is a registered trademark of Jason A. Donenfeld. " +
                  "wstunnel is distributed under BSD-3-Clause. " +
                  "OutWarp is distributed under the MIT license.",
```

---

### A.6 — Multi-perfil: decidir y unificar

Hoy la UI dice "Perfiles", "Añadir perfil", "Reemplazar conexión" — pero realmente sólo hay un perfil activo a la vez. **Decidir UNA de las dos**:

#### Opción B (recomendada para v0.1) — *renombrar a singular*

Cambios mínimos:

1. `STR.es.profiles_title` → `"Perfil"`; `profiles_add` → `"Reemplazar perfil"`; `profiles_replaceWarn` ya está bien.
2. `STR.en.profiles_title` → `"Profile"`; `profiles_add` → `"Replace profile"`.
3. En `Sidebar.items`, segundo elemento `T.nav_profiles` → cambiar string a `T.nav_profile` = `"Conexión"` / `"Connection"` o mantener `"Perfil"`.
4. Renombrar `list_profiles` y `remove_profile` está bien (la API queda igual) pero documentar en docstring "siempre devuelve 0 o 1 perfiles".

#### Opción A — *implementar multi-perfil de verdad* (más trabajo)

Backend:
1. `ClientConfig` ya soporta serialización a archivo. Crear `client/outwarp/profile_store.py` que gestione un directorio `%APPDATA%\OutWarp\profiles\<id>.json` y un `active.txt` con el id activo.
2. `Api.list_profiles()` → devolver N entradas; cada una con `id`, `name`, `endpoint`, `is_active`.
3. Nuevas APIs: `set_active_profile(id)`, `rename_profile(id, name)`.
4. `TunnelManager` se rebobina al cambiar el activo (igual que ya hace `import_profile`).

Frontend:
1. `Sidebar` muestra un selector compacto con el perfil activo (combobox) en lugar del bloque "OFFLINE" actual.
2. Pantalla *Import* lista todos los perfiles con su estado (activo / inactivo), botón "Activar" en cada uno, botón "Renombrar" en cada uno, "Eliminar" en cada uno, y "Importar nuevo" arriba a la derecha.

**Recomendación clara**: Opción B ahora. La Opción A debería discutirse después de la primera release.

---

### A.7 — Home conectado: stats expandidos

Hoy `<Stat label={T.download}/>`, `<Stat label={T.upload}/>`, `<Stat label={T.sessionTime}/>` (3 cards). Añadir:

- **Latencia** (`T.latency`): ping al peer WG. Backend: en `wireguard.py::get_tunnel_stats` ya hay `latest_handshake` — añadir una medición sencilla. Si es complicado en algún OS, mostrar "—" y suficiente.
- **Último handshake** (`T.lastHandshake`): hora del último handshake formateada como "hace 12s". Reusar la lógica `fmtAge` del servidor (mover a un módulo común — ver C.1).
- **Ubicación** (`T.location`): tras obtener el `exit_ip`, llamar a un servicio gratuito tipo `https://ipapi.co/<ip>/json/` para sacar `country_code` y `city`. Hacerlo en `_start_exit_ip_probe`:

```python
def _start_exit_ip_probe(self):
    def _probe():
        # … como ahora, obtener self._stats["exit_ip"] …
        # luego geolocalizar:
        ip = self._stats.get("exit_ip")
        if ip:
            try:
                with urllib.request.urlopen(f"https://ipapi.co/{ip}/json/", timeout=5) as r:
                    data = json.loads(r.read().decode("utf-8", "replace"))
                    loc = ", ".join(filter(None, [data.get("city"), data.get("country_name")]))
                    if loc:
                        self._stats["exit_location"] = loc
                        self._emit("stats", dict(self._stats))
            except Exception:
                pass
    threading.Thread(target=_probe, daemon=True, name="outwarp-exit-ip").start()
```

Layout:

```jsx
<div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
  <Stat label={T.download} value={fmtBps(stats.rx_bps)} sub={`↓ ${fmtBytes(stats.rx_total)} total`}/>
  <Stat label={T.upload}   value={fmtBps(stats.tx_bps)} sub={`↑ ${fmtBytes(stats.tx_total)} total`}/>
  <Stat label={T.sessionTime} value={fmtDuration(sessionSec)}/>
</div>
<div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
  <Stat label={T.latency} value={stats.latency_ms ? `${stats.latency_ms} ms` : "—"}/>
  <Stat label={T.lastHandshake} value={stats.last_handshake ? fmtAgo(stats.last_handshake) : "—"}/>
  <Stat label={T.location} value={stats.exit_location || "—"}/>
</div>
```

Donde `fmtAgo(epoch)` es:
```js
const fmtAgo = (epoch) => {
  if (!epoch) return "—";
  const d = Math.max(0, Math.floor(Date.now()/1000 - epoch));
  if (d < 60) return `hace ${d}s`;
  if (d < 3600) return `hace ${Math.floor(d/60)}m`;
  return `hace ${Math.floor(d/3600)}h`;
};
```

(La versión inglesa hay que hacerla i18n: pasar `T.fmtAgo_seconds`, etc., o más simple: usar `Intl.RelativeTimeFormat(lang)`.)

#### Stats payload — añadir campos
En `Api.__init__` ampliar `self._stats`:
```python
self._stats = {
    "tx_bps": 0, "rx_bps": 0,
    "tx_total": 0, "rx_total": 0,
    "session_start": 0, "last_handshake": 0,
    "exit_ip": "",
    "exit_location": "",
    "latency_ms": 0,
}
```

---

### A.8 — Logs del cliente: "saltar al final"

En `Logs` (`app.jsx`), añadir un botón flotante visible **sólo** cuando `!atBottomRef.current`:

```jsx
const [atBottom, setAtBottom] = useState(true);
const onScroll = () => {
  const el = ref.current;
  if (!el) return;
  const isBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
  atBottomRef.current = isBottom;
  setAtBottom(isBottom);
};

// dentro del JSX, hermano del scroller:
{!atBottom && (
  <button onClick={() => { ref.current.scrollTop = ref.current.scrollHeight; setAtBottom(true); }}
    style={{
      position: "absolute", right: 24, bottom: 24,
      padding: "6px 12px", borderRadius: 999,
      background: "var(--brand)", color: "#fff",
      fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer",
      boxShadow: "0 6px 18px -6px color-mix(in srgb, var(--brand) 60%, transparent)",
    }}>
    ↓ {T.logs_jumpBottom}
  </button>
)}
```

El `<section>` contenedor necesita `position: relative` para que el `position: absolute` funcione.

#### Copy
```js
// es
logs_jumpBottom: "Saltar al final",
// en
logs_jumpBottom: "Jump to bottom",
```

---

## B. SERVIDOR (`server/outwarp_server/ui/`)

### B.1 — i18n completo

`srv-data.jsx` ya define `SRV_STR.es` / `SRV_STR.en`. Falta mover el texto **hardcoded** que aparece en `app.jsx` del servidor. Lista exhaustiva:

#### En `SetupWizard`

| Texto actual | Clave a usar |
|---|---|
| `"Configuración inicial"` | `setup_title` |
| `"Levanta el servicio wstunnel + WireGuard en este servidor."` | `setup_sub` |
| `"Faltan dependencias. Instálalas antes de continuar."` | `setup_missingDeps` |
| `"no encontrado en $PATH"` (en `DepLine`) | `setup_depNotFound` |
| `"Endpoint (IP o dominio)"` | `setup_lblEndpoint` |
| `"Puerto WSS"` | `setup_lblPortWSS` |
| `"Puerto WireGuard (loopback)"` | `setup_lblPortWG` |
| `"Subred WG"` | `setup_lblSubnet` |
| `"Dirección del servidor WG"` | `setup_lblSrvAddr` |
| `"Instalando…"` | `setup_installing` |
| `"Instalar"` | `setup_install` |

#### En `Dashboard`

| `"Subred WG"` | `dash_subnet` |
| `"Puerto WG"` | `dash_wgPort` |
| `"Detalles del servidor"` | `dash_techDetails` |

#### En `ClientsScreen` / `ClientsTable`

| `"Generando…"` | `clients_generating` |
| `"Aún no hay clientes. Usa Añadir cliente para generar el primero."` | `clients_empty` |
| `"Estado"` | `clients_colStatus` |
| `"Endpoint"` (header) | `clients_colEndpoint` |
| `"no se pudo guardar"` | `clients_saveFailed` |
| `"✓ guardado en {path}"` | `clients_savedTo` (template `{path}`) |

#### En `ServiceScreen`

| `"Iniciar"` | `service_start` |
| `"Parar"` | `service_stop` |
| `"Iniciando…"` | `service_starting` |
| `"Error"` | `service_error` |

#### En `LogsScreen`

| `"Filtrar…"` | `logs_filter` |
| `"Limpiar"` | `logs_clear` |
| `"— sin entradas —"` | `logs_empty` |
| `"Registro"` / `"sub"` | `logs_title` / `logs_sub` ya existen |

#### En `SettingsScreen`

| `"Idioma"` | `set_language` |
| `"Tema"` | `set_theme` |
| `"Auto"` | `set_themeAuto` |
| `"Claro"` | `set_themeLight` |
| `"Oscuro"` | `set_themeDark` |
| `"Modo avanzado"` | `set_advanced` |
| `"Cambia la estética y muestra detalles técnicos"` | `set_advancedSub` |

#### Sidebar

| `"Iniciando…"` (status) | `starting` |
| `"Error"` (status) | `error` |

**Acción**: añadir todas estas claves en `SRV_STR.es` (textos arriba) y `SRV_STR.en` (traducir). Reemplazar las apariciones por `T.<key>`.

---

### B.2 — Portar `ConfirmDialog` al servidor

`ClientsTable.onRevoke` usa `window.confirm(T.revokeConfirm.replace(...))`. Reemplazar.

1. Crear `server/outwarp_server/ui/confirm.jsx`:

```jsx
const ConfirmDialog = ({ title, message, confirmLabel, cancelLabel, danger, onResult }) => {
  React.useEffect(() => {
    const onKey = (e) => {
      if (e.key === "Escape") onResult(false);
      else if (e.key === "Enter") onResult(true);
    };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onResult]);
  return (
    <div className="ow-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onResult(false); }}>
      <div className="ow-modal" role="dialog" aria-modal="true">
        {title && <div style={{ fontSize: 15, fontWeight: 600, marginBottom: 6 }}>{title}</div>}
        <div style={{ fontSize: 13, color: "var(--text-2)", lineHeight: 1.55 }}>{message}</div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 18 }}>
          <window.Btn kind="ghost" size="md" onClick={() => onResult(false)}>{cancelLabel}</window.Btn>
          <window.Btn kind={danger ? "danger" : "primary"} size="md" onClick={() => onResult(true)}>{confirmLabel}</window.Btn>
        </div>
      </div>
    </div>
  );
};

function useConfirmState() {
  const [pending, setPending] = React.useState(null);
  const confirm = React.useCallback((opts) => new Promise((resolve) => {
    setPending({ ...opts, resolve });
  }), []);
  const dialog = pending
    ? <ConfirmDialog {...pending} onResult={(v) => { pending.resolve(v); setPending(null); }}/>
    : null;
  return [confirm, dialog];
}

window.ConfirmDialog = ConfirmDialog;
window.useConfirmState = useConfirmState;
```

2. Cargarlo en `server/outwarp_server/ui/index.html` **antes** de `app.jsx`:
   ```html
   <script type="text/babel" src="confirm.jsx"></script>
   ```

3. Asegurar que `styles.css` del servidor tenga las clases `.ow-overlay` y `.ow-modal` (copiar las del cliente).

4. En `app.jsx` del servidor, dentro de `App`:
   ```jsx
   const [confirm, confirmDialog] = window.useConfirmState();
   // …
   return (
     <div data-theme={theme} style={…}>
       <Sidebar …/>
       <main …>
         {screen === "clients" && <ClientsScreen … confirm={confirm}/>}
         {/* etc — pasar confirm a los hijos que lo necesiten */}
       </main>
       {confirmDialog}
     </div>
   );
   ```

5. En `ClientsTable.onRevoke`:
   ```jsx
   const onRevoke = async (name) => {
     const ok = await confirm({
       title: T.revoke,
       message: T.revokeConfirm.replace("{name}", name),
       confirmLabel: T.revoke,
       cancelLabel: T.cancel,
       danger: true,
     });
     if (!ok) return;
     await api?.revoke_client(name);
   };
   ```

> A medio plazo (ver C.1) este componente debería vivir en un módulo compartido — pero copiarlo ahora es lo más pragmático.

---

### B.3 — Vista de detalle de cliente

Hoy *Clients* es una tabla y nada más. Añadir un panel/drawer al hacer click en una fila.

#### Backend

**`server/outwarp_server/api.py`** — añadir:

```python
def get_client(self, name: str) -> dict[str, Any]:
    """Datos extendidos de un cliente: la fila de list_clients() + clave pública,
    timestamp exacto del último handshake, endpoint dinámico, allowed-ips."""
    # buscar en self._mgr.list_clients() la entrada con .name == name
    # cruzar con get_live_peers() para datos en vivo

def regenerate_owcfg(self, name: str) -> dict[str, Any]:
    """Reconstruye el .owcfg de un cliente existente (no rota claves;
    sólo reconstruye el archivo). Devuelve {"ok": True, "owcfg_base64": "…"}.
    Útil cuando el usuario perdió el .owcfg original."""

def rotate_client_keys(self, name: str) -> dict[str, Any]:
    """Genera un nuevo par de claves WG para un cliente existente y un .owcfg
    nuevo. La clave pública anterior queda revocada en el peer-list.
    Devuelve {"ok": True, "owcfg_base64": "…"}."""
```

#### Frontend

Añadir state al `ClientsScreen`:
```jsx
const [selected, setSelected] = useState(null); // nombre o null
```

`ClientsTable` recibe `onRowClick` y dispara `setSelected(c.name)`.

Nuevo componente `ClientDetailDrawer` (panel derecho 480px de ancho):

```jsx
const ClientDetailDrawer = ({ T, api, name, onClose, confirm }) => {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");

  useEffect(() => {
    if (!api || !name) return;
    api.get_client(name).then(setInfo);
  }, [api, name]);

  const onRegenerate = async () => {
    setBusy(true);
    const r = await api.regenerate_owcfg(name);
    if (r.ok) {
      const save = await api.save_owcfg(name, r.owcfg_base64);
      if (save.ok) setMsg(T.clients_savedTo.replace("{path}", save.path));
    }
    setBusy(false);
  };

  const onRotate = async () => {
    const ok = await confirm({
      title: T.clientDetail_rotateTitle,
      message: T.clientDetail_rotateConfirm,
      confirmLabel: T.clientDetail_rotate,
      cancelLabel: T.cancel,
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    const r = await api.rotate_client_keys(name);
    if (r.ok) {
      const save = await api.save_owcfg(name, r.owcfg_base64);
      if (save.ok) setMsg(T.clients_savedTo.replace("{path}", save.path));
    }
    setBusy(false);
  };

  return (
    <aside className="ow-drawer">
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 20px", borderBottom: "1px solid var(--line)" }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>{name}</div>
        <button onClick={onClose} className="ow-link">{T.close}</button>
      </header>
      {info ? (
        <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
          <KV k={T.ipAssigned}      v={info.address}/>
          <KV k={T.clientDetail_pubkey} v={info.public_key} mono/>
          <KV k={T.lastHandshake}   v={fmtAgeFull(info.last_handshake_seconds_ago)}/>
          <KV k={T.transferred}     v={`↓ ${fmtBytes(info.rx_bytes)} · ↑ ${fmtBytes(info.tx_bytes)}`}/>
          <KV k="Endpoint"          v={info.endpoint || "—"} mono/>
          <KV k={T.clientDetail_allowed} v={info.allowed_ips?.join(", ") || "—"} mono last/>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            <window.Btn kind="primary" size="md" onClick={onRegenerate} disabled={busy}>
              {T.clientDetail_regenOwcfg}
            </window.Btn>
            <window.Btn kind="ghost" size="md" onClick={onRotate} disabled={busy}>
              {T.clientDetail_rotate}
            </window.Btn>
            <window.Btn kind="danger" size="md"
                        onClick={async () => {
                          const ok = await confirm({
                            title: T.revoke, message: T.revokeConfirm.replace("{name}", name),
                            confirmLabel: T.revoke, cancelLabel: T.cancel, danger: true,
                          });
                          if (ok) { await api.revoke_client(name); onClose(); }
                        }}>
              {T.revoke}
            </window.Btn>
          </div>
          {msg && <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-2)" }}>{msg}</div>}
        </div>
      ) : (
        <div style={{ padding: 20, color: "var(--text-3)" }}>{T.loading}</div>
      )}
    </aside>
  );
};
```

Y en `styles.css` del servidor:

```css
.ow-drawer {
  position: fixed; right: 0; top: 0; bottom: 0; width: 480px;
  background: var(--bg-2); border-left: 1px solid var(--line);
  box-shadow: -16px 0 32px -16px rgba(0,0,0,.25);
  display: flex; flex-direction: column; overflow: auto;
  z-index: 30;
  animation: ow-drawer-in .22s ease-out;
}
@keyframes ow-drawer-in {
  from { transform: translateX(20px); opacity: 0; }
  to   { transform: translateX(0);    opacity: 1; }
}
```

#### Copy

```js
// es
close: "Cerrar",
loading: "Cargando…",
clientDetail_pubkey: "Clave pública",
clientDetail_allowed: "Allowed IPs",
clientDetail_regenOwcfg: "Regenerar .owcfg",
clientDetail_rotate: "Rotar claves",
clientDetail_rotateTitle: "Rotar las claves del cliente",
clientDetail_rotateConfirm: "Generar nuevas claves invalida el .owcfg actual del cliente. " +
                            "Tendrás que reenviarle el nuevo. ¿Continuar?",

// en
close: "Close",
loading: "Loading…",
clientDetail_pubkey: "Public key",
clientDetail_allowed: "Allowed IPs",
clientDetail_regenOwcfg: "Regenerate .owcfg",
clientDetail_rotate: "Rotate keys",
clientDetail_rotateTitle: "Rotate client keys",
clientDetail_rotateConfirm: "Generating new keys invalidates the client's current .owcfg. " +
                            "You'll have to send the new one. Continue?",
```

---

### B.4 — Servidor: export de logs + filtro por nivel

#### Backend

`server/outwarp_server/api.py` ya tiene `clear_logs`. Añadir:

```python
def export_logs(self) -> dict[str, Any]:
    # idéntico a Api.export_logs del cliente: pide save dialog y escribe
    # las líneas del buffer en plano.
```

#### Frontend

En `LogsScreen` reemplazar la header por la versión del cliente (con `<select>` de nivel y `<Btn>` Export). El nivel del log entry ya está en `l.level`. Adaptar:

```jsx
const LEVELS = [
  ["all", T.logs_levelAll], ["info", "INFO"], ["warn", "WARN"],
  ["error", "ERROR"], ["debug", "DEBUG"],
];
const [level, setLevel] = useState("all");
const [exportMsg, setExportMsg] = useState("");

const filtered = logs.filter((l) =>
  (level === "all" || l.level === level) &&
  (!filter || l.msg.toLowerCase().includes(filter.toLowerCase()))
);

const doExport = async () => {
  const r = await api.export_logs();
  if (r?.ok) { setExportMsg(T.logs_exported); setTimeout(() => setExportMsg(""), 3000); }
};
```

#### Copy (reuso del cliente — añadir a `SRV_STR`)

```js
logs_level: "Nivel" / "Level",
logs_levelAll: "Todos" / "All",
logs_export: "Exportar" / "Export",
logs_exported: "✓ Registro exportado" / "✓ Log exported",
```

---

### B.5 — Editar configuración del servidor desde *Settings*

Hoy *Settings* del servidor sólo muestra `status.port`, `status.subnet`, `status.cert_fingerprint_sha256` en **read-only**. Hay que permitir editar:

| Campo | Backend method | Comportamiento |
|---|---|---|
| Puerto WSS | `api.change_port(port: int)` | Reescribe systemd unit + reinicia wstunnel. |
| Puerto WG | `api.change_wg_port(port: int)` | Reescribe wg conf + `wg syncconf`. |
| Endpoint | `api.change_endpoint(host: str)` | Actualiza config; advertir que **los .owcfg ya emitidos seguirán funcionando** sólo si el endpoint sigue siendo alcanzable. |
| Rotar certificado TLS | `api.rotate_tls_cert()` | Regenera cert auto-firmado y devuelve el nuevo fingerprint. **Invalida todos los `.owcfg` emitidos** — el usuario debe regenerarlos. |

#### Frontend (componente nuevo `ServerConfigEditor`)

```jsx
const ServerConfigEditor = ({ T, api, status, confirm }) => {
  const [form, setForm] = useState({
    port: status.port, wg_listen_port: status.wg_listen_port,
    endpoint: status.endpoint,
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  const dirty = form.port !== status.port
             || form.wg_listen_port !== status.wg_listen_port
             || form.endpoint !== status.endpoint;

  const save = async () => {
    const ok = await confirm({
      title: T.srvCfg_applyTitle,
      message: T.srvCfg_applyConfirm,
      confirmLabel: T.srvCfg_apply, cancelLabel: T.cancel,
    });
    if (!ok) return;
    setBusy(true); setErr(""); setMsg("");
    const r = await api.update_server_config(form);
    setBusy(false);
    if (r.ok) setMsg(T.srvCfg_applied);
    else setErr(r.error);
  };

  const rotate = async () => {
    const ok = await confirm({
      title: T.srvCfg_rotateTitle,
      message: T.srvCfg_rotateConfirm,
      confirmLabel: T.srvCfg_rotate, cancelLabel: T.cancel,
      danger: true,
    });
    if (!ok) return;
    setBusy(true);
    const r = await api.rotate_tls_cert();
    setBusy(false);
    if (r.ok) setMsg(T.srvCfg_rotated.replace("{fp}", r.fingerprint));
    else setErr(r.error);
  };

  return (
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)",
                      borderRadius: 14, padding: 18 }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{T.srvCfg_title}</div>
      <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 14 }}>{T.srvCfg_sub}</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Field label={T.set_port} value={form.port}
               onChange={(v) => setForm(f => ({...f, port: Number(v)}))}/>
        <Field label={T.dash_wgPort} value={form.wg_listen_port}
               onChange={(v) => setForm(f => ({...f, wg_listen_port: Number(v)}))}/>
        <div style={{ gridColumn: "1 / -1" }}>
          <Field label="Endpoint" value={form.endpoint}
                 onChange={(v) => setForm(f => ({...f, endpoint: v}))} mono/>
        </div>
      </div>

      <div style={{ marginTop: 14, display: "flex", gap: 8 }}>
        <window.Btn kind="primary" size="md" onClick={save} disabled={!dirty || busy}>
          {T.srvCfg_apply}
        </window.Btn>
      </div>

      <hr style={{ margin: "20px 0", border: "none", borderTop: "1px solid var(--line)" }}/>

      <div style={{ fontSize: 13, fontWeight: 600 }}>{T.srvCfg_rotateGroup}</div>
      <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{T.srvCfg_rotateGroupSub}</div>
      <div style={{ marginTop: 12 }}>
        <window.Btn kind="danger" size="md" onClick={rotate} disabled={busy}>
          {T.srvCfg_rotate}
        </window.Btn>
      </div>

      {msg && <div style={{ marginTop: 12, color: "var(--brand-2)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{msg}</div>}
      {err && <div style={{ marginTop: 12, color: "var(--brand-bad)", fontFamily: "var(--font-mono)", fontSize: 12 }}>{err}</div>}
    </section>
  );
};
```

Añadir un `Field`:
```jsx
const Field = ({ label, value, onChange, mono }) => (
  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
    <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text-2)" }}>{label}</span>
    <input value={value} onChange={(e) => onChange(e.target.value)}
      style={{
        height: 32, padding: "0 10px", borderRadius: 8,
        border: "1px solid var(--line-strong)", background: "var(--bg)",
        color: "var(--text)", outline: "none",
        fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)", fontSize: 13,
      }}/>
  </label>
);
```

Renderizarlo en `SettingsScreen` debajo del `DoctorPanel`.

#### Copy

```js
// es
srvCfg_title: "Configuración del servidor",
srvCfg_sub: "Cambios que requieren reiniciar el servicio.",
srvCfg_apply: "Aplicar cambios",
srvCfg_applyTitle: "Aplicar cambios",
srvCfg_applyConfirm: "El servicio se reiniciará para aplicar los cambios. Las conexiones activas se cortarán durante unos segundos. ¿Continuar?",
srvCfg_applied: "✓ Cambios aplicados",
srvCfg_rotateGroup: "Rotar certificado TLS",
srvCfg_rotateGroupSub: "Genera un certificado auto-firmado nuevo. Todos los .owcfg emitidos dejarán de validar — tendrás que regenerarlos.",
srvCfg_rotate: "Rotar certificado",
srvCfg_rotateTitle: "Rotar certificado TLS",
srvCfg_rotateConfirm: "Esto invalidará todos los .owcfg que hayas distribuido. Tendrás que regenerar y reenviar uno nuevo por cliente. ¿Continuar?",
srvCfg_rotated: "✓ Certificado rotado · fp={fp}",

// en
srvCfg_title: "Server configuration",
srvCfg_sub: "Changes that require restarting the service.",
srvCfg_apply: "Apply changes",
srvCfg_applyTitle: "Apply changes",
srvCfg_applyConfirm: "The service will restart to apply changes. Active connections will drop for a few seconds. Continue?",
srvCfg_applied: "✓ Changes applied",
srvCfg_rotateGroup: "Rotate TLS certificate",
srvCfg_rotateGroupSub: "Generates a new self-signed certificate. All issued .owcfg files will stop validating — you'll have to regenerate them.",
srvCfg_rotate: "Rotate certificate",
srvCfg_rotateTitle: "Rotate TLS certificate",
srvCfg_rotateConfirm: "This invalidates every .owcfg you've distributed. You'll need to regenerate and resend a new one to every client. Continue?",
srvCfg_rotated: "✓ Certificate rotated · fp={fp}",
```

---

### B.6 — Setup wizard con stepper y probe de puerto

El setup actual es un único formulario con un botón "Instalar" que se queda en spinner durante toda la instalación. Rediseño:

#### Backend — fases

Modificar `Api.run_setup` (servidor) para emitir progreso. En lugar de devolver `{ok: true}` al final, devolver una **promesa larga** con un canal de eventos. Mecanismo:

1. `Api.run_setup(params)` **no bloquea**; lanza un thread y devuelve `{ok: True, job_id: "..."}` inmediatamente.
2. El thread emite eventos `outwarp:setup_progress` con `{ phase: "deps"|"cert"|"systemd"|"probe"|"done", status: "running"|"ok"|"fail", message: "..." }`.
3. Al terminar emite `outwarp:setup_done` con `{ ok: true, fingerprint, ... }` o `{ ok: false, error: "..." }`.

#### Frontend

```jsx
const SetupWizard = ({ T, api, theme, onDone }) => {
  // Estado del formulario igual que ahora.
  const [phase, setPhase] = useState(null); // null | running phase
  const [phaseStates, setPhaseStates] = useState({});
  const [error, setError] = useState("");

  useBridgeEvent("setup_progress", useCallback((d) => {
    setPhase(d.phase);
    setPhaseStates(s => ({ ...s, [d.phase]: { status: d.status, message: d.message } }));
  }, []));

  useBridgeEvent("setup_done", useCallback(async (d) => {
    setPhase(null);
    if (d.ok) onDone();
    else setError(d.error || "");
  }, [onDone]));

  const onInstall = async () => { /* api.run_setup(form) */ };

  if (phase !== null) {
    return <SetupProgress T={T} phase={phase} phaseStates={phaseStates}/>;
  }
  return <SetupForm … />;
};

const SETUP_PHASES = [
  ["deps",    "setup_phaseDeps"],
  ["cert",    "setup_phaseCert"],
  ["systemd", "setup_phaseService"],
  ["probe",   "setup_phaseProbe"],
  ["done",    "setup_phaseDone"],
];

const SetupProgress = ({ T, phase, phaseStates }) => {
  const currentIdx = SETUP_PHASES.findIndex(([k]) => k === phase);
  return (
    <div style={{ /* centrado */ }}>
      <h2>{T.setup_installing}</h2>
      <ol style={…}>
        {SETUP_PHASES.map(([k, sk], i) => {
          const s = phaseStates[k]?.status ||
                    (i < currentIdx ? "ok" : i === currentIdx ? "running" : "pending");
          return (
            <li key={k}>
              <PhaseIcon status={s}/>
              <div>
                <div>{T[sk]}</div>
                {phaseStates[k]?.message && (
                  <div style={{ fontSize: 11, color: "var(--text-3)",
                                fontFamily: "var(--font-mono)" }}>
                    {phaseStates[k].message}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>
    </div>
  );
};
```

#### Validación inline del formulario

En `SetupForm` añadir:

```jsx
const errors = {
  port: (form.port < 1 || form.port > 65535) ? T.setup_errPort : "",
  wgPort: …,
  subnet: !/^\d+\.\d+\.\d+\.\d+\/\d+$/.test(form.subnet) ? T.setup_errSubnet : "",
  srvAddr: …,
};
const valid = Object.values(errors).every(e => !e);
```

Mostrar cada error debajo del input correspondiente en color `var(--brand-bad)`.

#### Probe de puerto

El **paso `probe`** dentro del setup llama a un servicio externo tipo `https://portchecker.io/api/<port>` (o equivalente — el repo seguro tiene preferencia). Si falla:
- `phaseStates.probe = { status: "warn", message: "El servidor está instalado pero el puerto X no es alcanzable desde fuera. Revisa firewall / port-forward." }`
- El setup termina igualmente con `ok: true` (el servicio está arriba aunque no llegue tráfico externo aún), pero la UI muestra un aviso amarillo y un botón "Reintentar probe" / "Saltar y continuar".

Backend correspondiente:

```python
def probe_external_port(self) -> dict[str, Any]:
    """Llama a un servicio externo para comprobar que el puerto WSS es
    alcanzable desde internet. Devuelve {"ok": bool, "reachable": bool,
    "detail": "..."}."""
```

Botón en *Settings* "Probar puerto desde fuera" que llama a esto.

#### Copy

```js
// es
setup_phaseDeps: "Comprobando dependencias",
setup_phaseCert: "Generando certificado TLS",
setup_phaseService: "Instalando servicio systemd",
setup_phaseProbe: "Probando conectividad externa",
setup_phaseDone: "Listo",
setup_errPort: "Puerto inválido (1-65535)",
setup_errSubnet: "Formato CIDR inválido (ej. 10.0.0.0/24)",
setup_probeRetry: "Reintentar probe",
setup_probeSkip: "Continuar sin probar",
setup_detectIp: "Detectar IP pública",

// en — traducir literalmente
```

---

### B.7 — Pantalla "Acerca de" (servidor)

Misma estructura que A.5 pero adaptada al servidor:

1. En el sidebar añadir `["about", T.nav_about, …]`.
2. `Api.get_app_info()` análogo al del cliente.
3. Componente `About` casi idéntico (cambia el blurb).

#### Copy

```js
nav_about: "Acerca de" / "About",
about_sub: "Versión, licencias y créditos." / "Version, licenses and credits.",
about_blurb: "outwarp-server orquesta wstunnel y WireGuard como servicio del sistema. " +
             "Genera certificados auto-firmados y .owcfg por cliente — sin dominio ni CA.",
// rest same as client
```

---

### B.8 — Pulido visual / a11y / consistencia (ambos)

1. **Foco visible**: en `app.jsx` del servidor hay un montón de `<button style={{ all: "unset" }}>`. Reemplazar por la clase `.ow-btn` (o crear una clase equivalente para botones "icon-only"). Añadir a `styles.css`:
   ```css
   .ow-iconbtn:focus-visible {
     outline: 2px solid var(--brand);
     outline-offset: 2px;
     border-radius: 6px;
   }
   ```
2. **Loading state del servidor**: en `App` cuando `!status`, reemplazar `"cargando…"` plano por el splash con `WSLogoMark` (igual que el cliente).
3. **Tabla de clientes vacía**: añadir un ícono SVG (silueta de persona) encima del texto "Aún no hay clientes…" para igualar la pantalla de import del cliente.
4. **Tabla de clientes — orden y filtro**:
   ```jsx
   const [sortKey, setSortKey] = useState("name");
   const [sortDir, setSortDir] = useState("asc"); // "asc" | "desc"
   const [filter, setFilter] = useState("");
   ```
   Click en `<Th>` hace toggle de `sortDir` o cambia `sortKey`. Input de filtro arriba a la derecha.
5. **Banner de bridge muerto**: en ambos, si el poll JS-side falla 3 veces seguidas con catch (hoy se silencia con `catch (_) {}`), mostrar un banner rojo arriba diciendo "Conexión perdida con la app. Reinicia OutWarp." Implementar como un state `bridgeAlive` que se pone a `false` tras N fallos.
6. **Iconografía consistente** (opcional pero ayuda mucho): crear `client/outwarp/ui/icons.jsx` y `server/outwarp_server/ui/icons.jsx`:
   ```jsx
   const ICONS = {
     home:     "M3 11 L12 3 L21 11 M5 10 V20 H19 V10",
     profile:  "M12 8 m-4 0 a4 4 0 1 0 8 0 a4 4 0 1 0 -8 0 M4 21 …",
     logs:     "M5 4 H19 V20 H5 Z M8 8 H16 M8 12 H16 M8 16 H13",
     settings: "M12 9 a3 3 0 1 1 0 6 a3 3 0 1 1 0 -6 …",
     about:    "M12 8 V13 M12 16 V16.01 M3 12 a9 9 0 1 1 18 0 a9 9 0 1 1 -18 0",
     // …
   };
   const Icon = ({ name, size = 16, stroke = "currentColor" }) => (
     <svg width={size} height={size} viewBox="0 0 24 24" fill="none"
          stroke={stroke} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
       <path d={ICONS[name]}/>
     </svg>
   );
   window.Icon = Icon;
   ```
   Y migrar los `<svg>` inline de `Sidebar.items` a `<Icon name="home"/>`.

---

## C. Compartido / refactor

### C.1 — Mover atomos a un módulo común (recomendado pero no bloqueante)

Hoy `shared.jsx` del cliente y del servidor son **dos archivos distintos**. Cada uno define `Btn`, `Pill`, `StatusDot`, `Toggle` con código idéntico, y el i18n diverge.

Propuesta:

1. Crear `shared-ui/` en la raíz del repo con `atoms.jsx`, `confirm.jsx`, `format.js`, `bridge.jsx` (helpers `waitForBridge`, `useBridgeEvent`).
2. En el setup de cada paquete copiar (`shutil.copytree`) o crear symlinks durante `pip install -e .` — o más simple: `installer/linux/install.sh` y `installer/windows/install.ps1` hacen la copia hacia el directorio `ui/` correspondiente.
3. El i18n se queda **separado** (cliente y servidor tienen vocabularios distintos), pero los strings genéricos (`cancel`, `close`, `loading`, `error`, `retry`) podrían moverse a `shared-ui/common-strings.js` y mergearse en cada `STR.es` / `STR.en`.

Esto reduce el bug-surface (un fix de `Btn` se aplica en ambos a la vez).

### C.2 — Helpers de formato compartidos

Hoy:
- `client/outwarp/ui/app.jsx` define `fmtBps`, `fmtBytes`, `fmtDuration`, `fmtClock`.
- `server/outwarp_server/ui/app.jsx` define `fmtBytes`, `fmtAge`.

Mover todos a `shared-ui/format.js` y exponer por `window.fmt = { bps, bytes, duration, clock, age, ago }`.

---

## D. Checklist de aceptación

Al final de toda la implementación se debe poder verificar:

- [ ] Ningún `grep` en `client/outwarp/ui` ni `server/outwarp_server/ui` encuentra `window.confirm(`.
- [ ] Ninguna cadena en español visible en runtime cuando `language === "en"` (servidor incluido).
- [ ] `grep "STR\." client/outwarp/ui/` y `grep "SRV_STR\." server/outwarp_server/ui/` no listan ninguna clave huérfana ni faltante.
- [ ] Cambiar cualquier toggle en *Settings* (cliente o servidor) persiste tras reinicio.
- [ ] `kill_switch=ON` bloquea el tráfico cuando el túnel cae (verificable con `curl ifconfig.me` tras `wg-quick down` forzado).
- [ ] `auto_reconnect=OFF` no relanza el túnel tras caer.
- [ ] `start_at_boot=ON` crea el artefacto de autostart del OS y lo elimina al volver a `OFF`.
- [ ] Pantalla *Connecting* del cliente muestra los 6 pasos progresando.
- [ ] *Import* del cliente acepta el `.owcfg` también como texto pegado.
- [ ] Pantalla *About* abre el repo en el navegador externo (no en la propia ventana pywebview).
- [ ] Click en una fila de la tabla de clientes del servidor abre el drawer; el botón "Regenerar .owcfg" produce un archivo válido importable por el cliente; "Rotar claves" invalida el `.owcfg` antiguo.
- [ ] El setup wizard del servidor muestra los 5 pasos con su estado y, si el probe externo falla, ofrece "Reintentar" / "Continuar sin probar".
- [ ] Cambiar el puerto WSS desde *Settings* reinicia el servicio y los clientes activos reconectan solos (esto último depende del backend; al menos la UI debe reflejarlo).
- [ ] Rotar el certificado TLS muestra el nuevo fingerprint y un aviso explícito sobre invalidar `.owcfg` antiguos.

---

## E. Orden recomendado de implementación

1. **A.1** (limpieza de strings) y **B.1** (i18n completo del servidor) — barre la inconsistencia base. 1 sesión.
2. **A.2** (toggles cableados) — pero **sólo** los que tienen backend factible: `auto_reconnect` y `minimize_to_tray`. Diferir `kill_switch` y `start_at_boot` si requieren trabajo de plataforma extenso. Marcarlos como "próximamente" en Settings con un `disabled` si hace falta.
3. **B.2** (`ConfirmDialog` en servidor).
4. **A.3** (stepper de Connecting) — requiere coordinar con `tunnel.py`. Si es complicado, dejar el step "wg" como único activo y los demás como placeholder.
5. **A.5** + **B.7** (About en ambos) — fácil, alto impacto visual.
6. **A.4** (Import con pegar texto) y **A.8** (jump-to-bottom) — quick wins.
7. **A.7** (stats expandidos) — depende de `tunnel.py` para latency; si no, dejar `latency: "—"`.
8. **B.3** (vista de detalle de cliente) — feature pedida pero requiere backend nuevo.
9. **B.4** (logs servidor: export + filtro).
10. **B.6** (setup wizard con stepper).
11. **B.5** (editor de configuración del servidor) — destructivo, hacerlo último.
12. **B.8** (pulido) — barrido final.
13. **A.6** decisión: si Opción B, hacerla en cualquier momento (15 min). Si Opción A, posponer a v0.2.
14. **C.1** / **C.2** refactor — sólo si el equipo lo ve útil.

---

## F. Notas para Claude Code

- **No** romper los tests existentes (~185 entre cliente y servidor). Tras cada tarea correr `pytest` en ambos paquetes.
- **No** cambiar el contrato existente de eventos `outwarp:status`, `outwarp:stats`, `outwarp:log`, `outwarp:settings`, `outwarp:clients` — sólo **añadir** campos. Los nuevos eventos (`outwarp:setup_progress`, `outwarp:setup_done`) son nuevos canales.
- **No** introducir build steps (Webpack, Vite, tsc): el proyecto sirve JSX crudo con Babel-standalone. Cualquier dependencia extra debe entrar por `<script src=…>` en `index.html`, no por `npm install`.
- **No** añadir librerías de UI externas (Material, Chakra, etc.). Todo se construye con `Btn`/`Pill`/`StatusDot`/`Toggle` + CSS tokens.
- Al tocar `shared.jsx` (cliente) o `srv-data.jsx` (servidor), **mantener orden alfabético no es obligatorio** pero **agrupar por sección** (nav, settings, logs, etc.) con un comentario `//` arriba — facilita revisión.
- Al añadir un emit Python → JS, comprobar que `_emit` se llame **después** de `bind_window`; si no, perder el primer evento. Backfill desde un poll JS-side (patrón que ya existe en ambos `app.jsx`).
- Cuando el handler de un evento mute `setState` con función de fold (`setLogs(l => [...l, e])`), envolver el handler en `useCallback(…, [])` para evitar re-suscripciones en cada render — el patrón ya está aplicado en los `useBridgeEvent` actuales, mantenerlo.

Fin.
