// Variation A — Polished consumer client (Tailscale/WARP feel)
// Big hero connect button, sidebar nav, soft cards, friendly copy.

const VarA = ({ tweaks }) => {
  const lang = tweaks.language || "es";
  const T = window.STR[lang];
  const theme = tweaks.theme === "dark" ? "dark" : "light";
  const status = tweaks.status || "connected"; // empty | disconnected | connecting | connected | error
  const screen = tweaks.screenA || "home";     // home | logs | settings | import
  const advanced = !!tweaks.advanced;

  return (
    <window.WindowsFrame width={1080} height={720} title="OutWarp" theme={theme} accent="#2563ff">
      <div data-theme={theme} style={{ display: "grid", gridTemplateColumns: "232px 1fr", height: "100%", background: "var(--bg)", color: "var(--text)" }}>
        <SidebarA T={T} screen={screen} status={status}/>
        <main style={{ overflow: "auto", padding: "28px 36px 36px" }} className="ws-scroll">
          {screen === "home" && status === "empty"        && <HomeEmptyA T={T}/>}
          {screen === "home" && status === "disconnected" && <HomeDisconnectedA T={T}/>}
          {screen === "home" && status === "connecting"   && <HomeConnectingA T={T}/>}
          {screen === "home" && status === "connected"    && <HomeConnectedA T={T} advanced={advanced}/>}
          {screen === "home" && status === "error"        && <HomeErrorA T={T}/>}
          {screen === "import"                            && <ImportA T={T}/>}
          {screen === "logs"                              && <LogsA T={T}/>}
          {screen === "settings"                          && <SettingsA T={T} tweaks={tweaks}/>}
        </main>
      </div>
    </window.WindowsFrame>
  );
};

// ── Sidebar ───────────────────────────────────────────────────────
const SidebarA = ({ T, screen, status }) => {
  const items = [
    { id: "home",     label: T.nav_home,     icon: <IconHome/> },
    { id: "import",   label: T.nav_profiles, icon: <IconProfile/> },
    { id: "logs",     label: T.nav_logs,     icon: <IconLogs/> },
    { id: "settings", label: T.nav_settings, icon: <IconCog/> },
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
    <aside style={{ background: "var(--bg-2)", borderRight: "1px solid var(--line)", display: "flex", flexDirection: "column", padding: "22px 14px" }}>
      <div style={{ padding: "0 8px 22px" }}>
        <window.WSWordmark size={16} color="var(--text)" accent="var(--brand)"/>
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
              cursor: "default",
            }}>
              <span style={{ color: active ? "var(--brand)" : "var(--text-3)", display: "inline-flex" }}>{it.icon}</span>
              {it.label}
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: "auto", padding: 12, borderRadius: 12, background: "var(--bg-sunk)", border: "1px solid var(--line)" }}>
        <div style={{ fontSize: 11, fontWeight: 500, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.profile}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <window.StatusDot tone={tone} pulse={status === "connecting" || status === "connected"}/>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Universidad</div>
        </div>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2, fontFamily: "var(--font-mono)" }}>{label}</div>
      </div>
    </aside>
  );
};

// ── Home — connected ──────────────────────────────────────────────
const HomeConnectedA = ({ T, advanced }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <HeaderA T={T} status="connected"/>

    {/* Hero */}
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28, position: "relative", overflow: "hidden" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
        <div>
          <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 10 }}>
            <window.StatusDot tone="good"/>
            <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-2)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.connected}</span>
          </div>
          <div style={{ fontSize: 38, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.05 }}>
            89.32.144.19
          </div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>
            Frankfurt, DE · {T.profile} <strong style={{ color: "var(--text)" }}>Universidad</strong>
          </div>
          <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
            <window.Btn kind="solid" size="md">{T.disconnect}</window.Btn>
            <window.Btn kind="ghost" size="md" icon={<IconLogs size={14}/>}>{T.nav_logs}</window.Btn>
          </div>
        </div>
        <DialA active/>
      </div>
      <BgGlow/>
    </section>

    {/* Stats */}
    <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: 12 }}>
      <Stat label={T.latency}     value="42 ms" trend={<Spark good/>}/>
      <Stat label={T.download}    value="8.4 MB/s" sub="↓ 19.7 MB total"/>
      <Stat label={T.upload}      value="1.1 MB/s" sub="↑ 2.1 MB total"/>
      <Stat label={T.sessionTime} value="00:14:32" sub={`${T.lastHandshake} · 42s`}/>
    </div>

    {/* Throughput chart */}
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18 }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 8 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>Tráfico · últimos 60 s</div>
        <div style={{ display: "flex", gap: 12, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)" }}>
          <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: "var(--brand)", marginRight: 6 }}/>{T.download}</span>
          <span><span style={{ display: "inline-block", width: 8, height: 8, borderRadius: 2, background: "var(--brand-2)", marginRight: 6 }}/>{T.upload}</span>
        </div>
      </div>
      <Throughput/>
    </section>

    {advanced && (
      <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 18, fontFamily: "var(--font-mono)", fontSize: 12 }}>
        <div style={{ fontSize: 11, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 10, fontFamily: "var(--font-sans)", fontWeight: 600 }}>Detalles técnicos</div>
        <KVRow k={T.endpoint} v="wss://vps.fcrespo.dev:443"/>
        <KVRow k={T.fingerprint} v="sha256:4f9a1c7eb3d28a55c192…"/>
        <KVRow k="WireGuard peer" v="10.66.0.1:51820"/>
        <KVRow k="Allowed IPs" v="0.0.0.0/0, ::/0"/>
        <KVRow k="DNS" v="1.1.1.1, 9.9.9.9" last/>
      </section>
    )}
  </div>
);

const HomeDisconnectedA = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <HeaderA T={T} status="disconnected"/>
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28, position: "relative", overflow: "hidden" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
        <div>
          <div style={{ fontSize: 12, fontWeight: 600, color: "var(--text-3)", letterSpacing: ".06em", textTransform: "uppercase", marginBottom: 8 }}>{T.disconnected}</div>
          <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.1 }}>Listo para conectar</div>
          <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6, maxWidth: 380 }}>
            Tu perfil <strong style={{ color: "var(--text)" }}>Universidad</strong> está cargado. {T.home_ribbon}
          </div>
          <div style={{ marginTop: 18 }}>
            <window.Btn kind="primary" size="lg" icon={<IconBolt/>}>{T.connect}</window.Btn>
          </div>
        </div>
        <DialA/>
      </div>
    </section>

    <div style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: 12 }}>
      <InfoCard icon={<IconShield/>} title="Tráfico cifrado" body="WireGuard sobre WebSocket (wstunnel)."/>
      <InfoCard icon={<IconLock/>} title="Certificado anclado" body="Verificación por huella SHA-256, sin DNS dinámico."/>
      <InfoCard icon={<IconRoute/>} title="Ruteo automático" body="Bypass para el endpoint del túnel y reconexión con backoff."/>
    </div>
  </div>
);

const HomeConnectingA = ({ T }) => {
  const steps = [T.step_resolve, T.step_tls, T.step_wg, T.step_ws];
  const cur = 3;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
      <HeaderA T={T} status="connecting"/>
      <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28, position: "relative" }}>
        <div style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 24, alignItems: "center" }}>
          <div>
            <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
              <window.StatusDot tone="warn"/>
              <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-warn)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.connecting}</span>
            </div>
            <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.handshake}</div>
            <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6 }}>vps.fcrespo.dev · 89.32.144.19</div>
            <div style={{ marginTop: 20, display: "flex", flexDirection: "column", gap: 8 }}>
              {steps.map((s, i) => (
                <div key={s} style={{ display: "flex", alignItems: "center", gap: 10, fontSize: 13, color: i <= cur ? "var(--text)" : "var(--text-3)" }}>
                  {i < cur ? <IconCheck color="var(--brand-2)"/> : i === cur ? <Spinner/> : <IconDot/>}
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>{s}</span>
                </div>
              ))}
            </div>
            <div style={{ marginTop: 18 }}>
              <window.Btn kind="ghost" size="md">{T.cancel}</window.Btn>
            </div>
          </div>
          <DialA pulsing/>
        </div>
      </section>
    </div>
  );
};

const HomeEmptyA = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <HeaderA T={T} status="empty"/>
    <ImportA T={T}/>
  </div>
);

const HomeErrorA = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 24 }}>
    <HeaderA T={T} status="error"/>
    <section style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 18, padding: 28 }}>
      <div style={{ display: "flex", alignItems: "center", gap: 10, marginBottom: 8 }}>
        <window.StatusDot tone="bad"/>
        <span style={{ fontSize: 12, fontWeight: 600, color: "var(--brand-bad)", letterSpacing: ".06em", textTransform: "uppercase" }}>{T.error}</span>
      </div>
      <div style={{ fontSize: 24, fontWeight: 600, letterSpacing: "-0.02em" }}>No se pudo verificar el certificado</div>
      <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 6, maxWidth: 540 }}>
        La huella SHA-256 que recibimos del servidor no coincide con la que tu archivo <code style={{ fontFamily: "var(--font-mono)" }}>.owcfg</code> tiene anclada. Esto suele significar que el servidor regeneró su certificado, o que alguien está interceptando la conexión.
      </div>
      <div style={{ marginTop: 18, display: "flex", gap: 8 }}>
        <window.Btn kind="primary" size="md">Reintentar</window.Btn>
        <window.Btn kind="ghost" size="md">Importar nuevo .owcfg</window.Btn>
      </div>
    </section>
  </div>
);

// ── Header ───────────────────────────────────────────────────────
const HeaderA = ({ T, status }) => (
  <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
    <div>
      <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.nav_home}</div>
      <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 2 }}>{T.home_ribbon}</div>
    </div>
    <window.Btn kind="ghost" size="sm" icon={<IconCog size={14}/>}>{T.nav_settings}</window.Btn>
  </header>
);

// ── Import ───────────────────────────────────────────────────────
const ImportA = ({ T }) => (
  <section>
    <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.welcomeTitle}</div>
    <div style={{ fontSize: 13, color: "var(--text-2)", marginTop: 4, maxWidth: 520 }}>{T.welcomeSub}</div>

    <div style={{ marginTop: 22, maxWidth: 720 }}>
      <div style={{
        border: "1.5px dashed var(--line-strong)", borderRadius: 14, padding: 28,
        background: "var(--bg-2)", display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", minHeight: 240,
      }}>
        <div style={{ width: 56, height: 56, borderRadius: 14, background: "color-mix(in srgb, var(--brand) 12%, transparent)", display: "grid", placeItems: "center", color: "var(--brand)" }}>
          <IconUpload size={26}/>
        </div>
        <div style={{ fontSize: 16, fontWeight: 600, marginTop: 14 }}>{T.importDrop}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4 }}>{T.importHint}</div>
        <div style={{ display: "flex", gap: 8, marginTop: 16 }}>
          <window.Btn kind="primary" size="md">{T.importFile}</window.Btn>
          <window.Btn kind="ghost" size="md">{T.importPaste}</window.Btn>
        </div>
      </div>
    </div>
  </section>
);

// ── Logs ─────────────────────────────────────────────────────────
const LogsA = ({ T }) => (
  <section style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%" }}>
    <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center" }}>
      <div>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.logs_title}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)" }}>outwarp-client · stdout + stderr · live</div>
      </div>
      <div style={{ display: "flex", gap: 8 }}>
        <input placeholder={T.logs_filter} style={{
          height: 30, padding: "0 12px", borderRadius: 8, border: "1px solid var(--line-strong)",
          background: "var(--bg-2)", color: "var(--text)", fontSize: 12, width: 220, outline: "none",
        }}/>
        <window.Btn kind="ghost" size="sm">{T.logs_export}</window.Btn>
        <window.Btn kind="ghost" size="sm">{T.logs_clear}</window.Btn>
      </div>
    </header>
    <div style={{
      background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 12,
      fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.65,
      padding: 14, color: "var(--text-2)", overflow: "auto", flex: 1, minHeight: 360,
    }} className="ws-scroll">
      {window.SAMPLE_LOGS.map((l, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "84px 60px 1fr", gap: 10 }}>
          <span style={{ color: "var(--text-3)" }}>{l.t}</span>
          <span style={{ color: l.lvl === "info" ? "var(--brand-2)" : l.lvl === "debug" ? "var(--text-3)" : "var(--brand-bad)", textTransform: "uppercase" }}>{l.lvl}</span>
          <span style={{ color: "var(--text)" }}>{l.msg}</span>
        </div>
      ))}
      <div style={{ marginTop: 4, display: "flex", alignItems: "center", gap: 6, color: "var(--text-3)" }}>
        <span style={{ width: 6, height: 12, background: "var(--brand)", animation: "ws-blink 1s steps(2,end) infinite" }}/>
      </div>
    </div>
  </section>
);

// ── Settings ─────────────────────────────────────────────────────
const SettingsA = ({ T, tweaks }) => {
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
    <section style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 720 }}>
      <header>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{T.nav_settings}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)" }}>outwarp-client · v0.4.2</div>
      </header>
      <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: "0 18px" }}>
        <Row title={T.set_killSwitch}    sub={T.set_killSwitchSub}   control={<window.Toggle on={true}/>}/>
        <Row title={T.set_autoconnect}   sub={T.set_autoconnectSub}  control={<window.Toggle on={true}/>}/>
        <Row title={T.set_startup}                                    control={<window.Toggle on={false}/>}/>
        <Row title={T.set_minimizeTray}                               control={<window.Toggle on={true}/>}/>
        <Row title={T.set_advanced}      sub={T.set_advancedSub}     control={<window.Toggle on={!!tweaks.advanced}/>}/>
      </div>
    </section>
  );
};

// ── Atoms specific to A ──────────────────────────────────────────
const Stat = ({ label, value, sub, trend }) => (
  <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 12, padding: 14 }}>
    <div style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600 }}>{label}</div>
    <div style={{ display: "flex", alignItems: "baseline", justifyContent: "space-between", marginTop: 6 }}>
      <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.01em", fontFamily: "var(--font-mono)" }}>{value}</div>
      {trend}
    </div>
    {sub && <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>{sub}</div>}
  </div>
);

const InfoCard = ({ icon, title, body }) => (
  <div style={{ background: "var(--bg-2)", border: "1px solid var(--line)", borderRadius: 14, padding: 16 }}>
    <div style={{ width: 32, height: 32, borderRadius: 8, background: "var(--chip)", display: "grid", placeItems: "center", color: "var(--brand)" }}>{icon}</div>
    <div style={{ fontSize: 13, fontWeight: 600, marginTop: 12 }}>{title}</div>
    <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 4 }}>{body}</div>
  </div>
);

const KVRow = ({ k, v, last }) => (
  <div style={{ display: "grid", gridTemplateColumns: "180px 1fr", gap: 12, padding: "8px 0", borderBottom: last ? "none" : "1px dashed var(--line)" }}>
    <div style={{ color: "var(--text-3)" }}>{k}</div>
    <div style={{ color: "var(--text)" }}>{v}</div>
  </div>
);

const DialA = ({ active, pulsing }) => (
  <div style={{ position: "relative", width: 200, height: 200 }}>
    <svg width="200" height="200" viewBox="0 0 200 200">
      <defs>
        <linearGradient id="dialA" x1="0" y1="0" x2="1" y2="1">
          <stop offset="0" stopColor="var(--brand)"/>
          <stop offset="1" stopColor="var(--brand-2)"/>
        </linearGradient>
      </defs>
      <circle cx="100" cy="100" r="86" stroke="var(--line-strong)" strokeWidth="1" fill="none"/>
      <circle cx="100" cy="100" r="72" stroke="var(--line)" strokeWidth="1" fill="none" strokeDasharray="2 4"/>
      {active && <circle cx="100" cy="100" r="86" stroke="url(#dialA)" strokeWidth="3" fill="none"
        strokeDasharray={`${2*Math.PI*86*0.78} ${2*Math.PI*86}`}
        transform="rotate(-90 100 100)" strokeLinecap="round"/>}
    </svg>
    <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center" }}>
      <div style={{
        width: 110, height: 110, borderRadius: 999,
        background: active ? "linear-gradient(135deg, var(--brand), var(--brand-2))" : "var(--bg-sunk)",
        border: active ? "none" : "1px solid var(--line-strong)",
        display: "grid", placeItems: "center", color: active ? "#fff" : "var(--text-2)",
        boxShadow: active ? "0 12px 28px -10px color-mix(in srgb, var(--brand) 55%, transparent)" : "none",
        animation: pulsing ? "ws-pulse 1.6s ease-out infinite" : "none",
      }}>
        <window.WSLogoMark size={44} color={active ? "#fff" : "var(--text-2)"} accent={active ? "rgba(255,255,255,.6)" : "var(--text-3)"}/>
      </div>
    </div>
  </div>
);

const Throughput = () => {
  // generate two pseudo-random series
  const N = 60;
  const seed = (i, o) => 0.5 + 0.4 * Math.sin(i / 5 + o) + 0.15 * Math.sin(i / 1.7 + o * 2);
  const dn = Array.from({ length: N }, (_, i) => Math.max(0.05, seed(i, 0.4)));
  const up = Array.from({ length: N }, (_, i) => Math.max(0.05, seed(i, 1.7) * 0.55));
  const W = 760, H = 120, P = 6;
  const path = (arr, mirror = false) => {
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

const Spark = ({ good }) => {
  const pts = [4, 6, 5, 7, 5, 8, 6, 9, 7, 10, 8, 9].map((v, i) => `${i*4},${14-v}`).join(" ");
  return <svg width="48" height="14" viewBox="0 0 48 14"><polyline points={pts} fill="none" stroke={good ? "var(--brand-2)" : "var(--brand-bad)"} strokeWidth="1.4"/></svg>;
};

const BgGlow = () => (
  <div aria-hidden style={{ position: "absolute", inset: 0, pointerEvents: "none", overflow: "hidden", borderRadius: 18 }}>
    <div style={{ position: "absolute", right: -80, top: -80, width: 280, height: 280, background: "radial-gradient(circle, color-mix(in srgb, var(--brand) 22%, transparent), transparent 60%)" }}/>
  </div>
);

const Spinner = () => (
  <span style={{ width: 14, height: 14, borderRadius: 999, border: "2px solid var(--line-strong)", borderTopColor: "var(--brand)", display: "inline-block", animation: "ws-spin .8s linear infinite" }}/>
);
const IconCheck = ({ color = "var(--brand-2)" }) => <svg width="14" height="14" viewBox="0 0 14 14"><path d="M2 7.5 L5.5 11 L12 3.5" stroke={color} strokeWidth="2" fill="none" strokeLinecap="round" strokeLinejoin="round"/></svg>;
const IconDot = () => <span style={{ width: 14, height: 14, display: "inline-block" }}><span style={{ width: 6, height: 6, borderRadius: 999, background: "var(--text-3)", display: "inline-block", margin: 4 }}/></span>;

// minimal icon set
const I = (d, s = 16) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{d}</svg>;
const IconHome = ({ size }) => I(<><path d="M3 11 L12 3 L21 11"/><path d="M5 10 V20 H19 V10"/></>, size);
const IconProfile = ({ size }) => I(<><circle cx="12" cy="8" r="4"/><path d="M4 21 C4 16 8 14 12 14 C16 14 20 16 20 21"/></>, size);
const IconLogs = ({ size }) => I(<><path d="M5 4 H19 V20 H5 Z"/><path d="M8 8 H16 M8 12 H16 M8 16 H13"/></>, size);
const IconCog = ({ size }) => I(<><circle cx="12" cy="12" r="3"/><path d="M12 2 V4 M12 20 V22 M2 12 H4 M20 12 H22 M5 5 L6.5 6.5 M17.5 17.5 L19 19 M5 19 L6.5 17.5 M17.5 6.5 L19 5"/></>, size);
const IconBolt = ({ size }) => I(<path d="M13 2 L4 14 H11 L9 22 L20 9 H13 Z"/>, size);
const IconUpload = ({ size }) => I(<><path d="M12 16 V4 M6 10 L12 4 L18 10"/><path d="M4 20 H20"/></>, size);
const IconShield = ({ size }) => I(<path d="M12 3 L4 6 V12 C4 17 8 20 12 21 C16 20 20 17 20 12 V6 Z"/>, size);
const IconLock = ({ size }) => I(<><rect x="5" y="11" width="14" height="9" rx="2"/><path d="M8 11 V8 a4 4 0 0 1 8 0 V11"/></>, size);
const IconRoute = ({ size }) => I(<><circle cx="6" cy="6" r="2"/><circle cx="18" cy="18" r="2"/><path d="M6 8 V14 a4 4 0 0 0 4 4 H16"/></>, size);

window.VarA = VarA;
