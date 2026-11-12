// views/smrAdminReview.js: the Ready-to-invoice SMR queue, the correction
// block on select, and the Not ready / Archive / Mark pasted / Regenerate /
// Print actions. Modeled on adminReview.test.js.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { mountView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
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
