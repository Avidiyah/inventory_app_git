// W3: a save refused because someone else changed the value first. The card's
// message line names who changed what and when, and offers Keep theirs /
// Save mine (workOrderConflict.js).

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  card, cardBody, clearRequests, mountWorkOrders, openCard, requests,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail } from "../../helpers/factories.js";
import { importView } from "../../helpers/shell.js";

afterEach(() => {
  restoreBrowserStubs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const conflict = (over = {}) => ({
  field: "priority", label: "Priority", current: "P2", current_label: "P2",
  changed_by: "Maria Lopez", seconds_ago: 12, ...over,
});

async function openConflictCard(over = {}) {
  const detail = workOrderDetail(over);
  await mountWorkOrders({
    role: "admin", cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail],
  });
  await openCard(0);
  const mod = await importView("views/workOrderConflict.js");
  return { detail, mod };
}

const msg = () => document.getElementById("wo-sec-msg");
const keepBtn = () => document.querySelector('[data-action="keep-theirs-wo"]');
const mineBtn = () => document.querySelector('[data-action="save-mine-wo"]');

describe("wording", () => {
  it("names who, what, the new value and how long ago", async () => {
    const { conflictSentence } = await importView("views/workOrderConflict.js");
    expect(conflictSentence(conflict())).toBe("Maria Lopez changed Priority to P2 12 seconds ago.");
  });

  it("no stamp: someone else", async () => {
    const { conflictSentence } = await importView("views/workOrderConflict.js");
    expect(conflictSentence(conflict({ seconds_ago: null, changed_by: null })))
      .toBe("Someone else changed Priority to P2.");
  });

  it("no name: the field was changed", async () => {
    const { conflictSentence } = await importView("views/workOrderConflict.js");
    expect(conflictSentence(conflict({ changed_by: null })))
      .toBe("Priority was changed to P2 12 seconds ago.");
  });

  it("age rolls up from seconds to minutes, hours and days", async () => {
    const { conflictAge } = await importView("views/workOrderConflict.js");
    expect(conflictAge(1)).toBe("1 second ago");
    expect(conflictAge(59)).toBe("59 seconds ago");
    expect(conflictAge(60)).toBe("1 minute ago");
    expect(conflictAge(7200)).toBe("2 hours ago");
    expect(conflictAge(172800)).toBe("2 days ago");
  });

  it("isFieldConflict reads only the structured 409", async () => {
    const { isFieldConflict } = await importView("views/workOrderConflict.js");
    expect(isFieldConflict({ status: 409, detail: { code: "field_conflict", conflicts: [] } })).toBe(true);
    expect(isFieldConflict({ status: 409, detail: "This Work Order was already assigned to X" })).toBe(false);
    expect(isFieldConflict({ status: 400, detail: { code: "field_conflict" } })).toBe(false);
  });
});

describe("the message line", () => {
  it("two conflicts: two sentences in one line, then both buttons", async () => {
    const { mod } = await openConflictCard();
    mod.showConflict(card(), [conflict(), conflict({ field: "location", label: "Location", current_label: "Bldg 9" })],
      { keep: vi.fn(), retry: vi.fn() });
    expect(msg().querySelector(".wo-conflict-text").textContent).toBe(
      "Maria Lopez changed Priority to P2 12 seconds ago. Maria Lopez changed Location to Bldg 9 12 seconds ago."
    );
    expect(keepBtn().textContent).toBe("Keep theirs");
    expect(keepBtn().id).toBe("wo-act-keep-theirs");
    expect(mineBtn().textContent).toBe("Save mine");
    expect(mineBtn().id).toBe("wo-act-save-mine");
    expect(msg().className).toBe("error");
  });

  it("Keep theirs calls keep with the conflicts and sends nothing", async () => {
    const { mod } = await openConflictCard();
    const keep = vi.fn();
    const conflicts = [conflict()];
    mod.showConflict(card(), conflicts, { keep, retry: vi.fn() });
    clearRequests();
    keepBtn().click();
    await vi.waitFor(() => expect(keep).toHaveBeenCalledWith(conflicts));
    expect(requests().filter((r) => r.method !== "GET")).toEqual([]);
    expect(msg().textContent).toBe("");
  });

  it("Save mine runs retry once on a double tap", async () => {
    const { mod } = await openConflictCard();
    let release;
    const retry = vi.fn(() => new Promise((resolve) => { release = resolve; }));
    mod.showConflict(card(), [conflict()], { keep: vi.fn(), retry });
    const button = mineBtn();
    button.click();
    button.click();
    release();
    await vi.waitFor(() => expect(retry).toHaveBeenCalledTimes(1));
    await new Promise((r) => setTimeout(r, 0));
    expect(retry).toHaveBeenCalledTimes(1);
  });

  it("buttons survive a live patch of the card body", async () => {
    const { detail, mod } = await openConflictCard();
    mod.showConflict(card(), [conflict()], { keep: vi.fn(), retry: vi.fn() });
    const live = await importView("views/workOrderLiveBody.js");
    live.patchBodyLive({ ...detail, priority: "P2" }, cardBody(), card());
    expect(keepBtn()?.isConnected).toBe(true);
    expect(mineBtn()?.isConnected).toBe(true);
  });

  it("without handlers (a replayed draft) shows the sentence and no buttons", async () => {
    const { mod } = await openConflictCard();
    mod.showConflict(card(), [conflict()]);
    expect(msg().textContent).toBe("Maria Lopez changed Priority to P2 12 seconds ago.");
    expect(keepBtn()).toBeNull();
  });
});
