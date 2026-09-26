// The committed bundle.js files are what users run; the .jsx are what people
// edit. This fails when someone edits a .jsx and forgets to rebuild.
import { execFileSync } from "node:child_process";
import { readFileSync } from "node:fs";
import path from "node:path";
import { describe, expect, it } from "vitest";
import { ROOT } from "./load.js";

const python = process.env.PYTHON || (process.platform === "win32" ? "python" : "python3");

describe("committed UI bundles", () => {
  it("match their .jsx sources (python scripts/build_ui.py --check)", () => {
    const run = () => execFileSync(python, [path.join(ROOT, "scripts", "build_ui.py"), "--check"], {
      cwd: ROOT, encoding: "utf8", stdio: "pipe",
    });
    expect(run).not.toThrow();
  });

  it("are built with the esbuild version package.json pins", () => {
    const pkg = JSON.parse(readFileSync(path.join(ROOT, "package.json"), "utf8"));
    const script = readFileSync(path.join(ROOT, "scripts", "build_ui.py"), "utf8");
    const pinned = script.match(/^ESBUILD_VERSION = "([^"]+)"/m)[1];
    expect(pkg.devDependencies.esbuild).toBe(pinned);
  });
});
