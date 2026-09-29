// OutWarp Server dashboard — login, client drawer, add-client modal, confirm.
const { Card: ECard, Btn: EBtn, Pill: EPill, Dot: EDot, Toggle: ETog, Field: EField, Input: EInput,
        KV: EKV, Sparkline: ESpark, Icons: EIcons, useUI: EuseUI } = window;
const EF = window.DSfmt;

// ── LOGIN ────────────────────────────────────────────────────────────────
function LoginScreen({ T, theme, appInfo, onLogin }) {
  const [token, setToken] = React.useState("");
  const [remember, setRemember] = React.useState(true);
  const [error, setError] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const submit = async (e) => {
    e.preventDefault();
    if (!token.trim() || busy) return;
    setBusy(true); setError("");
    const r = await onLogin({ token: token.trim(), remember });
    setBusy(false);
    if (!r.ok) setError(r.error || T.login_bad);
  };
  return (
    <div data-theme={theme} style={{ position: "fixed", inset: 0, background: "var(--bg)", color: "var(--text)", display: "grid", gridTemplateColumns: "1.05fr 1fr", overflow: "auto" }} className="login-wrap">
      <div className="login-brand" style={{ position: "relative", overflow: "hidden", background: "var(--bg-2)", borderRight: "1px solid var(--line)", padding: "48px 56px", display: "flex", flexDirection: "column", justifyContent: "space-between" }}>
        <window.WSWordmark size={20} color="var(--text)" accent="var(--brand)" />
        <div style={{ position: "relative", zIndex: 1 }}>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, letterSpacing: ".18em", textTransform: "uppercase", color: "var(--brand)" }}>{T.login_eyebrow}</div>
          <h1 style={{ fontSize: 38, fontWeight: 600, letterSpacing: "-0.03em", lineHeight: 1.05, margin: "14px 0 0", maxWidth: 440 }}>{T.login_title}</h1>
          <p style={{ fontSize: 14.5, color: "var(--text-2)", lineHeight: 1.55, maxWidth: 420, marginTop: 14 }}>{T.login_sub}</p>
          <div style={{ display: "flex", alignItems: "center", gap: 8, marginTop: 22, fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-2)" }}>
            {EIcons.shield(16)} {T.login_secured}
          </div>
        </div>
        <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)" }}>outwarp-server{appInfo && appInfo.version ? ` · v${appInfo.version}` : ""} · PolyForm Noncommercial</div>
        <div aria-hidden style={{ position: "absolute", right: -70, bottom: -60, opacity: 0.16, pointerEvents: "none" }}>
          <window.WSLogoMark size={420}/>
        </div>
        <div aria-hidden style={{ position: "absolute", left: -100, top: -80, width: 360, height: 360, background: "radial-gradient(circle, color-mix(in srgb, var(--brand) 14%, transparent), transparent 64%)", pointerEvents: "none" }} />
      </div>

      <div style={{ display: "grid", placeItems: "center", padding: "40px 32px" }}>
        {/* method/action + a username field are what browsers and password
            managers key on to offer "save" and autofill; the SPA still submits
            through onSubmit. The username is fixed: there is one admin. */}
        <form onSubmit={submit} method="post" action="/auth" autoComplete="on" style={{ width: "100%", maxWidth: 380, display: "flex", flexDirection: "column", gap: 16 }}>
          <input type="text" name="username" autoComplete="username" value="admin" readOnly tabIndex={-1} aria-hidden="true"
            style={{ position: "absolute", width: 1, height: 1, padding: 0, margin: -1, overflow: "hidden", clip: "rect(0 0 0 0)", border: 0 }} />
          <div className="login-brand-mobile" style={{ display: "none", marginBottom: 4 }}>
            <window.WSWordmark size={18} color="var(--text)" accent="var(--brand)" />
          </div>
          <EField label={T.login_token}>
            <div style={{ position: "relative" }}>
              <span style={{ position: "absolute", left: 11, top: "50%", transform: "translateY(-50%)", color: "var(--text-3)", display: "inline-flex" }}>{EIcons.lock(15)}</span>
              <EInput id="ow-admin-token" name="password" autoComplete="current-password" value={token} onChange={(e) => setToken(e.target.value)} type="password" placeholder={T.login_tokenPh} mono autoFocus style={{ paddingLeft: 34 }} />
            </div>
          </EField>
          <label style={{ display: "flex", alignItems: "center", gap: 10, cursor: "pointer", fontSize: 13, color: "var(--text-2)" }}>
            <ETog on={remember} onChange={setRemember} /> {T.login_remember}
          </label>
          {error && <div style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-bad)", textAlign: "center" }}>{error}</div>}
          <button type="submit" disabled={busy} className="ow-btn" style={{ height: 46, borderRadius: 10, background: "var(--brand)", color: "#fff", border: "none", cursor: "pointer",
            fontFamily: "var(--font-sans)", fontSize: 15, fontWeight: 600, display: "inline-flex", alignItems: "center", justifyContent: "center", gap: 9, marginTop: 4, opacity: busy ? 0.6 : 1 }}>
            {EIcons.power(17)} {busy ? "…" : T.login_btn}
          </button>
          <div style={{ fontFamily: "var(--font-mono)", fontSize: 11, color: "var(--text-3)", lineHeight: 1.5, textAlign: "center" }}>{T.login_hint}</div>
        </form>
      </div>
    </div>
  );
}

// ── CONFIRM DIALOG ─────────────────────────────────────────────────────────
function ConfirmDialog({ T, opts, onResult }) {
  React.useEffect(() => {
    const onKey = (e) => { if (e.key === "Escape") onResult(false); else if (e.key === "Enter") onResult(true); };
    window.addEventListener("keydown", onKey);
    return () => window.removeEventListener("keydown", onKey);
  }, [onResult]);
  return (
    <div className="ow-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onResult(false); }}>
      <div className="ow-modal" role="dialog" aria-modal="true" style={{ maxWidth: 440 }}>
        {opts.title && <div style={{ fontSize: 16, fontWeight: 600, marginBottom: 8 }}>{opts.title}</div>}
        <div style={{ fontSize: 13.5, color: "var(--text-2)", lineHeight: 1.55, wordBreak: "break-word" }}>{opts.body}</div>
        <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 22 }}>
          <EBtn kind="ghost" onClick={() => onResult(false)}>{opts.cancelLabel || T.cancel}</EBtn>
          <EBtn kind={opts.danger ? "danger" : "primary"} onClick={() => onResult(true)}>{opts.confirmLabel || T.confirm}</EBtn>
        </div>
      </div>
    </div>
  );
}

// ── ADD CLIENT MODAL ─────────────────────────────────────────────────────
function AddClientModal({ T, C, onClose }) {
  const ui = EuseUI();
  const [name, setName] = React.useState("");
  const [busy, setBusy] = React.useState(false);
  const [error, setError] = React.useState("");
  const [result, setResult] = React.useState(null); // { name, path, owcfg_base64 }
  const generate = async () => {
    if (!name.trim() || busy) return;
    setBusy(true); setError("");
    const r = await C.call("add_client", name.trim());
    setBusy(false);
    if (r && r.ok) setResult(r); else setError((r && r.error) || "error");
  };
  const download = () => C.call("save_owcfg", result.name, result.owcfg_base64);
  return (
    <div className="ow-overlay" onMouseDown={(e) => { if (e.target === e.currentTarget) onClose(); }}>
      <div className="ow-modal" role="dialog" aria-modal="true" style={{ maxWidth: 520 }}>
        <div style={{ display: "flex", justifyContent: "space-between", alignItems: "flex-start" }}>
          <div>
            <div style={{ fontSize: 18, fontWeight: 600, letterSpacing: "-0.01em" }}>{T.add_title}</div>
            <div style={{ fontSize: 12.5, color: "var(--text-2)", marginTop: 4, maxWidth: 420, lineHeight: 1.5 }}>{T.add_sub}</div>
          </div>
          <button className="ow-iconbtn" onClick={onClose} aria-label={T.a11y_close}>{EIcons.x(18)}</button>
        </div>

        {!result ? (
          <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 13 }}>
            <EField label={T.add_name}><EInput value={name} onChange={(e) => setName(e.target.value)} onKeyDown={(e) => { if (e.key === "Enter") generate(); }} placeholder={T.add_namePh} autoFocus /></EField>
            <div style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)" }}>{T.add_autoAssigned}</div>
            {error && <div role="alert" style={{ fontFamily: "var(--font-mono)", fontSize: 12, color: "var(--brand-bad)" }}>{error}</div>}
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8, marginTop: 6 }}>
              <EBtn kind="ghost" onClick={onClose}>{T.cancel}</EBtn>
              <EBtn kind="primary" icon={EIcons.plus(15)} disabled={!name.trim() || busy} onClick={generate} style={{ opacity: name.trim() && !busy ? 1 : 0.5 }}>{busy ? "…" : T.add_generate}</EBtn>
            </div>
          </div>
        ) : (
          <div style={{ marginTop: 18, display: "flex", flexDirection: "column", gap: 14 }}>
            <div>
              <div>
                <div style={{ border: "1px solid color-mix(in srgb, var(--brand-2) 36%, transparent)", background: "color-mix(in srgb, var(--brand-2) 7%, transparent)", borderRadius: ui.radiusSm, padding: "12px 14px", fontFamily: "var(--font-mono)", fontSize: 12, lineHeight: 1.7 }}>
                  <div><span style={{ color: "var(--brand-2)" }}>✓</span> <b>{result.name}.owcfg</b> <span style={{ color: "var(--text-3)" }}>· {T.add_done}</span></div>
                  {result.path && <div style={{ color: "var(--text-3)", wordBreak: "break-all" }}>{T.add_writtenTo} {result.path}</div>}
                  <div><span style={{ color: "var(--brand-warn)" }}>⏱</span> <span style={{ color: "var(--text-2)" }}>{T.add_token}</span></div>
                </div>
              </div>
            </div>
            <div style={{ borderLeft: "2px solid var(--brand-warn)", background: "color-mix(in srgb, var(--brand-warn) 8%, transparent)", padding: "10px 14px", borderRadius: "0 6px 6px 0", fontSize: 12, color: "var(--text-2)", lineHeight: 1.5 }}>
              <span style={{ color: "var(--brand-warn)", fontWeight: 600 }}>⚠ </span>{T.add_warnKey}
            </div>
            <div style={{ display: "flex", justifyContent: "flex-end", gap: 8 }}>
              <EBtn kind="ghost" icon={EIcons.download(15)} onClick={download}>{T.detail_download}</EBtn>
              <EBtn kind="primary" icon={EIcons.check(15)} onClick={onClose}>{T.add_close}</EBtn>
            </div>
          </div>
        )}
      </div>
    </div>
  );
}

// ── CLIENT DETAIL DRAWER ─────────────────────────────────────────────────
function ClientDrawer({ T, client, lang, C, onClose, confirm }) {
  const ui = EuseUI();
  const [detail, setDetail] = React.useState(null);
  const [busy, setBusy] = React.useState("");
  React.useEffect(() => {
    let alive = true;
    C.call("get_client", client.name).then((d) => { if (alive && d && d.ok) setDetail(d); }).catch(() => {});
    return () => { alive = false; };
  }, [client.name]);
  if (!client) return null;
  const tone = client.state === "online" ? "good" : client.state === "idle" || client.state === "pending" ? "warn" : "neutral";
  const allowed = detail && detail.allowed_ips ? detail.allowed_ips.join(", ") : "—";

  // The server never stores the client's private key, so producing a fresh
  // .owcfg == rotating keys (invalidates the previous file). Both buttons say so.
  const rotateAndDownload = async (method, confirmCopy) => {
    if (confirmCopy) {
      const ok = await confirm({ title: EF.tr(T.rotateTitle, { name: client.name }), body: EF.tr(T.rotateBody, { name: client.name }), danger: true });
      if (!ok) return;
    }
    setBusy(method);
    try {
      const r = await C.call(method, client.name);
      if (r && r.ok && r.owcfg_base64) await C.call("save_owcfg", client.name, r.owcfg_base64);
      await C.refresh();
    } finally { setBusy(""); }
  };
  const setEnabled = async (enabled) => {
    setBusy("enable");
    try { await C.call("set_client_enabled", client.name, enabled); await C.refresh(); } finally { setBusy(""); }
  };
  const revoke = async () => {
    const ok = await confirm({ title: EF.tr(T.revokeTitle, { name: client.name }), body: EF.tr(T.revokeBody, { name: client.name }), danger: true, confirmLabel: T.detail_revoke });
    if (!ok) return;
    setBusy("revoke");
    try { await C.call("revoke_client", client.name); await C.refresh(); onClose(); } finally { setBusy(""); }
  };
  return (
    <>
      <div className="ow-drawer-scrim" onClick={onClose} />
      <aside className="ow-drawer ws-scroll" role="dialog" aria-modal="true">
        <header style={{ display: "flex", justifyContent: "space-between", alignItems: "center", padding: "18px 20px", borderBottom: "1px solid var(--line)", position: "sticky", top: 0, background: "var(--bg-2)", zIndex: 1 }}>
          <div style={{ display: "flex", alignItems: "center", gap: 10, minWidth: 0 }}>
            <span style={{ color: "var(--text-3)", display: "inline-flex" }}>{EIcons.device(client.device, 18)}</span>
            <div style={{ minWidth: 0 }}>
              <div style={{ fontSize: 16, fontWeight: 600, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }}>{client.name}</div>
              <div style={{ display: "flex", alignItems: "center", gap: 6, marginTop: 2 }}>
                <EDot tone={tone} pulse={client.state === "online"} size={6} />
                <span style={{ fontSize: 11, color: "var(--text-3)", fontFamily: "var(--font-mono)", textTransform: "uppercase", letterSpacing: ".06em" }}>{T[client.state]}</span>
              </div>
            </div>
          </div>
          <button className="ow-iconbtn" onClick={onClose} aria-label={T.a11y_close}>{EIcons.x(18)}</button>
        </header>

        <div style={{ padding: 20, display: "flex", flexDirection: "column", gap: 16 }}>
          <ECard pad={14} style={{ background: "var(--bg)" }}>
            <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 10 }}>
              <span style={{ fontSize: 11, fontWeight: 600, color: "var(--text-3)", letterSpacing: ".08em", textTransform: "uppercase", fontFamily: "var(--font-mono)" }}>{T.detail_session}</span>
              {(client.state === "online" || client.state === "idle") && <EPill tone="good">{EIcons.bolt(11)} {T.detail_live}</EPill>}
              {client.state === "pending" && <EPill tone="warn">{T.detail_pending}</EPill>}
              {client.state === "disabled" && <EPill tone="neutral">{T.detail_disabled}</EPill>}
            </div>
            <div style={{ display: "grid", gridTemplateColumns: "1fr 1fr", gap: 10 }}>
              <div>
                <div style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>↓ {EF.fmtBps(client.rxBps)}</div>
                <ESpark data={client.spark} w={120} h={28} color="var(--brand)" />
              </div>
              <div>
                <div style={{ fontSize: 10, color: "var(--text-3)", fontFamily: "var(--font-mono)", textTransform: "uppercase" }}>↑ {EF.fmtBps(client.txBps)}</div>
                <ESpark data={client.sparkTx} w={120} h={28} color="var(--brand-2)" />
              </div>
            </div>
          </ECard>

          <div>
            <EKV k={T.detail_transfer} v={`↓ ${EF.fmtBytes(client.rxTotal)} · ↑ ${EF.fmtBytes(client.txTotal)}`} mono />
            <EKV k={T.col_handshake} v={EF.fmtAgo(client.hsSec, lang)} mono tone={client.state === "online" ? "var(--brand-2)" : "var(--text)"} />
            <EKV k={T.detail_endpoint} v={client.endpoint} mono />
            <EKV k={T.col_ip} v={client.ip} mono />
            <EKV k={T.detail_allowed} v={allowed} mono />
            <EKV k={T.detail_pubkey} v={client.pub} mono last />
          </div>

          <div style={{ borderTop: "1px solid var(--line)", paddingTop: 16, display: "flex", flexDirection: "column", gap: 8 }}>
            <EBtn kind="ghost" icon={EIcons.rotate(15)} disabled={!!busy} style={{ justifyContent: "flex-start" }}
              onClick={() => rotateAndDownload("rotate_client_keys", true)}>{T.detail_rotate}</EBtn>
            {client.state === "disabled" ? (
              <EBtn kind="ghost" icon={EIcons.play(15)} disabled={!!busy} style={{ justifyContent: "flex-start" }}
                onClick={() => setEnabled(true)}>{T.detail_enable}</EBtn>
            ) : (
              <EBtn kind="ghost" icon={EIcons.pause(15)} disabled={!!busy} style={{ justifyContent: "flex-start" }}
                onClick={() => setEnabled(false)}>{T.detail_disable}</EBtn>
            )}
            <EBtn kind="danger" icon={EIcons.trash(15)} disabled={!!busy} style={{ justifyContent: "flex-start" }}
              onClick={revoke}>{T.detail_revoke}</EBtn>
          </div>
        </div>
      </aside>
    </>
  );
}

Object.assign(window, { LoginScreen, ConfirmDialog, AddClientModal, ClientDrawer });
