// The Paper corrections section (spec 2026-11-04, Editor): its `smr-*`
// actions in workOrderSmrActions.js, the read-only view below Admin, the
// totals and block status lines, and the vocabulary mirror of the domain.

import { readFileSync } from "node:fs";
import { describe, expect, it, vi } from "vitest";
import {
  card, message, mountWorkOrders, openCard, requestFor, requests, respond,
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

async function open({ role = "admin", detail: overrides = {} } = {}) {
  const detail = workOrderDetail({ smr: true, smr_readings: [READING], smr_lines: [LINE], smr_block: BLOCK, ...overrides });
  await mountWorkOrders({ role, cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail] });
  await openCard(0);
  return detail;
}

const section = () => card().querySelector(".wo-smr-section");
const form = () => section().querySelector(".wo-smr-line-form");
const click = (action) => card().querySelector(`[data-action="${action}"]`).click();
const set = (cls, value) => { section().querySelector(`.${cls}`).value = value; };
const detailGets = (id) => requests().filter((r) => r.method === "GET" && r.url === `/work-orders/${id}`).length;
const expectRefresh = (id) => vi.waitFor(() => expect(detailGets(id)).toBe(1));
const sent = (fragment, method) => vi.waitFor(() => expect(requestFor(fragment, method)).not.toBeNull());

describe("who sees what", () => {
  it("is absent on a live order", async () => {
    await open({ detail: { smr: false, smr_readings: [], smr_lines: [], smr_block: null } });
    expect(section()).toBeNull();
  });

  it("is read-only below Admin: readings, lines and block status, no buttons", async () => {
    await open({ role: "supervisor" });
    expect(section().textContent).toContain("Printing 1");
    expect(section().textContent).toContain("Skilled Technician ×2");
    expect(section().textContent).toContain("v3 · not yet pasted");
    expect(section().querySelector("[data-action]")).toBeNull();
  });

  it("retitles Labor as the NetFacilities record once lines exist, with no labor controls", async () => {
    await open({ detail: { labor: [{ id: "e1", technician_id: "t", technician_name: "Pat", minutes: 90 }] } });
    const labor = card().querySelector(".wo-labor-section");
    expect(labor.textContent).toContain("NetFacilities Record Before Correction");
    expect(labor.textContent).toContain("Pat");
    expect(labor.querySelector('[data-action="add-labor"], [data-action="edit-labor"], [data-action="add-skilled-labor"]')).toBeNull();
  });
});

// Ready for invoice (spec 2026-11-06-smr-paper-stage): a person's stamp,
// offered only once a line is dated.
describe("ready for invoice", () => {
  const row = () => card().querySelector(".wo-smr-ready");

  it("a dated order offers the Ready button, and pressing it PUTs ready and refreshes", async () => {
    const detail = await open({ detail: { smr_stage: "dated" } });
    const btn = row().querySelector('[data-action="smr-ready"]');
    expect(btn.textContent).toBe("Ready for invoice");
    expect(row().querySelector('[data-action="smr-not-ready"]')).toBeNull();
    respond("put", "/work-orders/smr/:id/ready", {});
    click("smr-ready");
    await sent("/ready", "PUT");
    expect(requestFor("/ready", "PUT").body).toEqual({ ready: true });
    await expectRefresh(detail.id);
  });

  it("a ready order shows the stamp and a Not ready button that PUTs ready false", async () => {
    await open({ detail: { smr_stage: "ready", smr_ready: { at: "2026-11-08T15:00:00Z", by_name: "JM" } } });
    expect(row().textContent).toMatch(/Ready for invoice · \d\d\/\d\d\/\d\d by JM/);
    expect(row().querySelector('[data-action="smr-not-ready"]').textContent).toBe("Not ready");
    respond("put", "/work-orders/smr/:id/ready", {});
    click("smr-not-ready");
    await sent("/ready", "PUT");
    expect(requestFor("/ready", "PUT").body).toEqual({ ready: false });
  });

  it("an undated order says to date a line first, with no button", async () => {
    await open({ detail: { smr_stage: "undated" } });
    expect(row().textContent).toBe("Date a line to mark ready");
    expect(row().querySelector("[data-action]")).toBeNull();
    expect(row().classList.contains("hint")).toBe(true);
  });

  it("a ready stamp on an order that lost its date is held, not shown as ready", async () => {
    await open({ detail: { smr_stage: "undated", smr_ready: { at: "2026-11-08T15:00:00Z", by_name: "JM" } } });
    expect(row().textContent).toBe("Ready stamp held until a line is dated");
    expect(row().querySelector("[data-action]")).toBeNull();
  });

  it("below Admin a ready order shows the stamp with no button", async () => {
    await open({ role: "supervisor", detail: { smr_stage: "ready", smr_ready: { at: "2026-11-08T15:00:00Z", by_name: "JM" } } });
    expect(row().textContent).toContain("Ready for invoice");
    expect(row().querySelector("[data-action]")).toBeNull();
  });

  it("below Admin a dated order says not yet ready, with no button", async () => {
    await open({ role: "supervisor", detail: { smr_stage: "dated" } });
    expect(row().textContent).toBe("Not yet ready for invoice");
    expect(row().querySelector("[data-action]")).toBeNull();
  });

  it("the NetFacilities record renders collapsed once the paper is read", async () => {
    await open({ detail: { smr_lines: [], labor: [{ id: "e1", technician_id: "t", technician_name: "Pat", minutes: 90 }] } });
    const labor = card().querySelector(".wo-labor-section");
    expect(labor.textContent).toContain("NetFacilities Record Before Correction");
    expect(labor.open).toBe(false);
  });
});

describe("totals and block status", () => {
  it("prints billed, corrected, change and the charge", async () => {
    await open({ detail: { smr_legacy_labor_minutes: 120, labor_total: "375.00" } });
    const tiles = [...section().querySelectorAll(".wo-smr-stat")].map((t) => t.textContent.replace(/\s+/g, " ").trim());
    expect(tiles).toEqual(["Billed (NetFacilities)2.0 h", "Corrected6.0 h", "Change+4.0 h", "Charge$375.00"]);
    expect(section().querySelector(".wo-smr-stat--up")).not.toBeNull();
    expect(section().querySelector(".wo-smr-totals").getAttribute("aria-label"))
      .toBe("Billed (NetFacilities) 2.0 h · Corrected 6.0 h · Change +4.0 h · $375.00");
  });

  it("words the block line for pasted and stale blocks", async () => {
    const { blockStatusText } = await importView("views/workOrderSmrLines.js");
    expect(blockStatusText(null)).toBe("No correction block yet.");
    expect(blockStatusText({ ...BLOCK, stale: true })).toBe("v3 · not yet pasted · lines changed since v3");
    expect(blockStatusText({ ...BLOCK, pasted_at: "2026-11-10T15:00:00Z", pasted_by_name: "JM" })).toMatch(/^v3 · pasted \d\d\/\d\d\/\d\d by JM$/);
  });
});

describe("readings", () => {
  it("\"smr-add-reading\" posts the printing and refreshes", async () => {
    const detail = await open();
    respond("post", "/work-orders/smr/:id/readings", { ...READING, id: "r2", printing_no: 2 });
    set("wo-smr-r-printing", "2");
    set("wo-smr-r-date", "2026-07-01");
    set("wo-smr-r-hours", "1.5");
    set("wo-smr-r-note", "typed from paper");
    click("smr-add-reading");
    await sent("/readings", "POST");
    expect(requestFor("/readings", "POST").body).toEqual({ printing_no: 2, work_date: "2026-07-01", hours_as_read: "1.5", raw_note: "typed from paper" });
    await expectRefresh(detail.id);
  });

  it("\"smr-edit-reading\" fills the reading form and saving PATCHes that reading", async () => {
    const detail = await open();
    respond("patch", "/work-orders/smr/readings/:id", { ...READING, hours_as_read: "4.0" });
    click("smr-edit-reading");
    const f = section().querySelector(".wo-smr-reading-form");
    expect(f.dataset.readingId).toBe("r1");
    expect(f.querySelector(".wo-smr-r-printing").value).toBe("1");
    expect(f.querySelector(".wo-smr-r-hours").value).toBe("6.0");
    expect(f.querySelector('[data-action="smr-add-reading"]').textContent).toBe("Save reading");
    expect(f.querySelector('[data-action="smr-cancel-reading"]').hidden).toBe(false);
    set("wo-smr-r-hours", "4");
    click("smr-add-reading");
    await sent("/readings/r1", "PATCH");
    expect(requestFor("/readings/r1", "PATCH").body).toEqual({ printing_no: 1, work_date: "2026-06-20", hours_as_read: "4", raw_note: "BT x2 3h" });
    expect(requestFor("/readings", "POST")).toBeNull();
    await expectRefresh(detail.id);
  });

  it("\"smr-cancel-reading\" blanks the form back to add", async () => {
    await open();
    click("smr-edit-reading");
    click("smr-cancel-reading");
    const f = section().querySelector(".wo-smr-reading-form");
    expect(f.dataset.readingId).toBe("");
    expect(f.querySelector(".wo-smr-r-printing").value).toBe("");
    expect(f.querySelector('[data-action="smr-add-reading"]').textContent).toBe("Add reading");
    expect(f.querySelector('[data-action="smr-cancel-reading"]').hidden).toBe(true);
  });

  it("refuses a blank printing number without a request", async () => {
    await open();
    click("smr-add-reading");
    await vi.waitFor(() => expect(message().textContent).toBe("Enter the printing number from the paper."));
    expect(requestFor("/readings", "POST")).toBeNull();
  });
});

describe("lines", () => {
  it("reads like a labor entry: a named hand, a Skilled Technician and a crew", async () => {
    await open({ detail: { smr_lines: [
      { ...LINE, id: "a", headcount: 1, alias_on_paper: "Pat Doe", work_date: "2026-06-20", status: "charged" },
      { ...LINE, id: "b", headcount: 1, alias_on_paper: null, work_date: null, week: null, status: "excluded", exclusion_ground: "undated" },
      { ...LINE, id: "c", headcount: 3, alias_on_paper: "BT crew", worker_name: null, kind: "staging" },
    ] } });
    const rows = [...section().querySelectorAll(".wo-smr-line")];
    const text = (el) => el.textContent.replace(/\s+/g, " ").trim();
    const hours = (el) => el.querySelector(".wo-smr-line-hours").textContent;
    expect(text(rows[0])).toContain("Pat Doe 06/20/26 · BT Restoration");
    expect(hours(rows[0])).toBe("3.0 h");
    expect(text(rows[1])).toContain("Skilled Technician undated · BT Restoration");
    expect(text(rows[1])).toContain("excluded: undated");
    expect(text(rows[2])).toContain("BT crew ×3Staging 06/20/26");
    expect(hours(rows[2])).toBe("3 × 3.0 h");
    // The note sits behind a closed toggle; audit/staging show as a chip, field does not.
    const note = rows[0].querySelector("details.wo-smr-line-note");
    expect(note.open).toBe(false);
    expect(note.querySelector("p").textContent).toBe("crew billed as one person");
    expect(rows[0].querySelector(".wo-smr-line-kind")).toBeNull();
    expect(rows[2].querySelector(".wo-smr-line-kind").textContent).toBe("Staging");
    expect(rows[2].querySelector(".wo-smr-line-kind").classList.contains("wo-smr-line-kind--staging")).toBe(true);
    expect(section().querySelector("table")).toBeNull();
  });

  it("\"smr-add-line\" posts the add row as a charged field line and refreshes", async () => {
    const detail = await open();
    respond("post", "/work-orders/smr/:id/lines", { ...LINE, id: "l2" });
    // The vendor select defaults to the last line's vendor.
    expect(section().querySelector(".wo-smr-a-vendor").value).toBe("BT Restoration");
    set("wo-smr-a-name", "Jesus");
    set("wo-smr-a-headcount", "2");
    set("wo-smr-a-hours", "4");
    set("wo-smr-a-date", "2026-06-22");
    set("wo-smr-a-vendor", "XXL Construction");
    expect([...section().querySelector(".wo-smr-a-kind").options].map((o) => o.textContent))
      .toEqual(["Labor", "Assessment", "Audit", "Staging", "Material Preparation", "Clean-up"]);
    set("wo-smr-a-kind", "clean-up");
    click("smr-add-line");
    await sent("/lines", "POST");
    expect(requestFor("/lines", "POST").body).toEqual({
      reading_id: null, work_date: "2026-06-22", date_basis: "paper", vendor: "XXL Construction", worker_id: null,
      alias_on_paper: "Jesus", headcount: 2, hours_each: "4", kind: "clean-up", reason_code: "as_read",
      status: "charged", exclusion_ground: null, note: null, reason: "keyed from the paper",
    });
    await expectRefresh(detail.id);
  });

  it("an undated add waits as excluded: undated", async () => {
    await open();
    respond("post", "/work-orders/smr/:id/lines", { ...LINE, id: "l2" });
    set("wo-smr-a-hours", "1.5");
    click("smr-add-line");
    await sent("/lines", "POST");
    expect(requestFor("/lines", "POST").body).toMatchObject({ alias_on_paper: null, status: "excluded", exclusion_ground: "undated" });
  });

  it("refuses an add without hours", async () => {
    await open();
    click("smr-add-line");
    await vi.waitFor(() => expect(message().textContent).toBe("Enter the hours each person worked."));
    expect(requestFor("/lines", "POST")).toBeNull();
  });

  it("\"smr-cancel-line\" hides the edit form", async () => {
    await open();
    expect(form().hidden).toBe(true);
    click("smr-edit-line");
    expect(form().hidden).toBe(false);
    click("smr-cancel-line");
    expect(form().hidden).toBe(true);
  });

  it("\"smr-edit-line\" fills the form from the row and saving PATCHes that line", async () => {
    await open();
    respond("patch", "/work-orders/smr/lines/:id", LINE);
    click("smr-edit-line");
    expect(form().dataset.lineId).toBe(LINE.id);
    expect(form().querySelector(".wo-smr-f-hours").value).toBe("3.0");
    expect(form().querySelector(".wo-smr-f-headcount").value).toBe("2");
    set("wo-smr-f-hours", "3.5");
    set("wo-smr-f-reason", "misread");
    click("smr-save-line");
    await sent(`/lines/${LINE.id}`, "PATCH");
    const body = requestFor(`/lines/${LINE.id}`, "PATCH").body;
    expect(body).toMatchObject({ hours_each: "3.5", reason: "misread" });
    expect(body).not.toHaveProperty("worker_id"); // the server links the keyed name
  });

  it("\"smr-exclude-line\" PATCHes the line excluded in one tap, no ground", async () => {
    const detail = await open();
    respond("patch", "/work-orders/smr/lines/:id", { ...LINE, status: "excluded" });
    click("smr-exclude-line");
    await sent(`/lines/${LINE.id}`, "PATCH");
    expect(requestFor(`/lines/${LINE.id}`, "PATCH").body).toEqual({ status: "excluded", reason: "excluded on the card" });
    expect(form().hidden).toBe(true);
    await expectRefresh(detail.id);
  });

  it("\"smr-charge-line\" on an excluded line PATCHes it charged and clears the ground", async () => {
    await open({ detail: { smr_lines: [{ ...LINE, status: "excluded", exclusion_ground: "undated" }] } });
    respond("patch", "/work-orders/smr/lines/:id", LINE);
    expect(section().querySelector('[data-action="smr-exclude-line"]')).toBeNull();
    click("smr-charge-line");
    await sent(`/lines/${LINE.id}`, "PATCH");
    expect(requestFor(`/lines/${LINE.id}`, "PATCH").body).toEqual({ status: "charged", exclusion_ground: null, reason: "charged on the card" });
  });

  it("refuses to save without a reason", async () => {
    await open();
    click("smr-edit-line");
    set("wo-smr-f-hours", "1");
    click("smr-save-line");
    await vi.waitFor(() => expect(message().textContent).toBe("Say why: the reason is kept with the line."));
    expect(requestFor("/lines", "POST")).toBeNull();
  });
});

describe("the correction block", () => {
  it("\"smr-generate-block\" posts and refreshes; the text sits in the copy box", async () => {
    const detail = await open();
    expect(section().querySelector(".wo-smr-block-text").value).toBe(BLOCK.text);
    respond("post", "/work-orders/smr/:id/block", { ...BLOCK, version: 4 });
    click("smr-generate-block");
    await sent("/block", "POST");
    expect(requestFor("/block", "POST").url).toBe(`/work-orders/smr/${detail.id}/block`);
    await expectRefresh(detail.id);
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
    expect(section().querySelector('[data-action="smr-mark-pasted"]')).toBeNull();
    expect(section().textContent).toContain("by JM");
  });
});

describe("vocabulary", () => {
  it("every vendor, kind, basis, ground and reason code is still in the domain module", async () => {
    const mod = await importView("views/workOrderSmrLines.js");
    const domain = readFileSync("backend/app/domain/work_orders_smr_lines.py", "utf8");
    const all = [...mod.SMR_VENDORS, ...mod.SMR_KINDS, ...mod.SMR_DATE_BASES, ...mod.SMR_GROUNDS, ...mod.SMR_REASON_CODES];
    const missing = all.filter((v) => !domain.includes(`"${v}"`));
    expect(missing).toEqual([]);
  });
});
