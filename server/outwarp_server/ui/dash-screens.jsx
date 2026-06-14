// OutWarp Server dashboard — screens (wired to the real Api via C.call).
const { Card, SLabel, PageHead, Btn, Pill, Dot, Toggle, Segmented, Stat, Field, Input,
        Sparkline, AreaChart, BarSeries, Donut, KV, Icons, useUI } = window;
const { fmtBytes, fmtBps, fmtDuration, fmtAgo, tr } = window.DSfmt;

const stateTone = (s) => s === "online" ? "good" : s === "idle" ? "warn" : "neutral";

const MiniKV = ({ k, v, last }) => (
  <div style={{ display: "grid", gridTemplateColumns: "82px 1fr", gap: 8, padding: "5px 0", borderBottom: last ? "none" : "1px solid var(--line)" }}>
    <span style={{ color: "var(--text-3)" }}>{k}</span>
    <span style={{ color: "var(--text)", wordBreak: "break-all" }}>{v}</span>
  </div>
);

const shortFp = (fp) => {
  if (!fp || fp === "—") return "—";
  const parts = fp.split(":");
  return parts.length > 6 ? `${parts.slice(0, 3).join(":")}…${parts.slice(-1)}` : fp;
};

function deriveServices(status) {
  const running = !!(status && status.status === "running");
  return [
    { id: "wstunnel", name: "wstunnel", running },
    { id: "wg", name: "wg-quick@wg0", running },
  ];
}

// traffic history fetch — backed by Api.get_traffic_history(window) (Fase 4).
function useTraffic(C, win) {
  const [data, setData] = React.useState(null);
  React.useEffect(() => {
    let alive = true;
    C.call("get_traffic_history", win).then((d) => { if (alive && d && !d.error) setData(d); }).catch(() => {});
    return () => { alive = false; };
  }, [win]);
  return data;
}

// ════════════════════════ DASHBOARD ════════════════════════════════════
function ScreenDashboard({ C }) {
  const ui = useUI();
  const { T, live, server, go } = C;
  const online = live.totals.online, idle = live.totals.idle, offline = live.totals.offline;
  const total = online + idle + offline;
  const services = deriveServices(live.status);
  const traffic = useTraffic(C, "24h");

  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ui.sectionGap }}>
      <PageHead title={T.dash_title} sub={server.host}
        right={<Btn kind="primary" icon={Icons.plus(16)} onClick={() => C.openAdd()}>{T.clients_add}</Btn>} />

      {/* Hero health */}
      <Card lg style={{ position: "relative", overflow: "hidden" }}>
        <div style={{ display: "grid", gridTemplateColumns: "auto 1fr auto", gap: 22, alignItems: "center" }} className="dash-hero">
          <Donut size={96} stroke={13} center={
            <div>
              <div style={{ fontSize: 26, fontWeight: 700, fontFamily: "var(--font-mono)", lineHeight: 1 }}>{online}</div>
              <div style={{ fontSize: 9.5, color: "var(--text-3)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: ".1em" }}>online</div>
            </div>}
            segments={[
              { value: online, color: "var(--brand-2)" },
              { value: idle, color: "var(--brand-warn)" },
              { value: Math.max(offline, total === 0 ? 1 : 0), color: "var(--line-strong)" },
            ]} />
          <div style={{ minWidth: 0 }}>
            <div style={{ display: "flex", alignItems: "center", gap: 9, marginBottom: 8 }}>
              <Dot tone={live.status && live.status.status === "running" ? "good" : "neutral"} pulse={!!(live.status && live.status.status === "running")} />
              <span style={{ fontSize: 12, fontWeight: 700, color: "var(--brand-2)", letterSpacing: ".08em", textTransform: "uppercase", fontFamily: "var(--font-mono)", whiteSpace: "nowrap" }}>
                {live.status && live.status.status === "running" ? T.running : T.stopped}
              </span>
            </div>
            <div style={{ fontSize: 30, fontWeight: 600, letterSpacing: "-0.02em", lineHeight: 1.05, fontFamily: ui.headFont }}>
              {online} / {total} <span style={{ color: "var(--text-3)", fontWeight: 500 }}>{T.dash_clientsOnline}</span>
            </div>
            <div style={{ fontSize: 12.5, color: "var(--text-2)", marginTop: 7, fontFamily: "var(--font-mono)" }}>
              wstunnel + wg-quick@wg0
            </div>
            <div style={{ display: "flex", gap: 7, marginTop: 12, flexWrap: "wrap" }}>
              <Pill tone="good">{Icons.check(13)} {T.dash_allHealthy}</Pill>
              {server.daysLeft !== "—" && <Pill tone="neutral">{tr(T.dash_daysLeft, { n: server.daysLeft })} · TLS</Pill>}
            </div>
          </div>
          <div style={{ textAlign: "right", fontFamily: "var(--font-mono)" }} className="dash-hero-traffic">
            <SLabel style={{ textAlign: "right" }}>{T.dash_traffic24}</SLabel>
            <div style={{ fontSize: 28, fontWeight: 600, marginTop: 6 }}>{traffic ? fmtBytes((traffic.rx_total || 0) + (traffic.tx_total || 0)) : "—"}</div>
            <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 2 }}>
              {traffic ? `↓ ${fmtBytes(traffic.rx_total || 0)} · ↑ ${fmtBytes(traffic.tx_total || 0)}` : "—"}
            </div>
          </div>
        </div>
        <div aria-hidden style={{ position: "absolute", right: -130, top: -110, width: 320, height: 320,
          background: "radial-gradient(circle, color-mix(in srgb, var(--brand) 16%, transparent), transparent 62%)", pointerEvents: "none" }} />
      </Card>

      {/* Live throughput */}
      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 12, flexWrap: "wrap", gap: 8 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10 }}>
            <SLabel>{T.dash_throughput}</SLabel>
            <Dot tone="good" pulse size={6} />
          </div>
          <div style={{ display: "flex", gap: 18, fontFamily: "var(--font-mono)", fontSize: 12.5 }}>
            <span style={{ color: "var(--brand)" }}>↓ {fmtBps(live.totals.rxBps)}</span>
            <span style={{ color: "var(--brand-2)" }}>↑ {fmtBps(live.totals.txBps)}</span>
          </div>
        </div>
        <AreaChart rx={live.rxSeries} tx={live.txSeries} h={150} />
        <div style={{ display: "flex", justifyContent: "space-between", marginTop: 6, fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--text-3)" }}>
          <span>-60s</span><span>{T.dash_now}</span>
        </div>
      </Card>

      {/* Status triad */}
      <div className="dash-triad" style={{ display: "grid", gridTemplateColumns: "repeat(3, 1fr)", gap: ui.gap }}>
        <Card>
          <SLabel style={{ marginBottom: 12 }}>{T.dash_services}</SLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 11 }}>
            {services.map((s) => (
              <div key={s.id} style={{ display: "flex", alignItems: "center", gap: 9 }}>
                <Dot tone={s.running ? "good" : "neutral"} />
                <span style={{ fontSize: 12.5, fontFamily: "var(--font-mono)", fontWeight: 600 }}>{s.name}</span>
                <span style={{ marginLeft: "auto", fontSize: 11, color: s.running ? "var(--brand-2)" : "var(--text-3)", fontFamily: "var(--font-mono)" }}>{s.running ? "active" : "inactive"}</span>
              </div>
            ))}
          </div>
        </Card>
        <Card>
          <SLabel style={{ marginBottom: 12 }}>{T.dash_network}</SLabel>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
            <MiniKV k={T.dash_endpoint} v={server.endpoint} />
            <MiniKV k={T.dash_subnet} v={server.subnet} />
            <MiniKV k={T.dash_wgListen} v={server.wgListen} />
            <MiniKV k={T.dash_nat} v={<span style={{ color: "var(--brand-2)" }}>MASQUERADE</span>} last />
          </div>
        </Card>
        <Card>
          <SLabel style={{ marginBottom: 12 }}>{T.dash_tls}</SLabel>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 12 }}>
            <MiniKV k={T.dash_fingerprint} v={shortFp(server.fingerprint)} />
            <MiniKV k={T.dash_validUntil} v={server.validUntil} />
            <MiniKV k={T.dash_transport} v="TLS 1.3 · ws" last />
          </div>
        </Card>
      </div>

      {/* Top talkers + active clients */}
      <div className="dash-split" style={{ display: "grid", gridTemplateColumns: "1fr 1.3fr", gap: ui.gap }}>
        <Card>
          <SLabel style={{ marginBottom: 14 }}>{T.dash_topTalkers}</SLabel>
          <div style={{ display: "flex", flexDirection: "column", gap: 13 }}>
            {[...live.clients].filter((c) => c.state !== "offline").sort((a, b) => b.rxTotal - a.rxTotal).slice(0, 4).map((c) => {
              const maxRx = Math.max(...live.clients.map((x) => x.rxTotal), 1);
              return (
                <div key={c.name} style={{ display: "grid", gridTemplateColumns: "1fr auto", gap: 8, alignItems: "center" }}>
                  <div style={{ minWidth: 0 }}>
                    <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 4 }}>
                      <span style={{ fontSize: 12.5, fontWeight: 600 }}>{c.name}</span>
                      <span style={{ fontSize: 11.5, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{fmtBytes(c.rxTotal)}</span>
                    </div>
                    <div style={{ height: 6, background: "var(--bg-sunk)", borderRadius: 3, overflow: "hidden" }}>
                      <div style={{ height: "100%", width: `${Math.max(4, (c.rxTotal / maxRx) * 100)}%`, background: "var(--brand)", borderRadius: 3 }} />
                    </div>
                  </div>
                </div>
              );
            })}
            {live.clients.filter((c) => c.state !== "offline").length === 0 &&
              <div style={{ color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 12 }}>—</div>}
          </div>
        </Card>
        <Card pad={0} style={{ overflow: "hidden" }}>
          <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: `${ui.cardPad}px ${ui.cardPad}px 12px` }}>
            <SLabel>{T.dash_activeClients}</SLabel>
            <button className="ow-link" onClick={() => go("clients")}>{T.dash_viewAll} →</button>
          </div>
          {live.clients.filter((c) => c.state !== "offline").slice(0, 5).map((c) => (
            <button key={c.name} className="ow-row" onClick={() => C.openClient(c.name)} style={{
              all: "unset", cursor: "pointer", display: "grid", gridTemplateColumns: "auto 1fr auto auto", gap: 11,
              alignItems: "center", padding: `10px ${ui.cardPad}px`, borderTop: "1px solid var(--line)", boxSizing: "border-box", width: "100%" }}>
              <Dot tone={stateTone(c.state)} pulse={c.state === "online"} />
              <div style={{ minWidth: 0 }}>
                <div style={{ fontSize: 12.5, fontWeight: 600 }}>{c.name}</div>
                <div style={{ fontSize: 10.5, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{c.ip}</div>
              </div>
              <Sparkline data={c.spark} w={56} h={20} color={c.state === "online" ? "var(--brand-2)" : "var(--text-3)"} />
              <div style={{ fontSize: 11, fontFamily: "var(--font-mono)", color: "var(--text-2)", textAlign: "right", whiteSpace: "nowrap" }}>↓{fmtBps(c.rxBps)}</div>
            </button>
          ))}
          {live.clients.filter((c) => c.state !== "offline").length === 0 &&
            <div style={{ padding: 24, textAlign: "center", color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 13, borderTop: "1px solid var(--line)" }}>—</div>}
        </Card>
      </div>
    </div>
  );
}

// ════════════════════════ CLIENTS ══════════════════════════════════════
function ScreenClients({ C }) {
  const ui = useUI();
  const { T, live } = C;
  const [q, setQ] = React.useState("");
  const [filter, setFilter] = React.useState("all");
  const filters = [
    { value: "all", label: T.filter_all },
    { value: "online", label: T.online },
    { value: "idle", label: T.idle },
    { value: "offline", label: T.offline },
  ];
  const rows = live.clients.filter((c) => {
    if (filter !== "all" && c.state !== filter) return false;
    if (q && !(`${c.name} ${c.ip}`.toLowerCase().includes(q.toLowerCase()))) return false;
    return true;
  });
  const online = live.totals.online;
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ui.gap }}>
      <PageHead title={T.clients_title}
        sub={tr(T.clients_sub, { total: live.clients.length, online })}
        right={<Btn kind="primary" icon={Icons.plus(16)} onClick={() => C.openAdd()}>{T.clients_add}</Btn>} />

      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: "1 1 240px", maxWidth: 360 }}>
          <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-3)", display: "inline-flex" }}>{Icons.search(15)}</span>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={T.clients_searchPh} style={{ paddingLeft: 34 }} />
        </div>
        <Segmented options={filters} value={filter} onChange={setFilter} />
      </div>

      <Card pad={0} style={{ overflow: "hidden" }}>
        <div className="cl-grid cl-head" style={{ padding: `11px ${ui.rowPadX}px`, borderBottom: "1px solid var(--line)", background: "var(--bg-sunk)" }}>
          <span />
          <span>{T.col_name}</span>
          <span className="cl-hide-sm">{T.col_ip}</span>
          <span className="cl-hide-sm">{T.col_handshake}</span>
          <span style={{ textAlign: "right" }}>{T.col_rx}</span>
          <span className="cl-hide-sm" style={{ textAlign: "right" }}>{T.col_tx}</span>
          <span className="cl-hide-md" style={{ textAlign: "center" }}>{T.col_throughput}</span>
          <span />
        </div>
        <div>
          {rows.map((c, i) => (
            <button key={c.name} className="cl-grid ow-rowbtn ow-row" onClick={() => C.openClient(c.name)} style={{
              boxSizing: "border-box", width: "100%", cursor: "pointer",
              padding: `${ui.rowPadY}px ${ui.rowPadX}px`, borderBottom: i === rows.length - 1 ? "none" : "1px solid var(--line)" }}>
              <Dot tone={stateTone(c.state)} pulse={c.state === "online"} />
              <div style={{ minWidth: 0 }}>
                <div style={{ display: "flex", alignItems: "center", gap: 7 }}>
                  <span style={{ color: "var(--text-3)", display: "inline-flex" }}>{Icons.device(c.device, 14)}</span>
                  <span style={{ fontSize: 13, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{c.name}</span>
                </div>
                <div className="cl-show-sm" style={{ fontSize: 10.5, color: "var(--text-3)", fontFamily: "var(--font-mono)", marginTop: 2 }}>{c.ip} · {fmtAgo(c.hsSec, C.lang)}</div>
              </div>
              <span className="cl-hide-sm" style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-2)" }}>{c.ip}</span>
              <span className="cl-hide-sm" style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: c.state === "online" ? "var(--brand-2)" : "var(--text-3)" }}>{fmtAgo(c.hsSec, C.lang)}</span>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-2)", textAlign: "right" }}>{fmtBytes(c.rxTotal)}</span>
              <span className="cl-hide-sm" style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--text-2)", textAlign: "right" }}>{fmtBytes(c.txTotal)}</span>
              <span className="cl-hide-md" style={{ display: "flex", justifyContent: "center" }}>
                <Sparkline data={c.spark} w={68} h={22} color={c.state === "online" ? "var(--brand-2)" : "var(--text-3)"} fill={c.state === "online"} />
              </span>
              <span style={{ color: "var(--text-3)", display: "flex", justifyContent: "flex-end" }}>{Icons.chevR(16)}</span>
            </button>
          ))}
          {rows.length === 0 && <div style={{ padding: 32, textAlign: "center", color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 13 }}>—</div>}
        </div>
      </Card>
    </div>
  );
}

// ════════════════════════ TRAFFIC ══════════════════════════════════════
function ScreenTraffic({ C }) {
  const ui = useUI();
  const { T, live } = C;
  const [win, setWin] = React.useState("24h");
  const windows = [
    { value: "1h", label: T.traffic_1h },
    { value: "24h", label: T.traffic_24h },
    { value: "7d", label: T.traffic_7d },
  ];
  const data = useTraffic(C, win);
  const rx = (data && data.rx_buckets) || [];
  const tx = (data && data.tx_buckets) || [];
  const perClient = (data && data.per_client) || [...live.clients].map((c) => ({ name: c.name, rx: c.rxTotal, tx: c.txTotal, state: c.state }));
  const maxRx = Math.max(...perClient.map((x) => x.rx), 1);
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ui.gap }}>
      <PageHead title={T.traffic_title} sub={T.traffic_sub}
        right={<Segmented options={windows} value={win} onChange={setWin} />} />

      <div className="dash-triad" style={{ display: "grid", gridTemplateColumns: "repeat(4, 1fr)", gap: ui.gap }}>
        <Stat label={T.traffic_rxTotal} value={data ? fmtBytes(data.rx_total || 0) : "—"} sub="↓ peers" tone="var(--brand)" />
        <Stat label={T.traffic_txTotal} value={data ? fmtBytes(data.tx_total || 0) : "—"} sub="↑ peers" tone="var(--brand-2)" />
        <Stat label={T.traffic_peak} value={data ? fmtBps(data.peak_bps || 0) : "—"} sub={win} />
        <Stat label={T.traffic_avg} value={data ? fmtBps(data.avg_bps || 0) : "—"} sub={win} />
      </div>

      <Card>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 14 }}>
          <SLabel>RX · {win}</SLabel>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--brand)" }}>↓ download</span>
        </div>
        {rx.length ? <BarSeries data={rx} h={120} color="var(--brand)" /> : <div style={{ color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 12 }}>—</div>}
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", margin: "22px 0 14px" }}>
          <SLabel>TX · {win}</SLabel>
          <span style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--brand-2)" }}>↑ upload</span>
        </div>
        {tx.length ? <BarSeries data={tx} h={90} color="var(--brand-2)" /> : <div style={{ color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 12 }}>—</div>}
      </Card>

      <Card>
        <SLabel style={{ marginBottom: 14 }}>{T.traffic_perClient}</SLabel>
        <div style={{ display: "flex", flexDirection: "column", gap: 12 }}>
          {[...perClient].sort((a, b) => b.rx - a.rx).map((c) => (
            <div key={c.name} style={{ display: "grid", gridTemplateColumns: "minmax(110px,1fr) 2fr auto", gap: 12, alignItems: "center" }}>
              <span style={{ fontSize: 12.5, fontWeight: 600, display: "flex", alignItems: "center", gap: 7 }}>
                <Dot tone={stateTone(c.state || "offline")} size={6} />{c.name}
              </span>
              <div style={{ height: 8, background: "var(--bg-sunk)", borderRadius: 4, overflow: "hidden" }}>
                <div style={{ height: "100%", width: `${Math.max(2, (c.rx / maxRx) * 100)}%`, background: c.state === "offline" ? "var(--text-3)" : "var(--brand)", borderRadius: 4 }} />
              </div>
              <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--text-2)", textAlign: "right", whiteSpace: "nowrap" }}>↓{fmtBytes(c.rx)} ↑{fmtBytes(c.tx)}</span>
            </div>
          ))}
        </div>
      </Card>
    </div>
  );
}

// ════════════════════════ SERVICE ══════════════════════════════════════
function ScreenService({ C }) {
  const ui = useUI();
  const { T, live } = C;
  const [busy, setBusy] = React.useState("");
  const services = deriveServices(live.status);
  const act = async (kind, confirmBody) => {
    if (confirmBody) { const ok = await C.confirm({ title: T[`service_${kind}`] || kind, body: confirmBody }); if (!ok) return; }
    setBusy(kind);
    try { await C.call(`${kind}_service`); await C.refresh(); } finally { setBusy(""); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ui.gap }}>
      <PageHead title={T.service_title} sub={T.service_sub} />
      <div className="svc-grid" style={{ display: "grid", gridTemplateColumns: "repeat(auto-fit, minmax(260px, 1fr))", gap: ui.gap }}>
        {services.map((s) => (
          <Card key={s.id}>
            <div style={{ display: "flex", alignItems: "center", gap: 9 }}>
              <Dot tone={s.running ? "good" : "neutral"} pulse={s.running} />
              <span style={{ fontSize: 13.5, fontWeight: 600, fontFamily: "var(--font-mono)" }}>{s.name}</span>
              <Pill tone={s.running ? "good" : "neutral"} style={{ marginLeft: "auto" }}>{s.running ? "active" : "inactive"}</Pill>
            </div>
            <div style={{ fontSize: 12, color: "var(--text-2)", marginTop: 10 }}>
              {s.running ? T.running : T.stopped}
            </div>
          </Card>
        ))}
      </div>
      <Card>
        <SLabel style={{ marginBottom: 14 }}>{T.service_actions}</SLabel>
        <div style={{ display: "flex", flexWrap: "wrap", gap: 9 }}>
          <Btn kind="primary" icon={Icons.power(15)} disabled={!!busy} onClick={() => act("start")}>{T.service_start}</Btn>
          <Btn icon={Icons.refresh(15)} disabled={!!busy} onClick={() => act("restart", T.service_confirmRestart)}>{T.service_restart}</Btn>
          <Btn kind="danger" icon={Icons.power(15)} disabled={!!busy} onClick={() => act("stop", T.service_confirmRestart)}>{T.service_stop}</Btn>
        </div>
      </Card>
    </div>
  );
}

// ════════════════════════ LOGS ═════════════════════════════════════════
function ScreenLogs({ C }) {
  const ui = useUI();
  const { T, live } = C;
  const [q, setQ] = React.useState("");
  const [level, setLevel] = React.useState("all");
  const [follow, setFollow] = React.useState(true);
  const scrollerRef = React.useRef(null);
  const levels = [
    { value: "all", label: T.filter_all },
    { value: "info", label: "info" },
    { value: "warn", label: "warn" },
    { value: "error", label: "error" },
    { value: "debug", label: "debug" },
  ];
  const rows = live.logs.filter((l) => {
    if (level !== "all" && l.lvl !== level) return false;
    if (q && !l.msg.toLowerCase().includes(q.toLowerCase())) return false;
    return true;
  });
  React.useEffect(() => {
    if (follow && scrollerRef.current) scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight;
  }, [live.logs.length, follow]);
  const lvlColor = (l) => l === "info" ? "var(--brand-2)" : l === "warn" ? "var(--brand-warn)" : l === "error" ? "var(--brand-bad)" : "var(--text-3)";
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: 14, height: "100%", minHeight: 0 }}>
      <PageHead title={T.logs_title} sub={T.logs_sub}
        right={<>
          <Segmented options={levels} value={level} onChange={setLevel} />
          <Btn size="sm" icon={Icons.download(14)} onClick={() => C.call("export_logs")}>{T.logs_export}</Btn>
          <Btn size="sm" kind="ghost" icon={Icons.trash(14)} onClick={async () => { await C.call("clear_logs"); }}>{T.logs_clear}</Btn>
        </>} />
      <div style={{ display: "flex", gap: 10, alignItems: "center", flexWrap: "wrap" }}>
        <div style={{ position: "relative", flex: "1 1 220px", maxWidth: 340 }}>
          <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-3)", display: "inline-flex" }}>{Icons.search(15)}</span>
          <Input value={q} onChange={(e) => setQ(e.target.value)} placeholder={T.logs_filterPh} mono style={{ paddingLeft: 34 }} />
        </div>
        <button className="ow-btn" onClick={() => setFollow((f) => !f)} style={{ all: "unset", cursor: "pointer", display: "inline-flex", alignItems: "center", gap: 7, fontFamily: "var(--font-mono)", fontSize: 12, color: follow ? "var(--brand-2)" : "var(--text-3)" }}>
          <Dot tone={follow ? "good" : "neutral"} pulse={follow} size={7} />{follow ? T.logs_following : T.logs_paused}
        </button>
        <span style={{ marginLeft: "auto", fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)" }}>{tr(T.logs_lines, { n: rows.length })}</span>
      </div>
      <Card pad={0} style={{ flex: 1, minHeight: 320, position: "relative", overflow: "hidden", display: "flex", flexDirection: "column" }}>
        <div ref={scrollerRef} className="ws-scroll" onScroll={(e) => {
          const el = e.target; const bottom = el.scrollHeight - el.scrollTop - el.clientHeight < 28;
          if (!bottom && follow) setFollow(false);
        }} style={{ flex: 1, overflow: "auto", fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.7, padding: 14 }}>
          {rows.map((l, i) => (
            <div key={i} className="log-line" style={{ display: "grid", gridTemplateColumns: "92px 52px 1fr", gap: 10 }}>
              <span style={{ color: "var(--text-3)" }}>{l.t}</span>
              <span style={{ color: lvlColor(l.lvl), textTransform: "uppercase" }}>{l.lvl}</span>
              <span style={{ color: "var(--text)", wordBreak: "break-word" }}>{l.msg}</span>
            </div>
          ))}
          <div style={{ marginTop: 4 }}><span style={{ display: "inline-block", width: 7, height: 13, background: "var(--brand)", animation: "ws-blink 1s steps(2,end) infinite", verticalAlign: "middle" }} /></div>
        </div>
        {!follow && (
          <button className="ow-btn" onClick={() => { setFollow(true); if (scrollerRef.current) scrollerRef.current.scrollTop = scrollerRef.current.scrollHeight; }}
            style={{ position: "absolute", right: 18, bottom: 18, padding: "7px 13px", borderRadius: 999, background: "var(--brand)", color: "#fff",
              fontSize: 12, fontWeight: 600, border: "none", cursor: "pointer", fontFamily: "var(--font-mono)",
              boxShadow: "0 6px 18px -6px color-mix(in srgb, var(--brand) 60%, transparent)", display: "flex", alignItems: "center", gap: 6 }}>
            ↓ {T.logs_jumpBottom}
          </button>
        )}
      </Card>
    </div>
  );
}

// ════════════════════════ DOCTOR ═══════════════════════════════════════
function ScreenDoctor({ C }) {
  const ui = useUI();
  const { T } = C;
  const [report, setReport] = React.useState(null);
  const [running, setRunning] = React.useState(false);
  const [applying, setApplying] = React.useState("");
  const run = React.useCallback(async () => {
    setRunning(true);
    try { setReport(await C.call("run_diagnostics")); } finally { setRunning(false); }
  }, []);
  React.useEffect(() => { run(); }, [run]);

  const norm = (st) => st === "pass" || st === "ok" ? "ok" : st === "warn" ? "warn" : st === "skip" ? "skip" : "fail";
  const checks = (report && report.checks) || [];
  const counts = checks.reduce((a, c) => { const k = norm(c.status); a[k] = (a[k] || 0) + 1; return a; }, { ok: 0, warn: 0, fail: 0 });
  const sIco = (st) => st === "ok" ? <span style={{ color: "var(--brand-2)" }}>{Icons.check(16)}</span>
    : st === "warn" ? <span style={{ color: "var(--brand-warn)" }}>{Icons.warn(16)}</span>
    : st === "skip" ? <span style={{ color: "var(--text-3)" }}>{Icons.check(16)}</span>
    : <span style={{ color: "var(--brand-bad)" }}>{Icons.fail(16)}</span>;
  const applyFix = async (name) => {
    setApplying(name);
    try { await C.call("apply_remediation", name); await run(); } finally { setApplying(""); }
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ui.gap }}>
      <PageHead title={T.doctor_title} sub={T.doctor_sub}
        right={<>
          <Pill tone="good">{counts.ok} {T.doctor_ok}</Pill>
          <Pill tone="warn">{counts.warn} {T.doctor_warn}</Pill>
          <Pill tone="bad">{counts.fail} {T.doctor_fail}</Pill>
          <Btn size="sm" icon={Icons.refresh(14)} disabled={running} onClick={run}>{T.doctor_rerun}</Btn>
        </>} />
      <Card pad={0} style={{ overflow: "hidden" }}>
        {checks.length === 0 && <div style={{ padding: 32, textAlign: "center", color: "var(--text-3)", fontFamily: "var(--font-mono)", fontSize: 13 }}>{running ? "…" : "—"}</div>}
        {checks.map((c, i) => {
          const st = norm(c.status);
          return (
            <div key={c.name} style={{ borderBottom: i === checks.length - 1 ? "none" : "1px solid var(--line)" }}>
              <div style={{ display: "grid", gridTemplateColumns: "auto minmax(120px, 200px) 1fr", gap: 12, alignItems: "center", padding: `${ui.rowPadY + 1}px ${ui.rowPadX}px` }}>
                {sIco(st)}
                <span style={{ fontSize: 13, fontWeight: 600, fontFamily: "var(--font-mono)" }}>{c.name}</span>
                <span style={{ fontSize: 12, color: "var(--text-2)", fontFamily: "var(--font-mono)", wordBreak: "break-word" }}>{c.detail}</span>
              </div>
              {c.remediation_command && (
                <div style={{ display: "flex", gap: 10, alignItems: "center", padding: `0 ${ui.rowPadX}px ${ui.rowPadY + 2}px 46px`, flexWrap: "wrap" }}>
                  <span style={{ fontFamily: "var(--font-mono)", fontSize: 11.5, color: st === "fail" ? "var(--brand-bad)" : "var(--brand-warn)", background: "var(--bg-sunk)", padding: "4px 9px", borderRadius: 5, wordBreak: "break-all" }}>
                    {T.doctor_fix}: {c.remediation_command}
                  </span>
                  {c.fix_kind === "auto" && (
                    <Btn size="sm" icon={Icons.bolt(13)} disabled={applying === c.name}
                      onClick={() => C.confirm({ title: T.doctor_applyFix, body: c.remediation_command, danger: true }).then((ok) => ok && applyFix(c.name))}>
                      {applying === c.name ? "…" : T.doctor_applyFix}
                    </Btn>
                  )}
                </div>
              )}
            </div>
          );
        })}
      </Card>
      <div style={{ display: "flex", justifyContent: "space-between", fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--text-3)", padding: "0 4px" }}>
        <span>{tr(T.doctor_checks, { n: checks.length })}</span>
      </div>
    </div>
  );
}

// ════════════════════════ SETTINGS ═════════════════════════════════════
function ScreenSettings({ C }) {
  const ui = useUI();
  const { T, server, appInfo } = C;
  const st = C.live.status || {};
  const [copied, setCopied] = React.useState(false);
  const [form, setForm] = React.useState({ port: st.port || "", wg: st.wg_listen_port || "", endpoint: st.endpoint || "", subnet: st.subnet || "" });
  React.useEffect(() => { setForm({ port: st.port || "", wg: st.wg_listen_port || "", endpoint: st.endpoint || "", subnet: st.subnet || "" }); }, [st.port, st.wg_listen_port, st.endpoint, st.subnet]);
  const copyFp = () => { navigator.clipboard?.writeText("sha256:" + server.fingerprint); setCopied(true); setTimeout(() => setCopied(false), 1600); };
  const apply = async () => {
    const ok = await C.confirm({ title: T.set_apply, body: T.service_confirmRestart });
    if (!ok) return;
    await C.call("update_server_config", { port: Number(form.port), wg_listen_port: Number(form.wg), endpoint: form.endpoint });
    await C.refresh();
  };
  const rotate = async () => {
    const ok = await C.confirm({ title: T.set_rotateCert, body: T.set_rotateCertSub, danger: true });
    if (!ok) return;
    await C.call("rotate_tls_cert"); await C.refresh();
  };
  return (
    <div style={{ display: "flex", flexDirection: "column", gap: ui.sectionGap, maxWidth: 760 }}>
      <PageHead title={T.settings_title} sub={`outwarp-server · v${appInfo.version || ""}`} />

      <div>
        <SLabel style={{ marginBottom: 9 }}>{T.set_serverCfg}</SLabel>
        <Card>
          <div style={{ fontSize: 12, color: "var(--text-3)", marginBottom: 14 }}>{T.set_serverCfgSub}</div>
          <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 14 }} className="set-grid">
            <Field label={T.set_port}><Input value={form.port} onChange={(e) => setForm((f) => ({ ...f, port: e.target.value }))} mono /></Field>
            <Field label={T.set_wgPort}><Input value={form.wg} onChange={(e) => setForm((f) => ({ ...f, wg: e.target.value }))} mono /></Field>
            <Field label={T.set_endpoint} style={{ gridColumn: "1 / -1" }}><Input value={form.endpoint} onChange={(e) => setForm((f) => ({ ...f, endpoint: e.target.value }))} mono /></Field>
            <Field label={T.set_subnet} style={{ gridColumn: "1 / -1" }}><Input value={form.subnet} readOnly mono style={{ opacity: 0.6 }} /></Field>
          </div>
          <div style={{ marginTop: 16 }}><Btn kind="primary" icon={Icons.check(15)} onClick={apply}>{T.set_apply}</Btn></div>
        </Card>
      </div>

      <div>
        <SLabel style={{ marginBottom: 9 }}>{T.set_cert}</SLabel>
        <Card>
          <div style={{ fontSize: 12, color: "var(--text-3)" }}>{T.set_certSub}</div>
          <div style={{ marginTop: 12, padding: 12, background: "var(--bg-sunk)", borderRadius: ui.radiusSm, fontFamily: "var(--font-mono)", fontSize: 11.5, color: "var(--text-2)", wordBreak: "break-all" }}>
            sha256:{server.fingerprint}
          </div>
          <div style={{ display: "flex", gap: 8, marginTop: 12, flexWrap: "wrap" }}>
            <Btn size="sm" icon={Icons.copy(14)} onClick={copyFp}>{copied ? T.copied + " ✓" : T.set_copyFp}</Btn>
            <Btn size="sm" kind="danger" icon={Icons.rotate(14)} onClick={rotate}>{T.set_rotateCert}</Btn>
          </div>
          <div style={{ fontSize: 11.5, color: "var(--text-3)", marginTop: 10, lineHeight: 1.5 }}>{T.set_rotateCertSub}</div>
        </Card>
      </div>

      <div>
        <SLabel style={{ marginBottom: 9 }}>{T.set_appearance}</SLabel>
        <Card style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
          <Field label={T.set_language} style={{ minWidth: 160 }}>
            <Segmented options={[{ value: "es", label: "ES" }, { value: "en", label: "EN" }]} value={C.lang} onChange={C.setLang} />
          </Field>
          <Field label={T.set_theme} style={{ minWidth: 160 }}>
            <Segmented options={[{ value: "light", label: T.set_themeLight }, { value: "dark", label: T.set_themeDark }]} value={C.theme} onChange={(v) => { if (v !== C.theme) C.toggleTheme(); }} />
          </Field>
        </Card>
      </div>

      {C.isWeb && (
        <div>
          <SLabel style={{ marginBottom: 9 }}>{T.set_session}</SLabel>
          <Card style={{ display: "flex", justifyContent: "space-between", alignItems: "center", gap: 14, flexWrap: "wrap" }}>
            <div>
              <div style={{ fontSize: 13, fontWeight: 600, fontFamily: "var(--font-mono)" }}>{T.remoteSession}</div>
              <div style={{ fontSize: 11.5, color: "var(--text-3)", marginTop: 2 }}>{T.set_sessionSub}</div>
            </div>
            <Btn kind="danger" size="sm" icon={Icons.lock(14)} onClick={() => C.signOut()}>{T.signOut}</Btn>
          </Card>
        </div>
      )}
    </div>
  );
}

Object.assign(window, { ScreenDashboard, ScreenClients, ScreenTraffic, ScreenService, ScreenLogs, ScreenDoctor, ScreenSettings });
