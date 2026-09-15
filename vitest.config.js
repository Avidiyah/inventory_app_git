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
    // Each file builds its own jsdom and mounts the real page shell, which
    // costs seconds under load. Eight of those in parallel on a laptop made
    // otherwise-passing tests time out at the 5 s default (and occasionally
    // took a worker down), so the pool is capped and the budget widened.
    // These are wall-clock allowances, not an invitation to slow tests.
    testTimeout: 20000,
    hookTimeout: 20000,
    maxWorkers: 4,
    coverage: {
      provider: "v8",
      include: ["backend/static/**/*.js"],
      exclude: ["backend/static/vendor/**"],
      reporter: ["text-summary", "lcov"],
      // Blocking since P7f, at P7e's measured level minus 2, floored.
      // Ratcheted BY HAND at each phase close -- `autoUpdate` is not used,
      // because it rewrites this file on every local run.
      thresholds: { statements: 94, branches: 84, functions: 96, lines: 96 },
    },
  },
});
