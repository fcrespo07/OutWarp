// OutWarp client — runtime app shell.
//
// Renders a real, interactive UI on top of the design tokens shipped in
// var-a.jsx / var-b.jsx. We do NOT use the static VarA/VarB previews
// directly because their sidebars/buttons are non-interactive design
// mockups; the chassis here mirrors them visually (same sidebar layout,
// same hero card, same stat strip) but every control is wired to
// window.pywebview.api.
//
// VarB (developer mode) is selected by settings.advanced = true.

const { useState, useEffect, useCallback, useRef } = React;

// ── pywebview bridge helpers ───────────────────────────────────────
function waitForBridge() {
  return new Promise((resolve) => {
    const tick = () => {
      if (window.pywebview && window.pywebview.api) return resolve(window.pywebview.api);
      setTimeout(tick, 30);
    };
    tick();
  });
}

function useBridgeEvent(name, handler) {
  useEffect(() => {
    const wrapped = (e) => handler(e.detail);
    window.addEventListener(`outwarp:${name}`, wrapped);
    return () => window.removeEventListener(`outwarp:${name}`, wrapped);
  }, [handler]);
}

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
const fmtDuration = (sec) => {
  sec = Math.max(0, Math.floor(sec));
  const h = Math.floor(sec / 3600), m = Math.floor((sec % 3600) / 60), s = sec % 60;
  return `${String(h).padStart(2, "0")}:${String(m).padStart(2, "0")}:${String(s).padStart(2, "0")}`;
};

// ── App root ───────────────────────────────────────────────────────
function App() {
  const [api, setApi] = useState(null);
  const [status, setStatus] = useState("empty");
  const [profiles, setProfiles] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [stats, setStats] = useState({ tx_bps: 0, rx_bps: 0, tx_total: 0, rx_total: 0, session_start: 0, last_handshake: 0 });
  const [logs, setLogs] = useState([]);
  const [settings, setSettings] = useState({ language: "es", theme: "auto", advanced: false, start_at_boot: false, auto_reconnect: true, kill_switch: false });
  const [screen, setScreen] = useState("home");
  const [busyMsg, setBusyMsg] = useState("");

  // bootstrap
  useEffect(() => {
    waitForBridge().then(async (a) => {
      setApi(a);
      const [s, ps, st, lg] = await Promise.all([
        a.get_status(), a.list_profiles(), a.get_settings(), a.get_logs(0),
      ]);
      setStatus(s.status);
      setActiveId(s.active_profile_id);
      setStats(s.stats);
      setProfiles(ps);
      setSettings(st);
      setLogs(lg);
    });
  }, []);

  useBridgeEvent("status", useCallback((d) => {
    setStatus(d.status);
    setActiveId(d.active_profile_id);
    if (d.status !== "connecting" && d.status !== "error") setBusyMsg("");
  }, []));
  useBridgeEvent("stats",   useCallback((d) => setStats(d), []));
  useBridgeEvent("log",     useCallback((e) => setLogs((l) => [...l.slice(-1999), e]), []));
  useBridgeEvent("settings", useCallback((d) => setSettings(d), []));

  // resolve theme
  const isDark = settings.theme === "dark" ||
    (settings.theme === "auto" && window.matchMedia?.("(prefers-color-scheme: dark)")?.matches);
  const theme = isDark ? "dark" : "light";

  // language strings
  const lang = settings.language === "en" ? "en" : "es";
  const T = window.STR[lang];

  const active = profiles[0] || null;

  const onConnect = async () => {
    if (!api) return;
    setBusyMsg(T.connecting);
    const r = await api.connect(activeId);
    if (!r.ok) setBusyMsg(r.error || T.error);
  };
  const onDisconnect = async () => api?.disconnect();
  const onReconnect = async () => api?.reconnect();

  const onImport = async (text) => {
    if (!api) return { ok: false };
    return api.import_profile(text);
  };
  const onRemoveProfile = async () => {
    if (!api || !activeId) return;
    if (!window.confirm("¿Eliminar el perfil activo? Tendrás que importar de nuevo el .owcfg.")) return;
    await api.remove_profile(activeId);
    const ps = await api.list_profiles();
    setProfiles(ps);
    setActiveId(null);
  };

  const onSetting = (k, v) => api?.set_settings({ [k]: v });

  return (
    <div data-theme={theme} style={{ display: "grid", gridTemplateColumns: "232px 1fr", height: "100%", background: "var(--bg)", color: "var(--text)" }}>
      <Sidebar
        T={T}
        screen={screen}
        onScreen={setScreen}
        status={status}
        profileName={active?.name}
        advanced={!!settings.advanced}
      />
      <main style={{ overflow: "auto", padding: "28px 36px 36px", minWidth: 0 }} className="ws-scroll">
        {screen === "home" && (
          <Home
            T={T}
            status={status}
            active={active}
            stats={stats}
            advanced={!!settings.advanced}
            busyMsg={busyMsg}
            onConnect={onConnect}
            onDisconnect={onDisconnect}
            onReconnect={onReconnect}
            onImport={() => setScreen("import")}
          />
        )}
        {screen === "import"  && <Import T={T} api={api} active={active} onImported={(p) => { setActiveId(p.id); setProfiles([p]); setScreen("home"); }} onRemove={onRemoveProfile}/>}
        {screen === "logs"     && <Logs T={T} logs={logs} api={api} onClear={() => setLogs([])}/>}
        {screen === "settings" && <Settings T={T} settings={settings} onSetting={onSetting}/>}
      </main>
    </div>
  );
}

// ── Sidebar (clickable, mirrors VarA/VarB design) ──────────────────
const Sidebar = ({ T, screen, onScreen, status, profileName, advanced }) => {
  const items = [
    ["home",     T.nav_home,     "M3 11 L12 3 L21 11 M5 10 V20 H19 V10"],
    ["import",   T.nav_profiles, "M12 8 m-4 0 a4 4 0 1 0 8 0 a4 4 0 1 0 -8 0 M4 21 C4 16 8 14 12 14 C16 14 20 16 20 21"],
    ["logs",     T.nav_logs,     "M5 4 H19 V20 H5 Z M8 8 H16 M8 12 H16 M8 16 H13"],
    ["settings", T.nav_settings, "M12 9 a3 3 0 1 1 0 6 a3 3 0 1 1 0 -6 M12 2 V4 M12 20 V22 M2 12 H4 M20 12 H22"],
  ];
  const tone =
    status === "connected" ? "good" :
    status === "connecting" ? "warn" :
    status === "error" ? "bad" : "neutral";
  const label =
    status === "connected" ? T.connected :
    status === "connecting" ? T.connecting :
    status === "error" ? T.error :
    status === "empty" ? T.notConnected : T.disconnected;

  return (
    <aside style={{
      background: "var(--bg-2)",
      borderRight: advanced ? "1px solid var(--line-strong)" : "1px solid var(--line)",
      display: "flex", flexDirection: "column", padding: "22px 14px",
    }}>
      <div style={{ padding: "0 8px 22px" }}>
        <window.WSWordmark size={16} color="var(--text)" accent="var(--brand)"/>
      </div>

      {advanced && (
        <div style={{ padding: "0 8px 14px", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase" }}>
          dev mode
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: advanced ? 0 : 2 }}>
        {items.map(([id, lbl, d], i) => {
          const active = id === screen;
          return (
            <button key={id} onClick={() => onScreen(id)} style={{
              all: "unset",
              display: advanced ? "grid" : "flex",
              gridTemplateColumns: advanced ? "auto 1fr auto" : undefined,
              alignItems: "center", gap: 10,
              padding: "9px 10px",
              borderLeft: advanced ? (active ? "2px solid var(--brand)" : "2px solid transparent") : undefined,
              borderRadius: advanced ? 0 : 8,
              fontSize: 13, fontWeight: active ? 600 : 500,
              background: active ? "var(--chip)" : "transparent",
              color: active ? "var(--text)" : "var(--text-2)",
              cursor: "pointer",
            }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={active ? "var(--brand)" : "var(--text-3)"} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d={d}/>
              </svg>
              <span>{lbl}</span>
              {advanced && <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)" }}>0{i+1}</span>}
            </button>
          );
        })}
      </div>

      <div style={{
        marginTop: "auto",
        padding: 12,
        borderRadius: advanced ? 0 : 12,
        background: "var(--bg-sunk)",
        border: "1px solid " + (advanced ? "var(--line-strong)" : "var(--line)"),
      }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.profile}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <window.StatusDot tone={tone} pulse={status === "connecting" || status === "connected"}/>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{profileName || "—"}</div>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2, fontFamily: "var(--font-mono)" }}>{label}</div>
      </div>
    </aside>
  );
};

// ── Home ───────────────────────────────────────────────────────────
const Home = ({ T, status, active, stats, advanced, busyMsg, onConnect, onDisconnect, onReconnect, onImport }) => {
  if (status === "empty" || !active) {
    return <EmptyHome T={T} onImport={onImport}/>;
  }
  if (status === "connected") return <ConnectedHome T={T} active={active} stats={stats} advanced={advanced} onDisconnect={onDisconnect}/>;
  if (status === "connecting") return <ConnectingHome T={T} active={active} busyMsg={busyMsg}/>;
  if (status === "error") return <ErrorHome T={T} active={active} onReconnect={onReconnect} onImport={onImport}/>;
  return <DisconnectedHome T={T} active={active} onConnect={onConnect}/>;
};

const EmptyHome = ({ T, onImport }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 720 }}>
    <Header title={T.welcomeTitle} sub={T.welcomeSub}/>
    <section style={{ background: "var(--bg-2)", border: "1.5px dashed var(--line-strong)", borderRadius: 16, padding: 36, textAlign: "center" }}>
      <div style={{ width: 56, height: 56, borderRadius: 14, background: "color-mix(in srgb, var(--brand) 12%, transparent)", color: "var(--brand)", display: "grid", placeItems: "center", margin: "0 auto" }}>
        <svg width="26" height="26" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16 V4 M6 10 L12 4 L18 10"/><path d="M4 20 H20"/></svg>
      </div>
      <div style={{ fontSize: 16, fontWeight: 600, marginTop: 12 }}>{T.importDrop}</div>
      <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{T.importHint}</div>
      <div style={{ marginTop: 18 }}>
        <window.Btn kind="primary" size="md" onClick={onImport}>{T.importFile}</window.Btn>
      </div>
    </section>
  </div>
);

const DisconnectedHome = ({ T, active, onConnect }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <Header title={T.nav_home} sub={T.home_ribbon}/>
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28, position: "relative", overflow: "hidden" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 8 }}>{T.disconnected}</div>
          <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.1 }}>{active.name}</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>{active.endpoint}</div>
          <div style={{ marginTop: 18 }}>
            <window.Btn kind="primary" size="lg" onClick={onConnect}>{T.connect}</window.Btn>
          </div>
        </div>
        <Dial/>
      </div>
    </section>
  </div>
);

const ConnectingHome = ({ T, active, busyMsg }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <Header title={T.nav_home} sub={T.home_ribbon}/>
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28 }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
            <window.StatusDot tone="warn"/>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-warn)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.connecting}</span>
          </div>
          <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.handshake}</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>{active.endpoint}</div>
          {busyMsg && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 8, fontFamily: "var(--font-mono)" }}>{busyMsg}</div>}
        </div>
        <Dial pulsing/>
      </div>
    </section>
  </div>
);

const ConnectedHome = ({ T, active, stats, advanced, onDisconnect }) => {
  const sessionSec = stats.session_start ? (Date.now() / 1000 - stats.session_start) : 0;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Header title={T.nav_home} sub={T.home_ribbon}/>

      <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28, position: "relative", overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
              <window.StatusDot tone="good"/>
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-2)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.connected}</span>
            </div>
            <div style={{ fontSize: 28, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.05 }}>{active.name}</div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>{active.endpoint}</div>
            <div style={{ marginTop: 18 }}>
              <window.Btn kind="solid" size="md" onClick={onDisconnect}>{T.disconnect}</window.Btn>
            </div>
          </div>
          <Dial active/>
        </div>
      </section>

      <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
        <Stat label={T.download} value={fmtBps(stats.rx_bps)} sub={`↓ ${fmtBytes(stats.rx_total)} total`}/>
        <Stat label={T.upload}    value={fmtBps(stats.tx_bps)} sub={`↑ ${fmtBytes(stats.tx_total)} total`}/>
        <Stat label={T.sessionTime} value={fmtDuration(sessionSec)}/>
      </div>

      {advanced && (
        <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18, fontFamily: "var(--font-mono)", fontSize: 12 }}>
          <div style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 10, fontFamily: "var(--font-sans)", fontWeight: 600 }}>Detalles técnicos</div>
          <KV k={T.endpoint} v={active.endpoint}/>
          <KV k={T.fingerprint} v={active.fingerprint || "—"}/>
          <KV k="Client IP" v={active.client_address || "—"}/>
          <KV k="DNS" v={(active.dns || []).join(", ") || "—"} last/>
        </section>
      )}
    </div>
  );
};

const ErrorHome = ({ T, active, onReconnect, onImport }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <Header title={T.nav_home} sub={T.home_ribbon}/>
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <window.StatusDot tone="bad"/>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-bad)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.error}</span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.02em" }}>No se pudo conectar</div>
      <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6, maxWidth: 540 }}>
        Revisa los logs para más detalles. Puede ser un error de huella TLS, un endpoint inalcanzable o un fallo de WireGuard.
      </div>
      <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
        <window.Btn kind="primary" size="md" onClick={onReconnect}>Reintentar</window.Btn>
        <window.Btn kind="ghost" size="md" onClick={onImport}>Importar nuevo .owcfg</window.Btn>
      </div>
    </section>
  </div>
);

const Header = ({ title, sub }) => (
  <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
    <div>
      <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{title}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
    </div>
  </header>
);

const Stat = ({ label, value, sub }) => (
  <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 12, padding: 14 }}>
    <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 600, marginTop: 6, fontFamily: "var(--font-mono)" }}>{value}</div>
    {sub && <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>{sub}</div>}
  </div>
);

const KV = ({ k, v, last }) => (
  <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, padding: "8px 0", borderBottom: last ? "none" : "1px dashed var(--line)" }}>
    <div style={{ color: "var(--text-3)" }}>{k}</div>
    <div style={{ color: "var(--text)", wordBreak: "break-all" }}>{v}</div>
  </div>
);

const Dial = ({ active, pulsing }) => (
  <div style={{ position: "relative", width: 180, height: 180 }}>
    <svg width="180" height="180" viewBox="0 0 200 200">
      <defs>
        <linearGradient id="dial-grad" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--brand)"/>
          <stop offset="1" stopColor="var(--brand-2)"/>
        </linearGradient>
      </defs>
      <circle cx="100" cy="100" r="86" stroke="var(--line-strong)" strokeWidth="1" fill="none"/>
      <circle cx="100" cy="100" r="72" stroke="var(--line)" strokeWidth="1" fill="none" strokeDasharray="2 4"/>
      {active && <circle cx="100" cy="100" r="86" stroke="url(#dial-grad)" strokeWidth="3" fill="none"
        strokeDasharray={`${2*Math.PI*86*0.78} ${2*Math.PI*86}`} transform="rotate(-90 100 100)" strokeLinecap="round"/>}
    </svg>
    <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
      <div style={{
        width: 100, height: 100, borderRadius: 999,
        background: active ? "linear-gradient(135deg, var(--brand), var(--brand-2))" : "var(--bg-sunk)",
        border: active ? "none" : "1px solid var(--line-strong)",
        display: "grid", placeItems: "center", color: active ? "#fff" : "var(--text-2)",
        boxShadow: active ? "0 12px 28px -10px color-mix(in srgb, var(--brand) 55%, transparent)" : "none",
        animation: pulsing ? "ws-pulse 1.6s ease-out infinite" : "none",
      }}>
        <window.WSLogoMark size={40} color={active ? "#fff" : "var(--text-2)"} accent={active ? "rgba(255,255,255,.6)" : "var(--text-3)"}/>
      </div>
    </div>
  </div>
);

// ── Import / Profiles ──────────────────────────────────────────────
const Import = ({ T, api, active, onImported, onRemove }) => {
  const fileRef = useRef(null);
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");

  const handleFile = async (file) => {
    if (!file) return;
    setError("");
    setMsg("Leyendo archivo…");
    try {
      const text = await file.text();
      const r = await api.import_profile(text);
      if (r.ok) {
        setMsg(`✓ ${r.profile.name}`);
        setError("");
        onImported(r.profile);
      } else {
        setMsg("");
        setError(r.error || "Error desconocido");
      }
    } catch (e) {
      setError(String(e));
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 720 }}>
      <Header title={T.welcomeTitle} sub={T.welcomeSub}/>
      {active && (
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 12, padding: 16, display: "flex", justifyContent: "space-between", alignItems: "center" }}>
          <div>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{active.name}</div>
            <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2, fontFamily: "var(--font-mono)" }}>{active.endpoint}</div>
          </div>
          <window.Btn kind="danger" size="sm" onClick={onRemove}>Eliminar</window.Btn>
        </div>
      )}
      <div style={{
        border: "1.5px dashed var(--line-strong)", borderRadius: 14, padding: 32,
        background: "var(--bg-2)", textAlign: "center",
      }}
        onDragOver={(e) => e.preventDefault()}
        onDrop={(e) => { e.preventDefault(); handleFile(e.dataTransfer.files[0]); }}
      >
        <input ref={fileRef} type="file" accept=".owcfg,.warpcfg,.json,.txt" hidden onChange={(e) => handleFile(e.target.files[0])}/>
        <div style={{ width: 48, height: 48, borderRadius: 12, background: "color-mix(in srgb, var(--brand) 12%, transparent)", color: "var(--brand)", display: "grid", placeItems: "center", margin: "0 auto" }}>
          <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round"><path d="M12 16 V4 M6 10 L12 4 L18 10"/><path d="M4 20 H20"/></svg>
        </div>
        <div style={{ fontSize: 15, fontWeight: 600, marginTop: 10 }}>{T.importDrop}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{T.importHint}</div>
        <div style={{ marginTop: 16 }}>
          <window.Btn kind="primary" size="md" onClick={() => fileRef.current?.click()}>{T.importFile}</window.Btn>
        </div>
        {msg && <div style={{ marginTop: 14, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-2)" }}>{msg}</div>}
        {error && <div style={{ marginTop: 14, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-bad)" }}>{error}</div>}
      </div>
    </div>
  );
};

// ── Logs ───────────────────────────────────────────────────────────
const Logs = ({ T, logs, api, onClear }) => {
  const ref = useRef(null);
  const [filter, setFilter] = useState("");
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [logs.length]);

  const filtered = filter ? logs.filter((l) => l.msg.toLowerCase().includes(filter.toLowerCase())) : logs;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.logs_title}</div>
          <div style={{ fontSize: 12, color: "var(--text-3)" }}>outwarp-client · live</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={T.logs_filter} style={{
            height: 30, padding: "0 12px", borderRadius: 8, border: "1px solid var(--line-strong)",
            background: "var(--bg-2)", color: "var(--text)", fontSize: 12, width: 220, outline: "none",
          }}/>
          <window.Btn kind="ghost" size="sm" onClick={onClear}>{T.logs_clear}</window.Btn>
        </div>
      </header>
      <div ref={ref} style={{
        background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 12,
        fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.65,
        padding: 14, color: "var(--text-2)", overflow: "auto", flex: 1, minHeight: 360,
      }} className="ws-scroll">
        {filtered.map((l) => {
          const ts = new Date(l.ts * 1000).toISOString().slice(11, 19);
          const c = l.level === "error" ? "var(--brand-bad)" : l.level === "warn" ? "var(--brand-warn)" : l.level === "debug" ? "var(--text-3)" : "var(--brand-2)";
          return (
            <div key={l.seq} style={{ display: "grid", gridTemplateColumns: "84px 60px 1fr", gap: 10 }}>
              <span style={{ color: "var(--text-3)" }}>{ts}</span>
              <span style={{ color: c, textTransform: "uppercase" }}>{l.level}</span>
              <span style={{ color: "var(--text)", wordBreak: "break-all" }}>{l.msg}</span>
            </div>
          );
        })}
        {filtered.length === 0 && <div style={{ opacity: .5 }}>— sin entradas —</div>}
      </div>
    </section>
  );
};

// ── Settings ───────────────────────────────────────────────────────
const Settings = ({ T, settings, onSetting }) => {
  const Row = ({ title, sub, control }) => (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 16, alignItems: "center", padding: "14px 0", borderBottom: "1px solid var(--line)" }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{title}</div>
        {sub && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
      </div>
      <div>{control}</div>
    </div>
  );
  const Select = ({ value, onChange, options }) => (
    <select value={value} onChange={(e) => onChange(e.target.value)} style={{
      height: 30, padding: "0 10px", borderRadius: 8, border: "1px solid var(--line-strong)",
      background: "var(--bg)", color: "var(--text)", fontSize: 13, fontFamily: "var(--font-sans)",
    }}>{options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}</select>
  );
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 720 }}>
      <Header title={T.nav_settings} sub="outwarp-client · v0.0.1"/>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: "0 18px" }}>
        <Row title={T.set_language} control={<Select value={settings.language} onChange={(v) => onSetting("language", v)} options={[["es", "Español"], ["en", "English"]]}/>}/>
        <Row title={T.set_theme} control={<Select value={settings.theme} onChange={(v) => onSetting("theme", v)} options={[["auto", T.set_themeAuto], ["light", T.set_themeLight], ["dark", T.set_themeDark]]}/>}/>
        <Row title={T.set_advanced} sub={T.set_advancedSub} control={<window.Toggle on={!!settings.advanced} onChange={(v) => onSetting("advanced", v)}/>}/>
        <Row title={T.set_autoconnect} sub={T.set_autoconnectSub} control={<window.Toggle on={!!settings.auto_reconnect} onChange={(v) => onSetting("auto_reconnect", v)}/>}/>
        <Row title={T.set_startup} control={<window.Toggle on={!!settings.start_at_boot} onChange={(v) => onSetting("start_at_boot", v)}/>}/>
        <Row title={T.set_killSwitch} sub={T.set_killSwitchSub} control={<window.Toggle on={!!settings.kill_switch} onChange={(v) => onSetting("kill_switch", v)}/>}/>
      </div>
    </section>
  );
};

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
