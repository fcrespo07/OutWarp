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
      } catch (_) {}
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
    return (
      <div data-theme={theme} style={{ height: "100%", display: "grid", placeItems: "center", background: "var(--bg)", color: "var(--text-3)", fontSize: 13 }}>
        cargando…
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
    <div data-theme={theme} style={{ display: "grid", gridTemplateColumns: "232px 1fr", height: "100%", background: "var(--bg)", color: "var(--text)" }}>
      <Sidebar T={T} screen={screen} onScreen={setScreen} status={status} advanced={!!settings.advanced}/>
      <main style={{ overflow: "auto", padding: "28px 36px 36px", minWidth: 0 }} className="ws-scroll">
        {screen === "dashboard" && <Dashboard T={T} api={api} status={status} clients={clients} advanced={!!settings.advanced}/>}
        {screen === "clients"   && <ClientsScreen T={T} api={api} clients={clients}/>}
        {screen === "service"   && <ServiceScreen T={T} api={api} status={status}/>}
        {screen === "logs"      && <LogsScreen T={T} logs={logs} onClear={() => setLogs([])}/>}
        {screen === "settings"  && <SettingsScreen T={T} settings={settings} onSetting={onSetting} status={status} api={api}/>}
      </main>
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
  ];
  const tone =
    status.status === "running" ? "good" :
    status.status === "starting" ? "warn" :
    status.status === "error" ? "bad" : "neutral";
  const label =
    status.status === "running" ? T.running :
    status.status === "starting" ? "Iniciando…" :
    status.status === "error" ? "Error" : T.stopped;

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
const SetupWizard = ({ T, api, theme, onDone }) => {
  const [endpoint, setEndpoint] = useState("");
  const [port, setPort] = useState(443);
  const [wgPort, setWgPort] = useState(51820);
  const [subnet, setSubnet] = useState("10.0.0.0/24");
  const [srvAddr, setSrvAddr] = useState("10.0.0.1/24");
  const [deps, setDeps] = useState(null);
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");

  useEffect(() => {
    if (!api) return;
    api.get_deps().then(setDeps);
    api.detect_public_ip().then((r) => { if (r.ip && !endpoint) setEndpoint(r.ip); });
  }, [api]);

  const missing = deps && (!deps.wstunnel || !deps.wg);

  const onInstall = async () => {
    setError(""); setBusy(true);
    try {
      const r = await api.run_setup({ endpoint, port: Number(port), wg_listen_port: Number(wgPort), subnet, server_address: srvAddr });
      if (!r.ok) setError(r.error);
      else onDone();
    } finally { setBusy(false); }
  };

  return (
    <div data-theme={theme} style={{ height: "100%", display: "grid", placeItems: "center", padding: 24, background: "var(--bg)" }}>
      <div style={{ width: 560, background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 16, padding: 28, boxShadow: "var(--shadow)" }}>
        <window.WSWordmark size={20} color="var(--text)" accent="var(--brand)"/>
        <div style={{ fontSize: 22, fontWeight: 600, marginTop: 16, letterSpacing: "-0.02em" }}>Configuración inicial</div>
        <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 4 }}>
          Levanta el servicio wstunnel + WireGuard en este servidor.
        </div>

        {deps && (
          <div style={{ marginTop: 18, fontFamily: "var(--font-mono)", fontSize: 12 }}>
            <DepLine name="wstunnel" path={deps.wstunnel}/>
            <DepLine name="wg" path={deps.wg}/>
          </div>
        )}
        {missing && (
          <div style={{ marginTop: 12, padding: 12, background: "color-mix(in srgb, var(--brand-bad) 12%, transparent)", color: "var(--brand-bad)", borderRadius: 8, fontSize: 12 }}>
            Faltan dependencias. Instálalas antes de continuar.
          </div>
        )}

        <div style={{ marginTop: 22, display: "grid", gap: 10 }}>
          <SetupRow label="Endpoint (IP o dominio)"><input value={endpoint} onChange={(e) => setEndpoint(e.target.value)} style={inputStyle}/></SetupRow>
          <SetupRow label="Puerto WSS"><input value={port} onChange={(e) => setPort(e.target.value)} style={inputStyle}/></SetupRow>
          <SetupRow label="Puerto WireGuard (loopback)"><input value={wgPort} onChange={(e) => setWgPort(e.target.value)} style={inputStyle}/></SetupRow>
          <SetupRow label="Subred WG"><input value={subnet} onChange={(e) => setSubnet(e.target.value)} style={inputStyle}/></SetupRow>
          <SetupRow label="Dirección del servidor WG"><input value={srvAddr} onChange={(e) => setSrvAddr(e.target.value)} style={inputStyle}/></SetupRow>
        </div>

        {error && <div style={{ marginTop: 14, padding: 12, background: "color-mix(in srgb, var(--brand-bad) 12%, transparent)", color: "var(--brand-bad)", borderRadius: 8, fontSize: 12, fontFamily: "var(--font-mono)" }}>{error}</div>}

        <div style={{ marginTop: 18, display: "flex", justifyContent: "flex-end", gap: 8 }}>
          <window.Btn kind="primary" size="md" onClick={onInstall} disabled={busy || missing || !endpoint}>
            {busy ? "Instalando…" : "Instalar"}
          </window.Btn>
        </div>
      </div>
    </div>
  );
};

const DepLine = ({ name, path }) => (
  <div style={{ display: "flex", gap: 8, alignItems: "center", padding: "4px 0" }}>
    <span style={{ color: path ? "var(--brand-2)" : "var(--brand-bad)" }}>{path ? "✓" : "✗"}</span>
    <span style={{ color: "var(--text-2)" }}>{name}:</span>
    <span style={{ color: path ? "var(--text)" : "var(--text-3)" }}>{path || "no encontrado en $PATH"}</span>
  </div>
);
const SetupRow = ({ label, children }) => (
  <label style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, alignItems: "center" }}>
    <span style={{ fontSize: 12, color: "var(--text-2)" }}>{label}</span>
    {children}
  </label>
);
const inputStyle = {
  height: 30, padding: "0 10px", borderRadius: 8,
  border: "1px solid var(--line-strong)", background: "var(--bg)", color: "var(--text)",
  fontFamily: "var(--font-mono)", fontSize: 12, outline: "none",
};

// ── Dashboard ──────────────────────────────────────────────────────
const Dashboard = ({ T, api, status, clients, advanced }) => {
  const online = clients.filter((c) => c.status === "online").length;
  const totalRx = clients.reduce((acc, c) => acc + (c.rx_bytes || 0), 0);
  const totalTx = clients.reduce((acc, c) => acc + (c.tx_bytes || 0), 0);

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <Header title={T.nav_dashboard} sub={`${status.endpoint}:${status.port} · ${status.subnet}`}/>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
        <Metric label={T.metric_clientsOnline} value={`${online}/${clients.length}`}/>
        <Metric label={T.metric_traffic}        value={fmtBytes(totalRx + totalTx)} sub={`↓ ${fmtBytes(totalRx)} · ↑ ${fmtBytes(totalTx)}`}/>
        <Metric label="Subred WG"               value={status.subnet}/>
        <Metric label="Puerto WG"               value={String(status.wg_listen_port)}/>
      </div>
      <ClientsTable T={T} clients={clients} api={api} compact/>
      {advanced && (
        <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18, fontFamily: "var(--font-mono)", fontSize: 12 }}>
          <div style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 10, fontFamily: "var(--font-sans)", fontWeight: 600 }}>Detalles del servidor</div>
          <KV k="Endpoint" v={`${status.endpoint}:${status.port}`}/>
          <KV k="WG addr" v={status.server_address}/>
          <KV k="WG port" v={String(status.wg_listen_port)}/>
          <KV k="Subred" v={status.subnet}/>
          <KV k="TLS fingerprint" v={status.cert_fingerprint_sha256} last/>
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
const ClientsScreen = ({ T, api, clients }) => {
  const [name, setName] = useState("");
  const [busy, setBusy] = useState(false);
  const [error, setError] = useState("");
  const [lastAdded, setLastAdded] = useState(null);
  const [savedTo, setSavedTo] = useState("");

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
      setError(r.error || "no se pudo guardar");
    }
  };

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
      <Header title={T.nav_clients}/>
      <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
        <div style={{ fontSize: 14, fontWeight: 600, marginBottom: 4 }}>{T.setup_title}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 14 }}>{T.setup_sub}</div>
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8 }}>
          <input value={name} onChange={(e) => setName(e.target.value)} placeholder={T.setup_namePh} style={{ ...inputStyle, height: 36, fontFamily: "var(--font-sans)", fontSize: 13 }}/>
          <window.Btn kind="primary" size="md" onClick={onAdd} disabled={busy || !name.trim()}>{busy ? "Generando…" : T.setup_generate}</window.Btn>
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
            ✓ guardado en {savedTo}
          </div>
        )}
      </section>
      <ClientsTable T={T} clients={clients} api={api}/>
    </div>
  );
};

const ClientsTable = ({ T, clients, api, compact }) => {
  const onRevoke = async (name) => {
    if (!window.confirm(T.revokeConfirm.replace("{name}", name))) return;
    await api?.revoke_client(name);
  };
  return (
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, overflow: "hidden" }}>
      <table style={{ width: "100%", borderCollapse: "collapse", fontSize: 13 }}>
        <thead style={{ background: "var(--bg-sunk)" }}>
          <tr>
            <Th>{T.clientName}</Th>
            <Th>{T.ipAssigned}</Th>
            <Th>Estado</Th>
            <Th>{T.lastHandshake}</Th>
            <Th>{T.transferred}</Th>
            {!compact && <Th>Endpoint</Th>}
            <Th/>
          </tr>
        </thead>
        <tbody>
          {clients.length === 0 && (
            <tr><td colSpan={compact ? 6 : 7} style={{ textAlign: "center", padding: 24, color: "var(--text-3)", fontSize: 13 }}>
              Aún no hay clientes. Usa <strong>{T.addClient}</strong> para generar el primero.
            </td></tr>
          )}
          {clients.map((c) => (
            <tr key={c.name} style={{ borderTop: "1px solid var(--line)" }}>
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
                <window.Btn kind="danger" size="sm" onClick={() => onRevoke(c.name)}>{T.revoke}</window.Btn>
              </Td>
            </tr>
          ))}
        </tbody>
      </table>
    </section>
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
          {status.status === "running" ? T.running : status.status === "starting" ? "Iniciando…" : status.status === "error" ? "Error" : T.stopped}
        </span>
      </div>
      <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
        <window.Btn kind="primary" size="md" onClick={() => api?.start_service()}>Iniciar</window.Btn>
        <window.Btn kind="ghost"   size="md" onClick={() => api?.stop_service()}>Parar</window.Btn>
        <window.Btn kind="ghost"   size="md" onClick={() => api?.restart_service()}>{T.service_restart}</window.Btn>
      </div>
    </section>
  </div>
);

// ── Logs ───────────────────────────────────────────────────────────
const LogsScreen = ({ T, logs, onClear }) => {
  const ref = useRef(null);
  const [filter, setFilter] = useState("");
  useEffect(() => { if (ref.current) ref.current.scrollTop = ref.current.scrollHeight; }, [logs.length]);
  const filtered = filter ? logs.filter((l) => l.msg.toLowerCase().includes(filter.toLowerCase())) : logs;
  return (
    <section style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
      <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.logs_title}</div>
          <div style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{T.logs_sub}</div>
        </div>
        <div style={{ display: "flex", gap: 8 }}>
          <input value={filter} onChange={(e) => setFilter(e.target.value)} placeholder="Filtrar…" style={{ ...inputStyle, width: 220 }}/>
          <window.Btn kind="ghost" size="sm" onClick={onClear}>Limpiar</window.Btn>
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
                      display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "start",
                    }}>
                      <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-2)", whiteSpace: "pre-wrap", wordBreak: "break-word" }}>
                        {c.remediation}
                      </div>
                      <button onClick={() => onCopy(c.remediation, i)} style={{
                        all: "unset", cursor: "pointer", padding: "4px 10px", borderRadius: 6,
                        fontSize: 11, fontWeight: 600, color: "var(--text-2)", border: "1px solid var(--line-strong)",
                        background: "var(--bg-2)",
                      }}>
                        {copiedIdx === i ? T.doctor_copied : T.doctor_copy}
                      </button>
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

// ── Settings ───────────────────────────────────────────────────────
const SettingsScreen = ({ T, settings, onSetting, status, api }) => {
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
        <Row title="Idioma" control={<select value={settings.language} onChange={(e) => onSetting("language", e.target.value)} style={inputStyle}>
          <option value="es">Español</option><option value="en">English</option>
        </select>}/>
        <Row title="Tema" control={<select value={settings.theme} onChange={(e) => onSetting("theme", e.target.value)} style={inputStyle}>
          <option value="auto">Auto</option><option value="light">Claro</option><option value="dark">Oscuro</option>
        </select>}/>
        <Row title="Modo avanzado" sub="Cambia la estética y muestra detalles técnicos" control={<window.Toggle on={!!settings.advanced} onChange={(v) => onSetting("advanced", v)}/>}/>
      </div>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: "0 18px" }}>
        <Row title={T.set_port} control={<span style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}>{status.port}</span>}/>
        <Row title={T.set_subnet} control={<span style={{ fontFamily: "var(--font-mono)", fontSize: 13 }}>{status.subnet}</span>}/>
        <Row title={T.set_cert} sub={T.set_certSub} control={<span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)", maxWidth: 320, display: "inline-block", textAlign: "right", wordBreak: "break-all" }}>{status.cert_fingerprint_sha256}</span>}/>
      </div>
      <DoctorPanel T={T} api={api}/>
    </section>
  );
};

ReactDOM.createRoot(document.getElementById("root")).render(<App/>);
