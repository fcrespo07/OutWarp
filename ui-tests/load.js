// Load one UI source file the way the bundle does (its own IIFE, globals on
// window) so tests can reach what it publishes, e.g. window.DSfmt. The UI is
// not ES modules on purpose (see scripts/build_ui.py); this keeps it that way.
import { readFileSync } from "node:fs";
import { fileURLToPath } from "node:url";
import path from "node:path";
import { transformSync } from "esbuild";

export const ROOT = path.resolve(path.dirname(fileURLToPath(import.meta.url)), "..");

// Enough of React for a file's top level to run; components are not rendered.
const reactStub = {
  createElement: (type, props, ...children) => ({ type, props, children }),
  Fragment: "Fragment",
  Component: class {},
  useState: (v) => [v, () => {}],
  useEffect: () => {},
  useLayoutEffect: () => {},
  useCallback: (f) => f,
  useMemo: (f) => f(),
  useRef: (v) => ({ current: v }),
  useContext: () => undefined,
  createContext: () => ({}),
};

export function loadUi(relPath) {
  const src = readFileSync(path.join(ROOT, relPath), "utf8");
  const { code } = transformSync(`;(function(){\n${src}\n})();`, { loader: "jsx" });
  globalThis.window ??= globalThis;
  globalThis.React = reactStub;
  new Function(code)();
  return globalThis.window;
}
