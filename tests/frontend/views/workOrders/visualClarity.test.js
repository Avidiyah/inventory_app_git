// The Work Orders visual clarity pass (docs/superpowers/specs/
// 2026-09-27-work-orders-visual-clarity-design.md): status glyphs, quiet
// routine priority, the Overdue tag, one primary action per state, the
// charging strip, and the applied-filter chips + result count.

import { describe, expect, it, vi } from "vitest";
import {
  card, cardEls, listEl, mountWorkOrders, openCard, requests,
} from "../../helpers/workOrders.js";
import { filterOptions, workOrderCard, workOrderDetail } from "../../helpers/factories.js";

const el = (id) => document.getElementById(id);

const change = (control, value) => {
  control.value = value;
  control.dispatchEvent(new Event("change", { bubbles: true }));
};

async function renderOne(overrides) {
  await mountWorkOrders({ role: "admin", cards: [workOrderCard(overrides)] });
  return cardEls()[0];
}

function isoDay(offsetDays) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  const pad = (n) => String(n).padStart(2, "0");
  return `${d.getFullYear()}-${pad(d.getMonth() + 1)}-${pad(d.getDate())}`;
}

function slashDay(offsetDays) {
  const d = new Date();
  d.setDate(d.getDate() + offsetDays);
  return `${d.getMonth() + 1}/${d.getDate()}/${d.getFullYear()}`;
}

describe("C1 status pill", () => {
  it.each([
    "created", "assigned", "in_progress", "on_hold", "ready_to_complete", "completed", "review",
  ])("%s carries an aria-hidden glyph ahead of its label", async (status) => {
    const row = await renderOne({ status });
    const glyph = row.querySelector(".wo-status > svg.wo-glyph");
    expect(glyph).not.toBeNull();
    expect(glyph.getAttribute("aria-hidden")).toBe("true");
  });
});

describe("C2 priority tag", () => {
  it.each(["Emergency", "Urgent", "High"])("%s is filled with a warning glyph", async (priority) => {
    const row = await renderOne({ priority, status: "assigned" });
    expect(row.querySelector(".wo-priority svg.wo-glyph")).not.toBeNull();
    expect(row.querySelector(".wo-priority").textContent).toBe(priority);
  });

  it.each(["Normal", "Low", "Whenever", null])("%s is a quiet outline with no glyph", async (priority) => {
    const row = await renderOne({ priority, status: "assigned" });
    expect(row.querySelector(".wo-priority svg")).toBeNull();
  });
});

describe("C3 Overdue tag", () => {
  it.each([
    ["yesterday, ISO", isoDay(-1), "in_progress"],
    ["last week, vendor M/D/YYYY with a time", `${slashDay(-7)} 8:00 AM`, "assigned"],
    ["yesterday, On-Hold", isoDay(-1), "on_hold"],
  ])("shows for %s", async (_label, schedule_date, status) => {
    const row = await renderOne({ schedule_date, status });
    const tag = row.querySelector(".wo-tag-overdue");
    expect(tag?.textContent).toBe("Overdue");
    // After the priority tag.
    expect(tag.previousElementSibling.classList.contains("wo-priority")).toBe(true);
  });

  it.each([
    ["today", isoDay(0), "in_progress"],
    ["tomorrow", isoDay(1), "in_progress"],
    ["blank", null, "in_progress"],
    ["unparseable", "ASAP", "in_progress"],
    ["an impossible date", "2/31/2020", "in_progress"],
    ["Completed", isoDay(-3), "completed"],
    ["Review", isoDay(-3), "review"],
  ])("does not show for %s", async (_label, schedule_date, status) => {
    const row = await renderOne({ schedule_date, status });
    expect(row.querySelector(".wo-tag-overdue")).toBeNull();
  });

  it("follows the detail repaint", async () => {
    const detail = workOrderDetail({ status: "in_progress", schedule_date: isoDay(-2) });
    await mountWorkOrders({
      role: "admin",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "in_progress", schedule_date: null })],
      details: [detail],
    });
    expect(card().querySelector(".wo-tag-overdue")).toBeNull();
    await openCard(0);
    expect(card().querySelectorAll(".wo-tag-overdue")).toHaveLength(1);
    expect(card().querySelector(".wo-status > svg.wo-glyph")).not.toBeNull();
  });
});

// Mount one card for `role`, the signed-in user assigned or not, optionally
// with their clock running, and open it.
async function renderCell({ role, status, assigned = true, tracking = false }) {
  const detail = workOrderDetail({ status, supervisor_id: null });
  await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status })],
    details: [detail],
  });
  const state = await import("../../../../backend/static/state.js");
  const me = state.getCurrentUser().id;
  detail.assigned_to_ids = assigned ? [me] : [];
  detail.assigned_to_names = assigned ? ["Me"] : [];
  detail.active_labor_session = tracking
    ? { id: "s1", technician_id: me, started_at: "2026-09-10T14:14:00Z" }
    : null;
  await openCard(0);
  return card();
}

const primaries = (cardEl) =>
  Array.from(cardEl.querySelectorAll(".wo-controls > button"))
    .filter((b) => !b.classList.contains("secondary-btn") && !b.classList.contains("btn-danger"));
const secondaries = (cardEl) =>
  Array.from(cardEl.querySelectorAll(".wo-controls > button.secondary-btn")).map((b) => b.dataset.action);

describe("C4 one primary action per state", () => {
  it.each([
    ["created", "technician", false, "start-tracking-wo", []],
    ["assigned", "supervisor", false, "start-tracking-wo", []],
    ["in_progress", "technician", false, "start-tracking-wo", ["hold-assigned-wo"]],
    ["in_progress", "supervisor", false, "start-tracking-wo", ["hold-assigned-wo", "complete-wo"]],
    ["in_progress", "technician", true, "notify-supervisor-wo", ["stop-tracking-wo", "hold-assigned-wo"]],
    ["in_progress", "supervisor", true, "complete-wo", ["stop-tracking-wo", "hold-assigned-wo"]],
    ["on_hold", "supervisor", false, "start-tracking-wo", ["resume-assigned-wo", "complete-wo"]],
    ["ready_to_complete", "supervisor", false, "complete-wo", ["send-back-wo"]],
  ])("%s, %s, charging=%s -> %s", async (status, role, tracking, primary, secondary) => {
    const cardEl = await renderCell({ role, status, tracking });
    const filled = primaries(cardEl);
    expect(filled.map((b) => b.dataset.action)).toEqual([primary]);
    expect(secondaries(cardEl)).toEqual(secondary);
  });

  it("Completed: Send to Review is primary for an unassigned Admin, Reopen secondary", async () => {
    const cardEl = await renderCell({ role: "admin", status: "completed", assigned: false });
    expect(primaries(cardEl).map((b) => b.dataset.action)).toEqual(["review-wo"]);
    expect(secondaries(cardEl)).toEqual(["reopen-wo"]);
  });

  it("Completed: the TechFM OA keeps the disabled Send to Review with its reason", async () => {
    const cardEl = await renderCell({ role: "techfm_oa", status: "completed", assigned: false });
    const [btn] = primaries(cardEl);
    expect(btn.dataset.action).toBe("review-wo");
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe("An Admin or the Owner must send this to Review.");
  });

  it("Review: no filled button, label stays, Reopen secondary", async () => {
    const cardEl = await renderCell({ role: "supervisor", status: "review" });
    expect(primaries(cardEl)).toHaveLength(0);
    expect(cardEl.querySelector(".wo-review-ready").textContent).toBe("Ready for Admin Review");
    expect(secondaries(cardEl)).toEqual(["reopen-wo"]);
  });

  it("puts Netfacilities and Archive in a trailing tools group for Admin+", async () => {
    const admin = await renderCell({ role: "admin", status: "in_progress" });
    const tools = admin.querySelector(".wo-controls > .wo-controls-tools");
    expect(tools.parentElement.lastElementChild).toBe(tools);
    expect(Array.from(tools.querySelectorAll("button"), (b) => b.dataset.action))
      .toEqual(["open-netfacilities-wo", "archive-wo"]);
    expect(tools.querySelector('[data-action="open-netfacilities-wo"]').classList.contains("secondary-btn")).toBe(true);
    expect(tools.querySelector('[data-action="archive-wo"]').className).toBe("btn-danger");
  });

  it("gives a Supervisor no tools group", async () => {
    const sup = await renderCell({ role: "supervisor", status: "in_progress" });
    expect(sup.querySelector(".wo-controls-tools")).toBeNull();
  });

  it("keeps the entry-mode selector first in the row", async () => {
    const cardEl = await renderCell({ role: "supervisor", status: "in_progress" });
    expect(cardEl.querySelector(".wo-controls").firstElementChild.classList.contains("wo-mode-row")).toBe(true);
  });
});

describe("C5 charging strip", () => {
  it("sits directly above the controls while my clock runs", async () => {
    const cardEl = await renderCell({ role: "technician", status: "in_progress", tracking: true });
    const strip = cardEl.querySelector(".wo-charging-strip");
    const expected = new Date("2026-09-10T14:14:00Z").toLocaleTimeString([], { hour: "numeric", minute: "2-digit" });
    expect(strip.textContent).toBe(`Charging since ${expected}`);
    expect(strip.nextElementSibling.classList.contains("wo-controls")).toBe(true);
  });

  it("is absent with no running session", async () => {
    const cardEl = await renderCell({ role: "technician", status: "in_progress" });
    expect(cardEl.querySelector(".wo-charging-strip")).toBeNull();
  });
});

describe("C6 applied-filter chips and result count", () => {
  const chips = () => Array.from(el("work-orders-filter-chips").querySelectorAll(".wo-filter-chip"));
  const count = () => el("work-orders-result-count");
  const listLoads = () => requests().filter((r) => r.url.startsWith("/work-orders/?") || r.url === "/work-orders/");

  it("shows no chips and a plain count on an unfiltered browse", async () => {
    await mountWorkOrders({ role: "admin", cards: [workOrderCard(), workOrderCard(), workOrderCard()] });
    expect(el("work-orders-filter-chips").hidden).toBe(true);
    expect(count().textContent).toBe("Showing 3 work orders");
  });

  it("says 'the N most recent' when the browse is capped", async () => {
    const cards = Array.from({ length: 10 }, () => workOrderCard());
    await mountWorkOrders({ role: "admin", cards });
    expect(count().textContent).toBe("Showing the 10 most recent");
  });

  it("renders a chip per filter, with the status glyph swatch and an aria-label", async () => {
    await mountWorkOrders({ role: "admin", cards: [workOrderCard()] });
    change(el("work-orders-status-filter"), "on_hold");
    await vi.waitFor(() => expect(chips()).toHaveLength(1));
    const [chip] = chips();
    expect(chip.tagName).toBe("BUTTON");
    expect(chip.textContent).toContain("Status: On-Hold");
    expect(chip.getAttribute("aria-label")).toBe("Remove filter Status: On-Hold");
    expect(chip.querySelector(".wo-filter-chip-swatch.wo-status-on_hold svg.wo-glyph")).not.toBeNull();
  });

  it("uses option text for selects and quotes keyword searches", async () => {
    await mountWorkOrders({
      role: "admin",
      cards: [workOrderCard()],
      filterOptions: filterOptions({ supervisors: [{ id: "s1", name: "Sue S" }] }),
    });
    el("work-orders-location-search").value = "bldg 4";
    change(el("work-orders-supervisor-filter"), "s1");
    await vi.waitFor(() => expect(chips().length).toBeGreaterThan(1));
    const labels = chips().map((c) => c.getAttribute("aria-label"));
    expect(labels).toContain("Remove filter Supervisor: Sue S");
    expect(labels).toContain('Remove filter Location: "bldg 4"');
  });

  it("x resets only that filter and reloads", async () => {
    await mountWorkOrders({ role: "admin", cards: [workOrderCard()] });
    el("work-orders-search").value = "1234";
    change(el("work-orders-status-filter"), "on_hold");
    await vi.waitFor(() => expect(chips()).toHaveLength(3));
    expect(chips()[2].textContent).toBe("Clear all");
    const before = listLoads().length;
    chips()[0].click();
    await vi.waitFor(() => expect(chips()).toHaveLength(1));
    expect(el("work-orders-status-filter").value).toBe("");
    expect(el("work-orders-search").value).toBe("1234");
    expect(chips()[0].textContent).toContain("WO #: 1234");
    expect(listLoads().length).toBeGreaterThan(before);
  });

  it("Clear all clears every filter", async () => {
    await mountWorkOrders({ role: "admin", cards: [workOrderCard()] });
    el("work-orders-task-search").value = "leak";
    change(el("work-orders-status-filter"), "created");
    await vi.waitFor(() => expect(chips()).toHaveLength(3));
    chips()[2].click();
    await vi.waitFor(() => expect(el("work-orders-filter-chips").hidden).toBe(true));
    expect(el("work-orders-status-filter").value).toBe("");
    expect(el("work-orders-task-search").value).toBe("");
  });

  it("explains an empty filtered list", async () => {
    await mountWorkOrders({ role: "admin", cards: [] });
    change(el("work-orders-status-filter"), "review");
    await vi.waitFor(() => expect(count().textContent)
      .toBe("No work orders match these filters — clear a filter to widen the list"));
    expect(listEl().textContent).toContain("No work orders match.");
  });
});
