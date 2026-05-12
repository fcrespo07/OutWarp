// Variation B — "Modo desarrollador"
// SAME chassis as Variation A (left sidebar, main column, header).
// What changes: content density, mono type, hard borders, instrument panels,
// tunnel visualizer, raw routing/cipher tables. Designed to slot in as a
// developer-mode skin of A — not a separate app.

const VarB = ({ tweaks }) => {
  const lang = tweaks.language || "es";
  const T = window.STR[lang];
  const theme = tweaks.theme === "dark" ? "dark" : "light";
  const status = tweaks.status || "connected";
  const screen = tweaks.screenB || "home";

  return (
    <window.WindowsFrame width={1080} height={720} title="OutWarp — dev mode" theme={theme} accent="#2563ff">
      <div data-theme={theme} style={{ display: "grid", gridTemplateColumns: "232px 1fr", height: "100%", background: "var(--bg)", color: "var(--text)", fontFamily: "var(--font-sans)" }}>
        <SidebarB T={T} screen={screen} status={status}/>
        <main style={{ overflow: "auto", padding: "28px 36px 36px", display: "flex", flexDirection: "column", minHeight: 0 }} className="ws-scroll">
          {screen === "home"     && <HomeB     T={T} status={status}/>}
          {screen === "import"   && <ImportB   T={T}/>}
          {screen === "logs"     && <LogsB     T={T}/>}
          {screen === "settings" && <SettingsB T={T}/>}
        </main>
      </div>
    </window.WindowsFrame>
  );
};

// ── Sidebar (matches A's structure) ─────────────────────────────
const SidebarB = ({ T, screen, status }) => {
  const items = [
    { id: "home",     label: T.nav_home,     icon: <IcHome/> },
    { id: "import",   label: T.nav_profiles, icon: <IcProfile/> },
    { id: "logs",     label: T.nav_logs,     icon: <IcLogs/> },
    { id: "settings", label: T.nav_settings, icon: <IcCog/> },
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
    <aside style={{ background: "var(--bg-2)", borderRight: "1px solid var(--line-strong)", display: "flex", flexDirection: "column", padding: "22px 14px" }}>
      <div style={{ padding: "0 8px 8px" }}>
        <window.WSWordmark size={16} color="var(--text)" accent="var(--brand)"/>
      </div>
      <div style={{ padding: "0 8px 18px", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase" }}>
        dev mode · v0.4.2
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 0 }}>
        {items.map((it, i) => {
          const active = it.id === screen;
          return (
            <div key={it.id} style={{
              display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 10, alignItems: "center",
              padding: "10px 10px",
              borderLeft: active ? "2px solid var(--brand)" : "2px solid transparent",
              background: active ? "var(--chip)" : "transparent",
              fontSize: 13, fontWeight: 500,
              color: active ? "var(--text)" : "var(--text-2)",
              cursor: "default",
            }}>
              <span style={{ color: active ? "var(--brand)" : "var(--text-3)", display: "inline-flex" }}>{it.icon}</span>
              <span>{it.label}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)" }}>0{i+1}</span>
            </div>
          );
        })}
      </div>

      <div style={{ marginTop: "auto", border: "1px solid var(--line-strong)", padding: 12, background: "var(--bg-sunk)" }}>
        <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase" }}>{T.profile}</div>
        <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 6 }}>
          <window.StatusDot tone={tone} pulse={status === "connecting" || status === "connected"}/>
          <div style={{ fontSize: 13, fontWeight: 600 }}>Universidad</div>
        </div>
        <div style={{ fontSize: 10, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>{label.toUpperCase()}</div>
        <div style={{ height: 1, background: "var(--line-strong)", margin: "10px -12px" }}/>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.7 }}>
          <div>peer 10.66.0.1</div>
          <div>port 443/wss</div>
          <div>cipher AES-256-GCM</div>
        </div>
      </div>
    </aside>
  );
};

// ── Header (mono header, same shape as A's HeaderA) ─────────────
const HeaderB = ({ T, k = "01", title, sub, right }) => (
  <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", marginBottom: 18 }}>
    <div>
      <div style={{ display: "flex", alignItems: "baseline", gap: 10 }}>
        <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)" }}>{k}</span>
        <div style={{ fontSize: 22, fontWeight: 600, letterSpacing: "-0.02em" }}>{title}</div>
      </div>
      {sub && <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 4, fontFamily: "var(--font-mono)" }}>{sub}</div>}
    </div>
    <div style={{ display: "flex", gap: 8 }}>{right}</div>
  </header>
);

// ── HOME ────────────────────────────────────────────────────────
const HomeB = ({ T, status }) => {
  const connected  = status === "connected";
  const connecting = status === "connecting";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
      <HeaderB T={T} k="01" title={T.nav_home}
        sub={connected ? "TUNNEL UP · wstunnel/wss → wg-quick" : connecting ? "NEGOTIATING" : status === "error" ? "FAULT" : "TUNNEL DOWN"}
        right={
          <>
            {connected   && <window.Btn kind="ghost"   size="sm">{T.disconnect}</window.Btn>}
            {!connected && !connecting && <window.Btn kind="primary" size="sm" icon={<IcBolt size={14}/>}>{T.connect}</window.Btn>}
            {connecting  && <window.Btn kind="ghost"   size="sm">{T.cancel}</window.Btn>}
          </>
        }
      />

      {/* Hero — instrument readout instead of dial */}
      <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)", padding: 0 }}>
        <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 0 }}>
          <div style={{ padding: "22px 24px", borderRight: "1px solid var(--line-strong)" }}>
            <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>{T.publicIp}</div>
            <div style={{ fontSize: 38, fontWeight: 600, fontFamily: "var(--font-mono)", letterSpacing: "-0.02em", lineHeight: 1.05, marginTop: 4 }}>
              {connected ? "89.32.144.19" : "—"}
            </div>
            <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 6, fontFamily: "var(--font-mono)" }}>
              {connected ? "FRANKFURT-DE · AS24940 HETZNER" : T.notConnected.toUpperCase()}
            </div>

            <div style={{ display: "grid", gridTemplateColumns: "repeat(2, 1fr)", marginTop: 18, gap: 0 }}>
              <Mono label={T.latency}      value={connected ? "42 ms"     : "—"} sub="rtt p50"/>
              <Mono label={T.sessionTime}  value={connected ? "00:14:32"  : "—"} sub={`hs ${connected ? "42s ago" : "—"}`}/>
              <Mono label={T.download}     value={connected ? "8.4 MB/s"  : "—"} sub="↓ 19.7 MB" border/>
              <Mono label={T.upload}       value={connected ? "1.1 MB/s"  : "—"} sub="↑ 2.1 MB"  border/>
            </div>
          </div>

          <div style={{ padding: "22px 24px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
            <div>
              <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>tunnel</div>
              <div style={{ marginTop: 8, height: 84 }}>
                <window.TunnelViz active={connected || connecting} throughput={connecting ? 0.4 : 1}/>
              </div>
            </div>
            <div style={{ marginTop: 10, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)", lineHeight: 1.7 }}>
              <div><span style={{ color: "var(--text-3)" }}>local  </span> 10.66.0.2/24 · outwarp0</div>
              <div><span style={{ color: "var(--text-3)" }}>peer   </span> 10.66.0.1:51820</div>
              <div><span style={{ color: "var(--text-3)" }}>via    </span> wss://vps.fcrespo.dev:443</div>
            </div>
          </div>
        </div>

        {/* Connecting steps row */}
        {connecting && (
          <div style={{ borderTop: "1px solid var(--line-strong)", padding: 14, display: "grid", gridTemplateColumns: "repeat(5, 1fr)", gap: 8 }}>
            {[T.step_resolve, T.step_tls, T.step_ws, T.step_wg, T.step_route].map((s, i) => {
              const cur = 3;
              return (
                <div key={s} style={{
                  border: "1px solid var(--line-strong)", padding: "8px 10px",
                  fontFamily: "var(--font-mono)", fontSize: 11,
                  background: i < cur ? "color-mix(in srgb, var(--brand-2) 12%, transparent)" : i === cur ? "color-mix(in srgb, var(--brand-warn) 14%, transparent)" : "transparent",
                  color: i <= cur ? "var(--text)" : "var(--text-3)",
                }}>
                  <div style={{ fontSize: 10, color: "var(--text-3)" }}>{String(i+1).padStart(2,"0")}</div>
                  <div>{s}</div>
                </div>
              );
            })}
          </div>
        )}
      </section>

      {/* Throughput bars + endpoint table side-by-side */}
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr", gap: 16 }}>
        <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)", padding: 16 }}>
          <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 10 }}>
            <span>throughput · 60 s</span><span>peak 12.3 mb/s</span>
          </div>
          <BarMatrix/>
        </section>

        <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)", fontFamily: "var(--font-mono)", fontSize: 12 }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line-strong)", fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>endpoint</div>
          <KV k="endpoint" v="wss://vps.fcrespo.dev:443"/>
          <KV k="resolved" v="89.32.144.19"/>
          <KV k="protocol" v="TLS 1.3 + WS + WG"/>
          <KV k="cipher"   v="TLS_AES_256_GCM_SHA384"/>
          <KV k="cert.fp"  v="sha256:4f9a1c7eb3d2…"/>
          <KV k="allowed"  v="0.0.0.0/0, ::/0" last/>
        </section>
      </div>

      {/* Routing + last events */}
      <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
        <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line-strong)", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>routing table</div>
          <div style={{ padding: 14, fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.8 }}>
            <div style={{ color: "var(--text-3)" }}># bypass para wstunnel</div>
            <div>89.32.144.19/32 → 192.168.1.1</div>
            <div style={{ color: "var(--text-3)", marginTop: 8 }}># tráfico cifrado</div>
            <div>0.0.0.0/0 → outwarp0</div>
            <div>::/0       → outwarp0</div>
          </div>
        </section>

        <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
          <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line-strong)", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>last events</div>
          <div style={{ padding: "8px 14px", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)" }}>
            {window.SAMPLE_LOGS.slice(-6).map((l, i) => (
              <div key={i} style={{ display: "grid", gridTemplateColumns: "70px 50px 1fr", gap: 8, padding: "3px 0" }}>
                <span style={{ color: "var(--text-3)" }}>{l.t.slice(0,8)}</span>
                <span style={{ color: l.lvl === "info" ? "var(--brand-2)" : "var(--text-3)" }}>{l.lvl.toUpperCase()}</span>
                <span>{l.msg}</span>
              </div>
            ))}
          </div>
        </section>
      </div>
    </div>
  );
};

// ── IMPORT ──────────────────────────────────────────────────────
const ImportB = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
    <HeaderB T={T} k="02" title={T.profiles_title} sub=".owcfg / wstunnel + wg config"
      right={<window.Btn kind="primary" size="sm">{T.profiles_add}</window.Btn>}/>

    <div style={{ display: "grid", gridTemplateColumns: "1.4fr 1fr", gap: 16 }}>
      <div style={{ border: "1.5px dashed var(--line-strong)", background: "var(--bg-2)", padding: 28, display: "flex", flexDirection: "column", alignItems: "center", justifyContent: "center", textAlign: "center", minHeight: 320 }}>
        <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>drop / paste</div>
        <div style={{ fontSize: 22, fontWeight: 600, marginTop: 12, letterSpacing: "-0.01em" }}>{T.importDrop}</div>
        <div style={{ fontSize: 12, color: "var(--text-3)", marginTop: 6, fontFamily: "var(--font-mono)" }}>{T.importHint}</div>
        <div style={{ display: "flex", gap: 8, marginTop: 18 }}>
          <window.Btn kind="primary" size="md">{T.importFile}</window.Btn>
          <window.Btn kind="ghost" size="md">{T.importPaste}</window.Btn>
        </div>
        <div style={{ marginTop: 18, padding: 12, border: "1px solid var(--line-strong)", width: "100%", maxWidth: 380, background: "var(--bg)", textAlign: "left", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)", lineHeight: 1.7 }}>
          <div>[Interface]</div>
          <div>PrivateKey = ████████████████████</div>
          <div>Address    = 10.66.0.2/24</div>
          <div>DNS        = 1.1.1.1</div>
          <div style={{ marginTop: 4 }}>[Peer]</div>
          <div>PublicKey  = ████████████████████</div>
          <div>Endpoint   = 127.0.0.1:8443</div>
          <div>Wstunnel   = wss://vps.fcrespo.dev:443</div>
          <div>Pin        = sha256:4f9a1c7e…</div>
        </div>
      </div>

      <div style={{ display: "flex", flexDirection: "column", gap: 10 }}>
        <ProfileRow active name="Universidad" host="vps.fcrespo.dev" status="connected"/>
        <ProfileRow         name="Casa"         host="home.fcrespo.dev" status="off"/>
        <ProfileRow         name="Cafe-Wifi"    host="89.32.144.19"   status="off"/>

        <div style={{ marginTop: 6, border: "1px solid var(--line-strong)", padding: 14, background: "var(--bg-2)" }}>
          <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>{T.importQR}</div>
          <div style={{ display: "grid", gridTemplateColumns: "auto 1fr", gap: 14, marginTop: 10, alignItems: "center" }}>
            <div style={{ background: "#fff", padding: 6, border: "1px solid var(--line-strong)" }}><FakeQRB/></div>
            <div style={{ fontSize: 12, color: "var(--text-2)", lineHeight: 1.5, fontFamily: "var(--font-mono)" }}>
              <code style={{ color: "var(--text)" }}>outwarp-server</code><br/>
              <code style={{ color: "var(--text)" }}>  add-client &lt;name&gt; --qr</code>
            </div>
          </div>
        </div>
      </div>
    </div>
  </div>
);

const ProfileRow = ({ active, name, host, status }) => (
  <div style={{ border: "1px solid var(--line-strong)", padding: 14, background: "var(--bg-2)", display: "grid", gridTemplateColumns: "auto 1fr auto auto", gap: 12, alignItems: "center" }}>
    <window.StatusDot tone={status === "connected" ? "good" : "neutral"} pulse={status === "connected"}/>
    <div>
      <div style={{ fontSize: 13, fontWeight: 600, display: "flex", alignItems: "center", gap: 8 }}>
        {name}
        {active && <span style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--brand)", padding: "1px 6px", border: "1px solid var(--brand)" }}>ACTIVE</span>}
      </div>
      <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{host}</div>
    </div>
    <window.Btn kind="ghost" size="sm">EDIT</window.Btn>
    <window.Btn kind="ghost" size="sm">⋯</window.Btn>
  </div>
);

// ── LOGS ────────────────────────────────────────────────────────
const LogsB = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%", minHeight: 0 }}>
    <HeaderB T={T} k="03" title={T.logs_title} sub="outwarp-client · stdout + stderr · live tail"
      right={
        <>
          <input placeholder={T.logs_filter} style={{
            height: 28, padding: "0 10px", border: "1px solid var(--line-strong)",
            background: "var(--bg-2)", color: "var(--text)", fontFamily: "var(--font-mono)", fontSize: 12, width: 200, outline: "none", borderRadius: 0,
          }}/>
          <window.Pill tone="good">INFO</window.Pill>
          <window.Pill tone="neutral">DEBUG</window.Pill>
          <window.Pill tone="bad">ERROR</window.Pill>
          <window.Btn kind="ghost" size="sm">{T.logs_export}</window.Btn>
          <window.Btn kind="ghost" size="sm">{T.logs_clear}</window.Btn>
        </>
      }/>
    <div style={{
      border: "1px solid var(--line-strong)", background: "var(--bg-2)",
      fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.7,
      padding: 14, color: "var(--text-2)", overflow: "auto", flex: 1, minHeight: 360,
    }} className="ws-scroll">
      {window.SAMPLE_LOGS.map((l, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "92px 56px 1fr", gap: 10 }}>
          <span style={{ color: "var(--text-3)" }}>{l.t}</span>
          <span style={{ color: l.lvl === "info" ? "var(--brand-2)" : l.lvl === "debug" ? "var(--text-3)" : "var(--brand-bad)" }}>{l.lvl.toUpperCase()}</span>
          <span style={{ color: "var(--text)" }}>{l.msg}</span>
        </div>
      ))}
      <div style={{ marginTop: 4, color: "var(--brand)" }}>
        <span style={{ display: "inline-block", width: 8, height: 14, background: "var(--brand)", animation: "ws-blink 1s steps(2,end) infinite" }}/>
      </div>
    </div>
  </div>
);

// ── SETTINGS ────────────────────────────────────────────────────
const SettingsB = ({ T }) => {
  const Row = ({ k, label, sub, control }) => (
    <div style={{ display: "grid", gridTemplateColumns: "60px 1fr auto", gap: 14, alignItems: "center", padding: "14px 16px", borderTop: "1px dashed var(--line-strong)" }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)" }}>{k}</div>
      <div>
        <div style={{ fontSize: 13, fontWeight: 500 }}>{label}</div>
        {sub && <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
      </div>
      <div>{control}</div>
    </div>
  );
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 760 }}>
      <HeaderB T={T} k="04" title={T.nav_settings} sub="outwarp-client · v0.4.2"/>

      <div style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
        <Row k="0x01" label={T.set_killSwitch}    sub={T.set_killSwitchSub}   control={<window.Toggle on/>}/>
        <Row k="0x02" label={T.set_autoconnect}   sub={T.set_autoconnectSub}  control={<window.Toggle on/>}/>
        <Row k="0x03" label={T.set_splitTunnel}   sub={T.set_splitTunnelSub}  control={<window.Btn kind="ghost" size="sm">CONFIG</window.Btn>}/>
        <Row k="0x04" label={T.set_minimizeTray}                              control={<window.Toggle on/>}/>
        <Row k="0x05" label={T.set_advanced}      sub={T.set_advancedSub}     control={<window.Toggle on/>}/>
      </div>

      <div style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
        <Row k="0x06" label={T.set_dns}  control={<input defaultValue="1.1.1.1, 9.9.9.9" style={{ width: 220, height: 30, padding: "0 10px", border: "1px solid var(--line-strong)", background: "var(--bg)", color: "var(--text)", fontFamily: "var(--font-mono)", fontSize: 12, borderRadius: 0 }}/>}/>
        <Row k="0x07" label={T.set_mtu}  control={<input defaultValue="1280"            style={{ width: 90,  height: 30, padding: "0 10px", border: "1px solid var(--line-strong)", background: "var(--bg)", color: "var(--text)", fontFamily: "var(--font-mono)", fontSize: 12, borderRadius: 0 }}/>}/>
      </div>
    </div>
  );
};

// ── Atoms ───────────────────────────────────────────────────────
const Mono = ({ label, value, sub, border }) => (
  <div style={{ padding: "10px 0", borderTop: border ? "1px dashed var(--line-strong)" : "none", paddingRight: 14 }}>
    <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>{label}</div>
    <div style={{ fontSize: 18, fontFamily: "var(--font-mono)", fontWeight: 600, marginTop: 4 }}>{value}</div>
    {sub && <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
  </div>
);

const KV = ({ k, v, last }) => (
  <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 12, padding: "8px 14px", borderBottom: last ? "none" : "1px dashed var(--line-strong)" }}>
    <span style={{ color: "var(--text-3)" }}>{k}</span>
    <span style={{ color: "var(--text)" }}>{v}</span>
  </div>
);

const BarMatrix = () => {
  const N = 60;
  const arr = Array.from({ length: N }, (_, i) => 0.2 + 0.7 * Math.abs(Math.sin(i / 4 + 0.7)) * (1 - i / 200));
  return (
    <div>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 96 }}>
        {arr.map((v, i) => (
          <div key={i} style={{ flex: 1, height: `${v*100}%`, background: i > N-6 ? "var(--brand)" : "color-mix(in srgb, var(--brand) 55%, transparent)" }}/>
        ))}
      </div>
      <div style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", marginTop: 10, fontFamily: "var(--font-mono)", fontSize: 11 }}>
        <Mono label="rx total" value="19.7 MB"/>
        <Mono label="tx total" value="2.1 MB"/>
        <Mono label="hs"       value="42 s ago"/>
        <Mono label="rtt p50"  value="42 ms"/>
      </div>
    </div>
  );
};

const FakeQRB = () => (
  <svg viewBox="0 0 21 21" width="100" height="100" shapeRendering="crispEdges">
    {Array.from({ length: 21 }).flatMap((_, y) => Array.from({ length: 21 }).map((_, x) => {
      const seed = (x * 41 + y * 23 + 11) % 17;
      const isFinder = (x < 7 && y < 7) || (x > 13 && y < 7) || (x < 7 && y > 13);
      const fill = isFinder ? ((Math.abs(x - (x>13?17:3)) <= 1 && Math.abs(y - (y>13?17:3)) <= 1) ? 1 : (Math.abs(x - (x>13?17:3)) === 3 || Math.abs(y - (y>13?17:3)) === 3) ? 1 : 0) : (seed > 8 ? 1 : 0);
      return fill ? <rect key={`${x}-${y}`} x={x} y={y} width="1" height="1" fill="#0a0d12"/> : null;
    }))}
  </svg>
);

// Icons (B-prefixed to avoid clashes with var-a)
const Ic = (d, s = 16) => <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{d}</svg>;
const IcHome    = ({ size }) => Ic(<><path d="M3 11 L12 3 L21 11"/><path d="M5 10 V20 H19 V10"/></>, size);
const IcProfile = ({ size }) => Ic(<><circle cx="12" cy="8" r="4"/><path d="M4 21 C4 16 8 14 12 14 C16 14 20 16 20 21"/></>, size);
const IcLogs    = ({ size }) => Ic(<><path d="M5 4 H19 V20 H5 Z"/><path d="M8 8 H16 M8 12 H16 M8 16 H13"/></>, size);
const IcCog     = ({ size }) => Ic(<><circle cx="12" cy="12" r="3"/><path d="M12 2 V4 M12 20 V22 M2 12 H4 M20 12 H22 M5 5 L6.5 6.5 M17.5 17.5 L19 19 M5 19 L6.5 17.5 M17.5 6.5 L19 5"/></>, size);
const IcBolt    = ({ size }) => Ic(<path d="M13 2 L4 14 H11 L9 22 L20 9 H13 Z"/>, size);

window.VarB = VarB;
