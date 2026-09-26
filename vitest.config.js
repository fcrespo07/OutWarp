import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    // node, not jsdom: esbuild refuses to run inside jsdom, and the code under
    // test only needs a `window` to publish on (see ui-tests/load.js).
    environment: "node",
    include: ["ui-tests/**/*.test.js"],
    testTimeout: 60_000,
  },
});
