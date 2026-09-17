import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";

// Imported per test: connectivity.js registers itself with api.js's
// `setConnectivityHandler` and window listeners at module load, and
// setup.js's `vi.resetModules()` means each test needs its own fresh
// instance of that wiring rather than reusing the previous test's.
let connectivity;
beforeEach(async () => {
  connectivity = await import("../../../backend/static/connectivity.js");
});

afterEach(() => {
  vi.useRealTimers();
});

describe("initial state", () => {
  it("starts online", () => {
    expect(connectivity.isOnline()).toBe(true);
  });

  it("subscribeConnectivity calls the handler immediately with the current state", () => {
    const handler = vi.fn();
    connectivity.subscribeConnectivity(handler);
    expect(handler).toHaveBeenCalledExactlyOnceWith(true);
  });
});

describe("the browser's own offline/online events", () => {
  it("offline marks the state false immediately, no request needed", () => {
    const handler = vi.fn();
    connectivity.subscribeConnectivity(handler);
    window.dispatchEvent(new Event("offline"));
    expect(connectivity.isOnline()).toBe(false);
    expect(handler).toHaveBeenLastCalledWith(false);
  });

  it("online triggers a real check rather than trusting the event outright", async () => {
    window.dispatchEvent(new Event("offline"));
    server.use(http.get("/auth/me", () => HttpResponse.error()));
    window.dispatchEvent(new Event("online"));
    await vi.waitFor(() => {}); // let the async checkNow() settle
    // The interface says it's up, but the server still isn't reachable --
    // the event alone must not have cleared the state.
    expect(connectivity.isOnline()).toBe(false);

    server.use(http.get("/auth/me", () => HttpResponse.json({}, { status: 401 })));
    window.dispatchEvent(new Event("online"));
    await vi.waitFor(() => expect(connectivity.isOnline()).toBe(true));
  });
});

describe("a real request failing or succeeding (api.js's connectivity handler)", () => {
  it("a network-level failure anywhere marks offline", async () => {
    server.use(http.get("/auth/me", () => HttpResponse.error()));
    const api = await import("../../../backend/static/api.js");
    await expect(api.apiMe()).rejects.toBeTruthy();
    expect(connectivity.isOnline()).toBe(false);
  });

  it("any response at all -- even a 4xx -- marks online", async () => {
    window.dispatchEvent(new Event("offline"));
    expect(connectivity.isOnline()).toBe(false);

    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: "no" }, { status: 401 })));
    const api = await import("../../../backend/static/api.js");
    await expect(api.apiMe()).rejects.toMatchObject({ status: 401 });
    expect(connectivity.isOnline()).toBe(true);
  });
});

describe("checkNow", () => {
  it("resolves to the resulting state on success and failure alike", async () => {
    server.use(http.get("/auth/me", () => HttpResponse.error()));
    expect(await connectivity.checkNow()).toBe(false);

    server.use(http.get("/auth/me", () => HttpResponse.json({})));
    expect(await connectivity.checkNow()).toBe(true);
  });
});

describe("the periodic probe while offline", () => {
  it("keeps retrying on an interval until one succeeds", async () => {
    vi.useFakeTimers();
    server.use(http.get("/auth/me", () => HttpResponse.error()));
    window.dispatchEvent(new Event("offline"));
    expect(connectivity.isOnline()).toBe(false);

    server.use(http.get("/auth/me", () => HttpResponse.json({})));
    await vi.advanceTimersByTimeAsync(8000);
    expect(connectivity.isOnline()).toBe(true);
  });

  it("stops polling once back online", async () => {
    vi.useFakeTimers();
    server.use(http.get("/auth/me", () => HttpResponse.error()));
    window.dispatchEvent(new Event("offline"));
    server.use(http.get("/auth/me", () => HttpResponse.json({})));
    await vi.advanceTimersByTimeAsync(8000);
    expect(connectivity.isOnline()).toBe(true);

    // If the timer were still running, this handler would have been
    // dispatched again by the next tick; it must not be.
    const handler = vi.fn();
    connectivity.subscribeConnectivity(handler);
    await vi.advanceTimersByTimeAsync(16000);
    expect(handler).toHaveBeenCalledExactlyOnceWith(true); // only the initial sync call
  });
});
