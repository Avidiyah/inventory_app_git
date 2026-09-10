import { beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";

// api.js keeps `unauthorizedHandler` in module scope; setup.js resets the
// registry per test, so the import must happen inside the test's generation.
let api;
beforeEach(async () => {
  api = await import("../../../backend/static/api.js");
});

describe("parseResponse", () => {
  it("returns null for an empty 200 body", async () => {
    server.use(http.get("/auth/me", () => new HttpResponse("", { status: 200 })));
    await expect(api.apiMe()).resolves.toBeNull();
  });

  it("returns the raw text for a non-JSON 200 body", async () => {
    server.use(http.get("/auth/me", () => new HttpResponse("plain", { status: 200 })));
    await expect(api.apiMe()).resolves.toBe("plain");
  });

  it("uses statusText when an error body is absent entirely", async () => {
    server.use(http.get("/auth/me", () => new HttpResponse(null, { status: 503, statusText: "Service Unavailable" })));
    await expect(api.apiMe()).rejects.toEqual({ status: 503, detail: "Service Unavailable" });
  });

  it("prefers `detail` over the whole body object", async () => {
    server.use(http.get("/auth/me", () =>
      HttpResponse.json({ detail: "Nope", other: 1 }, { status: 400 })));
    await expect(api.apiMe()).rejects.toEqual({ status: 400, detail: "Nope" });
  });

  it("passes a null detail through rather than substituting statusText", async () => {
    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: null }, { status: 400 })));
    await expect(api.apiMe()).rejects.toEqual({ status: 400, detail: null });
  });
});

describe("the 401 handler", () => {
  it("throws normally when no handler is registered", async () => {
    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: "no session" }, { status: 401 })));
    await expect(api.apiMe()).rejects.toEqual({ status: 401, detail: "no session" });
  });

  it("fires for any wrapper, not just the one that registered it", async () => {
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    server.use(
      http.get("/items/", () => HttpResponse.json({ detail: "x" }, { status: 401 })),
      http.post("/transactions/", () => HttpResponse.json({ detail: "x" }, { status: 401 })),
    );
    await expect(api.apiListItems()).rejects.toMatchObject({ status: 401 });
    await expect(api.apiCreateTransaction({ item_id: 1, transaction_type: "out", quantity: 1 }))
      .rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).toHaveBeenCalledTimes(2);
  });

  it("does not fire on a 403", async () => {
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: "x" }, { status: 403 })));
    await expect(api.apiMe()).rejects.toMatchObject({ status: 403 });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });

  it("does not leak across module generations", async () => {
    const onUnauthorized = vi.fn();
    api.setUnauthorizedHandler(onUnauthorized);
    vi.resetModules();
    const fresh = await import("../../../backend/static/api.js");
    server.use(http.get("/auth/me", () => HttpResponse.json({ detail: "x" }, { status: 401 })));
    await expect(fresh.apiMe()).rejects.toMatchObject({ status: 401 });
    expect(onUnauthorized).not.toHaveBeenCalled();
  });
});

describe("jsonRequest", () => {
  it("sends the JSON content type and the serialised body", async () => {
    let seen;
    server.use(http.post("/auth/login", async ({ request }) => {
      seen = { type: request.headers.get("Content-Type"), body: await request.json() };
      return HttpResponse.json({ ok: true });
    }));
    await api.apiLogin({ username: "owner", password: "owner1" });
    expect(seen.type).toContain("application/json");
    // `remember` defaults to false and must still be sent -- the backend
    // distinguishes a shift session from a browser-session cookie.
    expect(seen.body).toEqual({ username: "owner", password: "owner1", remember: false });
  });
});
