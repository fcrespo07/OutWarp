// i18n + shared UI primitives for OutWarp

const STR = {
  es: {
    // Window title bar
    win_minimize: "Minimizar",
    win_maximize: "Maximizar",
    win_restore: "Restaurar",
    win_close: "Cerrar",
    // Empty state
    welcomeTitle: "Conéctate a tu túnel",
    welcomeSub: "Importa un archivo de configuración .owcfg que te haya enviado tu servidor.",
    importFile: "Importar archivo",
    importDrop: "Arrastra el .owcfg aquí",
    importPaste: "Pega el contenido del .owcfg",
    importHint: "Formato soportado: .owcfg generado por outwarp-server add-client",
    import_tabFile: "Desde archivo",
    import_tabPaste: "Pegar texto",
    import_loadFromPaste: "Importar",

    // States
    disconnected: "Desconectado",
    connecting: "Conectando…",
    handshake: "Handshake WireGuard",
    reconnecting: "Reconectando",
    connected: "Conectado",
    error: "Error de conexión",

    // Big actions
    connect: "Conectar",
    disconnect: "Desconectar",
    cancel: "Cancelar",

    // Stats
    publicIp: "IP pública",
    location: "Ubicación",
    latency: "Latencia",
    upload: "Subida",
    download: "Bajada",
    transferred: "Transferido",
    sessionTime: "Tiempo de sesión",
    lastHandshake: "Último handshake",
    endpoint: "Endpoint",
    fingerprint: "Huella TLS",

    // Nav / sections
    nav_home: "Conexión",
    nav_profiles: "Perfil",
    nav_logs: "Registro",
    nav_settings: "Ajustes",
    nav_about: "Acerca de",
    about_sub: "Información de la aplicación y de sus componentes.",
    about_blurb: "Cliente OutWarp: levanta un túnel WireGuard sobre WebSocket usando wstunnel como transporte, para redes que bloquean UDP.",
    about_openRepo: "Abrir repositorio",
    about_thirdParty: "Componentes de terceros",
    about_openUrl: "Abrir →",
    about_disclaimer: "OutWarp se distribuye bajo licencia MIT. WireGuard es marca registrada de Jason A. Donenfeld. wstunnel es un proyecto independiente de erebe.",
    // Updates
    upd_check: "Buscar actualizaciones",
    upd_checking: "Buscando…",
    upd_current: "Estás en la última versión.",
    upd_available: "Nueva versión disponible:",
    upd_now: "Actualizar ahora",
    upd_downloading: "Descargando…",
    upd_applying: "Aplicando en segundo plano. La app se reiniciará sola…",
    upd_error: "No se pudo comprobar la actualización.",
    upd_seeReleases: "Ver releases",
    upd_linux: "Para actualizar en Linux, ejecuta este comando:",
    upd_copy: "Copiar",
    upd_copied: "Copiado",

    // Settings
    set_checkUpdates: "Buscar actualizaciones al iniciar",
    set_checkUpdatesSub: "Comprobar si hay una versión nueva al abrir Ajustes.",
    set_killSwitch: "Kill switch",
    set_killSwitchSub: "Bloquea todo el tráfico de internet si el túnel se cae.",
    set_autoconnect: "Reintento automático",
    set_autoconnectSub: "Reconectar automáticamente si el túnel se cae mientras está activo.",
    set_autoconnectLaunch: "Conectar al abrir",
    set_autoconnectLaunchSub: "Levantar el túnel automáticamente al iniciar OutWarp.",
    set_startup: "Iniciar al iniciar sesión",
    set_startupSub: "Arrancar OutWarp automáticamente al entrar en tu cuenta de usuario.",
    set_minimizeTray: "Minimizar a la bandeja",
    set_minimizeTraySub: "Al iniciar OutWarp, mostrar sólo el icono de la bandeja del sistema.",
    set_advanced: "Modo avanzado",
    set_advancedSub: "Mostrar IPs, claves y huella del certificado",
    set_tlsIntercept: "Permitir redes que inspeccionan TLS",
    set_tlsInterceptSub: "Continúa aunque la huella del certificado no coincida (proxies de instituto/empresa). WireGuard sigue cifrando el tráfico de extremo a extremo.",
    set_language: "Idioma",
    set_theme: "Tema",
    set_themeAuto: "Automático",
    set_themeLight: "Claro",
    set_themeDark: "Oscuro",
    set_groupAppearance: "Apariencia",
    set_groupConnection: "Conexión",
    set_groupSystem: "Sistema",
    set_groupUpdates: "Actualizaciones",
    set_errorTitle: "No se pudo aplicar el ajuste",

    // Logs
    logs_title: "Registro de actividad",
    logs_clear: "Limpiar",
    logs_export: "Exportar",
    logs_filter: "Filtrar…",

    // Profiles
    profiles_title: "Perfil",
    profiles_add: "Reemplazar perfil",
    profiles_active: "Activo",
    profiles_replaceWarn: "Ya tienes una conexión configurada. Importar otra reemplazará la actual. ¿Continuar?",

    // Profile editor
    edit_title: "Ajustes del perfil",
    edit_sub: "Valores de conexión asignados por tu servidor.",
    edit_open: "Modificar conexión",
    edit_disclaimerTitle: "Estás a punto de editar la configuración",
    edit_disclaimerBody: "Estos valores vienen de tu servidor y normalmente no necesitan cambiarse. Una configuración incorrecta puede impedir que el túnel conecte. Si algo deja de funcionar, usa «Reiniciar a predeterminados».",
    edit_disclaimerAck: "Entiendo, quiero editar",
    edit_name: "Nombre del perfil",
    edit_mtu: "MTU",
    edit_mtuHint: "Entre 576 y 1500. Por defecto 1380.",
    edit_dns: "Servidores DNS",
    edit_dnsHint: "Separados por comas.",
    edit_clientIp: "IP del cliente",
    edit_clientIpHint: "Debe coincidir con la asignada en el servidor (ej. 10.0.0.2/32).",
    edit_bypass: "Endpoint",
    edit_bypassHint: "IP(s) del servidor que quedan fuera del túnel. Separadas por comas.",
    edit_maxAttempts: "Reintentos de reconexión",
    edit_delays: "Tiempos de reconexión (s)",
    edit_delaysHint: "Segundos entre reintentos, separados por comas.",
    edit_save: "Guardar cambios",
    edit_reset: "Reiniciar a predeterminados",
    edit_cancel: "Cancelar",
    edit_reconnectNote: "El túnel se reconectará automáticamente para aplicar los cambios.",
    edit_saved: "✓ Ajustes guardados",
    edit_resetDone: "✓ Ajustes restaurados a los valores originales",
    edit_resetConfirm: "¿Restaurar todos los ajustes a como estaban al importar el perfil? Se perderán los cambios locales.",
    edit_resetTitle: "Reiniciar ajustes",

    // Confirmations
    confirm_continue: "Continuar",
    confirm_reset: "Reiniciar",
    profiles_remove: "Eliminar",
    profiles_removeTitle: "Eliminar perfil",
    profiles_removeConfirm: "¿Eliminar el perfil activo? Tendrás que importar de nuevo el .owcfg.",
    profiles_replaceTitle: "Reemplazar conexión",

    // Errors / status
    error_title: "No se pudo conectar",
    error_genericBody: "Puede ser un error de huella TLS, un endpoint inalcanzable o un fallo de WireGuard.",
    error_checkLog: "Revisa el registro para el detalle completo.",
    error_importNew: "Importar nuevo .owcfg",
    retry: "Reintentar",
    bootError: "No se pudo iniciar la interfaz.",
    reconnectAttempt: "Intento",
    importReading: "Leyendo archivo…",
    errorUnknown: "Error desconocido",
    techDetails: "Detalles técnicos",
    clientIp: "IP del cliente",

    // Logs (extra)
    logs_empty: "— sin entradas —",
    logs_level: "Nivel",
    logs_levelAll: "Todos",
    logs_exported: "✓ Registro exportado",
    logs_jumpBottom: "Saltar al final",

    // Connecting steps. No "step_route" — bypass IPs are excluded from
    // WG AllowedIPs at config-build time, not added as host routes after.
    step_resolve: "Resolviendo endpoint",
    step_tls: "Verificando certificado",
    step_wg: "Levantando interfaz WireGuard",
    step_ws: "Abriendo túnel WebSocket",
    step_done: "Listo",

    // Misc
    profile: "Perfil",
    home_ribbon: "Tu tráfico viaja cifrado por wstunnel → WireGuard.",
    home_clickToConnect: "Pulsa el botón para conectar.",
    home_secure_title: "Tráfico cifrado",
    home_secure_body: "WireGuard sobre WebSocket (wstunnel).",
    home_pinned_title: "Certificado anclado",
    home_pinned_body: "Verificación por huella SHA-256, sin DNS dinámico.",
    home_routing_title: "Ruteo automático",
    home_routing_body: "Bypass del endpoint y reconexión con backoff.",
    throughput_title: "Tráfico",
    throughput_window: "últimos {n} s",
    throughput_empty: "Recogiendo muestras…",
    notConnected: "Sin túnel activo",
  },
  en: {
    // Window title bar
    win_minimize: "Minimize",
    win_maximize: "Maximize",
    win_restore: "Restore",
    win_close: "Close",
    welcomeTitle: "Connect to your tunnel",
    welcomeSub: "Import a .owcfg configuration file shared by your server.",
    importFile: "Import file",
    importDrop: "Drop your .owcfg here",
    importPaste: "Paste your .owcfg contents",
    importHint: "Supported format: .owcfg generated by outwarp-server add-client",
    import_tabFile: "From file",
    import_tabPaste: "Paste text",
    import_loadFromPaste: "Import",

    disconnected: "Disconnected",
    connecting: "Connecting…",
    handshake: "WireGuard handshake",
    reconnecting: "Reconnecting",
    connected: "Connected",
    error: "Connection error",

    connect: "Connect",
    disconnect: "Disconnect",
    cancel: "Cancel",

    publicIp: "Public IP",
    location: "Location",
    latency: "Latency",
    upload: "Upload",
    download: "Download",
    transferred: "Transferred",
    sessionTime: "Session time",
    lastHandshake: "Last handshake",
    endpoint: "Endpoint",
    fingerprint: "TLS fingerprint",

    nav_home: "Connection",
    nav_profiles: "Profile",
    nav_logs: "Logs",
    nav_settings: "Settings",
    nav_about: "About",
    about_sub: "Application info and component licenses.",
    about_blurb: "OutWarp client: brings up a WireGuard tunnel over WebSocket using wstunnel as transport, for networks that block UDP.",
    about_openRepo: "Open repository",
    about_thirdParty: "Third-party components",
    about_openUrl: "Open →",
    about_disclaimer: "OutWarp is distributed under the MIT license. WireGuard is a registered trademark of Jason A. Donenfeld. wstunnel is an independent project by erebe.",
    // Updates
    upd_check: "Check for updates",
    upd_checking: "Checking…",
    upd_current: "You're on the latest version.",
    upd_available: "New version available:",
    upd_now: "Update now",
    upd_downloading: "Downloading…",
    upd_applying: "Applying in the background. The app will restart itself…",
    upd_error: "Couldn't check for updates.",
    upd_seeReleases: "View releases",
    upd_linux: "To update on Linux, run this command:",
    upd_copy: "Copy",
    upd_copied: "Copied",

    set_checkUpdates: "Check for updates on startup",
    set_checkUpdatesSub: "Check for a newer version when opening Settings.",
    set_killSwitch: "Kill switch",
    set_killSwitchSub: "Block all internet traffic if the tunnel drops.",
    set_autoconnect: "Automatic retry",
    set_autoconnectSub: "Reconnect automatically if the tunnel drops while active.",
    set_autoconnectLaunch: "Connect on launch",
    set_autoconnectLaunchSub: "Bring the tunnel up automatically when OutWarp starts.",
    set_startup: "Start at login",
    set_startupSub: "Launch OutWarp automatically when you sign in.",
    set_minimizeTray: "Minimize to system tray",
    set_minimizeTraySub: "On launch, show only the system tray icon.",
    set_advanced: "Advanced mode",
    set_advancedSub: "Show IPs, keys and certificate fingerprint",
    set_tlsIntercept: "Allow TLS-intercepting networks",
    set_tlsInterceptSub: "Connect even if the certificate fingerprint doesn't match (school/corporate proxies). WireGuard still encrypts your traffic end-to-end.",
    set_language: "Language",
    set_theme: "Theme",
    set_themeAuto: "Auto",
    set_themeLight: "Light",
    set_themeDark: "Dark",
    set_groupAppearance: "Appearance",
    set_groupConnection: "Connection",
    set_groupSystem: "System",
    set_groupUpdates: "Updates",
    set_errorTitle: "Couldn't apply the setting",

    logs_title: "Activity log",
    logs_clear: "Clear",
    logs_export: "Export",
    logs_filter: "Filter…",

    profiles_title: "Profile",
    profiles_add: "Replace profile",
    profiles_active: "Active",
    profiles_replaceWarn: "You already have a connection configured. Importing another will replace the current one. Continue?",

    edit_title: "Profile settings",
    edit_sub: "Connection values assigned by your server.",
    edit_open: "Modify connection",
    edit_disclaimerTitle: "You're about to edit the configuration",
    edit_disclaimerBody: "These values come from your server and rarely need changing. A wrong setting can stop the tunnel from connecting. If something breaks, use “Reset to defaults”.",
    edit_disclaimerAck: "I understand, let me edit",
    edit_name: "Profile name",
    edit_mtu: "MTU",
    edit_mtuHint: "Between 576 and 1500. Default 1380.",
    edit_dns: "DNS servers",
    edit_dnsHint: "Comma-separated.",
    edit_clientIp: "Client IP",
    edit_clientIpHint: "Must match the address assigned on the server (e.g. 10.0.0.2/32).",
    edit_bypass: "Endpoint",
    edit_bypassHint: "Server IP(s) routed outside the tunnel. Comma-separated.",
    edit_maxAttempts: "Reconnect attempts",
    edit_delays: "Reconnect delays (s)",
    edit_delaysHint: "Seconds between retries, comma-separated.",
    edit_save: "Save changes",
    edit_reset: "Reset to defaults",
    edit_cancel: "Cancel",
    edit_reconnectNote: "The tunnel will reconnect automatically to apply the changes.",
    edit_saved: "✓ Settings saved",
    edit_resetDone: "✓ Settings restored to their original values",
    edit_resetConfirm: "Restore all settings to how they were when the profile was imported? Local changes will be lost.",
    edit_resetTitle: "Reset settings",

    confirm_continue: "Continue",
    confirm_reset: "Reset",
    profiles_remove: "Remove",
    profiles_removeTitle: "Remove profile",
    profiles_removeConfirm: "Remove the active profile? You'll need to import the .owcfg again.",
    profiles_replaceTitle: "Replace connection",

    error_title: "Couldn't connect",
    error_genericBody: "It may be a TLS fingerprint mismatch, an unreachable endpoint or a WireGuard failure.",
    error_checkLog: "Check the activity log for the full detail.",
    error_importNew: "Import a new .owcfg",
    retry: "Retry",
    bootError: "Couldn't start the interface.",
    reconnectAttempt: "Attempt",
    importReading: "Reading file…",
    errorUnknown: "Unknown error",
    techDetails: "Technical details",
    clientIp: "Client IP",

    logs_empty: "— no entries —",
    logs_level: "Level",
    logs_levelAll: "All",
    logs_exported: "✓ Log exported",
    logs_jumpBottom: "Jump to bottom",

    step_resolve: "Resolving endpoint",
    step_tls: "Verifying certificate",
    step_wg: "Bringing up WireGuard interface",
    step_ws: "Opening WebSocket tunnel",
    step_done: "Done",

    profile: "Profile",
    home_ribbon: "Your traffic is encrypted via wstunnel → WireGuard.",
    home_clickToConnect: "Click the dial to connect.",
    home_secure_title: "Encrypted traffic",
    home_secure_body: "WireGuard over WebSocket (wstunnel).",
    home_pinned_title: "Pinned certificate",
    home_pinned_body: "SHA-256 fingerprint verification, no dynamic DNS.",
    home_routing_title: "Automatic routing",
    home_routing_body: "Endpoint bypass and reconnect with backoff.",
    throughput_title: "Traffic",
    throughput_window: "last {n} s",
    throughput_empty: "Gathering samples…",
    notConnected: "No active tunnel",
  },
};

// realistic log lines used by both variations
const SAMPLE_LOGS = [
  { t: "12:04:02.118", lvl: "info",  msg: "outwarp client v0.4.2 starting" },
  { t: "12:04:02.221", lvl: "info",  msg: "loading profile 'Universidad' from %APPDATA%\\OutWarp" },
  { t: "12:04:02.310", lvl: "debug", msg: "wstunnel target = wss://vps.fcrespo.dev:443" },
  { t: "12:04:02.402", lvl: "info",  msg: "resolving vps.fcrespo.dev → 89.32.144.19" },
  { t: "12:04:02.566", lvl: "debug", msg: "TLS cert sha256 fingerprint: 4f:9a:1c:7e:b3:d2:8a:55:…" },
  { t: "12:04:02.567", lvl: "info",  msg: "fingerprint matches pinned value ✓" },
  { t: "12:04:02.701", lvl: "info",  msg: "WebSocket established (HTTP/1.1 → 101 Switching Protocols)" },
  { t: "12:04:02.840", lvl: "info",  msg: "wg-quick: bringing up interface outwarp0" },
  { t: "12:04:03.002", lvl: "info",  msg: "added route 89.32.144.19/32 → 192.168.1.1 (bypass)" },
  { t: "12:04:03.219", lvl: "debug", msg: "WG: sending initial handshake" },
  { t: "12:04:03.401", lvl: "info",  msg: "WG handshake OK (rtt=182ms)" },
  { t: "12:04:03.402", lvl: "info",  msg: "tunnel UP — peer 10.66.0.1, allowed-ips 0.0.0.0/0" },
  { t: "12:05:18.712", lvl: "debug", msg: "rx 4.2 MB · tx 812 KB · last_hs=00:01:15" },
  { t: "12:07:44.114", lvl: "debug", msg: "rx 19.7 MB · tx 2.1 MB · last_hs=00:00:42" },
];

window.STR = STR;
window.SAMPLE_LOGS = SAMPLE_LOGS;

// hook to read tweaks from a parent
const useUiState = (initial) => {
  const [state, setState] = React.useState(initial);
  return [state, (k, v) => setState((s) => ({ ...s, [k]: typeof k === "object" ? { ...s, ...k } : v ?? s[k] })), setState];
};
window.useUiState = useUiState;

// Tiny atoms shared by both variations.
// Btn's palette + interactive states live in styles.css (.ow-btn) so
// hover/active/focus-visible/disabled actually render — inline styles can't
// express pseudo-states.
const Btn = ({ children, kind = "ghost", size = "md", icon, style = {}, className = "", ...rest }) => (
  <button
    {...rest}
    className={`ow-btn ow-btn--${kind} ow-btn--${size}${className ? " " + className : ""}`}
    style={style}
  >
    {icon}{children}
  </button>
);

const Pill = ({ children, tone = "neutral", style = {} }) => {
  const tones = {
    neutral: { bg: "var(--chip)", fg: "var(--text-2)" },
    good:    { bg: "color-mix(in srgb, var(--brand-2) 16%, transparent)", fg: "var(--brand-2)" },
    bad:     { bg: "color-mix(in srgb, var(--brand-bad) 16%, transparent)", fg: "var(--brand-bad)" },
    warn:    { bg: "color-mix(in srgb, var(--brand-warn) 18%, transparent)", fg: "var(--brand-warn)" },
    brand:   { bg: "color-mix(in srgb, var(--brand) 16%, transparent)", fg: "var(--brand)" },
  }[tone];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 22, padding: "0 8px", borderRadius: 999, fontSize: 11, fontWeight: 500, fontFamily: "var(--font-mono)", background: tones.bg, color: tones.fg, ...style }}>
      {children}
    </span>
  );
};

const StatusDot = ({ tone = "good", pulse = true }) => {
  const c = tone === "good" ? "var(--brand-2)" : tone === "bad" ? "var(--brand-bad)" : tone === "warn" ? "var(--brand-warn)" : "var(--text-3)";
  return (
    <span style={{ position: "relative", display: "inline-block", width: 8, height: 8 }}>
      {pulse ? <span style={{ position: "absolute", inset: 0, borderRadius: 999, background: c, animation: "ws-pulse 1.6s ease-out infinite" }}/> : null}
      <span style={{ position: "absolute", inset: 0, borderRadius: 999, background: c }}/>
    </span>
  );
};

const Toggle = ({ on, onChange, accent }) => (
  <button onClick={() => onChange?.(!on)} aria-pressed={on} className="ow-toggle"
    style={{
      width: 36, height: 20, borderRadius: 999, padding: 2, border: "none",
      background: on ? (accent || "var(--brand)") : "var(--line-strong)",
      cursor: "pointer", display: "inline-flex", alignItems: "center",
      transition: "background .15s",
    }}>
    <span style={{ width: 16, height: 16, borderRadius: 999, background: "#fff",
      transform: on ? "translateX(16px)" : "translateX(0)", transition: "transform .15s",
      boxShadow: "0 1px 2px rgba(0,0,0,.25)" }}/>
  </button>
);

// ── Crash recovery ─────────────────────────────────────────────────
// A render/lifecycle exception anywhere in the tree would otherwise blank the
// whole pywebview window with no way back (frameless = no native chrome). This
// boundary catches it, reports the stack to the Python log via the bridge, and
// shows a self-contained recovery screen so the user is never stuck. It uses
// only inline styles + design tokens — it must not depend on the components
// that may have just crashed.
const _ErrorScreen = ({ error }) => {
  const reload = () => { try { window.location.reload(); } catch (_) {} };
  const close = () => { try { window.pywebview?.api?.window_close?.(); } catch (_) {} };
  const startMove = (e) => { if (e.button === 0) { try { window.pywebview?.api?.window_start_move?.(); } catch (_) {} } };
  const detail = (error && (error.stack || error.message)) || String(error || "");
  return (
    <div style={{ height: "100%", display: "flex", flexDirection: "column", background: "var(--bg)", color: "var(--text)" }}>
      <div className="pywebview-drag-region" onMouseDown={startMove}
        style={{ flex: "0 0 38px", display: "flex", alignItems: "center", justifyContent: "flex-end", borderBottom: "1px solid var(--line)", background: "var(--bg-2)" }}>
        <button className="ow-winbtn close" onClick={close} title="Cerrar / Close" aria-label="Cerrar / Close">
          <svg width="11" height="11" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="1.1"><line x1="2.5" y1="2.5" x2="9.5" y2="9.5"/><line x1="9.5" y1="2.5" x2="2.5" y2="9.5"/></svg>
        </button>
      </div>
      <div style={{ flex: 1, minHeight: 0, display: "grid", placeItems: "center", padding: 28 }}>
        <div style={{ maxWidth: 520, width: "100%" }}>
          <div style={{ fontSize: 20, fontWeight: 600, letterSpacing: "-0.02em" }}>Algo ha fallado · Something went wrong</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 8 }}>
            La interfaz encontró un error inesperado. Tu conexión no se ve afectada — recarga la ventana para continuar.
            <br/>The interface hit an unexpected error. Your connection is unaffected — reload to continue.
          </div>
          <pre style={{ marginTop: 16, maxHeight: 180, overflow: "auto", background: "var(--bg-sunk)", border: "1px solid var(--line)", borderRadius: 8, padding: 12, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)", whiteSpace: "pre-wrap" }}>{detail}</pre>
          <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
            <button onClick={reload} style={{ all: "unset", cursor: "pointer", padding: "9px 16px", borderRadius: 8, background: "var(--brand)", color: "#fff", fontSize: 13, fontWeight: 600 }}>Recargar · Reload</button>
            <button onClick={close} style={{ all: "unset", cursor: "pointer", padding: "9px 16px", borderRadius: 8, border: "1px solid var(--line-strong)", color: "var(--text)", fontSize: 13, fontWeight: 500 }}>Cerrar · Close</button>
          </div>
        </div>
      </div>
    </div>
  );
};

class ErrorBoundary extends React.Component {
  constructor(props) {
    super(props);
    this.state = { error: null };
  }
  static getDerivedStateFromError(error) {
    return { error };
  }
  componentDidCatch(error, info) {
    try {
      const where = (info && info.componentStack) || "";
      const msg = (error && (error.stack || error.message)) || String(error);
      window.pywebview?.api?.report_ui_error?.(`render crash: ${msg}\n${where}`.slice(0, 4000));
    } catch (_) {}
  }
  render() {
    if (this.state.error) return React.createElement(_ErrorScreen, { error: this.state.error });
    return this.props.children;
  }
}

// ── Minimal markdown renderer ──────────────────────────────────────
// GitHub release notes are markdown; rendering them as plain text looked raw.
// This is a tiny, dependency-free renderer (we can't pull a CDN lib into an
// offline VPN app) covering the subset release notes actually use: headings,
// bold, italic, inline code, code fences, links, ordered/unordered lists and
// horizontal rules. It returns React elements (never innerHTML), so it is
// XSS-safe by construction — React escapes all text.
const _MD_INLINE = /(`[^`]+`)|(\*\*[^*]+\*\*)|(\[[^\]]+\]\([^)]+\))|(\*[^*]+\*)|(_[^_]+_)/g;

const _mdInline = (text, kp) => {
  const out = [];
  let last = 0;
  let n = 0;
  for (const m of String(text).matchAll(_MD_INLINE)) {
    if (m.index > last) out.push(text.slice(last, m.index));
    const tok = m[0];
    const key = `${kp}-${n++}`;
    if (m[1]) {
      out.push(<code key={key} className="ow-md-code">{tok.slice(1, -1)}</code>);
    } else if (m[2]) {
      out.push(<strong key={key}>{tok.slice(2, -2)}</strong>);
    } else if (m[3]) {
      const link = tok.match(/\[([^\]]+)\]\(([^)]+)\)/);
      const url = link[2];
      out.push(
        <a key={key} href={url} className="ow-md-link"
          onClick={(e) => { e.preventDefault(); try { window.pywebview?.api?.open_url?.(url); } catch (_) {} }}>
          {link[1]}
        </a>,
      );
    } else {
      out.push(<em key={key}>{tok.slice(1, -1)}</em>);
    }
    last = m.index + tok.length;
  }
  if (last < text.length) out.push(text.slice(last));
  return out;
};

const _isBlockStart = (l) =>
  /^\s*$/.test(l) || /^```/.test(l) || /^(#{1,6})\s+/.test(l) ||
  /^\s*[-*+]\s+/.test(l) || /^\s*\d+\.\s+/.test(l) || /^\s*([-*_])\1{2,}\s*$/.test(l);

const Markdown = ({ text }) => {
  if (!text) return null;
  const lines = String(text).replace(/\r\n/g, "\n").split("\n");
  const blocks = [];
  let i = 0;
  while (i < lines.length) {
    const line = lines[i];
    const bk = `b${blocks.length}`;
    if (/^```/.test(line)) {
      const buf = [];
      i++;
      while (i < lines.length && !/^```/.test(lines[i])) { buf.push(lines[i]); i++; }
      i++; // closing fence
      blocks.push(<pre key={bk} className="ow-md-pre"><code>{buf.join("\n")}</code></pre>);
      continue;
    }
    if (/^\s*$/.test(line)) { i++; continue; }
    if (/^\s*([-*_])\1{2,}\s*$/.test(line)) { blocks.push(<hr key={bk} className="ow-md-hr"/>); i++; continue; }
    const h = line.match(/^(#{1,6})\s+(.*)$/);
    if (h) {
      blocks.push(<div key={bk} className={`ow-md-h ow-md-h${h[1].length}`}>{_mdInline(h[2], bk)}</div>);
      i++;
      continue;
    }
    if (/^\s*[-*+]\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*[-*+]\s+/.test(lines[i])) {
        items.push(<li key={items.length}>{_mdInline(lines[i].replace(/^\s*[-*+]\s+/, ""), `${bk}-li${items.length}`)}</li>);
        i++;
      }
      blocks.push(<ul key={bk} className="ow-md-list">{items}</ul>);
      continue;
    }
    if (/^\s*\d+\.\s+/.test(line)) {
      const items = [];
      while (i < lines.length && /^\s*\d+\.\s+/.test(lines[i])) {
        items.push(<li key={items.length}>{_mdInline(lines[i].replace(/^\s*\d+\.\s+/, ""), `${bk}-li${items.length}`)}</li>);
        i++;
      }
      blocks.push(<ol key={bk} className="ow-md-list">{items}</ol>);
      continue;
    }
    const para = [];
    while (i < lines.length && !_isBlockStart(lines[i])) { para.push(lines[i]); i++; }
    const nodes = [];
    para.forEach((p, idx) => {
      if (idx > 0) nodes.push(<br key={`${bk}-br${idx}`}/>);
      _mdInline(p, `${bk}-l${idx}`).forEach((nd) => nodes.push(nd));
    });
    blocks.push(<p key={bk} className="ow-md-p">{nodes}</p>);
  }
  return <div className="ow-md">{blocks}</div>;
};

window.Btn = Btn;
window.Pill = Pill;
window.StatusDot = StatusDot;
window.Toggle = Toggle;
window.ErrorBoundary = ErrorBoundary;
window.Markdown = Markdown;
