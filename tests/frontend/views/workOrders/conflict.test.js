// W3: a save refused because someone else changed the value first. The card's
// message line names who changed what and when, and offers Keep theirs /
// Save mine (workOrderConflict.js).

import { afterEach, describe, expect, it, vi } from "vitest";
import {
  card, cardBody, clearRequests, mountWorkOrders, openCard, requestFor, requests, respond,
} from "../../helpers/workOrders.js";
import { restoreBrowserStubs } from "../../helpers/browserStubs.js";
import { user, workOrderCard, workOrderDetail } from "../../helpers/factories.js";
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

// --- Task 5: Edit details sends only what changed --------------------------

const TECH_A = "20000000-0000-4000-8000-00000000000a";
const TECH_B = "20000000-0000-4000-8000-00000000000b";

async function openEditor({ users = [], ...over } = {}) {
  const detail = workOrderDetail({ location: "Bldg 4", priority: "P1", ...over });
  await mountWorkOrders({
    role: "admin", cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail], users,
  });
  await openCard(0);
  card().querySelector(".wo-edit-card").open = true;
  return detail;
}

const $ = (sel) => cardBody().querySelector(sel);
const saveDetails = () => card().querySelector('[data-action="save-details"]').click();
const patchSent = (detail) => requestFor(`/work-orders/${detail.id}`, "PATCH")?.body;
const priorityConflict = { ...conflict(), current: "P2", current_label: "P2" };
const conflict409 = (conflicts) => ({ detail: { code: "field_conflict", message: "x", conflicts } });

describe("save-details: only what changed", () => {
  it("sends only the edited field, with the value it showed as expected", async () => {
    const detail = await openEditor();
    respond("patch", "/work-orders/:id", detail);
    $(".wo-edit-location").value = "  Hallway B ";
    saveDetails();
    await vi.waitFor(() => expect(patchSent(detail)).toBeTruthy());
    expect(patchSent(detail)).toEqual({ location: "Hallway B", expected: { location: "Bldg 4" } });
  });

  it("nothing edited: no request, the editor closes", async () => {
    const detail = await openEditor();
    saveDetails();
    await vi.waitFor(() => expect(card().querySelector(".wo-edit-card").open).toBe(false));
    expect(patchSent(detail)).toBeUndefined();
  });

  it("Ready to Complete: a status change carries the real status as expected", async () => {
    const detail = await openEditor({ status: "ready_to_complete" });
    respond("patch", "/work-orders/:id", detail);
    $(".wo-edit-status").value = "in_progress";
    saveDetails();
    await vi.waitFor(() => expect(patchSent(detail)).toBeTruthy());
    expect(patchSent(detail)).toEqual({ status: "in_progress", expected: { status: "ready_to_complete" } });
  });

  it("an untouched status select whose rendered default differs from the row is not sent", async () => {
    // "assigned" with no technicians renders "created" first: the old full-form
    // save silently rolled such a row back.
    const detail = await openEditor({ status: "assigned" });
    respond("patch", "/work-orders/:id", detail);
    $(".wo-edit-location").value = "Hallway B";
    saveDetails();
    await vi.waitFor(() => expect(patchSent(detail)).toBeTruthy());
    expect(Object.keys(patchSent(detail))).toEqual(["location", "expected"]);
  });

  it("reordering the crew is not a change", async () => {
    const detail = await openEditor({ assigned_to_ids: [TECH_A, TECH_B], assigned_to_names: ["Ada", "Bo"] });
    const list = $(".wo-tech-selected-list");
    list.prepend(list.lastElementChild);
    saveDetails();
    await vi.waitFor(() => expect(card().querySelector(".wo-edit-card").open).toBe(false));
    expect(patchSent(detail)).toBeUndefined();
  });

  it("removing a crew member sends the new crew with the old one as expected", async () => {
    const detail = await openEditor({ assigned_to_ids: [TECH_A, TECH_B], assigned_to_names: ["Ada", "Bo"] });
    respond("patch", "/work-orders/:id", detail);
    card().querySelector(`[data-technician-id="${TECH_B}"] [data-action="remove-technician"]`).click();
    saveDetails();
    await vi.waitFor(() => expect(patchSent(detail)).toBeTruthy());
    expect(patchSent(detail)).toEqual({
      assigned_to_ids: [TECH_A], expected: { assigned_to_ids: [TECH_A, TECH_B] },
    });
  });

  it("the expected value survives a live patch while the editor is open", async () => {
    const detail = await openEditor();
    const live = await importView("views/workOrderLiveBody.js");
    live.patchBodyLive({ ...detail, location: "Bldg 7", priority: "P2" }, cardBody(), card());
    respond("patch", "/work-orders/:id", detail);
    $(".wo-edit-location").value = "Hallway B";
    saveDetails();
    await vi.waitFor(() => expect(patchSent(detail)).toBeTruthy());
    expect(patchSent(detail).expected).toEqual({ location: "Bldg 4" });
  });
});

describe("save-details: a conflict", () => {
  it("shows the sentence and both buttons", async () => {
    const detail = await openEditor();
    respond("patch", "/work-orders/:id", conflict409([priorityConflict]), { status: 409 });
    $(".wo-edit-priority").value = "P3";
    saveDetails();
    await vi.waitFor(() => expect(mineBtn()).not.toBeNull());
    expect(msg().textContent).toContain("Maria Lopez changed Priority to P2 12 seconds ago.");
    expect(patchSent(detail)).toEqual({ priority: "P3", expected: { priority: "P1" } });
  });

  it("Keep theirs takes their value and keeps other typing", async () => {
    await openEditor();
    respond("patch", "/work-orders/:id", conflict409([priorityConflict]), { status: 409 });
    $(".wo-edit-priority").value = "P3";
    $(".wo-edit-location").value = "Hallway B";
    $(".wo-edit-priority").classList.add("wo-field-conflict");
    saveDetails();
    await vi.waitFor(() => expect(keepBtn()).not.toBeNull());
    keepBtn().click();
    await vi.waitFor(() => expect($(".wo-edit-priority").value).toBe("P2"));
    expect($(".wo-edit-priority").defaultValue).toBe("P2");
    expect($(".wo-edit-priority").classList.contains("wo-field-conflict")).toBe(false);
    expect($(".wo-edit-location").value).toBe("Hallway B");
    expect($(".wo-edit-location").defaultValue).toBe("Bldg 4");
    expect(card().querySelector(".wo-edit-card").open).toBe(true);
  });

  it("Keep theirs on status and crew updates the combo and the originals", async () => {
    const tech = user({ role: "technician", full_name: "Cy Tech" });
    await openEditor({ status: "in_progress", users: [tech] });
    respond("patch", "/work-orders/:id", conflict409([
      conflict({ field: "status", label: "Status", current: "on_hold", current_label: "On-Hold" }),
      conflict({ field: "assigned_to_ids", label: "Assigned technicians", current: [tech.id], current_label: "Cy Tech" }),
    ]), { status: 409 });
    $(".wo-edit-status").value = "completed";
    saveDetails();
    await vi.waitFor(() => expect(keepBtn()).not.toBeNull());
    keepBtn().click();
    await vi.waitFor(() => expect($(".wo-edit-status").value).toBe("on_hold"));
    expect($(".wo-status-combo .menu-trigger-label").textContent).toBe("On-Hold");
    expect($(".wo-edit").dataset.originalStatus).toBe("on_hold");
    expect([...cardBody().querySelectorAll(".wo-tech-selected-row")].map((r) => r.dataset.technicianId))
      .toEqual([tech.id]);
    expect($(".wo-edit").dataset.originalCrew).toBe(tech.id);
  });

  it("Save mine resends with their value as expected, then repaints", async () => {
    const detail = await openEditor();
    respond("patch", "/work-orders/:id", conflict409([priorityConflict]), { status: 409 });
    $(".wo-edit-priority").value = "P3";
    saveDetails();
    await vi.waitFor(() => expect(mineBtn()).not.toBeNull());
    respond("patch", "/work-orders/:id", { ...detail, priority: "P3" });
    clearRequests();
    mineBtn().click();
    await vi.waitFor(() => expect(patchSent(detail)).toBeTruthy());
    expect(patchSent(detail)).toEqual({ priority: "P3", expected: { priority: "P2" } });
    await vi.waitFor(() => expect(requestFor(`/work-orders/${detail.id}`, "GET")).not.toBeNull());
  });

  it("a third change before Save mine lands shows the conflict again", async () => {
    await openEditor();
    respond("patch", "/work-orders/:id", conflict409([priorityConflict]), { status: 409 });
    $(".wo-edit-priority").value = "P3";
    saveDetails();
    await vi.waitFor(() => expect(mineBtn()).not.toBeNull());
    respond("patch", "/work-orders/:id",
      conflict409([{ ...priorityConflict, current: "P9", current_label: "P9", changed_by: "Kim Diaz" }]), { status: 409 });
    mineBtn().click();
    await vi.waitFor(() => expect(msg().textContent).toContain("Kim Diaz changed Priority to P9"));
    expect(mineBtn()).not.toBeNull();
  });
});
