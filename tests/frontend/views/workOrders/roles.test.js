// Characterization: which controls each role sees on a card body.
//
// The matrix below was READ OFF THE RUNNING CODE and then frozen. It is not a
// specification -- if P4 changes a cell, the right response is to decide
// whether the change was intended, not to re-derive the table. Every control
// not listed for a cell is asserted ABSENT from the DOM, so a guard P4 drops
// fails here rather than shipping.
//
// Dimensions: role x status x (assigned to me?). Tracking is the only other
// input that changes a cell, and only for In-Progress, so it has its own
// small table rather than doubling all 56.

import { describe, expect, it } from "vitest";
import { card, mountWorkOrders, openCard } from "../../helpers/workOrders.js";
import { workOrderCard, workOrderDetail, workOrderItem } from "../../helpers/factories.js";

const ROLES = ["technician", "supervisor", "techfm_oa", "admin", "owner"];
const STATUSES = [
  "created", "assigned", "in_progress", "on_hold",
  "ready_to_complete", "completed", "review",
];

// Every control the matrix speaks about. A cell lists what is present; this
// list is what "absent" is checked against.
const CONTROL_SELECTOR = {
  "start-tracking-wo": '[data-action="start-tracking-wo"]',
  "stop-tracking-wo": '[data-action="stop-tracking-wo"]',
  "notify-supervisor-wo": '[data-action="notify-supervisor-wo"]',
  "hold-assigned-wo": '[data-action="hold-assigned-wo"]',
  "resume-assigned-wo": '[data-action="resume-assigned-wo"]',
  "send-back-wo": '[data-action="send-back-wo"]',
  "complete-wo": '[data-action="complete-wo"]',
  "review-wo": '[data-action="review-wo"]',
  "reopen-wo": '[data-action="reopen-wo"]',
  "archive-wo": '[data-action="archive-wo"]',
  "open-netfacilities-wo": '[data-action="open-netfacilities-wo"]',
  editor: ".wo-edit-card",
  labor: ".wo-labor-section",
  "add-material": ".wo-add-item",
  notes: ".wo-notes-section",
  "notes-input": ".wo-notes-input",
  // The single hint a Technician off the crew sees in place of their inputs.
  "crew-lock": ".wo-crew-lock",
  mode: ".wo-mode-row",
};
const ALL_CONTROLS = Object.keys(CONTROL_SELECTOR);

// Everyone sees every work order; an unassigned Technician is read-only
// (no notes box, no add-material row, one hint) until Begin Charging adds them.
// Begin Charging is on offer on every unfinished status, for every role but
// the Owner.
const MATRIX = {
  technician: {
    created: {
      assigned: ["start-tracking-wo", "labor", "add-material", "notes", "notes-input"],
      unassigned: ["start-tracking-wo", "notes", "crew-lock"],
    },
    assigned: {
      assigned: ["start-tracking-wo", "labor", "add-material", "notes", "notes-input"],
      unassigned: ["start-tracking-wo", "notes", "crew-lock"],
    },
    in_progress: {
      assigned: ["start-tracking-wo", "hold-assigned-wo", "labor", "add-material", "notes", "notes-input"],
      unassigned: ["start-tracking-wo", "notes", "crew-lock"],
    },
    on_hold: {
      assigned: ["start-tracking-wo", "resume-assigned-wo", "labor", "add-material", "notes", "notes-input"],
      unassigned: ["start-tracking-wo", "notes", "crew-lock"],
    },
    ready_to_complete: {
      assigned: ["labor", "add-material", "notes", "notes-input"],
      unassigned: ["notes", "crew-lock"],
    },
    completed: {
      assigned: ["labor", "add-material", "notes", "notes-input"],
      unassigned: ["notes", "crew-lock"],
    },
    review: {
      assigned: ["labor", "add-material", "notes", "notes-input"],
      unassigned: ["notes", "crew-lock"],
    },
  },
  supervisor: {
    created: {
      assigned: ["start-tracking-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    assigned: {
      assigned: ["start-tracking-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    in_progress: {
      assigned: ["start-tracking-wo", "hold-assigned-wo", "complete-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    on_hold: {
      assigned: ["start-tracking-wo", "resume-assigned-wo", "complete-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    ready_to_complete: {
      assigned: ["send-back-wo", "complete-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["send-back-wo", "complete-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    completed: {
      assigned: ["reopen-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["reopen-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    review: {
      assigned: ["reopen-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["reopen-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
  },
  techfm_oa: {
    created: {
      assigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    assigned: {
      assigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    in_progress: {
      assigned: ["start-tracking-wo", "hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    on_hold: {
      assigned: ["start-tracking-wo", "resume-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    ready_to_complete: {
      assigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    completed: {
      assigned: ["review-wo:disabled", "reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["review-wo:disabled", "reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    review: {
      assigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
  },
  admin: {
    created: {
      assigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    assigned: {
      assigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    in_progress: {
      assigned: ["start-tracking-wo", "hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    on_hold: {
      assigned: ["start-tracking-wo", "resume-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    ready_to_complete: {
      assigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    completed: {
      assigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["review-wo", "reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    review: {
      assigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
  },
  // The Owner is not assignable and cannot Begin Charging (no start button in
  // any cell), so Mark Completed is the only way it moves unfinished work on.
  // An `assigned` Owner is an impossible state kept only so the table stays
  // rectangular; the server never produces one.
  owner: {
    created: {
      assigned: ["archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    assigned: {
      assigned: ["archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    in_progress: {
      assigned: ["hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    on_hold: {
      assigned: ["resume-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    ready_to_complete: {
      assigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    completed: {
      assigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["review-wo", "reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
    review: {
      assigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
      unassigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"],
    },
  },
};

// The only cell tracking changes: an In-Progress row with the caller's own
// clock running swaps Begin Charging for Stop Charging (and, for an assigned
// non-Team-Lead, adds Notify Team Lead). The Owner cannot track, so it has no row.
const WHILE_TRACKING = {
  technician: { assigned: ["stop-tracking-wo", "notify-supervisor-wo", "hold-assigned-wo", "labor", "add-material", "notes", "notes-input"], unassigned: ["stop-tracking-wo", "notes", "crew-lock"] },
  supervisor: { assigned: ["stop-tracking-wo", "hold-assigned-wo", "complete-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"], unassigned: ["stop-tracking-wo", "complete-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"] },
  techfm_oa: { assigned: ["stop-tracking-wo", "hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"], unassigned: ["stop-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"] },
  admin: { assigned: ["stop-tracking-wo", "hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"], unassigned: ["stop-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "notes-input", "mode"] },
};

// A control named "x:disabled" is present but disabled -- the TechFM OA
// Send to Review treatment.
function expectCell(cardEl, expected) {
  const present = new Map(expected.map((name) => {
    const [control, flag] = name.split(":");
    return [control, flag === "disabled"];
  }));
  for (const control of ALL_CONTROLS) {
    const el = cardEl.querySelector(CONTROL_SELECTOR[control]);
    if (present.has(control)) {
      expect(el, `${control} should be present`).not.toBeNull();
      expect(Boolean(el.disabled), `${control} disabled state`).toBe(present.get(control));
    } else {
      expect(el, `${control} should be absent`).toBeNull();
    }
  }
}

// Mount one card at `status` for `role`, with the signed-in user assigned or
// not, and open it. The user's real id is only known after `setTestUser`, so
// the detail is amended between the mount and the open -- the fixture serves
// the object by reference.
async function renderCell({ role, status, assigned, tracking = false }) {
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
    ? { id: "s1", technician_id: me, started_at: "2026-09-10T12:00:00Z" }
    : null;
  await openCard(0);
  return card();
}

const cells = [];
for (const role of ROLES) {
  for (const status of STATUSES) {
    for (const assigned of [true, false]) cells.push([role, status, assigned]);
  }
}

describe("the render-time role matrix", () => {
  it.each(cells)("%s, %s, assigned=%s", async (role, status, assigned) => {
    const cardEl = await renderCell({ role, status, assigned });
    expectCell(cardEl, MATRIX[role][status][assigned ? "assigned" : "unassigned"]);
  });
});

describe("an In-Progress row with the caller's clock running", () => {
  it.each(ROLES.filter((role) => role !== "owner").flatMap((role) => [[role, true], [role, false]]))(
    "%s, assigned=%s", async (role, assigned) => {
      const cardEl = await renderCell({ role, status: "in_progress", assigned, tracking: true });
      expectCell(cardEl, WHILE_TRACKING[role][assigned ? "assigned" : "unassigned"]);
    });
});

describe("isSupervisorPlus / isAdminPlus", () => {
  // Read through the two controls each gate owns exclusively: the editor is
  // Supervisor+, Archive is Admin+ (TechFM OA and above).
  it.each([
    ["technician", false, false],
    ["supervisor", true, false],
    ["techfm_oa", true, true],
    ["admin", true, true],
  ])("%s: supervisorPlus=%s adminPlus=%s", async (role, supervisorPlus, adminPlus) => {
    const cardEl = await renderCell({ role, status: "assigned", assigned: true });
    expect(Boolean(cardEl.querySelector(".wo-edit-card"))).toBe(supervisorPlus);
    expect(Boolean(cardEl.querySelector('[data-action="archive-wo"]'))).toBe(adminPlus);
  });
});

describe("isAssignedToCurrentUser", () => {
  it("recognises the caller inside assigned_to_ids", async () => {
    const cardEl = await renderCell({ role: "technician", status: "in_progress", assigned: true });
    expect(cardEl.querySelector('[data-action="hold-assigned-wo"]')).not.toBeNull();
  });

  it("does not recognise a caller who is merely one of several other ids", async () => {
    const detail = workOrderDetail({ status: "in_progress", assigned_to_ids: ["x", "y"] });
    await mountWorkOrders({
      role: "technician",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "in_progress" })],
      details: [detail],
    });
    await openCard(0);
    expect(card().querySelector('[data-action="hold-assigned-wo"]')).toBeNull();
  });

  it("reads the single legacy assigned_to_id when the plural array is absent", async () => {
    const detail = workOrderDetail({ status: "in_progress" });
    delete detail.assigned_to_ids;
    await mountWorkOrders({
      role: "technician",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "in_progress" })],
      details: [detail],
    });
    const state = await import("../../../../backend/static/state.js");
    detail.assigned_to_id = state.getCurrentUser().id;
    await openCard(0);
    expect(card().querySelector('[data-action="hold-assigned-wo"]')).not.toBeNull();
  });
});

describe("canCurrentUserSendToReview", () => {
  // Completed is the only status that renders the control, so this is where
  // the predicate is observable.
  async function reviewControl({ role, assigned, supervisorIsMe }) {
    const detail = workOrderDetail({ status: "completed" });
    await mountWorkOrders({
      role,
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "completed" })],
      details: [detail],
    });
    const state = await import("../../../../backend/static/state.js");
    const me = state.getCurrentUser().id;
    detail.assigned_to_ids = assigned ? [me] : [];
    detail.supervisor_id = supervisorIsMe ? me : null;
    await openCard(0);
    return card().querySelector('[data-action="review-wo"]');
  }

  it("lets an Admin who is not working the job send it", async () => {
    const btn = await reviewControl({ role: "admin", assigned: false, supervisorIsMe: false });
    expect(btn).not.toBeNull();
    expect(btn.disabled).toBe(false);
  });

  it("hides it from an Admin who is one of the assigned workers", async () => {
    expect(await reviewControl({ role: "admin", assigned: true, supervisorIsMe: false })).toBeNull();
  });

  it("hides it from the routed Supervisor", async () => {
    expect(await reviewControl({ role: "supervisor", assigned: false, supervisorIsMe: true })).toBeNull();
  });

  it("hides it from a Supervisor who is not the routed one", async () => {
    expect(await reviewControl({ role: "supervisor", assigned: false, supervisorIsMe: false })).toBeNull();
  });

  it("hides it from the routed Supervisor when they are also assigned", async () => {
    expect(await reviewControl({ role: "supervisor", assigned: true, supervisorIsMe: true })).toBeNull();
  });

  it("shows a TechFM OA the control disabled, with the reason", async () => {
    const btn = await reviewControl({ role: "techfm_oa", assigned: false, supervisorIsMe: true });
    expect(btn.disabled).toBe(true);
    expect(btn.title).toBe("An Admin or the Owner must send this to Review.");
  });

  it("hides it from a technician entirely", async () => {
    expect(await reviewControl({ role: "technician", assigned: false, supervisorIsMe: false })).toBeNull();
  });
});

describe("labor entry controls (edit-labor / remove-labor)", () => {
  it.each([
    // Team Lead and above edit or remove anyone's entry. A Technician may not,
    // not even on the row they are credited for (unless they hand-keyed it).
    ["technician", false, false],
    ["technician", true, false],
    ["supervisor", false, true],
    ["techfm_oa", false, true],
    ["admin", false, true],
    ["owner", false, true],
  ])("%s, owns the entry: %s -> can edit/remove: %s", async (role, ownsEntry, canEdit) => {
    const detail = workOrderDetail({
      status: "in_progress",
      labor: [{
        id: "l1", technician_id: "t1", technician_name: "Ada L",
        minutes: 60, session_window: null, auto_closed: false,
      }],
    });
    const { currentUser } = await mountWorkOrders({
      role,
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "in_progress" })],
      details: [detail],
    });
    detail.assigned_to_ids = [currentUser.id];
    if (ownsEntry) detail.labor[0].technician_id = currentUser.id;
    await openCard(0);
    expect(Boolean(card().querySelector('[data-action="edit-labor"]'))).toBe(canEdit);
    expect(Boolean(card().querySelector('[data-action="remove-labor"]'))).toBe(canEdit);
  });
});

describe("add-labor visibility", () => {
  it.each([
    // Team Lead and above may add hours by hand, crediting themselves when
    // unassigned. A Technician only for themselves, while on the crew.
    ["technician", false, false],
    ["technician", true, true],
    ["supervisor", false, true],
    ["techfm_oa", false, true],
    ["admin", false, true],
    ["owner", false, true],
  ])("%s, assigned: %s -> can add labor: %s", async (role, assigned, canAdd) => {
    const detail = workOrderDetail({ status: "in_progress", labor: [] });
    const { currentUser } = await mountWorkOrders({
      role,
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "in_progress" })],
      details: [detail],
    });
    detail.assigned_to_ids = assigned ? [currentUser.id] : [];
    await openCard(0);
    expect(Boolean(card().querySelector('[data-action="add-labor"]'))).toBe(canAdd);
  });
});

describe("material line controls", () => {
  async function materialCard({ assigned }) {
    const detail = workOrderDetail({
      status: "in_progress",
      items: [workOrderItem({ id: "wi1", quantity: "2" })],
    });
    await mountWorkOrders({
      role: "technician",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "in_progress" })],
      details: [detail],
    });
    if (assigned) {
      const state = await import("../../../../backend/static/state.js");
      detail.assigned_to_ids = [state.getCurrentUser().id];
    }
    await openCard(0);
    return card();
  }

  it("lets a Technician on the crew remove a material line, with no quantity editor", async () => {
    const cardEl = await materialCard({ assigned: true });
    expect(cardEl.querySelector('[data-action="remove-item"]')).not.toBeNull();
    expect(cardEl.querySelector('[data-action="edit-item"]')).toBeNull();
    expect(cardEl.querySelector(".wo-line-qty")).toBeNull();
  });

  it("draws the line read-only for a Technician off the crew: quantity shown, no Remove", async () => {
    const cardEl = await materialCard({ assigned: false });
    expect(cardEl.querySelectorAll(".wo-item")).toHaveLength(1);
    expect(cardEl.querySelector(".wo-item .hint").textContent).toBe("Quantity: 2");
    expect(cardEl.querySelector('[data-action="remove-item"]')).toBeNull();
    expect(cardEl.querySelector('[data-action="edit-item"]')).toBeNull();
  });
});

describe("the crew-lock hint", () => {
  it.each([
    ["created", "Begin Charging to add notes, materials, requests, or a signature."],
    ["on_hold", "Begin Charging to add notes, materials, requests, or a signature."],
    ["completed", "You are not on this work order's crew, so it is read-only for you."],
  ])("an unassigned Technician on a %s work order reads: %s", async (status, text) => {
    const cardEl = await renderCell({ role: "technician", status, assigned: false });
    expect(cardEl.querySelector(".wo-crew-lock").textContent).toBe(text);
  });

  // One mount per test (see the note above `the labor section`).
  it.each(
    ["supervisor", "techfm_oa", "admin", "owner"].flatMap((role) => [[role, true], [role, false]])
  )("never locks a %s, assigned=%s", async (role, assigned) => {
    const cardEl = await renderCell({ role, status: "created", assigned });
    expect(cardEl.querySelector(".wo-crew-lock")).toBeNull();
    expect(cardEl.querySelector(".wo-notes-input")).not.toBeNull();
  });

  it("hides the request form and the signature button too, but leaves the lists readable", async () => {
    const cardEl = await renderCell({ role: "technician", status: "in_progress", assigned: false });
    expect(cardEl.querySelector(".wo-request-section")).not.toBeNull();
    expect(cardEl.querySelector(".wo-request-form")).toBeNull();
    expect(cardEl.querySelector('[data-action="capture-signature"]')).toBeNull();
    expect(cardEl.querySelector(".wo-signature-section")).not.toBeNull();
  });

  it("unlocks once the Technician is on the crew", async () => {
    const cardEl = await renderCell({ role: "technician", status: "in_progress", assigned: true });
    expect(cardEl.querySelector(".wo-crew-lock")).toBeNull();
    expect(cardEl.querySelector(".wo-request-form")).not.toBeNull();
    expect(cardEl.querySelector('[data-action="capture-signature"]')).not.toBeNull();
  });
});

describe("the denial spot-check", () => {
  it("removes the assigned-only controls from the DOM, not merely disables them", async () => {
    // An unassigned Technician has Begin Charging only: no Notify, Hold, or
    // Resume, and no add-material or note input -- gone, not disabled. (Stop
    // Charging cannot render without a running clock, which assigns them.)
    const cardEl = await renderCell({
      role: "technician", status: "in_progress", assigned: false,
    });
    for (const action of ["hold-assigned-wo", "notify-supervisor-wo", "resume-assigned-wo", "stop-tracking-wo"]) {
      expect(cardEl.querySelector(`[data-action="${action}"]`), action).toBeNull();
    }
    for (const selector of [".wo-add-item", ".wo-notes-input", '[data-action="add-item"]', '[data-action="save-notes"]']) {
      expect(cardEl.querySelector(selector), selector).toBeNull();
    }
    // Not disabled-but-present anywhere in the body either. Save signature is
    // the one button that is disabled by an input gate (S6), not by role.
    expect(cardEl.querySelectorAll('button[disabled]:not([data-action="save-signature"])'))
      .toHaveLength(0);
  });
});

// 2026-10-16 self-edit: a worker keys and revises their own hand-entered
// labor in the open week. The server enforces it; the card only mirrors it.
describe("Labor card self-edit", () => {
  async function laborCard(role, { assigned = true, labor = () => [] } = {}) {
    const detail = workOrderDetail({ status: "in_progress", supervisor_id: null });
    await mountWorkOrders({
      role,
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "in_progress" })],
      details: [detail],
    });
    const state = await import("../../../../backend/static/state.js");
    const me = state.getCurrentUser().id;
    detail.assigned_to_ids = assigned ? [me, "peer"] : ["peer"];
    detail.assigned_to_names = assigned ? ["Me", "Peer"] : ["Peer"];
    detail.labor = labor(me);
    await openCard(0);
    return card();
  }
  const row = (id, overrides) => ({
    id, technician_id: "peer", technician_name: "Someone", minutes: 60,
    session_window: null, auto_closed: false,
    hand_entered: true, week_open: true, recorded_by_self: true, ...overrides,
  });
  const entry = (cardEl, id) => cardEl.querySelector(`.wo-labor-entry[data-labor-id="${id}"]`);
  const hasUpdate = (cardEl, id) => Boolean(entry(cardEl, id).querySelector('[data-action="edit-labor"]'));

  it("technician sees Update on own hand-entered row in the open week only", async () => {
    const cardEl = await laborCard("technician", { labor: (me) => [
      row("open", { technician_id: me }),
      row("closed", { technician_id: me, week_open: false }),
    ] });
    expect(hasUpdate(cardEl, "open")).toBe(true);
    expect(entry(cardEl, "open").querySelector('[data-action="remove-labor"]')).not.toBeNull();
    expect(entry(cardEl, "open").textContent).toContain("Self-entered");
    expect(hasUpdate(cardEl, "closed")).toBe(false);
  });

  it("technician never sees Update on a session row or a peer's row", async () => {
    const cardEl = await laborCard("technician", { labor: (me) => [
      row("session", { technician_id: me, hand_entered: false, session_window: "8:00 AM – 9:00 AM" }),
      row("peer", { recorded_by_self: false }),
    ] });
    expect(hasUpdate(cardEl, "session")).toBe(false);
    expect(hasUpdate(cardEl, "peer")).toBe(false);
    expect(entry(cardEl, "peer").textContent).toContain("Admin-entered");
  });

  it("technician on the crew sees Add labor with only themselves", async () => {
    const cardEl = await laborCard("technician");
    const options = [...cardEl.querySelectorAll(".wo-labor-technician option")];
    expect(cardEl.querySelector('[data-action="add-labor"]')).not.toBeNull();
    const state = await import("../../../../backend/static/state.js");
    expect(options.map((o) => o.value)).toEqual([state.getCurrentUser().id]);
  });

  it("technician off the crew gets no Add labor", async () => {
    const cardEl = await laborCard("technician", { assigned: false });
    expect(cardEl.querySelector('[data-action="add-labor"]')).toBeNull();
  });

  it("admin unchanged", async () => {
    const cardEl = await laborCard("admin", { labor: () => [
      row("session", { hand_entered: false, week_open: false }),
    ] });
    expect(hasUpdate(cardEl, "session")).toBe(true);
    const options = [...cardEl.querySelectorAll(".wo-labor-technician option")].map((o) => o.value);
    expect(options).toContain("peer");
  });
});
