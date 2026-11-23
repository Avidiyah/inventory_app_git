import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";

// Imported fresh per test: api.js holds `unauthorizedHandler` in module scope,
// and setup.js resets the module registry between tests.
let api;
beforeEach(async () => {
  api = await import("../../../backend/static/api.js");
});

describe("apiGetWorkOrder", () => {
  it("returns the parsed body on 200", async () => {
    server.use(http.get("/work-orders/:id", () => HttpResponse.json({ id: 7, number: "WO-7" })));
    await expect(api.apiGetWorkOrder(7)).resolves.toEqual({ id: 7, number: "WO-7" });
  });

  it("throws {status, detail} on a 422 validation error", async () => {
    server.use(http.get("/work-orders/:id", () =>
      HttpResponse.json({ detail: [{ msg: "value is not a valid integer" }] }, { status: 422 })));
    await expect(api.apiGetWorkOrder("abc")).rejects.toEqual({
      status: 422,
      detail: [{ msg: "value is not a valid integer" }],
    });
  });

  it("throws the string detail on a 403", async () => {
    server.use(http.get("/work-orders/:id", () =>
      HttpResponse.json({ detail: "Not allowed" }, { status: 403 })));
    await expect(api.apiGetWorkOrder(7)).rejects.toEqual({ status: 403, detail: "Not allowed" });
  });

  it("fires the unauthorized handler on a 401, and still throws", async () => {
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    server.use(http.get("/work-orders/:id", () =>
      HttpResponse.json({ detail: "Not authenticated" }, { status: 401 })));
    await expect(api.apiGetWorkOrder(7)).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledOnce();
  });

  it("short-circuits a 204 to null", async () => {
    server.use(http.get("/work-orders/:id", () => new HttpResponse(null, { status: 204 })));
    await expect(api.apiGetWorkOrder(7)).resolves.toBeNull();
  });

  it("falls back to the raw text when the body is not JSON", async () => {
    server.use(http.get("/work-orders/:id", () =>
      new HttpResponse("upstream exploded", { status: 502 })));
    await expect(api.apiGetWorkOrder(7)).rejects.toEqual({
      status: 502,
      detail: "upstream exploded",
    });
  });
});

describe("setSampleResponder", () => {
  const throwIfHit = () => server.use(http.get("/work-orders/", () => { throw new Error("reached the network"); }));

  it("answers a listed GET without reaching the network", async () => {
    throwIfHit();
    api.setSampleResponder((path) => (path === "/work-orders/" ? [{ id: "x" }] : undefined));
    await expect(api.apiListWorkOrders()).resolves.toEqual([{ id: "x" }]);
  });

  it("lets an unlisted GET through", async () => {
    server.use(http.get("/work-orders/", () => HttpResponse.json([{ id: "real" }])));
    api.setSampleResponder(() => undefined);
    await expect(api.apiListWorkOrders()).resolves.toEqual([{ id: "real" }]);
  });

  it("answers nothing after it is cleared", async () => {
    server.use(http.get("/work-orders/", () => HttpResponse.json([{ id: "real" }])));
    api.setSampleResponder(() => [{ id: "x" }]);
    api.setSampleResponder(null);
    await expect(api.apiListWorkOrders()).resolves.toEqual([{ id: "real" }]);
  });

  it("is called with the path alone, query stripped", async () => {
    throwIfHit();
    const fn = vi.fn((path) => (path === "/work-orders/" ? [] : undefined));
    api.setSampleResponder(fn);
    await expect(api.apiListWorkOrders({ status: "x", mine: true })).resolves.toEqual([]);
    expect(fn).toHaveBeenCalledWith("/work-orders/");
  });

  it("never sees a write", async () => {
    server.use(http.post("/auth/logout", () => new HttpResponse(null, { status: 204 })));
    const fn = vi.fn(() => ({}));
    api.setSampleResponder(fn);
    await api.apiLogout();
    expect(fn).not.toHaveBeenCalled();
  });
});

describe("unhandled requests", () => {
  it("fail loudly rather than resolving to undefined", async () => {
    // No handler registered for this path.
    await expect(api.apiGetHub()).rejects.toBeDefined();
  });
});
