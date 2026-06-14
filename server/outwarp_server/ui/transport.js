// OutWarp UI transport shim.
//
// One surface, two backends. The dashboard never calls the bridge directly —
// it calls OW.call(method, ...args) and listens for the same outwarp:<name>
// CustomEvents in both modes:
//
//   pywebview (desktop) : OW.call delegates to window.pywebview.api.<method>;
//                         events already arrive as window CustomEvents.
//   web (browser)       : OW.call POSTs /api/<method>; an EventSource on
//                         /events re-dispatches each SSE message as the same
//                         window CustomEvent the UI already listens for.
//
// save_owcfg / export_logs are special-cased in web mode: the file belongs on
// the *admin's* machine, not the server's disk, so we download client-side
// from data the API already returned instead of POSTing.

(function () {
  const isPywebview = typeof window !== "undefined" && !!window.pywebview;

  function waitForPywebview() {
    return new Promise((resolve) => {
      const tick = () => {
        if (window.pywebview && window.pywebview.api) return resolve(window.pywebview.api);
        setTimeout(tick, 30);
      };
      tick();
    });
  }

  // ── web helpers ────────────────────────────────────────────────────────
  function triggerDownload(filename, bytes, mime) {
    const blob = new Blob([bytes], { type: mime || "application/octet-stream" });
    const url = URL.createObjectURL(blob);
    const a = document.createElement("a");
    a.href = url;
    a.download = filename;
    document.body.appendChild(a);
    a.click();
    a.remove();
    setTimeout(() => URL.revokeObjectURL(url), 1000);
  }

  function b64ToBytes(b64) {
    const bin = atob(b64);
    const out = new Uint8Array(bin.length);
    for (let i = 0; i < bin.length; i++) out[i] = bin.charCodeAt(i);
    return out;
  }

  async function webCall(method, args) {
    // Downloads can't write to the server's filesystem in web mode — hand the
    // bytes to the browser instead.
    if (method === "save_owcfg") {
      const [name, b64] = args;
      triggerDownload(`${name}.owcfg`, b64ToBytes(b64), "application/octet-stream");
      return { ok: true, downloaded: true };
    }
    if (method === "export_logs") {
      const logs = await webCall("get_logs", [0]);
      const lines = (logs || []).map((e) => {
        const t = new Date((e.ts || 0) * 1000).toISOString();
        return `${t} [${(e.level || "info").toUpperCase()}] ${e.msg}`;
      });
      triggerDownload("outwarp-server-logs.txt", lines.join("\n") + "\n", "text/plain");
      return { ok: true, downloaded: true };
    }
    const res = await fetch("/api/" + method, {
      method: "POST",
      credentials: "same-origin",
      headers: {
        "Content-Type": "application/json",
        "X-OutWarp-Panel": "1",
      },
      body: JSON.stringify(args || []),
    });
    if (res.status === 401) {
      window.dispatchEvent(new CustomEvent("outwarp:unauthorized", { detail: {} }));
      throw new Error("unauthorized");
    }
    const text = await res.text();
    if (!text) return null;
    try {
      return JSON.parse(text);
    } catch (_e) {
      return text;
    }
  }

  function startEventStream() {
    // EventSource auto-reconnects; we re-dispatch every named SSE event as the
    // window CustomEvent the dashboard already listens for.
    const NAMES = [
      "status", "clients", "log", "settings", "setup_progress", "setup_done",
    ];
    const es = new EventSource("/events");
    NAMES.forEach((name) => {
      es.addEventListener("outwarp:" + name, (ev) => {
        let detail = {};
        try { detail = JSON.parse(ev.data); } catch (_e) { detail = {}; }
        window.dispatchEvent(new CustomEvent("outwarp:" + name, { detail }));
      });
    });
    es.onerror = () => { /* EventSource retries on its own */ };
    return es;
  }

  // ── public surface ──────────────────────────────────────────────────────
  const OW = {
    mode: isPywebview ? "pywebview" : "web",
    isWeb: !isPywebview,

    async call(method, ...args) {
      if (isPywebview) {
        const api = await waitForPywebview();
        return api[method](...args);
      }
      return webCall(method, args);
    },

    on(name, handler) {
      const wrapped = (e) => handler(e.detail);
      window.addEventListener("outwarp:" + name, wrapped);
      return () => window.removeEventListener("outwarp:" + name, wrapped);
    },

    // Web-only auth surface (no-ops under pywebview, which is already local).
    async login(token, remember) {
      if (isPywebview) return { ok: true };
      const res = await fetch("/auth", {
        method: "POST",
        credentials: "same-origin",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({ token, remember: !!remember }),
      });
      let body = {};
      try { body = await res.json(); } catch (_e) { body = {}; }
      return { ok: res.ok && body.ok !== false, status: res.status, ...body };
    },

    async logout() {
      if (isPywebview) return { ok: true };
      try {
        await fetch("/logout", {
          method: "POST",
          credentials: "same-origin",
          headers: { "X-OutWarp-Panel": "1" },
        });
      } catch (_e) { /* best effort */ }
      return { ok: true };
    },
  };

  if (OW.isWeb) {
    // Kick the SSE stream once the page is interactive. If the user isn't
    // authenticated yet /events 401s and EventSource keeps retrying — it
    // connects for real right after login.
    OW._es = startEventStream();
  }

  window.OW = OW;
})();
