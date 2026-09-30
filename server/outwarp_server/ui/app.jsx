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

// Per-client sparkline: how many samples (one a second) the visible ring holds, plus how
// many *additional* window-max samples window.DSfmt.makeBoundedPeak below
// remembers past that — see its own comment (dash-data.jsx) for why this
// pairing matters.
const SPARK_RING_LEN = 24;
const SPARK_PEAK_MEMORY = 10;

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
  // "unknown" = enrolled but not on the interface right now; "pending" (no
  // public key yet, token unredeemed) and "disabled" (taken off the interface
  // by an admin) are states of their own — there is no peer to be online or
  // offline.
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
    spark: derived.spark || new Array(SPARK_RING_LEN).fill(0),
    sparkTx: derived.sparkTx || new Array(SPARK_RING_LEN).fill(0),
  };
}

// Samples closer together than this are dropped: the same counters read
// twice a few ms apart (an SSE event and a fetch, or a burst a proxy held back)
// give a rate of 0 or a huge spike, which the chart drew as a dip or a peak.
const MIN_SAMPLE_GAP_S = 0.5;
// Samples the live chart keeps: one a second, the 60 s it shows plus a few
// that have slid off its left edge (its curve needs them to reach the edge).
const LIVE_POINTS = 66;
const MAX_LOGS = 400;

function useLiveData() {
  const [, force] = useState(0);
  const ref = useRef(null);
  if (!ref.current) {
    ref.current = {
      status: null,
      clients: [],
      totals: { online: 0, idle: 0, offline: 0, pending: 0, disabled: 0, rxBps: 0, txBps: 0 },
      // Total throughput as {t (server seconds), rx, tx}; the chart places
      // points by their own time, so late or bunched delivery cannot bend it.
      samples: [],
      logs: [],
      lastSeq: 0,
      lastEventAt: 0,
      uptimeSec: null,
    };
  }
  // Keyed by client name: pending clients all share an empty public_key and
  // used to collapse into one row of rate/sparkline state.
  const prevRef = useRef({});       // name -> {rx, tx, t, rxBps, txBps}
  const sparkRef = useRef({});      // name -> number[] (rx)
  const sparkTxRef = useRef({});    // name -> number[] (tx)
  const peakRef = useRef({});       // name -> boundedPeak() instance (sparkline scale)

  const onClients = useCallback((rows) => {
    const s = ref.current;
    const browserNow = Date.now() / 1000;
    let totRx = 0, totTx = 0, online = 0, idle = 0, offline = 0, pending = 0, disabled = 0;
    let newest = 0;
    const adapted = (rows || []).map((row) => {
      // The server stamps each sample with the time it actually took it
      // (sampled_at): rates divide by the real gap between two readings.
      const { state: rate, advanced } = window.DSfmt.nextRate(
        prevRef.current[row.name], row, browserNow, MIN_SAMPLE_GAP_S);
      prevRef.current[row.name] = rate;
      const { rxBps, txBps } = rate;
      if (advanced) {
        newest = Math.max(newest, rate.t);
        const ring = (sparkRef.current[row.name] || new Array(SPARK_RING_LEN).fill(0)).slice(1);
        ring.push(rxBps);
        sparkRef.current[row.name] = ring;
        const ringTx = (sparkTxRef.current[row.name] || new Array(SPARK_RING_LEN).fill(0)).slice(1);
        ringTx.push(txBps);
        sparkTxRef.current[row.name] = ringTx;
      }
      const ring = sparkRef.current[row.name] || new Array(SPARK_RING_LEN).fill(0);
      const ringTx = sparkTxRef.current[row.name] || new Array(SPARK_RING_LEN).fill(0);
      const state = row.status === "unknown" ? "offline" : row.status;
      if (state === "online") { online++; totRx += rxBps; totTx += txBps; }
      else if (state === "idle") idle++;
      else if (state === "pending") pending++;
      else if (state === "disabled") disabled++;
      else offline++;
      // Normalize to 0..1 for the sparkline — see makeBoundedPeak's comment
      // (dash-data.jsx) for why a bounded peak-hold, not a raw or decaying one.
      const boundedPeak = peakRef.current[row.name] || window.DSfmt.makeBoundedPeak(SPARK_PEAK_MEMORY);
      peakRef.current[row.name] = boundedPeak;
      const peak = advanced ? boundedPeak(Math.max(...ring, 1)) : Math.max(...ring, 1);
      const normSpark = ring.map((v) => Math.min(1, v / peak));
      // The upload sparkline scales on its own: it used to be the download
      // one drawn backwards.
      const peakTx = Math.max(...ringTx, 1);
      const normSparkTx = ringTx.map((v) => v / peakTx);
      return adaptClient(row, { rxBps, txBps, spark: normSpark, sparkTx: normSparkTx });
    });
    s.clients = adapted;
    s.totals = { online, idle, offline, pending, disabled, rxBps: totRx, txBps: totTx };
    if (newest) {
      // Placed by the moment the server took it, on this browser's clock, so a
      // late or bunched delivery cannot bend the curve (see AreaChart).
      const clock = window.DSfmt.nextClockOffset(s.clockRecent || [], browserNow - newest);
      s.clockRecent = clock.recent;
      const last = s.samples.length ? s.samples[s.samples.length - 1].t : null;
      const t = window.DSfmt.sampleTime(newest, clock.offset, last);
      s.samples = s.samples.concat({ t, rx: totRx, tx: totTx }).slice(-LIVE_POINTS);
    }
    force((x) => x + 1);
  }, []);

  // Merge, never replace: an event may carry fewer fields than get_status().
  const onStatus = useCallback((st) => {
    ref.current.status = { ...(ref.current.status || {}), ...(st || {}) };
    force((x) => x + 1);
  }, []);

  // Entries arrive from events and from fetches (start-up, resync, fallback
  // polling); each carries the server's sequence number, so none shows twice.
  const addLogs = useCallback((entries) => {
    const s = ref.current;
    const next = window.DSfmt.mergeLogs(s.logs, s.lastSeq, entries, MAX_LOGS);
    if (next.logs === s.logs) return;
    s.logs = next.logs;
    s.lastSeq = next.lastSeq;
    force((x) => x + 1);
  }, []);
  const onLog = useCallback((entry) => addLogs([entry]), [addLogs]);

  useEffect(() => {
    const seen = (fn) => (d) => { ref.current.lastEventAt = Date.now(); fn(d); };
    const offC = OW.on("clients", seen(onClients));
    const offS = OW.on("status", seen(onStatus));
    const offL = OW.on("log", onLog);
    return () => { offC(); offS(); offL(); };
  }, [onClients, onStatus, onLog]);

  // What the live events would have delivered, fetched instead: after a
  // reconnect, and while events are not arriving (a proxy that buffers or
  // drops the event stream must not freeze the page).
  const poll = useCallback(async () => {
    const [stt, cls, lgs] = await Promise.all([
      OW.call("get_status"), OW.call("list_clients"), OW.call("get_logs", ref.current.lastSeq),
    ]);
    if (stt) onStatus(stt);
    if (cls) onClients(cls);
    addLogs(lgs);
  }, [onStatus, onClients, addLogs]);

  return { live: ref.current, onStatus, onClients, addLogs, poll };
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
      <button key={id} className="nav-item" data-active={route === id} aria-current={route === id ? "page" : undefined} onClick={() => go(id)}>
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

const ThemeBtn = ({ theme, onToggle, label }) => (
  <button className="ow-iconbtn" onClick={onToggle} aria-label={label}>
    {theme === "dark" ? window.Icons.sun(18) : window.Icons.moon(18)}
  </button>
);

function App() {
  const [booted, setBooted] = useState(false);
  // Web: null until we know whether the browser still holds a valid session
  // cookie. It used to start at false, so every reload showed the login
  // screen and "keep this session" seemed to do nothing (B-039).
  const [authed, setAuthed] = useState(OW.mode === "pywebview" ? true : null);
  const [settings, setSettings] = useState({ language: "auto", theme: "auto" });
  const [appInfo, setAppInfo] = useState({ version: "" });
  const [route, setRoute] = useState(() => localStorage.getItem("ow_dash_route") || "dashboard");
  const [selected, setSelected] = useState(null);
  const [addOpen, setAddOpen] = useState(false);
  const [navOpen, setNavOpen] = useState(false);
  const [, setViewTick] = useState(0);
  const [isMobile, setIsMobile] = useState(() => window.matchMedia("(max-width: 860px)").matches);

  const lang = window.OWi18n.resolveLang(settings.language, window.OWi18n.systemLangs());
  const theme = resolveTheme(settings.theme);
  const T = window.OWi18n.stringsFor(window.DS_STR, lang);
  useEffect(() => {
    // Lets the browser pick the right CJK glyph variants for the language.
    document.documentElement.lang = lang;
    if (!OW.isWeb) OW.call("set_ui_language", lang).catch(() => {});
  }, [lang]);
  const ui = window.styleTokens("pulida");

  const { live, onStatus, onClients, addLogs, poll } = useLiveData();
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
      onStatus(stt);
      onClients(cls);
      addLogs(lgs);
      live.lastEventAt = Date.now();
      setBooted(true);
      OW.call("notify_ready");
    } catch (e) {
      // In web mode a 401 means we need to log in first; the gate handles it.
      setBooted(true);
    }
  }, [onStatus, onClients, addLogs]);

  useEffect(() => {
    if (authed !== null) return;
    OW.call("get_app_info")
      .then((info) => { if (info) setAppInfo(info); setAuthed(true); })
      .catch(() => setAuthed(false));
  }, [authed]);
  useEffect(() => { if (authed) bootstrap(); }, [authed, bootstrap]);
  // The live stream dropped and came back (transport.js): fetch what it missed.
  useEffect(() => OW.on("resync", () => { if (authed) poll().catch(() => {}); }), [authed, poll]);
  // Fallback: no live event for a while (a proxy buffering the stream, a
  // renderer that stopped taking them) → fetch every second until they resume.
  useEffect(() => {
    if (!authed || !booted) return undefined;
    let busy = false;
    const id = setInterval(async () => {
      if (busy || document.hidden || Date.now() - live.lastEventAt < 3000) return;
      busy = true;
      try { await poll(); } catch (_e) { /* next tick */ } finally { busy = false; }
    }, 1000);
    return () => clearInterval(id);
  }, [authed, booted, poll, live]);

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
    T, lang, langPref: settings.language || "auto", live, server, go, appInfo,
    call: (m, ...a) => OW.call(m, ...a),
    refreshView: () => setViewTick((x) => x + 1),
    openClient: (name) => setSelected(name),
    openAdd: () => setAddOpen(true),
    confirm, signOut, setLang, theme, toggleTheme,
    isWeb: OW.isWeb,
    refresh: async () => {
      const [stt, cls] = await Promise.all([OW.call("get_status"), OW.call("list_clients")]);
      onStatus(stt); onClients(cls);
    },
  };

  // ── login gate (web only) ────────────────────────────────────────────────
  if (authed === null) return null;
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
              <ThemeBtn theme={theme} onToggle={toggleTheme} label={T.a11y_theme} />
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
            <button className="ow-iconbtn" onClick={() => setNavOpen(true)} aria-label={T.a11y_menu}>{window.Icons.menu(20)}</button>
            <window.WSWordmark size={15} color="var(--text)" accent="var(--brand)" />
            <div style={{ marginLeft: "auto", display: "flex", alignItems: "center", gap: 6 }}>
              <StatusChip T={T} live={live} />
              <ThemeBtn theme={theme} onToggle={toggleTheme} label={T.a11y_theme} />
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
                <button className="ow-iconbtn" onClick={() => setNavOpen(false)} aria-label={T.a11y_close}>{window.Icons.x(18)}</button>
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
