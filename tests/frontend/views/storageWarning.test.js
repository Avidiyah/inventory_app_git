// The Admin/Owner photo-storage warning after sign-in (spec 2026-11-24).

import { describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { bootApp } from "../helpers/app.js";
import { stubScrollIntoView, restoreBrowserStubs } from "../helpers/browserStubs.js";

const warning = () => document.querySelector(".storage-warning");
const clockIn = () => document.querySelector(".clock-in-prompt");
const settle = () => new Promise((r) => setTimeout(r, 20));
const storage = (ratio, o = {}) => http.get("/work-order-photos/storage", () => HttpResponse.json({
  used: Math.round(ratio * 1073741824), disk: 1073741824, ratio,
  warn: ratio >= 0.5, full: ratio >= 0.8, waiting_photos: 4, waiting_bytes: 1, exported_photos: 0, ...o,
}));

describe("photo-storage warning", () => {
  it("shows for the Owner at 50% (no clock-in prompt first)", async () => {
    await bootApp({ role: "owner", handlers: [storage(0.5)] });
    await vi.waitFor(() => expect(warning()).not.toBeNull());
    expect(warning().textContent).toContain("Photo storage is half full");
    expect(warning().textContent).toContain("512 MB of 1 GB (50%)");
  });

  it("waits for the Admin's clock-in prompt to close, then shows", async () => {
    await bootApp({ role: "admin", handlers: [storage(0.6)] });
    await vi.waitFor(() => expect(clockIn()).not.toBeNull());
    await settle();
    expect(warning()).toBeNull();
    clockIn().querySelector('[data-action="skip"]').click();
    await vi.waitFor(() => expect(warning()).not.toBeNull());
  });

  it("says uploads are stopped at 80%", async () => {
    await bootApp({ role: "owner", handlers: [storage(0.85)] });
    await vi.waitFor(() => expect(warning()).not.toBeNull());
    expect(warning().textContent).toContain("uploads are stopped");
  });

  it("stays away below 50%", async () => {
    await bootApp({ role: "owner", handlers: [storage(0.49)] });
    await settle();
    expect(warning()).toBeNull();
  });

  it("never asks for a Technician", async () => {
    let asked = false;
    await bootApp({
      role: "technician",
      handlers: [http.get("/work-order-photos/storage", () => { asked = true; return HttpResponse.json({}); })],
    });
    await vi.waitFor(() => expect(clockIn()).not.toBeNull());
    clockIn().querySelector('[data-action="skip"]').click();
    await settle();
    expect(asked).toBe(false);
    expect(warning()).toBeNull();
  });

  it("is quiet when the lookup fails", async () => {
    await bootApp({
      role: "owner",
      handlers: [http.get("/work-order-photos/storage", () => HttpResponse.json({ detail: "x" }, { status: 500 }))],
    });
    await settle();
    expect(warning()).toBeNull();
  });

  it("Go to Image export lands on the Integrations section; Later just closes", async () => {
    const scroll = stubScrollIntoView();
    await bootApp({ role: "owner", handlers: [storage(0.5)] });
    await vi.waitFor(() => expect(warning()).not.toBeNull());
    warning().querySelector('[data-action="go-image-export"]').click();
    await vi.waitFor(() => expect(document.getElementById("integrations-image-export").hidden).toBe(false));
    expect(document.getElementById("integrations-page").classList.contains("active")).toBe(true);
    expect(warning()).toBeNull();
    expect(scroll.mock.contexts.some((el) => el.id === "integrations-image-export")).toBe(true);
    restoreBrowserStubs();
  });
});
