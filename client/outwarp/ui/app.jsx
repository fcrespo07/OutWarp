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
const fmtAgo = (epoch, lang) => {
  if (!epoch) return "—";
  const d = Math.max(0, Math.floor(Date.now() / 1000 - epoch));
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
const fmtClock = (epoch) => {
  const d = new Date(epoch * 1000);  // local time, not UTC
  return [d.getHours(), d.getMinutes(), d.getSeconds()]
    .map((n) => String(n).padStart(2, "0")).join(":");
};

// ── Confirm modal ──────────────────────────────────────────────────
// Replaces window.confirm so destructive actions match the app's design.
// useConfirmState returns [confirm, dialogElement]: render the element inside
// the themed tree, then `await confirm({...})` resolves to a boolean.
const ConfirmDialog = ({ title, message, confirmLabel, cancelLabel, danger, onResult }) => {
  useEffect(() => {
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
  const [pending, setPending] = useState(null);
  const confirm = useCallback((opts) => new Promise((resolve) => {
    setPending({ ...opts, resolve });
  }), []);
  const dialog = pending
    ? <ConfirmDialog {...pending} onResult={(val) => { pending.resolve(val); setPending(null); }}/>
    : null;
  return [confirm, dialog];
}

// ── App root ───────────────────────────────────────────────────────
function App() {
  const [api, setApi] = useState(null);
  const [status, setStatus] = useState("empty");
  const [profiles, setProfiles] = useState([]);
  const [activeId, setActiveId] = useState(null);
  const [stats, setStats] = useState({ tx_bps: 0, rx_bps: 0, tx_total: 0, rx_total: 0, session_start: 0, last_handshake: 0 });
  const [logs, setLogs] = useState([]);
  const [settings, setSettings] = useState({ language: "es", theme: "auto", advanced: false, allow_tls_intercept: false });
  const [screen, setScreen] = useState("home");
  const [busyMsg, setBusyMsg] = useState("");
  const [connError, setConnError] = useState("");
  const [attemptInfo, setAttemptInfo] = useState({ attempt: 0, max_attempts: 0 });
  // Connect-progress hint emitted by the manager: "" between attempts,
  // "resolve"|"tls"|"wg"|"ws"|"done" while connecting. Drives the stepper.
  const [phase, setPhase] = useState("");
  const [ready, setReady] = useState(false);
  // Non-empty when bootstrap itself threw — the splash shows a retry instead of
  // spinning forever on a half-initialised bridge.
  const [bootError, setBootError] = useState("");
  // Frameless window chrome: caps tells us whether the host supports native
  // drag/edge-resize (Windows); maximized drives the max/restore glyph.
  const [caps, setCaps] = useState({ native_drag_resize: false, maximized: false });
  const [maximized, setMaximized] = useState(false);
  const [confirm, confirmDialog] = useConfirmState();
  // Rolling window of (rx_bps, tx_bps) samples for the Home throughput chart.
  // Fed from the outwarp:stats heartbeat (1 Hz) so the chart and the stat
  // cards never disagree. Capped at 60 samples ≈ 60 s of history.
  const [history, setHistory] = useState([]);

  // bootstrap
  useEffect(() => {
    waitForBridge().then(async (a) => {
      setApi(a);
      try {
        const [s, ps, st, lg, wc] = await Promise.all([
          a.get_status(), a.list_profiles(), a.get_settings(), a.get_logs(0),
          a.get_window_caps(),
        ]);
        setStatus(s.status);
        setActiveId(s.active_profile_id);
        setStats(s.stats);
        setConnError(s.error || "");
        setAttemptInfo({ attempt: s.attempt || 0, max_attempts: s.max_attempts || 0 });
        setPhase(s.phase || "");
        setProfiles(ps);
        setSettings(st);
        setLogs(lg);
        if (wc) { setCaps(wc); setMaximized(!!wc.maximized); }
        setReady(true);
      } catch (e) {
        try { a?.report_ui_error?.(`bootstrap failed: ${(e && (e.stack || e.message)) || e}`); } catch (_) {}
        setBootError(String((e && e.message) || e));
      }
    });
  }, []);

  useBridgeEvent("status", useCallback((d) => {
    setStatus(d.status);
    setActiveId(d.active_profile_id);
    setConnError(d.error || "");
    setAttemptInfo({ attempt: d.attempt || 0, max_attempts: d.max_attempts || 0 });
    setPhase(d.phase || "");
    if (d.status === "connected" || d.status === "disconnected" || d.status === "empty") setBusyMsg("");
  }, []));
  useBridgeEvent("stats", useCallback((d) => {
    setStats(d);
    setHistory((h) => {
      const next = h.concat({ rx: d.rx_bps || 0, tx: d.tx_bps || 0, lat: d.latency_ms || 0 });
      return next.length > 60 ? next.slice(-60) : next;
    });
  }, []));
  useBridgeEvent("log",     useCallback((e) => setLogs((l) => [...l.slice(-1999), e]), []));
  useBridgeEvent("settings", useCallback((d) => setSettings(d), []));
  useBridgeEvent("window",   useCallback((d) => setMaximized(!!d.maximized), []));

  // Reset the throughput history whenever the tunnel isn't actively
  // transferring — leaving stale samples on screen after a disconnect would
  // be lying about what's happening now.
  useEffect(() => {
    if (status !== "connected") setHistory([]);
  }, [status]);

  // JS-side poll — same reasoning as the server: evaluate_js from a Python
  // background thread can be silently dropped on some platform/backend
  // combinations. Polling from JS guarantees the connection state and stats
  // stay live regardless of threading or window-focus throttling.
  useEffect(() => {
    if (!api) return;
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      try {
        const s = await api.get_status();
        setStatus(s.status);
        setActiveId(s.active_profile_id);
        setStats(s.stats);
        setConnError(s.error || "");
        setAttemptInfo({ attempt: s.attempt || 0, max_attempts: s.max_attempts || 0 });
        setPhase(s.phase || "");
      } catch (_) {}
      if (alive) setTimeout(tick, 1000);
    };
    setTimeout(tick, 1000);
    return () => { alive = false; };
  }, [api]);

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
    const ok = await confirm({
      title: T.profiles_removeTitle,
      message: T.profiles_removeConfirm,
      confirmLabel: T.profiles_remove,
      cancelLabel: T.cancel,
      danger: true,
    });
    if (!ok) return;
    await api.remove_profile(activeId);
    const ps = await api.list_profiles();
    setProfiles(ps);
    setActiveId(null);
  };
  const refreshProfiles = async () => {
    if (!api) return;
    const ps = await api.list_profiles();
    setProfiles(ps);
  };

  // onSetting returns the bridge result so children can show an inline error
  // when a side-effecting setting (kill_switch / start_at_boot) fails. The
  // persisted value is rolled back server-side and re-broadcast via
  // outwarp:settings, so the toggle's visual state recovers on its own.
  const onSetting = async (k, v) => {
    if (!api) return { ok: false, error: "no bridge" };
    return api.set_settings({ [k]: v });
  };

  // Hold the first paint until the bridge has answered — otherwise the app
  // briefly renders the "empty / import" screen even when a profile exists.
  // The title bar renders in both states so the window stays draggable and
  // closable while the bridge is still warming up.
  if (!ready) {
    return (
      <div data-theme={theme} className="ow-root">
        <TitleBar T={T} api={api} caps={caps} maximized={maximized}/>
        <div style={{ flex: 1, display: "grid", placeItems: "center", minHeight: 0, padding: 24 }}>
          {bootError ? (
            <div style={{ maxWidth: 460, textAlign: "center" }}>
              <div style={{ fontSize: 15, fontWeight: 600 }}>{T.bootError}</div>
              <pre style={{ marginTop: 12, maxHeight: 140, overflow: "auto", textAlign: "left", background: "var(--bg-sunk)", border: "1px solid var(--line)", borderRadius: 8, padding: 12, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)", whiteSpace: "pre-wrap" }}>{bootError}</pre>
              <window.Btn kind="primary" size="md" onClick={() => window.location.reload()} style={{ marginTop: 14 }}>{T.retry}</window.Btn>
            </div>
          ) : (
            <window.WSLogoMark size={40} color="var(--text-3)" accent="var(--brand)"/>
          )}
        </div>
        {caps.native_drag_resize && !maximized && <ResizeHandles api={api}/>}
      </div>
    );
  }

  return (
    <div data-theme={theme} className="ow-root">
      <TitleBar T={T} api={api} caps={caps} maximized={maximized}/>
      <div className="ow-body">
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
              lang={lang}
              status={status}
              active={active}
              stats={stats}
              history={history}
              advanced={!!settings.advanced}
              busyMsg={busyMsg}
              connError={connError}
              attemptInfo={attemptInfo}
              phase={phase}
              onConnect={onConnect}
              onDisconnect={onDisconnect}
              onReconnect={onReconnect}
              onImport={() => setScreen("import")}
              onLogs={() => setScreen("logs")}
            />
          )}
          {screen === "import"  && <Import T={T} api={api} active={active} confirm={confirm} onImported={(p) => { setActiveId(p.id); setProfiles([p]); setScreen("home"); }} onRemove={onRemoveProfile} onProfilesChanged={refreshProfiles}/>}
          {screen === "logs"     && <Logs T={T} logs={logs} api={api} onClear={() => setLogs([])}/>}
          {screen === "settings" && <Settings T={T} settings={settings} onSetting={onSetting}/>}
          {screen === "about"    && <About T={T} api={api} settings={settings}/>}
        </main>
      </div>
      {caps.native_drag_resize && !maximized && <ResizeHandles api={api}/>}
      {confirmDialog}
    </div>
  );
}

// ── Custom title bar (frameless window chrome) ─────────────────────
// The native OS title bar is hidden (frameless=True); this draws one in the
// app's palette. Dragging + double-click-maximize + edge-resize are native on
// Windows (api.window_start_move / window_start_resize → WM_NCLBUTTONDOWN);
// elsewhere the drag region uses pywebview's built-in "pywebview-drag-region".
const TitleBar = ({ T, api, caps, maximized }) => {
  const native = !!caps.native_drag_resize;

  const onDragMouseDown = (e) => {
    if (e.button !== 0 || !native || !api) return;
    // Let clicks on the window buttons through (they're outside this element,
    // but guard anyway) and hand the press to the OS move loop.
    api.window_start_move();
  };
  // Native caption already handles double-click; only wire it for the
  // drag-region fallback so non-Windows still gets double-click-to-maximize.
  const onDragDoubleClick = () => { if (!native && api) api.window_toggle_maximize(); };

  return (
    <div className="ow-titlebar">
      <div
        className={native ? "ow-titlebar-drag" : "ow-titlebar-drag pywebview-drag-region"}
        onMouseDown={onDragMouseDown}
        onDoubleClick={onDragDoubleClick}
      >
        <window.WSWordmark size={13} color="var(--text)" accent="var(--brand)"/>
      </div>
      <div className="ow-titlebar-controls">
        <button className="ow-winbtn" title={T.win_minimize} aria-label={T.win_minimize}
          onClick={() => api && api.window_minimize()}>
          <svg width="11" height="11" viewBox="0 0 12 12"><line x1="2" y1="6.5" x2="10" y2="6.5" stroke="currentColor" strokeWidth="1.1"/></svg>
        </button>
        <button className="ow-winbtn" title={maximized ? T.win_restore : T.win_maximize} aria-label={maximized ? T.win_restore : T.win_maximize}
          onClick={() => api && api.window_toggle_maximize()}>
          {maximized ? (
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.1">
              <rect x="2" y="3.5" width="6" height="6"/><path d="M4 3.5 V2 H10 V8 H8.5"/>
            </svg>
          ) : (
            <svg width="11" height="11" viewBox="0 0 12 12" fill="none" stroke="currentColor" strokeWidth="1.1">
              <rect x="2.2" y="2.2" width="7.6" height="7.6"/>
            </svg>
          )}
        </button>
        <button className="ow-winbtn close" title={T.win_close} aria-label={T.win_close}
          onClick={() => api && api.window_close()}>
          <svg width="11" height="11" viewBox="0 0 12 12" stroke="currentColor" strokeWidth="1.1"><line x1="2.5" y1="2.5" x2="9.5" y2="9.5"/><line x1="9.5" y1="2.5" x2="2.5" y2="9.5"/></svg>
        </button>
      </div>
    </div>
  );
};

// Invisible native edge/corner grips for the frameless window (Windows only).
// mousedown hands the matching hit-test code to the OS resize loop.
const RESIZE_EDGES = ["t", "b", "l", "r", "tl", "tr", "bl", "br"];
const ResizeHandles = ({ api }) => (
  <>
    {RESIZE_EDGES.map((edge) => (
      <div key={edge} className={`ow-resize-h ${edge}`}
        onMouseDown={(e) => { if (e.button === 0 && api) { e.preventDefault(); api.window_start_resize(edge); } }}/>
    ))}
  </>
);

// ── Sidebar (clickable, mirrors VarA/VarB design) ──────────────────
const Sidebar = ({ T, screen, onScreen, status, profileName, advanced }) => {
  const items = [
    ["home",     T.nav_home,     "M3 11 L12 3 L21 11 M5 10 V20 H19 V10"],
    ["import",   T.nav_profiles, "M12 8 m-4 0 a4 4 0 1 0 8 0 a4 4 0 1 0 -8 0 M4 21 C4 16 8 14 12 14 C16 14 20 16 20 21"],
    ["logs",     T.nav_logs,     "M5 4 H19 V20 H5 Z M8 8 H16 M8 12 H16 M8 16 H13"],
    ["settings", T.nav_settings, "M12 9 a3 3 0 1 1 0 6 a3 3 0 1 1 0 -6 M12 2 V4 M12 20 V22 M2 12 H4 M20 12 H22"],
    ["about",    T.nav_about,    "M3 12 a9 9 0 1 1 18 0 a9 9 0 1 1 -18 0 M12 8 V13 M12 16 V16.01"],
  ];
  const tone =
    status === "connected" ? "good" :
    (status === "connecting" || status === "reconnecting") ? "warn" :
    status === "error" ? "bad" : "neutral";
  const label =
    status === "connected" ? T.connected :
    status === "connecting" ? T.connecting :
    status === "reconnecting" ? T.reconnecting :
    status === "error" ? T.error :
    status === "empty" ? T.notConnected : T.disconnected;
  const pulse = status === "connecting" || status === "reconnecting" || status === "connected";

  return (
    <aside className="ow-sidebar" style={{
      background: "var(--bg-2)",
      borderRight: advanced ? "1px solid var(--line-strong)" : "1px solid var(--line)",
      display: "flex", flexDirection: "column", padding: "22px 14px",
    }}>
      {/* Wordmark moved to the window title bar (frameless chrome). */}
      {advanced && (
        <div style={{ padding: "0 8px 14px", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase" }}>
          dev mode
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: advanced ? 0 : 2 }}>
        {items.map(([id, lbl, d], i) => {
          const active = id === screen;
          return (
            <button key={id} onClick={() => onScreen(id)}
              className={`ow-nav${active ? " is-active" : ""}`}
              style={{
              appearance: "none", border: "none", font: "inherit", textAlign: "left", width: "100%",
              display: advanced ? "grid" : "flex",
              gridTemplateColumns: advanced ? "auto 1fr auto" : undefined,
              alignItems: "center", gap: 10,
              padding: "9px 10px",
              borderLeft: advanced ? (active ? "2px solid var(--brand)" : "2px solid transparent") : undefined,
              borderRadius: advanced ? 0 : 8,
              fontSize: 13, fontWeight: active ? 600 : 500,
            }}>
              <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke={active ? "var(--brand)" : "var(--text-3)"} strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
                <path d={d}/>
              </svg>
              <span className="ow-nav-label">{lbl}</span>
              {advanced && <span className="ow-nav-num" style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)" }}>0{i+1}</span>}
            </button>
          );
        })}
      </div>

      <div className="ow-sidebar-foot" style={{
        marginTop: "auto",
        padding: 12,
        borderRadius: advanced ? 0 : 12,
        background: "var(--bg-sunk)",
        border: "1px solid " + (advanced ? "var(--line-strong)" : "var(--line)"),
      }}>
        <div className="ow-sidebar-foot-text" style={{ fontSize: 11, fontWeight: 500, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.profile}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <window.StatusDot tone={tone} pulse={pulse}/>
          <div className="ow-sidebar-foot-text" style={{ fontSize: 13, fontWeight: 600 }}>{profileName || "—"}</div>
        </div>
        <div className="ow-sidebar-foot-text" style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2, fontFamily: "var(--font-mono)" }}>{label}</div>
      </div>
    </aside>
  );
};

// ── Home ───────────────────────────────────────────────────────────
const Home = ({ T, lang, status, active, stats, history, advanced, busyMsg, connError, attemptInfo, phase, onConnect, onDisconnect, onReconnect, onImport, onLogs }) => {
  if (status === "empty" || !active) {
    return <EmptyHome T={T} onImport={onImport}/>;
  }
  if (status === "connected") return <ConnectedHome T={T} lang={lang} active={active} stats={stats} history={history} advanced={advanced} onDisconnect={onDisconnect} onLogs={onLogs}/>;
  if (status === "connecting" || status === "reconnecting") {
    return <ConnectingHome T={T} active={active} busyMsg={busyMsg} reconnecting={status === "reconnecting"} attemptInfo={attemptInfo} phase={phase}/>;
  }
  if (status === "error") return <ErrorHome T={T} active={active} connError={connError} onReconnect={onReconnect} onImport={onImport}/>;
  return <DisconnectedHome T={T} active={active} onConnect={onConnect}/>;
};

const EmptyHome = ({ T, onImport }) => (
  <div className="ow-screen" style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 720 }}>
    <Header title={T.welcomeTitle} sub={T.welcomeSub}/>
    <section style={{ background: "var(--bg-2)", border: "1.5px dashed var(--line-strong)", borderRadius: "var(--radius-lg)", padding: 36, textAlign: "center" }}>
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
  <div className="ow-screen" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <Header title={T.nav_home} sub={T.home_ribbon}/>
    <section className="ow-hero">
      <div className="ow-hero-grid">
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 8 }}>{T.disconnected}</div>
          <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.1 }}>{active.name}</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>{active.endpoint}</div>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 14 }}>{T.home_clickToConnect}</div>
        </div>
        <Dial status="disconnected" onClick={onConnect} label={T.connect}/>
      </div>
      <BgGlow/>
    </section>

    <div className="ow-info-grid">
      <InfoCard icon={<IconShield/>} title={T.home_secure_title}  body={T.home_secure_body}/>
      <InfoCard icon={<IconLock/>}   title={T.home_pinned_title}  body={T.home_pinned_body}/>
      <InfoCard icon={<IconRoute/>}  title={T.home_routing_title} body={T.home_routing_body}/>
    </div>
  </div>
);

// Order matches outwarp.tunnel.Tunnel.connect(): probe TCP, verify TLS pin,
// install the WG service, launch wstunnel, settle on CONNECTED. There is no
// separate "route" step — bypass IPs are excluded from WG AllowedIPs at
// config-build time.
const CONNECT_STEPS = [
  ["resolve", "step_resolve"],
  ["tls",     "step_tls"],
  ["wg",      "step_wg"],
  ["ws",      "step_ws"],
  ["done",    "step_done"],
];

const ConnectingHome = ({ T, active, busyMsg, reconnecting, attemptInfo, phase }) => {
  const showAttempt = reconnecting && attemptInfo && attemptInfo.attempt > 0;
  // -1 when phase is empty (between attempts) so every step renders pending.
  const currentIdx = phase
    ? Math.max(0, CONNECT_STEPS.findIndex(([k]) => k === phase))
    : -1;
  return (
    <div className="ow-screen" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Header title={T.nav_home} sub={T.home_ribbon}/>
      <section className="ow-hero">
        <div className="ow-hero-grid">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <window.StatusDot tone="warn"/>
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-warn)", letterSpacing: ".06em", textTransform: "uppercase" }}>
                {reconnecting ? T.reconnecting : T.connecting}
              </span>
            </div>
            <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.02em" }}>{active.name}</div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>{active.endpoint}</div>
            {showAttempt && (
              <div style={{ fontSize: 12, color: "var(--brand-warn)", marginTop: 8, fontFamily: "var(--font-mono)" }}>
                {T.reconnectAttempt} {attemptInfo.attempt}/{attemptInfo.max_attempts}
              </div>
            )}
          </div>
          <Dial status={reconnecting ? "reconnecting" : "connecting"} label={reconnecting ? T.reconnecting : T.connecting}/>
        </div>
        <Stepper T={T} currentIdx={currentIdx}/>
        {busyMsg && (
          <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 14, fontFamily: "var(--font-mono)" }}>
            {busyMsg}
          </div>
        )}
      </section>
    </div>
  );
};

const Stepper = ({ T, currentIdx }) => (
  <ol style={{
    listStyle: "none", padding: 0, margin: "24px 0 0",
    display: "flex", flexDirection: "column", gap: 10,
  }}>
    {CONNECT_STEPS.map(([key, strKey], i) => {
      const state = i < currentIdx ? "done" : i === currentIdx ? "active" : "pending";
      return (
        <li key={key} style={{
          display: "grid", gridTemplateColumns: "20px 1fr",
          gap: 12, alignItems: "center",
        }}>
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
      <circle cx="12" cy="12" r="10" fill="color-mix(in srgb, var(--brand-2) 14%, transparent)" stroke="none"/>
      <path d="M7 12 L11 16 L17 9"/>
    </svg>
  );
  if (state === "active") return (
    <span style={{ position: "relative", display: "inline-block", width: 20, height: 20 }}>
      <span style={{
        position: "absolute", inset: 0, borderRadius: 999,
        border: "2px solid var(--brand-warn)", borderTopColor: "transparent",
        animation: "ws-spin 0.9s linear infinite",
      }}/>
    </span>
  );
  return (
    <svg width="20" height="20" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="9" fill="none" stroke="var(--line-strong)" strokeWidth="1.5"/>
    </svg>
  );
};

const ConnectedHome = ({ T, lang, active, stats, history, advanced, onDisconnect, onLogs }) => {
  const sessionSec = stats.session_start ? (Date.now() / 1000 - stats.session_start) : 0;
  // Headline the live exit IP once it's known; fall back to the profile name
  // while the exit-IP probe is still resolving.
  const heroTitle = stats.exit_ip || active.name;
  const heroSub = [stats.exit_location, `${T.profile} ${active.name}`].filter(Boolean).join(" · ");
  // Latency trend (was mistakenly fed download bytes, on the latency card).
  const spark = (history || []).slice(-12).map((s) => s.lat || 0);
  const lastHs = stats.last_handshake ? fmtAgo(stats.last_handshake, lang) : "—";
  return (
    <div className="ow-screen" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Header title={T.nav_home} sub={T.home_ribbon}/>

      <section className="ow-hero">
        <div className="ow-hero-grid">
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
              <window.StatusDot tone="good"/>
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-2)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.connected}</span>
            </div>
            <div style={{ fontSize: 36, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.05 }}>{heroTitle}</div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>{heroSub}</div>
            <div className="ow-hero-actions" style={{ marginTop: 18, display: "flex", gap: 8 }}>
              <window.Btn kind="ghost" size="md" icon={<IconLogs size={14}/>} onClick={onLogs}>{T.nav_logs}</window.Btn>
            </div>
          </div>
          <Dial status="connected" onClick={onDisconnect} label={T.disconnect}/>
        </div>
        <BgGlow/>
      </section>

      <div className="ow-stats-grid">
        <Stat label={T.latency}     value={stats.latency_ms ? `${stats.latency_ms} ms` : "—"} trend={spark.length >= 2 ? <Spark data={spark} good/> : null}/>
        <Stat label={T.download}    value={fmtBps(stats.rx_bps)} sub={`↓ ${fmtBytes(stats.rx_total)} total`}/>
        <Stat label={T.upload}      value={fmtBps(stats.tx_bps)} sub={`↑ ${fmtBytes(stats.tx_total)} total`}/>
        <Stat label={T.sessionTime} value={fmtDuration(sessionSec)} sub={`${T.lastHandshake} · ${lastHs}`}/>
      </div>

      <ThroughputChart T={T} history={history || []}/>

      {advanced && (
        <section className="ow-card ow-card--md" style={{ padding: 18, fontFamily: "var(--font-mono)", fontSize: 12 }}>
          <div style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 10, fontFamily: "var(--font-sans)", fontWeight: 600 }}>{T.techDetails}</div>
          <KV k={T.endpoint} v={active.endpoint}/>
          <KV k={T.fingerprint} v={active.fingerprint || "—"}/>
          <KV k={T.clientIp} v={active.client_address || "—"}/>
          <KV k="DNS" v={(active.dns || []).join(", ") || "—"} last/>
        </section>
      )}
    </div>
  );
};

const ErrorHome = ({ T, active, connError, onReconnect, onImport }) => (
  <div className="ow-screen" style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <Header title={T.nav_home} sub={T.home_ribbon}/>
    <section className="ow-hero" style={{ padding: 28 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <window.StatusDot tone="bad"/>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-bad)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.error}</span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.error_title}</div>
      {connError ? (
        <div style={{
          marginTop: 12, padding: "10px 12px", borderRadius: 8,
          background: "color-mix(in srgb, var(--brand-bad) 10%, transparent)",
          border: "1px solid color-mix(in srgb, var(--brand-bad) 35%, transparent)",
          fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text)",
          wordBreak: "break-word", maxWidth: 560,
        }}>
          {connError}
        </div>
      ) : (
        <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6, maxWidth: 540 }}>
          {T.error_genericBody}
        </div>
      )}
      <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 10 }}>
        {T.error_checkLog}
      </div>
      <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
        <window.Btn kind="primary" size="md" onClick={onReconnect}>{T.retry}</window.Btn>
        <window.Btn kind="ghost" size="md" onClick={onImport}>{T.error_importNew}</window.Btn>
      </div>
    </section>
  </div>
);

const Header = ({ title, sub, right }) => (
  <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 16 }}>
    <div>
      <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{title}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
    </div>
    {right && <div style={{ display: "flex", alignItems: "center", gap: 8 }}>{right}</div>}
  </header>
);

// Mirror-stacked area chart: download grows downward from the centre line,
// upload upward. Auto-scales to the max sample in the window so a low
// constant signal doesn't flatten to nothing. Renders a placeholder until
// we have at least two samples — one point doesn't define a line.
const ThroughputChart = ({ T, history }) => {
  const W = 760, H = 140, P = 8;
  const window_s = T.throughput_window.replace("{n}", String(history.length));
  const peak = history.reduce((m, s) => Math.max(m, s.rx || 0, s.tx || 0), 0);
  // Floor the scale so tiny constant traffic still draws a visible band.
  // 64 KB/s = 524288 b/s; one cell-tower screenshot's worth of upload, ish.
  const scale = Math.max(peak, 64 * 1024);
  const mid = H / 2;
  const innerH = mid - P;
  const innerW = W - P * 2;
  const xAt = (i) => history.length <= 1 ? P : P + (i * innerW) / (history.length - 1);
  const path = (key, sign) => {
    if (history.length === 0) return "";
    return history.map((s, i) => {
      const v = (s[key] || 0) / scale;
      const y = mid + sign * v * innerH;
      return `${i === 0 ? "M" : "L"} ${xAt(i).toFixed(1)} ${y.toFixed(1)}`;
    }).join(" ");
  };
  const area = (key, sign) => {
    if (history.length === 0) return "";
    return `${path(key, sign)} L ${(W - P).toFixed(1)} ${mid} L ${P} ${mid} Z`;
  };

  return (
    <section className="ow-card ow-card--md" style={{ padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10, gap: 12 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>
          {T.throughput_title}
          <span style={{ color: "var(--text-3)", fontWeight: 400, marginLeft: 8, fontFamily: "var(--font-mono)", fontSize: 12 }}>
            · {window_s}
          </span>
        </div>
        <div style={{ display: "flex", gap: 14, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)" }}>
          <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: "var(--brand)", marginRight: 6, verticalAlign: 1 }}/>{T.download}</span>
          <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: "var(--brand-2)", marginRight: 6, verticalAlign: 1 }}/>{T.upload}</span>
        </div>
      </div>
      {history.length < 2 ? (
        <div style={{ height: H, display: "grid", placeItems: "center", color: "var(--text-3)", fontSize: 12, fontFamily: "var(--font-mono)" }}>
          {T.throughput_empty}
        </div>
      ) : (
        <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
          <line x1="0" y1={mid} x2={W} y2={mid} stroke="var(--line)" strokeDasharray="2 4"/>
          <path d={area("rx", +1)} fill="color-mix(in srgb, var(--brand) 18%, transparent)"/>
          <path d={path("rx", +1)} stroke="var(--brand)" fill="none" strokeWidth="1.6"/>
          <path d={area("tx", -1)} fill="color-mix(in srgb, var(--brand-2) 18%, transparent)"/>
          <path d={path("tx", -1)} stroke="var(--brand-2)" fill="none" strokeWidth="1.6"/>
        </svg>
      )}
    </section>
  );
};

const Stat = ({ label, value, sub, trend }) => (
  <div className="ow-card" style={{ padding: 14 }}>
    <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>{label}</div>
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", gap: 8, marginTop: 6 }}>
      <div style={{ fontSize: 22, fontWeight: 600, fontFamily: "var(--font-mono)" }}>{value}</div>
      {trend}
    </div>
    {sub && <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>{sub}</div>}
  </div>
);

// ── Ported design atoms (mirror var-a.jsx) ─────────────────────────
const InfoCard = ({ icon, title, body }) => (
  <div className="ow-card ow-card--md ow-card--hover" style={{ padding: 16 }}>
    <div style={{ width: 32, height: 32, borderRadius: 8, background: "var(--chip)", display: "grid", placeItems: "center", color: "var(--brand)" }}>{icon}</div>
    <div style={{ fontSize: 13, fontWeight: 600, marginTop: 12 }}>{title}</div>
    <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 4 }}>{body}</div>
  </div>
);

const BgGlow = () => (
  <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden", borderRadius: 18 }}>
    <div style={{ position: "absolute", right: -80, top: -80, width: 280, height: 280, background: "radial-gradient(circle, color-mix(in srgb, var(--brand) 22%, transparent), transparent 60%)" }}/>
  </div>
);

// Auto-scaling sparkline. Feeds off the live throughput history; flat/short
// series fall back to a single baseline segment rather than a misleading line.
const Spark = ({ data = [], good }) => {
  const w = 48, h = 14;
  const peak = data.reduce((m, v) => Math.max(m, v || 0), 0) || 1;
  const pts = data.map((v, i) => {
    const x = data.length <= 1 ? 0 : (i * w) / (data.length - 1);
    const y = h - 2 - ((v || 0) / peak) * (h - 4);
    return `${x.toFixed(1)},${y.toFixed(1)}`;
  }).join(" ");
  return (
    <svg width={w} height={h} viewBox={`0 0 ${w} ${h}`} style={{ flexShrink: 0 }}>
      <polyline points={pts} fill="none" stroke={good ? "var(--brand-2)" : "var(--brand-bad)"} strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round"/>
    </svg>
  );
};

const HomeIcon = (d, s = 16) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{d}</svg>;
const IconShield = ({ size }) => HomeIcon(<path d="M12 3 L4 6 V12 C4 17 8 20 12 21 C16 20 20 17 20 12 V6 Z"/>, size);
const IconLock   = ({ size }) => HomeIcon(<><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11 V8 a4 4 0 0 1 8 0 V11"/></>, size);
const IconRoute  = ({ size }) => HomeIcon(<><circle cx="6" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M6 8 V14 a4 4 0 0 0 4 4 H16"/></>, size);
const IconLogs   = ({ size }) => HomeIcon(<><path d="M5 4 H19 V20 H5 Z"/><path d="M8 8 H16 M8 12 H16 M8 16 H13"/></>, size);

const KV = ({ k, v, last }) => (
  <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, padding: "8px 0", borderBottom: last ? "none" : "1px dashed var(--line)" }}>
    <div style={{ color: "var(--text-3)" }}>{k}</div>
    <div style={{ color: "var(--text)", wordBreak: "break-all" }}>{v}</div>
  </div>
);

const PowerGlyph = ({ size = 30, color = "currentColor" }) => (
  <svg width={size} height={size} viewBox="0 0 24 24" fill="none" stroke={color}
       strokeWidth="1.9" strokeLinecap="round" strokeLinejoin="round">
    <path d="M12 3 V11"/><path d="M6.6 6.6 a7.5 7.5 0 1 0 10.8 0"/>
  </svg>
);

// The dial is the primary connect/disconnect control, not decoration.
// - disconnected/empty: a real button; clicking calls onClick (connect).
// - connected: a button labelled with the disconnect action.
// - connecting/reconnecting: non-interactive, ring spins as a progress hint.
// State (Connected/…) is shown by the hero's StatusDot + pill; the dial label
// is always the *action* the click performs, mirroring Mullvad/Proton.
const Dial = ({ status = "disconnected", onClick, label }) => {
  const connected = status === "connected";
  const busy = status === "connecting" || status === "reconnecting";
  const interactive = !!onClick && !busy;
  const puckColor = connected ? "#fff" : "var(--text)";

  const body = (
    <>
      <svg width="200" height="200" viewBox="0 0 200 200">
        <defs>
          <linearGradient id="dial-grad" x1="0" y1="0" x2="1" y2="1">
            <stop offset="0" stopColor="var(--brand)"/>
            <stop offset="1" stopColor="var(--brand-2)"/>
          </linearGradient>
        </defs>
        <circle cx="100" cy="100" r="86" stroke="var(--line-strong)" strokeWidth="1" fill="none"/>
        <circle cx="100" cy="100" r="72" stroke="var(--line)" strokeWidth="1" fill="none" strokeDasharray="2 4"/>
        {connected && (
          <circle cx="100" cy="100" r="86" stroke="url(#dial-grad)" strokeWidth="3" fill="none"
            strokeDasharray={`${2*Math.PI*86*0.78} ${2*Math.PI*86}`}
            transform="rotate(-90 100 100)" strokeLinecap="round"/>
        )}
        {busy && (
          <circle className="ow-dial-spin" cx="100" cy="100" r="86" stroke="var(--brand-warn)"
            strokeWidth="3" fill="none"
            strokeDasharray={`${2*Math.PI*86*0.25} ${2*Math.PI*86}`} strokeLinecap="round"/>
        )}
      </svg>
      <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
        <div style={{
          width: 118, height: 118, borderRadius: 999,
          background: connected ? "linear-gradient(135deg, var(--brand), var(--brand-2))" : "var(--bg-sunk)",
          border: connected ? "none" : "1px solid var(--line-strong)",
          display: "flex", flexDirection: "column", gap: 6, alignItems: "center", justifyContent: "center",
          color: puckColor,
          boxShadow: connected ? "0 14px 30px -10px color-mix(in srgb, var(--brand) 55%, transparent)" : "none",
        }}>
          {connected
            ? <window.WSLogoMark size={34} color="#fff" accent="rgba(255,255,255,.6)"/>
            : <PowerGlyph size={30} color={busy ? "var(--brand-warn)" : "var(--brand)"}/>}
          {label && <span style={{ fontSize: 12, fontWeight: 600, letterSpacing: "-0.01em" }}>{label}</span>}
        </div>
      </div>
    </>
  );

  if (interactive) {
    return (
      <button type="button" className="ow-dial" role="button" aria-label={label} onClick={onClick}>
        {body}
      </button>
    );
  }
  return <div className="ow-dial" aria-live="polite">{body}</div>;
};

// ── Import / Profiles ──────────────────────────────────────────────
const Import = ({ T, api, active, confirm, onImported, onRemove, onProfilesChanged }) => {
  const fileRef = useRef(null);
  const [mode, setMode] = useState("file");      // "file" | "paste"
  const [paste, setPaste] = useState("");
  const [msg, setMsg] = useState("");
  const [error, setError] = useState("");
  const [showEditor, setShowEditor] = useState(false);

  // Single import path used by both the file picker / drop and the textarea.
  // `source` only controls a UX detail (clearing the textarea after a paste).
  const submit = async (text, source) => {
    setError("");
    if (!text || !text.trim()) {
      setError(T.errorUnknown);
      return;
    }
    // Replacing an existing profile: confirm first regardless of source.
    if (active) {
      const ok = await confirm({
        title: T.profiles_replaceTitle,
        message: T.profiles_replaceWarn,
        confirmLabel: T.confirm_continue,
        cancelLabel: T.cancel,
      });
      if (!ok) return;
    }
    setMsg(T.importReading);
    try {
      const r = await api.import_profile(text);
      if (r.ok) {
        setMsg(`✓ ${r.profile.name}`);
        if (source === "paste") setPaste("");
        onImported(r.profile);
      } else {
        setMsg("");
        setError(r.error || T.errorUnknown);
      }
    } catch (e) {
      setMsg("");
      setError(String(e));
    }
  };

  const handleFile = async (file) => {
    if (!file) return;
    try {
      const text = await file.text();
      await submit(text, "file");
    } catch (e) {
      setError(String(e));
    }
  };

  // Container-level drop so dropping anywhere on the Import screen works —
  // not just on the dashed dropzone, and not just on the empty-state view.
  // Useful when a profile already exists and the user drops a replacement.
  const onContainerDragOver = (e) => e.preventDefault();
  const onContainerDrop = (e) => {
    e.preventDefault();
    const f = e.dataTransfer.files?.[0];
    if (f) handleFile(f);
  };

  return (
    <div onDragOver={onContainerDragOver} onDrop={onContainerDrop} className="ow-screen"
         style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 720 }}>
      <Header
        title={active ? T.profiles_title : T.welcomeTitle}
        sub={T.welcomeSub}
      />

      <input ref={fileRef} type="file"
             accept=".owcfg,.warpcfg,.json,.txt" hidden
             onChange={(e) => handleFile(e.target.files[0])}/>

      <div style={{
        display: "inline-flex", gap: 4, padding: 4,
        background: "var(--bg-sunk)", borderRadius: 10, width: "fit-content",
      }}>
        <ImportTabBtn active={mode === "file"}  onClick={() => setMode("file")}>{T.import_tabFile}</ImportTabBtn>
        <ImportTabBtn active={mode === "paste"} onClick={() => setMode("paste")}>{T.import_tabPaste}</ImportTabBtn>
      </div>

      {mode === "file" && (
        <DropZone T={T}
          onPick={() => fileRef.current?.click()}
          onFile={handleFile}/>
      )}
      {mode === "paste" && (
        <PasteArea T={T}
          value={paste}
          onChange={setPaste}
          onSubmit={() => submit(paste, "paste")}
          disabled={!paste.trim()}/>
      )}

      {msg && (
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-2)" }}>
          {msg}
        </div>
      )}
      {error && (
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-bad)" }}>
          {error}
        </div>
      )}

      {active && (
        <ProfileCard active={active}
          editLabel={T.edit_open}
          removeLabel={T.profiles_remove}
          onEdit={() => setShowEditor((v) => !v)}
          onRemove={onRemove}/>
      )}
      {showEditor && active && (
        <div>
          <ProfileEditor
            T={T} api={api} active={active} confirm={confirm}
            onUpdated={onProfilesChanged}
            onClose={() => setShowEditor(false)}/>
        </div>
      )}
    </div>
  );
};

const ImportTabBtn = ({ active, onClick, children }) => (
  <button onClick={onClick} type="button"
    style={{
      all: "unset", padding: "6px 14px", borderRadius: 8, cursor: "pointer",
      fontSize: 12, fontWeight: 600,
      background: active ? "var(--bg)" : "transparent",
      color: active ? "var(--text)" : "var(--text-3)",
      boxShadow: active ? "0 1px 2px rgba(0,0,0,.12)" : "none",
      transition: "background .15s, color .15s",
    }}>{children}</button>
);

const DropZone = ({ T, onPick, onFile }) => (
  <div
    onDragOver={(e) => { e.preventDefault(); e.stopPropagation(); }}
    onDrop={(e) => {
      // stopPropagation: the outer container also listens for drop so users
      // can drop anywhere on the screen. Without it the same file is handed
      // to handleFile twice and import_profile runs twice — that races two
      // TunnelManagers, both binding wstunnel on UDP :51820 → port crash.
      e.preventDefault();
      e.stopPropagation();
      const f = e.dataTransfer.files?.[0];
      if (f) onFile(f);
    }}
    style={{
      border: "1.5px dashed var(--line-strong)", borderRadius: "var(--radius-md)", padding: 32,
      background: "var(--bg-2)", textAlign: "center",
    }}>
    <div style={{
      width: 48, height: 48, borderRadius: 12,
      background: "color-mix(in srgb, var(--brand) 12%, transparent)",
      color: "var(--brand)", display: "grid", placeItems: "center",
      margin: "0 auto",
    }}>
      <svg width="22" height="22" viewBox="0 0 24 24" fill="none"
        stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">
        <path d="M12 16 V4 M6 10 L12 4 L18 10"/><path d="M4 20 H20"/>
      </svg>
    </div>
    <div style={{ fontSize: 15, fontWeight: 600, marginTop: 10 }}>{T.importDrop}</div>
    <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{T.importHint}</div>
    <div style={{ marginTop: 16 }}>
      <window.Btn kind="primary" size="md" onClick={onPick}>{T.importFile}</window.Btn>
    </div>
  </div>
);

const PasteArea = ({ T, value, onChange, onSubmit, disabled }) => (
  <div className="ow-card ow-card--md" style={{ padding: 18 }}>
    <div style={{ fontSize: 13, fontWeight: 600 }}>{T.importPaste}</div>
    <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{T.importHint}</div>
    <textarea
      value={value}
      onChange={(e) => onChange(e.target.value)}
      spellCheck={false}
      placeholder='{ "server": { ... }, "wireguard": { ... } }'
      style={{
        marginTop: 12, width: "100%", height: 220, resize: "vertical",
        background: "var(--bg)", color: "var(--text)",
        border: "1px solid var(--line-strong)", borderRadius: 10,
        padding: "10px 12px", outline: "none",
        fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.55,
        boxSizing: "border-box",
      }}/>
    <div style={{ marginTop: 12, display: "flex", justifyContent: "flex-end" }}>
      <window.Btn kind="primary" size="md" disabled={disabled} onClick={onSubmit}>
        {T.import_loadFromPaste}
      </window.Btn>
    </div>
  </div>
);

const ProfileCard = ({ active, onEdit, onRemove, editLabel, removeLabel }) => (
  <div className="ow-card" style={{
    padding: 16,
    display: "flex", justifyContent: "space-between", alignItems: "center",
    gap: 12,
  }}>
    <div style={{ minWidth: 0 }}>
      <div style={{ fontSize: 13, fontWeight: 600 }}>{active.name}</div>
      <div style={{
        fontSize: 12, color: "var(--text-3)", marginTop: 2,
        fontFamily: "var(--font-mono)",
        overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap",
      }}>{active.endpoint}</div>
    </div>
    <div style={{ display: "flex", gap: 8, flexShrink: 0 }}>
      <window.Btn kind="ghost"  size="sm" onClick={onEdit}>{editLabel}</window.Btn>
      <window.Btn kind="danger" size="sm" onClick={onRemove}>{removeLabel}</window.Btn>
    </div>
  </div>
);

// ── Profile editor ─────────────────────────────────────────────────
// Lets the user tweak the connection settings the server baked into the
// .owcfg (name, MTU, DNS, client IP, bypass routes, reconnect backoff).
// Gated behind a disclaimer because a wrong value breaks the tunnel; the
// "reset to defaults" button restores the pristine imported config.
const ProfileEditor = ({ T, api, active, confirm, onUpdated, onClose }) => {
  const [ack, setAck] = useState(false);
  const [form, setForm] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!active) { setForm(null); return; }
    setForm({
      name: active.name || "",
      client_address: active.client_address || "",
      mtu: String(active.mtu ?? 1380),
      dns: (active.dns || []).join(", "),
      bypass_ips: (active.bypass_ips || []).join(", "),
      reconnect_max_attempts: String(active.reconnect_max_attempts ?? 5),
      reconnect_delays: (active.reconnect_delays || []).join(", "),
    });
    setAck(false);
  }, [active]);

  if (!form) return null;

  const set = (k, v) => setForm((f) => ({ ...f, [k]: v }));

  const save = async () => {
    if (!api) return;
    setBusy(true); setErr(""); setMsg("");
    const r = await api.update_profile(active.id, { ...form });
    setBusy(false);
    if (r && r.ok) { setMsg(T.edit_saved); await onUpdated?.(); }
    else { setErr((r && r.error) || T.error); }
  };

  const reset = async () => {
    if (!api) return;
    const ok = await confirm({
      title: T.edit_resetTitle,
      message: T.edit_resetConfirm,
      confirmLabel: T.confirm_reset,
      cancelLabel: T.cancel,
      danger: true,
    });
    if (!ok) return;
    setBusy(true); setErr(""); setMsg("");
    const r = await api.reset_profile(active.id);
    setBusy(false);
    if (r && r.ok) { setMsg(T.edit_resetDone); await onUpdated?.(); }
    else { setErr((r && r.error) || T.error); }
  };

  // Plain render function (not a component) — defining a component inside the
  // render would remount the <input> on every keystroke and drop focus.
  const field = (label, k, { hint = "", mono = true } = {}) => (
    <div key={k} style={{ display: "flex", flexDirection: "column", gap: 4 }}>
      <label style={{ fontSize: 12, fontWeight: 600, color: "var(--text-2)" }}>{label}</label>
      <input
        className="ow-input"
        value={form[k]}
        disabled={!ack || busy}
        onChange={(e) => set(k, e.target.value)}
        style={{ width: "100%", fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)" }}
      />
      {hint && <div style={{ fontSize: 11, color: "var(--text-3)" }}>{hint}</div>}
    </div>
  );

  return (
    <section className="ow-card ow-card--md" style={{ padding: 18, display: "flex", flexDirection: "column", gap: 16 }}>
      <div>
        <div style={{ fontSize: 15, fontWeight: 600 }}>{T.edit_title}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{T.edit_sub}</div>
      </div>

      {!ack && (
        <div style={{
          background: "color-mix(in srgb, var(--brand-warn) 12%, transparent)",
          border: "1px solid color-mix(in srgb, var(--brand-warn) 45%, transparent)",
          borderRadius: 10, padding: 14,
        }}>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginBottom: 6 }}>
            <svg width="16" height="16" viewBox="0 0 24 24" fill="none" stroke="var(--brand-warn)" strokeWidth="1.8" strokeLinecap="round" strokeLinejoin="round"><path d="M12 3 L22 20 H2 Z"/><path d="M12 10 V14 M12 17 V17.5"/></svg>
            <div style={{ fontSize: 13, fontWeight: 600, color: "var(--brand-warn)" }}>{T.edit_disclaimerTitle}</div>
          </div>
          <div style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.55 }}>{T.edit_disclaimerBody}</div>
          <div style={{ marginTop: 12, display: "flex", gap: 8 }}>
            <window.Btn kind="ghost" size="sm" onClick={() => { setMsg(""); setErr(""); setAck(true); }}>{T.edit_disclaimerAck}</window.Btn>
            <window.Btn kind="ghost" size="sm" onClick={onClose}>{T.edit_cancel}</window.Btn>
          </div>
        </div>
      )}

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        {field(T.edit_name, "name", { mono: false })}
        {field(T.edit_mtu, "mtu", { hint: T.edit_mtuHint })}
        {field(T.edit_clientIp, "client_address", { hint: T.edit_clientIpHint })}
        {field(T.edit_dns, "dns", { hint: T.edit_dnsHint })}
        {field(T.edit_bypass, "bypass_ips", { hint: T.edit_bypassHint })}
        {field(T.edit_maxAttempts, "reconnect_max_attempts")}
        <div style={{ gridColumn: "1 / -1" }}>
          {field(T.edit_delays, "reconnect_delays", { hint: T.edit_delaysHint })}
        </div>
      </div>

      {ack && (
        <div style={{ display: "flex", alignItems: "center", gap: 10, flexWrap: "wrap" }}>
          <window.Btn kind="primary" size="md" onClick={save} disabled={busy}>{T.edit_save}</window.Btn>
          <window.Btn kind="danger" size="md" onClick={reset} disabled={busy}>{T.edit_reset}</window.Btn>
          <window.Btn kind="ghost" size="md" onClick={onClose} disabled={busy}>{T.edit_cancel}</window.Btn>
          <span style={{ fontSize: 11, color: "var(--text-3)" }}>{T.edit_reconnectNote}</span>
        </div>
      )}

      {msg && <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-2)" }}>{msg}</div>}
      {err && <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-bad)" }}>{err}</div>}
    </section>
  );
};

// ── Logs ───────────────────────────────────────────────────────────
const LOG_LEVEL_COLOR = {
  error: "var(--brand-bad)", warn: "var(--brand-warn)", debug: "var(--text-3)",
};
const Logs = ({ T, logs, api, onClear }) => {
  const ref = useRef(null);
  const atBottomRef = useRef(true);
  const [atBottom, setAtBottom] = useState(true);
  const [filter, setFilter] = useState("");
  const [level, setLevel] = useState("all");
  const [exportMsg, setExportMsg] = useState("");

  // Auto-scroll only when the user is already at the bottom — don't yank them
  // down while they're scrolled up reading history.
  useEffect(() => {
    const el = ref.current;
    if (el && atBottomRef.current) el.scrollTop = el.scrollHeight;
  }, [logs.length]);
  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    const isBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    atBottomRef.current = isBottom;
    setAtBottom(isBottom);
  };
  const jumpToBottom = () => {
    const el = ref.current;
    if (!el) return;
    el.scrollTop = el.scrollHeight;
    atBottomRef.current = true;
    setAtBottom(true);
  };

  const filtered = logs.filter((l) =>
    (level === "all" || l.level === level) &&
    (!filter || l.msg.toLowerCase().includes(filter.toLowerCase()))
  );

  const doClear = async () => { await api?.clear_logs?.(); onClear(); };
  const doExport = async () => {
    const r = await api?.export_logs?.();
    if (r && r.ok) { setExportMsg(T.logs_exported); setTimeout(() => setExportMsg(""), 3000); }
  };

  const levels = [
    ["all", T.logs_levelAll], ["info", "INFO"], ["warn", "WARN"],
    ["error", "ERROR"], ["debug", "DEBUG"],
  ];

  return (
    <section className="ow-screen" style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      <Header title={T.logs_title} sub="outwarp-client" right={
        <>
          <select className="ow-input" value={level} onChange={(e) => setLevel(e.target.value)}
            aria-label={T.logs_level} style={{ width: "auto", height: 30, fontSize: 12 }}>
            {levels.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
          </select>
          <input className="ow-input" value={filter} onChange={(e) => setFilter(e.target.value)}
            placeholder={T.logs_filter} style={{ width: 200, height: 30, fontSize: 12 }}/>
          <window.Btn kind="ghost" size="sm" onClick={doExport}>{T.logs_export}</window.Btn>
          <window.Btn kind="ghost" size="sm" onClick={doClear}>{T.logs_clear}</window.Btn>
        </>
      }/>
      {exportMsg && <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-2)" }}>{exportMsg}</div>}
      <div style={{ position: "relative", flex: 1, minHeight: 360 }}>
        <div ref={ref} onScroll={onScroll} style={{
          background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: "var(--radius-sm)",
          fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.65,
          padding: 14, color: "var(--text-2)", overflow: "auto",
          height: "100%", cursor: "text",
        }} className="ws-scroll ow-logs">
          {filtered.map((l) => (
            <div key={l.seq} style={{ display: "grid", gridTemplateColumns: "84px 60px 1fr", gap: 10 }}>
              <span style={{ color: "var(--text-3)" }}>{fmtClock(l.ts)}</span>
              <span style={{ color: LOG_LEVEL_COLOR[l.level] || "var(--brand-2)", textTransform: "uppercase" }}>{l.level}</span>
              <span style={{ color: "var(--text)", wordBreak: "break-all" }}>{l.msg}</span>
            </div>
          ))}
          {filtered.length === 0 && <div style={{ opacity: .5 }}>{T.logs_empty}</div>}
        </div>
        {!atBottom && (
          <button onClick={jumpToBottom} className="ow-logs-jump" type="button">
            ↓ {T.logs_jumpBottom}
          </button>
        )}
      </div>
    </section>
  );
};

// ── Settings ───────────────────────────────────────────────────────
const SettingsCard = ({ title, children }) => (
  <div>
    {title && (
      <div style={{
        fontSize: 11, fontWeight: 600, color: "var(--text-3)",
        letterSpacing: ".06em", textTransform: "uppercase",
        margin: "0 4px 8px",
      }}>{title}</div>
    )}
    <div className="ow-card ow-card--md" style={{ padding: "0 18px" }}>{children}</div>
  </div>
);

const SettingsRow = ({ title, sub, control, isLast }) => (
  <div style={{
    display: "grid", gridTemplateColumns: "1fr auto", gap: 16,
    alignItems: "center", padding: "14px 0",
    borderBottom: isLast ? "none" : "1px solid var(--line)",
  }}>
    <div>
      <div style={{ fontSize: 13, fontWeight: 500 }}>{title}</div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2, lineHeight: 1.45 }}>{sub}</div>}
    </div>
    <div>{control}</div>
  </div>
);

const SettingsSelect = ({ value, onChange, options }) => (
  <select className="ow-input" value={value} onChange={(e) => onChange(e.target.value)}
    style={{ height: 30, fontSize: 13, width: "auto" }}>
    {options.map(([v, l]) => <option key={v} value={v}>{l}</option>)}
  </select>
);

const Settings = ({ T, settings, onSetting }) => {
  // Side-effecting toggles (kill_switch on Linux/macOS, start_at_boot on a
  // platform where the registry write fails, etc.) return {ok:false}. Surface
  // the error inline; the persisted value is rolled back by the backend and
  // arrives via outwarp:settings, so the toggle's visual state self-corrects.
  const [error, setError] = useState("");

  const apply = async (k, v) => {
    setError("");
    const r = await onSetting(k, v);
    if (r && r.ok === false && r.error) setError(r.error);
  };

  const groups = [
    { key: "appearance", title: T.set_groupAppearance, rows: [
      { title: T.set_language, control: (
        <SettingsSelect value={settings.language} onChange={(v) => apply("language", v)}
          options={[["es", "Español"], ["en", "English"]]}/>
      )},
      { title: T.set_theme, control: (
        <SettingsSelect value={settings.theme} onChange={(v) => apply("theme", v)}
          options={[["auto", T.set_themeAuto], ["light", T.set_themeLight], ["dark", T.set_themeDark]]}/>
      )},
      { title: T.set_advanced, sub: T.set_advancedSub, control: (
        <window.Toggle on={!!settings.advanced} onChange={(v) => apply("advanced", v)}/>
      )},
    ]},
    { key: "connection", title: T.set_groupConnection, rows: [
      { title: T.set_autoconnectLaunch, sub: T.set_autoconnectLaunchSub, control: (
        <window.Toggle on={!!settings.auto_connect} onChange={(v) => apply("auto_connect", v)}/>
      )},
      { title: T.set_autoconnect, sub: T.set_autoconnectSub, control: (
        <window.Toggle on={!!settings.auto_reconnect} onChange={(v) => apply("auto_reconnect", v)}/>
      )},
      { title: T.set_killSwitch, sub: T.set_killSwitchSub, control: (
        <window.Toggle on={!!settings.kill_switch} onChange={(v) => apply("kill_switch", v)}/>
      )},
      { title: T.set_tlsIntercept, sub: T.set_tlsInterceptSub, control: (
        <window.Toggle on={!!settings.allow_tls_intercept} onChange={(v) => apply("allow_tls_intercept", v)}/>
      )},
    ]},
    { key: "system", title: T.set_groupSystem, rows: [
      { title: T.set_startup, sub: T.set_startupSub, control: (
        <window.Toggle on={!!settings.start_at_boot} onChange={(v) => apply("start_at_boot", v)}/>
      )},
      { title: T.set_minimizeTray, sub: T.set_minimizeTraySub, control: (
        <window.Toggle on={!!settings.minimize_to_tray} onChange={(v) => apply("minimize_to_tray", v)}/>
      )},
      { title: T.set_checkUpdates, sub: T.set_checkUpdatesSub, control: (
        <window.Toggle on={!!settings.check_updates_on_start} onChange={(v) => apply("check_updates_on_start", v)}/>
      )},
    ]},
  ];

  return (
    <section className="ow-screen" style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 720 }}>
      <Header title={T.nav_settings} sub="outwarp-client · v0.0.1"/>

      {error && (
        <div style={{
          background: "color-mix(in srgb, var(--brand-bad) 12%, transparent)",
          border: "1px solid color-mix(in srgb, var(--brand-bad) 35%, transparent)",
          color: "var(--brand-bad)",
          borderRadius: 12, padding: "12px 14px", fontSize: 13,
        }}>
          <div style={{ fontWeight: 600, marginBottom: 2 }}>{T.set_errorTitle}</div>
          <div style={{ color: "var(--text-2)", fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.5 }}>{error}</div>
        </div>
      )}

      {groups.map((g) => (
        <SettingsCard key={g.key} title={g.title}>
          {g.rows.map((r, i) => (
            <SettingsRow key={r.title} title={r.title} sub={r.sub}
              control={r.control} isLast={i === g.rows.length - 1}/>
          ))}
        </SettingsCard>
      ))}
    </section>
  );
};

// ── Update panel (lives inside About) ──────────────────────────────
// Drives the "check for updates" → "update now" flow. Checking is synchronous
// over the bridge; applying (Windows) runs in the background and reports
// download progress + phases via the outwarp:update event. On Linux there is
// no .exe to apply, so check_for_updates() returns {manual, command} and we
// show the install one-liner instead.
const UpdatePanel = ({ T, api, autoCheck }) => {
  const [state, setState] = useState("idle"); // idle|checking|current|available|downloading|applying|error
  const [info, setInfo] = useState(null);
  const [progress, setProgress] = useState(0);
  const [error, setError] = useState("");
  const [copied, setCopied] = useState(false);

  const doCheck = useCallback(async () => {
    if (!api) return;
    setState("checking");
    setError("");
    const r = await api.check_for_updates();
    setInfo(r);
    if (r.error) { setState("error"); setError(r.error); return; }
    setState(r.available ? "available" : "current");
  }, [api]);

  // Auto-check once on mount when the user opted in.
  useEffect(() => { if (autoCheck) doCheck(); }, [autoCheck, doCheck]);

  // Progress + phase events emitted by apply_update() on Windows.
  useBridgeEvent("update", useCallback((d) => {
    if (d.phase === "downloading") { setState("downloading"); setProgress(d.progress || 0); }
    else if (d.phase === "applying") { setState("applying"); }
    else if (d.phase === "error") { setState("error"); setError(d.error || ""); }
    else if (d.phase === "current") { setState("current"); }
  }, []));

  const doApply = async () => { if (api) await api.apply_update(); };
  const copyCmd = async (cmd) => {
    try {
      await navigator.clipboard.writeText(cmd);
      setCopied(true);
      setTimeout(() => setCopied(false), 2000);
    } catch (_) {}
  };

  const wrap = { marginTop: 18, paddingTop: 18, borderTop: "1px solid var(--line)" };

  if (state === "checking")
    return <div style={wrap}><span style={{ fontSize: 13, color: "var(--text-3)" }}>{T.upd_checking}</span></div>;

  if (state === "downloading")
    return (
      <div style={{ ...wrap, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 13, color: "var(--text-2)" }}>{T.upd_downloading} {progress}%</div>
        <div style={{ height: 6, borderRadius: 4, background: "var(--line)", overflow: "hidden" }}>
          <div style={{ height: "100%", width: `${progress}%`, background: "var(--brand)", transition: "width .2s" }}/>
        </div>
      </div>
    );

  if (state === "applying")
    return <div style={wrap}><span style={{ fontSize: 13, color: "var(--text-2)" }}>{T.upd_applying}</span></div>;

  if (state === "error")
    return (
      <div style={{ ...wrap, display: "flex", flexDirection: "column", gap: 8 }}>
        <div style={{ fontSize: 13, color: "var(--brand-bad)" }}>{T.upd_error}</div>
        {error && <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-3)", wordBreak: "break-all" }}>{error}</div>}
        <div style={{ display: "flex", gap: 8 }}>
          <window.Btn kind="ghost" size="sm" onClick={doCheck}>{T.upd_check}</window.Btn>
          {info?.html_url && <window.Btn kind="ghost" size="sm" onClick={() => api?.open_url(info.html_url)}>{T.upd_seeReleases}</window.Btn>}
        </div>
      </div>
    );

  if (state === "current")
    return (
      <div style={{ ...wrap, display: "flex", alignItems: "center", gap: 10 }}>
        <window.Pill tone="good">v{info?.latest || info?.current}</window.Pill>
        <span style={{ fontSize: 13, color: "var(--text-2)", flex: 1 }}>{T.upd_current}</span>
        <window.Btn kind="ghost" size="sm" onClick={doCheck}>{T.upd_check}</window.Btn>
      </div>
    );

  if (state === "available" && info)
    return (
      <div style={{ ...wrap, display: "flex", flexDirection: "column", gap: 10 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
          <span style={{ fontSize: 13, color: "var(--text-2)" }}>{T.upd_available}</span>
          <window.Pill tone="brand">v{info.latest}</window.Pill>
        </div>
        {info.notes && (
          <div className="ws-scroll" style={{
            background: "var(--bg)", border: "1px solid var(--line)", borderRadius: 10,
            padding: "10px 12px", maxHeight: 160, overflow: "auto",
          }}>
            <window.Markdown text={info.notes}/>
          </div>
        )}
        {info.manual ? (
          <div style={{ display: "flex", flexDirection: "column", gap: 8 }}>
            <div style={{ fontSize: 13, color: "var(--text-2)" }}>{T.upd_linux}</div>
            <div style={{ display: "flex", gap: 8, alignItems: "stretch" }}>
              <code style={{
                flex: 1, fontFamily: "var(--font-mono)", fontSize: 12, background: "var(--bg)",
                border: "1px solid var(--line)", borderRadius: 8, padding: "8px 10px",
                color: "var(--text)", wordBreak: "break-all",
              }}>{info.command}</code>
              <window.Btn kind="ghost" size="sm" onClick={() => copyCmd(info.command)}>{copied ? T.upd_copied : T.upd_copy}</window.Btn>
            </div>
          </div>
        ) : (
          <div style={{ display: "flex", gap: 8 }}>
            <window.Btn kind="primary" size="md" onClick={doApply}>{T.upd_now}</window.Btn>
            <window.Btn kind="ghost" size="md" onClick={() => api?.open_url(info.html_url)}>{T.upd_seeReleases}</window.Btn>
          </div>
        )}
      </div>
    );

  return <div style={wrap}><window.Btn kind="ghost" size="sm" onClick={doCheck}>{T.upd_check}</window.Btn></div>;
};

// ── About ──────────────────────────────────────────────────────────
const About = ({ T, api, settings }) => {
  const [info, setInfo] = useState(null);
  useEffect(() => {
    if (!api) return;
    let alive = true;
    api.get_app_info().then((data) => { if (alive) setInfo(data); });
    return () => { alive = false; };
  }, [api]);

  // Best-effort: any failure to open the URL is logged server-side and the
  // bridge returns {ok:false}. We don't surface it inline because the only
  // realistic failure is a Linux box without a default browser, which we
  // can't fix from here anyway.
  const openUrl = (url) => api?.open_url(url);

  if (!info) {
    return (
      <section style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 720 }}>
        <Header title={T.nav_about} sub={T.about_sub}/>
      </section>
    );
  }

  return (
    <section className="ow-screen" style={{ display: "flex", flexDirection: "column", gap: 22, maxWidth: 720 }}>
      <Header title={T.nav_about} sub={T.about_sub}/>

      <div className="ow-card ow-card--md" style={{ padding: 24 }}>
        <window.WSWordmark size={22} color="var(--text)" accent="var(--brand)"/>
        <div style={{
          marginTop: 14, fontFamily: "var(--font-mono)", fontSize: 12,
          color: "var(--text-3)",
        }}>
          v{info.version} · {info.platform} · Python {info.python}
        </div>
        <div style={{
          marginTop: 14, fontSize: 13, color: "var(--text-2)", lineHeight: 1.6,
        }}>
          {T.about_blurb}
        </div>
        <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
          <window.Btn kind="primary" size="md" onClick={() => openUrl(info.repo_url)}>
            {T.about_openRepo}
          </window.Btn>
        </div>

        <UpdatePanel T={T} api={api} autoCheck={!!settings?.check_updates_on_start}/>
      </div>

      <div>
        <div style={{
          fontSize: 11, fontWeight: 600, color: "var(--text-3)",
          letterSpacing: ".06em", textTransform: "uppercase",
          margin: "0 4px 8px",
        }}>{T.about_thirdParty}</div>
        <div className="ow-card ow-card--md" style={{ overflow: "hidden" }}>
          {info.third_party.map((p, i) => (
            <div key={p.name} style={{
              display: "grid", gridTemplateColumns: "1fr auto auto",
              gap: 16, alignItems: "center", padding: "14px 18px",
              borderTop: i === 0 ? "none" : "1px solid var(--line)",
            }}>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{p.name}</div>
              <window.Pill tone="neutral">{p.license}</window.Pill>
              <button onClick={() => openUrl(p.url)} className="ow-link" type="button">
                {T.about_openUrl}
              </button>
            </div>
          ))}
        </div>
      </div>

      <div style={{
        fontSize: 11, color: "var(--text-3)", lineHeight: 1.6, padding: "0 4px",
      }}>
        {T.about_disclaimer}
      </div>
    </section>
  );
};

// Catch errors that escape React's render cycle (event handlers, async
// callbacks, bridge promises) and forward them to the Python log so a field
// crash leaves a trace instead of a silent renderer. The boundary below handles
// render-time errors and the user-facing recovery screen.
window.addEventListener("error", (e) => {
  try { window.pywebview?.api?.report_ui_error?.(`window.error: ${e.message} @ ${e.filename || "?"}:${e.lineno || 0}`); } catch (_) {}
});
window.addEventListener("unhandledrejection", (e) => {
  try {
    const r = e.reason;
    window.pywebview?.api?.report_ui_error?.(`unhandledrejection: ${(r && (r.stack || r.message)) || r}`);
  } catch (_) {}
});

ReactDOM.createRoot(document.getElementById("root")).render(
  <window.ErrorBoundary><App/></window.ErrorBoundary>
);
