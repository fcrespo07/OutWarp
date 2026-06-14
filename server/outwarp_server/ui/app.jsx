// OutWarp Server dashboard — runtime shell.
//
// Unified UI for both transports (see transport.js):
//   • pywebview desktop GUI  → already authenticated (local admin), native frame.
//   • remote web panel       → token login gate, served over HTTPS.
//
// All domain data comes from the real Api via OW.call + outwarp:* events. The
// mock useLiveData / DS_* fixtures from the design prototype are gone; the
// live throughput, sparklines and per-client rates here are derived from the
// 2 s poll deltas the server already emits.

const { useState, useEffect, useRef, useCallback } = React;
const OW = window.OW;

// ── confirm hook (pairs with window.ConfirmDialog from dash-extras) ────────
function useConfirm(T) {
  const [pending, setPending] = useState(null);
  const confirm = useCallback((opts) => new Promise((res) => setPending({ opts, res })), []);
  const node = pending ? (
    <window.ConfirmDialog T={T} opts={pending.opts} onResult={(v) => { pending.res(v); setPending(null); }} />
  ) : null;
  return [confirm, node];
}

const ipOnly = (addr) => (addr ? String(addr).split("/")[0] : "—");

// Map a raw list_clients() row to the shape the screens expect, carrying the
// derived live rate + sparkline computed in useLiveData.
function adaptClient(row, derived) {
  const state = row.status === "unknown" ? "offline" : row.status;
  return {
    name: row.name,
    ip: ipOnly(row.address),
    state,
    hsSec: row.last_handshake_seconds_ago,
    rxTotal: row.rx_bytes || 0,
    txTotal: row.tx_bytes || 0,
    endpoint: row.endpoint || "—",
    pub: row.public_key,
    device: "laptop",
    expiresAt: row.expires_at || "",
    rxBps: derived.rxBps || 0,
    txBps: derived.txBps || 0,
    spark: derived.spark || new Array(24).fill(0),
  };
}

function useLiveData() {
  const [, force] = useState(0);
  const ref = useRef(null);
  if (!ref.current) {
    ref.current = {
      status: null,
      clients: [],
      totals: { online: 0, idle: 0, offline: 0, rxBps: 0, txBps: 0 },
      rxSeries: new Array(60).fill(0),
      txSeries: new Array(60).fill(0),
      logs: [],
      uptimeSec: null,
    };
  }
  const prevRef = useRef({});       // public_key -> {rx, tx, t}
  const sparkRef = useRef({});      // public_key -> number[]

  const onClients = useCallback((rows) => {
    const s = ref.current;
    const now = Date.now() / 1000;
    let totRx = 0, totTx = 0, online = 0, idle = 0, offline = 0;
    const adapted = (rows || []).map((row) => {
      const prev = prevRef.current[row.public_key];
      let rxBps = 0, txBps = 0;
      if (prev && now > prev.t) {
        const dt = now - prev.t;
        rxBps = Math.max(0, (row.rx_bytes - prev.rx) / dt);
        txBps = Math.max(0, (row.tx_bytes - prev.tx) / dt);
      }
      prevRef.current[row.public_key] = { rx: row.rx_bytes || 0, tx: row.tx_bytes || 0, t: now };
      const ring = (sparkRef.current[row.public_key] || new Array(24).fill(0)).slice(1);
      ring.push(rxBps);
      sparkRef.current[row.public_key] = ring;
      const state = row.status === "unknown" ? "offline" : row.status;
      if (state === "online") { online++; totRx += rxBps; totTx += txBps; }
      else if (state === "idle") idle++;
      else offline++;
      // normalize spark to 0..1 for the sparkline
      const peak = Math.max(...ring, 1);
      const normSpark = ring.map((v) => v / peak);
      return adaptClient(row, { rxBps, txBps, spark: normSpark });
    });
    s.clients = adapted;
    s.totals = { online, idle, offline, rxBps: totRx, txBps: totTx };
    s.rxSeries = s.rxSeries.slice(1).concat(totRx);
    s.txSeries = s.txSeries.slice(1).concat(totTx);
    force((x) => x + 1);
  }, []);

  const onStatus = useCallback((st) => {
    ref.current.status = st;
    force((x) => x + 1);
  }, []);

  const onLog = useCallback((entry) => {
    const s = ref.current;
    const t = window.DSfmt.nowClock();
    s.logs = s.logs.concat({
      seq: entry.seq, t,
      svc: "", lvl: entry.level || "info", msg: entry.msg,
    });
    if (s.logs.length > 400) s.logs = s.logs.slice(-400);
    force((x) => x + 1);
  }, []);

  useEffect(() => {
    const offC = OW.on("clients", onClients);
    const offS = OW.on("status", onStatus);
    const offL = OW.on("log", onLog);
    return () => { offC(); offS(); offL(); };
  }, [onClients, onStatus, onLog]);

  return { live: ref.current, seedLogs: (entries) => {
    ref.current.logs = (entries || []).map((e) => ({
      seq: e.seq, t: window.DSfmt.nowClock(), svc: "", lvl: e.level || "info", msg: e.msg,
    }));
    force((x) => x + 1);
  }, seedClients: onClients };
}

function resolveTheme(theme) {
  if (theme === "dark" || theme === "light") return theme;
  return window.matchMedia && window.matchMedia("(prefers-color-scheme: dark)").matches ? "dark" : "light";
}

const NAV = [
  ["dashboard", "nav_dashboard", "dashboard"],
  ["clients", "nav_clients", "clients"],
  ["traffic", "nav_traffic", "traffic"],
  ["service", "nav_service", "service"],
  ["logs", "nav_logs", "logs"],
  ["doctor", "nav_doctor", "doctor"],
  ["settings", "nav_settings", "settings"],
];
const SCREENS = {
  dashboard: () => window.ScreenDashboard, clients: () => window.ScreenClients,
  traffic: () => window.ScreenTraffic, service: () => window.ScreenService,
  logs: () => window.ScreenLogs, doctor: () => window.ScreenDoctor,
  settings: () => window.ScreenSettings,
};

const NavList = ({ T, route, go }) => (
  <>
    {NAV.map(([id, key, icon]) => (
      <button key={id} className="nav-item" data-active={route === id} onClick={() => go(id)}>
        <span className="nav-ic">{window.Icons[icon](18)}</span>
        {T[key]}
      </button>
    ))}
  </>
);

const StatusChip = ({ T, live }) => {
  const running = live.status && live.status.status === "running";
  return (
    <div style={{ display: "flex", alignItems: "center", gap: 8, fontFamily: "var(--font-mono)" }}>
      <window.Dot tone={running ? "good" : "neutral"} pulse={running} />
      <span style={{ fontSize: 12, fontWeight: 600, color: "var(--text)", whiteSpace: "nowrap" }}>
        {running ? T.running : T.stopped}
      </span>
    </div>
  );
};

const ThemeBtn = ({ theme, onToggle }) => (
  <button className="ow-iconbtn" onClick={onToggle} aria-label="theme">
    {theme === "dark" ? window.Icons.sun(18) : window.Icons.moon(18)}
  </button>
);

function App() {
  const [booted, setBooted] = useState(false);
  const [authed, setAuthed] = useState(OW.mode === "pywebview");
  const [settings, setSettings] = useState({ language: "es", theme: "auto" });
  const [appInfo, setAppInfo] = useState({ version: "" });
  const [route, setRoute] = useState(() => localStorage.getItem("ow_dash_route") || "dashboard");
  const [selected, setSelected] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia("(max-width: 860px)").matches);

  const lang = settings.language === "en" ? "en" : "es";
  const theme = resolveTheme(settings.theme);
  const T = window.DS_STR[lang];
  const ui = window.styleTokens("pulida");

  const { live, seedLogs, seedClients } = useLiveData();
  const [confirm, confirmNode] = useConfirm(T);

  const server = (() => {
    const st = live.status || {};
    return {
      host: st.endpoint || "—",
      publicIp: st.endpoint || "—",
      endpoint: st.endpoint ? `${st.endpoint}:${st.port || 443}` : "—",
      subnet: st.subnet || "—",
      wgListen: st.wg_listen_port ? `${st.wg_listen_port}/udp` : "—",
      fingerprint: st.cert_fingerprint_sha256 || "—",
      validUntil: st.tls_valid_until || "—",
      daysLeft: st.tls_days_left != null ? st.tls_days_left : "—",
    };
  })();

  // ── bootstrap ───────────────────────────────────────────────────────────
  const bootstrap = useCallback(async () => {
    try {
      const [stt, cls, lgs, set, info] = await Promise.all([
        OW.call("get_status"),
        OW.call("list_clients"),
        OW.call("get_logs", 0),
        OW.call("get_settings"),
        OW.call("get_app_info"),
      ]);
      if (set) setSettings((s) => ({ ...s, ...set }));
      if (info) setAppInfo(info);
      live.status = stt;
      seedClients(cls);
      seedLogs(lgs);
      setBooted(true);
      OW.call("notify_ready");
    } catch (e) {
      // In web mode a 401 means we need to log in first; the gate handles it.
      setBooted(true);
    }
  }, [live, seedClients, seedLogs]);

  useEffect(() => { if (authed) bootstrap(); }, [authed, bootstrap]);

  useEffect(() => {
    const off = OW.on("settings", (s) => setSettings((cur) => ({ ...cur, ...s })));
    const offU = OW.on("unauthorized", () => setAuthed(false));
    return () => { off(); offU(); };
  }, []);

  useEffect(() => {
    const mq = window.matchMedia("(max-width: 860px)");
    const fn = () => { setIsMobile(mq.matches); if (!mq.matches) setNavOpen(false); };
    mq.addEventListener("change", fn);
    return () => mq.removeEventListener("change", fn);
  }, []);
  useEffect(() => { localStorage.setItem("ow_dash_route", route); }, [route]);

  const go = (id) => { setRoute(id); setNavOpen(false); };
  const toggleTheme = () => {
    const next = theme === "dark" ? "light" : "dark";
    setSettings((s) => ({ ...s, theme: next }));
    OW.call("set_settings", { theme: next });
  };
  const setLang = (l) => { setSettings((s) => ({ ...s, language: l })); OW.call("set_settings", { language: l }); };
  const signOut = async () => { await OW.logout(); setAuthed(false); };

  const C = {
    T, lang, live, server, go, appInfo,
    call: (m, ...a) => OW.call(m, ...a),
    openClient: (name) => setSelected(name),
    openAdd: () => setAddOpen(true),
    confirm, signOut, setLang, theme, toggleTheme,
    isWeb: OW.isWeb,
    refresh: async () => {
      const [stt, cls] = await Promise.all([OW.call("get_status"), OW.call("list_clients")]);
      live.status = stt; seedClients(cls);
    },
  };

  // ── login gate (web only) ────────────────────────────────────────────────
  if (!authed) {
    return (
      <window.OWUIContext.Provider value={ui}>
        <window.LoginScreen T={T} theme={theme} appInfo={appInfo}
          onLogin={async ({ token, remember }) => {
            const r = await OW.login(token, remember);
            if (r.ok) { setAuthed(true); return { ok: true }; }
            return { ok: false, error: r.error || (r.status === 429 ? T.login_locked : T.login_bad) };
          }} />
      </window.OWUIContext.Provider>
    );
  }

  const selClient = selected ? live.clients.find((c) => c.name === selected) : null;
  const Screen = (SCREENS[route] || SCREENS.dashboard)() || window.ScreenDashboard;

  return (
    <window.OWUIContext.Provider value={ui}>
      <div className="app" data-theme={theme} data-nav={isMobile ? "mobile" : "sidebar"} data-style="pulida">
        {!isMobile && (
          <aside className="rail">
            <div className="rail-brand">
              <window.WSWordmark size={16} color="var(--text)" accent="var(--brand)" />
              <ThemeBtn theme={theme} onToggle={toggleTheme} />
            </div>
            <div style={{ padding: "0 8px 16px", fontSize: 10.5, color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase", fontWeight: 600, fontFamily: "var(--font-mono)" }}>{T.serverAdmin}</div>
            <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
              <NavList T={T} route={route} go={go} />
            </div>
            <div className="rail-status">
              <div style={{ fontSize: 10, fontWeight: 600, color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase", fontFamily: "var(--font-mono)", marginBottom: 7, wordBreak: "break-all" }}>{server.host}</div>
              <StatusChip T={T} live={live} />
            </div>
          </aside>
        )}

        {isMobile && (
          <header className="m-appbar">
            <button className="ow-iconbtn" onClick={() => setNavOpen(true)} aria-label="menu">{window.Icons.menu(20)}</button>
            <window.WSWordmark size={15} color="var(--text)" accent="var(--brand)" />
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
              <StatusChip T={T} live={live} />
              <ThemeBtn theme={theme} onToggle={toggleTheme} />
            </div>
          </header>
        )}

        <main className="main">
          <div className="main-inner">
            {!booted
              ? <div style={{ padding: 60, textAlign: "center", color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>…</div>
              : <Screen C={C} />}
          </div>
        </main>

        {isMobile && navOpen && (
          <>
            <div className="m-scrim" onClick={() => setNavOpen(false)} />
            <aside className="m-drawer">
              <div className="rail-brand">
                <window.WSWordmark size={16} color="var(--text)" accent="var(--brand)" />
                <button className="ow-iconbtn" onClick={() => setNavOpen(false)}>{window.Icons.x(18)}</button>
              </div>
              <div style={{ padding: "0 8px 16px", fontSize: 10.5, color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase", fontWeight: 600, fontFamily: "var(--font-mono)" }}>{T.serverAdmin}</div>
              <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
                <NavList T={T} route={route} go={go} />
              </div>
            </aside>
          </>
        )}

        {selClient && <window.ClientDrawer T={T} client={selClient} lang={lang} C={C}
          onClose={() => setSelected(null)} confirm={confirm} />}
        {addOpen && <window.AddClientModal T={T} C={C} onClose={() => setAddOpen(false)} />}
        {confirmNode}
      </div>
    </window.OWUIContext.Provider>
  );
}

ReactDOM.createRoot(document.getElementById("root")).render(<App />);
