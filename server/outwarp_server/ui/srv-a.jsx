// Server Variation A — pulida (consumer/admin friendly)
// Same chassis as client VarA: left sidebar + main column.

const SrvA = ({ tweaks }) => {
  const lang = tweaks.language || "es";
  const T = window.SRV_STR[lang];
  const theme = tweaks.theme === "dark" ? "dark" : "light";
  const screen = tweaks.screenSrvA || "dashboard";
  const dialog = tweaks.dialogSrvA || null; // 'add' | 'qr' | null

  return (
    <window.WindowsFrame width={1180} height={780} title="OutWarp Server" theme={theme} accent="#2563ff">
      <div data-theme={theme} style={{ display: "grid", gridTemplateColumns: "240px 1fr", height: "100%", background: "var(--bg)", color: "var(--text)", position: "relative" }}>
        <SrvSidebarA T={T} screen={screen}/>
        <main style={{ overflow: "auto", padding: "28px 36px 36px" }} className="ws-scroll">
          {screen === "dashboard" && <SrvDashA T={T}/>}
          {screen === "clients"   && <SrvClientsA T={T}/>}
          {screen === "service"   && <SrvServiceA T={T}/>}
          {screen === "logs"      && <SrvLogsA T={T}/>}
          {screen === "settings"  && <SrvSettingsA T={T}/>}
        </main>
        {dialog === "add" && <AddClientDialog T={T}/>}
        {dialog === "qr"  && <QRDialog T={T}/>}
      </div>
    </window.WindowsFrame>
  );
};

const SrvSidebarA = ({ T, screen }) => {
  const items = [
    { id: "dashboard", label: T.nav_dashboard, icon: <SI_Dash/> },
    { id: "clients",   label: T.nav_clients,   icon: <SI_Users/> },
    { id: "service",   label: T.nav_service,   icon: <SI_Server/> },
    { id: "logs",      label: T.nav_logs,      icon: <SI_Logs/> },
    { id: "settings",  label: T.nav_settings,  icon: <SI_Cog/> },
  ];
  return (
    <aside style={{ background: "var(--bg-2)", borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", padding: "22px 14px" }}>
      <div style={{ padding: "0 8px 4px" }}>
        <window.WSWordmark size={16} color="var(--text)" accent="var(--brand)"/>
      </div>
      <div style={{ padding: "0 8px 22px", fontSize: 11, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", fontWeight: 500 }}>
        Server admin
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 2 }}>
        {items.map(it => {
          const active = it.id === screen;
          return (
            <div key={it.id} style={{
              display: "flex", alignItems: "center", gap: 10,
              padding: "9px 10px", borderRadius: 8,
              fontSize: 13, fontWeight: 500,
              background: active ? "var(--chip)" : "transparent",
              color: active ? "var(--text)" : "var(--text-2)",
            }}>
              <span style={{ color: active ? "var(--brand)" : "var(--text-3)", display: "inline-flex" }}>{it.icon}</span>
              {it.label}
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: "auto", padding: 12, borderRadius: 12, background: "var(--bg-sunk)", border: "1px solid var(--line)" }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.serverStatus}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <window.StatusDot tone="good"/>
          <div style={{ fontSize: 13, fontWeight: 600 }}>{T.running}</div>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2, fontFamily: "var(--font-mono)" }}>vps.fcrespo.dev:443</div>
      </div>
    </aside>
  );
};

// ── Dashboard ───────────────────────────────────────────────────
const SrvDashA = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
      <div>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.nav_dashboard}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>vps.fcrespo.dev · 89.32.144.19 · Frankfurt, DE</div>
      </div>
      <window.Btn kind="primary" size="md" icon={<SI_Plus/>}>{T.addClient}</window.Btn>
    </header>

    {/* Hero status */}
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28, position: "relative", overflow: "hidden" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <window.StatusDot tone="good"/>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-2)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.running}</span>
          </div>
          <div style={{ fontSize: 32, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.05 }}>4 / 7 clientes en línea</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>{T.metric_uptime}: 12 d 04 h 33 m · wstunnel + wg-quick@wg0</div>
        </div>
        <div style={{ display: "flex", flexDirection: "column", gap: 6, alignItems: "flex-end", fontFamily: "var(--font-mono)" }}>
          <div style={{ fontSize: 12, color: "var(--text-3)" }}>TRÁFICO TOTAL · 24 h</div>
          <div style={{ fontSize: 28, fontWeight: 600 }}>2.13 GB</div>
          <div style={{ fontSize: 12, color: "var(--text-2)" }}>↓ 1.78 GB &nbsp;·&nbsp; ↑ 358 MB</div>
        </div>
      </div>
      <div aria-hidden style={{ position: "absolute", right: -120, top: -100, width: 320, height: 320, background: "radial-gradient(circle, color-mix(in srgb, var(--brand) 18%, transparent), transparent 60%)", pointerEvents: "none" }}/>
    </section>

    {/* Metric grid */}
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
      <Stat label={T.metric_clientsOnline} value="4" sub={`de 7 ${T.metric_clientsTotal.toLowerCase()}`}/>
      <Stat label={T.metric_traffic}       value="2.13 GB" sub="últimas 24 h"/>
      <Stat label={T.metric_peakClients}   value="6" sub="hace 2 días"/>
      <Stat label={T.metric_peakTraffic}   value="42 MB/s" sub="ayer 21:14"/>
    </div>

    {/* Traffic chart */}
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>Tráfico agregado · últimas 24 h</div>
        <div style={{ display: "flex", gap: 12, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)" }}>
          <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: "var(--brand)", marginRight: 6 }}/>RX</span>
          <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: "var(--brand-2)", marginRight: 6 }}/>TX</span>
        </div>
      </div>
      <SrvThroughput/>
    </section>

    {/* Recent clients summary */}
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>Clientes activos</div>
      <div style={{ display: "flex", flexDirection: "column", gap: 6 }}>
        {window.SAMPLE_CLIENTS.filter(c => c.online).slice(0, 4).map(c => (
          <div key={c.name} style={{ display: "grid", gridTemplateColumns: "auto 1fr auto auto", gap: 12, alignItems: "center", padding: "8px 10px", borderRadius: 8, background: "var(--bg)" }}>
            <window.StatusDot tone="good"/>
            <div>
              <div style={{ fontSize: 13, fontWeight: 500 }}>{c.name}</div>
              <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{c.ip} · {c.endpoint}</div>
            </div>
            <div style={{ fontSize: 12, fontFamily: "var(--font-mono)", color: "var(--text-2)" }}>↓ {c.rx} ↑ {c.tx}</div>
            <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-3)" }}>hs {c.hs}</div>
          </div>
        ))}
      </div>
    </section>
  </div>
);

// ── Clients ─────────────────────────────────────────────────────
const SrvClientsA = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
    <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
      <div>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.nav_clients}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)" }}>{window.SAMPLE_CLIENTS.length} totales · {window.SAMPLE_CLIENTS.filter(c=>c.online).length} en línea</div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input placeholder="Buscar…" style={{ height: 32, padding: "0 12px", borderRadius: 8, border: "1px solid var(--line-strong)", background: "var(--bg-2)", color: "var(--text)", fontSize: 12, width: 200, outline: "none" }}/>
        <window.Btn kind="primary" size="md" icon={<SI_Plus/>}>{T.addClient}</window.Btn>
      </div>
    </header>

    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, overflow: "hidden" }}>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1.4fr 1fr 1fr 1fr 1fr auto", gap: 0, padding: "10px 16px", borderBottom: "1px solid var(--line)", fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600, background: "var(--bg-sunk)" }}>
        <span/>
        <span>{T.clientName}</span>
        <span>{T.ipAssigned}</span>
        <span>{T.lastHandshake}</span>
        <span>↓ {T.metric_rx}</span>
        <span>↑ {T.metric_tx}</span>
        <span/>
      </div>
      {window.SAMPLE_CLIENTS.map((c, i) => (
        <div key={c.name} style={{ display: "grid", gridTemplateColumns: "auto 1.4fr 1fr 1fr 1fr 1fr auto", gap: 0, padding: "12px 16px", borderBottom: i === window.SAMPLE_CLIENTS.length - 1 ? "none" : "1px solid var(--line)", alignItems: "center" }}>
          <window.StatusDot tone={c.online ? "good" : "neutral"} pulse={c.online}/>
          <div style={{ paddingLeft: 12 }}>
            <div style={{ fontSize: 13, fontWeight: 600 }}>{c.name}</div>
            <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{c.endpoint}</div>
          </div>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-2)" }}>{c.ip}</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: c.online ? "var(--brand-2)" : "var(--text-3)" }}>{c.hs}</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-2)" }}>{c.rx}</span>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-2)" }}>{c.tx}</span>
          <div style={{ display: "flex", gap: 4 }}>
            <window.Btn kind="ghost" size="sm">QR</window.Btn>
            <window.Btn kind="ghost" size="sm">⋯</window.Btn>
          </div>
        </div>
      ))}
    </section>
  </div>
);

// ── Service ─────────────────────────────────────────────────────
const SrvServiceA = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
    <header>
      <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.nav_service}</div>
      <div style={{ fontSize: 12, color: "var(--text-3)" }}>Control de los servicios systemd que usa OutWarp.</div>
    </header>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
      <ServiceCard name={T.service_wstunnel} status="active" sub="Listening :443 (TLS) · 12 d 04 h" pid="2114" mem="38 MB"/>
      <ServiceCard name={T.service_wg}       status="active" sub="wg0 up · 4 peers handshaking"  pid="2151" mem="—"/>
    </div>
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
      <div style={{ fontSize: 13, fontWeight: 600, marginBottom: 12 }}>Acciones</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 10 }}>
        <window.Btn kind="ghost" size="md" icon={<SI_Refresh/>}>{T.service_restart}</window.Btn>
        <window.Btn kind="ghost" size="md" icon={<SI_Refresh/>}>{T.service_regen}</window.Btn>
        <window.Btn kind="danger" size="md">{T.service_uninstall}</window.Btn>
      </div>
    </section>
  </div>
);

const ServiceCard = ({ name, status, sub, pid, mem }) => (
  <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
    <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
      <window.StatusDot tone="good"/>
      <div style={{ fontSize: 14, fontWeight: 600, fontFamily: "var(--font-mono)" }}>{name}</div>
      <window.Pill tone="good">{status}</window.Pill>
    </div>
    <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 6 }}>{sub}</div>
    <div style={{ display: "flex", gap: 18, marginTop: 12, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)" }}>
      <span>PID {pid}</span><span>MEM {mem}</span>
    </div>
  </div>
);

// ── Logs (server) ───────────────────────────────────────────────
const SrvLogsA = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%", minHeight: 0 }}>
    <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end" }}>
      <div>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.logs_title}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{T.logs_sub}</div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input placeholder="Filtrar…" style={{ height: 30, padding: "0 12px", borderRadius: 8, border: "1px solid var(--line-strong)", background: "var(--bg-2)", color: "var(--text)", fontSize: 12, width: 220, outline: "none" }}/>
        <window.Btn kind="ghost" size="sm">Exportar</window.Btn>
      </div>
    </header>
    <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 12, fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.65, padding: 14, color: "var(--text-2)", overflow: "auto", flex: 1, minHeight: 360 }} className="ws-scroll">
      {window.SAMPLE_SRV_LOGS.map((l, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "92px 130px 60px 1fr", gap: 10 }}>
          <span style={{ color: "var(--text-3)" }}>{l.t}</span>
          <span style={{ color: "var(--brand)" }}>{l.svc}</span>
          <span style={{ color: l.lvl === "info" ? "var(--brand-2)" : l.lvl === "warn" ? "var(--brand-warn)" : l.lvl === "error" ? "var(--brand-bad)" : "var(--text-3)", textTransform: "uppercase" }}>{l.lvl}</span>
          <span style={{ color: "var(--text)" }}>{l.msg}</span>
        </div>
      ))}
      <div style={{ marginTop: 4 }}><span style={{ display: "inline-block", width: 6, height: 12, background: "var(--brand)", animation: "ws-blink 1s steps(2,end) infinite" }}/></div>
    </div>
  </div>
);

// ── Settings ────────────────────────────────────────────────────
const SrvSettingsA = ({ T }) => {
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
      <header>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.nav_settings}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)" }}>outwarp-server · v0.4.2</div>
      </header>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: "0 18px" }}>
        <Row title={T.set_port}   control={<input defaultValue="443" style={inputCss}/>}/>
        <Row title={T.set_iface}  control={<input defaultValue="wg0" style={inputCss}/>}/>
        <Row title={T.set_subnet} control={<input defaultValue="10.66.0.0/24" style={{ ...inputCss, width: 180 }}/>}/>
        <Row title={T.set_domain} sub={T.set_domainSub} control={<input placeholder="(opcional)" style={{ ...inputCss, width: 220 }}/>}/>
      </div>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{T.set_cert}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{T.set_certSub}</div>
        <div style={{ marginTop: 12, padding: 12, background: "var(--bg-sunk)", borderRadius: 8, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-2)" }}>
          sha256:4f:9a:1c:7e:b3:d2:8a:55:c1:92:7e:34:ab:55:01:e8:ff:21:cc:a0:14:9d:bb:60:8c:dd:4e:ff:71:02:a1:33
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 12 }}>
          <window.Btn kind="ghost" size="sm">Copiar huella</window.Btn>
          <window.Btn kind="danger" size="sm">{T.set_regen}</window.Btn>
        </div>
      </div>
    </section>
  );
};

const inputCss = { width: 120, height: 30, padding: "0 10px", borderRadius: 6, border: "1px solid var(--line-strong)", background: "var(--bg)", color: "var(--text)", fontFamily: "var(--font-mono)", fontSize: 12, outline: "none" };

// ── Dialogs ─────────────────────────────────────────────────────
const AddClientDialog = ({ T }) => (
  <DialogShell>
    <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em" }}>{T.setup_title}</div>
    <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 4, maxWidth: 460 }}>{T.setup_sub}</div>
    <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 12 }}>
      <Field label={T.setup_name}>
        <input placeholder={T.setup_namePh} style={{ ...inputCss, width: "100%" }}/>
      </Field>
      <Field label={T.setup_allowedIps}>
        <input defaultValue="0.0.0.0/0, ::/0" style={{ ...inputCss, width: "100%" }}/>
      </Field>
      <Field label={T.setup_dns}>
        <input defaultValue="1.1.1.1, 9.9.9.9" style={{ ...inputCss, width: "100%" }}/>
      </Field>
    </div>
    <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end", gap: 8 }}>
      <window.Btn kind="ghost" size="md">Cancelar</window.Btn>
      <window.Btn kind="primary" size="md">{T.setup_generate}</window.Btn>
    </div>
  </DialogShell>
);

const QRDialog = ({ T }) => (
  <DialogShell>
    <div style={{ fontSize: 18, fontWeight: 600 }}>ana-laptop · {T.showQR}</div>
    <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 4 }}>Escanea desde el cliente OutWarp o descarga el archivo.</div>
    <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 18, marginTop: 18, alignItems: "center" }}>
      <div style={{ background: "#fff", padding: 10, borderRadius: 8, border: "1px solid var(--line-strong)" }}>
        <SrvQR/>
      </div>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)", lineHeight: 1.7 }}>
        <div>name: ana-laptop</div>
        <div>ip:   10.66.0.2/24</div>
        <div>endpoint: wss://vps.fcrespo.dev:443</div>
        <div>pin:  sha256:4f9a1c7e…</div>
        <div>added: 2026-04-12</div>
      </div>
    </div>
    <div style={{ marginTop: 20, display: "flex", justifyContent: "flex-end", gap: 8 }}>
      <window.Btn kind="ghost" size="md">{T.copyConfig}</window.Btn>
      <window.Btn kind="primary" size="md">{T.download}</window.Btn>
    </div>
  </DialogShell>
);

const Field = ({ label, children }) => (
  <label style={{ display: "flex", flexDirection: "column", gap: 4 }}>
    <span style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>{label}</span>
    {children}
  </label>
);

const DialogShell = ({ children }) => (
  <div style={{ position: "absolute", inset: 0, background: "rgba(0,0,0,0.32)", display: "grid", placeItems: "center", zIndex: 5 }}>
    <div style={{ width: 480, background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 24, boxShadow: "0 24px 64px rgba(0,0,0,.3)" }}>
      {children}
    </div>
  </div>
);

// ── Atoms ───────────────────────────────────────────────────────
const Stat = ({ label, value, sub }) => (
  <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 12, padding: 14 }}>
    <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>{label}</div>
    <div style={{ fontSize: 24, fontWeight: 600, fontFamily: "var(--font-mono)", marginTop: 6 }}>{value}</div>
    {sub && <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>{sub}</div>}
  </div>
);

const SrvThroughput = () => {
  const N = 80;
  const seed = (i, o) => 0.5 + 0.4 * Math.sin(i / 7 + o) + 0.15 * Math.sin(i / 2.3 + o * 2);
  const dn = Array.from({ length: N }, (_, i) => Math.max(0.05, seed(i, 0.4)));
  const up = Array.from({ length: N }, (_, i) => Math.max(0.05, seed(i, 1.7) * 0.45));
  const W = 920, H = 140, P = 6;
  const path = (arr, mirror) => {
    const step = (W - P * 2) / (N - 1);
    return arr.map((v, i) => {
      const x = P + i * step;
      const y = mirror ? (H / 2 + (v * (H / 2 - P))) : (H / 2 - (v * (H / 2 - P)));
      return `${i === 0 ? "M" : "L"} ${x} ${y}`;
    }).join(" ");
  };
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none">
      <line x1="0" y1={H/2} x2={W} y2={H/2} stroke="var(--line)" strokeDasharray="2 4"/>
      <path d={`${path(dn)} L ${W-P} ${H/2} L ${P} ${H/2} Z`} fill="color-mix(in srgb, var(--brand) 18%, transparent)"/>
      <path d={path(dn)} stroke="var(--brand)" fill="none" strokeWidth="1.6"/>
      <path d={`${path(up, true)} L ${W-P} ${H/2} L ${P} ${H/2} Z`} fill="color-mix(in srgb, var(--brand-2) 18%, transparent)"/>
      <path d={path(up, true)} stroke="var(--brand-2)" fill="none" strokeWidth="1.6"/>
    </svg>
  );
};

const SrvQR = () => (
  <svg viewBox="0 0 25 25" width="160" height="160" shapeRendering="crispEdges">
    {Array.from({ length: 25 }).flatMap((_, y) => Array.from({ length: 25 }).map((_, x) => {
      const seed = (x * 47 + y * 19 + 13) % 19;
      const isFinder = (x < 7 && y < 7) || (x > 17 && y < 7) || (x < 7 && y > 17);
      const fill = isFinder ? ((Math.abs(x - (x>17?21:3)) <= 1 && Math.abs(y - (y>17?21:3)) <= 1) ? 1 : (Math.abs(x - (x>17?21:3)) === 3 || Math.abs(y - (y>17?21:3)) === 3) ? 1 : 0) : (seed > 9 ? 1 : 0);
      return fill ? <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill="#0a0d12"/> : null;
    }))}
  </svg>
);

// Icons
const SIc = (d, s = 16) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{d}</svg>;
const SI_Dash   = ({ size }) => SIc(<><rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="3" width="8" height="5" rx="1"/><rect x="13" y="10" width="8" height="11" rx="1"/><rect x="3" y="13" width="8" height="8" rx="1"/></>, size);
const SI_Users  = ({ size }) => SIc(<><circle cx="9" cy="8" r="3.5"/><path d="M2 21 c0-4 3-6 7-6 s7 2 7 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16 21 c0-3 2-4.5 4.5-4.5"/></>, size);
const SI_Server = ({ size }) => SIc(<><rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><circle cx="7" cy="7" r=".7" fill="currentColor"/><circle cx="7" cy="17" r=".7" fill="currentColor"/></>, size);
const SI_Logs   = ({ size }) => SIc(<><path d="M5 4 H19 V20 H5 Z"/><path d="M8 8 H16 M8 12 H16 M8 16 H13"/></>, size);
const SI_Cog    = ({ size }) => SIc(<><circle cx="12" cy="12" r="3"/><path d="M12 2 V4 M12 20 V22 M2 12 H4 M20 12 H22 M5 5 L6.5 6.5 M17.5 17.5 L19 19 M5 19 L6.5 17.5 M17.5 6.5 L19 5"/></>, size);
const SI_Plus   = ({ size }) => SIc(<><path d="M12 5 V19 M5 12 H19"/></>, size);
const SI_Refresh= ({ size }) => SIc(<><path d="M3 12 a9 9 0 0 1 15-6 L21 9 M21 4 V9 H16"/><path d="M21 12 a9 9 0 0 1-15 6 L3 15 M3 20 V15 H8"/></>, size);

window.SrvA = SrvA;
