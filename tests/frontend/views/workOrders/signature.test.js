// The witness signature card (spec 2026-09-30): rendered last on every card,
// draws on a pad, saves once, locks, and clears for a Supervisor+.
//
// jsdom has no canvas, so the 2d context is a local stub; every assertion on
// "drawing" is an assertion on which stub method was called.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import {
  card, confirmOverlay, mountWorkOrders, openCard, requestFor, requests, respond, seedDetail,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../../helpers/factories.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SIG_MODULE = "../../../../backend/static/views/workOrderSignature.js";

afterEach(() => restoreBrowserStubs());

const SIGNED = {
  witness_name: "Pat Doe",
  witness_phone_display: "(555) 555-1234",
  captured_by_name: "Tia Tech",
  captured_at: "2026-09-30T19:15:00Z",
  captured_at_label: "09/30/26 02:15 PM",
  image_url: "/work-orders/wo-1/signature.png?v=1790802900",
};

// Same fixture as actions.test.js: one card, the signed-in user assigned, opened.
async function open({ role, status, assigned = true, detail: overrides = {} }) {
  const detail = workOrderDetail({ status, ...overrides });
  await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status })],
    details: [detail],
  });
  const stateMod = await import("../../../../backend/static/state.js");
  if (assigned) {
    detail.assigned_to_ids = [stateMod.getCurrentUser().id];
    detail.assigned_to_names = ["Me"];
  }
  await openCard(0);
  return detail;
}

function stubPad() {
  const ctx = {
    fillRect: vi.fn(), beginPath: vi.fn(), moveTo: vi.fn(), lineTo: vi.fn(),
    stroke: vi.fn(), drawImage: vi.fn(), setTransform: vi.fn(),
  };
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
  HTMLCanvasElement.prototype.toDataURL = vi.fn(() => "data:image/png;base64,iVBORw0KGgo=");
  return ctx;
}

const stroke = (canvas) => ["pointerdown", "pointermove", "pointerup"]
  .forEach((t) => canvas.dispatchEvent(new MouseEvent(t, { bubbles: true, clientX: 5, clientY: 5 })));

function type(section, selector, value) {
  const input = section.querySelector(selector);
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

const section = () => card().querySelector(".wo-signature-section");
const saveBtn = () => section().querySelector('[data-action="save-signature"]');

// Opening the section is what builds the pad; the `toggle` event is async.
async function openPad() {
  section().open = true;
  await vi.waitFor(() => expect(section().dataset.padMounted).toBe("1"));
  return section();
}

async function fillPad() {
  const el = await openPad();
  stroke(el.querySelector(".wo-signature-pad"));
  type(el, ".wo-signature-name", "Pat Doe");
  type(el, ".wo-signature-phone", "(555) 555-1234");
  return el;
}

const detailGets = (id) =>
  requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}`).length;
const expectRefresh = (id) => vi.waitFor(() => expect(detailGets(id)).toBe(1));

describe("normalizePhone", () => {
  it("mirrors the domain rule: strip, drop a leading 1, require ten digits", async () => {
    const { normalizePhone } = await import(SIG_MODULE);
    expect(normalizePhone("(555) 555-1234")).toBe("5555551234");
    expect(normalizePhone("15555551234")).toBe("5555551234");
    expect(normalizePhone("555-5555")).toBeNull();
    expect(normalizePhone("25555551234")).toBeNull();
  });
});

describe("the Signature section", () => {
  it("is the last section on the card, for a technician too", async () => {
    await open({ role: "technician", status: "assigned" });
    const sections = card().querySelectorAll(".wo-section-card");
    const last = sections[sections.length - 1];
    expect(last.classList.contains("wo-signature-section")).toBe(true);
    expect(last.querySelector("summary").textContent).toBe("Signature");
    expect(last.open).toBe(false);
    expect(last.querySelector(".wo-signature-pad")).not.toBeNull();
  });
});

describe("save-signature", () => {
  it("stays disabled until a stroke, a name and a valid phone all exist", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    const el = await openPad();
    expect(saveBtn().disabled).toBe(true);
    stroke(el.querySelector(".wo-signature-pad"));
    expect(saveBtn().disabled).toBe(true);
    type(el, ".wo-signature-name", "Pat Doe");
    expect(saveBtn().disabled).toBe(true);
    type(el, ".wo-signature-phone", "555-5555");
    expect(saveBtn().disabled).toBe(true);
    type(el, ".wo-signature-phone", "(555) 555-1234");
    expect(saveBtn().disabled).toBe(false);
  });

  it("posts image, name and digits, then refreshes with the section open", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    await fillPad();
    respond("post", "/work-orders/:id/signature", { ...detail, signature: SIGNED }, { status: 201 });
    seedDetail({ ...detail, signature: SIGNED });
    saveBtn().click();
    await expectRefresh(detail.id);
    const post = requestFor("/signature", "POST");
    expect(post.url).toBe(`/work-orders/${detail.id}/signature`);
    expect(post.body).toEqual({
      image: "data:image/png;base64,iVBORw0KGgo=",
      witness_name: "Pat Doe",
      witness_phone: "5555551234",
    });
    expect(section().open).toBe(true);
    expect(section().querySelector(".wo-signature-image")).not.toBeNull();
  });

  it("ignores a double tap: one POST, no error under the saved signature", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    await fillPad();
    respond("post", "/work-orders/:id/signature", { ...detail, signature: SIGNED }, { status: 201 });
    seedDetail({ ...detail, signature: SIGNED });
    saveBtn().click();
    saveBtn().click();
    await expectRefresh(detail.id);
    expect(requests().filter((r) => r.method === "POST" && r.url.endsWith("/signature"))).toHaveLength(1);
    expect(section().querySelector(".wo-signature-message").textContent).toBe("");
  });

  it("re-enables Save when the request fails so the operator can retry", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    await fillPad();
    respond("post", "/work-orders/:id/signature", { detail: "Enter a 10-digit phone number." }, { status: 422 });
    saveBtn().click();
    await vi.waitFor(() => expect(requestFor("/signature", "POST")).not.toBeNull());
    await vi.waitFor(() => expect(saveBtn().disabled).toBe(false));
  });

  it("on 409 shows the signature that won and the server's reason", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    await fillPad();
    respond("post", "/work-orders/:id/signature",
      { detail: "This work order is already signed." }, { status: 409 });
    seedDetail({ ...detail, signature: SIGNED });
    saveBtn().click();
    await expectRefresh(detail.id);
    expect(section().querySelector(".wo-signature-image")).not.toBeNull();
    expect(section().querySelector(".wo-signature-message").textContent)
      .toBe("This work order is already signed.");
  });
});

describe("the locked view", () => {
  it("shows the image, name, phone and captured-by line, and no pad", async () => {
    await open({ role: "technician", status: "assigned", detail: { signature: SIGNED } });
    const el = section();
    expect(el.querySelector("img.wo-signature-image").getAttribute("src")).toBe(SIGNED.image_url);
    expect(el.textContent).toContain("Pat Doe");
    expect(el.textContent).toContain("(555) 555-1234");
    expect(el.textContent).toContain("Captured by Tia Tech on 09/30/26 02:15 PM");
    expect(el.querySelector(".wo-signature-pad")).toBeNull();
    expect(el.querySelector('[data-action="save-signature"]')).toBeNull();
  });
});

describe("clear-signature", () => {
  it("is absent for a technician", async () => {
    await open({ role: "technician", status: "assigned", detail: { signature: SIGNED } });
    expect(section().querySelector('[data-action="clear-signature"]')).toBeNull();
  });

  it("deletes and refreshes for a supervisor, with no confirm dialog", async () => {
    const detail = await open({ role: "supervisor", status: "assigned", detail: { signature: SIGNED } });
    respond("delete", "/work-orders/:id/signature", { ...detail, signature: null });
    seedDetail({ ...detail, signature: null });
    section().querySelector('[data-action="clear-signature"]').click();
    await expectRefresh(detail.id);
    expect(requestFor("/signature", "DELETE").url).toBe(`/work-orders/${detail.id}/signature`);
    expect(confirmOverlay().hidden).toBe(true);
    expect(section().querySelector(".wo-signature-pad")).not.toBeNull();
  });
});

describe("clear-signature-pad", () => {
  it("wipes the pad and disables Save again", async () => {
    const ctx = stubPad();
    await open({ role: "technician", status: "assigned" });
    const el = await fillPad();
    expect(saveBtn().disabled).toBe(false);
    const wipes = ctx.fillRect.mock.calls.length;
    el.querySelector('[data-action="clear-signature-pad"]').click();
    expect(ctx.fillRect.mock.calls.length).toBe(wipes + 1);
    expect(saveBtn().disabled).toBe(true);
  });
});

describe("the pad", () => {
  it("binds its listeners once even when the section is opened twice", async () => {
    const ctx = stubPad();
    await open({ role: "technician", status: "assigned" });
    const el = await openPad();
    el.open = false;
    await vi.waitFor(() => expect(el.open).toBe(false));
    el.open = true;
    await vi.waitFor(() => expect(el.open).toBe(true));
    stroke(el.querySelector(".wo-signature-pad"));
    expect(ctx.beginPath).toHaveBeenCalledTimes(1);
  });
});

describe("signature-fullscreen", () => {
  // jsdom lays nothing out: the pad's CSS box is whatever the test says it is.
  const box = { w: 320, h: 180 };
  beforeEach(() => {
    Object.assign(box, { w: 320, h: 180 });
    Object.defineProperty(HTMLCanvasElement.prototype, "clientWidth", { configurable: true, get: () => box.w });
    Object.defineProperty(HTMLCanvasElement.prototype, "clientHeight", { configurable: true, get: () => box.h });
  });
  afterEach(() => {
    delete HTMLCanvasElement.prototype.clientWidth;
    delete HTMLCanvasElement.prototype.clientHeight;
  });
  const fullBtn = () => section().querySelector('[data-action="signature-fullscreen"]');
  const isFull = () => section().querySelector(".wo-signature-pad-wrap").classList.contains("wo-signature-pad-wrap--full");

  it("covers the screen until Done, resizing the pad to its box both ways", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    const canvas = (await openPad()).querySelector(".wo-signature-pad");
    expect([canvas.width, canvas.height]).toEqual([320, 180]);
    Object.assign(box, { w: 800, h: 400 });
    fullBtn().click();
    expect(isFull()).toBe(true);
    expect(fullBtn().textContent).toBe("Done");
    expect([canvas.width, canvas.height]).toEqual([800, 400]);
    Object.assign(box, { w: 320, h: 180 });
    fullBtn().click();
    expect(isFull()).toBe(false);
    expect(fullBtn().textContent).toBe("Full screen");
    expect([canvas.width, canvas.height]).toEqual([320, 180]);
  });

  it("carries the drawing across the resize, contain-fit, and keeps Save's stroke", async () => {
    const ctx = stubPad();
    await open({ role: "technician", status: "assigned" });
    const el = await openPad();
    stroke(el.querySelector(".wo-signature-pad"));
    Object.assign(box, { w: 800, h: 400 });
    fullBtn().click();
    // 320x180 into 800x400: scale = min(2.5, 2.22) = 2.22 -> 711x400.
    const redraw = ctx.drawImage.mock.calls.at(-1);
    expect(redraw[0]).toBeInstanceOf(HTMLCanvasElement);
    expect(redraw.slice(1, 3)).toEqual([0, 0]);
    expect(redraw[3]).toBeCloseTo(711.1, 0);
    expect(redraw[4]).toBeCloseTo(400, 5);
    expect(el.dataset.hasStroke).toBe("1");
  });

  it("Escape leaves full screen, and only once", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    await openPad();
    fullBtn().click();
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(isFull()).toBe(false);
    document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape" }));
    expect(isFull()).toBe(false);
  });

  it("refits the pad when the phone is turned while full, not after Done", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    const canvas = (await openPad()).querySelector(".wo-signature-pad");
    fullBtn().click();
    Object.assign(box, { w: 400, h: 800 });
    window.dispatchEvent(new Event("resize"));
    expect([canvas.width, canvas.height]).toEqual([400, 800]);
    fullBtn().click();
    Object.assign(box, { w: 999, h: 999 });
    window.dispatchEvent(new Event("resize"));
    expect(canvas.width).toBe(400);
  });
});

describe("styles", () => {
  const css = () => readFileSync(
    join(HERE, "..", "..", "..", "..", "backend", "static", "styles.css"), "utf8"
  );

  it("keeps the page still under a drawing finger", () => {
    const rule = /\.wo-signature-pad\s*\{([^}]*)\}/.exec(css());
    expect(rule?.[1]).toMatch(/touch-action:\s*none/);
  });

  it("the full-screen pad covers the viewport", () => {
    const rule = /\.wo-signature-pad-wrap--full\s*\{([^}]*)\}/.exec(css());
    expect(rule?.[1]).toMatch(/position:\s*fixed/);
    expect(rule?.[1]).toMatch(/inset:\s*0/);
  });
});
