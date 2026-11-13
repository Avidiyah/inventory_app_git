// An SMR order's Labor card and Invoice section (user 2026-11-12): its
// `smr-*` actions in workOrderSmrActions.js, the read-only view below Admin,
// the total and block status lines, and the vocabulary mirror of the domain.

import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import {
  answerConfirm, card, message, mountWorkOrders, openCard, requestFor, requests, respond,
} from "../../helpers/workOrders.js";
import { workOrderCard, workOrderDetail } from "../../helpers/factories.js";
import { importView } from "../../helpers/shell.js";

const LINE = {
  id: "11111111-1111-4111-8111-111111111111", work_order_id: "w", reading_id: "r1", import_key: null,
  work_date: "2026-06-20", date_basis: "paper", week: 4, vendor: "BT Restoration", worker_id: null,
  worker_name: null, alias_on_paper: null, headcount: 2, hours_each: "3.0", hours: "6.0", kind: "field",
  reason_code: "crew_as_one", status: "charged", exclusion_ground: null, note: "crew billed as one person",
  created_at: "2026-11-06T12:00:00Z", updated_at: "2026-11-06T12:00:00Z", history: [],
};
const READING = {
  id: "r1", work_order_id: "w", printing_no: 1, work_date: "2026-06-20", hours_as_read: "6.0",
  raw_note: "BT x2 3h", reviewer: null, source: "import abc", created_at: "2026-11-06T12:00:00Z",
};
const BLOCK = {
  id: "b1", work_order_id: "w", version: 3, text: "SMR27 LABOR CORRECTION v3\nline", generated_at: "2026-11-06T12:00:00Z",
  generated_by_name: "JM", pasted_at: null, pasted_by_name: null, lines_digest: "d", stale: false,
};
const KEYED = { id: "e1", technician_id: "t", technician_name: "Pat", minutes: 90 };

async function open({ role = "admin", detail: overrides = {} } = {}) {
  const detail = workOrderDetail({ smr: true, smr_readings: [READING], smr_lines: [LINE], smr_block: BLOCK, ...overrides });
  await mountWorkOrders({ role, cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail] });
  await openCard(0);
  return detail;
}

const section = () => card().querySelector(".wo-smr-section");
const invoice = () => card().querySelector(".wo-smr-invoice");
const entryRow = () => section().querySelector(".wo-smr-add");
const click = (action) => card().querySelector(`[data-action="${action}"]`).click();
const set = (cls, value) => { card().querySelector(`.${cls}`).value = value; };
const detailGets = (id) => requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}`).length;
const expectRefresh = (id) => vi.waitFor(() => expect(detailGets(id)).toBe(1));
const sent = (fragment, method) => vi.waitFor(() => expect(requestFor(fragment, method)).not.toBeNull());

describe("who sees what", () => {
  it("is absent on a live order", async () => {
    await open({ detail: { smr: false, smr_readings: [], smr_lines: [], smr_block: null } });
    expect(section()).toBeNull();
    expect(invoice()).toBeNull();
  });

  it("is the one Labor card, open, with the Invoice section under it and no readings", async () => {
    await open();
    expect([...card().querySelectorAll(".wo-labor-section")]).toEqual([section()]);
    expect(section().querySelector("summary").textContent).toBe("Labor");
    expect(section().open).toBe(true);
    expect(invoice().querySelector("summary").textContent).toBe("Invoice");
    expect(invoice().open).toBe(true);
    expect(card().textContent).not.toContain("Printing 1");
    expect(card().textContent).not.toContain("Paper corrections");
    expect(card().textContent).not.toContain("NetFacilities Record Before Correction");
  });

  it("is read-only below Admin: lines and block status, no buttons, Invoice folded", async () => {
    await open({ role: "supervisor" });
    expect(section().textContent).toContain("Skilled Technician ×2");
    expect(section().querySelector(".wo-smr-line-hours").textContent).toBe("2 × 3.0 h");
    expect(invoice().textContent).toContain("v3 · not yet pasted");
    expect(invoice().open).toBe(false);
    expect(section().querySelector("[data-action], input, .tip-btn")).toBeNull();
    expect(invoice().querySelector("[data-action]")).toBeNull();
  });

  it("an order whose only labor was keyed in the app keeps the original Labor card", async () => {
    await open({ detail: { smr_lines: [], labor: [KEYED] } });
    expect(section()).toBeNull();
    const labor = card().querySelector(".wo-labor-section");
    expect(labor.textContent).toContain("Pat");
    expect(labor.querySelector('[data-action="edit-labor"]')).not.toBeNull();
    expect(card().querySelector('[data-action="smr-add-line"]')).toBeNull();
    expect(invoice()).not.toBeNull();
  });

  it("vendor lines take the card over from entries keyed in the app", async () => {
    await open({ detail: { labor: [KEYED] } });
    expect(section().textContent).not.toContain("Pat");
    expect(card().querySelector('[data-action="edit-labor"]')).toBeNull();
  });

  it("an order with no labor at all gets the empty card and the entry row", async () => {
    await open({ detail: { smr_lines: [] } });
    expect(section().textContent).toContain("No labor recorded yet.");
    expect(section().querySelector(".wo-labor-summary")).toBeNull();
    expect(entryRow()).not.toBeNull();
  });
});

// Ready to invoice: a person's stamp, offered while a line is in invoice
// Weeks 1–7 (the backend's gate), whatever the stage says about materials.
describe("ready to invoice", () => {
  const row = () => card().querySelector(".wo-smr-ready");
  // Week 9 = After W7: outside the invoice period, so no Ready button.
  const AFTER_W7 = { ...LINE, week: 9, work_date: "2026-07-25" };

  it("a needs-review order offers the Ready button, and pressing it PUTs ready and refreshes", async () => {
    const detail = await open({ detail: { smr_stage: "needs_review" } });
    const btn = row().querySelector('[data-action="smr-ready"]');
    expect(btn.textContent).toBe("Ready to invoice");
    expect(row().querySelector('[data-action="smr-not-ready"]')).toBeNull();
    respond("put", "/work-orders/smr/:id/ready", {});
    click("smr-ready");
    await sent("/ready", "PUT");
    expect(requestFor("/ready", "PUT").body).toEqual({ ready: true });
    await expectRefresh(detail.id);
  });

  it("a ready order shows the stamp and a Not ready button that PUTs ready false", async () => {
    await open({ detail: { smr_stage: "ready", smr_ready: { at: "2026-11-08T15:00:00Z", by_name: "JM" } } });
    expect(row().textContent).toMatch(/Ready to invoice · \d\d\/\d\d\/\d\d by JM/);
    expect(row().querySelector('[data-action="smr-not-ready"]').textContent).toBe("Not ready");
    respond("put", "/work-orders/smr/:id/ready", {});
    click("smr-not-ready");
    await sent("/ready", "PUT");
    expect(requestFor("/ready", "PUT").body).toEqual({ ready: false });
  });

  it("a paper-review order offers Mark paper reviewed", async () => {
    await open({ detail: { smr_stage: "paper_review", smr_lines: [AFTER_W7] } });
    expect(row().textContent).toBe("Mark paper reviewed");
    expect(row().querySelector("[data-action]").dataset.action).toBe("smr-paper-reviewed");
  });

  it("a paper-reviewed order shows who and the undo", async () => {
    await open({ detail: { smr_stage: "needs_review", smr_lines: [AFTER_W7], smr_paper_reviewed: { at: "2026-11-13T12:00:00Z", by_name: "Pat" } } });
    expect(row().textContent).toContain("Paper reviewed");
    expect(row().querySelector("[data-action]").dataset.action).toBe("smr-not-paper-reviewed");
  });

  it("a labor-only (material not keyed) order with a Weeks 1–7 line still offers the Ready button", async () => {
    await open({ detail: { smr_stage: "no_material" } });
    expect(row().querySelector('[data-action="smr-ready"]').textContent).toBe("Ready to invoice");
  });

  it("a material-not-keyed order with no Weeks 1–7 line offers no button", async () => {
    await open({ detail: { smr_stage: "no_material", smr_lines: [AFTER_W7] } });
    expect(row().querySelector("[data-action]")).toBeNull();
  });

  it("a ready stamp on an order that lost its Weeks 1–7 line is held, not shown as ready", async () => {
    await open({ detail: { smr_stage: "paper_review", smr_lines: [AFTER_W7], smr_ready: { at: "2026-11-08T15:00:00Z", by_name: "JM" } } });
    expect(row().textContent).toBe("Ready stamp held until a line is in Weeks 1–7");
    expect(row().querySelector("[data-action]")).toBeNull();
  });

  it("below Admin a ready order shows the stamp with no button", async () => {
    await open({ role: "supervisor", detail: { smr_stage: "ready", smr_ready: { at: "2026-11-08T15:00:00Z", by_name: "JM" } } });
    expect(row().textContent).toContain("Ready to invoice");
    expect(row().querySelector("[data-action]")).toBeNull();
  });

  it("below Admin a needs-review order says not yet ready, with no button", async () => {
    await open({ role: "supervisor", detail: { smr_stage: "needs_review" } });
    expect(row().textContent).toBe("Not yet ready to invoice");
    expect(row().querySelector("[data-action]")).toBeNull();
  });
});

describe("total and block status", () => {
  it("prints one total line: the hours and the charge", async () => {
    await open({ detail: { labor_total: "375.00", smr_lines: [LINE, { ...LINE, id: "b", headcount: 1, hours_each: "1.5", hours: "1.5" }] } });
    expect(section().querySelector(".wo-labor-summary").textContent).toBe("Total: 7.5 h$375.00");
    expect(section().querySelector(".wo-smr-stat")).toBeNull();
  });

  it("leaves the charge off for a role that sees no money", async () => {
    await open({ detail: { labor_total: null } });
    expect(section().querySelector(".wo-labor-summary").textContent).toBe("Total: 6.0 h");
  });

  it("words the block line for pasted and stale blocks", async () => {
    const { blockStatusText } = await importView("views/workOrderSmrLines.js");
    expect(blockStatusText(null)).toBe("No correction block yet.");
    expect(blockStatusText({ ...BLOCK, stale: true })).toBe("v3 · not yet pasted · lines changed since v3");
    expect(blockStatusText({ ...BLOCK, pasted_at: "2026-11-10T15:00:00Z", pasted_by_name: "JM" })).toMatch(/^v3 · pasted \d\d\/\d\d\/\d\d by JM$/);
  });
});

describe("lines", () => {
  it("reads like a labor entry: a named hand, a week-placed Skilled Technician and a crew", async () => {
    await open({ detail: { smr_lines: [
      { ...LINE, id: "a", headcount: 1, alias_on_paper: "Pat Doe", work_date: "2026-06-20" },
      { ...LINE, id: "b", headcount: 1, alias_on_paper: null, work_date: null, week: 3 },
      { ...LINE, id: "c", headcount: 3, alias_on_paper: "BT crew", worker_name: null, kind: "staging" },
    ] } });
    const rows = [...section().querySelectorAll(".wo-smr-line")];
    const text = (el) => el.textContent.replace(/\s+/g, " ").trim();
    const box = (el) => el.querySelector(".wo-smr-l-hours");
    expect(text(rows[0])).toContain("Pat Doe 06/20/26 · BT Restoration");
    expect(box(rows[0]).value).toBe("3.0");
    expect(box(rows[0]).getAttribute("aria-label")).toBe("Hours");
    expect(text(rows[1])).toContain("Skilled Technician Week 3 · BT Restoration");
    expect(text(rows[2])).toContain("BT crew ×3Staging 06/20/26 · BT Restoration · hours each");
    expect(box(rows[2]).getAttribute("aria-label")).toBe("Hours each");
    // Labor shows no chip; the other reasons do. The note, status and history are off the card.
    expect(rows[0].querySelector(".wo-smr-line-kind")).toBeNull();
    expect(rows[2].querySelector(".wo-smr-line-kind").textContent).toBe("Staging");
    expect(rows[2].querySelector(".wo-smr-line-kind").classList.contains("wo-smr-line-kind--staging")).toBe(true);
    expect(section().textContent).not.toContain("crew billed as one person");
    expect([...rows[0].querySelectorAll("[data-action]")].map((b) => b.textContent)).toEqual(["Update", "Edit", "Remove"]);
  });

  it("the entry row carries its tips and the vendor of the last line", async () => {
    await open();
    expect([...section().querySelectorAll(".tip-btn")].map((b) => b.dataset.tip))
      .toEqual(["smr.remove", "smr.crew", "smr.vendor", "smr.reason"]);
    expect(entryRow().querySelector(".wo-smr-a-vendor").value).toBe("BT Restoration");
    expect([...entryRow().querySelector(".wo-smr-a-kind").options].map((o) => o.textContent))
      .toEqual(["Labor", "Assessment", "Audit", "Staging", "Material Preparation", "Clean-up"]);
  });

  it("\"smr-add-line\" posts the entry row and refreshes", async () => {
    const detail = await open();
    respond("post", "/work-orders/smr/:id/lines", { ...LINE, id: "l2" });
    set("wo-smr-a-name", "Jesus");
    set("wo-smr-a-headcount", "2");
    set("wo-smr-a-hours", "4");
    set("wo-smr-a-date", "2026-06-22");
    set("wo-smr-a-vendor", "XXL Construction");
    set("wo-smr-a-kind", "clean-up");
    click("smr-add-line");
    await sent("/lines", "POST");
    expect(requestFor("/lines", "POST").body).toEqual({
      work_date: "2026-06-22", vendor: "XXL Construction", alias_on_paper: "Jesus", headcount: 2,
      hours_each: "4", kind: "clean-up", reason_code: "as_read",
    });
    await expectRefresh(detail.id);
  });

  it("refuses an add without hours, then without a date", async () => {
    await open();
    click("smr-add-line");
    await vi.waitFor(() => expect(message().textContent).toBe("Enter the hours each person worked."));
    set("wo-smr-a-hours", "1.5");
    click("smr-add-line");
    await vi.waitFor(() => expect(message().textContent).toBe("Enter the date the work was done."));
    expect(requestFor("/lines", "POST")).toBeNull();
  });

  it("\"smr-update-line\" PATCHes the hours in the row's box and refreshes", async () => {
    const detail = await open();
    respond("patch", "/work-orders/smr/lines/:id", LINE);
    set("wo-smr-l-hours", "3.5");
    click("smr-update-line");
    await sent(`/lines/${LINE.id}`, "PATCH");
    expect(requestFor(`/lines/${LINE.id}`, "PATCH").body).toEqual({ hours_each: "3.5" });
    await expectRefresh(detail.id);
  });

  it("\"smr-edit-line\" loads the line into the entry row and saving PATCHes that line", async () => {
    const detail = await open({ detail: { smr_lines: [{ ...LINE, alias_on_paper: "BT crew", kind: "audit, staging" }] } });
    respond("patch", "/work-orders/smr/lines/:id", LINE);
    click("smr-edit-line");
    const row = entryRow();
    expect(row.dataset.lineId).toBe(LINE.id);
    expect(row.querySelector(".wo-smr-a-name").value).toBe("BT crew");
    expect(row.querySelector(".wo-smr-a-headcount").value).toBe("2");
    expect(row.querySelector(".wo-smr-a-hours").value).toBe("3.0");
    expect(row.querySelector(".wo-smr-a-date").value).toBe("2026-06-20");
    expect(row.querySelector(".wo-smr-a-kind").value).toBe("audit, staging"); // an imported kind survives
    expect(row.querySelector('[data-action="smr-add-line"]').textContent).toBe("Save changes");
    expect(row.querySelector('[data-action="smr-cancel-line"]').hidden).toBe(false);
    set("wo-smr-a-date", "2026-06-21");
    click("smr-add-line");
    await sent(`/lines/${LINE.id}`, "PATCH");
    expect(requestFor(`/lines/${LINE.id}`, "PATCH").body).toEqual({
      work_date: "2026-06-21", vendor: "BT Restoration", alias_on_paper: "BT crew", headcount: 2,
      hours_each: "3.0", kind: "audit, staging",
    });
    expect(requestFor("/lines", "POST")).toBeNull();
    await expectRefresh(detail.id);
  });

  it("\"smr-cancel-line\" puts the entry row back to add", async () => {
    await open();
    click("smr-edit-line");
    click("smr-cancel-line");
    const row = entryRow();
    expect(row.dataset.lineId).toBe("");
    expect(row.querySelector(".wo-smr-a-hours").value).toBe("");
    expect(row.querySelector(".wo-smr-a-headcount").value).toBe("1");
    expect(row.querySelector('[data-action="smr-add-line"]').textContent).toBe("Add labor");
    expect(row.querySelector('[data-action="smr-cancel-line"]').hidden).toBe(true);
  });

  it("\"smr-delete-line\" asks first; No sends nothing, Yes DELETEs the line and refreshes", async () => {
    const detail = await open();
    click("smr-delete-line");
    await answerConfirm(false);
    expect(requestFor(`/lines/${LINE.id}`, "DELETE")).toBeNull();
    respond("delete", "/work-orders/smr/lines/:id", null);
    click("smr-delete-line");
    await answerConfirm(true);
    await sent(`/lines/${LINE.id}`, "DELETE");
    expect(requestFor(`/lines/${LINE.id}`, "PATCH")).toBeNull();
    await expectRefresh(detail.id);
  });
});

describe("the correction block", () => {
  it("\"smr-generate-block\" posts and refreshes; the text sits in the copy box", async () => {
    const detail = await open();
    expect(invoice().querySelector(".wo-smr-block-text").value).toBe(BLOCK.text);
    respond("post", "/work-orders/smr/:id/block", { ...BLOCK, version: 4 });
    set("wo-smr-description-text", "Patched drywall.");
    click("smr-generate-block");
    await sent("/block", "POST");
    expect(requestFor("/block", "POST").url).toBe(`/work-orders/smr/${detail.id}/block`);
    expect(requestFor("/block", "POST").body).toEqual({ description: "Patched drywall." });
    await expectRefresh(detail.id);
  });

  it("\"smr-print-block\" prints the block text alone and cleans up", async () => {
    await open();
    let seen = null;
    window.print = () => { seen = [document.body.classList.contains("smr-printing"), document.querySelector(".smr-print-sheet").textContent]; };
    click("smr-print-block");
    expect(seen).toEqual([true, BLOCK.text]);
    expect(document.body.classList.contains("smr-printing")).toBe(false);
    expect(document.querySelector(".smr-print-sheet")).toBeNull();
  });

  it("\"smr-mark-pasted\" posts the block id and refreshes", async () => {
    const detail = await open();
    respond("post", "/work-orders/smr/blocks/:id/pasted", { ...BLOCK, pasted_at: "2026-11-10T15:00:00Z" });
    click("smr-mark-pasted");
    await sent("/blocks/b1/pasted", "POST");
    await expectRefresh(detail.id);
  });

  it("a pasted block offers no second stamp", async () => {
    await open({ detail: { smr_block: { ...BLOCK, pasted_at: "2026-11-10T15:00:00Z", pasted_by_name: "JM" } } });
    expect(invoice().querySelector('[data-action="smr-mark-pasted"]')).toBeNull();
    expect(invoice().textContent).toContain("by JM");
  });
});

describe("vocabulary", () => {
  it("every vendor and kind is still in the domain module", async () => {
    const mod = await importView("views/workOrderSmrLines.js");
    const domain = readFileSync("backend/app/domain/work_orders_smr_lines.py", "utf8");
    const missing = [...mod.SMR_VENDORS, ...mod.SMR_KINDS].filter((v) => !domain.includes(`"${v}"`));
    expect(missing).toEqual([]);
  });
});
