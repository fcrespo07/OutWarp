import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { loadUi } from "./load.js";

// The panel opens /events on load, before the admin has logged in. The
// browser closes an EventSource for good on an HTTP error (readyState 2), so
// without an explicit reopen the dashboard got no live status, clients or
// logs after logging in until the page was reloaded (B-036).
class FakeEventSource {
  static all = [];
  constructor(url) {
    this.url = url;
    this.readyState = 0;
    FakeEventSource.all.push(this);
  }
  addEventListener() {}
  fail(closed) { this.readyState = closed ? 2 : 0; this.onerror?.(); }
  open() { this.readyState = 1; this.onopen?.(); }
}

function loadTransport() {
  globalThis.window = globalThis;
  delete globalThis.pywebview;
  globalThis.EventSource = FakeEventSource;
  globalThis.CustomEvent = class { constructor(type, init) { this.type = type; this.detail = init?.detail; } };
  const seen = [];
  globalThis.dispatchEvent = (e) => seen.push(e.type);
  globalThis.fetch = vi.fn(async () => ({ ok: true, status: 200, json: async () => ({ ok: true }), text: async () => "{}" }));
  loadUi("server/outwarp_server/ui/transport.js");
  return seen;
}

describe("panel event stream", () => {
  beforeEach(() => { FakeEventSource.all = []; vi.useFakeTimers(); });
  afterEach(() => { vi.useRealTimers(); });

  it("reopens the stream right after a successful login", async () => {
    loadTransport();
    expect(FakeEventSource.all).toHaveLength(1);
    FakeEventSource.all[0].fail(true); // 401 before login: closed for good
    await window.OW.login("token", false);
    expect(FakeEventSource.all).toHaveLength(2);
  });

  it("does not open a second stream while one is alive", async () => {
    loadTransport();
    FakeEventSource.all[0].open();
    await window.OW.login("token", false);
    expect(FakeEventSource.all).toHaveLength(1);
  });

  it("retries by itself when the browser gives up, and asks the page to resync", () => {
    const seen = loadTransport();
    FakeEventSource.all[0].fail(true);
    vi.advanceTimersByTime(1000);
    expect(FakeEventSource.all).toHaveLength(2);
    FakeEventSource.all[1].open();
    expect(seen).toContain("outwarp:resync");
  });

  it("leaves the browser's own retry alone when it is still reconnecting", () => {
    loadTransport();
    FakeEventSource.all[0].fail(false);
    vi.advanceTimersByTime(20000);
    expect(FakeEventSource.all).toHaveLength(1);
  });
});
