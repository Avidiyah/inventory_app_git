// Characterization coverage for service-worker.js -- the only code in the
// app that runs with no DOM, no modules and no session: install, activate,
// push and notificationclick.
//
// The seam is the worker's global. `vi.stubGlobal("self", fakeSelf)` installs
// a scope whose `addEventListener` captures the four handlers by type, then
// `importView` executes the real file against it (a `new Function` wrapper
// would keep it out of the v8 coverage report). Each test imports its own
// copy -- `setup.js` resets the module registry per test.

import { afterEach, describe, expect, it, vi } from "vitest";
import { importView } from "../helpers/shell.js";

const FALLBACK_TITLE = "Inventory";
const FALLBACK_BODY = "You have a new notification.";

function fakeClient({ focus = true, id = "c1" } = {}) {
  const client = { id };
  if (focus) client.focus = vi.fn(async () => `focused:${id}`);
  return client;
}

async function mountServiceWorker({ clients = [], openWindow = true } = {}) {
  const listeners = new Map();
  const self = {
    addEventListener: vi.fn((type, handler) => listeners.set(type, handler)),
    skipWaiting: vi.fn(),
    clients: {
      claim: vi.fn(async () => "claimed"),
      matchAll: vi.fn(async () => clients),
    },
    registration: { showNotification: vi.fn(async () => {}) },
  };
  if (openWindow) self.clients.openWindow = vi.fn(async () => "opened");
  vi.stubGlobal("self", self);
  await importView("service-worker.js");

  // Fire one event and hand back whatever it passed to `waitUntil`, already
  // awaited: every branch of this worker lives inside that promise.
  const fire = async (type, event = {}) => {
    const held = [];
    const full = { ...event, waitUntil: vi.fn((promise) => held.push(promise)) };
    listeners.get(type)(full);
    const results = await Promise.all(held);
    return { event: full, results, result: results[0] };
  };
  return { self, listeners, fire };
}

afterEach(() => {
  vi.unstubAllGlobals();
});

describe("the lifecycle handlers", () => {
  it("registers exactly four listeners", async () => {
    const { listeners } = await mountServiceWorker();
    expect([...listeners.keys()]).toEqual(["install", "activate", "push", "notificationclick"]);
  });

  it("install takes over immediately instead of waiting for every tab to close", async () => {
    const { self, fire } = await mountServiceWorker();
    await fire("install");
    expect(self.skipWaiting).toHaveBeenCalled();
  });

  it("activate claims the open pages, and holds the event until it has", async () => {
    const { self, fire } = await mountServiceWorker();
    const { event, result } = await fire("activate");
    expect(self.clients.claim).toHaveBeenCalled();
    expect(event.waitUntil).toHaveBeenCalledTimes(1);
    expect(result).toBe("claimed");
  });
});

describe("push", () => {
  const shown = (self) => self.registration.showNotification.mock.calls[0];
  const payload = (json) => ({ data: { json } });

  it("a push with no payload still shows the fallback notification", async () => {
    const { self, fire } = await mountServiceWorker();
    await fire("push", { data: null });
    expect(shown(self)).toEqual([FALLBACK_TITLE, {
      body: FALLBACK_BODY,
      icon: "/static/icon-180.png",
      badge: "/static/icon-180.png",
      tag: "inventory-notification",
    }]);
  });

  it("a full payload is shown with the shared icon, badge and collapse tag", async () => {
    const { self, fire } = await mountServiceWorker();
    await fire("push", payload(() => ({ title: "WO 412", body: "Returned to In-Progress" })));
    expect(shown(self)).toEqual(["WO 412", {
      body: "Returned to In-Progress",
      icon: "/static/icon-180.png",
      badge: "/static/icon-180.png",
      tag: "inventory-notification",
    }]);
  });

  it("a missing title falls back on the title alone", async () => {
    const { self, fire } = await mountServiceWorker();
    await fire("push", payload(() => ({ body: "Just the body" })));
    expect(shown(self)[0]).toBe(FALLBACK_TITLE);
    expect(shown(self)[1].body).toBe("Just the body");
  });

  it("a missing body falls back on the body alone", async () => {
    const { self, fire } = await mountServiceWorker();
    await fire("push", payload(() => ({ title: "Just the title" })));
    expect(shown(self)[0]).toBe("Just the title");
    expect(shown(self)[1].body).toBe(FALLBACK_BODY);
  });

  it("an empty string is not a title: the fallback answers falsy, not absent", async () => {
    const { self, fire } = await mountServiceWorker();
    await fire("push", payload(() => ({ title: "", body: "" })));
    expect(shown(self)[0]).toBe(FALLBACK_TITLE);
    expect(shown(self)[1].body).toBe(FALLBACK_BODY);
  });

  it("a payload that will not parse shows the fallback rather than nothing", async () => {
    const { self, fire } = await mountServiceWorker();
    await fire("push", payload(() => { throw new SyntaxError("Unexpected token <"); }));
    expect(shown(self)[0]).toBe(FALLBACK_TITLE);
    expect(shown(self)[1].body).toBe(FALLBACK_BODY);
  });

  it("holds the event until the notification is on screen", async () => {
    const { event } = await mountServiceWorker().then((m) => m.fire("push", { data: null }));
    expect(event.waitUntil).toHaveBeenCalledTimes(1);
  });
});

describe("notificationclick", () => {
  const clickEvent = () => ({ notification: { close: vi.fn() } });

  it("closes the notification and looks for a window this worker may not control yet", async () => {
    const { self, fire } = await mountServiceWorker();
    const { event } = await fire("notificationclick", clickEvent());
    expect(event.notification.close).toHaveBeenCalled();
    expect(self.clients.matchAll).toHaveBeenCalledWith({ type: "window", includeUncontrolled: true });
  });

  it("focuses an open window rather than launching a second one", async () => {
    const client = fakeClient({ id: "open" });
    const { self, fire } = await mountServiceWorker({ clients: [client] });
    const { result } = await fire("notificationclick", clickEvent());
    expect(client.focus).toHaveBeenCalled();
    expect(result).toBe("focused:open");
    expect(self.clients.openWindow).not.toHaveBeenCalled();
  });

  it("skips a client that cannot be focused and takes the next one that can", async () => {
    const unfocusable = fakeClient({ focus: false, id: "worker" });
    const focusable = fakeClient({ id: "tab" });
    const { fire } = await mountServiceWorker({ clients: [unfocusable, focusable] });
    const { result } = await fire("notificationclick", clickEvent());
    expect(focusable.focus).toHaveBeenCalled();
    expect(result).toBe("focused:tab");
  });

  it("with nothing open, launches the app at the root", async () => {
    const { self, fire } = await mountServiceWorker({ clients: [] });
    const { result } = await fire("notificationclick", clickEvent());
    expect(self.clients.openWindow).toHaveBeenCalledWith("/");
    expect(result).toBe("opened");
  });

  it("a browser without openWindow resolves to nothing at all", async () => {
    const { fire } = await mountServiceWorker({ clients: [], openWindow: false });
    const { result } = await fire("notificationclick", clickEvent());
    expect(result).toBeUndefined();
  });
});
