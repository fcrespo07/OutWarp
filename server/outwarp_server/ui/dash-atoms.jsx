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
const Toggle = ({ on, onChange }) => (
  <button onClick={() => onChange?.(!on)} aria-pressed={on} className="ow-btn" style={{
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
    <div style={{ display: "inline-flex", gap: 3, padding: 3, background: "var(--bg-sunk)", borderRadius: ui.radiusSm, border: ui.style === "tecnica" ? "1px solid var(--line)" : "none" }}>
      {options.map((o) => {
        const active = o.value === value;
        return (
          <button key={o.value} onClick={() => onChange(o.value)} className="ow-btn" style={{
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
  const max = Math.max(...data, 0.0001);
  const step = w / (data.length - 1);
  const pts = data.map((v, i) => [i * step, h - (v / max) * (h - 2) - 1]);
  const d = pts.map((p, i) => `${i ? "L" : "M"}${p[0].toFixed(1)} ${p[1].toFixed(1)}`).join(" ");
  return (
    <svg width={w} height={h} style={{ display: "block", overflow: "visible" }}>
      {fill && <path d={`${d} L${w} ${h} L0 ${h} Z`} fill={`color-mix(in srgb, ${color} 16%, transparent)`}/>}
      <path d={d} fill="none" stroke={color} strokeWidth="1.5" strokeLinejoin="round" strokeLinecap="round"/>
    </svg>
  );
};

// ── Area throughput chart (dual: rx up, tx down-mirrored) ─────────────────
const AreaChart = ({ rx, tx, h = 150 }) => {
  const W = 1000, P = 4;
  const maxR = Math.max(...rx, 0.0001), maxT = Math.max(...tx, 0.0001);
  const max = Math.max(maxR, maxT);
  const n = rx.length;
  const mid = h / 2;
  const line = (arr, mirror) => {
    const step = (W - P * 2) / (n - 1);
    return arr.map((v, i) => {
      const x = P + i * step;
      const y = mirror ? mid + (v / max) * (mid - P) : mid - (v / max) * (mid - P);
      return `${i ? "L" : "M"}${x.toFixed(1)} ${y.toFixed(1)}`;
    }).join(" ");
  };
  return (
    <svg viewBox={`0 0 ${W} ${h}`} width="100%" height={h} preserveAspectRatio="none" style={{ display: "block" }}>
      <defs>
        {/* fade toward the centre axis → transparent, like the Windows GUI */}
        <linearGradient id="owGradRx" gradientUnits="userSpaceOnUse" x1="0" y1={P} x2="0" y2={mid}>
          <stop offset="0" stopColor="var(--brand)" stopOpacity="0.5"/>
          <stop offset="0.7" stopColor="var(--brand)" stopOpacity="0.16"/>
          <stop offset="1" stopColor="var(--brand)" stopOpacity="0"/>
        </linearGradient>
        <linearGradient id="owGradTx" gradientUnits="userSpaceOnUse" x1="0" y1={mid} x2="0" y2={h - P}>
          <stop offset="0" stopColor="var(--brand-2)" stopOpacity="0"/>
          <stop offset="0.3" stopColor="var(--brand-2)" stopOpacity="0.16"/>
          <stop offset="1" stopColor="var(--brand-2)" stopOpacity="0.5"/>
        </linearGradient>
      </defs>
      <line x1="0" y1={mid} x2={W} y2={mid} stroke="var(--line)" strokeDasharray="2 5"/>
      <path d={`${line(rx)} L${W - P} ${mid} L${P} ${mid} Z`} fill="url(#owGradRx)"/>
      <path d={line(rx)} fill="none" stroke="var(--brand)" strokeWidth="1.8"/>
      <path d={`${line(tx, true)} L${W - P} ${mid} L${P} ${mid} Z`} fill="url(#owGradTx)"/>
      <path d={line(tx, true)} fill="none" stroke="var(--brand-2)" strokeWidth="1.8"/>
    </svg>
  );
};

// ── Bars (24h history) ───────────────────────────────────────────────────
const BarSeries = ({ data, h = 120, color = "var(--brand)" }) => {
  const max = Math.max(...data, 0.0001);
  const n = data.length;
  const gap = 2;
  return (
    <div style={{ display: "flex", alignItems: "flex-end", gap, height: h, width: "100%" }}>
      {data.map((v, i) => (
        <div key={i} style={{ flex: 1, height: `${Math.max(2, (v / max) * 100)}%`,
          background: color, opacity: 0.35 + 0.65 * (v / max), borderRadius: 1, minWidth: 0 }}/>
      ))}
    </div>
  );
};

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
  globe: (s) => IC(<><circle cx="12" cy="12" r="9"/><path d="M3 12h18M12 3c3 3.5 3 14.5 0 18M12 3c-3 3.5-3 14.5 0 18"/></>, s),
};

window.OWUIContext = OWUIContext;
window.useUI = useUI;
window.styleTokens = styleTokens;
Object.assign(window, {
  Card, SLabel, PageHead, Btn, Pill, Dot, Toggle, Segmented, Stat, Field, Input,
  Sparkline, AreaChart, BarSeries, Donut, KV, Icons,
});
