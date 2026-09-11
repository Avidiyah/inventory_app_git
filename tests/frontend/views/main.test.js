// Characterization of `backend/static/main.js` -- the composition root.
//
// The module is twenty lines of imports and five bootstrap calls, and every
// one of them is a wiring nothing else asserts. Each is tested at its EFFECT
// rather than by spying on the import: a spy would prove `main.js` called a
// function, which is what reading the file already proves. What matters is
// that the callback it injected is the one the other module actually reaches.

import { beforeEach, describe, expect, it, vi } from "vitest";
import userEvent from "@testing-library/user-event";
import { http, HttpResponse } from "msw";
import { bootApp, bootLoggedOut, appRoot, loginScreen } from "../helpers/app.js";
import { workOrderCard } from "../helpers/factories.js";

const gateCards = () => document.getElementById("wo-gate-cards");
const firstGateCard = () => gateCards().querySelector(".wo-card");

// A card the gate will accept straight into a batch: `in_progress` skips the
// assign/start confirmations in `selectWorkOrderForBatch`.
const liveCard = (overrides = {}) => workOrderCard({ status: "in_progress", ...overrides });

// Seed the work-order gate's list and open the Transaction page on it.
async function openGate({ cards = [liveCard()], permission = "prompt" } = {}) {
  const booted = await bootApp({
    role: "owner",
    media: { permission },
    handlers: [http.get("/work-orders/", () => HttpResponse.json(cards))],
  });
  booted.nav.showPage("transaction");
  await vi.waitFor(() => expect(firstGateCard()).not.toBeNull());
  return booted;
}

describe("initAuth runs at import", () => {
  it("a valid session reveals the app on the role's landing page", async () => {
    const { nav, requestsFor } = await bootApp({ role: "supervisor" });
    expect(appRoot().hidden).toBe(false);
    expect(loginScreen().hidden).toBe(true);
    expect(nav.getActivePage()).toBe(nav.landingPageForRole("supervisor"));
    expect(requestsFor("/auth/me")).toHaveLength(1);
  });

  it("fills the identity button with the signed-in user's name and role", async () => {
    await bootApp({
      role: "admin",
      user: { full_name: "Dana Okafor", first_name: "Dana", last_name: "Okafor" },
    });
    const indicator = document.getElementById("auth-user-indicator");
    expect(indicator.querySelector(".user-hub-name").textContent).toBe("Dana Okafor");
    expect(indicator.querySelector(".user-hub-role").textContent).toBe("Admin");
    expect(indicator.getAttribute("aria-label")).toContain("Dana Okafor");
  });

  it("a 401 shows the login screen and fires no page loader", async () => {
    const { requests, requestsFor } = await bootLoggedOut();
    expect(appRoot().hidden).toBe(true);
    expect(loginScreen().hidden).toBe(false);
    // The only call made is the boot check itself.
    expect(requestsFor("/auth/me")).toHaveLength(1);
    expect(requests()).toHaveLength(1);
    expect(requestsFor("/hub")).toHaveLength(0);
  });

  // The asymmetry `views/auth.js` documents: a boot-time 401 is "not signed in
  // yet", not an expiry, so the timeout copy must stay quiet. Asserted from
  // this side too, because it is main.js's unawaited `initAuth()` that puts
  // the app in the state the handler reads.
  it("a boot-time 401 shows no session-timeout copy", async () => {
    await bootLoggedOut();
    expect(document.getElementById("login-message").textContent).toBe("");
  });
});

describe("setScanAutostarter", () => {
  // The camera comes up as the batch begins, but only where permission is
  // already granted. The "never prompts" half is the load-bearing one: an
  // unprompted `getUserMedia` on iOS gives no second chance after a denial.
  it("starts the camera when a batch begins and permission is granted", async () => {
    const { nav } = await openGate({ permission: "granted" });
    const { getUserMedia } = navigator.mediaDevices;

    await userEvent.click(firstGateCard());
    await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));

    // Leave the page so the decode loop this started is torn down with it.
    nav.showPage("history");
  });

  it("does not start, or prompt, when permission has not been granted", async () => {
    await openGate({ permission: "prompt" });
    const { getUserMedia } = navigator.mediaDevices;

    await userEvent.click(firstGateCard());
    await vi.waitFor(() =>
      expect(document.getElementById("scango-wo-label").textContent).toContain("Work order:"));
    expect(getUserMedia).not.toHaveBeenCalled();
  });

  it("does not start when the camera is denied outright", async () => {
    await openGate({ permission: "denied" });
    const { getUserMedia } = navigator.mediaDevices;

    await userEvent.click(firstGateCard());
    await vi.waitFor(() =>
      expect(document.getElementById("scango-wo-label").textContent).toContain("Work order:"));
    expect(getUserMedia).not.toHaveBeenCalled();
  });
});

describe("setScanResetter", () => {
  // Changing the work order clears the scan UI. Without the injection this is
  // a silent no-op (`if (resetScanUi)`), which is exactly the state every
  // other test file in this suite runs in -- so only a booted app can see it.
  it("changing the work order clears the scan section", async () => {
    await openGate({ permission: "granted" });
    await userEvent.click(firstGateCard());
    await vi.waitFor(() =>
      expect(document.getElementById("scango-wo-label").textContent).toContain("Work order:"));

    const message = document.getElementById("txn-scan-message");
    const chooser = document.getElementById("txn-scan-chooser");
    message.textContent = "Aim at a barcode…";
    chooser.innerHTML = "<button>pick</button>";
    chooser.hidden = false;

    await userEvent.click(document.getElementById("scango-change-wo-btn"));

    expect(message.textContent).toBe("");
    expect(chooser.innerHTML).toBe("");
    expect(chooser.hidden).toBe(true);
  });

  it("releases the camera when the work order changes", async () => {
    await openGate({ permission: "granted" });
    await userEvent.click(firstGateCard());
    const { getUserMedia } = navigator.mediaDevices;
    await vi.waitFor(() => expect(getUserMedia).toHaveBeenCalledTimes(1));
    const stream = await getUserMedia.mock.results[0].value;
    const [track] = stream.getTracks();

    await userEvent.click(document.getElementById("scango-change-wo-btn"));
    expect(track.stop).toHaveBeenCalled();
  });
});

describe("setActivePageGetter", () => {
  // `realtime.js` must be able to report the active page without importing a
  // view module or reading the DOM. Driven through the real dispatch path --
  // a scripted socket delivering a real envelope -- because there is no
  // `__emit` seam and inventing one would test the seam, not the wiring.
  it("realtime notifications carry the page nav.js says is active", async () => {
    const { nav, sockets } = await bootApp({ role: "owner" });
    const realtime = await import("../../../backend/static/realtime.js");

    const seen = [];
    const unsubscribe = realtime.subscribe("test.event", (n) => seen.push(n.activePage));

    const socket = sockets.last();
    socket.emitOpen();

    nav.showPage("history");
    socket.emitMessage(JSON.stringify({ id: null, req: null, type: "test.event" }));
    expect(seen).toEqual(["history"]);

    nav.showPage("tools");
    socket.emitMessage(JSON.stringify({ id: null, req: null, type: "test.event" }));
    expect(seen).toEqual(["history", "tools"]);

    unsubscribe();
  });

  it("connects a socket on sign-in", async () => {
    const { sockets } = await bootApp({ role: "owner" });
    expect(sockets.sockets).toHaveLength(1);
    expect(sockets.last().url).toMatch(/\/ws$/);
  });

  it("opens no socket when the boot check is refused", async () => {
    const { sockets } = await bootLoggedOut();
    expect(sockets.sockets).toHaveLength(0);
  });
});

describe("installTooltips", () => {
  beforeEach(async () => { await bootApp({ role: "owner" }); });

  // The delegation claim in main.js's comment: one call, once, covering
  // markup that does not exist yet. Half the app's `?` anchors are written by
  // views that re-render, so a per-element binding would go silently dead.
  it("a data-tip element added after boot still opens a bubble", async () => {
    const late = document.createElement("button");
    late.type = "button";
    late.dataset.tip = "txn.quick-mode";
    document.getElementById("app-root").appendChild(late);

    await userEvent.click(late);

    const bubble = document.getElementById("tip-bubble");
    expect(bubble.hidden).toBe(false);
    expect(bubble.textContent).toContain("Quick mode commits a dispense scan");
    expect(late.getAttribute("aria-expanded")).toBe("true");
  });

  it("a second click on the same trigger closes it", async () => {
    const trigger = document.querySelector("[data-tip]");
    await userEvent.click(trigger);
    expect(document.getElementById("tip-bubble").hidden).toBe(false);
    await userEvent.click(trigger);
    expect(document.getElementById("tip-bubble").hidden).toBe(true);
  });

  it("labels the shell's hand-authored triggers from tips.js", () => {
    const trigger = document.querySelector('[data-tip="auth.shift-session"]');
    expect(trigger.getAttribute("aria-label")).toBe("Help: Stay signed in for this shift");
    expect(trigger.getAttribute("aria-expanded")).toBe("false");
  });
});
