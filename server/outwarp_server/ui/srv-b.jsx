// Server Variation B — dev mode (matches client VarB chassis)
const SrvB = ({ tweaks }) => {
  const lang = tweaks.language || "es";
  const T = window.SRV_STR[lang];
  const theme = tweaks.theme === "dark" ? "dark" : "light";
  const screen = tweaks.screenSrvB || "dashboard";

  return (
    <window.WindowsFrame width={1180} height={780} title="outwarp-server — dev mode" theme={theme} accent="#2563ff">
      <div data-theme={theme} style={{ display: "grid", gridTemplateColumns: "240px 1fr", height: "100%", background: "var(--bg)", color: "var(--text)", fontFamily: "var(--font-sans)" }}>
        <SrvSidebarB T={T} screen={screen}/>
        <main style={{ overflow: "auto", padding: "28px 36px 36px", display: "flex", flexDirection: "column", minHeight: 0 }} className="ws-scroll">
          {screen === "dashboard" && <SrvDashB T={T}/>}
          {screen === "clients"   && <SrvClientsB T={T}/>}
          {screen === "service"   && <SrvServiceB T={T}/>}
          {screen === "logs"      && <SrvLogsB T={T}/>}
          {screen === "settings"  && <SrvSettingsB T={T}/>}
        </main>
      </div>
    </window.WindowsFrame>
  );
};

const SrvSidebarB = ({ T, screen }) => {
  const items = [
    { id: "dashboard", label: T.nav_dashboard },
    { id: "clients",   label: T.nav_clients },
    { id: "service",   label: T.nav_service },
    { id: "logs",      label: T.nav_logs },
    { id: "settings",  label: T.nav_settings },
  ];
  return (
    <aside style={{ background: "var(--bg-2)", borderRight: "1px solid var(--line-strong)", display: "flex", flexDirection: "column", padding: "22px 14px" }}>
      <div style={{ padding: "0 8px 4px" }}>
        <window.WSWordmark size={16} color="var(--text)" accent="var(--brand)"/>
      </div>
      <div style={{ padding: "0 8px 18px", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase" }}>
        server · dev mode · v0.4.2
      </div>
      <div style={{ display: "flex", flexDirection: "column" }}>
        {items.map((it, i) => {
          const a = it.id === screen;
          return (
            <div key={it.id} style={{
              display: "grid", gridTemplateColumns: "1fr auto", alignItems: "center",
              padding: "10px 10px",
              borderLeft: a ? "2px solid var(--brand)" : "2px solid transparent",
              background: a ? "var(--chip)" : "transparent",
              fontSize: 13, fontWeight: 500,
              color: a ? "var(--text)" : "var(--text-2)",
            }}>
              <span>{it.label}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)" }}>0{i+1}</span>
            </div>
          );
        })}
      </div>
      <div style={{ marginTop: "auto", border: "1px solid var(--line-strong)", padding: 12, background: "var(--bg-sunk)", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", lineHeight: 1.7 }}>
        <div style={{ display: "flex", alignItems: "center", gap: 8, color: "var(--text)", fontSize: 12, fontWeight: 600, marginBottom: 6, fontFamily: "var(--font-sans)" }}>
          <window.StatusDot tone="good"/> {T.running}
        </div>
        <div>host vps.fcrespo.dev</div>
        <div>ip   89.32.144.19</div>
        <div>port 443/wss</div>
        <div>peers 4/7</div>
        <div>uptime 12d 04h</div>
      </div>
    </aside>
  );
};

const HeaderB = ({ k, title, sub, right }) => (
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

const SrvDashB = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 20 }}>
    <HeaderB k="01" title={T.nav_dashboard} sub="vps.fcrespo.dev · 89.32.144.19 · TUNNEL UP"
      right={<window.Btn kind="primary" size="sm">+ {T.addClient}</window.Btn>}/>

    <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "1.2fr 1fr" }}>
        <div style={{ padding: "22px 24px", borderRight: "1px solid var(--line-strong)" }}>
          <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>peers online</div>
          <div style={{ fontSize: 38, fontWeight: 600, fontFamily: "var(--font-mono)", letterSpacing: "-0.02em", marginTop: 4 }}>4 <span style={{ color: "var(--text-3)" }}>/ 7</span></div>
          <div style={{ display: "grid", gridTemplateColumns: "repeat(2,1fr)", marginTop: 18 }}>
            <Mono label={T.metric_uptime} value="12d 04h" sub="since 2026-04-17"/>
            <Mono label={T.metric_traffic} value="2.13 GB" sub="last 24h"/>
            <Mono label="rx 24h" value="1.78 GB" border/>
            <Mono label="tx 24h" value="358 MB" border/>
          </div>
        </div>
        <div style={{ padding: "22px 24px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
          <div>
            <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>aggregate throughput · 60s</div>
            <BarMatrix/>
          </div>
        </div>
      </div>
    </section>

    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 16 }}>
      <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line-strong)", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>service status</div>
        <div style={{ padding: 14, fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.8 }}>
          <KV k="wstunnel" v="active · pid 2114 · 38 MB"/>
          <KV k="wg-quick" v="active · wg0 up · 4 peers"/>
          <KV k="cert.fp"  v="sha256:4f9a1c7eb3d2…"/>
          <KV k="port"     v="443/wss" last/>
        </div>
      </section>
      <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
        <div style={{ padding: "10px 14px", borderBottom: "1px solid var(--line-strong)", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>active peers</div>
        <div style={{ padding: "8px 14px", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)" }}>
          {window.SAMPLE_CLIENTS.filter(c => c.online).map((c, i) => (
            <div key={c.name} style={{ display: "grid", gridTemplateColumns: "auto 1fr 1fr 1fr", gap: 8, padding: "5px 0" }}>
              <window.StatusDot tone="good"/>
              <span>{c.name}</span>
              <span style={{ color: "var(--text-3)" }}>{c.ip}</span>
              <span style={{ color: "var(--brand-2)" }}>↓{c.rx} ↑{c.tx}</span>
            </div>
          ))}
        </div>
      </section>
    </div>
  </div>
);

const SrvClientsB = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
    <HeaderB k="02" title={T.nav_clients}
      sub={`${window.SAMPLE_CLIENTS.length} total · ${window.SAMPLE_CLIENTS.filter(c=>c.online).length} online`}
      right={<window.Btn kind="primary" size="sm">+ {T.addClient}</window.Btn>}/>
    <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
      <div style={{ display: "grid", gridTemplateColumns: "auto 1.4fr 1fr 1fr 1fr 1fr auto", padding: "10px 14px", borderBottom: "1px solid var(--line-strong)", fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>
        <span/><span>name</span><span>ip</span><span>last_hs</span><span>rx</span><span>tx</span><span/>
      </div>
      {window.SAMPLE_CLIENTS.map((c, i) => (
        <div key={c.name} style={{ display: "grid", gridTemplateColumns: "auto 1.4fr 1fr 1fr 1fr 1fr auto", padding: "10px 14px", borderBottom: i === window.SAMPLE_CLIENTS.length - 1 ? "none" : "1px dashed var(--line-strong)", alignItems: "center", fontFamily: "var(--font-mono)", fontSize: 12 }}>
          <window.StatusDot tone={c.online ? "good" : "neutral"} pulse={c.online}/>
          <div style={{ paddingLeft: 10 }}>
            <div style={{ fontWeight: 600, fontFamily: "var(--font-sans)" }}>{c.name}</div>
            <div style={{ fontSize: 10, color: "var(--text-3)" }}>{c.endpoint}</div>
          </div>
          <span style={{ color: "var(--text-2)" }}>{c.ip}</span>
          <span style={{ color: c.online ? "var(--brand-2)" : "var(--text-3)" }}>{c.hs}</span>
          <span style={{ color: "var(--text-2)" }}>{c.rx}</span>
          <span style={{ color: "var(--text-2)" }}>{c.tx}</span>
          <div style={{ display: "flex", gap: 4 }}>
            <window.Btn kind="ghost" size="sm">QR</window.Btn>
            <window.Btn kind="ghost" size="sm">CFG</window.Btn>
            <window.Btn kind="ghost" size="sm">×</window.Btn>
          </div>
        </div>
      ))}
    </section>
  </div>
);

const SrvServiceB = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 18 }}>
    <HeaderB k="03" title={T.nav_service} sub="systemctl status · live"/>
    <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }}>
      {[
        { name: T.service_wstunnel, pid: 2114, mem: "38 MB", sub: "Listening :443 (TLS) · 12d 04h" },
        { name: T.service_wg,       pid: 2151, mem: "—",     sub: "wg0 up · 4 peers handshaking" },
      ].map(s => (
        <div key={s.name} style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
          <div style={{ display: "flex", alignItems: "center", justifyContent: "space-between", padding: "10px 14px", borderBottom: "1px dashed var(--line-strong)" }}>
            <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
              <window.StatusDot tone="good"/>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 13, fontWeight: 600 }}>{s.name}</span>
            </div>
            <window.Pill tone="good">ACTIVE</window.Pill>
          </div>
          <div style={{ padding: 14, fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)", lineHeight: 1.8 }}>
            <div style={{ color: "var(--text-3)" }}>● {s.sub}</div>
            <div>pid {s.pid} · mem {s.mem}</div>
          </div>
        </div>
      ))}
    </div>
    <section style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)", padding: 16 }}>
      <div style={{ fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em", marginBottom: 10 }}>actions</div>
      <div style={{ display: "flex", flexWrap: "wrap", gap: 8 }}>
        <window.Btn kind="ghost" size="sm">SYSTEMCTL RESTART WSTUNNEL</window.Btn>
        <window.Btn kind="ghost" size="sm">SYSTEMCTL RESTART WG-QUICK@WG0</window.Btn>
        <window.Btn kind="ghost" size="sm">REGEN CONFIG</window.Btn>
        <window.Btn kind="danger" size="sm">UNINSTALL</window.Btn>
      </div>
    </section>
  </div>
);

const SrvLogsB = ({ T }) => (
  <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%", minHeight: 0 }}>
    <HeaderB k="04" title={T.logs_title} sub={T.logs_sub}
      right={<>
        <input placeholder="filter…" style={{ height: 28, padding: "0 10px", border: "1px solid var(--line-strong)", background: "var(--bg-2)", color: "var(--text)", fontFamily: "var(--font-mono)", fontSize: 12, width: 200, outline: "none", borderRadius: 0 }}/>
        <window.Pill tone="good">INFO</window.Pill>
        <window.Pill tone="warn">WARN</window.Pill>
        <window.Pill tone="bad">ERROR</window.Pill>
      </>}/>
    <div style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)", fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.7, padding: 14, color: "var(--text-2)", overflow: "auto", flex: 1, minHeight: 360 }} className="ws-scroll">
      {window.SAMPLE_SRV_LOGS.map((l, i) => (
        <div key={i} style={{ display: "grid", gridTemplateColumns: "92px 130px 56px 1fr", gap: 10 }}>
          <span style={{ color: "var(--text-3)" }}>{l.t}</span>
          <span style={{ color: "var(--brand)" }}>{l.svc}</span>
          <span style={{ color: l.lvl === "info" ? "var(--brand-2)" : l.lvl === "warn" ? "var(--brand-warn)" : l.lvl === "error" ? "var(--brand-bad)" : "var(--text-3)" }}>{l.lvl.toUpperCase()}</span>
          <span style={{ color: "var(--text)" }}>{l.msg}</span>
        </div>
      ))}
      <div style={{ marginTop: 4, color: "var(--brand)" }}><span style={{ display: "inline-block", width: 8, height: 14, background: "var(--brand)", animation: "ws-blink 1s steps(2,end) infinite" }}/></div>
    </div>
  </div>
);

const SrvSettingsB = ({ T }) => {
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
  const inp = { width: 220, height: 30, padding: "0 10px", border: "1px solid var(--line-strong)", background: "var(--bg)", color: "var(--text)", fontFamily: "var(--font-mono)", fontSize: 12, borderRadius: 0 };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 18, maxWidth: 800 }}>
      <HeaderB k="05" title={T.nav_settings} sub="outwarp-server · v0.4.2"/>
      <div style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)" }}>
        <Row k="0x01" label={T.set_port}   control={<input defaultValue="443" style={{...inp, width: 100}}/>}/>
        <Row k="0x02" label={T.set_iface}  control={<input defaultValue="wg0" style={{...inp, width: 100}}/>}/>
        <Row k="0x03" label={T.set_subnet} control={<input defaultValue="10.66.0.0/24" style={{...inp, width: 180}}/>}/>
        <Row k="0x04" label={T.set_domain} sub={T.set_domainSub} control={<input placeholder="(opcional)" style={inp}/>}/>
      </div>
      <div style={{ border: "1px solid var(--line-strong)", background: "var(--bg-2)", padding: 16 }}>
        <div style={{ fontSize: 13, fontWeight: 600 }}>{T.set_cert}</div>
        <div style={{ fontSize: 11, color: "var(--text-3)", marginTop: 2 }}>{T.set_certSub}</div>
        <div style={{ marginTop: 10, padding: 10, background: "var(--bg-sunk)", border: "1px dashed var(--line-strong)", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-2)", wordBreak: "break-all" }}>
          sha256:4f:9a:1c:7e:b3:d2:8a:55:c1:92:7e:34:ab:55:01:e8:ff:21:cc:a0:14:9d:bb:60:8c:dd:4e:ff:71:02:a1:33
        </div>
        <div style={{ display: "flex", gap: 8, marginTop: 10 }}>
          <window.Btn kind="ghost" size="sm">COPY FP</window.Btn>
          <window.Btn kind="danger" size="sm">REGEN CERT</window.Btn>
        </div>
      </div>
    </div>
  );
};

// shared atoms reused from VarB style
const Mono = ({ label, value, sub, border }) => (
  <div style={{ padding: "10px 0", borderTop: border ? "1px dashed var(--line-strong)" : "none", paddingRight: 14 }}>
    <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".1em" }}>{label}</div>
    <div style={{ fontSize: 18, fontFamily: "var(--font-mono)", fontWeight: 600, marginTop: 4 }}>{value}</div>
    {sub && <div style={{ fontSize: 10, fontFamily: "var(--font-mono)", color: "var(--text-3)", marginTop: 2 }}>{sub}</div>}
  </div>
);
const KV = ({ k, v, last }) => (
  <div style={{ display: "grid", gridTemplateColumns: "100px 1fr", gap: 12, padding: "6px 0", borderBottom: last ? "none" : "1px dashed var(--line-strong)" }}>
    <span style={{ color: "var(--text-3)" }}>{k}</span>
    <span style={{ color: "var(--text)" }}>{v}</span>
  </div>
);
const BarMatrix = () => {
  const N = 60;
  const arr = Array.from({ length: N }, (_, i) => 0.2 + 0.7 * Math.abs(Math.sin(i / 4 + 0.7)) * (1 - i / 200));
  return (
    <div style={{ marginTop: 8 }}>
      <div style={{ display: "flex", alignItems: "flex-end", gap: 2, height: 96 }}>
        {arr.map((v, i) => (
          <div key={i} style={{ flex: 1, height: `${v*100}%`, background: i > N-6 ? "var(--brand)" : "color-mix(in srgb, var(--brand) 55%, transparent)" }}/>
        ))}
      </div>
    </div>
  );
};

window.SrvB = SrvB;
