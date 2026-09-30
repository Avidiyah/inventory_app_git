import { afterAll, afterEach, beforeAll, beforeEach, vi } from "vitest";
import { server } from "./helpers/handlers.js";

// jsdom has no canvas: `getContext` returns null. A no-op 2d context keeps a
// view that draws (the signature pad) from crashing when a test merely
// reopens its section; tests that assert on drawing install their own spies.
HTMLCanvasElement.prototype.getContext = () => new Proxy({}, { get: () => () => {} });

beforeAll(() => {
  // An un-mocked fetch must fail the test, not resolve to undefined and
  // leave a green test standing over a broken call.
  server.listen({ onUnhandledRequest: "error" });
});

beforeEach(() => {
  // View modules wire themselves on import and Vitest caches modules per
  // process. Without this, the second test in a file re-uses the first
  // test's instance, still bound to the first test's (discarded) DOM.
  vi.resetModules();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  server.resetHandlers();
  vi.useRealTimers();
});

afterAll(() => {
  server.close();
});
