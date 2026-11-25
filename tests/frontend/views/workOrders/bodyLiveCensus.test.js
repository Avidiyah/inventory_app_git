// The card body's identity census (Stage 2, Task 2). A live patch pairs old
// and new elements by id, so every element it may leave alone, and every
// direct child of the body, must carry one. This file fails when a field,
// row, form or action button is added outside those rules.

import { describe, expect, it, vi } from "vitest";
import { workOrderDetail, workOrderItem } from "../../helpers/factories.js";
import { setTestUser } from "../../helpers/session.js";
import { importView, mountShell } from "../../helpers/shell.js";

const SECTION_ORDER = [
  "wo-sec-pin", "wo-sec-charging", "wo-sec-lock", "wo-sec-prior", "wo-sec-actions", "wo-sec-details", "wo-sec-notes",
  "wo-sec-materials", "wo-sec-labor", "wo-sec-photos", "wo-sec-invoice", "wo-sec-msg",
];
const ROLES = [
  { name: "Owner", role: "owner", crew: false },
  { name: "Team Lead", role: "supervisor", crew: false },
  { name: "Technician on the crew", role: "technician", crew: true },
  { name: "Technician off the crew", role: "technician", crew: false },
];
const STATUSES = ["assigned", "in_progress", "on_hold", "ready_to_complete", "completed", "review"];
const SMR_STAGES = ["paper_review", "needs_review", "ready", null, "ready", "paper_review"];

const smrLine = (id, overrides = {}) => ({
  id, work_order_id: "w", reading_id: "r1", import_key: null, work_date: "2026-06-20", date_basis: "paper",
  week: 4, vendor: "BT Restoration", worker_id: null, worker_name: null, alias_on_paper: null, headcount: 1,
  hours_each: "3.0", hours: "3.0", kind: "field", reason_code: null, status: "charged", exclusion_ground: null,
  note: null, created_at: "2026-11-06T12:00:00Z", updated_at: "2026-11-06T12:00:00Z", history: [], ...overrides,
});
const laborEntry = (id, technicianId) => ({
  id, technician_id: technicianId, technician_name: "Pat", minutes: 90, hand_entered: true,
  recorded_by_self: false, week_open: true, session_window: null, auto_closed: false,
});

// Every combination the plan names, swept across the statuses so each action
// ladder rung renders at least once per role.
function fixtures() {
  const out = [];
  for (const who of ROLES) {
    for (const smr of [false, true]) {
      for (const extras of [false, true]) {
        STATUSES.forEach((status, index) => {
          out.push({ who, smr, extras, status, stage: SMR_STAGES[index] });
        });
      }
    }
  }
  return out;
}

const label = (f) => `${f.who.name} / ${f.smr ? "SMR" : "plain"} / ${f.extras ? "clock+prior" : "bare"} / ${f.status}`;

async function setup() {
  mountShell();
  const html = await importView("views/workOrderCardHtml.js");
  const live = await importView("views/workOrderLiveBody.js");
  const morph = await importView("morph.js");
  const host = document.getElementById("work-orders-list");
  return { html, live, morph, host };
}

async function detailFor(f) {
  const me = await setTestUser({ role: f.who.role, smr_enabled: true }); // SMR27 on: the editable SMR card
  const technicianId = "20000000-0000-4000-8000-000000000001";
  const crew = f.who.crew ? [me.id] : [technicianId];
  return workOrderDetail({
    status: f.status,
    smr: f.smr,
    entry_mode: f.smr ? "retroactive" : "dispense",
    assigned_to_ids: crew,
    assigned_to_names: crew.map(() => "Crew Member"),
    notes: "Ann Lee began work",
    items: [
      workOrderItem({ id: "30000000-0000-4000-8000-000000000001" }),
      workOrderItem({ id: "30000000-0000-4000-8000-000000000002", item_name: "Fuse" }),
    ],
    labor: [
      laborEntry("40000000-0000-4000-8000-000000000001", crew[0]),
      laborEntry("40000000-0000-4000-8000-000000000002", crew[0]),
    ],
    labor_minutes: 180,
    smr_lines: [
      smrLine("50000000-0000-4000-8000-000000000001"),
      smrLine("50000000-0000-4000-8000-000000000002", { headcount: 2, hours: "6.0", kind: "clean-up" }),
    ],
    smr_stage: f.smr ? f.stage : null,
    smr_paper_reviewed: f.smr ? { at: "2026-11-06T12:00:00Z", by_name: "JM" } : null,
    smr_ready: f.smr && f.stage === "ready" ? { at: "2026-11-06T12:00:00Z", by_name: "JM" } : null,
    smr_block: f.smr
      ? { id: "b1", version: 1, text: "SMR27 LABOR CORRECTION v1\nline", pasted_at: null, stale: false }
      : null,
    smr_paper_check: null,
    active_labor_session: f.extras ? { started_at: "2026-11-15T14:00:00Z" } : null,
    prior_work: f.extras ? { by: ["Ann Lee"], last_at: "2026-10-14T15:05:00Z" } : null,
  });
}

// Paints a fixture into a `.wo-body` inside the real shell document.
async function paint(ctx, f) {
  ctx.host.innerHTML = `<details class="wo-card" open><summary class="wo-summary"></summary><div class="wo-body"></div></details>`;
  const body = ctx.host.querySelector(".wo-body");
  const detail = await detailFor(f);
  ctx.html.renderBody(detail, body);
  return { body, detail };
}

async function eachFixture(check) {
  const ctx = await setup();
  for (const f of fixtures()) {
    const { body, detail } = await paint(ctx, f);
    check(body, label(f), ctx, f, detail);
  }
}

const dupes = (ids) => ids.filter((id, i) => ids.indexOf(id) !== i);
const FIELDS = "input, select, textarea";

describe("card body identity census", () => {
  it("every direct child of the body carries a unique id", async () => {
    await eachFixture((body, name) => {
      const ids = [...body.children].map((el) => el.id);
      expect(ids.filter((id) => !SECTION_ORDER.includes(id)), name).toEqual([]);
      expect(dupes(ids), name).toEqual([]);
      const positions = ids.map((id) => SECTION_ORDER.indexOf(id));
      expect(positions, name).toEqual([...positions].sort((a, b) => a - b));
    });
  });

  it("every row and every entry form carries a unique id", async () => {
    await eachFixture((body, name, ctx) => {
      const { LIVE_FORMS, LIVE_ROWS } = ctx.live;
      const els = [...body.querySelectorAll(`${LIVE_ROWS}, ${LIVE_FORMS}`)];
      expect(els.filter((el) => !el.id).map((el) => el.className), name).toEqual([]);
      expect(dupes(els.map((el) => el.id)), name).toEqual([]);
      body.querySelectorAll(".wo-item").forEach((row) => {
        expect(row.id, name).toBe(`wo-line-${row.dataset.woItemId}`);
        const qty = row.querySelector(".wo-line-qty");
        if (qty) expect(qty.id, name).toBe(`wo-line-qty-${row.dataset.woItemId}`);
      });
      body.querySelectorAll(".wo-labor-entry:not(.wo-smr-line)").forEach((row) => {
        expect(row.id, name).toBe(`wo-labor-${row.dataset.laborId}`);
        const hours = row.querySelector(".wo-labor-hours");
        if (hours) expect(hours.id, name).toBe(`wo-labor-hours-${row.dataset.laborId}`);
      });
      body.querySelectorAll(".wo-smr-line").forEach((row) => {
        expect(row.id, name).toBe(`wo-smrline-${row.dataset.lineId}`);
        const hours = row.querySelector(".wo-smr-l-hours");
        if (hours) expect(hours.id, name).toBe(`wo-smrline-hours-${row.dataset.lineId}`);
      });
      const formIds = { ".wo-add-item": "wo-add-item", ".wo-add-skilled-labor": "wo-add-skilled", ".wo-smr-add": "wo-add-smr" };
      for (const [selector, id] of Object.entries(formIds)) {
        const el = body.querySelector(selector);
        if (el) expect(el.id, name).toBe(id);
      }
      const plain = body.querySelector(".wo-add-labor:not(.wo-add-skilled-labor):not(.wo-smr-add)");
      if (plain) expect(plain.id, name).toBe("wo-add-labor");
      const edit = body.querySelector(".wo-edit-card");
      if (edit) expect(edit.id, name).toBe("wo-edit-card");
    });
  });

  it("every field outside an entry form and outside Edit details carries a unique id", async () => {
    await eachFixture((body, name, ctx) => {
      const fields = [...body.querySelectorAll(FIELDS)].filter(
        (f) => !f.closest("#wo-edit-card") && !f.closest(ctx.live.LIVE_FORMS) && !f.readOnly,
      );
      expect(fields.filter((f) => !f.id).map((f) => f.className), name).toEqual([]);
      expect(dupes(fields.map((f) => f.id)), name).toEqual([]);
      const named = { ".wo-notes-input": "wo-notes-input", ".wo-smr-description-text": "wo-smr-description", ".wo-mode-select": "wo-mode-select" };
      for (const [selector, id] of Object.entries(named)) {
        const el = body.querySelector(selector);
        if (el) expect(el.id, name).toBe(id);
      }
    });
  });

  it("no id is duplicated in the document", async () => {
    // The shell carries every page's static markup, the User Hub's included.
    await eachFixture((body, name) => {
      const ids = [...document.querySelectorAll("[id]")].map((el) => el.id);
      expect(dupes(ids), name).toEqual([]);
    });
  });

  it("both message lines carry data-live-keep and an id", async () => {
    await eachFixture((body, name) => {
      const msg = body.querySelector(".wo-message");
      expect(msg.id, name).toBe("wo-sec-msg");
      expect(msg.hasAttribute("data-live-keep"), name).toBe(true);
      const notes = body.querySelector(".wo-notes-message");
      if (notes) {
        expect(notes.id, name).toBe("wo-notes-msg");
        expect(notes.hasAttribute("data-live-keep"), name).toBe(true);
      }
    });
  });

  it("every Edit details field has a W3 snapshot source", async () => {
    const { DETAIL_FIELD_SELECTORS } = await importView("views/workOrderConflict.js");
    await eachFixture((body, name) => {
      const unsourced = [...body.querySelectorAll(`#wo-edit-card :is(${FIELDS})`)].filter(
        (f) => !f.disabled && !f.matches(".wo-tech-search") && !DETAIL_FIELD_SELECTORS.some((s) => f.matches(s)),
      );
      expect(unsourced.map((f) => `${f.localName}.${[...f.classList].join(".")}`), name).toEqual([]);
    });
  });

  it("every field is accounted for", async () => {
    await eachFixture((body, name, ctx) => {
      const strays = [...body.querySelectorAll(FIELDS)].filter(
        (f) => !f.closest("#wo-edit-card") && !f.closest(ctx.live.LIVE_FORMS) && !f.id && !f.readOnly,
      );
      expect(strays.map((f) => `${f.localName}.${[...f.classList].join(".")}`), name).toEqual([]);
    });
  });

  it("the message line is still the body's last child", async () => {
    await eachFixture((body, name) => {
      expect(body.lastElementChild.id, name).toBe("wo-sec-msg");
      expect(body.lastElementChild.classList.contains("wo-message"), name).toBe(true);
    });
  });

  it("every action button outside a row, form and Edit details has the id wo-act-<its action>", async () => {
    const seen = new Set();
    await eachFixture((body, name, ctx) => {
      const { LIVE_FORMS, LIVE_ROWS } = ctx.live;
      const buttons = [...body.querySelectorAll("[data-action]")].filter(
        (b) => !b.closest(LIVE_ROWS) && !b.closest(LIVE_FORMS) && !b.closest("#wo-edit-card"),
      );
      buttons.forEach((b) => seen.add(b.dataset.action));
      const wrong = buttons.filter((b) => b.id !== `wo-act-${b.dataset.action}`);
      expect(wrong.map((b) => `${b.dataset.action} -> "${b.id}"`), name).toEqual([]);
    });
    // The sweep reaches every part of the body the rule names.
    for (const action of ["start-tracking-wo", "complete-wo", "reopen-wo", "archive-wo", "ack-notes-wo",
      "save-notes", "smr-ready", "smr-paper-reviewed", "smr-generate-block", "smr-paper-check"]) {
      expect(seen.has(action), action).toBe(true);
    }
  });

  it("the message line has role=status before any message is set", async () => {
    await eachFixture((body, name) => {
      const msg = body.querySelector("#wo-sec-msg");
      expect(msg.getAttribute("role"), name).toBe("status");
      expect(msg.textContent, name).toBe("");
    });
  });

  it("rendering any fixture twice and patching one into the other logs no duplicate-id warning", async () => {
    const warn = vi.spyOn(console, "warn");
    try {
      await eachFixture((body, name, ctx, f, detail) => {
        warn.mockClear();
        const tree = document.createElement("div");
        ctx.html.renderBody(detail, tree);
        ctx.morph.morphInto(body, tree.childNodes);
        expect(warn.mock.calls, name).toEqual([]);
        expect(body.lastElementChild.id, name).toBe("wo-sec-msg");
      });
    } finally {
      warn.mockRestore();
    }
  });
});
