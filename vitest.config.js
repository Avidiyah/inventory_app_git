import { defineConfig } from "vitest/config";

export default defineConfig({
  test: {
    environment: "jsdom",
    globals: false,
    include: ["tests/frontend/**/*.test.js"],
    setupFiles: ["tests/frontend/setup.js"],
    // The app's modules are import-time singletons that capture DOM nodes.
    // A module registry shared across files would leak a dead DOM into the
    // next file, so each test file gets its own worker.
    isolate: true,
    coverage: {
      provider: "v8",
      include: ["backend/static/**/*.js"],
      exclude: ["backend/static/vendor/**"],
      reporter: ["text-summary", "lcov"],
      // Advisory in P0. Turned blocking in P7 at the level then achieved.
      thresholds: undefined,
    },
  },
});
