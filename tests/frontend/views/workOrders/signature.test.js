// The witness signature module (spec 2026-09-30, guided flow 2026-10-05): the
// section builder, the four-step pop-up and its drawing pad.
//
// The Signature section left the card on 2026-11-06 and the card's two
// actions went with it; views/workOrderSignature.js stays in the app,
// unmounted. So this drives the module directly: `signatureSectionHtml` on a
// detail, and `openSignatureFlow({ number, onSave })` with a spy for the save
// the card used to own.
//
// jsdom has no canvas, so the 2d context is a local stub; every assertion on
// "drawing" is an assertion on which stub method was called.

import { readFileSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { afterEach, describe, expect, it, vi } from "vitest";
import { restoreBrowserStubs } from "../../helpers/browserStubs.js";
import { workOrderDetail } from "../../helpers/factories.js";
import { setTestUser } from "../../helpers/session.js";
import { importView, mountShell } from "../../helpers/shell.js";

const HERE = dirname(fileURLToPath(import.meta.url));
const PNG = "data:image/png;base64,iVBORw0KGgo=";
const NUMBER = "7001";

const flow = () => document.querySelector(".wo-sig-flow");
const pressKey = (key) => {
  const event = new KeyboardEvent("keydown", { key, cancelable: true });
  document.dispatchEvent(event);
  return event;
};

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

// The shell, a signed-in user and the module, in the order a view needs them.
async function load(role = "technician") {
  const me = await setTestUser({ role });
  mountShell();
  const mod = await importView("views/workOrderSignature.js");
  return { mod, me };
}

// The section as the card would have painted it.
function section(mod, detail) {
  const host = document.createElement("div");
  host.innerHTML = mod.signatureSectionHtml(detail);
  return host.querySelector(".wo-signature-section");
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

// Open the flow with a stubbed pad; `onSave` stands in for the card's save.
async function startFlow({ onSave = vi.fn(async () => {}), role = "technician" } = {}) {
  const ctx = stubPad();
  const { mod } = await load(role);
  mod.openSignatureFlow({ number: NUMBER, onSave });
  return { mod, ctx, onSave };
}

function fillDetails() {
  button("intro", "next").click();
  type(".wo-signature-name", "Pat Doe");
  type(".wo-signature-phone", "5555551234");
  button("details", "next").click();
}

// Guidance -> details -> the signing step, pad still blank.
async function reachSign(opts) {
  const started = await startFlow(opts);
  fillDetails();
  return started;
}

async function reachConfirm(opts) {
  const started = await reachSign(opts);
  stroke();
  button("sign", "next").click();
  return started;
}

describe("the phone rule", () => {
  it("normalizePhone mirrors the domain: strip, drop a leading 1, require ten digits", async () => {
    const { mod: { normalizePhone } } = await load();
    expect(normalizePhone("(555) 555-1234")).toBe("5555551234");
    expect(normalizePhone("15555551234")).toBe("5555551234");
    expect(normalizePhone("555-5555")).toBeNull();
    expect(normalizePhone("25555551234")).toBeNull();
    expect(normalizePhone(null)).toBeNull();
  });

  it("formatPhone shows it as typed and never adds punctuation Backspace cannot remove", async () => {
    const { mod: { formatPhone } } = await load();
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
    const { mod: { inkWidth } } = await load();
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
  it("unsigned: a closed section holding only the launch button, for a technician on the crew", async () => {
    const { mod, me } = await load("technician");
    const el = section(mod, workOrderDetail({ assigned_to_ids: [me.id], assigned_to_names: ["Me"] }));
    expect(el.querySelector("summary").textContent).toBe("Signature");
    expect(el.open).toBe(false);
    expect(el.querySelector('[data-action="capture-signature"]').textContent).toBe("Capture witness signature");
    expect(el.querySelector(".wo-signature-pad")).toBeNull();
    expect(el.querySelector(".wo-signature-message").getAttribute("aria-live")).toBe("polite");
  });

  it("unsigned: a technician off the crew gets the hint and no button", async () => {
    const { mod } = await load("technician");
    const el = section(mod, workOrderDetail({ assigned_to_ids: [], assigned_to_names: [] }));
    expect(el.textContent).toContain("Captured step by step with the witness present.");
    expect(el.querySelector('[data-action="capture-signature"]')).toBeNull();
  });

  it("signed: the image, name, phone and captured-by line, and nothing to capture", async () => {
    const { mod } = await load("technician");
    const el = section(mod, workOrderDetail({ signature: SIGNED }));
    expect(el.querySelector("img.wo-signature-image").getAttribute("src")).toBe(SIGNED.image_url);
    expect(el.textContent).toContain("Pat Doe");
    expect(el.textContent).toContain("(555) 555-1234");
    expect(el.textContent).toContain("Captured by Tia Tech on 09/30/26 02:15 PM");
    expect(el.querySelector('[data-action="capture-signature"]')).toBeNull();
    // Clearing is a Team Lead's: a technician is offered no button.
    expect(el.querySelector('[data-action="clear-signature"]')).toBeNull();
  });

  it("signed: a supervisor is offered Clear, carrying the witness to name in the confirm", async () => {
    const { mod } = await load("supervisor");
    const clear = section(mod, workOrderDetail({ signature: SIGNED })).querySelector('[data-action="clear-signature"]');
    expect(clear.textContent).toBe("Clear signature");
    expect(clear.dataset.witness).toBe("Pat Doe");
    expect(clear.className).toBe("btn-danger");
  });
});

describe("the guided flow", () => {
  it("opens on the guidance step, on the page rather than in the list, and Cancel saves nothing", async () => {
    const { onSave } = await startFlow();
    expect(flow().querySelector(".wo-sig-step").textContent).toBe(`Step 1 of 4 · WO ${NUMBER}`);
    expect(flow().querySelector(".modal-title").textContent).toBe("Before you start");
    expect(panel("intro").textContent).toContain("Never sign for someone else.");
    expect(panel("details").hidden).toBe(true);
    // The list's <section> has a backdrop-filter, which traps a fixed overlay.
    expect(flow().closest("section")).toBeNull();
    expect(flow().closest("#work-orders-page")).not.toBeNull();
    button("intro", "cancel").click();
    expect(flow()).toBeNull();
    expect(onSave).not.toHaveBeenCalled();
  });

  it("opens one flow however many times it is asked for", async () => {
    const { mod } = await startFlow();
    mod.openSignatureFlow({ number: NUMBER, onSave: vi.fn() });
    expect(document.querySelectorAll(".wo-sig-flow")).toHaveLength(1);
  });

  it("holds Continue, and says what is missing, until a name and a valid phone exist", async () => {
    await startFlow();
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

  it("Back returns to the step before with what was typed still there", async () => {
    await reachSign();
    button("sign", "back").click();
    expect(panel("details").hidden).toBe(false);
    expect(flow().querySelector(".wo-signature-name").value).toBe("Pat Doe");
    expect(flow().querySelector(".wo-sig-step").textContent).toBe(`Step 2 of 4 · WO ${NUMBER}`);
  });

  it("holds Clear, Undo stroke and Submit until the witness draws; a tap counts", async () => {
    const { ctx } = await reachSign();
    for (const sig of ["clear", "undo", "next"]) expect(button("sign", sig).disabled).toBe(true);
    expect(button("sign", "next").textContent).toBe("Submit");
    pointer("pointerdown", 5, 5);
    pointer("pointerup", 5, 5);
    expect(ctx.arc).toHaveBeenCalledTimes(1);
    for (const sig of ["clear", "undo", "next"]) expect(button("sign", sig).disabled).toBe(false);
  });

  it("draws a move as a curve, not a straight segment", async () => {
    const { ctx } = await reachSign();
    stroke();
    expect(ctx.quadraticCurveTo).toHaveBeenCalledTimes(1);
  });

  it("Undo stroke takes back one stroke at a time; Clear takes them all", async () => {
    await reachSign();
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
    const { ctx } = await reachSign();
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
    const { onSave } = await reachConfirm();
    expect(flow().querySelector(".modal-title").textContent).toBe("Confirm sign-off");
    expect(flow().querySelector(".wo-sig-preview").getAttribute("src")).toBe(PNG);
    expect(flow().querySelector(".wo-sig-who").textContent).toBe("Pat Doe · (555) 555-1234");
    expect(panel("confirm").textContent).toContain(`WO ${NUMBER}`);
    expect(onSave).not.toHaveBeenCalled();
  });

  it("Escape steps back one step at a time and closes from the first", async () => {
    await reachSign();
    pressKey("Escape");
    expect(panel("details").hidden).toBe(false);
    pressKey("Escape");
    expect(panel("intro").hidden).toBe(false);
    pressKey("Escape");
    expect(flow()).toBeNull();
  });

  it("Tab stays inside the step: past the last stop it wraps to the first, and back again", async () => {
    await startFlow();
    const stops = [...panel("intro").querySelectorAll("input, button:not([disabled])")];
    stops.at(-1).focus();
    expect(pressKey("Tab").defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(stops[0]);
    const back = new KeyboardEvent("keydown", { key: "Tab", shiftKey: true, cancelable: true });
    document.dispatchEvent(back);
    expect(back.defaultPrevented).toBe(true);
    expect(document.activeElement).toBe(stops.at(-1));
    // Any other key is left alone.
    expect(pressKey("a").defaultPrevented).toBe(false);
  });

  it("closes when the browser goes Back, and stops listening", async () => {
    await startFlow();
    window.dispatchEvent(new Event("popstate"));
    expect(flow()).toBeNull();
    // The keydown listener went with it: Escape now reaches nothing.
    expect(() => pressKey("Escape")).not.toThrow();
  });
});

describe("the sideways signing step", () => {
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
    stubLayout();
    await startFlow();
    expect(turned()).toBe(false);
    fillDetails();
    expect(turned()).toBe(true);
    expect([box().style.width, box().style.height]).toEqual(["844px", "390px"]);
    stroke();
    button("sign", "next").click();
    expect(turned()).toBe(false);
    expect([box().style.width, box().style.height]).toEqual(["", ""]);
  });

  it("maps a turned pad's touches onto the paper: the screen's bottom-left is its far corner", async () => {
    stubLayout();
    HTMLCanvasElement.prototype.getBoundingClientRect = () => (
      { left: 0, top: 0, right: 156, bottom: 390, width: 156, height: 390 });
    const { ctx } = await startFlow();
    fillDetails();
    pointer("pointerdown", 0, 390);
    pointer("pointerup", 0, 390);
    expect(pad().width).toBeGreaterThan(0);
    expect(ctx.arc.mock.calls.at(-1).slice(0, 2)).toEqual([pad().width, pad().height]);
  });

  it("refits and redraws the pad when the phone is turned, keeping the strokes", async () => {
    stubLayout();
    const { ctx } = await startFlow();
    fillDetails();
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
});

describe("Save", () => {
  it("hands onSave the image, the name and the digits, then closes", async () => {
    const { onSave } = await reachConfirm();
    button("confirm", "save").click();
    await vi.waitFor(() => expect(flow()).toBeNull());
    expect(onSave).toHaveBeenCalledTimes(1);
    expect(onSave).toHaveBeenCalledWith({ image: PNG, witnessName: "Pat Doe", witnessPhone: "5555551234" });
  });

  it("ignores a double tap: one save", async () => {
    let release;
    const onSave = vi.fn(() => new Promise((resolve) => { release = resolve; }));
    await reachConfirm({ onSave });
    const save = button("confirm", "save");
    save.click();
    expect(save.disabled).toBe(true);
    save.click();
    release();
    await vi.waitFor(() => expect(flow()).toBeNull());
    expect(onSave).toHaveBeenCalledTimes(1);
  });

  it("stays open with the reason when the save is refused, and can be tried again", async () => {
    const onSave = vi.fn(async () => { throw { status: 422, detail: "Enter a 10-digit phone number." }; });
    await reachConfirm({ onSave });
    button("confirm", "save").click();
    await vi.waitFor(() =>
      expect(flow().querySelector(".wo-sig-error").textContent).toBe("Enter a 10-digit phone number."));
    expect(button("confirm", "save").disabled).toBe(false);
    onSave.mockImplementationOnce(async () => {});
    button("confirm", "save").click();
    await vi.waitFor(() => expect(flow()).toBeNull());
  });

  it("a failure with no reason falls back to the fixed copy", async () => {
    await reachConfirm({ onSave: vi.fn(async () => { throw new Error(""); }) });
    button("confirm", "save").click();
    await vi.waitFor(() =>
      expect(flow().querySelector(".wo-sig-error").textContent).not.toBe(""));
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
