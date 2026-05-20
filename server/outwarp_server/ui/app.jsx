// OutWarp Server — runtime app shell.
//
// Wires the design (srv-a / srv-b) to window.pywebview.api. The static
// srv-a/b previews are not used directly; this shell mirrors their visual
// language but every control here is functional.
//
// settings.advanced = true switches the chassis to "dev mode" styling.

const { useState, useEffect, useCallback, useRef } = React;

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

const fmtBytes = (n) => {
  if (!n) return "0 B";
  if (n < 1024) return `${n} B`;
  if (n < 1024 * 1024) return `${(n / 1024).toFixed(1)} KB`;
  if (n < 1024 * 1024 * 1024) return `${(n / 1024 / 1024).toFixed(1)} MB`;
  return `${(n / 1024 / 1024 / 1024).toFixed(2)} GB`;
};

const fmtAge = (sec) => {
  if (sec == null) return "—";
  if (sec < 60) return `${sec}s`;
  if (sec < 3600) return `${Math.floor(sec / 60)}m`;
  if (sec < 86400) return `${Math.floor(sec / 3600)}h`;
  return `${Math.floor(sec / 86400)}d`;
};

function App() {
  const [api, setApi] = useState(null);
  const [status, setStatus] = useState(null);
  const [clients, setClients] = useState([]);
  const [logs, setLogs] = useState([]);
  const [settings, setSettings] = useState({ language: "es", theme: "auto", advanced: false });
  const [screen, setScreen] = useState("dashboard");
  const [confirm, confirmDialog] = window.useConfirmState();
  const [bridgeAlive, setBridgeAlive] = useState(true);
  const pollFailsRef = useRef(0);

  // bootstrap
  useEffect(() => {
    waitForBridge().then(async (a) => {
      setApi(a);
      const [s, st, lg] = await Promise.all([a.get_status(), a.get_settings(), a.get_logs(0)]);
      setStatus(s);
      setSettings(st);
      setLogs(lg);
      if (s.config_present) {
        setClients(await a.list_clients());
      } else {
        setScreen("setup");
      }
      // Signal Python that the page is ready; the live poll starts only now so
      // events are never dispatched before React has registered its listeners.
      a.notify_ready();
    });
  }, []);

  useBridgeEvent("status", useCallback((d) => {
    setStatus((prev) => ({ ...(prev || {}), ...d }));
  }, []));
  useBridgeEvent("clients", useCallback((d) => setClients(d), []));
  useBridgeEvent("log",     useCallback((e) => setLogs((l) => [...l.slice(-1999), e]), []));
  useBridgeEvent("settings", useCallback((d) => setSettings(d), []));

  // JS-side poll — primary mechanism for live updates. evaluate_js from a
  // Python background thread can be silently dropped on some platform/backend
  // combinations (GTK throttling, window not focused, etc.). Polling from JS
  // via the bridge always works because those calls go JS → Python, not the
  // other way around.
  useEffect(() => {
    if (!api) return;
    let alive = true;
    const tick = async () => {
      if (!alive) return;
      try {
        const [s, cl] = await Promise.all([api.get_status(), api.list_clients()]);
        setStatus((prev) => ({ ...(prev || {}), ...s }));
        setClients(cl);
        pollFailsRef.current = 0;
        if (!bridgeAlive) setBridgeAlive(true);
      } catch (_) {
        pollFailsRef.current += 1;
        if (pollFailsRef.current >= 3 && bridgeAlive) setBridgeAlive(false);
      }
      if (alive) setTimeout(tick, 2000);
    };
    setTimeout(tick, 2000); // initial data already loaded in bootstrap
    return () => { alive = false; };
  }, [api]);

  const T = (settings.language === "en" ? window.SRV_STR.en : window.SRV_STR.es);

  const isDark = settings.theme === "dark" ||
    (settings.theme === "auto" && window.matchMedia?.("(prefers-color-scheme: dark)")?.matches);
  const theme = isDark ? "dark" : "light";

  const onSetting = (k, v) => api?.set_settings({ [k]: v });

  if (!status) {
    const splashT = settings.language === "en" ? window.SRV_STR.en : window.SRV_STR.es;
    return (
      <div data-theme={theme} style={{
        height: "100%", display: "flex", flexDirection: "column",
        alignItems: "center", justifyContent: "center", gap: 14,
        background: "var(--bg)", color: "var(--text-3)", fontSize: 13,
      }}>
        <window.WSLogoMark size={56} color="var(--brand)" accent="var(--brand-2)"/>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, opacity: 0.8 }}>
          {splashT.loading}
        </div>
      </div>
    );
  }

  if (!status.config_present || screen === "setup") {
    return <SetupWizard T={T} api={api} theme={theme} onDone={async () => {
      const s = await api.get_status();
      setStatus(s);
      setClients(await api.list_clients());
      setScreen("dashboard");
    }}/>;
  }

  return (
    <div data-theme={theme} style={{ display: "grid", gridTemplateRows: bridgeAlive ? "1fr" : "auto 1fr", height: "100%", background: "var(--bg)", color: "var(--text)" }}>
      {!bridgeAlive && <div className="ow-bridge-banner">{T.bridgeLost}</div>}
      <div style={{ display: "grid", gridTemplateColumns: "232px 1fr", minHeight: 0 }}>
        <Sidebar T={T} screen={screen} onScreen={setScreen} status={status} advanced={!!settings.advanced}/>
        <main style={{ overflow: "auto", padding: "28px 36px 36px", minWidth: 0 }} className="ws-scroll">
          {screen === "dashboard" && <Dashboard T={T} api={api} status={status} clients={clients} advanced={!!settings.advanced} confirm={confirm}/>}
          {screen === "clients"   && <ClientsScreen T={T} api={api} clients={clients} confirm={confirm}/>}
          {screen === "service"   && <ServiceScreen T={T} api={api} status={status}/>}
          {screen === "logs"      && <LogsScreen T={T} api={api} logs={logs} onClear={() => setLogs([])}/>}
          {screen === "settings"  && <SettingsScreen T={T} settings={settings} onSetting={onSetting} status={status} api={api} confirm={confirm}/>}
          {screen === "about"     && <About T={T} api={api}/>}
        </main>
      </div>
      {confirmDialog}
    </div>
  );
}

// ── Sidebar ────────────────────────────────────────────────────────
const Sidebar = ({ T, screen, onScreen, status, advanced }) => {
  const items = [
    ["dashboard", T.nav_dashboard, "M3 12 L12 3 L21 12 M5 10 V20 H19 V10"],
    ["clients",   T.nav_clients,   "M9 10 a3 3 0 1 0 0 -6 a3 3 0 1 0 0 6 M2 20 c0 -4 3.5 -6 7 -6 s7 2 7 6 M17 11 a2 2 0 1 0 0 -4 a2 2 0 1 0 0 4 M14 20 c0 -3 2 -5 5 -5 s3 1 3 3"],
    ["service",   T.nav_service,   "M4 4 H20 V8 H4 Z M4 16 H20 V20 H4 Z M8 6 H8.01 M8 18 H8.01"],
    ["logs",      T.nav_logs,      "M5 4 H19 V20 H5 Z M8 8 H16 M8 12 H16 M8 16 H13"],
    ["settings",  T.nav_settings,  "M12 9 a3 3 0 1 1 0 6 a3 3 0 1 1 0 -6 M12 2 V4 M12 20 V22 M2 12 H4 M20 12 H22"],
    ["about",     T.nav_about,     "M12 8 V13 M12 16 V16.01 M3 12 a9 9 0 1 1 18 0 a9 9 0 1 1 -18 0"],
  ];
  const tone =
    status.status === "running" ? "good" :
    status.status === "starting" ? "warn" :
    status.status === "error" ? "bad" : "neutral";
  const label =
    status.status === "running" ? T.running :
    status.status === "starting" ? T.starting :
    status.status === "error" ? T.error : T.stopped;

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
          server · dev
        </div>
      )}

      <div style={{ display: "flex", flexDirection: "column", gap: advanced ? 0 : 2 }}>
        {items.map(([id, lbl, d], i) => {
          const active = id === screen;
          return (
            <button key={id} onClick={() => onScreen(id)} className="ow-iconbtn" style={{
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
        <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.serverStatus}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <window.StatusDot tone={tone} pulse={status.status === "running" || status.status === "starting"}/>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{label}</div>
        </div>
        {status.endpoint && (
          <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>
            {status.endpoint}:{status.port}
          </div>
        )}
      </div>
    </aside>
  );
};

// ── Setup wizard ───────────────────────────────────────────────────
const SETUP_PHASES = [
  ["deps",    "setup_phaseDeps"],
  ["cert",    "setup_phaseCert"],
  ["systemd", "setup_phaseService"],
  ["probe",   "setup_phaseProbe"],
  ["done",    "setup_phaseDone"],
];

const CIDR_RE = /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}\/\d{1,2}$/;
const ADDR_RE = /^\d{1,3}\.\d{1,3}\.\d{1,3}\.\d{1,3}(\/\d{1,2})?$/;

const SetupWizard = ({ T, api, theme, onDone }) => {
  const [endpoint, setEndpoint] = useState("");
  const [port, setPort] = useState(443);
  const [wgPort, setWgPort] = useState(51820);
  const [subnet, setSubnet] = useState("10.0.0.0/24");
  const [srvAddr, setSrvAddr] = useState("10.0.0.1/24");
  const [deps, setDeps] = useState(null);
  const [installing, setInstalling] = useState(false);
  const [phaseStates, setPhaseStates] = useState({});
  const [error, setError] = useState("");

  useEffect(() => {
    if (!api) return;
    api.get_deps().then(setDeps);
    api.detect_public_ip().then((r) => { if (r.ip) setEndpoint((e) => e || r.ip); });
  }, [api]);

  useBridgeEvent("setup_progress", useCallback((d) => {
    setPhaseStates((s) => ({ ...s, [d.phase]: { status: d.status, message: d.message } }));
  }, []));

  useBridgeEvent("setup_done", useCallback((d) => {
    if (d.ok) {
      // Give the user a beat to see the "done" tick before navigating away.
      setTimeout(() => onDone(), 600);
    } else {
      setInstalling(false);
      setError(d.error || "");
    }
  }, [onDone]));

  const missing = deps && (!deps.wstunnel || !deps.wg);
  const errors = {
    endpoint: !endpoint.trim() ? T.setup_errEndpoint : "",
    port:     (Number(port)   < 1 || Number(port)   > 65535) ? T.setup_errPort : "",
    wgPort:   (Number(wgPort) < 1 || Number(wgPort) > 65535) ? T.setup_errPort : "",
    subnet:   CIDR_RE.test(subnet) ? "" : T.setup_errSubnet,
    srvAddr:  ADDR_RE.test(srvAddr) ? "" : T.setup_errAddr,
  };
  const valid = Object.values(errors).every((e) => !e);

  const onInstall = async () => {
    setError(""); setPhaseStates({}); setInstalling(true);
    try {
      const r = await api.run_setup({
        endpoint, port: Number(port), wg_listen_port: Number(wgPort),
        subnet, server_address: srvAddr,
      });
      // Result also surfaces via the setup_done event; this is the fallback
      // in case the event arrived before the bridge handler attached.
      if (!r.ok) { setError(r.error); setInstalling(false); }
    } catch (exc) {
      setError(String(exc)); setInstalling(false);
    }
  };

  const onProbeRetry = async () => {
    setPhaseStates((s) => ({ ...s, probe: { status: "running", message: "" } }));
    try {
      const r = await api.probe_external_port();
      setPhaseStates((s) => ({
        ...s,
        probe: {
          status: r.reachable ? "ok" : "warn",
          message: r.detail || "",
        },
      }));
    } catch (exc) {
      setPhaseStates((s) => ({ ...s, probe: { status: "warn", message: String(exc) } }));
    }
  };

  return (
    <div data-theme={theme} style={{ height: "100%", display: "grid", placeItems: "center", padding: 24, background: "var(--bg)" }}>
      <div style={{ width: 560, background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 16, padding: 28, boxShadow: "var(--shadow)" }}>
        <window.WSWordmark size={20} color="var(--text)" accent="var(--brand)"/>
        <div style={{ fontSize: 22, fontWeight: 600, marginTop: 16, letterSpacing: "-0.02em" }}>{T.setup_title}</div>
        <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 4 }}>{T.setup_sub}</div>

        {!installing && (
          <>
            {deps && (
              <div style={{ marginTop: 18, fontFamily: "var(--font-mono)", fontSize: 12 }}>
                <DepLine name="wstunnel" path={deps.wstunnel} notFoundLabel={T.setup_depNotFound}/>
                <DepLine name="wg" path={deps.wg} notFoundLabel={T.setup_depNotFound}/>
              </div>
            )}
            {missing && (
              <div style={{ marginTop: 12, padding: 12, background: "color-mix(in srgb, var(--brand-bad) 12%, transparent)", color: "var(--brand-bad)", borderRadius: 8, fontSize: 12 }}>
                {T.setup_missingDeps}
              </div>
            )}

            <div style={{ marginTop: 22, display: "grid", gap: 10 }}>
              <SetupRow label={T.setup_lblEndpoint} error={errors.endpoint}>
                <input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} style={inputStyle}/>
              </SetupRow>
              <SetupRow label={T.setup_lblPortWSS} error={errors.port}>
                <input value={port} onChange={(e) => setPort(e.target.value)} style={inputStyle}/>
              </SetupRow>
              <SetupRow label={T.setup_lblPortWG} error={errors.wgPort}>
                <input value={wgPort} onChange={(e) => setWgPort(e.target.value)} style={inputStyle}/>
              </SetupRow>
              <SetupRow label={T.setup_lblSubnet} error={errors.subnet}>
                <input value={subnet} onChange={(e) => setSubnet(e.target.value)} style={inputStyle}/>
              </SetupRow>
              <SetupRow label={T.setup_lblSrvAddr} error={errors.srvAddr}>
                <input value={srvAddr} onChange={(e) => setSrvAddr(e.target.value)} style={inputStyle}/>
              </SetupRow>
            </div>

            {error && <div style={{ marginTop: 14, padding: 12, background: "color-mix(in srgb, var(--brand-bad) 12%, transparent)", color: "var(--brand-bad)", borderRadius: 8, fontSize: 12, fontFamily: "var(--font-mono)" }}>{error}</div>}

            <div style={{ marginTop: 18, display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <window.Btn kind="primary" size="md" onClick={onInstall} disabled={missing || !valid}>
                {T.setup_install}
              </window.Btn>
            </div>
          </>
        )}

        {installing && (
          <SetupProgress T={T} phaseStates={phaseStates} onProbeRetry={onProbeRetry} onProbeSkip={() => onDone()} error={error}/>
        )}
      </div>
    </div>
  );
};

const SetupProgress = ({ T, phaseStates, onProbeRetry, onProbeSkip, error }) => {
  // current phase = first one not yet "ok" or "warn"
  const currentIdx = SETUP_PHASES.findIndex(([k]) => {
    const s = phaseStates[k]?.status;
    return s !== "ok" && s !== "warn";
  });
  const done = currentIdx === -1;
  const probeState = phaseStates.probe;

  return (
    <div style={{ marginTop: 20 }}>
      <div style={{ fontSize: 13, color: "var(--text-2)", marginBottom: 14 }}>
        {T.setup_installing}
      </div>
      <ol style={{ listStyle: "none", padding: 0, margin: 0, display: "flex", flexDirection: "column", gap: 12 }}>
        {SETUP_PHASES.map(([key, sk], i) => {
          const explicit = phaseStates[key]?.status;
          const inferred =
            explicit ? explicit
            : done ? "ok"
            : i < currentIdx ? "ok"
            : i === currentIdx ? "running"
            : "pending";
          const msg = phaseStates[key]?.message || "";
          return (
            <li key={key} style={{ display: "grid", gridTemplateColumns: "22px 1fr", gap: 12, alignItems: "flex-start" }}>
              <PhaseIcon status={inferred}/>
              <div>
                <div style={{ fontSize: 13, fontWeight: inferred === "running" ? 600 : 500, color: inferred === "pending" ? "var(--text-3)" : "var(--text)" }}>
                  {T[sk]}
                </div>
                {msg && (
                  <div style={{ fontSize: 11, color: inferred === "fail" ? "var(--brand-bad)" : inferred === "warn" ? "var(--brand-warn)" : "var(--text-3)", marginTop: 2, fontFamily: "var(--font-mono)", wordBreak: "break-word" }}>
                    {msg}
                  </div>
                )}
              </div>
            </li>
          );
        })}
      </ol>

      {probeState && probeState.status === "warn" && (
        <div style={{ marginTop: 16, padding: 12, background: "color-mix(in srgb, var(--brand-warn) 12%, transparent)", color: "var(--brand-warn)", borderRadius: 8, fontSize: 12, display: "flex", justifyContent: "space-between", alignItems: "center", gap: 12, flexWrap: "wrap" }}>
          <div style={{ fontFamily: "var(--font-mono)", flex: 1, minWidth: 0 }}>{probeState.message || "external probe failed"}</div>
          <div style={{ display: "flex", gap: 6 }}>
            <window.Btn kind="ghost" size="sm" onClick={onProbeRetry}>{T.setup_probeRetry}</window.Btn>
            <window.Btn kind="ghost" size="sm" onClick={onProbeSkip}>{T.setup_probeSkip}</window.Btn>
          </div>
        </div>
      )}

      {error && (
        <div style={{ marginTop: 16, padding: 12, background: "color-mix(in srgb, var(--brand-bad) 12%, transparent)", color: "var(--brand-bad)", borderRadius: 8, fontSize: 12, fontFamily: "var(--font-mono)" }}>
          {error}
        </div>
      )}
    </div>
  );
};

const PhaseIcon = ({ status }) => {
  if (status === "ok") return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--brand-2)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" fill="color-mix(in srgb, var(--brand-2) 12%, transparent)" stroke="none"/>
      <path d="M7 12 L11 16 L17 9"/>
    </svg>
  );
  if (status === "warn") return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--brand-warn)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" fill="color-mix(in srgb, var(--brand-warn) 14%, transparent)" stroke="none"/>
      <path d="M12 8 V13 M12 16 V16.01"/>
    </svg>
  );
  if (status === "fail") return (
    <svg width="22" height="22" viewBox="0 0 24 24" fill="none" stroke="var(--brand-bad)" strokeWidth="2.4" strokeLinecap="round" strokeLinejoin="round">
      <circle cx="12" cy="12" r="10" fill="color-mix(in srgb, var(--brand-bad) 14%, transparent)" stroke="none"/>
      <path d="M8 8 L16 16 M16 8 L8 16"/>
    </svg>
  );
  if (status === "running") return (
    <span style={{ position: "relative", display: "inline-block", width: 22, height: 22 }}>
      <span style={{ position: "absolute", inset: 0, borderRadius: 999, border: "2px solid var(--brand-warn)", borderTopColor: "transparent", animation: "ws-spin 0.9s linear infinite" }}/>
    </span>
  );
  return (
    <svg width="22" height="22" viewBox="0 0 24 24">
      <circle cx="12" cy="12" r="10" fill="none" stroke="var(--line-strong)" strokeWidth="1.5"/>
    </svg>
  );
};

const DepLine = ({ name, path, notFoundLabel }) => (
  <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}>
    <span style={{ color: path ? "var(--brand-2)" : "var(--brand-bad)" }}>{path ? "✓" : "✗"}</span>
    <span style={{ color: "var(--text-2)" }}>{name}:</span>
    <span style={{ color: path ? "var(--text)" : "var(--text-3)" }}>{path || notFoundLabel}</span>
  </div>
);
const SetupRow = ({ label, error, children }) => (
  <label style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, alignItems: "center" }}>
    <span style={{ fontSize: 12, color: "var(--text-2)" }}>{label}</span>
    <div>
      {children}
      {error && (
        <div style={{ marginTop: 4, fontSize: 11, color: "var(--brand-bad)", fontFamily: "var(--font-mono)" }}>{error}</div>
      )}
    </div>
  </label>
);
const inputStyle = {
  height: 30, padding: "0 10px", borderRadius: 8,
  border: "1px solid var(--line-strong)", background: "var(--bg)", color: "var(--text)",
  fontFamily: "var(--font-mono)", fontSize: 12, outline: "none",
};

// ── Dashboard ──────────────────────────────────────────────────────
const Dashboard = ({ T, api, status, clients, advanced, confirm }) => {
  const online = clients.filter((c) => c.status === "online").length;
  const totalRx = clients.reduce((acc, c) => acc + (c.rx_bytes || 0), 0);
  const totalTx = clients.reduce((acc, c) => acc + (c.tx_bytes || 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Header title={T.nav_dashboard} sub={`${status.endpoint}:${status.port} · ${status.subnet}`}/>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <Metric label={T.metric_clientsOnline} value={`${online}/${clients.length}`}/>
        <Metric label={T.metric_traffic}        value={fmtBytes(totalRx + totalTx)} sub={`↓ ${fmtBytes(totalRx)} · ↑ ${fmtBytes(totalTx)}`}/>
        <Metric label={T.dash_subnet}           value={status.subnet}/>
        <Metric label={T.dash_wgPort}           value={String(status.wg_listen_port)}/>
      </div>
      <ClientsTable T={T} clients={clients} api={api} compact confirm={confirm}/>
      {advanced && (
        <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18, fontFamily: "var(--font-mono)", fontSize: 12 }}>
          <div style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 10, fontFamily: "var(--font-sans)", fontWeight: 600 }}>{T.dash_techDetails}</div>
          <KV k={T.dash_endpoint} v={`${status.endpoint}:${status.port}`}/>
          <KV k={T.dash_wgAddr} v={status.server_address}/>
          <KV k={T.dash_wgPort} v={String(status.wg_listen_port)}/>
          <KV k={T.dash_subnet} v={status.subnet}/>
          <KV k={T.dash_tlsFingerprint} v={status.cert_fingerprint_sha256} last/>
        </section>
      )}
    </div>
  );
};

const Metric = ({ label, value, sub }) => (
  <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 12, padding: 14 }}>
    <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>{label}</div>
    <div style={{ fontSize: 22, fontWeight: 600, marginTop: 6, fontFamily: "var(--font-mono)" }}>{value}</div>
    {sub && <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>{sub}</div>}
  </div>
);

const KV = ({ k, v, last }) => (
  <div style={{ display: "grid", gridTemplateColumns: "160px 1fr", gap: 12, padding: "8px 0", borderBottom: last ? "none" : "1px dashed var(--line)" }}>
    <div style={{ color: "var(--text-3)" }}>{k}</div>
    <div style={{ color: "var(--text)", wordBreak: "break-all" }}>{v}</div>
  </div>
);

const Header = ({ title, sub }) => (
  <header>
    <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{title}</div>
    {sub && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2, fontFamily: "var(--font-mono)" }}>{sub}</div>}
  </header>
);

// ── Clients ────────────────────────────────────────────────────────
const ClientsScreen = ({ T, api, clients, confirm }) => {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastAdded, setLastAdded] = useState(null);
  const [savedTo, setSavedTo] = useState("");
  const [selected, setSelected] = useState(null);
  const [sortKey, setSortKey] = useState("name");
  const [sortDir, setSortDir] = useState("asc");
  const [filter, setFilter] = useState("");

  const onAdd = async () => {
    if (!name.trim() || !api) return;
    setBusy(true); setError(""); setSavedTo("");
    try {
      const r = await api.add_client(name.trim());
      if (r.ok) {
        setName("");
        setLastAdded(r);
      } else {
        setError(r.error);
      }
    } finally { setBusy(false); }
  };

  const onDownload = async () => {
    if (!lastAdded || !api) return;
    setError(""); setSavedTo("");
    const r = await api.save_owcfg(lastAdded.name, lastAdded.owcfg_base64);
    if (r.ok) {
      setSavedTo(r.path);
    } else if (r.error !== "cancelled") {
      setError(r.error || T.clients_saveFailed);
    }
  };

  // Selected client may have been revoked elsewhere; auto-close the drawer.
  useEffect(() => {
    if (selected && !clients.some((c) => c.name === selected)) setSelected(null);
  }, [clients, selected]);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <Header title={T.nav_clients}/>
      <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{T.addClient_title}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 14 }}>{T.addClient_sub}</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8 }}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={T.addClient_namePh} style={{ ...inputStyle, height: 36, fontFamily: "var(--font-sans)", fontSize: 13 }}/>
          <window.Btn kind="primary" size="md" onClick={onAdd} disabled={busy || !name.trim()}>{busy ? T.clients_generating : T.addClient_generate}</window.Btn>
        </div>
        {error && <div style={{ marginTop: 10, fontSize: 12, color: "var(--brand-bad)" }}>{error}</div>}
        {lastAdded && (
          <div style={{ marginTop: 14, padding: 12, background: "var(--bg-sunk)", border: "1px solid var(--line)", borderRadius: 10, display: "flex", alignItems: "center", justifyContent: "space-between", gap: 10 }}>
            <div style={{ fontSize: 13 }}>
              <strong>{lastAdded.name}</strong> · <span style={{ fontFamily: "var(--font-mono)", color: "var(--text-3)" }}>{lastAdded.path}</span>
            </div>
            <window.Btn kind="primary" size="sm" onClick={onDownload}>{T.download}</window.Btn>
          </div>
        )}
        {savedTo && (
          <div style={{ marginTop: 10, fontSize: 12, color: "var(--brand-2)", fontFamily: "var(--font-mono)" }}>
            {T.clients_savedTo.replace("{path}", savedTo)}
          </div>
        )}
      </section>

      <div style={{ display: "flex", gap: 8, alignItems: "center", justifyContent: "flex-end" }}>
        <input
          value={filter}
          onChange={(e) => setFilter(e.target.value)}
          placeholder={T.logs_filter}
          style={{ ...inputStyle, height: 30, width: 220 }}
        />
      </div>

      <ClientsTable
        T={T} clients={clients} api={api} confirm={confirm}
        onRowClick={(n) => setSelected(n)}
        sortKey={sortKey} sortDir={sortDir}
        onSort={(k) => {
          if (k === sortKey) setSortDir((d) => d === "asc" ? "desc" : "asc");
          else { setSortKey(k); setSortDir("asc"); }
        }}
        filter={filter}
      />

      {selected && (
        <ClientDetailDrawer
          T={T} api={api} name={selected} confirm={confirm}
          onClose={() => setSelected(null)}
        />
      )}
    </div>
  );
};

const SORT_FNS = {
  name:    (a, b) => a.name.localeCompare(b.name),
  address: (a, b) => a.address.localeCompare(b.address, undefined, { numeric: true }),
  status:  (a, b) => (a.status || "").localeCompare(b.status || ""),
  hs:      (a, b) => (a.last_handshake_seconds_ago ?? 1e12) - (b.last_handshake_seconds_ago ?? 1e12),
  xfer:    (a, b) => ((a.rx_bytes || 0) + (a.tx_bytes || 0)) - ((b.rx_bytes || 0) + (b.tx_bytes || 0)),
};

const ClientsTable = ({ T, clients, api, compact, confirm, onRowClick, sortKey, sortDir, onSort, filter }) => {
  const onRevoke = async (name) => {
    const ok = confirm
      ? await confirm({
          title: T.revoke,
          message: T.revokeConfirm.replace("{name}", name),
          confirmLabel: T.revoke,
          cancelLabel: T.cancel,
          danger: true,
        })
      : window.confirm(T.revokeConfirm.replace("{name}", name));
    if (!ok) return;
    await api?.revoke_client(name);
  };

  let rows = clients;
  if (filter) {
    const q = filter.toLowerCase();
    rows = rows.filter((c) => c.name.toLowerCase().includes(q) || (c.address || "").includes(q));
  }
  if (sortKey && SORT_FNS[sortKey]) {
    rows = [...rows].sort(SORT_FNS[sortKey]);
    if (sortDir === "desc") rows.reverse();
  }

  const colArrow = (k) => sortKey === k ? (sortDir === "asc" ? " ↑" : " ↓") : "";
  const sortable = onSort && !compact;
  const headerBtn = (label, k) => sortable ? (
    <button onClick={() => onSort(k)} className="ow-iconbtn" style={{
      all: "unset", cursor: "pointer", fontSize: 11, fontWeight: 600,
      color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em",
    }}>{label}{colArrow(k)}</button>
  ) : <span>{label}</span>;

  return (
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead style={{ background: "var(--bg-sunk)" }}>
          <tr>
            <Th>{headerBtn(T.clientName, "name")}</Th>
            <Th>{headerBtn(T.ipAssigned, "address")}</Th>
            <Th>{headerBtn(T.clients_colStatus, "status")}</Th>
            <Th>{headerBtn(T.lastHandshake, "hs")}</Th>
            <Th>{headerBtn(T.transferred, "xfer")}</Th>
            {!compact && <Th>{T.clients_colEndpoint}</Th>}
            <Th/>
          </tr>
        </thead>
        <tbody>
          {rows.length === 0 && (
            <tr><td colSpan={compact ? 6 : 7} style={{ textAlign: "center", padding: 24, color: "var(--text-3)", fontSize: 13 }}>
              <div style={{ display: "flex", flexDirection: "column", alignItems: "center", gap: 10 }}>
                <svg width="32" height="32" viewBox="0 0 24 24" fill="none"
                     stroke="var(--text-3)" strokeWidth="1.4" strokeLinecap="round" strokeLinejoin="round" opacity="0.6">
                  <circle cx="12" cy="8" r="4"/>
                  <path d="M4 21 c0 -4 4 -7 8 -7 s8 3 8 7"/>
                </svg>
                <div>
                  {T.clients_empty.split("{add}").map((part, i, arr) => (
                    <React.Fragment key={i}>
                      {part}
                      {i < arr.length - 1 && <strong>{T.addClient}</strong>}
                    </React.Fragment>
                  ))}
                </div>
              </div>
            </td></tr>
          )}
          {rows.map((c) => (
            <tr key={c.name}
                onClick={onRowClick ? () => onRowClick(c.name) : undefined}
                style={{
                  borderTop: "1px solid var(--line)",
                  cursor: onRowClick ? "pointer" : "default",
                }}>
              <Td><strong>{c.name}</strong></Td>
              <Td mono>{c.address}</Td>
              <Td>
                <window.Pill tone={c.status === "online" ? "good" : c.status === "offline" ? "warn" : "neutral"}>
                  {c.status === "online" ? T.online : c.status === "offline" ? T.offline : c.status}
                </window.Pill>
              </Td>
              <Td mono>{fmtAge(c.last_handshake_seconds_ago)}</Td>
              <Td mono>↓ {fmtBytes(c.rx_bytes)} · ↑ {fmtBytes(c.tx_bytes)}</Td>
              {!compact && <Td mono>{c.endpoint || "—"}</Td>}
              <Td>
                <window.Btn
                  kind="danger" size="sm"
                  onClick={(e) => { e.stopPropagation(); onRevoke(c.name); }}>
                  {T.revoke}
                </window.Btn>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
  );
};

const ClientDetailDrawer = ({ T, api, name, onClose, confirm }) => {
  const [info, setInfo] = useState(null);
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");

  useEffect(() => {
    if (!api || !name) return;
    api.get_client(name).then((r) => {
      if (r.ok) setInfo(r);
      else setErr(r.error || "");
    });
  }, [api, name]);

  // Esc closes
  useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onClose(); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onClose]);

  const handleResult = async (r) => {
    if (!r.ok) { setErr(r.error || ""); return; }
    setErr("");
    const save = await api.save_owcfg(name, r.owcfg_base64);
    if (save.ok) setMsg(T.clients_savedTo.replace("{path}", save.path));
    else if (save.error !== "cancelled") setErr(save.error || T.clients_saveFailed);
  };

  const onRegenerate = async () => {
    const ok = await confirm({
      title: T.clientDetail_regenOwcfg,
      message: T.clientDetail_rotateConfirm,
      confirmLabel: T.clientDetail_regenOwcfg,
      cancelLabel: T.cancel,
      danger: true,
    });
    if (!ok) return;
    setBusy(true); setMsg("");
    try {
      const r = await api.regenerate_owcfg(name);
      await handleResult(r);
    } finally { setBusy(false); }
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
    setBusy(true); setMsg("");
    try {
      const r = await api.rotate_client_keys(name);
      await handleResult(r);
    } finally { setBusy(false); }
  };

  const onRevoke = async () => {
    const ok = await confirm({
      title: T.revoke,
      message: T.revokeConfirm.replace("{name}", name),
      confirmLabel: T.revoke,
      cancelLabel: T.cancel,
      danger: true,
    });
    if (!ok) return;
    await api.revoke_client(name);
    onClose();
  };

  return (
    <aside className="ow-drawer">
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 20px", borderBottom: "1px solid var(--line)" }}>
        <div style={{ fontSize: 16, fontWeight: 600 }}>{name}</div>
        <button onClick={onClose} className="ow-link">{T.close}</button>
      </header>
      {info ? (
        <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 14 }}>
          <KV k={T.ipAssigned}              v={info.address}/>
          <KV k={T.clientDetail_pubkey}      v={info.public_key} mono/>
          <KV k={T.lastHandshake}            v={fmtAge(info.last_handshake_seconds_ago)}/>
          <KV k={T.transferred}              v={`↓ ${fmtBytes(info.rx_bytes)} · ↑ ${fmtBytes(info.tx_bytes)}`}/>
          <KV k={T.clients_colEndpoint}      v={info.endpoint || "—"} mono/>
          <KV k={T.clientDetail_allowed}     v={(info.allowed_ips && info.allowed_ips.join(", ")) || "—"} mono last/>

          <div style={{ display: "flex", gap: 8, flexWrap: "wrap", marginTop: 8 }}>
            <window.Btn kind="primary" size="md" onClick={onRegenerate} disabled={busy}>
              {T.clientDetail_regenOwcfg}
            </window.Btn>
            <window.Btn kind="ghost" size="md" onClick={onRotate} disabled={busy}>
              {T.clientDetail_rotate}
            </window.Btn>
            <window.Btn kind="danger" size="md" onClick={onRevoke} disabled={busy}>
              {T.revoke}
            </window.Btn>
          </div>
          {msg && <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-2)" }}>{msg}</div>}
          {err && <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-bad)" }}>{err}</div>}
        </div>
      ) : err ? (
        <div style={{ padding: 20, color: "var(--brand-bad)", fontSize: 13 }}>{err}</div>
      ) : (
        <div style={{ padding: 20, color: "var(--text-3)" }}>{T.loading}</div>
      )}
    </aside>
  );
};

const Th = ({ children }) => <th style={{ textAlign: "left", padding: "10px 14px", fontSize: 11, fontWeight: 600, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em" }}>{children}</th>;
const Td = ({ children, mono }) => <td style={{ padding: "10px 14px", color: "var(--text)", fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)", fontSize: mono ? 12 : 13 }}>{children}</td>;

// ── Service ────────────────────────────────────────────────────────
const ServiceScreen = ({ T, api, status }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
    <Header title={T.nav_service} sub={`${status.endpoint}:${status.port}`}/>
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 14 }}>{T.serverStatus}</div>
      <div style={{ display: "flex", alignItems: "center", gap: 12 }}>
        <window.StatusDot tone={status.status === "running" ? "good" : status.status === "starting" ? "warn" : "bad"} pulse={status.status !== "stopped"}/>
        <span style={{ fontSize: 16, fontWeight: 600 }}>
          {status.status === "running" ? T.running : status.status === "starting" ? T.service_starting : status.status === "error" ? T.service_error : T.stopped}
        </span>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
        <window.Btn kind="primary" size="md" onClick={() => api?.start_service()}>{T.service_start}</window.Btn>
        <window.Btn kind="ghost"   size="md" onClick={() => api?.stop_service()}>{T.service_stop}</window.Btn>
        <window.Btn kind="ghost"   size="md" onClick={() => api?.restart_service()}>{T.service_restart}</window.Btn>
      </div>
    </section>
  </div>
);

// ── Logs ───────────────────────────────────────────────────────────
const LogsScreen = ({ T, api, logs, onClear }) => {
  const ref = useRef(null);
  const [filter, setFilter] = useState("");
  const [level, setLevel] = useState("all");
  const [atBottom, setAtBottom] = useState(true);
  const atBottomRef = useRef(true);
  const [exportMsg, setExportMsg] = useState("");

  useEffect(() => {
    if (ref.current && atBottomRef.current) ref.current.scrollTop = ref.current.scrollHeight;
  }, [logs.length]);

  const onScroll = () => {
    const el = ref.current;
    if (!el) return;
    const isBottom = el.scrollHeight - el.scrollTop - el.clientHeight < 24;
    atBottomRef.current = isBottom;
    setAtBottom(isBottom);
  };

  const doExport = async () => {
    if (!api) return;
    setExportMsg("");
    try {
      const r = await api.export_logs();
      if (r && r.ok) {
        setExportMsg(T.logs_exported);
        setTimeout(() => setExportMsg(""), 3000);
      } else if (r && r.error && r.error !== "cancelled") {
        // Show why the dialog didn't open / write didn't succeed — silent
        // failure here is what made this look like "the button does nothing".
        setExportMsg("✗ " + r.error);
        setTimeout(() => setExportMsg(""), 6000);
      }
    } catch (exc) {
      // export_logs not exposed by the bridge (stale build / missing method)
      // surfaces as a JS-side exception. Make it visible instead of silent.
      console.error("export_logs failed:", exc);
      setExportMsg("✗ " + String(exc));
      setTimeout(() => setExportMsg(""), 6000);
    }
  };

  const doClear = async () => {
    onClear();
    try { await api?.clear_logs(); } catch (_) {}
  };

  const filtered = logs.filter((l) =>
    (level === "all" || l.level === level) &&
    (!filter || l.msg.toLowerCase().includes(filter.toLowerCase()))
  );

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%", position: "relative" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", flexWrap: "wrap", gap: 10 }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.logs_title}</div>
          <div style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{T.logs_sub}</div>
        </div>
        <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
          <select value={level} onChange={(e) => setLevel(e.target.value)} style={{ ...inputStyle, height: 30 }}>
            <option value="all">{T.logs_levelAll}</option>
            <option value="info">INFO</option>
            <option value="warn">WARN</option>
            <option value="error">ERROR</option>
            <option value="debug">DEBUG</option>
          </select>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder={T.logs_filter} style={{ ...inputStyle, width: 220 }}/>
          <window.Btn kind="ghost" size="sm" onClick={doExport}>{T.logs_export}</window.Btn>
          <window.Btn kind="ghost" size="sm" onClick={doClear}>{T.logs_clear}</window.Btn>
        </div>
      </header>
      {exportMsg && (
        <div style={{
          fontSize: 12,
          color: exportMsg.startsWith("✗") ? "var(--brand-bad)" : "var(--brand-2)",
          fontFamily: "var(--font-mono)",
          wordBreak: "break-word",
        }}>{exportMsg}</div>
      )}
      <div ref={ref} onScroll={onScroll} style={{
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
        {filtered.length === 0 && <div style={{ opacity: .5 }}>{T.logs_empty}</div>}
      </div>
      {!atBottom && (
        <button
          onClick={() => {
            if (ref.current) {
              ref.current.scrollTop = ref.current.scrollHeight;
              atBottomRef.current = true;
              setAtBottom(true);
            }
          }}
          style={{
            position: "absolute", right: 16, bottom: 16,
            padding: "6px 12px", borderRadius: 999,
            background: "var(--brand)", color: "#fff",
            fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer",
            boxShadow: "0 6px 18px -6px color-mix(in srgb, var(--brand) 60%, transparent)",
          }}>
          ↓ {T.logs_jumpBottom}
        </button>
      )}
    </section>
  );
};

// ── Doctor (diagnostics panel embedded in Settings) ────────────────
//
// Runs the same battery as `outwarp-server doctor` and renders a table of
// pass/warn/fail rows. Each row with a remediation gets a copyable command
// block — the user is meant to paste those into an elevated PowerShell.
const DoctorPanel = ({ T, api }) => {
  const [running, setRunning] = useState(false);
  const [report, setReport] = useState(null);
  const [lastRunTs, setLastRunTs] = useState(null);
  const [copiedIdx, setCopiedIdx] = useState(null);

  const run = useCallback(async () => {
    if (!api || running) return;
    setRunning(true);
    try {
      const r = await api.run_diagnostics();
      setReport(r);
      setLastRunTs(Date.now());
    } finally {
      setRunning(false);
    }
  }, [api, running]);

  const onCopy = async (text, idx) => {
    try {
      await navigator.clipboard.writeText(text);
      setCopiedIdx(idx);
      setTimeout(() => setCopiedIdx((c) => (c === idx ? null : c)), 1500);
    } catch (_) {
      // Clipboard API can be blocked in pywebview on some platforms.
      // The text remains visible on screen; user can select + copy manually.
    }
  };

  const summaryTone = !report
    ? "neutral"
    : report.summary.fail > 0
    ? "bad"
    : report.summary.warn > 0
    ? "warn"
    : "good";
  const summaryText = !report
    ? T.doctor_neverRun
    : report.summary.fail > 0
    ? T.doctor_someFail
    : report.summary.warn > 0
    ? T.doctor_someWarn
    : T.doctor_allGood;

  const lastRunLabel = lastRunTs
    ? new Date(lastRunTs).toLocaleTimeString([], { hour: "2-digit", minute: "2-digit", second: "2-digit" })
    : null;

  const statusIcons = {
    pass: { ch: "✓", color: "var(--brand-2)" },
    warn: { ch: "⚠", color: "var(--brand-warn)" },
    fail: { ch: "✗", color: "var(--brand-bad)" },
    skip: { ch: "—", color: "var(--text-3)" },
  };

  return (
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start", gap: 16 }}>
        <div>
          <div style={{ fontSize: 14, fontWeight: 600 }}>{T.doctor_title}</div>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{T.doctor_sub}</div>
        </div>
        <window.Btn kind="primary" size="md" onClick={run} disabled={running || !api}>
          {running ? T.doctor_running : T.doctor_run}
        </window.Btn>
      </div>

      <div style={{ display: "flex", alignItems: "center", gap: 10, marginTop: 14 }}>
        <window.StatusDot tone={summaryTone} pulse={running}/>
        <span style={{ fontSize: 13, fontWeight: 500 }}>{summaryText}</span>
        {report && (
          <span style={{ fontSize: 12, color: "var(--text-3)", marginLeft: 8, fontFamily: "var(--font-mono)" }}>
            ✓ {report.summary.pass} · ⚠ {report.summary.warn} · ✗ {report.summary.fail}
          </span>
        )}
        {lastRunLabel && (
          <span style={{ marginLeft: "auto", fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>
            {T.doctor_lastRun}: {lastRunLabel}
          </span>
        )}
      </div>

      {report && report.error && (
        <div style={{ marginTop: 14, padding: 12, background: "color-mix(in srgb, var(--brand-bad) 12%, transparent)", color: "var(--brand-bad)", borderRadius: 8, fontSize: 12 }}>
          {report.error}
        </div>
      )}

      {report && report.checks.length > 0 && (
        <div style={{ marginTop: 14, border: "1px solid var(--line)", borderRadius: 10, overflow: "hidden" }}>
          {report.checks.map((c, i) => {
            const ic = statusIcons[c.status] || statusIcons.skip;
            return (
              <div key={i} style={{
                display: "grid",
                gridTemplateColumns: "28px 1fr",
                gap: 10,
                padding: "10px 14px",
                borderTop: i === 0 ? "none" : "1px solid var(--line)",
                background: c.status === "fail" ? "color-mix(in srgb, var(--brand-bad) 5%, transparent)"
                          : c.status === "warn" ? "color-mix(in srgb, var(--brand-warn) 5%, transparent)"
                          : "transparent",
              }}>
                <div style={{ fontSize: 14, fontWeight: 700, color: ic.color, lineHeight: "20px" }}>{ic.ch}</div>
                <div>
                  <div style={{ fontSize: 13, fontWeight: 500, color: "var(--text)" }}>{c.name}</div>
                  {c.detail && (
                    <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2, fontFamily: "var(--font-mono)", wordBreak: "break-word" }}>
                      {c.detail}
                    </div>
                  )}
                  {c.remediation && (
                    <div style={{
                      marginTop: 8, padding: "8px 10px",
                      background: "var(--bg-sunk)", border: "1px solid var(--line)", borderRadius: 8,
                    }}>
                      <div style={{ fontSize: 12, color: "var(--text-2)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                        {c.remediation}
                      </div>
                      {c.remediation_command && (
                        <div style={{
                          marginTop: 8,
                          display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "stretch",
                          background: "var(--bg)", border: "1px solid var(--line-strong)", borderRadius: 6,
                          padding: "6px 8px",
                        }}>
                          <code style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                            {c.remediation_command}
                          </code>
                          <button onClick={() => onCopy(c.remediation_command, i)} style={{
                            all: "unset", cursor: "pointer", padding: "2px 10px", borderRadius: 4,
                            fontSize: 11, fontWeight: 600, color: "var(--text-2)",
                            border: "1px solid var(--line-strong)", background: "var(--bg-2)",
                            alignSelf: "center",
                          }}>
                            {copiedIdx === i ? T.doctor_copied : T.doctor_copy}
                          </button>
                        </div>
                      )}
                    </div>
                  )}
                </div>
              </div>
            );
          })}
        </div>
      )}
    </section>
  );
};

// ── CLI activation toggle (Windows only) ───────────────────────────
// Mirrors the installer concept: the console CLI ships dormant; flipping this
// adds {app}\server to the user PATH so `outwarp-server` works in a terminal.
const CliToggleRow = ({ T, api }) => {
  const [st, setSt] = useState(null);
  const [busy, setBusy] = useState(false);
  useEffect(() => {
    let alive = true;
    api?.get_cli_status?.().then((s) => { if (alive) setSt(s); });
    return () => { alive = false; };
  }, [api]);
  if (!st || !st.supported) return null;
  const toggle = async (v) => {
    if (busy || !st.available || !api) return;
    setBusy(true);
    try {
      const r = await api.set_cli_enabled(v);
      if (r && r.ok) setSt((s) => ({ ...s, enabled: v }));
    } finally { setBusy(false); }
  };
  const sub = st.available ? T.set_cliSub : T.set_cliUnavailable;
  return (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 16, alignItems: "center", padding: "14px 0", borderBottom: "1px solid var(--line)" }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{T.set_cli}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{sub}</div>
      </div>
      <div style={{ opacity: st.available && !busy ? 1 : 0.45, pointerEvents: st.available && !busy ? "auto" : "none" }}>
        <window.Toggle on={!!st.enabled} onChange={toggle}/>
      </div>
    </div>
  );
};

// ── Settings ───────────────────────────────────────────────────────
const SettingsScreen = ({ T, settings, onSetting, status, api, confirm }) => {
  const Row = ({ title, sub, control }) => (
    <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 16, alignItems: "center", padding: "14px 0", borderBottom: "1px solid var(--line)" }}>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{title}</div>
        {sub && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
      </div>
      <div>{control}</div>
    </div>
  );
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 760 }}>
      <Header title={T.nav_settings} sub="outwarp-server-gui"/>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: "0 18px" }}>
        <Row title={T.set_language} control={<select value={settings.language} onChange={(e) => onSetting("language", e.target.value)} style={inputStyle}>
          <option value="es">Español</option><option value="en">English</option>
        </select>}/>
        <Row title={T.set_theme} control={<select value={settings.theme} onChange={(e) => onSetting("theme", e.target.value)} style={inputStyle}>
          <option value="auto">{T.set_themeAuto}</option><option value="light">{T.set_themeLight}</option><option value="dark">{T.set_themeDark}</option>
        </select>}/>
        <Row title={T.set_advanced} sub={T.set_advancedSub} control={<window.Toggle on={!!settings.advanced} onChange={(v) => onSetting("advanced", v)}/>}/>
        <CliToggleRow T={T} api={api}/>
      </div>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: "0 18px" }}>
        <Row title={T.dash_subnet} control={<span style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}>{status.subnet}</span>}/>
        <Row title={T.set_cert} sub={T.set_certSub} control={<span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)", maxWidth: 320, display: "inline-block", textAlign: "right", wordBreak: "break-all" }}>{status.cert_fingerprint_sha256}</span>}/>
      </div>
      <DoctorPanel T={T} api={api}/>
      <ServerConfigEditor T={T} api={api} status={status} confirm={confirm}/>
    </section>
  );
};

// ── Server config editor ───────────────────────────────────────────
const ServerConfigEditor = ({ T, api, status, confirm }) => {
  const [form, setForm] = useState({
    port: status.port,
    wg_listen_port: status.wg_listen_port,
    endpoint: status.endpoint,
  });
  const [busy, setBusy] = useState(false);
  const [msg, setMsg] = useState("");
  const [err, setErr] = useState("");
  const [probe, setProbe] = useState(null);

  // If the status snapshot changes (e.g. after a successful apply), reseed the form.
  useEffect(() => {
    setForm({ port: status.port, wg_listen_port: status.wg_listen_port, endpoint: status.endpoint });
  }, [status.port, status.wg_listen_port, status.endpoint]);

  const dirty =
    Number(form.port) !== status.port ||
    Number(form.wg_listen_port) !== status.wg_listen_port ||
    String(form.endpoint || "") !== String(status.endpoint || "");

  const save = async () => {
    if (!confirm || !api) return;
    const ok = await confirm({
      title: T.srvCfg_applyTitle,
      message: T.srvCfg_applyConfirm,
      confirmLabel: T.srvCfg_apply,
      cancelLabel: T.cancel,
    });
    if (!ok) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await api.update_server_config({
        port: Number(form.port),
        wg_listen_port: Number(form.wg_listen_port),
        endpoint: form.endpoint,
      });
      if (r.ok) setMsg(T.srvCfg_applied);
      else setErr(r.error || "");
    } finally { setBusy(false); }
  };

  const rotate = async () => {
    if (!confirm || !api) return;
    const ok = await confirm({
      title: T.srvCfg_rotateTitle,
      message: T.srvCfg_rotateConfirm,
      confirmLabel: T.srvCfg_rotate,
      cancelLabel: T.cancel,
      danger: true,
    });
    if (!ok) return;
    setBusy(true); setErr(""); setMsg("");
    try {
      const r = await api.rotate_tls_cert();
      if (r.ok) setMsg(T.srvCfg_rotated.replace("{fp}", r.fingerprint));
      else setErr(r.error || "");
    } finally { setBusy(false); }
  };

  const runProbe = async () => {
    if (!api) return;
    setProbe({ status: "running" });
    try {
      const r = await api.probe_external_port();
      setProbe({ status: r.reachable ? "ok" : "warn", detail: r.detail || "" });
    } catch (exc) {
      setProbe({ status: "warn", detail: String(exc) });
    }
  };

  return (
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
      <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{T.srvCfg_title}</div>
      <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 14 }}>{T.srvCfg_sub}</div>

      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
        <Field label={T.set_port} value={form.port}
               onChange={(v) => setForm((f) => ({ ...f, port: v }))}/>
        <Field label={T.dash_wgPort} value={form.wg_listen_port}
               onChange={(v) => setForm((f) => ({ ...f, wg_listen_port: v }))}/>
        <div style={{ gridColumn: "1 / -1" }}>
          <Field label={T.dash_endpoint} value={form.endpoint} mono
                 onChange={(v) => setForm((f) => ({ ...f, endpoint: v }))}/>
        </div>
      </div>

      <div style={{ marginTop: 14, display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>
        <window.Btn kind="primary" size="md" onClick={save} disabled={!dirty || busy}>
          {T.srvCfg_apply}
        </window.Btn>
        <window.Btn kind="ghost" size="md" onClick={runProbe} disabled={busy}>
          {T.srvCfg_probePort}
        </window.Btn>
        {probe && probe.status === "running" && (
          <span style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>…</span>
        )}
        {probe && probe.status === "ok" && (
          <span style={{ fontSize: 12, color: "var(--brand-2)", fontFamily: "var(--font-mono)" }}>{T.srvCfg_probeOk}</span>
        )}
        {probe && probe.status === "warn" && (
          <span style={{ fontSize: 12, color: "var(--brand-warn)", fontFamily: "var(--font-mono)" }}>
            {T.srvCfg_probeFail.replace("{detail}", probe.detail || "")}
          </span>
        )}
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

// ── About ──────────────────────────────────────────────────────────
const About = ({ T, api }) => {
  const [info, setInfo] = useState(null);
  useEffect(() => { api?.get_app_info().then(setInfo); }, [api]);
  if (!info) return null;

  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 24, maxWidth: 720 }}>
      <Header title={T.nav_about} sub={T.about_sub}/>

      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 24 }}>
        <window.WSWordmark size={22} color="var(--text)" accent="var(--brand)"/>
        <div style={{ marginTop: 16, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-3)" }}>
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
        <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", margin: "0 4px 8px" }}>
          {T.about_thirdParty}
        </div>
        <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, overflow: "hidden" }}>
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

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
