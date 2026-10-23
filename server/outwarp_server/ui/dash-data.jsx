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
    login_hint: "El token se imprime una vez al instalar (outwarp-server admin-token). Guárdalo en el navegador o en tu gestor de contraseñas.",
    login_secured: "Sesión cifrada · HTTPS + token",
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
    a11y_theme: "Cambiar tema",
    a11y_menu: "Menú",
    a11y_close: "Cerrar",
    idle: "Inactivo",
    offline: "Desconectado",
    pending: "Pendiente",
    disabled: "Desactivado",
    uptime: "Uptime",

    // dashboard
    dash_title: "Resumen",
    dash_health: "Estado del servicio",
    dash_clientsOnline: "clientes en línea",
    dash_tunnelUp: "Túnel en marcha",
    dash_tunnelDown: "Túnel parado",
    dash_noActive: "Ningún cliente conectado ahora mismo.",
    dash_noTop: "Aún no hay tráfico registrado en las últimas 24 h.",
    dash_throughput: "Throughput en vivo",
    dash_now: "ahora",
    dash_down: "Bajada",
    dash_up: "Subida",
    dash_traffic24: "Tráfico · 24 h",
    dash_total: "Total",
    dash_topTalkers: "Clientes con más tráfico · 24 h",
    dash_services: "Servicio",
    dash_network: "Red",
    dash_tls: "TLS",
    dash_activeClients: "Clientes activos",
    dash_viewAll: "Ver todos",
    dash_endpoint: "Endpoint",
    dash_publicIp: "IP pública",
    dash_subnet: "Subred",
    dash_wgListen: "WG listen",
    dash_ipForward: "ip_forward",
    dash_serverIp: "IP del túnel",
    dash_wssPort: "Puerto WSS",
    dash_tlsMode: "Modo",
    tls_selfSigned: "Autofirmado",
    tls_acme: "Let's Encrypt · Caddy",
    host_here: "Este proceso",
    host_container: "Contenedor (serve)",
    host_systemd: "Unidades systemd",
    host_windows: "App OutWarp Server",
    svc_runsIn: "Se ejecuta en",
    svc_control: "Control desde aquí",
    svc_controlFull: "Arrancar, parar y reiniciar",
    svc_controlRestart: "Solo reiniciar",
    svc_controlNone: "Ninguno",
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
    clients_empty: "Aún no hay clientes",
    clients_emptyBody: "Crea uno y envíale su .owcfg: al importarlo genera sus propias claves y entra en el túnel.",
    clients_noMatch: "Ningún cliente coincide con la búsqueda o el filtro.",

    // client detail
    detail_pubkey: "Clave pública",
    detail_endpoint: "Endpoint",
    detail_allowed: "Allowed IPs",
    detail_dns: "DNS",
    detail_added: "Añadido",
    detail_transfer: "Transferido",
    detail_session: "Sesión actual",
    detail_live: "En vivo",
    detail_pending: "Sin enrolar — el cliente aún no ha canjeado su token",
    detail_rotate: "Rotar claves y descargar .owcfg",
    detail_revoke: "Revocar",
    detail_disable: "Desactivar",
    detail_enable: "Activar",
    detail_disabled: "Desactivado — fuera del túnel hasta que lo actives; conserva IP, claves y .owcfg",
    detail_download: "Descargar",
    rotateTitle: "Rotar las claves del cliente",
    rotateBody: "Generar claves nuevas invalida el .owcfg actual de {name}. Tendrás que reenviarle el nuevo archivo. ¿Continuar?",
    revokeTitle: "Revocar {name}",
    revokeBody: "Su .owcfg dejará de funcionar de inmediato y se eliminará del peer-list de WireGuard. ¿Continuar?",
    confirm: "Continuar",
    cancel: "Cancelar",

    // add client
    add_title: "Añadir cliente",
    add_sub: "El .owcfg lleva un token de un solo uso: el cliente genera sus propias claves al importarlo y el servidor nunca las ve.",
    add_token: "token de un solo uso · caduca en 15 min",
    add_name: "Nombre del cliente",
    add_namePh: "ej. ana-laptop",
    add_ip: "IP asignada",
    add_autoAssigned: "auto-asignada (siguiente libre en la subred)",
    add_allowed: "Allowed IPs",
    add_dns: "DNS",
    add_generate: "Generar perfil",
    add_done: "creado",
    add_writtenTo: "escrito en",
    add_warnKey: "Quien importe este .owcfg antes de que caduque se convierte en este cliente. Envíalo por un canal privado (Signal, age, scp), no por email ni a un repositorio.",
    add_close: "Crear y cerrar",

    // traffic
    traffic_title: "Historial de tráfico",
    traffic_sub: "Todo el tráfico de los clientes por el túnel · una muestra por minuto, 7 días",
    traffic_window: "Ventana",
    traffic_1h: "1 h",
    traffic_24h: "24 h",
    traffic_7d: "7 d",
    traffic_rxTotal: "Recibido",
    traffic_rxSub: "RX · lo que suben los clientes",
    traffic_txTotal: "Enviado",
    traffic_txSub: "TX · lo que bajan los clientes",
    traffic_peak: "Pico",
    traffic_peakSub: "máximo entre dos muestras",
    traffic_avg: "Media",
    traffic_avgSub: "en {span} con datos",
    traffic_perClient: "Por cliente",
    traffic_chartTitle: "Tráfico en el tiempo",
    traffic_emptyTitle: "Aún no hay datos",
    traffic_emptyBody: "El servidor guarda una muestra del tráfico de cada cliente por minuto mientras el túnel está en marcha y las conserva 7 días. La primera aparecerá aquí en un par de minutos.",
    traffic_emptyStopped: "El túnel está parado: no se registra tráfico hasta que vuelva a arrancar.",
    traffic_noSamples: "sin datos",
    traffic_partial: "Hay datos desde {t}; antes de eso no hay muestras.",
    traffic_quiet: "Ningún cliente ha pasado tráfico en esta ventana.",
    traffic_error: "No se pudo leer el historial: {error}",
    traffic_share: "del total",

    // service
    service_title: "Servicio",
    service_sub: "Estado del túnel y qué se puede hacer con él desde aquí.",
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
    service_managedBySystemd: "El túnel lo gestionan las unidades systemd de este host: desde aquí solo se puede reiniciar (equivale a `outwarp-server restart`).",
    service_managedElsewhere: "El túnel lo ejecuta otro proceso de este host (el contenedor `serve`). Desde este panel no se puede arrancar, parar ni reiniciar; usa el runtime de contenedores.",

    // logs
    logs_title: "Registro",
    logs_sub: "OutWarp y wstunnel en este servidor · en vivo",
    logs_empty: "Aún no hay líneas de registro.",
    logs_noMatch: "Ninguna línea coincide con el filtro.",
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
    doctor_running: "Ejecutando comprobaciones…",

    // settings
    settings_title: "Ajustes",
    set_serverCfg: "Configuración del servidor",
    set_serverCfgSub: "Cambios que requieren reiniciar el servicio.",
    set_port: "Puerto WSS",
    set_wgPort: "Puerto WireGuard",
    set_endpoint: "Endpoint",
    set_subnet: "Subred WG",
    set_apply: "Aplicar cambios",
    set_cert: "Certificado TLS",
    set_certSub: "Autofirmado, anclado por huella SHA-256.",
    set_certSubAcme: "Certificado de Let's Encrypt que gestiona Caddy; se renueva solo y los clientes lo validan contra la CA.",
    set_subnetFixed: "No se puede cambiar: cada cliente tiene una IP de esta subred.",
    set_copyFp: "Copiar huella",
    set_rotateCert: "Rotar certificado",
    set_rotateCertSub: "Genera un certificado nuevo. Todos los .owcfg emitidos dejarán de validar — habrá que regenerarlos.",
    set_appearance: "Apariencia",
    set_language: "Idioma",
    set_languageAuto: "Auto",
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
    login_hint: "The token is printed once on install (outwarp-server admin-token). Save it in your browser or password manager.",
    login_secured: "Encrypted session · HTTPS + token",
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
    a11y_theme: "Toggle theme",
    a11y_menu: "Menu",
    a11y_close: "Close",
    idle: "Idle",
    offline: "Offline",
    pending: "Pending",
    disabled: "Disabled",
    uptime: "Uptime",

    dash_title: "Overview",
    dash_health: "Service health",
    dash_clientsOnline: "clients online",
    dash_tunnelUp: "Tunnel running",
    dash_tunnelDown: "Tunnel stopped",
    dash_noActive: "No client is connected right now.",
    dash_noTop: "No traffic recorded in the last 24 h yet.",
    dash_throughput: "Live throughput",
    dash_now: "now",
    dash_down: "Down",
    dash_up: "Up",
    dash_traffic24: "Traffic · 24 h",
    dash_total: "Total",
    dash_topTalkers: "Top clients · 24 h",
    dash_services: "Service",
    dash_network: "Network",
    dash_tls: "TLS",
    dash_activeClients: "Active clients",
    dash_viewAll: "View all",
    dash_endpoint: "Endpoint",
    dash_publicIp: "Public IP",
    dash_subnet: "Subnet",
    dash_wgListen: "WG listen",
    dash_ipForward: "ip_forward",
    dash_serverIp: "Tunnel IP",
    dash_wssPort: "WSS port",
    dash_tlsMode: "Mode",
    tls_selfSigned: "Self-signed",
    tls_acme: "Let's Encrypt · Caddy",
    host_here: "This process",
    host_container: "Container (serve)",
    host_systemd: "systemd units",
    host_windows: "OutWarp Server app",
    svc_runsIn: "Runs in",
    svc_control: "Control from here",
    svc_controlFull: "Start, stop and restart",
    svc_controlRestart: "Restart only",
    svc_controlNone: "None",
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
    clients_empty: "No clients yet",
    clients_emptyBody: "Create one and send it its .owcfg: importing it generates the client's own keys and puts it on the tunnel.",
    clients_noMatch: "No client matches the search or filter.",

    detail_pubkey: "Public key",
    detail_endpoint: "Endpoint",
    detail_allowed: "Allowed IPs",
    detail_dns: "DNS",
    detail_added: "Added",
    detail_transfer: "Transferred",
    detail_session: "Current session",
    detail_live: "Live",
    detail_pending: "Not enrolled — the client has not redeemed its token yet",
    detail_rotate: "Rotate keys and download .owcfg",
    detail_revoke: "Revoke",
    detail_disable: "Disable",
    detail_enable: "Enable",
    detail_disabled: "Disabled — off the tunnel until you enable it; keeps its IP, keys and .owcfg",
    detail_download: "Download",
    rotateTitle: "Rotate client keys",
    rotateBody: "Generating new keys invalidates {name}'s current .owcfg. You'll have to resend the new file. Continue?",
    revokeTitle: "Revoke {name}",
    revokeBody: "Their .owcfg will stop working immediately and the peer is removed from WireGuard. Continue?",
    confirm: "Continue",
    cancel: "Cancel",

    add_title: "Add client",
    add_sub: "The .owcfg carries a one-time token: the client generates its own keys when it imports it and the server never sees them.",
    add_token: "one-time token · expires in 15 min",
    add_name: "Client name",
    add_namePh: "e.g. ana-laptop",
    add_ip: "Assigned IP",
    add_autoAssigned: "auto-assigned (next free in subnet)",
    add_allowed: "Allowed IPs",
    add_dns: "DNS",
    add_generate: "Generate profile",
    add_done: "created",
    add_writtenTo: "written to",
    add_warnKey: "Whoever imports this .owcfg before it expires becomes this client. Send it over a private channel (Signal, age, scp), not by email or through a repository.",
    add_close: "Create & close",

    traffic_title: "Traffic history",
    traffic_sub: "All client traffic through the tunnel · one sample a minute, 7 days",
    traffic_window: "Window",
    traffic_1h: "1 h",
    traffic_24h: "24 h",
    traffic_7d: "7 d",
    traffic_rxTotal: "Received",
    traffic_rxSub: "RX · what clients upload",
    traffic_txTotal: "Sent",
    traffic_txSub: "TX · what clients download",
    traffic_peak: "Peak",
    traffic_peakSub: "highest between two samples",
    traffic_avg: "Average",
    traffic_avgSub: "over {span} with data",
    traffic_perClient: "Per client",
    traffic_chartTitle: "Traffic over time",
    traffic_emptyTitle: "No data yet",
    traffic_emptyBody: "The server records each client's traffic once a minute while the tunnel runs and keeps it for 7 days. The first sample shows up here in a couple of minutes.",
    traffic_emptyStopped: "The tunnel is stopped: no traffic is recorded until it starts again.",
    traffic_noSamples: "no data",
    traffic_partial: "Data since {t}; there are no samples before that.",
    traffic_quiet: "No client has sent traffic in this window.",
    traffic_error: "Could not read the history: {error}",
    traffic_share: "of total",

    service_title: "Service",
    service_sub: "Tunnel state and what can be done with it from here.",
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
    service_managedBySystemd: "The tunnel is run by this host's systemd units: only a restart is possible from here (same as `outwarp-server restart`).",
    service_managedElsewhere: "The tunnel is run by another process on this host (the `serve` container). It cannot be started, stopped or restarted from this panel; use your container runtime.",

    logs_title: "Logs",
    logs_sub: "OutWarp and wstunnel on this server · live",
    logs_empty: "No log lines yet.",
    logs_noMatch: "No line matches the filter.",
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
    doctor_running: "Running checks…",

    settings_title: "Settings",
    set_serverCfg: "Server configuration",
    set_serverCfgSub: "Changes that require restarting the service.",
    set_port: "WSS port",
    set_wgPort: "WireGuard port",
    set_endpoint: "Endpoint",
    set_subnet: "WG subnet",
    set_apply: "Apply changes",
    set_cert: "TLS certificate",
    set_certSub: "Self-signed, pinned by SHA-256 fingerprint.",
    set_certSubAcme: "A Let's Encrypt certificate managed by Caddy; it renews itself and clients validate it against the CA.",
    set_subnetFixed: "Cannot be changed: every client has an IP from this subnet.",
    set_copyFp: "Copy fingerprint",
    set_rotateCert: "Rotate certificate",
    set_rotateCertSub: "Generates a new certificate. All issued .owcfg files stop validating — you'll have to regenerate them.",
    set_appearance: "Appearance",
    set_language: "Language",
    set_languageAuto: "Auto",
    set_theme: "Theme",
    set_themeLight: "Light",
    set_themeDark: "Dark",
    set_session: "Session",
    set_sessionSub: "Token active in this browser.",

    copied: "Copied",
    never: "Never",
    ago: "ago",
  },
  fr: {
    serverAdmin: "Admin du serveur",
    remoteSession: "Session à distance",
    signOut: "Se déconnecter",
    search: "Rechercher…",
    collapse: "Réduire",

    login_eyebrow: "Accès au panneau",
    login_title: "Administrer votre serveur OutWarp",
    login_sub: "Saisissez le jeton d'administration du daemon pour ouvrir le panneau à distance.",
    login_endpoint: "Endpoint du serveur",
    login_token: "Jeton d'administration",
    login_tokenPh: "ow_admin_••••••••••••",
    login_remember: "Garder cette session dans ce navigateur",
    login_btn: "Ouvrir le panneau",
    login_hint: "Le jeton est affiché une seule fois à l'installation (outwarp-server admin-token). Enregistrez-le dans votre navigateur ou gestionnaire de mots de passe.",
    login_secured: "Session chiffrée · HTTPS + jeton",
    login_bad: "Jeton invalide",
    login_locked: "Trop de tentatives · patientez un instant",

    nav_dashboard: "Vue d'ensemble",
    nav_clients: "Clients",
    nav_traffic: "Trafic",
    nav_service: "Service",
    nav_logs: "Journal",
    nav_doctor: "Diagnostic",
    nav_settings: "Paramètres",

    running: "En marche",
    stopped: "Arrêté",
    degraded: "Dégradé",
    online: "En ligne",
    a11y_theme: "Changer de thème",
    a11y_menu: "Menu",
    a11y_close: "Fermer",
    idle: "Inactif",
    offline: "Hors ligne",
    pending: "En attente",
    disabled: "Désactivé",
    uptime: "Disponibilité",

    dash_title: "Vue d'ensemble",
    dash_health: "État du service",
    dash_clientsOnline: "clients en ligne",
    dash_tunnelUp: "Tunnel en marche",
    dash_tunnelDown: "Tunnel arrêté",
    dash_noActive: "Aucun client n'est connecté pour le moment.",
    dash_noTop: "Aucun trafic enregistré sur les dernières 24 h.",
    dash_throughput: "Débit en direct",
    dash_now: "maint.",
    dash_down: "Réception",
    dash_up: "Envoi",
    dash_traffic24: "Trafic · 24 h",
    dash_total: "Total",
    dash_topTalkers: "Top clients · 24 h",
    dash_services: "Service",
    dash_network: "Réseau",
    dash_tls: "TLS",
    dash_activeClients: "Clients actifs",
    dash_viewAll: "Tout voir",
    dash_endpoint: "Endpoint",
    dash_publicIp: "IP publique",
    dash_subnet: "Sous-réseau",
    dash_wgListen: "Écoute WG",
    dash_ipForward: "ip_forward",
    dash_serverIp: "IP du tunnel",
    dash_wssPort: "Port WSS",
    dash_tlsMode: "Mode",
    tls_selfSigned: "Auto-signé",
    tls_acme: "Let's Encrypt · Caddy",
    host_here: "Ce processus",
    host_container: "Conteneur (serve)",
    host_systemd: "Unités systemd",
    host_windows: "Application OutWarp Server",
    svc_runsIn: "S'exécute dans",
    svc_control: "Contrôle depuis ici",
    svc_controlFull: "Démarrer, arrêter et redémarrer",
    svc_controlRestart: "Redémarrage uniquement",
    svc_controlNone: "Aucun",
    dash_fingerprint: "Empreinte",
    dash_validUntil: "Valide jusqu'au",
    dash_transport: "Transport",
    dash_daysLeft: "{n} jours restants",

    clients_title: "Clients",
    clients_sub: "{total} au total · {online} en ligne",
    clients_add: "Ajouter un client",
    clients_searchPh: "Rechercher par nom ou IP…",
    col_name: "Nom",
    col_ip: "IP",
    col_status: "État",
    col_handshake: "Dern. HS",
    col_rx: "↓ RX",
    col_tx: "↑ TX",
    col_throughput: "Débit",
    col_actions: "",
    filter_all: "Tous",
    clients_empty: "Aucun client pour le moment",
    clients_emptyBody: "Créez-en un et envoyez-lui son .owcfg : l'importer génère les clés propres au client et le place sur le tunnel.",
    clients_noMatch: "Aucun client ne correspond à la recherche ou au filtre.",

    detail_pubkey: "Clé publique",
    detail_endpoint: "Endpoint",
    detail_allowed: "IP autorisées",
    detail_dns: "DNS",
    detail_added: "Ajouté",
    detail_transfer: "Transféré",
    detail_session: "Session en cours",
    detail_live: "En direct",
    detail_pending: "Non inscrit — le client n'a pas encore utilisé son jeton",
    detail_rotate: "Renouveler les clés et télécharger le .owcfg",
    detail_revoke: "Révoquer",
    detail_disable: "Désactiver",
    detail_enable: "Activer",
    detail_disabled: "Désactivé — hors du tunnel jusqu'à son activation ; conserve son IP, ses clés et son .owcfg",
    detail_download: "Télécharger",
    rotateTitle: "Renouveler les clés du client",
    rotateBody: "Générer de nouvelles clés invalide le .owcfg actuel de {name}. Vous devrez renvoyer le nouveau fichier. Continuer ?",
    revokeTitle: "Révoquer {name}",
    revokeBody: "Son .owcfg cessera de fonctionner immédiatement et le pair sera retiré de WireGuard. Continuer ?",
    confirm: "Continuer",
    cancel: "Annuler",

    add_title: "Ajouter un client",
    add_sub: "Le .owcfg contient un jeton à usage unique : le client génère ses propres clés à l'import et le serveur ne les voit jamais.",
    add_token: "jeton à usage unique · expire dans 15 min",
    add_name: "Nom du client",
    add_namePh: "ex. ana-portable",
    add_ip: "IP attribuée",
    add_autoAssigned: "automatique (prochaine libre du sous-réseau)",
    add_allowed: "IP autorisées",
    add_dns: "DNS",
    add_generate: "Générer le profil",
    add_done: "créé",
    add_writtenTo: "écrit dans",
    add_warnKey: "Quiconque importe ce .owcfg avant son expiration devient ce client. Envoyez-le par un canal privé (Signal, age, scp), pas par e-mail ni via un dépôt.",
    add_close: "Créer et fermer",

    traffic_title: "Historique du trafic",
    traffic_sub: "Tout le trafic des clients via le tunnel · un échantillon par minute, 7 jours",
    traffic_window: "Période",
    traffic_1h: "1 h",
    traffic_24h: "24 h",
    traffic_7d: "7 j",
    traffic_rxTotal: "Reçu",
    traffic_rxSub: "RX · ce que les clients envoient",
    traffic_txTotal: "Envoyé",
    traffic_txSub: "TX · ce que les clients téléchargent",
    traffic_peak: "Pic",
    traffic_peakSub: "maximum entre deux échantillons",
    traffic_avg: "Moyenne",
    traffic_avgSub: "sur {span} avec données",
    traffic_perClient: "Par client",
    traffic_chartTitle: "Trafic dans le temps",
    traffic_emptyTitle: "Pas encore de données",
    traffic_emptyBody: "Le serveur enregistre le trafic de chaque client une fois par minute tant que le tunnel fonctionne et le conserve 7 jours. Le premier échantillon apparaîtra ici d'ici quelques minutes.",
    traffic_emptyStopped: "Le tunnel est arrêté : aucun trafic n'est enregistré tant qu'il n'est pas relancé.",
    traffic_noSamples: "aucune donnée",
    traffic_partial: "Données depuis {t} ; il n'y a pas d'échantillons avant.",
    traffic_quiet: "Aucun client n'a émis de trafic sur cette période.",
    traffic_error: "Impossible de lire l'historique : {error}",
    traffic_share: "du total",

    service_title: "Service",
    service_sub: "État du tunnel et actions possibles depuis ici.",
    service_start: "Démarrer",
    service_stop: "Arrêter",
    service_restart: "Redémarrer",
    service_regen: "Régénérer la config",
    service_uninstall: "Désinstaller",
    service_pid: "PID",
    service_mem: "MÉM",
    service_cpu: "CPU",
    service_since: "actif depuis",
    service_actions: "Actions du serveur",
    service_confirmRestart: "Redémarrer le service coupera les connexions actives pendant quelques secondes. Continuer ?",
    service_managedBySystemd: "Le tunnel est géré par les unités systemd de cet hôte : seul un redémarrage est possible depuis ici (équivaut à `outwarp-server restart`).",
    service_managedElsewhere: "Le tunnel est géré par un autre processus de cet hôte (le conteneur `serve`). Il ne peut être ni démarré, ni arrêté, ni redémarré depuis ce panneau ; utilisez votre runtime de conteneurs.",

    logs_title: "Journal",
    logs_sub: "OutWarp et wstunnel sur ce serveur · en direct",
    logs_empty: "Aucune ligne de journal pour le moment.",
    logs_noMatch: "Aucune ligne ne correspond au filtre.",
    logs_filterPh: "Filtrer…",
    logs_level: "Niveau",
    logs_export: "Exporter",
    logs_clear: "Effacer",
    logs_following: "suivi",
    logs_paused: "en pause",
    logs_jumpBottom: "Aller en bas",
    logs_lines: "{n} lignes",

    doctor_title: "Diagnostic",
    doctor_sub: "Diagnostic complet du serveur avec correctifs.",
    doctor_rerun: "Relancer",
    doctor_copy: "Copier le rapport",
    doctor_applyFix: "Appliquer le correctif",
    doctor_ok: "OK",
    doctor_warn: "WARN",
    doctor_fail: "FAIL",
    doctor_lastRun: "dernière exéc. {t}",
    doctor_checks: "{n} vérifications",
    doctor_fix: "correctif",
    doctor_running: "Vérifications en cours…",

    settings_title: "Paramètres",
    set_serverCfg: "Configuration du serveur",
    set_serverCfgSub: "Changements nécessitant un redémarrage du service.",
    set_port: "Port WSS",
    set_wgPort: "Port WireGuard",
    set_endpoint: "Endpoint",
    set_subnet: "Sous-réseau WG",
    set_apply: "Appliquer",
    set_cert: "Certificat TLS",
    set_certSub: "Auto-signé, épinglé par empreinte SHA-256.",
    set_certSubAcme: "Certificat Let's Encrypt géré par Caddy ; il se renouvelle seul et les clients le valident auprès de la CA.",
    set_subnetFixed: "Non modifiable : chaque client a une IP de ce sous-réseau.",
    set_copyFp: "Copier l'empreinte",
    set_rotateCert: "Renouveler le certificat",
    set_rotateCertSub: "Génère un nouveau certificat. Tous les fichiers .owcfg émis cessent d'être valides — vous devrez les régénérer.",
    set_appearance: "Apparence",
    set_language: "Langue",
    set_languageAuto: "Auto",
    set_theme: "Thème",
    set_themeLight: "Clair",
    set_themeDark: "Sombre",
    set_session: "Session",
    set_sessionSub: "Jeton actif dans ce navigateur.",

    copied: "Copié",
    never: "Jamais",
    ago: "il y a",
  },
  pt: {
    serverAdmin: "Admin do servidor",
    remoteSession: "Sessão remota",
    signOut: "Sair",
    search: "Buscar…",
    collapse: "Recolher",

    login_eyebrow: "Acesso ao painel",
    login_title: "Administre seu servidor OutWarp",
    login_sub: "Informe o token de administração do daemon para abrir o painel remoto.",
    login_endpoint: "Endpoint do servidor",
    login_token: "Token de administração",
    login_tokenPh: "ow_admin_••••••••••••",
    login_remember: "Manter esta sessão neste navegador",
    login_btn: "Entrar no painel",
    login_hint: "O token é exibido uma única vez na instalação (outwarp-server admin-token). Guarde-o no navegador ou em um gerenciador de senhas.",
    login_secured: "Sessão criptografada · HTTPS + token",
    login_bad: "Token inválido",
    login_locked: "Tentativas demais · aguarde um momento",

    nav_dashboard: "Visão geral",
    nav_clients: "Clientes",
    nav_traffic: "Tráfego",
    nav_service: "Serviço",
    nav_logs: "Registros",
    nav_doctor: "Doctor",
    nav_settings: "Configurações",

    running: "Em execução",
    stopped: "Parado",
    degraded: "Degradado",
    online: "Online",
    a11y_theme: "Alternar tema",
    a11y_menu: "Menu",
    a11y_close: "Fechar",
    idle: "Inativo",
    offline: "Offline",
    pending: "Pendente",
    disabled: "Desativado",
    uptime: "Tempo ativo",

    dash_title: "Visão geral",
    dash_health: "Saúde do serviço",
    dash_clientsOnline: "clientes online",
    dash_tunnelUp: "Túnel em execução",
    dash_tunnelDown: "Túnel parado",
    dash_noActive: "Nenhum cliente conectado no momento.",
    dash_noTop: "Ainda não há tráfego registrado nas últimas 24 h.",
    dash_throughput: "Vazão ao vivo",
    dash_now: "agora",
    dash_down: "Baixada",
    dash_up: "Subida",
    dash_traffic24: "Tráfego · 24 h",
    dash_total: "Total",
    dash_topTalkers: "Principais clientes · 24 h",
    dash_services: "Serviço",
    dash_network: "Rede",
    dash_tls: "TLS",
    dash_activeClients: "Clientes ativos",
    dash_viewAll: "Ver todos",
    dash_endpoint: "Endpoint",
    dash_publicIp: "IP público",
    dash_subnet: "Sub-rede",
    dash_wgListen: "Escuta WG",
    dash_ipForward: "ip_forward",
    dash_serverIp: "IP do túnel",
    dash_wssPort: "Porta WSS",
    dash_tlsMode: "Modo",
    tls_selfSigned: "Autoassinado",
    tls_acme: "Let's Encrypt · Caddy",
    host_here: "Este processo",
    host_container: "Contêiner (serve)",
    host_systemd: "Unidades systemd",
    host_windows: "App OutWarp Server",
    svc_runsIn: "Executa em",
    svc_control: "Controlar daqui",
    svc_controlFull: "Iniciar, parar e reiniciar",
    svc_controlRestart: "Só reiniciar",
    svc_controlNone: "Nenhum",
    dash_fingerprint: "Impressão digital",
    dash_validUntil: "Válido até",
    dash_transport: "Transporte",
    dash_daysLeft: "{n} dias restantes",

    clients_title: "Clientes",
    clients_sub: "{total} no total · {online} online",
    clients_add: "Adicionar cliente",
    clients_searchPh: "Buscar por nome ou IP…",
    col_name: "Nome",
    col_ip: "IP",
    col_status: "Estado",
    col_handshake: "Últ. HS",
    col_rx: "↓ RX",
    col_tx: "↑ TX",
    col_throughput: "Vazão",
    col_actions: "",
    filter_all: "Todos",
    clients_empty: "Ainda não há clientes",
    clients_emptyBody: "Crie um e envie a ele o .owcfg: ao importá-lo, o cliente gera suas próprias chaves e entra no túnel.",
    clients_noMatch: "Nenhum cliente corresponde à busca ou ao filtro.",

    detail_pubkey: "Chave pública",
    detail_endpoint: "Endpoint",
    detail_allowed: "IPs permitidos",
    detail_dns: "DNS",
    detail_added: "Adicionado",
    detail_transfer: "Transferido",
    detail_session: "Sessão atual",
    detail_live: "Ao vivo",
    detail_pending: "Sem registro — o cliente ainda não resgatou seu token",
    detail_rotate: "Rotacionar chaves e baixar .owcfg",
    detail_revoke: "Revogar",
    detail_disable: "Desativar",
    detail_enable: "Ativar",
    detail_disabled: "Desativado — fora do túnel até você ativá-lo; mantém seu IP, chaves e .owcfg",
    detail_download: "Baixar",
    rotateTitle: "Rotacionar chaves do cliente",
    rotateBody: "Gerar novas chaves invalida o .owcfg atual de {name}. Você terá que reenviar o novo arquivo. Continuar?",
    revokeTitle: "Revogar {name}",
    revokeBody: "O .owcfg dele deixará de funcionar imediatamente e o peer será removido do WireGuard. Continuar?",
    confirm: "Continuar",
    cancel: "Cancelar",

    add_title: "Adicionar cliente",
    add_sub: "O .owcfg contém um token de uso único: o cliente gera suas próprias chaves ao importá-lo e o servidor nunca as vê.",
    add_token: "token de uso único · expira em 15 min",
    add_name: "Nome do cliente",
    add_namePh: "ex.: ana-notebook",
    add_ip: "IP atribuído",
    add_autoAssigned: "automático (próximo livre na sub-rede)",
    add_allowed: "IPs permitidos",
    add_dns: "DNS",
    add_generate: "Gerar perfil",
    add_done: "criado",
    add_writtenTo: "gravado em",
    add_warnKey: "Quem importar este .owcfg antes de expirar passa a ser este cliente. Envie-o por um canal privado (Signal, age, scp), não por e-mail nem por um repositório.",
    add_close: "Criar e fechar",

    traffic_title: "Histórico de tráfego",
    traffic_sub: "Todo o tráfego dos clientes pelo túnel · uma amostra por minuto, 7 dias",
    traffic_window: "Período",
    traffic_1h: "1 h",
    traffic_24h: "24 h",
    traffic_7d: "7 d",
    traffic_rxTotal: "Recebido",
    traffic_rxSub: "RX · o que os clientes enviam",
    traffic_txTotal: "Enviado",
    traffic_txSub: "TX · o que os clientes baixam",
    traffic_peak: "Pico",
    traffic_peakSub: "maior valor entre duas amostras",
    traffic_avg: "Média",
    traffic_avgSub: "em {span} com dados",
    traffic_perClient: "Por cliente",
    traffic_chartTitle: "Tráfego ao longo do tempo",
    traffic_emptyTitle: "Ainda sem dados",
    traffic_emptyBody: "O servidor registra o tráfego de cada cliente uma vez por minuto enquanto o túnel está ativo e o guarda por 7 dias. A primeira amostra aparece aqui em alguns minutos.",
    traffic_emptyStopped: "O túnel está parado: nenhum tráfego é registrado até ele voltar a iniciar.",
    traffic_noSamples: "sem dados",
    traffic_partial: "Dados desde {t}; não há amostras anteriores a isso.",
    traffic_quiet: "Nenhum cliente enviou tráfego neste período.",
    traffic_error: "Não foi possível ler o histórico: {error}",
    traffic_share: "do total",

    service_title: "Serviço",
    service_sub: "Estado do túnel e o que se pode fazer com ele daqui.",
    service_start: "Iniciar",
    service_stop: "Parar",
    service_restart: "Reiniciar",
    service_regen: "Regenerar configuração",
    service_uninstall: "Desinstalar",
    service_pid: "PID",
    service_mem: "MEM",
    service_cpu: "CPU",
    service_since: "ativo desde",
    service_actions: "Ações do servidor",
    service_confirmRestart: "Reiniciar o serviço derruba as conexões ativas por alguns segundos. Continuar?",
    service_managedBySystemd: "O túnel é executado pelas unidades systemd deste host: daqui só é possível reiniciar (equivale a `outwarp-server restart`).",
    service_managedElsewhere: "O túnel é executado por outro processo neste host (o contêiner `serve`). Não é possível iniciá-lo, pará-lo nem reiniciá-lo por este painel web; use o runtime de contêineres.",

    logs_title: "Registros",
    logs_sub: "OutWarp e wstunnel neste servidor · ao vivo",
    logs_empty: "Ainda não há linhas de registro.",
    logs_noMatch: "Nenhuma linha corresponde ao filtro.",
    logs_filterPh: "Filtrar…",
    logs_level: "Nível",
    logs_export: "Exportar",
    logs_clear: "Limpar",
    logs_following: "seguindo",
    logs_paused: "pausado",
    logs_jumpBottom: "Ir para o fim",
    logs_lines: "{n} linhas",

    doctor_title: "Doctor",
    doctor_sub: "Diagnóstico completo do servidor com correções.",
    doctor_rerun: "Executar de novo",
    doctor_copy: "Copiar relatório",
    doctor_applyFix: "Aplicar correção",
    doctor_ok: "OK",
    doctor_warn: "AVISO",
    doctor_fail: "FALHA",
    doctor_lastRun: "última execução {t}",
    doctor_checks: "{n} verificações",
    doctor_fix: "correção",
    doctor_running: "Executando verificações…",

    settings_title: "Configurações",
    set_serverCfg: "Configuração do servidor",
    set_serverCfgSub: "Alterações que exigem reiniciar o serviço.",
    set_port: "Porta WSS",
    set_wgPort: "Porta WireGuard",
    set_endpoint: "Endpoint",
    set_subnet: "Sub-rede WG",
    set_apply: "Aplicar alterações",
    set_cert: "Certificado TLS",
    set_certSub: "Autoassinado, fixado pela impressão digital SHA-256.",
    set_certSubAcme: "Um certificado Let's Encrypt gerenciado pelo Caddy; ele se renova sozinho e os clientes o validam contra a CA.",
    set_subnetFixed: "Não pode ser alterada: todo cliente tem um IP desta sub-rede.",
    set_copyFp: "Copiar impressão digital",
    set_rotateCert: "Rotacionar certificado",
    set_rotateCertSub: "Gera um novo certificado. Todos os arquivos .owcfg emitidos deixam de validar — você terá que regenerá-los.",
    set_appearance: "Aparência",
    set_language: "Idioma",
    set_languageAuto: "Auto",
    set_theme: "Tema",
    set_themeLight: "Claro",
    set_themeDark: "Escuro",
    set_session: "Sessão",
    set_sessionSub: "Token ativo neste navegador.",

    copied: "Copiado",
    never: "Nunca",
    ago: "atrás",
  },
  zh: {
    serverAdmin: "服务器管理",
    remoteSession: "远程会话",
    signOut: "退出登录",
    search: "搜索…",
    collapse: "收起",

    login_eyebrow: "面板访问",
    login_title: "管理你的 OutWarp 服务器",
    login_sub: "输入守护进程的管理员令牌以打开远程网页面板。",
    login_endpoint: "服务器 endpoint",
    login_token: "管理员令牌",
    login_tokenPh: "ow_admin_••••••••••••",
    login_remember: "在此浏览器中保持会话",
    login_btn: "进入面板",
    login_hint: "令牌在安装时只显示一次（outwarp-server admin-token）。请将其保存在浏览器或密码管理器中。",
    login_secured: "加密会话 · HTTPS + 令牌",
    login_bad: "令牌无效",
    login_locked: "尝试次数过多 · 请稍候",

    nav_dashboard: "概览",
    nav_clients: "客户端",
    nav_traffic: "流量",
    nav_service: "服务",
    nav_logs: "日志",
    nav_doctor: "诊断",
    nav_settings: "设置",

    running: "运行中",
    stopped: "已停止",
    degraded: "性能下降",
    online: "在线",
    a11y_theme: "切换主题",
    a11y_menu: "菜单",
    a11y_close: "关闭",
    idle: "空闲",
    offline: "离线",
    pending: "待注册",
    disabled: "已停用",
    uptime: "运行时间",

    dash_title: "概览",
    dash_health: "服务状态",
    dash_clientsOnline: "个客户端在线",
    dash_tunnelUp: "隧道运行中",
    dash_tunnelDown: "隧道已停止",
    dash_noActive: "目前没有客户端连接。",
    dash_noTop: "过去 24 小时内尚无流量记录。",
    dash_throughput: "实时吞吐量",
    dash_now: "现在",
    dash_down: "下行",
    dash_up: "上行",
    dash_traffic24: "流量 · 24 小时",
    dash_total: "总计",
    dash_topTalkers: "流量最高的客户端 · 24 小时",
    dash_services: "服务",
    dash_network: "网络",
    dash_tls: "TLS",
    dash_activeClients: "活动客户端",
    dash_viewAll: "查看全部",
    dash_endpoint: "Endpoint",
    dash_publicIp: "公网 IP",
    dash_subnet: "子网",
    dash_wgListen: "WG 监听",
    dash_ipForward: "ip_forward",
    dash_serverIp: "隧道 IP",
    dash_wssPort: "WSS 端口",
    dash_tlsMode: "模式",
    tls_selfSigned: "自签名",
    tls_acme: "Let's Encrypt · Caddy",
    host_here: "当前进程",
    host_container: "容器（serve）",
    host_systemd: "systemd 单元",
    host_windows: "OutWarp Server 应用",
    svc_runsIn: "运行于",
    svc_control: "在此控制",
    svc_controlFull: "启动、停止和重启",
    svc_controlRestart: "仅重启",
    svc_controlNone: "无",
    dash_fingerprint: "指纹",
    dash_validUntil: "有效期至",
    dash_transport: "传输",
    dash_daysLeft: "剩余 {n} 天",

    clients_title: "客户端",
    clients_sub: "共 {total} 个 · {online} 个在线",
    clients_add: "添加客户端",
    clients_searchPh: "按名称或 IP 搜索…",
    col_name: "名称",
    col_ip: "IP",
    col_status: "状态",
    col_handshake: "上次 HS",
    col_rx: "↓ RX",
    col_tx: "↑ TX",
    col_throughput: "吞吐量",
    col_actions: "",
    filter_all: "全部",
    clients_empty: "还没有客户端",
    clients_emptyBody: "创建一个并把它的 .owcfg 发给对方：导入时会生成客户端自己的密钥，并将其接入隧道。",
    clients_noMatch: "没有符合搜索或筛选条件的客户端。",

    detail_pubkey: "公钥",
    detail_endpoint: "Endpoint",
    detail_allowed: "允许的 IP",
    detail_dns: "DNS",
    detail_added: "添加时间",
    detail_transfer: "已传输",
    detail_session: "当前会话",
    detail_live: "实时",
    detail_pending: "尚未注册：客户端还没有兑换其令牌",
    detail_rotate: "轮换密钥并下载 .owcfg",
    detail_revoke: "吊销",
    detail_disable: "停用",
    detail_enable: "启用",
    detail_disabled: "已停用：在你启用之前不在隧道中；保留其 IP、密钥和 .owcfg",
    detail_download: "下载",
    rotateTitle: "轮换客户端密钥",
    rotateBody: "生成新密钥会使 {name} 当前的 .owcfg 失效。你需要重新发送新文件。是否继续？",
    revokeTitle: "吊销 {name}",
    revokeBody: "其 .owcfg 将立即失效，并且该对等端会从 WireGuard 中移除。是否继续？",
    confirm: "继续",
    cancel: "取消",

    add_title: "添加客户端",
    add_sub: ".owcfg 内含一次性令牌：客户端在导入时自行生成密钥，服务器不会看到这些密钥。",
    add_token: "一次性令牌 · 15 分钟后过期",
    add_name: "客户端名称",
    add_namePh: "例如 ana-laptop",
    add_ip: "分配的 IP",
    add_autoAssigned: "自动分配（子网中下一个空闲地址）",
    add_allowed: "允许的 IP",
    add_dns: "DNS",
    add_generate: "生成配置文件",
    add_done: "已创建",
    add_writtenTo: "已写入",
    add_warnKey: "在过期前导入此 .owcfg 的人就会成为该客户端。请通过私密渠道（Signal、age、scp）发送，不要通过电子邮件或代码仓库。",
    add_close: "创建并关闭",

    traffic_title: "流量历史",
    traffic_sub: "通过隧道的所有客户端流量 · 每分钟一个采样，保留 7 天",
    traffic_window: "时间范围",
    traffic_1h: "1 小时",
    traffic_24h: "24 小时",
    traffic_7d: "7 天",
    traffic_rxTotal: "已接收",
    traffic_rxSub: "RX · 客户端上传的数据",
    traffic_txTotal: "已发送",
    traffic_txSub: "TX · 客户端下载的数据",
    traffic_peak: "峰值",
    traffic_peakSub: "两次采样之间的最高值",
    traffic_avg: "平均值",
    traffic_avgSub: "在有数据的 {span} 内",
    traffic_perClient: "按客户端",
    traffic_chartTitle: "流量随时间变化",
    traffic_emptyTitle: "暂无数据",
    traffic_emptyBody: "隧道运行期间，服务器每分钟记录一次各客户端的流量，并保留 7 天。第一个采样将在几分钟后显示在这里。",
    traffic_emptyStopped: "隧道已停止：在其再次启动前不会记录流量。",
    traffic_noSamples: "无数据",
    traffic_partial: "数据始于 {t}；在此之前没有采样。",
    traffic_quiet: "此时间范围内没有客户端发送流量。",
    traffic_error: "无法读取历史记录：{error}",
    traffic_share: "占总量",

    service_title: "服务",
    service_sub: "隧道状态，以及可以在此执行的操作。",
    service_start: "启动",
    service_stop: "停止",
    service_restart: "重启",
    service_regen: "重新生成配置",
    service_uninstall: "卸载",
    service_pid: "PID",
    service_mem: "MEM",
    service_cpu: "CPU",
    service_since: "启动于",
    service_actions: "服务器操作",
    service_confirmRestart: "重启服务会使活动连接中断几秒钟。是否继续？",
    service_managedBySystemd: "隧道由此主机的 systemd 单元运行：在此只能重启（等同于 `outwarp-server restart`）。",
    service_managedElsewhere: "隧道由此主机上的另一个进程（`serve` 容器）运行。无法从此网页面板启动、停止或重启；请使用你的容器运行时。",

    logs_title: "日志",
    logs_sub: "此服务器上的 OutWarp 和 wstunnel · 实时",
    logs_empty: "还没有日志行。",
    logs_noMatch: "没有符合筛选条件的行。",
    logs_filterPh: "筛选…",
    logs_level: "级别",
    logs_export: "导出",
    logs_clear: "清除",
    logs_following: "跟随中",
    logs_paused: "已暂停",
    logs_jumpBottom: "跳到底部",
    logs_lines: "{n} 行",

    doctor_title: "诊断",
    doctor_sub: "完整的服务器诊断及修复建议。",
    doctor_rerun: "重新运行",
    doctor_copy: "复制报告",
    doctor_applyFix: "应用修复",
    doctor_ok: "OK",
    doctor_warn: "WARN",
    doctor_fail: "FAIL",
    doctor_lastRun: "上次运行 {t}",
    doctor_checks: "{n} 项检查",
    doctor_fix: "修复",
    doctor_running: "正在运行检查…",

    settings_title: "设置",
    set_serverCfg: "服务器配置",
    set_serverCfgSub: "需要重启服务才能生效的更改。",
    set_port: "WSS 端口",
    set_wgPort: "WireGuard 端口",
    set_endpoint: "Endpoint",
    set_subnet: "WG 子网",
    set_apply: "应用更改",
    set_cert: "TLS 证书",
    set_certSub: "自签名，通过 SHA-256 指纹固定。",
    set_certSubAcme: "由 Caddy 管理的 Let's Encrypt 证书；它会自动续期，客户端通过 CA 对其进行验证。",
    set_subnetFixed: "无法更改：每个客户端的 IP 都来自此子网。",
    set_copyFp: "复制指纹",
    set_rotateCert: "轮换证书",
    set_rotateCertSub: "生成新证书。所有已签发的 .owcfg 文件将无法通过验证，你需要重新生成它们。",
    set_appearance: "外观",
    set_language: "语言",
    set_languageAuto: "自动",
    set_theme: "主题",
    set_themeLight: "浅色",
    set_themeDark: "深色",
    set_session: "会话",
    set_sessionSub: "此浏览器中的有效令牌。",

    copied: "已复制",
    never: "从不",
    ago: "前",
  },
};

// ── formatters ──────────────────────────────────────────────────────────────
function fmtBytes(b) {
  if (b == null) return "—";
  if (b < 1024) return Math.round(b) + " B";
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
// Axis tick for the Traffic chart: a clock time for windows up to a day,
// a short day for the week.
function fmtTick(ts, bucketSeconds, lang) {
  const d = new Date(ts * 1000);
  if (bucketSeconds >= 3600) return d.toLocaleDateString(lang, { weekday: "short", day: "numeric" });
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}`;
}
function fmtRange(ts, bucketSeconds, lang) {
  const a = new Date(ts * 1000), b = new Date((ts + bucketSeconds) * 1000);
  const p = (n) => String(n).padStart(2, "0");
  const hm = (d) => `${p(d.getHours())}:${p(d.getMinutes())}`;
  const day = bucketSeconds >= 3600 ? a.toLocaleDateString(lang, { weekday: "short", day: "numeric" }) + " " : "";
  return `${day}${hm(a)}–${hm(b)}`;
}
// A stretch of time, coarse: "45 min", "3 h", "2 d".
function fmtSpan(sec) {
  sec = Math.max(0, Math.round(sec || 0));
  if (sec < 3600) return `${Math.max(1, Math.round(sec / 60))} min`;
  if (sec < 86400) return `${Math.round(sec / 3600)} h`;
  return `${Math.round(sec / 86400)} d`;
}
function tr(str, vars) {
  if (!vars) return str;
  return str.replace(/\{(\w+)\}/g, (_, k) => (vars[k] != null ? vars[k] : `{${k}}`));
}
function nowClock(ts) {
  // ts = seconds since the epoch (a log entry's own time); default: now.
  const d = ts ? new Date(ts * 1000) : new Date();
  const p = (n) => String(n).padStart(2, "0");
  return `${p(d.getHours())}:${p(d.getMinutes())}:${p(d.getSeconds())}.${String(d.getMilliseconds()).padStart(3, "0")}`;
}

// Bounded peak-hold for a rate-based chart's Y-axis scale.
//
// A raw per-tick max (recompute the scale from only what's on screen right
// now) makes a genuinely steady rate look like it's constantly surging and
// settling: real traffic arrives in bursts (TCP segments, video chunks), so
// the instantaneous per-tick rate is naturally spiky even when the average
// holds steady, and rescaling the axis to match every such blip makes the
// whole chart's proportions visibly reshuffle tick to tick.
//
// The fix isn't "hold the peak, decay it slowly" — that was tried (0.12.1)
// and traded one bug for another: with no bound tied to how much history is
// actually visible, an exponential decay remembers a one-off spike (a speed
// test) for exactly as long as it takes the math to fall below the real
// current rate, which grows with how much bigger the spike was — for a
// speed test against a normal client that can be minutes, during which
// smaller-but-real ongoing traffic (a video call, a stream) draws as a flat
// line even though the byte counters are genuinely moving.
//
// Instead, remember the maximum of the last `memory` window-max samples.
// That bounds total memory to (window + memory) samples *regardless of how
// large the spike was* — once the spike itself has scrolled out of the
// window AND out of this trailing history, the scale reflects only what's
// actually on screen, same as a fresh recompute, but without a single
// bursty low sample being able to collapse it in between.
function makeBoundedPeak(memory) {
  let hist = new Array(memory).fill(1);
  return (windowMax) => {
    hist = [...hist.slice(1), windowMax];
    return Math.max(...hist, 1);
  };
}

// SVG path through `pts` ([x, y] pairs) as a smooth curve instead of a spiky
// polyline: uniform Catmull-Rom converted to cubic béziers, the same curve the
// client GUI's traffic chart draws. Control points are clamped to
// [yMin, yMax] so a sharp jump cannot overshoot past the chart's centre axis
// or out of its box; the curve still passes through every sample.
function smoothPath(pts, yMin = -Infinity, yMax = Infinity) {
  if (!pts.length) return "";
  const f = (n) => n.toFixed(1);
  const cy = (y) => Math.min(yMax, Math.max(yMin, y));
  let d = `M${f(pts[0][0])} ${f(pts[0][1])}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[i - 1] || pts[i];
    const p1 = pts[i];
    const p2 = pts[i + 1];
    const p3 = pts[i + 2] || p2;
    const c1x = p1[0] + (p2[0] - p0[0]) / 6, c1y = cy(p1[1] + (p2[1] - p0[1]) / 6);
    const c2x = p2[0] - (p3[0] - p1[0]) / 6, c2y = cy(p2[1] - (p3[1] - p1[1]) / 6);
    d += ` C${f(c1x)} ${f(c1y)}, ${f(c2x)} ${f(c2y)}, ${f(p2[0])} ${f(p2[1])}`;
  }
  return d;
}

// Weighted moving average for what a chart *draws* (the numbers shown next to
// it stay raw). The 2 s rate samples jitter by tens of percent even under
// steady traffic, which a curve alone still draws as a comb of small peaks.
// The kernel is renormalised at the edges so the newest sample is not pulled
// toward zero.
function smoothSeries(values, kernel = [1, 2, 3, 2, 1]) {
  const r = (kernel.length - 1) / 2;
  return values.map((_, i) => {
    let sum = 0, weight = 0;
    kernel.forEach((k, j) => {
      const v = values[i + j - r];
      if (v !== undefined) { sum += v * k; weight += k; }
    });
    return sum / weight;
  });
}

// One client's throughput from two readings of its byte counters. A reading
// less than `minGap` seconds after the previous one is ignored (the previous
// rate stands): the same counters read twice a few ms apart — an event and a
// fetch, or a burst a proxy held back — gave a rate of 0 or a spike, drawn as
// a dip or a peak. Returns the new state and whether it moved on.
function nextRate(prev, row, now, minGap = 1.0) {
  const t = row.sampled_at != null ? row.sampled_at : now;
  const rx = row.rx_bytes || 0, tx = row.tx_bytes || 0;
  if (!prev) return { state: { rx, tx, t, rxBps: 0, txBps: 0 }, advanced: false };
  if (t - prev.t < minGap) return { state: prev, advanced: false };
  const dt = t - prev.t;
  return {
    state: { rx, tx, t, rxBps: Math.max(0, (rx - prev.rx) / dt), txBps: Math.max(0, (tx - prev.tx) / dt) },
    advanced: true,
  };
}

// The live chart places each sample by the moment the server took it, moved
// onto this browser's clock. The two clocks differ by an unknown skew plus
// the delivery delay of each sample, so the offset is the smallest
// (arrival − sampled_at) among the last few: it is the skew plus the fastest
// delivery, and every other sample then lands at or after its own moment.
function nextClockOffset(recent, lag, keep = 30) {
  const r = recent.slice(-(keep - 1)).concat(lag);
  return { recent: r, offset: Math.min(...r) };
}
// Browser-clock time of a sample; never earlier than the previous one, so a
// shrinking offset cannot reorder the curve.
function sampleTime(serverT, offset, lastT) {
  const t = serverT + offset;
  return lastT == null ? t : Math.max(t, lastT + 0.05);
}
// Seconds the chart's layer has slid left of its first sample: the right edge
// shows `lagS` ago, the left edge `windowS` before that.
function chartShift(firstT, nowS, lagS, windowS) {
  return nowS - lagS - windowS - firstT;
}

// Log entries arrive from live events and from fetches; the server's
// sequence number keeps each one once. A restarted server counts from 1
// again, so a batch starting at 1 below what we have starts over.
function mergeLogs(logs, lastSeq, entries, max = 400) {
  const list = entries || [];
  if (!list.length) return { logs, lastSeq };
  if (list[0].seq <= 1 && lastSeq > list[list.length - 1].seq) { logs = []; lastSeq = 0; }
  const fresh = list.filter((e) => e.seq > lastSeq);
  if (!fresh.length) return { logs, lastSeq };
  return {
    logs: logs.concat(fresh.map((e) => ({
      seq: e.seq, t: nowClock(e.ts), svc: "", lvl: e.level || "info", msg: e.msg,
    }))).slice(-max),
    lastSeq: fresh[fresh.length - 1].seq,
  };
}

window.DS_STR = DS_STR;
window.DSfmt = { fmtBytes, fmtBps, fmtDuration, fmtAgo, fmtTick, fmtRange, fmtSpan, tr, nowClock, makeBoundedPeak, smoothPath, smoothSeries, nextRate, mergeLogs, nextClockOffset, sampleTime, chartShift };
