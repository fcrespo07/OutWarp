import { beforeAll, describe, expect, it } from "vitest";
import { loadUi } from "./load.js";

let OWfmt;
let T;
beforeAll(() => {
  const w = loadUi("client/outwarp/ui/shared.jsx");
  OWfmt = w.OWfmt;
  T = w.STR.en;
});

describe("error screen: what kind of failure", () => {
  it("reads the tunnel's own messages", () => {
    expect(OWfmt.classifyError("")).toBe("generic");
    expect(OWfmt.classifyError(
      "Cannot reach vpn.example.com on any configured port (443). The server may be down",
    )).toBe("unreachable");
    expect(OWfmt.classifyError(
      "TLS certificate fingerprint mismatch for 203.0.113.42:443.",
    )).toBe("cert");
    expect(OWfmt.classifyError(
      "All connection strategies failed:\n  Direct: no WireGuard handshake",
    )).toBe("network");
    expect(OWfmt.classifyError(
      "wstunnel.exe was removed. Microsoft Defender may have quarantined it",
    )).toBe("blocked");
    expect(OWfmt.classifyError("Could not reach the enrolment endpoint")).toBe("token");
    expect(OWfmt.classifyError("something else entirely")).toBe("generic");
  });

  it("has a hint for every kind it returns", () => {
    for (const k of ["unreachable", "cert", "token", "blocked", "network", "expired"]) {
      expect(T[`err_hint_${k}`], k).toBeTruthy();
    }
  });
});

describe("home: the route the connection took", () => {
  it("names the client's own rungs and falls back to the server's label", () => {
    expect(OWfmt.routeLabel(null, T)).toBe("");
    expect(OWfmt.routeLabel({ id: "direct" }, T)).toBe("Direct");
    expect(OWfmt.routeLabel({ id: "direct-hostile" }, T)).toBe("Direct, public DNS");
    expect(OWfmt.routeLabel({ id: "direct-proxy" }, T)).toBe("Through the HTTP proxy");
    expect(OWfmt.routeLabel({ id: "port-8443", port: 8443 }, T)).toBe("Alternate port 8443");
    expect(OWfmt.routeLabel({ id: "cdn-front", label: "Cdn Front" }, T)).toBe("Cdn Front");
  });
});
