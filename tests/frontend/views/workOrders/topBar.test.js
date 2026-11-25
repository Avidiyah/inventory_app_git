// The card's pinned header and top icon bar (Takeoff spec, "Work-order top bar").

import { describe, expect, it } from "vitest";
import { card, mountWorkOrders, openCard } from "../../helpers/workOrders.js";
import { workOrderCard, workOrderDetail, workOrderItem } from "../../helpers/factories.js";

async function open(overrides = {}, role = "supervisor", extra = {}) {
  const detail = workOrderDetail(overrides);
  await mountWorkOrders({
    role,
    ...extra,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
    details: [detail],
  });
  await openCard(0);
  return { cardEl: card(), body: card().querySelector(".wo-body") };
}

const SMR_LINE = {
  id: "11111111-1111-4111-8111-111111111111", work_order_id: "w", reading_id: null, import_key: null,
  work_date: "2026-06-20", date_basis: "paper", week: 4, vendor: "BT Restoration", worker_id: null,
  worker_name: null, alias_on_paper: null, headcount: 1, hours_each: "3.0", hours: "3.0", kind: "field",
  reason_code: null, status: "charged", exclusion_ground: null, note: null,
  created_at: "2026-11-06T12:00:00Z", updated_at: "2026-11-06T12:00:00Z", history: [],
};
const bar = (body) => body.querySelector(".wo-pin .wo-topbar");
const keys = (root) => [...root.querySelectorAll(".wo-tab")].map((t) => t.dataset.woTab);

describe("the work-order top bar", () => {
  it("pin shows task and location", async () => {
    const { body } = await open({
      description: "Replace toilet", community: "Scholars", building_number: "4", unit_number: "212", number: "5001",
    });
    const pin = body.querySelector(":scope > .wo-pin");
    expect(pin.id).toBe("wo-sec-pin");
    expect(body.firstElementChild).toBe(pin);
    expect(pin.querySelector(".wo-pin-task").textContent).toBe("Replace toilet");
    expect(pin.querySelector(".wo-pin-place").textContent).toBe("Scholars · Bldg 4 · Unit 212");
    expect(pin.querySelector(".wo-pin-chips").textContent).toContain("WO 5001");
  });

  it("pin hints when the order has no task", async () => {
    const { body } = await open({ description: "" });
    expect(body.querySelector(".wo-pin-task").textContent).toBe("No task on this work order");
  });

  it("bar lists materials, labor, notes, photos then More", async () => {
    const { body } = await open({ items: [workOrderItem()] });
    const topbar = bar(body);
    const direct = [...topbar.children].map((el) => el.dataset.woTab ?? el.className);
    expect(direct).toEqual(["materials", "labor", "notes", "photos", "wo-more"]);
    const materials = topbar.querySelector('[data-wo-tab="materials"]');
    expect(materials.querySelector("svg")).not.toBeNull();
    expect(materials.querySelector("small").textContent).toBe("1");
  });

  it("labor hidden for an off-crew technician leaves four", async () => {
    const { body } = await open({ assigned_to_ids: [], assigned_to_names: [] }, "technician");
    expect([...bar(body).children].filter((el) => el.matches(".wo-tab")).map((t) => t.dataset.woTab))
      .toEqual(["materials", "notes", "photos"]);
    expect(bar(body).children).toHaveLength(4);
  });

  it("card opens on Materials", async () => {
    const { body } = await open();
    expect(body.dataset.woTab).toBe("materials");
    expect(body.querySelector(".wo-materials-section").open).toBe(true);
    expect(bar(body).querySelector('[data-wo-tab="materials"]').getAttribute("aria-selected")).toBe("true");
  });

  it("unread prior-work notes open Notes instead", async () => {
    const { body } = await open({
      notes: "Ann Lee began work", prior_work: { by: ["Ann Lee"], last_at: "2026-10-14T15:05:00Z" },
    });
    expect(body.dataset.woTab).toBe("notes");
    expect(body.querySelector(".wo-materials-section").open).toBe(false);
  });

  it("More lists Details and Invoice for an order with an invoice", async () => {
    const { body } = await open({ smr: true, entry_mode: "retroactive", smr_lines: [SMR_LINE] }, "admin", { smr: true });
    expect(keys(body.querySelector(".wo-more-menu"))).toEqual(["details", "takeoff", "invoice"]);
  });

  it("More lists Details and Takeoff for a Team Lead on an order without an invoice", async () => {
    const { body } = await open();
    expect(keys(body.querySelector(".wo-more-menu"))).toEqual(["details", "takeoff"]);
  });

  it("More lists only Details for a technician on an order with no takeoff", async () => {
    const { body } = await open({}, "technician");
    expect(keys(body.querySelector(".wo-more-menu"))).toEqual(["details"]);
  });

  it("picking Details from More closes all sections and marks More current", async () => {
    const { body } = await open();
    const more = body.querySelector("details.wo-more");
    more.open = true;
    more.querySelector('[data-wo-tab="details"]').click();
    expect(body.dataset.woTab).toBe("details");
    expect([...body.querySelectorAll(":scope > .wo-section-card")].some((s) => s.open)).toBe(false);
    expect(more.open).toBe(false);
    expect(more.classList.contains("wo-more-active")).toBe(true);
    expect(more.querySelector("summary small").textContent).toBe("Details");
    bar(body).querySelector('[data-wo-tab="notes"]').click();
    expect(more.classList.contains("wo-more-active")).toBe(false);
    expect(more.querySelector("summary small").textContent).toBe("");
  });

  it("exactly one .wo-more per card", async () => {
    const { cardEl } = await open({}, "admin");
    expect(cardEl.querySelectorAll(".wo-more")).toHaveLength(1);
  });
});
