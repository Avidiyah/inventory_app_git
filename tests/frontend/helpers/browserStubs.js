// The four browser globals `views/workOrders.js` reaches for that jsdom either
// does not implement or implements as a "Not implemented" console error.
//
// Each stub is a `vi.fn()` the test asserts on, so "we opened NetFacilities in
// a new tab" and "we reloaded after a 409" become assertions rather than
// console noise nobody reads. Install per test; `restoreBrowserStubs()` puts
// the originals back.

import { vi } from "vitest";

const restorers = [];

// `window.open` is a jsdom no-op that logs "Not implemented: window.open".
export function stubWindowOpen() {
  const original = window.open;
  const spy = vi.fn(() => null);
  window.open = spy;
  restorers.push(() => { window.open = original; });
  return spy;
}

// jsdom has no object-URL store, so `downloadExport` would throw on
// `URL.createObjectURL`. Both halves are stubbed together: revoking a URL the
// test invented is as unimplemented as creating one.
export function stubObjectUrl() {
  const originalCreate = URL.createObjectURL;
  const originalRevoke = URL.revokeObjectURL;
  const createObjectURL = vi.fn(() => "blob:test/1");
  const revokeObjectURL = vi.fn();
  URL.createObjectURL = createObjectURL;
  URL.revokeObjectURL = revokeObjectURL;
  restorers.push(() => {
    URL.createObjectURL = originalCreate;
    URL.revokeObjectURL = originalRevoke;
  });
  return { createObjectURL, revokeObjectURL };
}

// `reload` is not configurable on jsdom's Location, so the whole `location`
// object is replaced with a plain one carrying the fields this module reads.
// Only the 409 already-assigned path calls it. Solo-mode tests must NOT use
// this stub: the replacement is a snapshot, so `history.pushState` no longer
// moves `pathname` and `soloNumberFromPath` reads a frozen URL.
export function stubLocationReload() {
  const original = window.location;
  const reload = vi.fn();
  Object.defineProperty(window, "location", {
    configurable: true,
    writable: true,
    value: {
      href: original.href,
      origin: original.origin,
      pathname: original.pathname,
      search: original.search,
      hash: original.hash,
      reload,
    },
  });
  restorers.push(() => {
    Object.defineProperty(window, "location", {
      configurable: true,
      writable: true,
      value: original,
    });
  });
  return reload;
}

// jsdom logs "Not implemented: window.scrollTo" and never moves scrollY.
// `restoreListScrollY` defers through requestAnimationFrame, which jsdom does
// implement, so the stub is all that is missing.
export function stubScroll() {
  const original = window.scrollTo;
  const spy = vi.fn();
  window.scrollTo = spy;
  restorers.push(() => { window.scrollTo = original; });
  return spy;
}

export function restoreBrowserStubs() {
  while (restorers.length) restorers.pop()();
}
