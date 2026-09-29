// OutWarp brand marks — wordmark + icon
// Icon: an arrow breaking out through a barrier ring — "salir" + warp.
// Two arcs that gap on the right where a chevron arrow pierces through,
// and a small spark/tail indicating the "warp" / momentum.

// Chevron Stack — the app icon (resources/app_icon.png / .ico), redrawn as
// SVG so it stays sharp at any size. Geometry measured on the 512 px PNG:
// three right-angled chevrons (45° arms) with square-cut ends, a 5.3-unit
// stroke on a 48-unit box, one every 11.06 units. Colours are the icon's own:
// light grey, dark grey and warp blue. Until 0.17 the UI drew thinner, steeper
// chevrons tinted with the text colour, which did not match the icon.
const OW_ICON_COLORS = ["#BBBBB9", "#747577", "#2463FE"];
const OWLogoMark = ({ size = 28, colors = OW_ICON_COLORS }) => (
  <svg width={size} height={size} viewBox="0 0 48 48" aria-hidden="true"
    fill="none" strokeLinecap="butt" strokeLinejoin="miter" strokeMiterlimit="10" strokeWidth="5.3">
    {[0, 1, 2].map((i) => {
      const x = 5.44 + i * 11.06;
      return <polyline key={i} points={`${x},10.97 ${x + 13.03},24 ${x},37.03`} stroke={colors[i]}/>;
    })}
  </svg>
);

const OWWordmark = ({ size = 18, color = "currentColor", accent, withMark = true, gap = 8 }) => {
  return (
    <span style={{ display: "inline-flex", alignItems: "center", gap, color, fontFamily: "var(--font-display)", fontWeight: 600, letterSpacing: "-0.02em", fontSize: size }}>
      {withMark ? <OWLogoMark size={Math.round(size * 1.55)}/> : null}
      <span>
        Out<span style={{ color: accent || color, fontWeight: 700 }}>Warp</span>
      </span>
    </span>
  );
};

// monospace tunnel viz — used in variation B
const TunnelViz = ({ active = true, height = 84, throughput = 1 }) => {
  const id = React.useId();
  return (
    <svg width="100%" height={height} viewBox="0 0 360 84" preserveAspectRatio="none" style={{ display: "block" }}>
      <defs>
        <linearGradient id={`tg-${id}`} x1="0" x2="1">
          <stop offset="0" stopColor="var(--brand)" stopOpacity="0"/>
          <stop offset=".5" stopColor="var(--brand)" stopOpacity="1"/>
          <stop offset="1" stopColor="var(--brand-2)" stopOpacity="1"/>
        </linearGradient>
      </defs>
      <path d="M0 18 Q 180 2 360 18" stroke="var(--line-strong)" fill="none" strokeWidth="1"/>
      <path d="M0 66 Q 180 82 360 66" stroke="var(--line-strong)" fill="none" strokeWidth="1"/>
      {Array.from({ length: 14 }).map((_, i) => {
        const x = (i * 26) % 360;
        return (
          <g key={i} opacity={active ? 1 : 0.3}>
            <line x1={x} y1="22" x2={x + 14} y2="22" stroke={`url(#tg-${id})`} strokeWidth="2" strokeLinecap="round"
              style={ active ? { animation: `ws-flow ${2.2 / throughput}s linear infinite` } : {}} />
            <line x1={x + 8} y1="62" x2={x + 22} y2="62" stroke={`url(#tg-${id})`} strokeWidth="2" strokeLinecap="round"
              style={ active ? { animation: `ws-flow ${2.6 / throughput}s linear infinite reverse` } : {}} opacity=".7"/>
          </g>
        );
      })}
      <circle cx="6"   cy="42" r="5" fill="var(--brand)"/>
      <circle cx="354" cy="42" r="5" fill="var(--brand-2)"/>
      <text x="14" y="46" fontFamily="var(--font-mono)" fontSize="9" fill="var(--text-3)">CLIENT</text>
      <text x="320" y="46" fontFamily="var(--font-mono)" fontSize="9" fill="var(--text-3)">SERVER</text>
    </svg>
  );
};

// Backwards compatibility aliases — every existing file references window.WSWordmark / WSLogoMark.
// Re-export the new brand under both names so we don't have to rewrite ~6 files.
window.OWLogoMark = OWLogoMark;
window.OW_ICON_COLORS = OW_ICON_COLORS;
window.OWWordmark = OWWordmark;
window.WSLogoMark = OWLogoMark;
window.WSWordmark = OWWordmark;
window.TunnelViz  = TunnelViz;
