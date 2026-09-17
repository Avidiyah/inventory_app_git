// Characterization for views/connectivityModal.js: the app-wide "not
// connected to the server" prompt. Boots the real composition root
// (helpers/app.js) rather than mounting the module in isolation, since the
// whole point is that it reacts to any request anywhere in the app.

import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { bootApp } from "../helpers/app.js";

const overlay = () => document.getElementById("connectivity-overlay");
const title = () => document.getElementById("connectivity-title");
const reconnectBtn = () => document.getElementById("connectivity-reconnect");
const spinner = () => document.getElementById("connectivity-spinner");
const label = () => document.getElementById("connectivity-reconnect-label");

describe("the connectivity prompt", () => {
  it("stays hidden through a normal boot", async () => {
    await bootApp({ role: "supervisor" });
    expect(overlay().hidden).toBe(true);
  });

  it("appears the moment any request fails to reach the server", async () => {
    await bootApp({ role: "supervisor" });
    server.use(http.get("/items/", () => HttpResponse.error()));
    const api = await import("../../../backend/static/api.js");
    await expect(api.apiListItems()).rejects.toBeTruthy();
    expect(overlay().hidden).toBe(false);
    expect(title().textContent).toBe("Not Connected to Server");
  });

  it("appears immediately on the browser's own offline event, with no request needed", async () => {
    await bootApp({ role: "supervisor" });
    expect(overlay().hidden).toBe(true);
    window.dispatchEvent(new Event("offline"));
    expect(overlay().hidden).toBe(false);
  });

  it("Reconnect spins while checking, and clears the spinner (not the modal) if still offline", async () => {
    await bootApp({ role: "supervisor" });
    window.dispatchEvent(new Event("offline"));
    server.use(http.get("/auth/me", () => HttpResponse.error()));

    reconnectBtn().click();
    expect(spinner().hidden).toBe(false);
    expect(reconnectBtn().disabled).toBe(true);
    expect(label().textContent).toBe("Checking…");

    await vi.waitFor(() => expect(spinner().hidden).toBe(true));
    expect(overlay().hidden).toBe(false);
    expect(reconnectBtn().disabled).toBe(false);
    expect(label().textContent).toBe("Reconnect");
  });

  it("Reconnect clears the modal once the server answers", async () => {
    await bootApp({ role: "supervisor" });
    window.dispatchEvent(new Event("offline"));
    server.use(http.get("/auth/me", () => HttpResponse.json({})));

    reconnectBtn().click();
    await vi.waitFor(() => expect(overlay().hidden).toBe(true));
  });

  it("clears itself with no click once any request succeeds in the background", async () => {
    await bootApp({ role: "supervisor" });
    window.dispatchEvent(new Event("offline"));
    expect(overlay().hidden).toBe(false);

    const api = await import("../../../backend/static/api.js");
    await api.apiMe(); // the default /auth/me handler answers fine
    expect(overlay().hidden).toBe(true);
  });

  it("resends a drafted work-order save once back online", async () => {
    await bootApp({ role: "supervisor" });
    const drafts = await import("../../../backend/static/workOrderDrafts.js");
    drafts.saveDraft("wo1", "notes", {
      number: "4242", action: "save-notes", payload: { notes: "hi" },
    });

    window.dispatchEvent(new Event("offline"));
    server.use(http.patch("/work-orders/wo1", () => HttpResponse.json({ notes: "hi" })));
    window.dispatchEvent(new Event("online"));

    await vi.waitFor(() => expect(overlay().hidden).toBe(true));
    expect(drafts.readDraft("wo1", "notes")).toBeNull();
  });
});
