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
