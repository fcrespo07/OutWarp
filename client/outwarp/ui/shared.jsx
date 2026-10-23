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
    nav_profiles: "Perfiles",
    nav_logs: "Registro",
    nav_settings: "Ajustes",
    nav_about: "Acerca de",
    about_sub: "Información de la aplicación y de sus componentes.",
    about_blurb: "Cliente OutWarp: levanta un túnel WireGuard sobre WebSocket usando wstunnel como transporte, para redes que bloquean UDP.",
    about_openRepo: "Abrir repositorio",
    about_version: "Versión",
    about_releases: "Novedades",
    about_copy: "Copiar información",
    diag_title: "Comprobaciones",
    diag_sub: "Revisa que todo lo que necesita OutWarp esté en su sitio.",
    diag_run: "Comprobar",
    diag_rerun: "Volver a comprobar",
    diag_running: "Comprobando…",
    diag_allOk: "Todo en orden.",
    diag_issues: "Hay cosas que revisar.",
    diag_fail: "Fallo",
    diag_warn: "Aviso",
    diag_pass: "Bien",
    diag_skip: "Omitido",
    diag_error: "No se pudieron hacer las comprobaciones.",
    about_thirdParty: "Componentes de terceros",
    about_openUrl: "Abrir →",
    about_disclaimer: "OutWarp se distribuye bajo la licencia PolyForm Noncommercial 1.0.0. WireGuard es marca registrada de Jason A. Donenfeld. wstunnel es un proyecto independiente de erebe.",
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
    set_checkUpdatesSub: "Al abrir OutWarp comprueba si hay una versión nueva y lo avisa en la barra lateral.",
    upd_sidebar: "Versión {v} disponible",
    set_killSwitch: "Kill switch",
    set_killSwitchSub: "Bloquea todo el tráfico de internet si el túnel se cae.",
    set_autoconnect: "Reconectar si se cae",
    set_autoconnectSub: "Volver a conectar solo si el túnel se cae mientras está activo.",
    set_autoconnectLaunch: "Conectar al abrir",
    set_autoconnectLaunchSub: "Levantar el túnel automáticamente al iniciar OutWarp.",
    set_startup: "Abrir OutWarp al iniciar sesión",
    set_startupSub: "Arrancar OutWarp automáticamente al entrar en tu cuenta de usuario.",
    set_minimizeTray: "Empezar en la bandeja",
    set_minimizeTraySub: "Al abrir OutWarp, mostrar solo el icono de la bandeja en lugar de la ventana.",
    set_closeTray: "Seguir en segundo plano al cerrar",
    set_closeTraySub: "Cerrar la ventana la oculta en la bandeja y OutWarp sigue conectado. Para salir del todo, usa «Parar y salir» en el menú del icono.",
    set_advanced: "Modo avanzado",
    set_advancedSub: "Mostrar IPs, claves y huella del certificado",
    set_service: "Ejecutar como servicio en segundo plano",
    set_serviceSub: "Cede el túnel a una unidad de usuario de systemd que lo mantiene sin esta ventana. Equivale a `outwarp service install`.",
    set_serviceActive: "Activo: esta ventana solo muestra el estado.",
    set_preferTui: "Abrir la interfaz de terminal desde el menú",
    set_preferTuiSub: "El lanzador de aplicaciones abre `outwarp tui` en una terminal en vez de esta ventana. Equivale a `outwarp ui tui`.",
    set_tlsIntercept: "Permitir redes que inspeccionan TLS",
    set_tlsInterceptSub: "Continúa aunque la huella del certificado no coincida (proxies de instituto/empresa). WireGuard sigue cifrando el tráfico de extremo a extremo.",
    set_language: "Idioma",
    set_languageAuto: "Automático (sistema)",
    set_theme: "Tema",
    set_themeAuto: "Automático",
    set_themeLight: "Claro",
    set_themeDark: "Oscuro",
    set_groupAppearance: "Apariencia",
    set_groupConnection: "Conexión",
    set_groupSecurity: "Seguridad",
    set_groupStartup: "Inicio y ventana",
    set_groupAdvanced: "Avanzado",
    set_subtitle: "Los cambios se aplican al instante.",
    set_groupUpdates: "Actualizaciones",
    set_errorTitle: "No se pudo aplicar el ajuste",

    // Logs
    logs_title: "Registro de actividad",
    logs_sub: "Lo que OutWarp va haciendo, en vivo.",
    logs_clear: "Limpiar",
    logs_export: "Exportar",
    logs_filter: "Filtrar…",

    // Profiles
    profiles_title: "Perfiles",
    profiles_add: "Añadir perfil",
    profiles_active: "Activo",
    profiles_use: "Usar",
    profiles_switchTitle: "Cambiar de perfil",
    profiles_switchConfirm: "Cambiar a «{name}» desconecta el túnel actual.",
    profiles_importHint: "Importar un .owcfg añade un perfil y lo activa. Si es del mismo servidor y dispositivo que uno que ya tienes, lo sustituye.",
    profiles_expired: "Caducado",

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
    edit_bypass: "Rutas de bypass",
    edit_bypassHint: "IPs, CIDRs o dominios del servidor que quedan fuera del túnel. Separados por comas.",
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
    profiles_removeConfirm: "¿Eliminar el perfil «{name}»? Tendrás que importar de nuevo su .owcfg.",

    // Errors / status
    error_title: "No se pudo conectar",
    error_genericBody: "Puede ser un error de huella TLS, un endpoint inalcanzable o un fallo de WireGuard.",
    error_checkLog: "Revisa el registro para el detalle completo.",
    error_importNew: "Importar nuevo .owcfg",
    retry: "Reintentar",
    bootError: "No se pudo iniciar la interfaz.",
    integrity_av: "Tu antivirus parece haber eliminado parte de OutWarp.",
    integrity_av_cta: "Es un falso positivo conocido (HackTool:Win32/Wstunnel). Reinstala y añade una exclusión para la carpeta de OutWarp.",
    integrity_generic: "Faltan ficheros del programa. Reinstala OutWarp para repararlos.",
    integrity_details: "Ver detalles",
    integrity_hide: "Ocultar detalles",
    integrity_help: "Cómo solucionarlo",
    integrity_dismiss: "Cerrar aviso",
    hostile_headline: "Red hostil detectada",
    hostile_auto_on: "OutWarp ha activado DNS-bypass (1.1.1.1) automáticamente porque la red parece interceptar peticiones.",
    hostile_auto_off: "La red parece interceptar peticiones. Activa el modo hostil en el perfil si la conexión falla.",
    hostile_dismiss: "Cerrar aviso",
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
    home_ribbon: "Todo tu tráfico sale cifrado por tu propio servidor.",
    home_clickToConnect: "Pulsa el botón para conectar.",
    home_details: "Esta conexión",
    home_server: "Servidor",
    home_security: "Seguridad",
    home_killSwitch: "Kill switch",
    home_expires: "Caduca",
    home_never: "Nunca",
    home_route: "Ruta",
    home_exit: "IP de salida",
    home_change: "Cambiar",
    home_switch: "Cambiar de perfil",
    home_manage: "Gestionar perfiles",
    sec_pin: "Certificado anclado a tu servidor",
    sec_ca: "Certificado verificado por una CA",
    ks_on: "Activo: sin túnel no sale nada",
    ks_off: "Desactivado",
    route_direct: "Directa",
    route_hostile: "Directa, con DNS público",
    route_proxy: "Por el proxy HTTP",
    route_port: "Puerto alternativo {port}",
    err_hint_unreachable: "No se llega al servidor. Comprueba que está encendido y que su puerto está abierto en el firewall o el router.",
    err_hint_cert: "El certificado del servidor no es el de tu perfil. Si lo han reinstalado o renovado, pide un .owcfg nuevo; si no, algo en esta red podría estar interceptando la conexión.",
    err_hint_token: "El token de este perfil ha caducado o ya se usó. Pide al administrador un .owcfg nuevo.",
    err_hint_blocked: "El antivirus o Windows ha bloqueado wstunnel. Restáuralo desde la cuarentena de Microsoft Defender o reinstala OutWarp.",
    err_hint_network: "Esta red no deja pasar el túnel por ninguna de las rutas probadas. Prueba en otra red; un servidor con dominio y certificado real pasa por más redes.",
    err_hint_expired: "Este perfil ha caducado. Pide al administrador uno nuevo.",
    err_details: "Detalles técnicos",
    err_viewLog: "Ver registro",
    throughput_title: "Tráfico",
    throughput_window: "últimos {n}",
    throughput_empty: "Esperando el primer dato…",
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
    nav_profiles: "Profiles",
    nav_logs: "Logs",
    nav_settings: "Settings",
    nav_about: "About",
    about_sub: "Application info and component licenses.",
    about_blurb: "OutWarp client: brings up a WireGuard tunnel over WebSocket using wstunnel as transport, for networks that block UDP.",
    about_openRepo: "Open repository",
    about_version: "Version",
    about_releases: "What's new",
    about_copy: "Copy info",
    diag_title: "Health checks",
    diag_sub: "Checks that everything OutWarp needs is in place.",
    diag_run: "Run checks",
    diag_rerun: "Run again",
    diag_running: "Checking…",
    diag_allOk: "Everything looks fine.",
    diag_issues: "Some things need a look.",
    diag_fail: "Failed",
    diag_warn: "Warning",
    diag_pass: "OK",
    diag_skip: "Skipped",
    diag_error: "The checks could not run.",
    about_thirdParty: "Third-party components",
    about_openUrl: "Open →",
    about_disclaimer: "OutWarp is distributed under the PolyForm Noncommercial 1.0.0 license. WireGuard is a registered trademark of Jason A. Donenfeld. wstunnel is an independent project by erebe.",
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
    set_checkUpdatesSub: "When OutWarp opens, check for a newer version and flag it in the sidebar.",
    upd_sidebar: "Version {v} available",
    set_killSwitch: "Kill switch",
    set_killSwitchSub: "Block all internet traffic if the tunnel drops.",
    set_autoconnect: "Reconnect if it drops",
    set_autoconnectSub: "Connect again on its own if the tunnel drops while active.",
    set_autoconnectLaunch: "Connect on launch",
    set_autoconnectLaunchSub: "Bring the tunnel up automatically when OutWarp starts.",
    set_startup: "Open OutWarp at login",
    set_startupSub: "Launch OutWarp automatically when you sign in.",
    set_minimizeTray: "Start in the tray",
    set_minimizeTraySub: "When OutWarp opens, show only the tray icon instead of the window.",
    set_closeTray: "Keep running when the window is closed",
    set_closeTraySub: "Closing the window hides it to the tray and OutWarp stays connected. To quit completely, use “Stop and quit” in the tray icon's menu.",
    set_advanced: "Advanced mode",
    set_advancedSub: "Show IPs, keys and certificate fingerprint",
    set_service: "Run as a background service",
    set_serviceSub: "Hand the tunnel to a systemd user unit that keeps it up without this window. Same as `outwarp service install`.",
    set_serviceActive: "Active: this window only shows its status.",
    set_preferTui: "Open the terminal UI from the app menu",
    set_preferTuiSub: "The application launcher opens `outwarp tui` in a terminal instead of this window. Same as `outwarp ui tui`.",
    set_tlsIntercept: "Allow TLS-intercepting networks",
    set_tlsInterceptSub: "Connect even if the certificate fingerprint doesn't match (school/corporate proxies). WireGuard still encrypts your traffic end-to-end.",
    set_language: "Language",
    set_languageAuto: "Automatic (system)",
    set_theme: "Theme",
    set_themeAuto: "Auto",
    set_themeLight: "Light",
    set_themeDark: "Dark",
    set_groupAppearance: "Appearance",
    set_groupConnection: "Connection",
    set_groupSecurity: "Security",
    set_groupStartup: "Startup and window",
    set_groupAdvanced: "Advanced",
    set_subtitle: "Changes apply right away.",
    set_groupUpdates: "Updates",
    set_errorTitle: "Couldn't apply the setting",

    logs_title: "Activity log",
    logs_sub: "What OutWarp is doing, live.",
    logs_clear: "Clear",
    logs_export: "Export",
    logs_filter: "Filter…",

    profiles_title: "Profiles",
    profiles_add: "Add profile",
    profiles_active: "Active",
    profiles_use: "Use",
    profiles_switchTitle: "Switch profile",
    profiles_switchConfirm: "Switching to “{name}” disconnects the current tunnel.",
    profiles_importHint: "Importing an .owcfg adds a profile and makes it active. If it is for the same server and device as one you have, it replaces that one.",
    profiles_expired: "Expired",

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
    edit_bypass: "Bypass routes",
    edit_bypassHint: "Server IPs, CIDRs or hostnames routed outside the tunnel. Comma-separated.",
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
    profiles_removeConfirm: "Remove the profile “{name}”? You'll need to import its .owcfg again.",

    error_title: "Couldn't connect",
    error_genericBody: "It may be a TLS fingerprint mismatch, an unreachable endpoint or a WireGuard failure.",
    error_checkLog: "Check the activity log for the full detail.",
    error_importNew: "Import a new .owcfg",
    retry: "Retry",
    bootError: "Couldn't start the interface.",
    integrity_av: "Your antivirus appears to have removed part of OutWarp.",
    integrity_av_cta: "It's a known false positive (HackTool:Win32/Wstunnel). Reinstall and add an exclusion for the OutWarp folder.",
    integrity_generic: "Some program files are missing. Reinstall OutWarp to repair them.",
    integrity_details: "Show details",
    integrity_hide: "Hide details",
    integrity_help: "How to fix",
    integrity_dismiss: "Dismiss",
    hostile_headline: "Hostile network detected",
    hostile_auto_on: "OutWarp enabled DNS-bypass (1.1.1.1) automatically because the network appears to intercept lookups.",
    hostile_auto_off: "The network appears to intercept lookups. Switch hostile-mode to 'on' in the profile if the tunnel keeps failing.",
    hostile_dismiss: "Dismiss",
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
    home_ribbon: "All your traffic leaves encrypted through your own server.",
    home_clickToConnect: "Click the dial to connect.",
    home_details: "This connection",
    home_server: "Server",
    home_security: "Security",
    home_killSwitch: "Kill switch",
    home_expires: "Expires",
    home_never: "Never",
    home_route: "Route",
    home_exit: "Exit IP",
    home_change: "Change",
    home_switch: "Switch profile",
    home_manage: "Manage profiles",
    sec_pin: "Certificate pinned to your server",
    sec_ca: "Certificate verified by a CA",
    ks_on: "On: nothing leaves without the tunnel",
    ks_off: "Off",
    route_direct: "Direct",
    route_hostile: "Direct, public DNS",
    route_proxy: "Through the HTTP proxy",
    route_port: "Alternate port {port}",
    err_hint_unreachable: "The server can't be reached. Check that it is running and that its port is open on the firewall or router.",
    err_hint_cert: "The server's certificate is not the one in your profile. If it was reinstalled or renewed, ask for a new .owcfg; otherwise something on this network may be intercepting the connection.",
    err_hint_token: "This profile's token has expired or was already used. Ask the administrator for a new .owcfg.",
    err_hint_blocked: "Your antivirus or Windows blocked wstunnel. Restore it from Microsoft Defender's quarantine or reinstall OutWarp.",
    err_hint_network: "This network lets the tunnel through none of the routes tried. Try another network; a server with a domain and a real certificate gets through more of them.",
    err_hint_expired: "This profile has expired. Ask the administrator for a new one.",
    err_details: "Technical details",
    err_viewLog: "View log",
    throughput_title: "Traffic",
    throughput_window: "last {n}",
    throughput_empty: "Waiting for the first sample…",
    notConnected: "No active tunnel",
  },
  fr: {
    // Window title bar
    win_minimize: "Réduire",
    win_maximize: "Agrandir",
    win_restore: "Restaurer",
    win_close: "Fermer",
    welcomeTitle: "Se connecter à votre tunnel",
    welcomeSub: "Importez un fichier de configuration .owcfg partagé par votre serveur.",
    importFile: "Importer un fichier",
    importDrop: "Déposez votre .owcfg ici",
    importPaste: "Collez le contenu de votre .owcfg",
    importHint: "Format pris en charge : .owcfg généré par outwarp-server add-client",
    import_tabFile: "Depuis un fichier",
    import_tabPaste: "Coller du texte",
    import_loadFromPaste: "Importer",

    disconnected: "Déconnecté",
    connecting: "Connexion…",
    handshake: "Handshake WireGuard",
    reconnecting: "Reconnexion",
    connected: "Connecté",
    error: "Erreur de connexion",

    connect: "Se connecter",
    disconnect: "Se déconnecter",
    cancel: "Annuler",

    publicIp: "IP publique",
    location: "Emplacement",
    latency: "Latence",
    upload: "Envoi",
    download: "Réception",
    transferred: "Transféré",
    sessionTime: "Durée de session",
    lastHandshake: "Dernier handshake",
    endpoint: "Endpoint",
    fingerprint: "Empreinte TLS",

    nav_home: "Connexion",
    nav_profiles: "Profils",
    nav_logs: "Journal",
    nav_settings: "Paramètres",
    nav_about: "À propos",
    about_sub: "Informations sur l'application et licences des composants.",
    about_blurb: "Client OutWarp : établit un tunnel WireGuard via WebSocket avec wstunnel comme transport, pour les réseaux qui bloquent l'UDP.",
    about_openRepo: "Ouvrir le dépôt",
    about_version: "Version",
    about_releases: "Nouveautés",
    about_copy: "Copier les infos",
    diag_title: "Vérifications",
    diag_sub: "Vérifie que tout ce dont OutWarp a besoin est en place.",
    diag_run: "Lancer les vérifications",
    diag_rerun: "Relancer",
    diag_running: "Vérification…",
    diag_allOk: "Tout semble en ordre.",
    diag_issues: "Certains points demandent votre attention.",
    diag_fail: "Échec",
    diag_warn: "Avertissement",
    diag_pass: "OK",
    diag_skip: "Ignoré",
    diag_error: "Les vérifications n'ont pas pu s'exécuter.",
    about_thirdParty: "Composants tiers",
    about_openUrl: "Ouvrir →",
    about_disclaimer: "OutWarp est distribué sous licence PolyForm Noncommercial 1.0.0. WireGuard est une marque déposée de Jason A. Donenfeld. wstunnel est un projet indépendant d'erebe.",
    // Updates
    upd_check: "Rechercher des mises à jour",
    upd_checking: "Vérification…",
    upd_current: "Vous utilisez la dernière version.",
    upd_available: "Nouvelle version disponible :",
    upd_now: "Mettre à jour",
    upd_downloading: "Téléchargement…",
    upd_applying: "Application en arrière-plan. L'application va redémarrer d'elle-même…",
    upd_error: "Impossible de rechercher des mises à jour.",
    upd_seeReleases: "Voir les versions",
    upd_linux: "Pour mettre à jour sous Linux, exécutez cette commande :",
    upd_copy: "Copier",
    upd_copied: "Copié",

    set_checkUpdates: "Rechercher les mises à jour au démarrage",
    set_checkUpdatesSub: "À l'ouverture d'OutWarp, vérifie la présence d'une version plus récente et l'indique dans la barre latérale.",
    upd_sidebar: "Version {v} disponible",
    set_killSwitch: "Kill switch",
    set_killSwitchSub: "Bloque tout le trafic Internet si le tunnel tombe.",
    set_autoconnect: "Se reconnecter en cas de coupure",
    set_autoconnectSub: "Se reconnecte tout seul si le tunnel tombe pendant qu'il est actif.",
    set_autoconnectLaunch: "Se connecter au lancement",
    set_autoconnectLaunchSub: "Active le tunnel automatiquement au démarrage d'OutWarp.",
    set_startup: "Ouvrir OutWarp à l'ouverture de session",
    set_startupSub: "Lance OutWarp automatiquement quand vous ouvrez votre session.",
    set_minimizeTray: "Démarrer dans la zone de notification",
    set_minimizeTraySub: "À l'ouverture d'OutWarp, affiche uniquement l'icône de la zone de notification au lieu de la fenêtre.",
    set_closeTray: "Continuer à s'exécuter à la fermeture de la fenêtre",
    set_closeTraySub: "Fermer la fenêtre la masque dans la zone de notification et OutWarp reste connecté. Pour quitter complètement, utilisez « Arrêter et quitter » dans le menu de l'icône.",
    set_advanced: "Mode avancé",
    set_advancedSub: "Afficher les IP, les clés et l'empreinte du certificat",
    set_service: "Exécuter en tant que service d'arrière-plan",
    set_serviceSub: "Confie le tunnel à une unité systemd utilisateur qui le maintient sans cette fenêtre. Équivaut à `outwarp service install`.",
    set_serviceActive: "Actif : cette fenêtre n'affiche que son état.",
    set_preferTui: "Ouvrir l'interface terminal depuis le menu des applications",
    set_preferTuiSub: "Le lanceur d'applications ouvre `outwarp tui` dans un terminal au lieu de cette fenêtre. Équivaut à `outwarp ui tui`.",
    set_tlsIntercept: "Autoriser les réseaux qui interceptent le TLS",
    set_tlsInterceptSub: "Se connecter même si l'empreinte du certificat ne correspond pas (proxys d'école ou d'entreprise). WireGuard continue de chiffrer votre trafic de bout en bout.",
    set_language: "Langue",
    set_languageAuto: "Automatique (système)",
    set_theme: "Thème",
    set_themeAuto: "Auto",
    set_themeLight: "Clair",
    set_themeDark: "Sombre",
    set_groupAppearance: "Apparence",
    set_groupConnection: "Connexion",
    set_groupSecurity: "Sécurité",
    set_groupStartup: "Démarrage et fenêtre",
    set_groupAdvanced: "Avancé",
    set_subtitle: "Les changements s'appliquent immédiatement.",
    set_groupUpdates: "Mises à jour",
    set_errorTitle: "Impossible d'appliquer le paramètre",

    logs_title: "Journal d'activité",
    logs_sub: "Ce que fait OutWarp, en direct.",
    logs_clear: "Effacer",
    logs_export: "Exporter",
    logs_filter: "Filtrer…",

    profiles_title: "Profils",
    profiles_add: "Ajouter un profil",
    profiles_active: "Actif",
    profiles_use: "Utiliser",
    profiles_switchTitle: "Changer de profil",
    profiles_switchConfirm: "Passer à « {name} » déconnecte le tunnel actuel.",
    profiles_importHint: "Importer un .owcfg ajoute un profil et l'active. S'il concerne le même serveur et le même appareil qu'un profil existant, il le remplace.",
    profiles_expired: "Expiré",

    edit_title: "Paramètres du profil",
    edit_sub: "Valeurs de connexion attribuées par votre serveur.",
    edit_open: "Modifier la connexion",
    edit_disclaimerTitle: "Vous allez modifier la configuration",
    edit_disclaimerBody: "Ces valeurs viennent de votre serveur et doivent rarement être changées. Un mauvais réglage peut empêcher le tunnel de se connecter. En cas de problème, utilisez « Rétablir les valeurs par défaut ».",
    edit_disclaimerAck: "J'ai compris, je veux modifier",
    edit_name: "Nom du profil",
    edit_mtu: "MTU",
    edit_mtuHint: "Entre 576 et 1500. Par défaut : 1380.",
    edit_dns: "Serveurs DNS",
    edit_dnsHint: "Séparés par des virgules.",
    edit_clientIp: "IP du client",
    edit_clientIpHint: "Doit correspondre à l'adresse attribuée sur le serveur (ex. 10.0.0.2/32).",
    edit_bypass: "Routes de contournement",
    edit_bypassHint: "IP de serveurs, CIDR ou noms d'hôte routés hors du tunnel. Séparés par des virgules.",
    edit_maxAttempts: "Tentatives de reconnexion",
    edit_delays: "Délais de reconnexion (s)",
    edit_delaysHint: "Secondes entre les tentatives, séparées par des virgules.",
    edit_save: "Enregistrer",
    edit_reset: "Valeurs par défaut",
    edit_cancel: "Annuler",
    edit_reconnectNote: "Le tunnel se reconnectera automatiquement pour appliquer les changements.",
    edit_saved: "✓ Paramètres enregistrés",
    edit_resetDone: "✓ Paramètres rétablis à leurs valeurs d'origine",
    edit_resetConfirm: "Rétablir tous les paramètres tels qu'ils étaient à l'import du profil ? Les modifications locales seront perdues.",
    edit_resetTitle: "Réinitialiser les paramètres",

    confirm_continue: "Continuer",
    confirm_reset: "Réinitialiser",
    profiles_remove: "Supprimer",
    profiles_removeTitle: "Supprimer le profil",
    profiles_removeConfirm: "Supprimer le profil « {name} » ? Vous devrez réimporter son .owcfg.",

    error_title: "Impossible de se connecter",
    error_genericBody: "Il peut s'agir d'une empreinte TLS différente, d'un endpoint injoignable ou d'un échec de WireGuard.",
    error_checkLog: "Consultez le journal d'activité pour le détail complet.",
    error_importNew: "Importer un nouveau .owcfg",
    retry: "Réessayer",
    bootError: "Impossible de démarrer l'interface.",
    integrity_av: "Votre antivirus semble avoir supprimé une partie d'OutWarp.",
    integrity_av_cta: "C'est un faux positif connu (HackTool:Win32/Wstunnel). Réinstallez et ajoutez une exclusion pour le dossier OutWarp.",
    integrity_generic: "Certains fichiers du programme sont manquants. Réinstallez OutWarp pour les réparer.",
    integrity_details: "Afficher les détails",
    integrity_hide: "Masquer les détails",
    integrity_help: "Comment corriger",
    integrity_dismiss: "Ignorer",
    hostile_headline: "Réseau hostile détecté",
    hostile_auto_on: "OutWarp a activé automatiquement le contournement DNS (1.1.1.1) car le réseau semble intercepter les requêtes.",
    hostile_auto_off: "Le réseau semble intercepter les requêtes. Passez le hostile-mode sur 'on' dans le profil si le tunnel continue d'échouer.",
    hostile_dismiss: "Ignorer",
    reconnectAttempt: "Tentative",
    importReading: "Lecture du fichier…",
    errorUnknown: "Erreur inconnue",
    techDetails: "Détails techniques",
    clientIp: "IP du client",

    logs_empty: "— aucune entrée —",
    logs_level: "Niveau",
    logs_levelAll: "Tous",
    logs_exported: "✓ Journal exporté",
    logs_jumpBottom: "Aller en bas",

    step_resolve: "Résolution de l'endpoint",
    step_tls: "Vérification du certificat",
    step_wg: "Activation de l'interface WireGuard",
    step_ws: "Ouverture du tunnel WebSocket",
    step_done: "Terminé",

    profile: "Profil",
    home_ribbon: "Tout votre trafic sort chiffré via votre propre serveur.",
    home_clickToConnect: "Cliquez sur le cadran pour vous connecter.",
    home_details: "Cette connexion",
    home_server: "Serveur",
    home_security: "Sécurité",
    home_killSwitch: "Kill switch",
    home_expires: "Expire",
    home_never: "Jamais",
    home_route: "Route",
    home_exit: "IP de sortie",
    home_change: "Changer",
    home_switch: "Changer de profil",
    home_manage: "Gérer les profils",
    sec_pin: "Certificat épinglé sur votre serveur",
    sec_ca: "Certificat vérifié par une CA",
    ks_on: "Activé : rien ne sort sans le tunnel",
    ks_off: "Désactivé",
    route_direct: "Directe",
    route_hostile: "Directe, DNS public",
    route_proxy: "Via le proxy HTTP",
    route_port: "Port alternatif {port}",
    err_hint_unreachable: "Le serveur est injoignable. Vérifiez qu'il est démarré et que son port est ouvert sur le pare-feu ou le routeur.",
    err_hint_cert: "Le certificat du serveur n'est pas celui de votre profil. S'il a été réinstallé ou renouvelé, demandez un nouveau .owcfg ; sinon, quelque chose sur ce réseau intercepte peut-être la connexion.",
    err_hint_token: "Le jeton de ce profil a expiré ou a déjà été utilisé. Demandez un nouveau .owcfg à l'administrateur.",
    err_hint_blocked: "Votre antivirus ou Windows a bloqué wstunnel. Restaurez-le depuis la quarantaine de Microsoft Defender ou réinstallez OutWarp.",
    err_hint_network: "Ce réseau ne laisse passer le tunnel par aucune des routes essayées. Essayez un autre réseau ; un serveur avec un domaine et un vrai certificat passe plus souvent.",
    err_hint_expired: "Ce profil a expiré. Demandez-en un nouveau à l'administrateur.",
    err_details: "Détails techniques",
    err_viewLog: "Voir le journal",
    throughput_title: "Trafic",
    throughput_window: "derniers {n}",
    throughput_empty: "En attente du premier échantillon…",
    notConnected: "Aucun tunnel actif",
  },
};

window.STR = STR;

// ── formatters ─────────────────────────────────────────────────────
const fmtBps = (n) => {
  if (!n) return "0 B/s";
  if (n < 1024) return `${n} B/s`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB/s`;
  return `${(n / 1024 / 1024).toFixed(1)} MB/s`;
};
const fmtBytes = (n) => {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
};
// `now` (ms) is injectable for tests; the UI never passes it.
const fmtAgo = (epoch, lang, now = Date.now()) => {
  if (!epoch) return "—";
  const d = Math.max(0, Math.floor(now / 1000 - epoch));
  try {
    const rtf = new Intl.RelativeTimeFormat(lang || "es", { numeric: "auto" });
    if (d < 60) return rtf.format(-d, "second");
    if (d < 3600) return rtf.format(-Math.floor(d / 60), "minute");
    return rtf.format(-Math.floor(d / 3600), "hour");
  } catch (_) {
    if (d < 60) return `${d}s`;
    if (d < 3600) return `${Math.floor(d / 60)}m`;
    return `${Math.floor(d / 3600)}h`;
  }
};

const fmtDuration = (sec) => {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
};
// What kind of failure a connection error is, from the (English) message the
// tunnel raised, so the error screen can say what to do in plain words. The
// raw message stays available under "Technical details".
const classifyError = (msg) => {
  const m = String(msg || "").toLowerCase();
  if (!m) return "generic";
  if (/defender|smart app control|quarantin|wstunnel binary not found|could not be run|was removed/.test(m)) return "blocked";
  if (/expired profile|profile has expired|profile expired/.test(m)) return "expired";
  if (/token|enrol/.test(m)) return "token";
  if (/fingerprint mismatch|certificate verify|certificate_verify|pin mismatch|spki/.test(m)) return "cert";
  if (/cannot reach|connection refused|unreachable|timed out|no route to host|name or service not known|getaddrinfo/.test(m)) return "unreachable";
  if (/all connection strategies failed|no wireguard handshake|no traffic through tunnel/.test(m)) return "network";
  return "generic";
};

// The fallback-ladder rung that carried the connection, as the user reads it.
const routeLabel = (route, T) => {
  if (!route || !route.id) return "";
  if (route.id === "direct") return T.route_direct;
  if (route.id === "direct-hostile") return T.route_hostile;
  if (route.id === "direct-proxy") return T.route_proxy;
  if (/^port-\d+$/.test(route.id)) return T.route_port.replace("{port}", String(route.port || route.id.slice(5)));
  return route.label || route.id;
};

window.OWfmt = { fmtBps, fmtBytes, fmtAgo, fmtDuration, classifyError, routeLabel };

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
