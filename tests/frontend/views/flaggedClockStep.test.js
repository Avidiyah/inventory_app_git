// views/flaggedClockStep.js: the auto-stopped clock step inside Fix flagged
// time. dom.js is mocked so promptTime() is a plain resolved value -- the
// picker itself is tested on its own.

import { beforeEach, describe, expect, it, vi } from "vitest";

const promptTime = vi.fn();
vi.mock("../../../backend/static/dom.js", () => ({ promptTime }));

const { mountClockStep, resolveStop, recentNotes } = await import(
  "../../../backend/static/views/flaggedClockStep.js");

const flush = async () => { for (let i = 0; i < 8; i += 1) await Promise.resolve(); };

const ITEM = {
  id: "s1", workOrderId: "w1", number: "4412",
  started_at: "2026-11-24T13:02:00.000Z", ended_at: "2026-11-25T01:02:00.000Z",
};
const DETAIL = {
  id: "w1", number: "4412", location: "Bldg C Rm 210", description: "Replace ceiling tile",
  status: "in_progress", assigned_to_names: ["Dana R", "Luis M"],
  labor: [
    { id: "l1", technician_name: "Dana R", minutes: 720, session_id: "s1", recorded_by_self: true },
    { id: "l2", technician_name: "Luis M", minutes: 90, session_id: null, recorded_by_self: false },
  ],
  notes: ["n1", "n2", "n3", "n4", "n5", "n6", "n7"].join("\n\n"),
};

describe("resolveStop", () => {
  const start = "2026-11-24T13:02:00.000Z";
  const end = "2026-11-25T01:02:00.000Z";

  it("keeps a time inside the clock", () => {
    expect(resolveStop(new Date("2026-11-24T21:30:00.000Z"), start, end))
      .toBe("2026-11-24T21:30:00.000Z");
  });

  it("reads a late time on a midnight-crossing clock as the start day", () => {
    // Mon 7 PM -> Tue 7 AM Central; the picker returns Tue 11 PM, meaning Mon 11 PM.
    expect(resolveStop(new Date("2026-11-25T05:00:00.000Z"),
      "2026-11-24T01:00:00.000Z", "2026-11-24T13:00:00.000Z"))
      .toBe("2026-11-24T05:00:00.000Z");
  });

  it("refuses a time before the start", () => {
    expect(resolveStop(new Date("2026-11-25T00:00:00.000Z"),
      "2026-11-24T01:00:00.000Z", "2026-11-24T13:00:00.000Z")).toBeNull();
  });

  it("allows the automatic stop itself", () => {
    expect(resolveStop(new Date(end), start, end)).toBe(end);
  });
});

describe("recentNotes", () => {
  it("returns the last five entries, newest first", () => {
    expect(recentNotes(DETAIL.notes)).toEqual(["n7", "n6", "n5", "n4", "n3"]);
  });
  it("returns nothing for no notes", () => {
    expect(recentNotes(null)).toEqual([]);
  });
});

describe("the clock step", () => {
  let host;
  let calls;
  beforeEach(() => {
    document.body.innerHTML = "";
    host = document.createElement("div");
    document.body.appendChild(host);
    promptTime.mockReset();
    calls = { onSave: vi.fn(), onAccept: vi.fn(), onOpen: vi.fn(), onSkip: vi.fn() };
  });
  const q = (sel) => host.querySelector(sel);
  const mount = (load = () => Promise.resolve(DETAIL)) =>
    mountClockStep(host, { item: ITEM, loadWorkOrder: load, ...calls });

  it("shows the order line once the order loads", async () => {
    mount();
    expect(q(".flagged-clock-order").textContent).toContain("WO 4412");
    await flush();
    expect(q(".flagged-clock-order").textContent.replace(/\s+/g, " ").trim())
      .toBe("WO 4412 · Bldg C Rm 210 · Replace ceiling tile · In-Progress");
  });

  it("folds crew, labor and notes with counts", async () => {
    mount();
    await flush();
    const labor = q("details.flagged-clock-labor");
    const notes = q("details.flagged-clock-notes");
    expect(labor.open).toBe(false);
    expect(notes.open).toBe(false);
    expect(labor.querySelector("summary").textContent).toBe("Crew and labor (2)");
    expect(notes.querySelector("summary").textContent).toBe("Recent notes (5)");
    expect(labor.textContent).toContain("Dana R, Luis M");
    expect(labor.textContent).toContain("this clock");
    expect(notes.textContent).toContain("n7");
    expect(notes.textContent).not.toContain("n2");
  });

  it("enables Save & accept only after a stop is picked, then saves it", async () => {
    mount();
    await flush();
    const save = q('[data-flow="save-accept"]');
    expect(save.disabled).toBe(true);
    promptTime.mockResolvedValue(new Date("2026-11-24T21:32:00.000Z"));
    q(".flagged-clock-stop").click();
    await flush();
    expect(q(".flagged-clock-hours").textContent).toBe("8.5 h");
    expect(save.disabled).toBe(false);
    save.click();
    expect(calls.onSave).toHaveBeenCalledWith("2026-11-24T21:32:00.000Z");
  });

  it("explains a picked time outside the clock and keeps Save off", async () => {
    mount();
    await flush();
    promptTime.mockResolvedValue(new Date("2026-11-24T12:00:00.000Z"));
    q(".flagged-clock-stop").click();
    await flush();
    expect(q('[data-flow="save-accept"]').disabled).toBe(true);
    expect(host.textContent).toContain("after the start");
  });

  it("still edits when the order cannot be read", async () => {
    mount(() => Promise.reject(new Error("nope")));
    await flush();
    expect(host.textContent).toContain("Could not load the work order.");
    promptTime.mockResolvedValue(new Date("2026-11-24T21:32:00.000Z"));
    q(".flagged-clock-stop").click();
    await flush();
    q('[data-flow="save-accept"]').click();
    expect(calls.onSave).toHaveBeenCalled();
  });

  it("wires Accept as is, Open work order and Skip", async () => {
    mount();
    await flush();
    expect(q('[data-flow="accept"]').textContent).toBe("Accept as is");
    q('[data-flow="accept"]').click();
    q('[data-flow="open-wo"]').click();
    q('[data-flow="skip"]').click();
    expect(calls.onAccept).toHaveBeenCalled();
    expect(calls.onOpen).toHaveBeenCalled();
    expect(calls.onSkip).toHaveBeenCalled();
  });

  it("never nests a button or sets an inline style", async () => {
    mount();
    await flush();
    expect(host.querySelector("button button")).toBeNull();
    expect(host.querySelector("[style]")).toBeNull();
  });
});
