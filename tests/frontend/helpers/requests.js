// One request recorder for every view fixture.
//
// Wraps MSW's own `fetch` replacement, so the recorder sees exactly the `init`
// api.js built and MSW still answers the call. Synchronous by construction
// (`requestFor` right after an await is reliable); MSW's `request:start` event
// would hand back a body only after a further await.
//
// Lifted out of `helpers/auth.js` / `helpers/items.js` in P5d -- they had
// identical private copies. `helpers/workOrders.js` still carries its own.

import { vi } from "vitest";

let recorded = [];
let originalFetch = null;

export function startRecording() {
  if (originalFetch) return;
  originalFetch = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input, init = {}) => {
    let body = init.body ?? null;
    if (typeof body === "string") {
      try { body = JSON.parse(body); } catch { /* a non-JSON body is kept raw */ }
    }
    recorded.push({
      url: typeof input === "string" ? input : input.url,
      method: (init.method || "GET").toUpperCase(),
      body,
    });
    return originalFetch(input, init);
  });
}

export function stopRecording() {
  if (originalFetch) {
    globalThis.fetch = originalFetch;
    originalFetch = null;
  }
  recorded = [];
}

export const requests = () => recorded;

// The most recent call whose url contains `fragment` (and method matches, if
// given). A substring match, not a path match: the assertions care about
// `/work-orders/?q=4242` as much as about `/auth/login`.
export const requestFor = (fragment, method = null) =>
  [...recorded].reverse().find((r) => r.url.includes(fragment) && (!method || r.method === method)) ?? null;

export const clearRequests = () => { recorded = []; };
