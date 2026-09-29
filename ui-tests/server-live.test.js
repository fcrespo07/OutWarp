import { beforeAll, describe, expect, it } from "vitest";
import { loadUi } from "./load.js";

let DSfmt;
beforeAll(() => {
  DSfmt = loadUi("server/outwarp_server/ui/dash-data.jsx").DSfmt;
});

describe("nextRate (B-037)", () => {
  const row = (t, rx, tx = 0) => ({ sampled_at: t, rx_bytes: rx, tx_bytes: tx });

  it("needs two readings", () => {
    const r = DSfmt.nextRate(undefined, row(100, 5000), 100);
    expect(r.advanced).toBe(false);
    expect(r.state.rxBps).toBe(0);
  });

  it("divides by the real gap between readings", () => {
    const a = DSfmt.nextRate(undefined, row(100, 0), 100).state;
    const b = DSfmt.nextRate(a, row(102, 4000, 2000), 102);
    expect(b.advanced).toBe(true);
    expect(b.state.rxBps).toBe(2000);
    expect(b.state.txBps).toBe(1000);
  });

  it("ignores a second reading a few ms later instead of drawing a dip or a spike", () => {
    const a = DSfmt.nextRate(undefined, row(100, 0), 100).state;
    const b = DSfmt.nextRate(a, row(102, 4000), 102).state;
    const c = DSfmt.nextRate(b, row(102.05, 4100), 102.05);
    expect(c.advanced).toBe(false);
    expect(c.state).toBe(b);           // previous rate stands
  });
});

describe("mergeLogs (B-037)", () => {
  const e = (seq) => ({ seq, ts: 1_700_000_000, level: "info", msg: `line ${seq}` });

  it("keeps each entry once whether it came from an event or a fetch", () => {
    let st = DSfmt.mergeLogs([], 0, [e(1), e(2)]);
    st = DSfmt.mergeLogs(st.logs, st.lastSeq, [e(2)]);        // the same line as an event
    st = DSfmt.mergeLogs(st.logs, st.lastSeq, [e(2), e(3)]);  // and in a fetch
    expect(st.logs.map((l) => l.seq)).toEqual([1, 2, 3]);
    expect(st.lastSeq).toBe(3);
  });

  it("returns the same array when nothing is new, so the page does not repaint", () => {
    const st = DSfmt.mergeLogs([], 0, [e(1)]);
    expect(DSfmt.mergeLogs(st.logs, st.lastSeq, [e(1)]).logs).toBe(st.logs);
  });

  it("starts over when the server restarted and counts from 1 again", () => {
    let st = DSfmt.mergeLogs([], 0, [e(50), e(51)]);
    st = DSfmt.mergeLogs(st.logs, st.lastSeq, [e(1), e(2)]);
    expect(st.logs.map((l) => l.seq)).toEqual([1, 2]);
  });

  it("keeps at most `max` lines and still follows the newest", () => {
    const st = DSfmt.mergeLogs([], 0, [e(1), e(2), e(3)], 2);
    expect(st.logs.map((l) => l.seq)).toEqual([2, 3]);
  });
});

describe("small rates are rounded (B-039)", () => {
  it("never prints a long fraction", () => {
    expect(DSfmt.fmtBps(303.17889579135374)).toBe("303 B/s");
    expect(DSfmt.fmtBytes(0.4)).toBe("0 B");
  });
});
