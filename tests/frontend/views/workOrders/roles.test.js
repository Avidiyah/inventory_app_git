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

const ROLES = ["technician", "supervisor", "techfm_oa", "admin"];
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
  mode: ".wo-mode-row",
};
const ALL_CONTROLS = Object.keys(CONTROL_SELECTOR);

const MATRIX = {
  technician: {
    created: {
      assigned: ["start-tracking-wo", "labor", "add-material", "notes"],
      unassigned: ["add-material", "notes"],
    },
    assigned: {
      assigned: ["start-tracking-wo", "labor", "add-material", "notes"],
      unassigned: ["add-material", "notes"],
    },
    in_progress: {
      assigned: ["start-tracking-wo", "hold-assigned-wo", "labor", "add-material", "notes"],
      unassigned: ["add-material", "notes"],
    },
    on_hold: {
      assigned: ["start-tracking-wo", "resume-assigned-wo", "labor", "add-material", "notes"],
      unassigned: ["add-material", "notes"],
    },
    ready_to_complete: {
      assigned: ["labor", "add-material", "notes"],
      unassigned: ["add-material", "notes"],
    },
    completed: {
      assigned: ["labor", "add-material", "notes"],
      unassigned: ["add-material", "notes"],
    },
    review: {
      assigned: ["labor", "add-material", "notes"],
      unassigned: ["add-material", "notes"],
    },
  },
  supervisor: {
    created: {
      assigned: ["start-tracking-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    assigned: {
      assigned: ["start-tracking-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    in_progress: {
      assigned: ["start-tracking-wo", "hold-assigned-wo", "complete-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    on_hold: {
      assigned: ["start-tracking-wo", "resume-assigned-wo", "complete-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    ready_to_complete: {
      assigned: ["send-back-wo", "complete-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["send-back-wo", "complete-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    completed: {
      assigned: ["reopen-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["reopen-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    review: {
      assigned: ["reopen-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["reopen-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
  },
  techfm_oa: {
    created: {
      assigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    assigned: {
      assigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    in_progress: {
      assigned: ["start-tracking-wo", "hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    on_hold: {
      assigned: ["start-tracking-wo", "resume-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    ready_to_complete: {
      assigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    completed: {
      assigned: ["review-wo:disabled", "reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["review-wo:disabled", "reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    review: {
      assigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
  },
  admin: {
    created: {
      assigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    assigned: {
      assigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    in_progress: {
      assigned: ["start-tracking-wo", "hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    on_hold: {
      assigned: ["start-tracking-wo", "resume-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["start-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    ready_to_complete: {
      assigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["send-back-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    completed: {
      assigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["review-wo", "reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
    review: {
      assigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
      unassigned: ["reopen-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"],
    },
  },
};

// The only cell tracking changes: an In-Progress row with the caller's own
// clock running swaps Begin Charging for Stop Charging (and, for an assigned
// non-supervisor, adds Notify Supervisor).
const WHILE_TRACKING = {
  technician: { assigned: ["stop-tracking-wo", "notify-supervisor-wo", "hold-assigned-wo", "labor", "add-material", "notes"], unassigned: ["add-material", "notes"] },
  supervisor: { assigned: ["stop-tracking-wo", "hold-assigned-wo", "complete-wo", "editor", "labor", "add-material", "notes", "mode"], unassigned: ["stop-tracking-wo", "complete-wo", "editor", "labor", "add-material", "notes", "mode"] },
  techfm_oa: { assigned: ["stop-tracking-wo", "hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"], unassigned: ["stop-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"] },
  admin: { assigned: ["stop-tracking-wo", "hold-assigned-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"], unassigned: ["stop-tracking-wo", "complete-wo", "archive-wo", "open-netfacilities-wo", "editor", "labor", "add-material", "notes", "mode"] },
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
  it.each(ROLES.flatMap((role) => [[role, true], [role, false]]))(
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

  it("lets the routed Supervisor send it", async () => {
    const btn = await reviewControl({ role: "supervisor", assigned: false, supervisorIsMe: true });
    expect(btn).not.toBeNull();
    expect(btn.disabled).toBe(false);
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
    expect(btn.title).toBe("An Admin, Owner, or the routed Supervisor must send this to Review.");
  });

  it("hides it from a technician entirely", async () => {
    expect(await reviewControl({ role: "technician", assigned: false, supervisorIsMe: false })).toBeNull();
  });
});

describe("labor entry controls (edit-labor / remove-labor)", () => {
  it.each([
    // A Technician may edit/remove only a row attributed to them; every
    // Supervisor+ role may touch any row regardless of who it is credited to.
    ["technician", false, false],
    ["technician", true, true],
    ["supervisor", false, true],
    ["techfm_oa", false, true],
    ["admin", false, true],
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
    // A Technician needs to be assigned before they may add their own hours;
    // a Supervisor+ always can (they credit themselves when unassigned).
    ["technician", false, false],
    ["technician", true, true],
    ["supervisor", false, true],
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
  it("lets a Technician remove a material line, with no quantity editor", async () => {
    const detail = workOrderDetail({
      status: "in_progress",
      items: [workOrderItem({ id: "wi1", quantity: "2" })],
    });
    await mountWorkOrders({
      role: "technician",
      cards: [workOrderCard({ id: detail.id, number: detail.number, status: "in_progress" })],
      details: [detail],
    });
    await openCard(0);
    expect(card().querySelector('[data-action="remove-item"]')).not.toBeNull();
    expect(card().querySelector('[data-action="edit-item"]')).toBeNull();
    expect(card().querySelector(".wo-line-qty")).toBeNull();
  });
});

describe("the denial spot-check", () => {
  it("removes the three assigned-only controls from the DOM, not merely disables them", async () => {
    // In-Progress with a clock running is the only state where Notify, Hold
    // and Stop Charging would all render for an assigned technician.
    const cardEl = await renderCell({
      role: "technician", status: "in_progress", assigned: false, tracking: true,
    });
    for (const action of ["hold-assigned-wo", "notify-supervisor-wo", "stop-tracking-wo"]) {
      expect(cardEl.querySelector(`[data-action="${action}"]`), action).toBeNull();
    }
    // Not disabled-but-present anywhere in the body either.
    expect(cardEl.querySelectorAll("button[disabled]")).toHaveLength(0);
  });
});
