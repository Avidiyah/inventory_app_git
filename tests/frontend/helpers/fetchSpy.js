import { vi } from "vitest";

let original = null;

// MSW replaces `globalThis.fetch`; this wraps *that* replacement, so the spy
// sees exactly the `init` object api.js built and MSW still answers the call.
// Records every (url, init) pair, then delegates. Install inside the test --
// after MSW's own patch is in place -- and restore in afterEach.
export function installFetchSpy() {
  const calls = [];
  original = globalThis.fetch;
  globalThis.fetch = vi.fn(async (input, init = {}) => {
    calls.push({ url: typeof input === "string" ? input : input.url, init });
    return original(input, init);
  });
  return calls;
}

export function restoreFetchSpy() {
  if (original) globalThis.fetch = original;
  original = null;
}
