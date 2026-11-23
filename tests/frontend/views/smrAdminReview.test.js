// views/smrAdminReview.js: the Ready-to-invoice SMR queue, the correction
// block on select, and the Not ready / Archive / Mark pasted / Regenerate /
// Print actions. Modeled on adminReview.test.js.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { mountView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
import { connectFakeRealtime } from "../helpers/realtime.js";
import { clearRequests, requestFor, requests, startRecording, stopRecording } from "../helpers/requests.js";
import { answerConfirm, confirmTitle } from "../helpers/dialogs.js";
import { workOrderDetail } from "../helpers/factories.js";

afterEach(() => stopRecording());

const el = (id) => document.getElementById(`smr-admin-review-${id}`);
const cards = () => Array.from(el("list").querySelectorAll(".admin-review-card"));
const cardFor = (id) => el("list").querySelector(`.admin-review-card[data-id="${id}"]`);
const tilesGets = () => requests().filter((r) => r.url === "/work-orders/smr");
const settle = () => new Promise((r) => setTimeout(r, 0));

const tile = (o = {}) => ({
  id: "w1", number: "5001", building_number: "B", unit_number: "7", location: "Oak",
  vendor_assignee: "Belfor", stage: "ready", archived_at: null,
  lines: { block_version: 2, block_pasted_at: "2026-11-12T15:00:00Z", block_stale: false, charged_hours: "4.0" },
  ...o,
});
const block = (o = {}) => ({
  id: "b1", version: 2, text: "LINE ONE\nLINE TWO\nLINE THREE", pasted_at: null, pasted_by_name: null, stale: false, ...o,
});

async function mount({ tiles = [], details = [], handlers = [] } = {}) {
  const byId = new Map(details.map((d) => [String(d.id), d]));
  server.use(
    ...handlers,
    http.get("/work-orders/smr", () => HttpResponse.json({ tiles })),
    http.get("/work-orders/:id", ({ params }) => {
      const d = byId.get(params.id);
      return d ? HttpResponse.json(d) : HttpResponse.json({ detail: "nope" }, { status: 404 });
    }),
  );
  await setTestUser({ role: "admin" });
  startRecording();
  const mod = await mountView("views/smrAdminReview.js");
  await mod.loadSmrAdminReview();
  clearRequests();
  return mod;
}

async function mountSelected(detailOverrides = {}, handlers = []) {
  const detail = workOrderDetail({ id: "w1", number: "5001", smr_block: block(), ...detailOverrides });
  await mount({ tiles: [tile()], details: [detail], handlers });
  cardFor("w1").click();
  await vi.waitFor(() => expect(el("block-section").hidden).toBe(false));
  clearRequests();
  return detail;
}

describe("the queue", () => {
  it("lists only ready, unarchived SMR orders", async () => {
    await mount({
      tiles: [
        tile({ id: "a", number: "1" }),
        tile({ id: "b", stage: "review" }),
        tile({ id: "c", archived_at: "2026-11-01T00:00:00Z" }),
        tile({ id: "d", number: "4", lines: { block_version: 1, block_pasted_at: null, block_stale: true } }),
      ],
    });
    expect(cards().map((c) => c.dataset.id)).toEqual(["a", "d"]);
    expect(cardFor("a").querySelector(".wo-card-status-label").textContent).toBe("Ready to invoice");
    expect(cardFor("a").querySelector(".wo-card-meta").textContent).toBe("Oak · B · 7");
    expect(cardFor("a").querySelector(".wo-card-assignee").textContent).toBe("Belfor");
    expect(cardFor("d").querySelector(".wo-card-status-label").textContent).toBe("Block stale");
    expect(el("list-message").textContent).toBe("2 SMR orders ready to invoice.");
  });

  it.each([
    [{ block_version: null }, "No block"],
    [{ block_version: 1, block_pasted_at: null, block_stale: false }, "Not pasted"],
  ])("labels %o as %s", async (lines, label) => {
    await mount({ tiles: [tile({ lines })] });
    expect(cards()[0].querySelector(".wo-card-status-label").textContent).toBe(label);
  });

  it("says so when nothing is ready", async () => {
    await mount({ tiles: [tile({ stage: "charged" })] });
    expect(cards()).toHaveLength(0);
    expect(el("list-message").textContent).toBe("No SMR orders are ready to invoice.");
  });
});

describe("selecting an order", () => {
  it("shows the full block text and its status", async () => {
    await mountSelected();
    expect(el("block-output").value).toBe("LINE ONE\nLINE TWO\nLINE THREE");
    expect(el("block-output").rows).toBe(3);
    expect(el("block-status").textContent).toBe("v2 · not yet pasted");
    expect(el("block-title").textContent).toBe("WO 5001 Correction Block");
    expect(el("pasted-btn").hidden).toBe(false);
    expect(el("regenerate-btn").hidden).toBe(true);
    expect(cardFor("w1").classList.contains("selected")).toBe(true);
  });

  it("with no block offers Regenerate, which posts the description and reselects", async () => {
    await mountSelected({ smr_block: null, smr_description: "Fixed blinds" }, [
      http.post("/work-orders/smr/w1/block", () => HttpResponse.json({})),
    ]);
    expect(el("block-message").textContent).toMatch(/no correction block/);
    expect(el("regenerate-btn").hidden).toBe(false);
    expect(el("pasted-btn").hidden).toBe(true);
    el("regenerate-btn").click();
    await vi.waitFor(() => expect(requestFor("/work-orders/w1", "GET")).not.toBeNull());
    expect(requestFor("/work-orders/smr/w1/block", "POST").body).toEqual({ description: "Fixed blinds" });
  });

  it("a stale block says the lines changed and offers Regenerate", async () => {
    await mountSelected({ smr_block: block({ stale: true }) });
    expect(el("block-status").textContent).toBe("v2 · not yet pasted · lines changed since v2");
    expect(el("regenerate-btn").hidden).toBe(false);
  });
});

describe("actions", () => {
  it("Mark pasted posts the block id and reloads", async () => {
    await mountSelected({}, [http.post("/work-orders/smr/blocks/b1/pasted", () => HttpResponse.json({}))]);
    el("pasted-btn").click();
    await vi.waitFor(() => expect(requestFor("/work-orders/w1", "GET")).not.toBeNull());
    expect(requestFor("/work-orders/smr/blocks/b1/pasted", "POST")).not.toBeNull();
    expect(tilesGets()).toHaveLength(1);
  });

  it("Not ready asks first, then clears ready and reloads, keeping the block", async () => {
    await mountSelected({}, [http.put("/work-orders/smr/w1/ready", () => HttpResponse.json({}))]);
    server.use(http.get("/work-orders/smr", () => HttpResponse.json({ tiles: [] })));
    el("not-ready-btn").click();
    await answerConfirm(true);
    expect(confirmTitle()).toBe("Send WO 5001 back? It leaves Ready to invoice.");
    await vi.waitFor(() => expect(el("block-message").textContent).toBe(
      "WO 5001 sent back. The block remains available for reference."));
    expect(requestFor("/work-orders/smr/w1/ready", "PUT").body).toEqual({ ready: false });
    expect(cards()).toHaveLength(0);
    expect(el("block-output").value).toBe("LINE ONE\nLINE TWO\nLINE THREE");
  });

  it("Archive asks first, then archives and reloads", async () => {
    await mountSelected({}, [http.post("/work-orders/:id/archive", () => new HttpResponse(null, { status: 204 }))]);
    el("archive-btn").click();
    await answerConfirm(true);
    expect(confirmTitle()).toBe("Archive WO 5001? It will leave the live work-order views.");
    await vi.waitFor(() => expect(el("block-message").textContent).toBe(
      "WO 5001 archived. The block remains available for copying."));
    expect(requestFor("/work-orders/w1/archive", "POST")).not.toBeNull();
    expect(tilesGets()).toHaveLength(1);
  });

  it("No on the confirm sends nothing", async () => {
    await mountSelected();
    el("archive-btn").click();
    await answerConfirm(false);
    await settle();
    expect(requests()).toEqual([]);
  });

  it("a failed archive re-enables the buttons", async () => {
    await mountSelected({}, [http.post("/work-orders/:id/archive", () => HttpResponse.json({ detail: "" }, { status: 500 }))]);
    el("archive-btn").click();
    await answerConfirm(true);
    await vi.waitFor(() => expect(el("block-message").textContent).toBe("Could not archive that order."));
    expect(el("archive-btn").disabled).toBe(false);
  });

  it("Print prints only the block", async () => {
    await mountSelected();
    let seen = null;
    window.print = () => { seen = document.querySelector(".smr-print-sheet").textContent; };
    el("print-btn").click();
    expect(seen).toBe("LINE ONE\nLINE TWO\nLINE THREE");
    expect(document.querySelector(".smr-print-sheet")).toBeNull();
  });
});

describe("live queue", () => {
  const glows = (id) => cardFor(id).classList.contains("just-changed");
  let realtime = null;
  afterEach(() => {
    if (realtime) { realtime.disconnect(); realtime = null; }
    vi.useRealTimers();
  });
  async function connect(page = "smr-admin-review") {
    realtime = await connectFakeRealtime(page);
    return realtime;
  }

  it("a live reload keeps an unchanged tile's DOM node", async () => {
    const mod = await mount({ tiles: [tile({ id: "a" }), tile({ id: "b" })] });
    const before = cardFor("a");
    await mod.loadSmrAdminReview({ background: true });
    expect(cardFor("a")).toBe(before);
    expect(before.id).toBe("smr-review-card-a");
  });

  it("keeps the selected class on the selected tile", async () => {
    const detail = workOrderDetail({ id: "w1", number: "5001", smr_block: block() });
    const mod = await mount({ tiles: [tile()], details: [detail] });
    cardFor("w1").click();
    await vi.waitFor(() => expect(el("block-section").hidden).toBe(false));
    await mod.loadSmrAdminReview({ background: true });
    expect(cardFor("w1").classList.contains("selected")).toBe(true);
  });

  it("glows a new or changed tile only", async () => {
    const tiles = [tile({ id: "a", number: "1" }), tile({ id: "b", number: "2" })];
    const mod = await mount({ tiles });
    tiles[1] = tile({ id: "b", number: "2", lines: { block_version: 2, block_stale: true } });
    tiles.push(tile({ id: "c", number: "3" }));
    await mod.loadSmrAdminReview({ background: true });
    expect([glows("a"), glows("b"), glows("c")]).toEqual([false, true, true]);
  });

  it("first load glows nothing", async () => {
    await mount({ tiles: [tile({ id: "a" }), tile({ id: "b" })] });
    expect(el("list").querySelector(".just-changed")).toBeNull();
  });

  it("a background load leaves an action or error message alone", async () => {
    const mod = await mount({ tiles: [tile({ id: "a" })] });
    cardFor("a").click();
    await vi.waitFor(() => expect(el("list-message").className).toBe("error"));
    const text = el("list-message").textContent;
    await mod.loadSmrAdminReview({ background: true });
    expect(el("list-message").textContent).toBe(text);
  });

  it("reloads the queue on work_order.status.changed while the page is active", async () => {
    await mount({ tiles: [tile()] });
    const rt = await connect();
    rt.emit("work_order.status.changed", { id: "w9" });
    await vi.waitFor(() => expect(tilesGets()).toHaveLength(1));
  });

  it("ignores the event on another page", async () => {
    await mount({ tiles: [tile()] });
    const rt = await connect("history");
    rt.emit("work_order.status.changed", { id: "w9" });
    await settle();
    expect(requests()).toEqual([]);
  });

  it("reloads on reconnect", async () => {
    await mount({ tiles: [tile()] });
    const rt = await connect();
    vi.useFakeTimers();
    rt.reconnect();
    vi.advanceTimersByTime(1000);
    rt.ws.last().emitOpen();
    expect(tilesGets()).toHaveLength(1);
    await vi.runAllTimersAsync();
  });

  it('a background load shows no "Loading" line', async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    await mount({ tiles: [tile()] });
    server.use(http.get("/work-orders/smr", async () => { await gate; return HttpResponse.json({ tiles: [tile()] }); }));
    const rt = await connect();
    rt.emit("work_order.status.changed", { id: "w9" });
    await vi.waitFor(() => expect(tilesGets()).toHaveLength(1));
    expect(el("list-message").textContent).toBe("1 SMR order ready to invoice.");
    release();
    await settle();
  });
});

describe("live detail", () => {
  const CHANGED = "This order was changed by someone else. The block is up to date.";
  const READY = "Block ready — print it or select all and copy.";
  const ACTIONS = ["regenerate-btn", "print-btn", "pasted-btn", "not-ready-btn", "archive-btn"];
  const detailGets = () => requests().filter((r) => r.method === "GET" && r.url === "/work-orders/w1");
  let realtime = null;
  afterEach(() => {
    if (realtime) { realtime.disconnect(); realtime = null; }
    vi.useRealTimers();
  });
  async function open(overrides = {}, handlers = []) {
    const detail = await mountSelected({ smr_stage: "ready", ...overrides }, handlers);
    realtime = await connectFakeRealtime("smr-admin-review");
    return { detail, rt: realtime };
  }

  it("refreshes the block and status when labor changes", async () => {
    const { detail, rt } = await open();
    const focused = document.activeElement;
    detail.smr_block = block({ stale: true });
    rt.emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(el("block-message").textContent).toBe(CHANGED));
    expect(el("block-status").textContent).toBe("v2 · not yet pasted · lines changed since v2");
    expect(el("regenerate-btn").hidden).toBe(false);
    expect(document.activeElement).toBe(focused);
  });

  it("refreshes the block text", async () => {
    const { detail, rt } = await open();
    detail.smr_block = block({ version: 3, text: "NEW LINE" });
    rt.emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(el("block-output").value).toBe("NEW LINE"));
    expect(el("block-message").textContent).toBe(CHANGED);
  });

  it("an unchanged order shows no note", async () => {
    const { rt } = await open();
    rt.emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(detailGets()).toHaveLength(1));
    await settle();
    await settle();
    expect(el("block-message").textContent).toBe(READY);
    expect(detailGets()).toHaveLength(1);
  });

  it("an event for another order leaves the block alone", async () => {
    const { rt } = await open();
    rt.emit("work_order.status.changed", { id: "someone-else" });
    await vi.waitFor(() => expect(tilesGets()).toHaveLength(1));
    await settle();
    expect(detailGets()).toHaveLength(0);
    expect(el("block-message").textContent).toBe(READY);
  });

  it.each([
    ["no longer ready", (detail) => { detail.smr_stage = "review"; }],
    ["archived", () => server.use(http.get("/work-orders/w1", () => HttpResponse.json({ detail: "" }, { status: 404 })))],
  ])("marks the order gone when it is %s", async (_, change) => {
    const { detail, rt } = await open();
    change(detail);
    rt.emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(el("block-message").textContent).toBe(
      "WO 5001 was closed or sent back by someone else. The block remains for reference."));
    expect(ACTIONS.map((id) => el(id).disabled)).toEqual([true, true, true, true, true]);
    expect(el("block-output").value).toBe("LINE ONE\nLINE TWO\nLINE THREE");
  });

  it("own Archive shows its own message", async () => {
    const { detail, rt } = await open({}, [
      http.post("/work-orders/:id/archive", () => new HttpResponse(null, { status: 204 })),
    ]);
    el("archive-btn").click();
    await answerConfirm(true);
    const own = "WO 5001 archived. The block remains available for copying.";
    await vi.waitFor(() => expect(el("block-message").textContent).toBe(own));
    clearRequests();
    detail.smr_stage = "review";
    rt.emit("work_order.status.changed", { id: "w1" });
    await vi.waitFor(() => expect(tilesGets()).toHaveLength(1));
    await settle();
    await settle();
    expect(el("block-message").textContent).toBe(own);
    expect(detailGets()).toHaveLength(0);
  });

  it("a tile tapped during the refresh wins", async () => {
    let release;
    const gate = new Promise((r) => { release = r; });
    let held = false;
    const a = workOrderDetail({ id: "w1", number: "5001", smr_stage: "ready", smr_block: block() });
    const b = workOrderDetail({ id: "w2", number: "5002", smr_stage: "ready", smr_block: block({ text: "OTHER" }) });
    await mount({
      tiles: [tile(), tile({ id: "w2", number: "5002" })],
      details: [a, b],
      handlers: [http.get("/work-orders/w1", async () => {
        if (!held) return HttpResponse.json(a);
        await gate;
        return HttpResponse.json({ ...a, smr_block: block({ text: "LATE" }) });
      })],
    });
    cardFor("w1").click();
    await vi.waitFor(() => expect(el("block-section").hidden).toBe(false));
    realtime = await connectFakeRealtime("smr-admin-review");
    held = true;
    realtime.emit("work_order.status.changed", { id: "w1" });
    cardFor("w2").click();
    await vi.waitFor(() => expect(el("block-output").value).toBe("OTHER"));
    release();
    await settle();
    await settle();
    expect(el("block-title").textContent).toBe("WO 5002 Correction Block");
    expect(el("block-output").value).toBe("OTHER");
  });

  it("refreshes on reconnect", async () => {
    const { rt } = await open();
    vi.useFakeTimers();
    rt.reconnect();
    vi.advanceTimersByTime(1000);
    rt.ws.last().emitOpen();
    expect(detailGets()).toHaveLength(1);
    await vi.runAllTimersAsync();
  });
});
