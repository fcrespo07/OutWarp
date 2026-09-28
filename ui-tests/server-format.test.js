import { beforeAll, describe, expect, it } from "vitest";
import { loadUi } from "./load.js";

let DSfmt;
beforeAll(() => {
  DSfmt = loadUi("server/outwarp_server/ui/dash-data.jsx").DSfmt;
});

describe("makeBoundedPeak (B-022)", () => {
  it("never scales below 1", () => {
    const peak = DSfmt.makeBoundedPeak(3);
    expect(peak(0)).toBe(1);
  });

  it("holds a spike only for `memory` samples, then follows what is on screen", () => {
    const peak = DSfmt.makeBoundedPeak(3);
    expect(peak(1_000_000)).toBe(1_000_000); // speed test
    expect(peak(500)).toBe(1_000_000);
    expect(peak(500)).toBe(1_000_000);
    // Spike scrolled out of the trailing history: a real 500 B/s is drawn at
    // full height again instead of as a flat line under a stale peak.
    expect(peak(500)).toBe(500);
  });

  it("does not let one low sample collapse the scale", () => {
    const peak = DSfmt.makeBoundedPeak(3);
    peak(800);
    expect(peak(10)).toBe(800);
  });
});

describe("byte and rate formatting", () => {
  it("formats bytes with binary units", () => {
    expect(DSfmt.fmtBytes(null)).toBe("—");
    expect(DSfmt.fmtBytes(512)).toBe("512 B");
    expect(DSfmt.fmtBytes(1536)).toBe("1.5 KB");
    expect(DSfmt.fmtBytes(200 * 1024 * 1024)).toBe("200 MB");
    expect(DSfmt.fmtBytes(3 * 1024 ** 4)).toBe("3.0 TB");
  });

  it("formats rates", () => {
    expect(DSfmt.fmtBps(0)).toBe("0 B/s");
    expect(DSfmt.fmtBps(2048)).toBe("2.0 KB/s");
  });

  it("formats elapsed seconds per language", () => {
    expect(DSfmt.fmtAgo(null, "en")).toBe("—");
    expect(DSfmt.fmtAgo(42, "en")).toBe("42s ago");
    expect(DSfmt.fmtAgo(125, "es")).toBe("hace 2m");
    expect(DSfmt.fmtAgo(3 * 86400, "en")).toBe("3d ago");
  });

  it("formats durations", () => {
    expect(DSfmt.fmtDuration(3661)).toBe("01:01:01");
    expect(DSfmt.fmtDuration(90061)).toBe("1d 01h 01m");
  });
});

describe("smoothPath (dashboard charts)", () => {
  const nums = (d) => d.match(/-?\d+(\.\d+)?/g).map(Number);

  it("draws cubic curves through every sample instead of a polyline", () => {
    const d = DSfmt.smoothPath([[0, 50], [10, 10], [20, 50], [30, 50]]);
    expect(d.startsWith("M0.0 50.0")).toBe(true);
    expect(d).not.toMatch(/L/);
    expect(d.match(/C/g)).toHaveLength(3);
    // Each segment ends on the next sample.
    expect(d).toContain(", 10.0 10.0");
    expect(d).toContain(", 30.0 50.0");
  });

  it("keeps control points inside [yMin, yMax] so a jump cannot cross the axis", () => {
    const d = DSfmt.smoothPath([[0, 75], [10, 75], [20, 4], [30, 75], [40, 75]], 4, 75);
    const ys = nums(d).filter((_, i) => i % 2 === 1);
    expect(Math.min(...ys)).toBeGreaterThanOrEqual(4);
    expect(Math.max(...ys)).toBeLessThanOrEqual(75);
  });

  it("handles empty and single-sample input", () => {
    expect(DSfmt.smoothPath([])).toBe("");
    expect(DSfmt.smoothPath([[1, 2]])).toBe("M1.0 2.0");
  });
});

describe("smoothSeries (dashboard charts)", () => {
  it("flattens sample-to-sample jitter but keeps a steady level", () => {
    const out = DSfmt.smoothSeries([10, 10, 10, 10, 10]);
    expect(out).toEqual([10, 10, 10, 10, 10]);
    const jitter = DSfmt.smoothSeries([0, 90, 0, 90, 0, 90, 0]);
    const spread = (a) => Math.max(...a) - Math.min(...a);
    expect(spread(jitter.slice(2, -2))).toBeLessThan(90 / 4);
  });

  it("renormalises at the edges so the newest sample is not pulled to zero", () => {
    const out = DSfmt.smoothSeries([50, 50, 50]);
    expect(out[2]).toBe(50);
  });
});
