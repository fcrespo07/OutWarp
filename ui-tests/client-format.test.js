import { beforeAll, describe, expect, it } from "vitest";
import { loadUi } from "./load.js";

let OWfmt;
beforeAll(() => {
  OWfmt = loadUi("client/outwarp/ui/shared.jsx").OWfmt;
});

describe("client formatters", () => {
  it("formats rates and totals", () => {
    expect(OWfmt.fmtBps(0)).toBe("0 B/s");
    expect(OWfmt.fmtBps(900)).toBe("900 B/s");
    expect(OWfmt.fmtBps(1536)).toBe("1.5 KB/s");
    expect(OWfmt.fmtBytes(5 * 1024 ** 3)).toBe("5.00 GB");
  });

  it("formats an expiry date in the UI language without shifting the day", () => {
    expect(OWfmt.fmtDate("2027-01-31", "en")).toBe("Jan 31, 2027");
    expect(OWfmt.fmtDate("2027-01-31", "es")).toMatch(/^31 ene 2027$/);
    expect(OWfmt.fmtDate("not a date", "en")).toBe("not a date");
    expect(OWfmt.fmtDate("", "en")).toBe("");
  });

  it("formats durations as a clock", () => {
    expect(OWfmt.fmtDuration(59)).toBe("00:00:59");
    expect(OWfmt.fmtDuration(-5)).toBe("00:00:00");
  });

  it("describes a handshake relative to an injected now", () => {
    const now = 1_700_000_000_000;
    const at = now / 1000;
    expect(OWfmt.fmtAgo(0, "en", now)).toBe("—");
    expect(OWfmt.fmtAgo(at - 30, "en", now)).toBe("30 seconds ago");
    expect(OWfmt.fmtAgo(at - 120, "en", now)).toBe("2 minutes ago");
    expect(OWfmt.fmtAgo(at - 7200, "en", now)).toBe("2 hours ago");
    // A handshake stamped slightly in the future (clock skew) is "now", not negative.
    expect(OWfmt.fmtAgo(at + 5, "en", now)).toBe("now");
  });
});
