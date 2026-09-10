import { afterEach, beforeEach, vi } from "vitest";

beforeEach(() => {
  // View modules wire themselves on import and Vitest caches modules per
  // process. Without this, the second test in a file re-uses the first
  // test's instance, still bound to the first test's (discarded) DOM.
  vi.resetModules();
  localStorage.clear();
  sessionStorage.clear();
});

afterEach(() => {
  vi.useRealTimers();
});
