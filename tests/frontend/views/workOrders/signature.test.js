// The witness signature card (spec 2026-09-30, guided flow 2026-10-05): last
// on every card, captured through a four-step pop-up, saved once, locked, and
// cleared by a Supervisor+ after a confirm.
//
// jsdom has no canvas, so the 2d context is a local stub; every assertion on
// "drawing" is an assertion on which stub method was called.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../../helpers/handlers.js";
import {
  answerConfirm, card, confirmOverlay, message, mountWorkOrders, openCard, requestFor, requests,
  respond, seedDetail,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../../helpers/factories.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const SIG_MODULE = "../../../../backend/static/views/workOrderSignature.js";
const PNG = "data:image/png;base64,iVBORw0KGgo=";

const flow = () => document.querySelector(".wo-sig-flow");
const pressKey = (key) => document.dispatchEvent(new KeyboardEvent("keydown", { key }));

afterEach(() => {
  // A flow left open keeps its document listeners: step it back out.
  for (let i = 0; i < 5 && flow(); i++) pressKey("Escape");
  restoreBrowserStubs();
});

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
    quadraticCurveTo: vi.fn(), arc: vi.fn(), fill: vi.fn(), stroke: vi.fn(),
  };
  HTMLCanvasElement.prototype.getContext = vi.fn(() => ctx);
  HTMLCanvasElement.prototype.toDataURL = vi.fn(() => PNG);
  return ctx;
}

const section = () => card().querySelector(".wo-signature-section");
const panel = (step) => flow().querySelector(`[data-step="${step}"]`);
const button = (step, sig) => panel(step).querySelector(`[data-sig="${sig}"]`);
const pad = () => flow().querySelector(".wo-signature-pad");

const pointer = (type, x, y, pointerId = 1) => pad().dispatchEvent(
  new PointerEvent(type, { bubbles: true, clientX: x, clientY: y, pointerId }),
);
function stroke(x = 5, y = 5) {
  pointer("pointerdown", x, y);
  pointer("pointermove", x + 1, y + 1);
  pointer("pointerup", x + 1, y + 1);
}

function type(selector, value) {
  const input = flow().querySelector(selector);
  input.value = value;
  input.dispatchEvent(new Event("input", { bubbles: true }));
}

function startFlow() {
  section().open = true;
  section().querySelector('[data-action="capture-signature"]').click();
}

// Guidance -> details -> the signing step, pad still blank.
function reachSign() {
  startFlow();
  button("intro", "next").click();
  type(".wo-signature-name", "Pat Doe");
  type(".wo-signature-phone", "5555551234");
  button("details", "next").click();
}

function reachConfirm() {
  reachSign();
  stroke();
  button("sign", "next").click();
}

const detailGets = (id) =>
  requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}`).length;
const expectRefresh = (id) => vi.waitFor(() => expect(detailGets(id)).toBe(1));

describe("the phone rule", () => {
  it("normalizePhone mirrors the domain: strip, drop a leading 1, require ten digits", async () => {
    const { normalizePhone } = await import(SIG_MODULE);
    expect(normalizePhone("(555) 555-1234")).toBe("5555551234");
    expect(normalizePhone("15555551234")).toBe("5555551234");
    expect(normalizePhone("555-5555")).toBeNull();
    expect(normalizePhone("25555551234")).toBeNull();
  });

  it("formatPhone shows it as typed and never adds punctuation Backspace cannot remove", async () => {
    const { formatPhone } = await import(SIG_MODULE);
    expect(formatPhone("555")).toBe("555");
    expect(formatPhone("5551")).toBe("(555) 1");
    expect(formatPhone("(555) ")).toBe("555");
    expect(formatPhone("5551234567")).toBe("(555) 123-4567");
    expect(formatPhone("15551234567")).toBe("(555) 123-4567");
    expect(formatPhone("555123456789")).toBe("555123456789");
  });
});

describe("inkWidth", () => {
  it("thins the line as the hand speeds up, within bounds", async () => {
    const { inkWidth } = await import(SIG_MODULE);
    expect(inkWidth(1, 3)).toBeLessThan(inkWidth(1, 0));
    let slow = 1;
    let fast = 1;
    for (let i = 0; i < 50; i++) {
      slow = inkWidth(slow, 0);
      fast = inkWidth(fast, 100);
    }
    expect(slow).toBeCloseTo(1.3, 5);
    expect(fast).toBeCloseTo(0.6, 5);
  });
});

describe("the Signature section", () => {
  it("is the last section on the card, for a technician too, and holds only the launch button", async () => {
    await open({ role: "technician", status: "assigned" });
    const sections = card().querySelectorAll(".wo-section-card");
    const last = sections[sections.length - 1];
    expect(last.classList.contains("wo-signature-section")).toBe(true);
    expect(last.querySelector("summary").textContent).toBe("Signature");
    expect(last.open).toBe(false);
    expect(last.querySelector('[data-action="capture-signature"]')).not.toBeNull();
    expect(last.querySelector(".wo-signature-pad")).toBeNull();
  });
});

describe("capture-signature: the guided flow", () => {
  it("opens on the guidance step, outside the list section, and Cancel sends nothing", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    startFlow();
    expect(flow().querySelector(".wo-sig-step").textContent).toBe(`Step 1 of 4 · WO ${detail.number}`);
    expect(flow().querySelector(".modal-title").textContent).toBe("Before you start");
    expect(panel("intro").textContent).toContain("Never sign for someone else.");
    expect(panel("details").hidden).toBe(true);
    // The list's <section> has a backdrop-filter, which traps a fixed overlay.
    expect(flow().closest("section")).toBeNull();
    expect(flow().closest("#work-orders-page")).not.toBeNull();
    button("intro", "cancel").click();
    expect(flow()).toBeNull();
    expect(requestFor("/signature")).toBeNull();
  });

  it("opens one flow however many times the button is pressed", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    startFlow();
    startFlow();
    expect(document.querySelectorAll(".wo-sig-flow")).toHaveLength(1);
  });

  it("holds Continue, and says what is missing, until a name and a valid phone exist", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    startFlow();
    button("intro", "next").click();
    const needed = () => flow().querySelector(".wo-sig-needed").textContent;
    expect(button("details", "next").disabled).toBe(true);
    expect(needed()).toBe("Still needed: printed name and 10-digit phone number.");
    type(".wo-signature-name", "Pat Doe");
    expect(needed()).toBe("Still needed: 10-digit phone number.");
    type(".wo-signature-phone", "5555555");
    expect(flow().querySelector(".wo-signature-phone").value).toBe("(555) 555-5");
    expect(button("details", "next").disabled).toBe(true);
    type(".wo-signature-phone", "5555551234");
    expect(flow().querySelector(".wo-signature-phone").value).toBe("(555) 555-1234");
    expect(needed()).toBe("");
    expect(button("details", "next").disabled).toBe(false);
  });

  it("holds Clear, Undo stroke and Submit until the witness draws; a tap counts", async () => {
    const ctx = stubPad();
    await open({ role: "technician", status: "assigned" });
    reachSign();
    for (const sig of ["clear", "undo", "next"]) expect(button("sign", sig).disabled).toBe(true);
    expect(button("sign", "next").textContent).toBe("Submit");
    pointer("pointerdown", 5, 5);
    pointer("pointerup", 5, 5);
    expect(ctx.arc).toHaveBeenCalledTimes(1);
    for (const sig of ["clear", "undo", "next"]) expect(button("sign", sig).disabled).toBe(false);
  });

  it("draws a move as a curve, not a straight segment", async () => {
    const ctx = stubPad();
    await open({ role: "technician", status: "assigned" });
    reachSign();
    stroke();
    expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(1);
  });

  it("Undo stroke takes back one stroke at a time; Clear takes them all", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    reachSign();
    stroke(5, 5);
    stroke(20, 20);
    button("sign", "undo").click();
    expect(button("sign", "next").disabled).toBe(false);
    button("sign", "undo").click();
    expect(button("sign", "next").disabled).toBe(true);
    stroke(5, 5);
    stroke(20, 20);
    button("sign", "clear").click();
    expect(button("sign", "next").disabled).toBe(true);
  });

  it("ignores a second contact while one is drawing", async () => {
    const ctx = stubPad();
    await open({ role: "technician", status: "assigned" });
    reachSign();
    pointer("pointerdown", 5, 5, 1);
    pointer("pointerdown", 300, 100, 2); // a resting palm
    pointer("pointermove", 301, 101, 2);
    expect(ctx.quadraticCurveTo).not.toHaveBeenCalled();
    pointer("pointermove", 6, 6, 1);
    pointer("pointerup", 6, 6, 1);
    expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(1);
    button("sign", "undo").click(); // one stroke was all there was
    expect(button("sign", "next").disabled).toBe(true);
  });

  it("Submit shows the confirmation with the signature, the witness and the work order", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    reachConfirm();
    expect(flow().querySelector(".modal-title").textContent).toBe("Confirm sign-off");
    expect(flow().querySelector(".wo-sig-preview").getAttribute("src")).toBe(PNG);
    expect(flow().querySelector(".wo-sig-who").textContent).toBe("Pat Doe · (555) 555-1234");
    expect(panel("confirm").textContent).toContain(`WO ${detail.number}`);
    expect(requestFor("/signature")).toBeNull();
  });

  it("Escape steps back one step at a time and closes from the first", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    reachSign();
    pressKey("Escape");
    expect(panel("details").hidden).toBe(false);
    pressKey("Escape");
    expect(panel("intro").hidden).toBe(false);
    pressKey("Escape");
    expect(flow()).toBeNull();
  });
});

describe("capture-signature: the sideways signing step", () => {
  // jsdom lays nothing out: every box is whatever the test says the screen is.
  const screen = { w: 390, h: 844 };
  const stubLayout = () => {
    Object.assign(screen, { w: 390, h: 844 });
    Object.defineProperty(HTMLElement.prototype, "clientWidth", { configurable: true, get: () => screen.w });
    Object.defineProperty(HTMLElement.prototype, "clientHeight", { configurable: true, get: () => screen.h });
  };
  afterEach(() => {
    delete HTMLElement.prototype.clientWidth;
    delete HTMLElement.prototype.clientHeight;
    delete HTMLCanvasElement.prototype.getBoundingClientRect;
  });
  const turned = () => flow().classList.contains("wo-sig-flow--turned");
  const box = () => flow().querySelector(".wo-sig-box");

  it("turns a portrait phone's pad a quarter, and stands back up on Submit", async () => {
    stubPad();
    stubLayout();
    await open({ role: "technician", status: "assigned" });
    startFlow();
    expect(turned()).toBe(false);
    reachSignFromIntro();
    expect(turned()).toBe(true);
    expect([box().style.width, box().style.height]).toEqual(["844px", "390px"]);
    stroke();
    button("sign", "next").click();
    expect(turned()).toBe(false);
    expect([box().style.width, box().style.height]).toEqual(["", ""]);
  });

  it("maps a turned pad's touches onto the paper: the screen's bottom-left is its far corner", async () => {
    const ctx = stubPad();
    stubLayout();
    HTMLCanvasElement.prototype.getBoundingClientRect = () => (
      { left: 0, top: 0, right: 156, bottom: 390, width: 156, height: 390 });
    await open({ role: "technician", status: "assigned" });
    startFlow();
    reachSignFromIntro();
    pointer("pointerdown", 0, 390);
    pointer("pointerup", 0, 390);
    expect(pad().width).toBeGreaterThan(0);
    expect(ctx.arc.mock.calls.at(-1).slice(0, 2)).toEqual([pad().width, pad().height]);
  });

  it("refits and redraws the pad when the phone is turned, keeping the strokes", async () => {
    const ctx = stubPad();
    stubLayout();
    await open({ role: "technician", status: "assigned" });
    startFlow();
    reachSignFromIntro();
    expect([pad().width, pad().height]).toEqual([390, 156]);
    stroke();
    const drawn = ctx.quadraticCurveTo.mock.calls.length;
    Object.assign(screen, { w: 844, h: 390 });
    window.dispatchEvent(new Event("resize"));
    expect(turned()).toBe(false);
    expect([pad().width, pad().height]).toEqual([844, 338]);
    expect(ctx.quadraticCurveTo.mock.calls.length).toBe(drawn + 1);
    expect(button("sign", "next").disabled).toBe(false);
  });

  function reachSignFromIntro() {
    button("intro", "next").click();
    type(".wo-signature-name", "Pat Doe");
    type(".wo-signature-phone", "5555551234");
    button("details", "next").click();
  }
});

describe("capture-signature: Save and lock", () => {
  it("posts image, name and digits, closes the flow, and refreshes with the section open", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    reachConfirm();
    respond("post", "/work-orders/:id/signature", { ...detail, signature: SIGNED }, { status: 201 });
    seedDetail({ ...detail, signature: SIGNED });
    button("confirm", "save").click();
    await expectRefresh(detail.id);
    const post = requestFor("/signature", "POST");
    expect(post.url).toBe(`/work-orders/${detail.id}/signature`);
    expect(post.body).toEqual({ image: PNG, witness_name: "Pat Doe", witness_phone: "5555551234" });
    expect(flow()).toBeNull();
    expect(section().open).toBe(true);
    expect(section().querySelector(".wo-signature-image")).not.toBeNull();
    expect(localStorage.getItem(`wo-draft:${detail.id}:signature`)).toBeNull();
  });

  it("ignores a double tap: one POST, no error under the saved signature", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    reachConfirm();
    respond("post", "/work-orders/:id/signature", { ...detail, signature: SIGNED }, { status: 201 });
    seedDetail({ ...detail, signature: SIGNED });
    const save = button("confirm", "save");
    save.click();
    save.click();
    await expectRefresh(detail.id);
    expect(requests().filter((r) => r.method === "POST" && r.url.endsWith("/signature"))).toHaveLength(1);
    expect(section().querySelector(".wo-signature-message").textContent).toBe("");
  });

  it("keeps the flow open with the server's reason when the save is refused", async () => {
    stubPad();
    await open({ role: "technician", status: "assigned" });
    reachConfirm();
    respond("post", "/work-orders/:id/signature", { detail: "Enter a 10-digit phone number." }, { status: 422 });
    button("confirm", "save").click();
    await vi.waitFor(() =>
      expect(flow().querySelector(".wo-sig-error").textContent).toBe("Enter a 10-digit phone number."));
    expect(button("confirm", "save").disabled).toBe(false);
  });

  it("on 409 closes, shows the signature that won and the server's reason", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    reachConfirm();
    respond("post", "/work-orders/:id/signature",
      { detail: "This work order is already signed." }, { status: 409 });
    seedDetail({ ...detail, signature: SIGNED });
    button("confirm", "save").click();
    await expectRefresh(detail.id);
    expect(flow()).toBeNull();
    expect(section().querySelector(".wo-signature-image")).not.toBeNull();
    expect(section().querySelector(".wo-signature-message").textContent)
      .toBe("This work order is already signed.");
  });

  it("offline closes the flow, says so on the card, and keeps the draft to replay", async () => {
    stubPad();
    const detail = await open({ role: "technician", status: "assigned" });
    reachConfirm();
    server.use(http.post("/work-orders/:id/signature", () => HttpResponse.error()));
    button("confirm", "save").click();
    await vi.waitFor(() => expect(flow()).toBeNull());
    expect(message().textContent).toBe("Could not reach the app. Check your signal and try again.");
    expect(JSON.parse(localStorage.getItem(`wo-draft:${detail.id}:signature`))).toMatchObject({
      action: "save-signature",
      payload: { image: PNG, witnessName: "Pat Doe", witnessPhone: "5555551234" },
    });
  });
});

describe("the locked view", () => {
  it("shows the image, name, phone and captured-by line, and nothing to capture", async () => {
    await open({ role: "technician", status: "assigned", detail: { signature: SIGNED } });
    const el = section();
    expect(el.querySelector("img.wo-signature-image").getAttribute("src")).toBe(SIGNED.image_url);
    expect(el.textContent).toContain("Pat Doe");
    expect(el.textContent).toContain("(555) 555-1234");
    expect(el.textContent).toContain("Captured by Tia Tech on 09/30/26 02:15 PM");
    expect(el.querySelector('[data-action="capture-signature"]')).toBeNull();
  });
});

describe("clear-signature", () => {
  const clearBtn = () => section().querySelector('[data-action="clear-signature"]');

  it("is absent for a technician", async () => {
    await open({ role: "technician", status: "assigned", detail: { signature: SIGNED } });
    expect(clearBtn()).toBeNull();
  });

  it("asks a supervisor first, naming the witness, and Keep sends nothing", async () => {
    await open({ role: "supervisor", status: "assigned", detail: { signature: SIGNED } });
    clearBtn().click();
    await vi.waitFor(() => expect(confirmOverlay().hidden).toBe(false));
    expect(document.getElementById("scan-confirm-title").textContent).toBe(
      "Clear the saved witness sign-off from Pat Doe? The clear is recorded under your name in the notes.");
    await answerConfirm(false);
    expect(requestFor("/signature", "DELETE")).toBeNull();
    expect(section().querySelector(".wo-signature-image")).not.toBeNull();
  });

  it("deletes and refreshes once confirmed", async () => {
    const detail = await open({ role: "supervisor", status: "assigned", detail: { signature: SIGNED } });
    respond("delete", "/work-orders/:id/signature", { ...detail, signature: null });
    seedDetail({ ...detail, signature: null });
    clearBtn().click();
    await answerConfirm(true);
    await expectRefresh(detail.id);
    expect(requestFor("/signature", "DELETE").url).toBe(`/work-orders/${detail.id}/signature`);
    expect(section().querySelector('[data-action="capture-signature"]')).not.toBeNull();
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

  it("turns the sideways signing box a quarter about its corner", () => {
    const rule = /\.wo-sig-flow--turned \.wo-sig-box\s*\{([^}]*)\}/.exec(css());
    expect(rule?.[1]).toMatch(/transform:\s*rotate\(90deg\)/);
    expect(rule?.[1]).toMatch(/transform-origin:\s*top left/);
  });
});
