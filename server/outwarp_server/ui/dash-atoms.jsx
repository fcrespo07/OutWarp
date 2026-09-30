// OutWarp Web Dashboard — atoms, charts, icons (style-variant aware)
// Components read the active UI style from OWUIContext.

const OWUIContext = React.createContext(null);
const useUI = () => React.useContext(OWUIContext);

function styleTokens(style) {
  if (style === "tecnica") {
    return {
      style: "tecnica",
      radius: 3, radiusSm: 2, radiusLg: 4,
      border: "1px solid var(--line-strong)",
      cardPad: 14, gap: 12, sectionGap: 16, rowPadY: 8, rowPadX: 14,
      headFont: "var(--font-mono)", headWeight: 600, headSpacing: "0.01em",
      titleSize: 18, shadow: "none", mono: true,
      labelTransform: "uppercase",
    };
  }
  return {
    style: "pulida",
    radius: 14, radiusSm: 10, radiusLg: 18,
    border: "1px solid var(--line)",
    cardPad: 20, gap: 20, sectionGap: 24, rowPadY: 12, rowPadX: 16,
    headFont: "var(--font-sans)", headWeight: 600, headSpacing: "-0.02em",
    titleSize: 22, shadow: "var(--shadow)", mono: false,
    labelTransform: "uppercase",
  };
}

// ── Card ─────────────────────────────────────────────────────────────────
const Card = ({ children, pad, style = {}, lg, ...rest }) => {
  const ui = useUI();
  return (
    <section {...rest} style={{
      background: "var(--bg-2)", border: ui.border,
      borderRadius: lg ? ui.radiusLg : ui.radius,
      padding: pad != null ? pad : ui.cardPad,
      boxShadow: ui.shadow,
      ...style,
    }}>{children}</section>
  );
};

// ── Section label (small uppercase) ──────────────────────────────────────
const SLabel = ({ children, style = {} }) => (
  <div style={{ fontSize: 11, fontWeight: 600, color: "var(--text-3)", letterSpacing: ".09em", textTransform: "uppercase", fontFamily: "var(--font-mono)", ...style }}>{children}</div>
);

// ── Screen header ────────────────────────────────────────────────────────
const PageHead = ({ title, sub, right }) => {
  const ui = useUI();
  return (
    <header style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-end", gap: 16, flexWrap: "wrap" }}>
      <div style={{ minWidth: 0 }}>
        <h1 style={{ margin: 0, fontSize: ui.titleSize, fontWeight: ui.headWeight, letterSpacing: ui.headSpacing, fontFamily: ui.headFont, color: "var(--text)" }}>{title}</h1>
        {sub && <div style={{ fontSize: 12.5, color: "var(--text-3)", marginTop: 3, fontFamily: ui.mono ? "var(--font-mono)" : "var(--font-sans)" }}>{sub}</div>}
      </div>
      {right && <div style={{ display: "flex", gap: 8, alignItems: "center", flexWrap: "wrap" }}>{right}</div>}
    </header>
  );
};

// ── Button ───────────────────────────────────────────────────────────────
const Btn = ({ children, kind = "ghost", size = "md", icon, style = {}, ...rest }) => {
  const ui = useUI();
  const S = { sm: { h: 30, px: 11, fs: 12 }, md: { h: 36, px: 14, fs: 13 }, lg: { h: 44, px: 18, fs: 14 } }[size];
  const P = {
    primary: { bg: "var(--brand)", color: "#fff", border: "var(--brand)" },
    ghost:   { bg: "transparent", color: "var(--text)", border: "var(--line-strong)" },
    soft:    { bg: "var(--chip)", color: "var(--text)", border: "transparent" },
    danger:  { bg: "transparent", color: "var(--brand-bad)", border: "color-mix(in srgb, var(--brand-bad) 40%, transparent)" },
    solid:   { bg: "var(--text)", color: "var(--bg)", border: "var(--text)" },
  }[kind];
  return (
    <button {...rest} className="ow-btn" style={{
      height: S.h, padding: `0 ${S.px}px`, borderRadius: ui.radiusSm,
      background: P.bg, color: P.color, border: `1px solid ${P.border}`,
      fontFamily: ui.mono ? "var(--font-mono)" : "var(--font-sans)", fontSize: S.fs, fontWeight: 500,
      letterSpacing: ui.mono ? "0.01em" : "-0.005em", cursor: "pointer",
      display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 7, whiteSpace: "nowrap",
      transition: "filter .12s, background .12s", ...style,
    }}>{icon}{children}</button>
  );
};

// ── Pill / Dot ───────────────────────────────────────────────────────────
const Pill = ({ children, tone = "neutral", style = {} }) => {
  const ui = useUI();
  const T = {
    neutral: { bg: "var(--chip)", fg: "var(--text-2)" },
    good:    { bg: "color-mix(in srgb, var(--brand-2) 16%, transparent)", fg: "var(--brand-2)" },
    bad:     { bg: "color-mix(in srgb, var(--brand-bad) 16%, transparent)", fg: "var(--brand-bad)" },
    warn:    { bg: "color-mix(in srgb, var(--brand-warn) 18%, transparent)", fg: "var(--brand-warn)" },
    brand:   { bg: "color-mix(in srgb, var(--brand) 16%, transparent)", fg: "var(--brand)" },
  }[tone];
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap: 6, height: 22, padding: "0 9px",
      borderRadius: ui.mono ? 3 : 999, fontSize: 11, fontWeight: 600, fontFamily: "var(--font-mono)",
      background: T.bg, color: T.fg, letterSpacing: ".02em", whiteSpace: "nowrap", ...style }}>{children}</span>
  );
};

const Dot = ({ tone = "good", pulse = false, size = 8 }) => {
  const c = tone === "good" ? "var(--brand-2)" : tone === "bad" ? "var(--brand-bad)" : tone === "warn" ? "var(--brand-warn)" : "var(--text-3)";
  return (
    <span style={{ position: "relative", display: "inline-block", width: size, height: size, flex: "none" }}>
      {pulse && <span style={{ position: "absolute", inset: 0, borderRadius: 999, background: c, animation: "ws-pulse 1.8s ease-out infinite" }}/>}
      <span style={{ position: "absolute", inset: 0, borderRadius: 999, background: c }}/>
    </span>
  );
};

// ── Toggle ───────────────────────────────────────────────────────────────
const Toggle = ({ on, onChange, label }) => (
  <button type="button" role="switch" onClick={() => onChange?.(!on)} aria-checked={on} aria-label={label} className="ow-btn" style={{
    width: 38, height: 22, borderRadius: 999, padding: 2, border: "none",
    background: on ? "var(--brand)" : "var(--line-strong)", cursor: "pointer",
    display: "inline-flex", alignItems: "center", transition: "background .15s", flex: "none" }}>
    <span style={{ width: 18, height: 18, borderRadius: 999, background: "#fff",
      transform: on ? "translateX(16px)" : "translateX(0)", transition: "transform .15s",
      boxShadow: "0 1px 2px rgba(0,0,0,.3)" }}/>
  </button>
);

// ── Segmented control ────────────────────────────────────────────────────
const Segmented = ({ options, value, onChange }) => {
  const ui = useUI();
  return (
    <div role="group" style={{ display: "inline-flex", gap: 3, padding: 3, background: "var(--bg-sunk)", borderRadius: ui.radiusSm, border: ui.style === "tecnica" ? "1px solid var(--line)" : "none" }}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button key={o.value} type="button" aria-pressed={active} onClick={() => onChange(o.value)} className="ow-btn" style={{
            border: "none", cursor: "pointer", padding: "5px 12px", borderRadius: Math.max(2, ui.radiusSm - 2),
            fontSize: 12, fontWeight: 600, fontFamily: ui.mono ? "var(--font-mono)" : "var(--font-sans)",
            background: active ? "var(--bg-2)" : "transparent", color: active ? "var(--text)" : "var(--text-3)",
            boxShadow: active && ui.style === "pulida" ? "0 1px 2px rgba(0,0,0,.12)" : "none",
            whiteSpace: "nowrap" }}>{o.label}</button>
        );
      })}
    </div>
  );
};

// ── Stat card ────────────────────────────────────────────────────────────
const Stat = ({ label, value, sub, tone, spark }) => {
  const ui = useUI();
  return (
    <Card pad={ui.cardPad - 2} style={{ display: "flex", flexDirection: "column", gap: 6, minWidth: 0 }}>
      <SLabel>{label}</SLabel>
      <div style={{ fontSize: 24, fontWeight: 600, fontFamily: "var(--font-mono)", letterSpacing: "-0.01em", color: tone || "var(--text)", lineHeight: 1.05 }}>{value}</div>
      {spark}
      {sub && <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{sub}</div>}
    </Card>
  );
};

// ── Field (label + input) ────────────────────────────────────────────────
const Field = ({ label, children, style = {} }) => (
  <label style={{ display: "flex", flexDirection: "column", gap: 5, ...style }}>
    <span style={{ fontSize: 11, color: "var(--text-3)", textTransform: "uppercase", letterSpacing: ".06em", fontWeight: 600, fontFamily: "var(--font-mono)" }}>{label}</span>
    {children}
  </label>
);

const Input = (props) => {
  const ui = useUI();
  const { mono, style = {}, ...rest } = props;
  return (
    <input {...rest} style={{
      height: 36, padding: "0 12px", borderRadius: ui.radiusSm,
      border: "1px solid var(--line-strong)", background: "var(--bg)", color: "var(--text)",
      fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)", fontSize: 13, outline: "none",
      width: "100%", ...style,
    }}/>
  );
};

// ── Sparkline ────────────────────────────────────────────────────────────
const Sparkline = ({ data, w = 72, h = 22, color = "var(--brand-2)", fill = true }) => {
  if (!data || !data.length) return <svg width={w} height={h}/>;
  data = window.DSfmt.smoothSeries(data, [1, 2, 1]);
  const max = Math.max(...data, 0.0001);
  const step = w / (data.length - 1);
  const pts = data.map((v, i) => [i * step, h - (v / max) * (h - 2) - 1]);
  const d = window.DSfmt.smoothPath(pts, 0, h);
  return (
    <svg width={w} height={h} style={{ display: "block", overflow: "visible" }}>
      {fill && <path d={`${d} L${w} ${h} L0 ${h} Z`} fill={`color-mix(in srgb, ${color} 16%, transparent)`}/>}
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"/>
    </svg>
  );
};

// ── Area throughput chart ──────────────────────────────────────────────────
// Same look as the client GUI's chart (Catmull-Rom curve, 64 KB/s scale
// floor, download down and upload up) but it glides instead of stepping: the
// curve is laid out once per sample (one a second) in *time* coordinates and a
// frame loop only slides it left with the clock. The right edge shows the
// moment `lagS` ago, always between two samples already received, so nothing
// waits for data and nothing jumps when a sample arrives. 0.16.2 tried a
// sliding chart too, but with 2 s samples and a 4 s delay it felt slow; the
// samples are now 1 s apart and the delay 1.5 s.
const AreaChart = ({ samples, h = 150, windowS = 60, lagS = 1.5 }) => {
  const W = 760, H = h, P = 8, K = W / windowS;
  const gRef = React.useRef(null);
  const history = samples || [];
  const t0 = history.length ? history[0].t : 0;
  const peak = history.reduce((m, s) => Math.max(m, s.rx || 0, s.tx || 0), 0);
  const scale = Math.max(peak, 64 * 1024);
  const mid = H / 2;
  const innerH = mid - P;
  const ptsFor = (key, sign) => history.map((s) => [(s.t - t0) * K, mid + sign * ((s[key] || 0) / scale) * innerH]);
  // Clamped to its own half so the curve never dips across the centre axis.
  const line = (key, sign) => window.DSfmt.smoothPath(ptsFor(key, sign),
    sign > 0 ? mid : P, sign > 0 ? H - P : mid);
  const xLast = history.length ? (history[history.length - 1].t - t0) * K : 0;
  const area = (key, sign) => history.length
    ? `${line(key, sign)} L ${xLast.toFixed(1)} ${mid} L 0 ${mid} Z` : "";
  const place = () => {
    if (!gRef.current) return;
    const shift = window.DSfmt.chartShift(t0, Date.now() / 1000, lagS, windowS) * K;
    gRef.current.setAttribute("transform", `translate(${(-shift).toFixed(2)} 0)`);
  };
  // After every render (a new sample) so the new layout and the shift change
  // together, and on every frame in between.
  React.useLayoutEffect(place);
  React.useEffect(() => {
    let raf = 0;
    const tick = () => { place(); raf = requestAnimationFrame(tick); };
    raf = requestAnimationFrame(tick);
    return () => cancelAnimationFrame(raf);
  }, [t0, K, lagS, windowS]);
  if (history.length < 2) {
    return <div style={{ height: H }} />;
  }
  return (
    <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id="owGradRx" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--brand)" stopOpacity="0"/>
          <stop offset="1" stopColor="var(--brand)" stopOpacity="0.55"/>
        </linearGradient>
        <linearGradient id="owGradTx" x1="0" y1="0" x2="0" y2="1">
          <stop offset="0" stopColor="var(--brand-2)" stopOpacity="0.55"/>
          <stop offset="1" stopColor="var(--brand-2)" stopOpacity="0"/>
        </linearGradient>
      </defs>
      <line x1="0" y1={mid} x2={W} y2={mid} stroke="var(--line)" strokeDasharray="2 4"/>
      <g ref={gRef}>
        <path d={area("rx", +1)} fill="url(#owGradRx)"/>
        <path d={line("rx", +1)} stroke="var(--brand)" fill="none" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
        <path d={area("tx", -1)} fill="url(#owGradTx)"/>
        <path d={line("tx", -1)} stroke="var(--brand-2)" fill="none" strokeWidth="1.6" strokeLinejoin="round" strokeLinecap="round" vectorEffect="non-scaling-stroke"/>
      </g>
    </svg>
  );
};

// ── Traffic history chart (Traffic screen) ───────────────────────────────
// One bar per bucket, what the clients sent (RX) growing down and what they
// received (TX) growing up, like the live chart. Buckets before the first
// snapshot are shaded as "no data" rather than drawn as a flat zero, and
// hovering a bar shows its time range and bytes.
const HistoryChart = ({ rx, tx, start, bucketSeconds, firstTs, lang, T, h = 220 }) => {
  const [hover, setHover] = React.useState(null);
  const boxRef = React.useRef(null);
  const n = rx.length;
  const W = 760, H = h, PAD = 6, AXIS = 22;
  const plotH = H - AXIS;
  const mid = plotH / 2;
  const half = mid - PAD;
  const peak = Math.max(1, ...rx, ...tx);
  const slot = W / n;
  const barW = Math.max(1, slot - Math.min(2, slot * 0.25));
  const firstIdx = firstTs == null ? n : Math.max(0, Math.floor((firstTs - start) / bucketSeconds));
  const { fmtBytes, fmtTick, fmtRange } = window.DSfmt;
  const ticks = 5;
  const onMove = (e) => {
    const r = boxRef.current.getBoundingClientRect();
    const i = Math.floor(((e.clientX - r.left) / r.width) * n);
    setHover(i >= 0 && i < n ? i : null);
  };
  const hoverX = hover == null ? 0 : ((hover + 0.5) / n) * 100;
  return (
    <div ref={boxRef} style={{ position: "relative" }} onMouseMove={onMove} onMouseLeave={() => setHover(null)}>
      <svg viewBox={`0 0 ${W} ${H}`} width="100%" height={H} preserveAspectRatio="none" style={{ display: "block" }}
        role="img" aria-label={T.traffic_chartTitle}>
        <defs>
          <pattern id="owNoData" width="6" height="6" patternUnits="userSpaceOnUse" patternTransform="rotate(45)">
            <line x1="0" y1="0" x2="0" y2="6" stroke="var(--line-strong)" strokeWidth="1.2" />
          </pattern>
        </defs>
        {firstIdx > 0 && <rect x="0" y={PAD} width={Math.min(n, firstIdx) * slot} height={plotH - PAD * 2} fill="url(#owNoData)" opacity="0.35" />}
        {[0.5, 1].map((f) => (
          <g key={f}>
            <line x1="0" x2={W} y1={mid - f * half} y2={mid - f * half} stroke="var(--line)" strokeDasharray="2 5" />
            <line x1="0" x2={W} y1={mid + f * half} y2={mid + f * half} stroke="var(--line)" strokeDasharray="2 5" />
          </g>
        ))}
        {rx.map((v, i) => {
          const up = (tx[i] / peak) * half, down = (v / peak) * half;
          const x = i * slot + (slot - barW) / 2;
          const dim = hover != null && hover !== i ? 0.45 : 1;
          return (
            <g key={i} opacity={dim}>
              {up > 0 && <rect x={x} y={mid - Math.max(1, up)} width={barW} height={Math.max(1, up)} rx={Math.min(2, barW / 3)} fill="var(--brand-2)" />}
              {down > 0 && <rect x={x} y={mid} width={barW} height={Math.max(1, down)} rx={Math.min(2, barW / 3)} fill="var(--brand)" />}
            </g>
          );
        })}
        <line x1="0" x2={W} y1={mid} y2={mid} stroke="var(--line-strong)" />
        {hover != null && <rect x={hover * slot} y={PAD} width={slot} height={plotH - PAD * 2} fill="var(--text)" opacity="0.06" />}
      </svg>
      <div aria-hidden style={{ position: "absolute", left: 0, top: PAD - 2, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)" }}>↑ {fmtBytes(peak)}</div>
      <div aria-hidden style={{ position: "absolute", left: 0, top: plotH - PAD - 14, fontFamily: "var(--font-mono)", fontSize: 10, color: "var(--text-3)" }}>↓ {fmtBytes(peak)}</div>
      <div aria-hidden style={{ position: "absolute", left: 0, right: 0, bottom: 0, height: AXIS, display: "flex", justifyContent: "space-between", alignItems: "flex-end",
        fontFamily: "var(--font-mono)", fontSize: 10.5, color: "var(--text-3)" }}>
        {Array.from({ length: ticks }).map((_, k) => (
          <span key={k}>{fmtTick(start + (k / (ticks - 1)) * n * bucketSeconds, bucketSeconds, lang)}</span>
        ))}
      </div>
      {hover != null && (
        <div role="tooltip" style={{ position: "absolute", top: 4, left: `${hoverX}%`, transform: `translateX(${hoverX > 70 ? "-104%" : "4%"})`,
          background: "var(--bg-2)", border: "1px solid var(--line-strong)", borderRadius: 8, padding: "7px 10px", pointerEvents: "none",
          boxShadow: "0 8px 22px -10px rgba(0,0,0,.45)", fontFamily: "var(--font-mono)", fontSize: 11.5, whiteSpace: "nowrap", zIndex: 2 }}>
          <div style={{ color: "var(--text-3)", marginBottom: 4 }}>{fmtRange(start + hover * bucketSeconds, bucketSeconds, lang)}</div>
          {hover < firstIdx ? <div style={{ color: "var(--text-3)" }}>{T.traffic_noSamples}</div> : <>
            <div style={{ color: "var(--brand)" }}>↓ {T.traffic_rxTotal} {fmtBytes(rx[hover])}</div>
            <div style={{ color: "var(--brand-2)" }}>↑ {T.traffic_txTotal} {fmtBytes(tx[hover])}</div>
          </>}
        </div>
      )}
    </div>
  );
};

// ── Empty / placeholder state ────────────────────────────────────────────
// Says what is missing and why instead of a lone "—".
const EmptyState = ({ icon, title, body, action, compact }) => (
  <div style={{ display: "flex", flexDirection: "column", alignItems: "center", textAlign: "center", gap: 8,
    padding: compact ? "18px 12px" : "34px 20px", color: "var(--text-2)" }}>
    {icon && <div style={{ width: 40, height: 40, borderRadius: 12, display: "grid", placeItems: "center",
      background: "var(--bg-sunk)", color: "var(--text-3)", marginBottom: 2 }}>{icon}</div>}
    <div style={{ fontSize: compact ? 13 : 14, fontWeight: 600, color: "var(--text)" }}>{title}</div>
    {body && <div style={{ fontSize: 12.5, lineHeight: 1.55, maxWidth: 460, color: "var(--text-3)" }}>{body}</div>}
    {action && <div style={{ marginTop: 6 }}>{action}</div>}
  </div>
);

// ── Donut (clients online/idle/offline) ──────────────────────────────────
const Donut = ({ segments, size = 92, stroke = 12, center }) => {
  const r = (size - stroke) / 2;
  const c = 2 * Math.PI * r;
  const total = segments.reduce((s, x) => s + x.value, 0) || 1;
  let acc = 0;
  return (
    <div style={{ position: "relative", width: size, height: size, flex: "none" }}>
      <svg width={size} height={size} style={{ transform: "rotate(-90deg)" }}>
        <circle cx={size / 2} cy={size / 2} r={r} fill="none" stroke="var(--bg-sunk)" strokeWidth={stroke}/>
        {segments.map((s, i) => {
          const len = (s.value / total) * c;
          const el = <circle key={i} cx={size / 2} cy={size / 2} r={r} fill="none" stroke={s.color}
            strokeWidth={stroke} strokeDasharray={`${len} ${c - len}`} strokeDashoffset={-acc} strokeLinecap="butt"/>;
          acc += len;
          return el;
        })}
      </svg>
      {center && <div style={{ position: "absolute", inset: 0, display: "grid", placeItems: "center", textAlign: "center" }}>{center}</div>}
    </div>
  );
};

// ── KV row (used in drawer / dash detail blocks) ─────────────────────────
const KV = ({ k, v, mono, tone, last }) => (
  <div style={{ display: "grid", gridTemplateColumns: "minmax(96px, 38%) 1fr", gap: 12, alignItems: "baseline",
    padding: "8px 0", borderBottom: last ? "none" : "1px solid var(--line)" }}>
    <span style={{ fontSize: 12, color: "var(--text-3)" }}>{k}</span>
    <span style={{ fontSize: 12.5, color: tone || "var(--text)", fontFamily: mono ? "var(--font-mono)" : "var(--font-sans)", wordBreak: "break-all", textAlign: "left" }}>{v}</span>
  </div>
);

// ── device glyph ─────────────────────────────────────────────────────────
const deviceIcon = {
  mobile: "M7 3h10v18H7zM10 18h4",
  laptop: "M4 5h16v11H4zM2 19h20",
  tablet: "M5 3h14v18H5zM11 18h2",
  server: "M3 4h18v6H3zM3 14h18v6H3zM7 7h.01M7 17h.01",
};

// ── icon factory ─────────────────────────────────────────────────────────
const IC = (d, s = 18, fillStroke) => (
  <svg width={s} height={s} viewBox="0 0 24 24" fill="none" stroke="currentColor" strokeWidth="1.7" strokeLinecap="round" strokeLinejoin="round">{d}</svg>
);
const Icons = {
  dashboard: (s) => IC(<><rect x="3" y="3" width="8" height="8" rx="1"/><rect x="13" y="3" width="8" height="5" rx="1"/><rect x="13" y="10" width="8" height="11" rx="1"/><rect x="3" y="13" width="8" height="8" rx="1"/></>, s),
  clients: (s) => IC(<><circle cx="9" cy="8" r="3.5"/><path d="M2 21c0-4 3-6 7-6s7 2 7 6"/><circle cx="17" cy="9" r="2.5"/><path d="M16 21c0-3 2-4.5 4.5-4.5"/></>, s),
  traffic: (s) => IC(<><path d="M3 17l5-5 4 3 6-8"/><path d="M3 21h18"/></>, s),
  service: (s) => IC(<><rect x="3" y="4" width="18" height="6" rx="1"/><rect x="3" y="14" width="18" height="6" rx="1"/><circle cx="7" cy="7" r=".6" fill="currentColor"/><circle cx="7" cy="17" r=".6" fill="currentColor"/></>, s),
  logs: (s) => IC(<><path d="M5 4h14v16H5z"/><path d="M8 8h8M8 12h8M8 16h5"/></>, s),
  doctor: (s) => IC(<><path d="M12 3a9 9 0 1 0 9 9"/><path d="M21 4l-9 9-3-3"/></>, s),
  settings: (s) => IC(<><circle cx="12" cy="12" r="3"/><path d="M12 2v3M12 19v3M2 12h3M19 12h3M5 5l2 2M17 17l2 2M5 19l2-2M17 7l2-2"/></>, s),
  plus: (s) => IC(<><path d="M12 5v14M5 12h14"/></>, s),
  search: (s) => IC(<><circle cx="11" cy="11" r="7"/><path d="M21 21l-4-4"/></>, s),
  refresh: (s) => IC(<><path d="M3 12a9 9 0 0 1 15-6l3 3M21 4v5h-5"/><path d="M21 12a9 9 0 0 1-15 6l-3-3M3 20v-5h5"/></>, s),
  download: (s) => IC(<><path d="M12 3v12M7 10l5 5 5-5"/><path d="M4 21h16"/></>, s),
  qr: (s) => IC(<><rect x="3" y="3" width="7" height="7"/><rect x="14" y="3" width="7" height="7"/><rect x="3" y="14" width="7" height="7"/><path d="M14 14h3v3M21 14v7M17 21h-3M21 21h-1"/></>, s),
  copy: (s) => IC(<><rect x="9" y="9" width="11" height="11" rx="1.5"/><path d="M5 15V5a1 1 0 0 1 1-1h9"/></>, s),
  rotate: (s) => IC(<><path d="M21 12a9 9 0 1 1-3-6.7L21 7"/><path d="M21 3v4h-4"/></>, s),
  pause: (s) => IC(<><path d="M9 5v14M15 5v14"/></>, s),
  play: (s) => IC(<><path d="M7 4l13 8-13 8z"/></>, s),
  trash: (s) => IC(<><path d="M4 7h16M9 7V4h6v3M6 7l1 13h10l1-13"/></>, s),
  x: (s) => IC(<><path d="M6 6l12 12M18 6L6 18"/></>, s),
  menu: (s) => IC(<><path d="M3 6h18M3 12h18M3 18h18"/></>, s),
  chevR: (s) => IC(<><path d="M9 6l6 6-6 6"/></>, s),
  chevL: (s) => IC(<><path d="M15 6l-6 6 6 6"/></>, s),
  chevDown: (s) => IC(<><path d="M6 9l6 6 6-6"/></>, s),
  sun: (s) => IC(<><circle cx="12" cy="12" r="4"/><path d="M12 2v2M12 20v2M2 12h2M20 12h2M5 5l1.5 1.5M17.5 17.5L19 19M5 19l1.5-1.5M17.5 6.5L19 5"/></>, s),
  moon: (s) => IC(<><path d="M21 12.5A9 9 0 1 1 11.5 3a7 7 0 0 0 9.5 9.5z"/></>, s),
  check: (s) => IC(<><path d="M5 12l5 5L20 6"/></>, s),
  warn: (s) => IC(<><path d="M12 3l9 16H3z"/><path d="M12 10v4M12 17h.01"/></>, s),
  fail: (s) => IC(<><circle cx="12" cy="12" r="9"/><path d="M9 9l6 6M15 9l-6 6"/></>, s),
  arrow: (s) => IC(<><path d="M5 12h14M13 6l6 6-6 6"/></>, s),
  bolt: (s) => IC(<><path d="M13 2L4 14h7l-1 8 9-12h-7z"/></>, s),
  shield: (s) => IC(<><path d="M12 3l8 3v6c0 5-3.5 8-8 9-4.5-1-8-4-8-9V6z"/></>, s),
  device: (type, s) => IC(<path d={deviceIcon[type] || deviceIcon.laptop}/>, s),
  lock: (s) => IC(<><rect x="4" y="10" width="16" height="11" rx="2"/><path d="M8 10V7a4 4 0 0 1 8 0v3"/></>, s),
  power: (s) => IC(<><path d="M12 4v8"/><path d="M7 7a8 8 0 1 0 10 0"/></>, s),
  clock: (s) => IC(<><circle cx="12" cy="12" r="9"/><path d="M12 7v5l3 2"/></>, s),
  inbox: (s) => IC(<><path d="M3 13l3-8h12l3 8v6H3z"/><path d="M3 13h5l1 3h6l1-3h5"/></>, s),
  globe: (s) => IC(<><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></>, s),
};

window.OWUIContext = OWUIContext;
window.useUI = useUI;
window.styleTokens = styleTokens;
Object.assign(window, {
  Card, SLabel, PageHead, Btn, Pill, Dot, Toggle, Segmented, Stat, Field, Input,
  Sparkline, AreaChart, HistoryChart, EmptyState, Donut, KV, Icons,
});
