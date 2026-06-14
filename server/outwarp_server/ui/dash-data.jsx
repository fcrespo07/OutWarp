// OutWarp Server dashboard — i18n strings + formatters.
// Ported from the design handoff: mock fixtures (DS_CLIENTS/DS_SERVER/…)
// and the simulated-series generators are dropped — real data comes from
// the Api via OW.call + outwarp:* events (see app.jsx).

const DS_STR = {
  es: {
    // brand / chrome
    serverAdmin: "Panel del servidor",
    remoteSession: "Sesión remota",
    signOut: "Cerrar sesión",
    search: "Buscar…",
    collapse: "Contraer",

    // login
    login_eyebrow: "Acceso al panel",
    login_title: "Administra tu servidor OutWarp",
    login_sub: "Introduce el token de administración del daemon para abrir el panel remoto.",
    login_endpoint: "Endpoint del servidor",
    login_token: "Token de administración",
    login_tokenPh: "ow_admin_••••••••••••",
    login_remember: "Mantener la sesión en este navegador",
    login_btn: "Entrar al panel",
    login_hint: "El token se imprime una vez al instalar: outwarp-server admin-token",
    login_secured: "Sesión cifrada · WSS + token",
    login_bad: "Token inválido",
    login_locked: "Demasiados intentos · espera un momento",

    // nav
    nav_dashboard: "Resumen",
    nav_clients: "Clientes",
    nav_traffic: "Tráfico",
    nav_service: "Servicio",
    nav_logs: "Registro",
    nav_doctor: "Doctor",
    nav_settings: "Ajustes",

    // status
    running: "En ejecución",
    stopped: "Detenido",
    degraded: "Degradado",
    online: "En línea",
    idle: "Inactivo",
    offline: "Desconectado",
    uptime: "Uptime",

    // dashboard
    dash_title: "Resumen",
    dash_health: "Estado del servicio",
    dash_clientsOnline: "clientes en línea",
    dash_allHealthy: "Todos los servicios sanos",
    dash_throughput: "Throughput en vivo",
    dash_now: "ahora",
    dash_down: "Bajada",
    dash_up: "Subida",
    dash_traffic24: "Tráfico · 24 h",
    dash_total: "Total",
    dash_topTalkers: "Top talkers · última hora",
    dash_services: "Servicios",
    dash_network: "Red",
    dash_tls: "TLS",
    dash_activeClients: "Clientes activos",
    dash_viewAll: "Ver todos",
    dash_endpoint: "Endpoint",
    dash_publicIp: "IP pública",
    dash_subnet: "Subred",
    dash_wgListen: "WG listen",
    dash_ipForward: "ip_forward",
    dash_nat: "NAT",
    dash_fingerprint: "Huella",
    dash_validUntil: "Válido hasta",
    dash_transport: "Transporte",
    dash_daysLeft: "{n} días restantes",

    // clients
    clients_title: "Clientes",
    clients_sub: "{total} totales · {online} en línea",
    clients_add: "Añadir cliente",
    clients_searchPh: "Buscar por nombre o IP…",
    col_name: "Nombre",
    col_ip: "IP",
    col_status: "Estado",
    col_handshake: "Último HS",
    col_rx: "↓ RX",
    col_tx: "↑ TX",
    col_throughput: "Throughput",
    col_actions: "",
    filter_all: "Todos",

    // client detail
    detail_pubkey: "Clave pública",
    detail_endpoint: "Endpoint",
    detail_allowed: "Allowed IPs",
    detail_dns: "DNS",
    detail_added: "Añadido",
    detail_transfer: "Transferido",
    detail_session: "Sesión actual",
    detail_live: "En vivo",
    detail_regen: "Regenerar .owcfg",
    detail_rotate: "Rotar claves",
    detail_revoke: "Revocar",
    detail_qr: "Ver QR",
    detail_download: "Descargar",
    rotateTitle: "Rotar las claves del cliente",
    rotateBody: "Generar claves nuevas invalida el .owcfg actual de {name}. Tendrás que reenviarle el nuevo archivo. ¿Continuar?",
    revokeTitle: "Revocar {name}",
    revokeBody: "Su .owcfg dejará de funcionar de inmediato y se eliminará del peer-list de WireGuard. ¿Continuar?",
    confirm: "Continuar",
    cancel: "Cancelar",

    // add client
    add_title: "Añadir cliente",
    add_sub: "El servidor genera las claves WireGuard localmente y ancla la huella TLS en el .owcfg.",
    add_name: "Nombre del cliente",
    add_namePh: "ej. ana-laptop",
    add_ip: "IP asignada",
    add_autoAssigned: "auto-asignada (siguiente libre en la subred)",
    add_allowed: "Allowed IPs",
    add_dns: "DNS",
    add_generate: "Generar perfil",
    add_done: "creado",
    add_writtenTo: "escrito en",
    add_warnKey: "Envía el .owcfg de forma segura (Signal, age, scp). Lleva la clave privada del cliente — no lo mandes por email ni lo subas a un repo.",
    add_close: "Crear y cerrar",
    add_showQr: "Ver QR",

    // traffic
    traffic_title: "Historial de tráfico",
    traffic_sub: "Agregado de todos los peers · snapshots cada 60 s",
    traffic_window: "Ventana",
    traffic_1h: "1 h",
    traffic_24h: "24 h",
    traffic_7d: "7 d",
    traffic_rxTotal: "RX total",
    traffic_txTotal: "TX total",
    traffic_peak: "Pico",
    traffic_avg: "Media",
    traffic_perClient: "Por cliente",

    // service
    service_title: "Servicio",
    service_sub: "Control de las unidades systemd que usa OutWarp.",
    service_start: "Iniciar",
    service_stop: "Parar",
    service_restart: "Reiniciar",
    service_regen: "Regenerar config",
    service_uninstall: "Desinstalar",
    service_pid: "PID",
    service_mem: "MEM",
    service_cpu: "CPU",
    service_since: "activo desde",
    service_actions: "Acciones del servidor",
    service_confirmRestart: "Reiniciar el servicio cortará las conexiones activas unos segundos. ¿Continuar?",

    // logs
    logs_title: "Registro",
    logs_sub: "journalctl -u wstunnel -u wg-quick@wg0 · live",
    logs_filterPh: "Filtrar…",
    logs_level: "Nivel",
    logs_export: "Exportar",
    logs_clear: "Limpiar",
    logs_following: "siguiendo",
    logs_paused: "en pausa",
    logs_jumpBottom: "Saltar al final",
    logs_lines: "{n} líneas",

    // doctor
    doctor_title: "Doctor",
    doctor_sub: "Diagnóstico completo del servidor con remediación.",
    doctor_rerun: "Re-ejecutar",
    doctor_copy: "Copiar reporte",
    doctor_applyFix: "Aplicar fix",
    doctor_ok: "OK",
    doctor_warn: "WARN",
    doctor_fail: "FAIL",
    doctor_lastRun: "última ejecución {t}",
    doctor_checks: "{n} chequeos",
    doctor_fix: "fix",

    // settings
    settings_title: "Ajustes",
    settings_sub: "outwarp-server · v0.4.2",
    set_serverCfg: "Configuración del servidor",
    set_serverCfgSub: "Cambios que requieren reiniciar el servicio.",
    set_port: "Puerto WSS",
    set_wgPort: "Puerto WireGuard",
    set_endpoint: "Endpoint",
    set_subnet: "Subred WG",
    set_apply: "Aplicar cambios",
    set_cert: "Certificado TLS",
    set_certSub: "Auto-firmado, anclado por huella SHA-256.",
    set_copyFp: "Copiar huella",
    set_rotateCert: "Rotar certificado",
    set_rotateCertSub: "Genera un certificado nuevo. Todos los .owcfg emitidos dejarán de validar — habrá que regenerarlos.",
    set_appearance: "Apariencia",
    set_language: "Idioma",
    set_theme: "Tema",
    set_themeLight: "Claro",
    set_themeDark: "Oscuro",
    set_session: "Sesión",
    set_sessionSub: "Token activo en este navegador.",

    // misc
    copied: "Copiado",
    never: "Nunca",
    ago: "hace",
  },
  en: {
    serverAdmin: "Server admin",
    remoteSession: "Remote session",
    signOut: "Sign out",
    search: "Search…",
    collapse: "Collapse",

    login_eyebrow: "Panel access",
    login_title: "Administer your OutWarp server",
    login_sub: "Enter the daemon's admin token to open the remote panel.",
    login_endpoint: "Server endpoint",
    login_token: "Admin token",
    login_tokenPh: "ow_admin_••••••••••••",
    login_remember: "Keep this session in this browser",
    login_btn: "Enter panel",
    login_hint: "The token is printed once on install: outwarp-server admin-token",
    login_secured: "Encrypted session · WSS + token",
    login_bad: "Invalid token",
    login_locked: "Too many attempts · wait a moment",

    nav_dashboard: "Overview",
    nav_clients: "Clients",
    nav_traffic: "Traffic",
    nav_service: "Service",
    nav_logs: "Logs",
    nav_doctor: "Doctor",
    nav_settings: "Settings",

    running: "Running",
    stopped: "Stopped",
    degraded: "Degraded",
    online: "Online",
    idle: "Idle",
    offline: "Offline",
    uptime: "Uptime",

    dash_title: "Overview",
    dash_health: "Service health",
    dash_clientsOnline: "clients online",
    dash_allHealthy: "All services healthy",
    dash_throughput: "Live throughput",
    dash_now: "now",
    dash_down: "Down",
    dash_up: "Up",
    dash_traffic24: "Traffic · 24 h",
    dash_total: "Total",
    dash_topTalkers: "Top talkers · last hour",
    dash_services: "Services",
    dash_network: "Network",
    dash_tls: "TLS",
    dash_activeClients: "Active clients",
    dash_viewAll: "View all",
    dash_endpoint: "Endpoint",
    dash_publicIp: "Public IP",
    dash_subnet: "Subnet",
    dash_wgListen: "WG listen",
    dash_ipForward: "ip_forward",
    dash_nat: "NAT",
    dash_fingerprint: "Fingerprint",
    dash_validUntil: "Valid until",
    dash_transport: "Transport",
    dash_daysLeft: "{n} days remaining",

    clients_title: "Clients",
    clients_sub: "{total} total · {online} online",
    clients_add: "Add client",
    clients_searchPh: "Search by name or IP…",
    col_name: "Name",
    col_ip: "IP",
    col_status: "Status",
    col_handshake: "Last HS",
    col_rx: "↓ RX",
    col_tx: "↑ TX",
    col_throughput: "Throughput",
    col_actions: "",
    filter_all: "All",

    detail_pubkey: "Public key",
    detail_endpoint: "Endpoint",
    detail_allowed: "Allowed IPs",
    detail_dns: "DNS",
    detail_added: "Added",
    detail_transfer: "Transferred",
    detail_session: "Current session",
    detail_live: "Live",
    detail_regen: "Regenerate .owcfg",
    detail_rotate: "Rotate keys",
    detail_revoke: "Revoke",
    detail_qr: "Show QR",
    detail_download: "Download",
    rotateTitle: "Rotate client keys",
    rotateBody: "Generating new keys invalidates {name}'s current .owcfg. You'll have to resend the new file. Continue?",
    revokeTitle: "Revoke {name}",
    revokeBody: "Their .owcfg will stop working immediately and the peer is removed from WireGuard. Continue?",
    confirm: "Continue",
    cancel: "Cancel",

    add_title: "Add client",
    add_sub: "The server generates WireGuard keys locally and pins the TLS fingerprint into the .owcfg.",
    add_name: "Client name",
    add_namePh: "e.g. ana-laptop",
    add_ip: "Assigned IP",
    add_autoAssigned: "auto-assigned (next free in subnet)",
    add_allowed: "Allowed IPs",
    add_dns: "DNS",
    add_generate: "Generate profile",
    add_done: "created",
    add_writtenTo: "written to",
    add_warnKey: "Send the .owcfg securely (Signal, age, scp). It carries the client's private key — don't email it or commit it to a repo.",
    add_close: "Create & close",
    add_showQr: "Show QR",

    traffic_title: "Traffic history",
    traffic_sub: "Aggregated across all peers · 60 s snapshots",
    traffic_window: "Window",
    traffic_1h: "1 h",
    traffic_24h: "24 h",
    traffic_7d: "7 d",
    traffic_rxTotal: "RX total",
    traffic_txTotal: "TX total",
    traffic_peak: "Peak",
    traffic_avg: "Avg",
    traffic_perClient: "Per client",

    service_title: "Service",
    service_sub: "Control the systemd units OutWarp uses.",
    service_start: "Start",
    service_stop: "Stop",
    service_restart: "Restart",
    service_regen: "Regenerate config",
    service_uninstall: "Uninstall",
    service_pid: "PID",
    service_mem: "MEM",
    service_cpu: "CPU",
    service_since: "active since",
    service_actions: "Server actions",
    service_confirmRestart: "Restarting the service will drop active connections for a few seconds. Continue?",

    logs_title: "Logs",
    logs_sub: "journalctl -u wstunnel -u wg-quick@wg0 · live",
    logs_filterPh: "Filter…",
    logs_level: "Level",
    logs_export: "Export",
    logs_clear: "Clear",
    logs_following: "following",
    logs_paused: "paused",
    logs_jumpBottom: "Jump to bottom",
    logs_lines: "{n} lines",

    doctor_title: "Doctor",
    doctor_sub: "Full server diagnostics with remediation.",
    doctor_rerun: "Re-run",
    doctor_copy: "Copy report",
    doctor_applyFix: "Apply fix",
    doctor_ok: "OK",
    doctor_warn: "WARN",
    doctor_fail: "FAIL",
    doctor_lastRun: "last run {t}",
    doctor_checks: "{n} checks",
    doctor_fix: "fix",

    settings_title: "Settings",
    settings_sub: "outwarp-server · v0.4.2",
    set_serverCfg: "Server configuration",
    set_serverCfgSub: "Changes that require restarting the service.",
    set_port: "WSS port",
    set_wgPort: "WireGuard port",
    set_endpoint: "Endpoint",
    set_subnet: "WG subnet",
    set_apply: "Apply changes",
    set_cert: "TLS certificate",
    set_certSub: "Self-signed, pinned by SHA-256 fingerprint.",
    set_copyFp: "Copy fingerprint",
    set_rotateCert: "Rotate certificate",
    set_rotateCertSub: "Generates a new certificate. All issued .owcfg files stop validating — you'll have to regenerate them.",
    set_appearance: "Appearance",
    set_language: "Language",
    set_theme: "Theme",
    set_themeLight: "Light",
    set_themeDark: "Dark",
    set_session: "Session",
    set_sessionSub: "Token active in this browser.",

    copied: "Copied",
    never: "Never",
    ago: "ago",
  },
};

// ── formatters ──────────────────────────────────────────────────────────────
function fmtBytes(b) {
  if (b == null) return "—";
  if (b < 1024) return b + " B";
  const u = ["KB", "MB", "GB", "TB"];
  let i = -1, n = b;
  do { n /= 1024; i++; } while (n >= 1024 && i < u.length - 1);
  return (n >= 100 ? n.toFixed(0) : n.toFixed(1)) + " " + u[i];
}
function fmtBps(b) {
  if (!b) return "0 B/s";
  return fmtBytes(b) + "/s";
}
function fmtDuration(s) {
  s = Math.max(0, Math.floor(s));
  const d = Math.floor(s / 86400); s -= d * 86400;
  const h = Math.floor(s / 3600);  s -= h * 3600;
  const m = Math.floor(s / 60);    s -= m * 60;
  if (d > 0) return `${d}d ${String(h).padStart(2, "0")}h ${String(m).padStart(2, "0")}m`;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
}
function fmtAgo(sec, lang) {
  const ago = (lang === "en") ? "" : "hace ";
  const post = (lang === "en") ? " ago" : "";
  if (sec == null) return "—";
  if (sec < 60) return `${ago}${Math.floor(sec)}s${post}`;
  if (sec < 3600) return `${ago}${Math.floor(sec / 60)}m${post}`;
  if (sec < 86400) return `${ago}${Math.floor(sec / 3600)}h${post}`;
  return `${ago}${Math.floor(sec / 86400)}d${post}`;
}
function tr(str, vars) {
  if (!vars) return str;
  return str.replace(/\{(\w+)\}/g, (_, k) => (vars[k] != null ? vars[k] : `{${k}}`));
}
function nowClock() {
  const d = new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

window.DS_STR = DS_STR;
window.DSfmt = { fmtBytes, fmtBps, fmtDuration, fmtAgo, tr, nowClock };
