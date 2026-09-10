// Characterization: what a work-order card looks like today.
//
// Every assertion here records observed output, not intended output. Where
// the observed thing looks wrong it carries a comment and a line in
// docs/open-work.md -- see the plan's "A note on characterization".
//
// The pure render helpers (`summaryHtml`, `priorityBucket`, `placeMeta`,
// `formatMinutes`, …) are module-private, so they are exercised through the
// markup they produce. `workOrderCardClass` is the one exception: other views
// import it, so it is asserted directly as well.

import { describe, expect, it } from "vitest";
import { HttpResponse } from "msw";
import {
  card, cardEls, listEl, mountWorkOrders, openCard, state,
} from "../../helpers/workOrders.js";
import {
  filterOptions, user, workOrderCard, workOrderDetail, workOrderItem, workOrderLabor,
} from "../../helpers/factories.js";

const STATUSES = [
  ["created", "Created"],
  ["assigned", "Assigned"],
  ["in_progress", "In-Progress"],
  ["on_hold", "On-Hold"],
  ["ready_to_complete", "Ready to Complete"],
  ["completed", "Completed"],
  ["review", "Review"],
];

// One card, rendered in the list, without opening it.
async function renderOne(overrides, { role = "admin" } = {}) {
  const one = workOrderCard(overrides);
  await mountWorkOrders({ role, cards: [one] });
  return { row: cardEls()[0], one };
}

// One card, opened as a card page, with the given detail.
async function renderBody(overrides, { role = "admin", items = [], users = [] } = {}) {
  const detail = workOrderDetail(overrides);
  await mountWorkOrders({
    role,
    cards: [workOrderCard({ id: detail.id, number: detail.number, status: detail.status })],
    details: [detail],
    items,
    users,
  });
  await openCard(0);
  return { cardEl: card(), detail };
}

describe("the fixture", () => {
  it("mounts with a seeded list and opens one card", async () => {
    const cards = ["1001", "1002", "1003"].map((number) => workOrderCard({ number }));
    await mountWorkOrders({ role: "admin", cards });
    expect(cardEls()).toHaveLength(3);

    await openCard("1001", workOrderDetail({ id: cards[0].id, number: "1001" }));
    expect(card().dataset.id).toBe(String(cards[0].id));
    expect(card().querySelector(".wo-details")).not.toBeNull();
  });

  it("renders the empty state, not a blank list", async () => {
    await mountWorkOrders({ role: "admin", cards: [] });
    expect(listEl().textContent).toContain("No work orders match.");
  });
});

// --- Task 2: the collapsed row -------------------------------------------

describe("summaryHtml", () => {
  it.each(STATUSES)("badges %s as %s", async (status, label) => {
    const { row } = await renderOne({ status, number: "77" });
    expect(row.querySelector(".wo-title").textContent).toBe("WO 77");
    const badge = row.querySelector(".wo-status");
    expect(badge.textContent).toBe(label);
    expect(badge.className).toBe(`wo-status wo-status-${status}`);
  });

  it("composes an imported row's place from `location` alone", async () => {
    const { row } = await renderOne({ location: "Hallway B", item_count: 2 });
    expect(row.querySelector(".wo-meta").textContent).toBe("Hallway B · 2 items");
  });

  it("prefers the legacy community/building/unit trio and tags the row", async () => {
    const { row } = await renderOne({
      legacy: true, community: "Maple Ridge", building_number: "3", unit_number: "12",
      location: "ignored", item_count: 1,
    });
    expect(row.querySelector(".wo-meta").textContent).toBe("Maple Ridge · Bldg 3 · Unit 12 · 1 items");
    expect(row.querySelector(".wo-legacy-tag").textContent).toBe("Legacy");
  });

  it("omits the place entirely when there is neither", async () => {
    const { row } = await renderOne({ location: null, item_count: 0 });
    expect(row.querySelector(".wo-meta").textContent).toBe("0 items");
    expect(row.querySelector(".wo-legacy-tag")).toBeNull();
  });

  it("appends the assigned names, joined", async () => {
    const { row } = await renderOne({
      assigned_to_names: ["Ada L", "Grace H"], location: null, item_count: 3,
    });
    expect(row.querySelector(".wo-meta").textContent).toBe("3 items · Ada L, Grace H");
  });

  it("falls back to the singular legacy assignee field", async () => {
    const { row } = await renderOne({
      assigned_to_names: [], assigned_to_name: "Solo Tech", location: null, item_count: 0,
    });
    expect(row.querySelector(".wo-meta").textContent).toBe("0 items · Solo Tech");
  });

  it("escapes a number carrying markup", async () => {
    const { row } = await renderOne({ number: "<img src=x>" });
    expect(row.querySelector(".wo-title").textContent).toBe("WO <img src=x>");
    expect(row.querySelector("img")).toBeNull();
  });
});

describe("priorityBucket and the priority pill", () => {
  it.each([
    ["Emergency", "emergency"],
    ["EMERGENCY - after hours", "emergency"],
    ["Urgent", "urgent"],
    ["High", "high"],
    ["Low", "low"],
    ["Normal", "normal"],
    ["Routine", "normal"],
    ["Standard", "normal"],
    ["Whenever you like", "unknown"],
    // The filter sentinel is never a stored priority, but nothing stops it
    // reaching here, and it buckets as unrecognised text.
    ["__none__", "unknown"],
  ])("buckets %s as %s", async (priority, bucket) => {
    const { row } = await renderOne({ priority, status: "assigned" });
    const pill = row.querySelector(".wo-priority");
    expect(pill.textContent).toBe(priority);
    expect(pill.className).toContain(`wo-priority-${bucket}`);
  });

  it("labels a null priority 'No priority' and buckets it as none", async () => {
    const { row } = await renderOne({ priority: null });
    const pill = row.querySelector(".wo-priority");
    expect(pill.textContent).toBe("No priority");
    expect(pill.className).toBe("wo-priority wo-priority-none");
  });
});

describe("urgentFireActive", () => {
  it.each(["created", "assigned", "in_progress", "on_hold", "ready_to_complete"])(
    "burns an Urgent work order at %s", async (status) => {
      const { row } = await renderOne({ priority: "Urgent", status });
      expect(row.querySelector(".wo-priority").className).toContain("wo-priority-fire");
      expect(row.className).toContain("wo-card-urgent");
    });

  it.each(["completed", "review"])("stops burning once settled at %s", async (status) => {
    const { row } = await renderOne({ priority: "Urgent", status });
    expect(row.querySelector(".wo-priority").className).not.toContain("wo-priority-fire");
    expect(row.className).not.toContain("wo-card-urgent");
  });
});

describe("workOrderCardClass", () => {
  // Exported, and `adminReview.js` / `transactions.js` import it too, so P4
  // must keep it exported.
  it.each([
    [{ status: "created", priority: "Normal" }, "wo-card wo-card-status-created"],
    [{ status: "in_progress", priority: "Urgent" }, "wo-card wo-card-status-in_progress wo-card-urgent"],
    [{ status: "completed", priority: "Urgent" }, "wo-card wo-card-status-completed"],
    [{ status: "review", priority: "urgent lowercase" }, "wo-card wo-card-status-review"],
    [{ status: "on_hold", priority: null }, "wo-card wo-card-status-on_hold"],
  ])("%o -> %s", async (overrides, expected) => {
    const { mod } = await mountWorkOrders({ role: "admin" });
    expect(mod.workOrderCardClass(workOrderCard(overrides))).toBe(expected);
  });

  it("interpolates the status unescaped, so a card element mirrors it", async () => {
    const { row } = await renderOne({ status: "created" });
    expect(row.className).toBe("wo-card wo-card-status-created");
  });
});

describe("the skeleton", () => {
  it("shows a skeleton card while the list is in flight, and clears it", async () => {
    const { mod } = await mountWorkOrders({ role: "admin" });
    let release;
    const held = new Promise((resolve) => { release = resolve; });
    state.cards = [workOrderCard({ number: "9" })];
    state.listResponder = async () => {
      await held;
      return HttpResponse.json(state.cards);
    };
    // The list is only repainted by `renderCards`, so the skeleton under test
    // is the card body's, painted by `buildCard` before its detail lands.
    const pending = mod.loadWorkOrders();
    expect(listEl().querySelector(".skel-line")).toBeNull();
    release();
    await pending;
    expect(cardEls()).toHaveLength(1);
    expect(cardEls()[0].querySelector(".wo-body .skel-line")).not.toBeNull();
  });
});

// --- Task 3: the expanded body -------------------------------------------

describe("detailsViewHtml", () => {
  it("lists every filled imported field, and nothing empty", async () => {
    const { cardEl } = await renderBody({
      location: "Hallway B", service_type: "Electrical", schedule_date: "2026-09-10",
      output_to: "Vendor Co", vendor_assignee: "Bob", description: "Replace bulb",
      priority: "Normal", supervisor_name: "Sue S", assigned_to_names: ["Ada L"],
    });
    const terms = [...cardEl.querySelectorAll(".wo-import-meta dt")].map((dt) => dt.textContent);
    expect(terms).toEqual([
      "Location", "Service type", "Scheduled", "Output to", "Vendor contact",
      "Symptom / task", "Priority", "Supervisor", "Technicians",
    ]);
  });

  it("shows 'Not imported' for a null priority and drops the empty rows", async () => {
    const { cardEl } = await renderBody({
      priority: null, output_to: null, vendor_assignee: null, description: null,
      supervisor_name: null, schedule_date: null,
    });
    const rows = [...cardEl.querySelectorAll(".wo-import-meta dt")].map((dt) => dt.textContent);
    expect(rows).toEqual(["Location", "Service type", "Priority"]);
    expect(cardEl.querySelector(".wo-import-meta").textContent).toContain("Not imported");
  });

  it("appends the legacy place rows only when they hold something", async () => {
    const { cardEl } = await renderBody({ community: "Maple Ridge", building_number: "3" });
    const rows = [...cardEl.querySelectorAll(".wo-import-meta dt")].map((dt) => dt.textContent);
    expect(rows).toContain("Community");
    expect(rows).toContain("Building");
    expect(rows).not.toContain("Unit");
  });

  it("never reaches its own empty state, because Priority always fills a row", async () => {
    // Observed, and it looks wrong: the Priority row is
    // `detail.priority || "Not imported"`, which is always truthy, so the
    // `filled.length` guard can never be false and `.wo-details-empty` is
    // dead markup. Filed in docs/open-work.md; not fixed here.
    const { cardEl } = await renderBody({
      location: null, service_type: null, schedule_date: null, output_to: null,
      vendor_assignee: null, description: null, priority: null, supervisor_name: null,
    });
    expect(cardEl.querySelector(".wo-details-empty")).toBeNull();
    const rows = [...cardEl.querySelectorAll(".wo-import-meta dt")].map((dt) => dt.textContent);
    expect(rows).toEqual(["Priority"]);
  });

  it("links a Symptom / task that is a real http(s) URL, and only that field", async () => {
    const { cardEl } = await renderBody({
      description: "https://system.netfacilities.com/tools/x",
      location: "https://not-a-link.example",
    });
    const links = [...cardEl.querySelectorAll(".wo-import-meta a")];
    expect(links).toHaveLength(1);
    expect(links[0].getAttribute("href")).toBe("https://system.netfacilities.com/tools/x");
    expect(links[0].getAttribute("rel")).toBe("noopener noreferrer");
  });

  it("leaves a javascript: task as escaped text", async () => {
    const { cardEl } = await renderBody({ description: "javascript:alert(1)" });
    expect(cardEl.querySelector(".wo-import-meta a")).toBeNull();
    expect(cardEl.querySelector(".wo-import-meta").textContent).toContain("javascript:alert(1)");
  });
});

describe("detailsEditorHtml", () => {
  const admin = { role: "admin" };
  const supervisor = { role: "supervisor" };

  it("gives Admin+ the imported-metadata fields", async () => {
    const { cardEl } = await renderBody({}, admin);
    for (const cls of [
      "wo-edit-location", "wo-edit-service-type", "wo-edit-schedule-date",
      "wo-edit-output-to", "wo-edit-vendor", "wo-edit-priority", "wo-edit-description",
    ]) {
      expect(cardEl.querySelector(`.${cls}`), cls).not.toBeNull();
    }
    expect(cardEl.querySelector(".wo-edit .hint").textContent)
      .toBe("Edit imported metadata and operations for WO 12345.");
  });

  it("gives a Supervisor routing, technicians and status only", async () => {
    const { cardEl } = await renderBody({}, supervisor);
    expect(cardEl.querySelector(".wo-edit-location")).toBeNull();
    expect(cardEl.querySelector(".wo-edit-priority")).toBeNull();
    expect(cardEl.querySelector(".wo-edit-supervisor")).not.toBeNull();
    expect(cardEl.querySelector(".wo-tech-picker")).not.toBeNull();
    expect(cardEl.querySelector(".wo-edit-status")).not.toBeNull();
    expect(cardEl.querySelector(".wo-edit .hint").textContent)
      .toBe("Edit assignment and status for WO 12345.");
  });

  it("stamps the original supervisor id save-details sends back", async () => {
    const supervisorId = "00000000-0000-4000-8000-0000000000aa";
    const { cardEl } = await renderBody({ supervisor_id: supervisorId }, admin);
    expect(cardEl.querySelector(".wo-edit").dataset.originalSupervisorId).toBe(supervisorId);
  });

  it("stamps an empty original supervisor id when the row is unrouted", async () => {
    const { cardEl } = await renderBody({ supervisor_id: null }, admin);
    expect(cardEl.querySelector(".wo-edit").dataset.originalSupervisorId).toBe("");
  });

  it("suggests Urgent in the priority datalist, ahead of the live values", async () => {
    const { cardEl } = await renderBody({}, admin);
    const options = [...cardEl.querySelectorAll("datalist option")].map((o) => o.value);
    // `filterOptions()` seeds Normal + Urgent, and Urgent is already there, so
    // it is NOT prepended a second time.
    expect(options).toEqual(["Normal", "Urgent"]);
  });

  it("prepends Urgent when no live priority matches it", async () => {
    const detail = workOrderDetail({});
    await mountWorkOrders({
      role: "admin",
      cards: [workOrderCard({ id: detail.id, number: detail.number })],
      details: [detail],
      filterOptions: filterOptions({ priorities: ["Normal", "Low"] }),
    });
    await openCard(0);
    const options = [...card().querySelectorAll("datalist option")].map((o) => o.value);
    expect(options).toEqual(["Urgent", "Normal", "Low"]);
  });

  it.each([
    ["created", [], ["created", "in_progress", "on_hold"]],
    ["assigned", ["t1"], ["assigned", "in_progress", "on_hold"]],
    ["in_progress", ["t1"], ["assigned", "in_progress", "on_hold"]],
    ["on_hold", ["t1"], ["assigned", "in_progress", "on_hold", "completed"]],
    ["ready_to_complete", ["t1"], ["assigned", "in_progress", "on_hold", "completed"]],
    ["completed", ["t1"], ["assigned", "in_progress", "on_hold", "completed"]],
  ])("offers %s the statuses %o", async (status, assigned, expected) => {
    const { cardEl } = await renderBody({ status, assigned_to_ids: assigned }, supervisor);
    const values = [...cardEl.querySelectorAll(".wo-edit-status option")].map((o) => o.value);
    expect(values).toEqual(expected);
    expect(cardEl.querySelector(".wo-edit-status").value).toBe(
      expected.includes(status) ? status : expected[0]);
  });

  it("locks the status field on a Review row", async () => {
    const { cardEl } = await renderBody({ status: "review" }, supervisor);
    expect(cardEl.querySelector(".wo-edit-status")).toBeNull();
    const locked = cardEl.querySelector(".wo-edit-field input[disabled]");
    expect(locked.value).toBe("Review");
  });

  it("renders the supervisor combo with a hidden native select carrying the value", async () => {
    const supervisorUser = user({ role: "supervisor", full_name: "Sue S" });
    const detail = workOrderDetail({ supervisor_id: supervisorUser.id });
    await mountWorkOrders({
      role: "admin",
      cards: [workOrderCard({ id: detail.id, number: detail.number })],
      details: [detail],
      users: [supervisorUser],
    });
    await openCard(0);
    const native = card().querySelector(".wo-edit-supervisor");
    expect(native.hidden).toBe(true);
    expect(native.value).toBe(String(supervisorUser.id));
    expect([...native.options].map((o) => o.textContent)).toEqual(["Unassigned", "Sue S"]);
    const combo = card().querySelector(".wo-supervisor-combo");
    expect(combo.querySelector(".wo-combo-trigger-label").textContent).toBe("Sue S");
    expect(combo.querySelector(".wo-combo-list").hidden).toBe(true);
    expect([...combo.querySelectorAll(".wo-combo-option")].map((b) => b.dataset.value))
      .toEqual(["", String(supervisorUser.id)]);
  });

  it("renders the technician picker with a row per assignment", async () => {
    const { cardEl } = await renderBody({
      assigned_to_ids: ["t1", "t2"], assigned_to_names: ["Ada L", "Grace H"],
    }, supervisor);
    const rows = [...cardEl.querySelectorAll(".wo-tech-selected-row")];
    expect(rows.map((r) => r.dataset.technicianId)).toEqual(["t1", "t2"]);
    expect(rows.map((r) => r.querySelector(".wo-tech-selected-name").textContent))
      .toEqual(["Ada L", "Grace H"]);
    expect(cardEl.querySelector(".wo-tech-search").getAttribute("aria-expanded")).toBe("false");
  });

  it("says so when nobody is assigned", async () => {
    const { cardEl } = await renderBody({ assigned_to_ids: [], assigned_to_names: [] }, supervisor);
    expect(cardEl.querySelector(".wo-tech-empty").textContent).toBe("No technicians assigned.");
  });

  it("names an assigned id with no name after the loaded technician list", async () => {
    const tech = user({ role: "technician", full_name: "Ada L" });
    const detail = workOrderDetail({ assigned_to_ids: [tech.id], assigned_to_names: [] });
    await mountWorkOrders({
      role: "supervisor",
      cards: [workOrderCard({ id: detail.id, number: detail.number })],
      details: [detail],
      users: [tech],
    });
    await openCard(0);
    expect(card().querySelector(".wo-tech-selected-name").textContent).toBe("Ada L");
  });
});

describe("the labor section", () => {
  // One mount per test: `vi.resetModules()` runs in `beforeEach`, so a second
  // `mountView` inside one test returns the cached module still bound to the
  // first mount's discarded DOM.
  it.each([
    [0, "0 min"], [1, "1 min"], [59, "59 min"], [60, "1 hr"],
    [120, "2 hrs"], [90, "1 hr 30 min"], // No plural on the hours when there is also a remainder: the "hr"/"hrs"
    // branch is the whole-hours one only.
    [605, "10 hr 5 min"],
  ])("formats %i minutes as %s", async (minutes, text) => {
    const { cardEl } = await renderBody({
      labor: [workOrderLabor({ minutes })], labor_minutes: minutes,
    }, { role: "supervisor" });
    expect(cardEl.querySelector(".wo-labor-entry .hint").textContent).toBe(`${text} actual`);
  });

  it("treats a blank or non-numeric duration as zero", async () => {
    const { cardEl } = await renderBody({
      labor: [workOrderLabor({ minutes: "" }), workOrderLabor({ minutes: "abc" })],
    }, { role: "supervisor" });
    const entries = [...cardEl.querySelectorAll(".wo-labor-entry .hint")];
    expect(entries.map((e) => e.textContent)).toEqual(["0 min actual", "0 min actual"]);
    // `hoursInputValue` has no such guard -- it writes the string "NaN" --
    // and a number input sanitises that to the empty string.
    expect([...cardEl.querySelectorAll(".wo-labor-hours")].map((i) => i.value))
      .toEqual(["0", ""]);
  });

  it("renders the summary, the rate line and the charge", async () => {
    const { cardEl } = await renderBody({
      labor_minutes: 90, labor_billed_minutes: 120, labor_total: "125.00", labor_rate: "62.50",
    }, { role: "supervisor" });
    const summary = cardEl.querySelector(".wo-labor-summary").textContent;
    expect(summary).toContain("Actual: 1 hr 30 min");
    expect(summary).toContain("Billed: 2 hrs");
    expect(cardEl.querySelector(".wo-labor-charge").textContent).toBe("$125.00 at $62.50/hr");
    expect(cardEl.querySelector(".wo-labor-section").textContent)
      .toContain("Labor is billed at $62.50/hour.");
  });

  it("drops the charge and softens the rate line when cost is redacted", async () => {
    const { cardEl } = await renderBody({
      labor_total: null, labor_rate: null,
    }, { role: "supervisor" });
    expect(cardEl.querySelector(".wo-labor-charge")).toBeNull();
    expect(cardEl.querySelector(".wo-labor-section").textContent)
      .toContain("The combined actual time is rounded up to the next 30 minutes for billing.");
  });

  it("seeds the hours input from the stored minutes and shows the session window", async () => {
    const { cardEl } = await renderBody({
      labor: [workOrderLabor({ minutes: 75, session_window: "2:10-3:25 PM", auto_closed: true })],
    }, { role: "supervisor" });
    expect(cardEl.querySelector(".wo-labor-hours").value).toBe("1.25");
    expect(cardEl.querySelector(".wo-labor-window").textContent).toBe("2:10-3:25 PM");
    expect(cardEl.querySelector(".wo-labor-auto-stopped").textContent).toBe("auto-stopped");
  });

  it("gives a technician a read-only labor card", async () => {
    const me = user({ role: "technician" });
    const detail = workOrderDetail({
      assigned_to_ids: [me.id], labor: [workOrderLabor({ minutes: 60 })],
    });
    await mountWorkOrders({
      role: "technician",
      cards: [workOrderCard({ id: detail.id, number: detail.number })],
      details: [detail],
    });
    // `setTestUser` minted its own user; re-seed the detail with that id.
    const state_ = await import("../../../../backend/static/state.js");
    detail.assigned_to_ids = [state_.getCurrentUser().id];
    await openCard(0);
    expect(card().querySelector(".wo-labor-section")).not.toBeNull();
    expect(card().querySelector(".wo-labor-actions")).toBeNull();
    expect(card().querySelector(".wo-add-labor")).toBeNull();
    expect(card().querySelector(".wo-labor-section").textContent)
      .toContain("Your hours come from Begin Charging.");
  });

  it("offers a supervisor themselves as a labor technician when they are not on the crew", async () => {
    const { cardEl } = await renderBody({ assigned_to_ids: [] }, { role: "supervisor" });
    const options = [...cardEl.querySelectorAll(".wo-labor-technician option")];
    expect(options).toHaveLength(1);
    expect(options[0].textContent).toContain("(not assigned)");
    expect(cardEl.querySelector(".wo-new-labor-hours")).not.toBeNull();
  });
});

describe("the materials section", () => {
  it("renders a line with its mode tag, on-hand count and charge arithmetic", async () => {
    const { cardEl } = await renderBody({
      items: [workOrderItem({ quantity: "2", unit_price: "10.00", item_quantity: "7" })],
      materials_total: "20.00",
    });
    const line = cardEl.querySelector(".wo-item");
    expect(line.querySelector(".wo-line-mode").textContent).toBe("Dispense");
    expect(line.querySelector(".wo-onhand").textContent).toBe("On hand: 7");
    expect(line.querySelector(".charge-base").textContent).toBe("$20.00");
    // MARKUP_RATE is 1.15: 20 * 1.15 = 23.
    expect(line.querySelector(".charge-marked").textContent).toBe("+15%: $23.00");
    expect(cardEl.querySelector(".wo-materials-total").textContent)
      .toBe("Materials total: $20.00 +15%: $23.00");
  });

  it("labels a retroactive line", async () => {
    const { cardEl } = await renderBody({ items: [workOrderItem({ mode: "retroactive" })] });
    expect(cardEl.querySelector(".wo-line-mode").textContent).toBe("Retroactive");
    expect(cardEl.querySelector(".wo-line-mode").className)
      .toBe("wo-line-mode wo-line-mode-retroactive");
  });

  it("charges the billable override and flags the difference", async () => {
    const { cardEl } = await renderBody({
      items: [workOrderItem({ quantity: "4", billable_quantity: "1", unit_price: "10.00" })],
    });
    expect(cardEl.querySelector(".charge-base").textContent).toBe("$10.00");
    expect(cardEl.querySelector(".charge-flag").textContent).toBe("Billing 1 of 4");
    const cell = cardEl.querySelector(".wo-line-charge");
    expect(cell.dataset.quantity).toBe("4");
    expect(cell.dataset.billable).toBe("1");
  });

  it("says Not charged for a zero override", async () => {
    const { cardEl } = await renderBody({
      items: [workOrderItem({ quantity: "4", billable_quantity: "0", unit_price: "10.00" })],
    });
    expect(cardEl.querySelector(".charge-flag").textContent).toBe("Not charged");
    expect(cardEl.querySelector(".charge-flag").className).toBe("charge-flag not-charged");
  });

  it("hides every money cell when the backend redacted the price", async () => {
    const { cardEl } = await renderBody({
      items: [workOrderItem({ unit_price: null })], materials_total: null,
    }, { role: "supervisor" });
    expect(cardEl.querySelector(".wo-line-charge")).toBeNull();
    expect(cardEl.querySelector(".wo-materials-total")).toBeNull();
    expect(cardEl.querySelector(".wo-edit-charge-btn")).toBeNull();
  });

  it("says so when nothing is logged", async () => {
    const { cardEl } = await renderBody({ items: [] });
    expect(cardEl.querySelector(".wo-items").textContent).toBe("No materials logged yet.");
  });

  it("gives a technician a read-only quantity", async () => {
    const me = user({ role: "technician" });
    const detail = workOrderDetail({
      assigned_to_ids: [me.id], items: [workOrderItem({ quantity: "3", unit_price: null })],
    });
    await mountWorkOrders({
      role: "technician",
      cards: [workOrderCard({ id: detail.id, number: detail.number })],
      details: [detail],
    });
    await openCard(0);
    expect(card().querySelector(".wo-line-qty")).toBeNull();
    expect(card().querySelector(".wo-item .hint").textContent).toBe("Quantity: 3");
  });
});

describe("the notes log", () => {
  it.each([
    [null, "No notes recorded yet."],
    ["   ", "No notes recorded yet."],
  ])("renders %o as the empty state", async (notes, text) => {
    const { cardEl } = await renderBody({ notes });
    expect(cardEl.querySelector(".wo-notes-empty").textContent).toBe(text);
  });

  it("renders a multi-entry log as one escaped text block", async () => {
    const log = "2026-09-01 Ada: found it\n2026-09-02 Grace: <fixed>";
    const { cardEl } = await renderBody({ notes: log });
    expect(cardEl.querySelector(".wo-notes-log-text").textContent).toBe(log);
    expect(cardEl.querySelector(".wo-notes-log-text").children).toHaveLength(0);
  });
});

describe("the whole card body", () => {
  it("carries no inline style attribute anywhere", async () => {
    // CSP has no style-src, so the browser silently drops `style=` parsed out
    // of markup. This is the cheapest place to catch a regression.
    const { cardEl } = await renderBody({
      items: [workOrderItem()], labor: [workOrderLabor()], notes: "a note",
      assigned_to_ids: ["t1"], assigned_to_names: ["Ada L"],
    }, { role: "admin" });
    expect(cardEl.querySelectorAll("[style]")).toHaveLength(0);
  });

  it("renders every section a supervisor sees, once", async () => {
    const { cardEl } = await renderBody({}, { role: "supervisor" });
    for (const selector of [
      ".wo-controls", ".wo-details", ".wo-edit-card", ".wo-notes-section",
      ".wo-materials-section", ".wo-request-section", ".wo-labor-section", ".wo-message",
    ]) {
      expect(cardEl.querySelectorAll(selector), selector).toHaveLength(1);
    }
  });
});
