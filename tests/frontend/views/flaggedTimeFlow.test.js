// views/flaggedTimeFlow.js: the queue builders and the step-through pop-up.
// No fetch in the module, so every action is a stub here.

import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { importView, mountShell } from "../helpers/shell.js";

const flush = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };

function punch(id, over = {}) {
  return {
    id, started_at: "2026-11-24T13:02:00.000Z", ended_at: "2026-11-24T18:00:00.000Z",
    start_source: "manual", end_source: "manual", needs_review: false, minutes: 300,
    carried: false, open: false, lunch_waived: false, crosses_midnight: false, shop: false,
    ...over,
  };
}
const person = (id, first, last) => ({ id, first_name: first, last_name: last, role: "technician" });
function day(date, punches) { return { date, punches }; }

const WEEK = {
  rows: [
    { user: person("u2", "Zed", "Young"), days: [
      day("2026-11-23", [punch("p-z", { needs_review: true })]),
    ] },
    { user: person("u1", "Amy", "Baker"), days: [
      day("2026-11-23", [
        punch("p-auto", { needs_review: true, end_source: "auto_clock_out" }),
        punch("p-ok"),
      ]),
      day("2026-11-24", [
        punch("p-cross", { crosses_midnight: true }),
        punch("p-cross", { crosses_midnight: true, carried: true }),
        punch("p-other", { needs_review: true }),
      ]),
    ] },
  ],
  flagged_sessions: [{
    session_id: "s1", user_id: "u1", date: "2026-11-23", work_order_id: "w1", number: "4412",
    started_at: "2026-11-23T14:00:00.000Z", ended_at: "2026-11-24T02:00:00.000Z", running: false,
  }],
};

let mod;
let opener;
beforeEach(async () => {
  mountShell();
  opener = document.createElement("button");
  document.body.appendChild(opener);
  opener.focus();
  mod = await importView("views/flaggedTimeFlow.js");
});
afterEach(() => { document.querySelectorAll(".flagged-flow").forEach((n) => n.remove()); });

const q = (sel) => document.querySelector(sel);
const text = () => q(".flagged-flow").textContent;
const button = (label) => [...document.querySelectorAll(".flagged-flow button")]
  .find((b) => b.textContent.trim() === label);

function item(n, over = {}) {
  return {
    key: `punch:p${n}`, kind: "punch", id: `p${n}`, userId: "u1", name: "Amy Baker",
    date: "2026-11-24", reason: "Marked for review.",
    started_at: "2026-11-24T13:02:00.000Z", ended_at: "2026-11-24T18:00:00.000Z", number: null,
    ...over,
  };
}

function open(items, over = {}) {
  const actions = {
    savePunch: vi.fn().mockResolvedValue(), deletePunch: vi.fn().mockResolvedValue(),
    looksRight: vi.fn().mockResolvedValue(), acceptSession: vi.fn().mockResolvedValue(),
    openWorkOrder: vi.fn(), ...(over.actions || {}),
  };
  const refresh = over.refresh || vi.fn(async () => []);
  const onClose = vi.fn();
  const flow = mod.openFlaggedTimeFlow({
    items, canAccept: over.canAccept ?? true, actions, refresh, onClose,
  });
  return { flow, actions, refresh, onClose };
}

describe("flaggedItems", () => {
  it("orders by date then name, skips carried punches and lists sessions", () => {
    const items = mod.flaggedItems(WEEK);
    expect(items.map((i) => i.key)).toEqual([
      // Same day and person: the earlier start (the 11-23 clock) goes first.
      "session:s1", "punch:p-auto", "punch:p-z", "punch:p-cross", "punch:p-other",
    ]);
    expect(items.filter((i) => i.id === "p-cross")).toHaveLength(1);
    expect(items[0]).toMatchObject({
      kind: "session", id: "s1", userId: "u1", name: "Amy Baker", date: "2026-11-23", number: "4412",
    });
    expect(items[1]).toMatchObject({ kind: "punch", userId: "u1", name: "Amy Baker", date: "2026-11-23" });
  });

  it("maps each flag condition to the spec's reason line", () => {
    const by = Object.fromEntries(mod.flaggedItems(WEEK).map((i) => [i.id, i.reason]));
    expect(by["p-auto"]).toBe("Auto-closed at midnight. No clock-out was recorded.");
    expect(by["p-cross"]).toBe("This punch ends on the next day. Set the real end.");
    expect(by["p-other"]).toBe("Marked for review.");
    expect(by.s1).toBe("The clock on WO 4412 was stopped automatically after 12 hours.");
  });

  it("is empty when nothing is flagged or the payload has no sessions list", () => {
    expect(mod.flaggedItems({ rows: [{ user: person("u", "A", "B"), days: [day("2026-11-23", [punch("x")])] }] }))
      .toEqual([]);
  });
});

describe("ownFlaggedItems", () => {
  it("returns only the caller's flagged punches", () => {
    const attendance = { week_punches: [
      { id: "a", started_at: "2026-11-24T13:00:00.000Z", ended_at: null, needs_review: false, end_source: null },
      { id: "b", started_at: "2026-11-24T13:00:00.000Z", ended_at: "2026-11-25T06:00:00.000Z", needs_review: true, end_source: "auto_clock_out" },
      { id: "c", started_at: "2026-11-23T13:00:00.000Z", ended_at: "2026-11-23T20:00:00.000Z", needs_review: true, end_source: "manual" },
    ] };
    const items = mod.ownFlaggedItems(attendance, { id: "me", first_name: "Dana", last_name: "Reed" });
    expect(items.map((i) => i.key)).toEqual(["punch:c", "punch:b"]);
    expect(items[1]).toMatchObject({
      kind: "punch", userId: "me", name: "Dana Reed", date: "2026-11-24",
      reason: "Auto-closed at midnight. No clock-out was recorded.",
    });
    expect(items[0].reason).toBe("Marked for review.");
  });
});

describe("the pop-up", () => {
  it("is a labelled modal dialog on the body and shows 'Flagged time · 1 of N'", () => {
    open([item(1), item(2), item(3)]);
    const flow = q(".flagged-flow");
    expect(flow.parentElement).toBe(document.body);
    const box = flow.querySelector('[role="dialog"]');
    expect(box.getAttribute("aria-modal")).toBe("true");
    expect(q(".flagged-flow-heading").textContent).toBe("Flagged time · 1 of 3");
    expect(document.activeElement).toBe(q(".flagged-flow-heading"));
    expect(text()).toContain("Amy Baker");
    expect(text()).toContain("Marked for review.");
    expect(q(".flagged-flow [style]")).toBeNull();
    expect(q(".flagged-flow button button")).toBeNull();
  });

  it("Skip advances with no action call and counts as skipped", async () => {
    const { actions, refresh } = open([item(1), item(2)]);
    button("Skip").click();
    await flush();
    expect(q(".flagged-flow-heading").textContent).toBe("Flagged time · 2 of 2");
    expect(refresh).not.toHaveBeenCalled();
    for (const fn of Object.values(actions)) expect(fn).not.toHaveBeenCalled();
    button("Skip").click();
    await flush();
    expect(text()).toContain("Fixed 0 · Skipped 2");
  });

  it("a resolved action refreshes once and advances", async () => {
    const refresh = vi.fn(async () => [item(2)]);
    const { actions } = open([item(1), item(2)], { refresh });
    button("Looks right").click();
    await flush();
    expect(actions.looksRight).toHaveBeenCalledWith("p1");
    expect(refresh).toHaveBeenCalledTimes(1);
    expect(q(".flagged-flow-heading").textContent).toBe("Flagged time · 2 of 2");
    expect(text()).toContain("Marked for review.");
  });

  it("Save and Delete go through the editor's callbacks", async () => {
    const refresh = vi.fn(async () => [item(2)]);
    const { actions } = open([item(1), item(2)], { refresh });
    q(".punch-editor-reason").value = "forgot";
    q(".punch-editor-save").click();
    await flush();
    expect(actions.savePunch).toHaveBeenCalledWith("p1", {
      startedAt: "2026-11-24T13:02:00.000Z", endedAt: "2026-11-24T18:00:00.000Z", reason: "forgot",
    });
    refresh.mockResolvedValue([]);
    q(".punch-editor-delete").click();
    await flush();
    expect(actions.deletePunch).toHaveBeenCalledWith("p2", "");
  });

  it("the editor's Cancel reads Skip and skips", async () => {
    open([item(1), item(2)]);
    expect(q(".punch-editor-cancel").textContent.trim()).toBe("Skip");
    q(".punch-editor-cancel").click();
    await flush();
    expect(q(".flagged-flow-heading").textContent).toBe("Flagged time · 2 of 2");
  });

  it("a rejected action shows the error and stays", async () => {
    const looksRight = vi.fn().mockRejectedValue({ status: 409, detail: "Already changed." });
    const refresh = vi.fn(async () => [item(1), item(2)]);
    open([item(1), item(2)], { actions: { looksRight }, refresh });
    button("Looks right").click();
    await flush();
    expect(text()).toContain("Already changed.");
    expect(q(".flagged-flow-heading").textContent).toBe("Flagged time · 1 of 2");
  });

  it("after a rejection whose refresh drops the item, the flow advances", async () => {
    const looksRight = vi.fn().mockRejectedValue({ status: 404, detail: "Gone." });
    const refresh = vi.fn(async () => [item(2)]);
    const { onClose } = open([item(1), item(2)], { actions: { looksRight }, refresh });
    button("Looks right").click();
    await flush();
    expect(q(".flagged-flow-heading").textContent).toBe("Flagged time · 1 of 1");
    expect(text()).toContain("Marked for review.");
    expect(q(".flagged-flow-error").textContent).toBe("");
    button("Skip").click();
    await flush();
    button("Done").click();
    expect(onClose).toHaveBeenCalledWith({ fixed: 0, skipped: 1 });
  });

  it("keeps its place when an earlier skipped item stays flagged", async () => {
    const refresh = vi.fn(async () => [item(1), item(3)]);
    open([item(1), item(2), item(3)], { refresh });
    button("Skip").click();
    await flush();
    button("Looks right").click();
    await flush();
    expect(q(".flagged-flow-heading").textContent).toBe("Flagged time · 3 of 3");
    expect(q(".flagged-flow-who").textContent).toContain("Amy Baker");
  });

  it("a second click while busy makes no second call", async () => {
    let release;
    const looksRight = vi.fn(() => new Promise((r) => { release = r; }));
    open([item(1), item(2)], { actions: { looksRight } });
    const b = button("Looks right");
    b.click();
    b.click();
    await flush();
    expect(looksRight).toHaveBeenCalledTimes(1);
    release();
    await flush();
  });

  it("canAccept: false renders no Looks right", () => {
    open([item(1)], { canAccept: false });
    expect(button("Looks right")).toBeUndefined();
    expect(q(".punch-editor-save")).not.toBeNull();
  });

  it("a session step shows Accept, Open work order and Skip", async () => {
    const s = item(9, {
      key: "session:s9", kind: "session", id: "s9", number: "4412",
      reason: "The clock on WO 4412 was stopped automatically after 12 hours.",
    });
    const refresh = vi.fn(async () => []);
    const { actions } = open([s], { refresh });
    expect(button("Accept")).toBeDefined();
    expect(button("Open work order")).toBeDefined();
    expect(button("Skip")).toBeDefined();
    expect(q(".punch-editor")).toBeNull();
    button("Accept").click();
    await flush();
    expect(actions.acceptSession).toHaveBeenCalledWith("s9");
    expect(text()).toContain("Fixed 1 · Skipped 0");
  });

  it("drops session steps for a caller who cannot accept", () => {
    const s = item(9, { key: "session:s9", kind: "session", id: "s9", number: "1" });
    open([s, item(1)], { canAccept: false });
    expect(q(".flagged-flow-heading").textContent).toBe("Flagged time · 1 of 1");
  });

  it("the last step reads 'Fixed 3 · Skipped 2'", async () => {
    const refresh = vi.fn()
      .mockResolvedValueOnce([item(2), item(3), item(4), item(5)])
      .mockResolvedValueOnce([item(3), item(4), item(5)])
      .mockResolvedValueOnce([item(4), item(5)]);
    open([1, 2, 3, 4, 5].map((n) => item(n)), { refresh });
    button("Looks right").click(); await flush();
    button("Looks right").click(); await flush();
    button("Looks right").click(); await flush();
    button("Skip").click(); await flush();
    button("Skip").click(); await flush();
    expect(text()).toContain("Fixed 3 · Skipped 2");
    expect(button("Done")).toBeDefined();
  });

  it("X and Done call onClose with the counts and give focus back", async () => {
    const a = open([item(1), item(2)]);
    button("Skip").click(); await flush();
    q(".flagged-flow-close").click();
    expect(a.onClose).toHaveBeenCalledWith({ fixed: 0, skipped: 1 });
    expect(q(".flagged-flow")).toBeNull();
    expect(document.activeElement).toBe(opener);

    const b = open([item(1)]);
    button("Skip").click(); await flush();
    button("Done").click();
    expect(b.onClose).toHaveBeenCalledWith({ fixed: 0, skipped: 1 });
    expect(q(".flagged-flow")).toBeNull();
  });

  it("Open work order closes the pop-up first", () => {
    const s = item(9, { key: "session:s9", kind: "session", id: "s9", number: "4412" });
    const order = [];
    const openWorkOrder = vi.fn(() => order.push(q(".flagged-flow") ? "open-while-shown" : "open-after-close"));
    const { onClose } = open([s], { actions: { openWorkOrder } });
    onClose.mockImplementation(() => order.push("closed"));
    button("Open work order").click();
    expect(openWorkOrder).toHaveBeenCalledWith("4412");
    expect(order).toEqual(["closed", "open-after-close"]);
  });

  it("an empty queue goes straight to the summary", () => {
    open([]);
    expect(text()).toContain("Fixed 0 · Skipped 0");
  });
});
