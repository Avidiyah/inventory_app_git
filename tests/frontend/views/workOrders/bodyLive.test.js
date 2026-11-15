// A live update patches an open card body (Stage 2, Task 3): patchBodyLive
// keeps whatever the user typed, picked or opened, and pairs every row by id.

import { afterEach, describe, expect, it, vi } from "vitest";
import { card, cardBody, mountWorkOrders, openCard } from "../../helpers/workOrders.js";
import { restoreBrowserStubs } from "../../helpers/browserStubs.js";
import { workOrderCard, workOrderDetail, workOrderItem } from "../../helpers/factories.js";
import { setTestUser } from "../../helpers/session.js";
import { importView, mountShell } from "../../helpers/shell.js";

afterEach(() => {
  restoreBrowserStubs();
  vi.unstubAllGlobals();
  vi.restoreAllMocks();
  vi.useRealTimers();
});

const id = (n) => `30000000-0000-4000-8000-00000000000${n}`;
const T1 = "20000000-0000-4000-8000-000000000001";
const T2 = "20000000-0000-4000-8000-000000000002";
const T3 = "20000000-0000-4000-8000-000000000003";
const item = (n, over = {}) => workOrderItem({ id: id(n), item_name: `Item ${n}`, ...over });
const labor = (n, over = {}) => ({
  id: `4000000${n}-0000-4000-8000-000000000000`, technician_id: T1, technician_name: "Pat", minutes: 90,
  hand_entered: true, recorded_by_self: false, week_open: true, session_window: null, auto_closed: false, ...over,
});
const smrLine = (n, over = {}) => ({
  id: `5000000${n}-0000-4000-8000-000000000000`, work_order_id: "w", reading_id: "r1", import_key: null,
  work_date: "2026-06-20", date_basis: "paper", week: 4, vendor: "BT Restoration", worker_id: null,
  worker_name: `Worker ${n}`, alias_on_paper: null, headcount: 1, hours_each: "3.0", hours: "3.0", kind: "field",
  reason_code: null, status: "charged", exclusion_ground: null, note: null,
  created_at: "2026-11-06T12:00:00Z", updated_at: "2026-11-06T12:00:00Z", history: [], ...over,
});
const PRIOR = { by: ["Ann Lee"], last_at: "2026-10-14T15:05:00Z" };

// Opens the card page. `prep(detail, me)` runs before the open, for
// whatever depends on the signed-in user's id.
async function open({ role = "admin", prep = null, ...over } = {}) {
  const detail = workOrderDetail({
    items: [item(1), item(2), item(3)], assigned_to_ids: [T1, T2], assigned_to_names: ["Pat", "Sam"],
    notes: "Ann Lee began work", ...over,
  });
  const { currentUser } = await mountWorkOrders({
    role, cards: [workOrderCard({ id: detail.id, number: detail.number })], details: [detail],
  });
  if (prep) prep(detail, currentUser);
  await openCard(0);
  const live = await importView("views/workOrderLiveBody.js");
  const patch = (changes = {}) => live.patchBodyLive({ ...detail, ...changes }, cardBody(), card());
  return { detail, live, patch, me: currentUser };
}

const $ = (sel) => cardBody().querySelector(sel);
const byId = (x) => document.getElementById(x);
const msg = () => byId("wo-sec-msg");
const type = (el, value) => { el.value = value; };
const DROPPED = "This work order changed while you were typing. Something you entered no longer applies.";
const CONFLICT = "Someone else changed a value you are editing. Saving yours will replace theirs.";
const rowIds = (sel) => [...cardBody().querySelectorAll(sel)].map((el) => el.id);

describe("rows and typed values", () => {
  it("a line removed above a typed row: the typed quantity stays on its own line; rows match the server's order with no duplicate", async () => {
    const { detail, patch } = await open();
    type(byId(`wo-line-qty-${id(3)}`), "7");
    patch({ items: [detail.items[1], detail.items[2]] });
    expect(rowIds(".wo-item")).toEqual([`wo-line-${id(2)}`, `wo-line-${id(3)}`]);
    expect(byId(`wo-line-${id(3)}`).querySelector(".wo-line-qty").value).toBe("7");
    expect(msg().textContent).toBe("");
  });

  it("a typed row the server removed is gone, and the message line says input was dropped", async () => {
    const { detail, patch } = await open();
    type(byId(`wo-line-qty-${id(2)}`), "7");
    patch({ items: [detail.items[0], detail.items[2]] });
    expect(byId(`wo-line-${id(2)}`)).toBeNull();
    expect(msg().textContent).toBe(DROPPED);
    expect(cardBody().lastElementChild).toBe(msg());
  });

  it("a typed quantity stays while its row's on-hand and name take the server's values", async () => {
    const { detail, patch } = await open();
    type(byId(`wo-line-qty-${id(1)}`), "5");
    patch({ items: [item(1, { item_name: "Lamp", item_quantity: "3" }), ...detail.items.slice(1)] });
    const row = byId(`wo-line-${id(1)}`);
    expect(row.querySelector(".ms-item-name").textContent).toBe("Lamp");
    expect(row.querySelector(".wo-onhand").textContent).toBe("On hand: 3");
    expect(row.querySelector(".wo-line-qty").value).toBe("5");
  });

  it("an untouched row takes the server's quantity", async () => {
    const { detail, patch } = await open();
    patch({ items: [item(1, { quantity: "4" }), ...detail.items.slice(1)] });
    expect(byId(`wo-line-qty-${id(1)}`).value).toBe("4");
  });

  it("a picked add-material row keeps its item id, request id, search text and quantity", async () => {
    const { patch } = await open();
    const form = byId("wo-add-item");
    form.dataset.itemId = "i1";
    form.dataset.materialRequestId = "r1";
    type(form.querySelector(".ms-item-search"), "Bulb");
    type(form.querySelector(".wo-item-qty"), "2");
    patch({ items: [item(4)] });
    expect(byId("wo-add-item")).toBe(form);
    expect(form.dataset.itemId).toBe("i1");
    expect(form.dataset.materialRequestId).toBe("r1");
    expect(form.querySelector(".ms-item-search").value).toBe("Bulb");
    expect(form.querySelector(".wo-item-qty").value).toBe("2");
  });

  it("the focused search keeps its open result list", async () => {
    const { patch } = await open();
    const search = $(".ms-item-search");
    search.focus();
    const results = $(".ms-item-results");
    results.hidden = false;
    results.innerHTML = `<button type="button">Bulb</button>`;
    patch({ items: [item(4)] });
    expect(results.hidden).toBe(false);
    expect(results.textContent).toBe("Bulb");
    expect(document.activeElement).toBe(search);
  });

  it("a half-typed note stays while the notes log shows the new note", async () => {
    const { patch } = await open();
    type(byId("wo-notes-input"), "half a th");
    patch({ notes: "Ann Lee began work\nBob replaced the fan" });
    expect($(".wo-notes-log").textContent).toContain("Bob replaced the fan");
    expect(byId("wo-notes-input").value).toBe("half a th");
  });

  it("a typed labor hours box stays on its own entry when an entry is added above it", async () => {
    const { patch } = await open({ labor: [labor(1), labor(2)], labor_minutes: 180 });
    const hours = byId(`wo-labor-hours-${labor(2).id}`);
    type(hours, "2.5");
    patch({ labor: [labor(3), labor(1), labor(2)] });
    expect(rowIds(".wo-labor-entry")).toEqual([labor(3), labor(1), labor(2)].map((l) => `wo-labor-${l.id}`));
    expect(byId(`wo-labor-${labor(2).id}`).querySelector(".wo-labor-hours").value).toBe("2.5");
    expect(byId(`wo-labor-hours-${labor(1).id}`).value).toBe("1.5");
  });
});

describe("the add-labor row", () => {
  const techOptions = () => [...$("#wo-add-labor .wo-labor-technician").options].map((o) => o.value);

  it("hours typed in the add-labor row: a crew change does not alter the technician shown or its options", async () => {
    const { patch } = await open();
    const before = techOptions();
    type($(".wo-new-labor-hours"), "1");
    patch({ assigned_to_ids: [T3], assigned_to_names: ["Kim"] });
    expect(techOptions()).toEqual(before);
    expect($(".wo-labor-technician").value).toBe(T1);
  });

  it("an untouched add-labor row takes the new crew", async () => {
    const { patch } = await open();
    patch({ assigned_to_ids: [T3], assigned_to_names: ["Kim"] });
    expect(techOptions()[0]).toBe(T3);
    expect(techOptions()).not.toContain(T1);
  });

  it("an add-labor row held only by focus is deferred, so focus leaving catches it up", async () => {
    const { patch } = await open();
    $(".wo-new-labor-hours").focus();
    const { deferred } = patch({ assigned_to_ids: [T3], assigned_to_names: ["Kim"] });
    expect(techOptions()).toContain(T1);
    expect(deferred).toBe(true);
  });

  it("an add-labor row with a non-default technician picked is left alone", async () => {
    const { patch } = await open();
    $(".wo-labor-technician").value = T2;
    patch({ assigned_to_ids: [T3], assigned_to_names: ["Kim"] });
    expect(techOptions()).toContain(T2);
    expect($(".wo-labor-technician").value).toBe(T2);
  });
});

describe("SMR lines", () => {
  const smr = { smr: true, entry_mode: "retroactive", items: [], smr_lines: [smrLine(1), smrLine(2)] };

  it("an SMR entry row in edit mode keeps its line id, fields, Save changes label and visible Cancel; the lines around it update", async () => {
    const { patch } = await open(smr);
    byId(`wo-smrline-${smrLine(1).id}`).querySelector('[data-action="smr-edit-line"]').click();
    const row = byId("wo-add-smr");
    await vi.waitFor(() => expect(row.dataset.lineId).toBe(smrLine(1).id));
    row.querySelector(".wo-smr-a-name").blur();
    patch({ smr_lines: [smrLine(1), smrLine(2, { worker_name: "Renamed" }), smrLine(3)] });
    expect(byId("wo-add-smr")).toBe(row);
    expect(row.dataset.lineId).toBe(smrLine(1).id);
    expect(row.querySelector(".wo-smr-a-name").value).toBe("Worker 1");
    expect(row.querySelector(".wo-smr-a-hours").value).toBe("3.0");
    expect(row.querySelector('[data-action="smr-add-line"]').textContent).toBe("Save changes");
    expect(row.querySelector('[data-action="smr-cancel-line"]').hidden).toBe(false);
    expect(byId(`wo-smrline-${smrLine(2).id}`).textContent).toContain("Renamed");
    expect(byId(`wo-smrline-${smrLine(3).id}`)).not.toBeNull();
  });

  it("a typed SMR hours box stays while its row's data-line takes the server's snapshot", async () => {
    const { patch } = await open(smr);
    type(byId(`wo-smrline-hours-${smrLine(1).id}`), "4.5");
    patch({ smr_lines: [smrLine(1, { vendor: "Belfor" }), smrLine(2)] });
    const row = byId(`wo-smrline-${smrLine(1).id}`);
    expect(JSON.parse(row.dataset.line).vendor).toBe("Belfor");
    expect(row.querySelector(".wo-smr-l-hours").value).toBe("4.5");
    expect(msg().textContent).toBe("");
  });
});

describe("open editors", () => {
  it("an open charge editor stays, and its Cancel still restores the cell", async () => {
    const { detail, patch } = await open();
    byId(`wo-line-${id(1)}`).querySelector(".wo-edit-charge-btn").click();
    const row = byId(`wo-line-${id(1)}`);
    expect(row.querySelector(".charge-editor")).not.toBeNull();
    patch({ items: [item(1, { item_name: "Lamp" }), ...detail.items.slice(1)] });
    expect(byId(`wo-line-${id(1)}`)).toBe(row);
    expect(row.querySelector(".charge-editor")).not.toBeNull();
    row.querySelector(".charge-cancel").click();
    expect(row.querySelector(".charge-editor")).toBeNull();
    expect(row.querySelector(".wo-edit-charge-btn")).not.toBeNull();
  });

  it("an open Edit details form is untouched, the action bar updates, and deferred is true", async () => {
    const { patch } = await open();
    const editor = byId("wo-edit-card");
    editor.open = true;
    type(editor.querySelector(".wo-edit-location"), "Typed");
    const markup = editor.innerHTML;
    const bar = byId("wo-sec-actions").textContent;
    const { deferred } = patch({ status: "in_progress", location: "Server" });
    expect(byId("wo-edit-card")).toBe(editor);
    expect(editor.innerHTML).toBe(markup);
    expect(editor.querySelector(".wo-edit-location").value).toBe("Typed");
    expect(byId("wo-sec-actions").textContent).not.toBe(bar);
    expect(deferred).toBe(true);
  });

  it("a closed Edit details form takes the server's values", async () => {
    const { patch } = await open();
    const { deferred } = patch({ location: "Lobby" });
    expect($(".wo-edit-location").value).toBe("Lobby");
    expect(deferred).toBe(false);
  });

  it("a focused, unchanged field is left alone and deferred is true", async () => {
    const { detail, patch } = await open();
    const qty = byId(`wo-line-qty-${id(1)}`);
    qty.focus();
    const { deferred } = patch({ items: [item(1, { quantity: "9" }), ...detail.items.slice(1)] });
    expect(qty.value).toBe("1");
    expect(deferred).toBe(true);
  });

  it("the entry-mode select follows the server after the user changed it earlier", async () => {
    const { patch } = await open();
    byId("wo-mode-select").value = "retroactive";
    patch({ description: "Something else" });
    expect(byId("wo-mode-select").value).toBe("dispense");
  });
});

describe("tabs, message lines and the notes gate", () => {
  it("the tab the user was on stays selected, also when the patch adds a section that is open by default", async () => {
    const { patch } = await open();
    $('.wo-tab[data-wo-tab="materials"]').click();
    patch({ description: "Changed" });
    expect(cardBody().dataset.woTab).toBe("materials");
    patch({ smr: true, entry_mode: "retroactive", smr_lines: [smrLine(1)] });
    expect(byId("wo-sec-invoice")).not.toBeNull();
    expect(byId("wo-sec-invoice").open).toBe(false);
    expect(byId("wo-sec-labor").open).toBe(false);
    expect(byId("wo-sec-materials").open).toBe(true);
    expect(cardBody().dataset.woTab).toBe("materials");
    expect($('.wo-tab[data-wo-tab="materials"]').getAttribute("aria-selected")).toBe("true");
  });

  it("both message lines keep their text and class, and the message line stays last", async () => {
    const { patch } = await open();
    Object.assign(msg(), { textContent: "Saved.", className: "success" });
    Object.assign(byId("wo-notes-msg"), { textContent: "Note saved.", className: "success" });
    patch({ items: [item(5)], status: "in_progress" });
    expect([msg().textContent, msg().className]).toEqual(["Saved.", "success"]);
    expect([byId("wo-notes-msg").textContent, byId("wo-notes-msg").className]).toEqual(["Note saved.", "success"]);
    expect(cardBody().lastElementChild).toBe(msg());
  });

  it("a crew-lock hint that appears lands at the top, not in the message line", async () => {
    const { patch } = await open({ role: "technician", prep: (d, me) => { d.assigned_to_ids = [me.id]; } });
    patch({ assigned_to_ids: [T1], assigned_to_names: ["Pat"] });
    expect(cardBody().firstElementChild.id).toBe("wo-sec-lock");
    expect(msg().textContent).toBe("");
    expect(cardBody().lastElementChild).toBe(msg());
  });

  const gated = { prior_work: PRIOR, notes: "Ann Lee began work" };
  const begin = () => $('[data-action="start-tracking-wo"]');

  it("an acknowledged notes gate stays unlocked when the notes did not change", async () => {
    const { patch } = await open(gated);
    $('[data-action="ack-notes-wo"]').click();
    await vi.waitFor(() => expect(card().dataset.notesAck).toBe("1"));
    patch({ description: "Changed" });
    expect($('[data-action="ack-notes-wo"]').hidden).toBe(true);
    expect(begin().disabled).toBe(false);
    expect(begin().hasAttribute("title")).toBe(false);
  });

  it("new notes after an acknowledgement lock Begin Charging again and clear notesAck", async () => {
    const { patch } = await open(gated);
    $('[data-action="ack-notes-wo"]').click();
    await vi.waitFor(() => expect(card().dataset.notesAck).toBe("1"));
    patch({ notes: "Ann Lee began work\nLee: breaker is live" });
    expect($('[data-action="ack-notes-wo"]').hidden).toBe(false);
    expect(begin().disabled).toBe(true);
    expect(card().dataset.notesAck).toBeUndefined();
  });

  it("a typed note whose box the server removed (crew lock) raises the dropped-input message", async () => {
    const { patch } = await open({ role: "technician", prep: (d, me) => { d.assigned_to_ids = [me.id]; } });
    type(byId("wo-notes-input"), "Breaker is off");
    patch({ assigned_to_ids: [T1], assigned_to_names: ["Pat"] });
    expect(byId("wo-notes-input")).toBeNull();
    expect(msg().textContent).toBe(DROPPED);
  });
});

describe("focus and scroll", () => {
  it("an update that removes the focused row does not throw and leaves focus in the document", async () => {
    const { detail, patch } = await open();
    byId(`wo-line-qty-${id(2)}`).focus();
    expect(() => patch({ items: [detail.items[0]] })).not.toThrow();
    expect(document.contains(document.activeElement)).toBe(true);
  });

  it("a focused field that the patch moved is focused again with its caret", async () => {
    const { detail, patch } = await open();
    const qty = byId(`wo-line-qty-${id(1)}`);
    // jsdom gives a number input no caret; a text input stands in.
    qty.type = "text";
    qty.focus();
    type(qty, "12");
    qty.setSelectionRange(1, 1);
    // iOS Safari has no moveBefore, so a move during the patch can drop focus.
    // jsdom keeps it; this stub drops it on the first row move, as the phone may.
    const insertBefore = Node.prototype.insertBefore;
    let dropped = false;
    vi.spyOn(Node.prototype, "insertBefore").mockImplementation(function (node, ref) {
      const result = insertBefore.call(this, node, ref);
      if (!dropped && node.classList?.contains("wo-item") && document.activeElement === qty) {
        dropped = true;
        qty.blur();
      }
      return result;
    });
    const [a, b, c] = detail.items;
    patch({ items: [b, c, a] });
    expect(dropped).toBe(true);
    expect(rowIds(".wo-item")).toEqual([id(2), id(3), id(1)].map((x) => `wo-line-${x}`));
    expect(document.activeElement).toBe(qty);
    expect([qty.selectionStart, qty.selectionEnd]).toEqual([1, 1]);
  });

  function stubLayout(supports) {
    vi.stubGlobal("CSS", { supports: () => supports });
    vi.spyOn(Element.prototype, "getBoundingClientRect")
      .mockImplementationOnce(() => ({ top: 100, bottom: 200 }))
      .mockImplementation(() => ({ top: 160, bottom: 260 }));
    const scrollBy = vi.fn();
    vi.stubGlobal("scrollBy", scrollBy);
    window.scrollBy = scrollBy;
    return scrollBy;
  }

  it("without native scroll anchoring, the page scrolls by the amount the anchor moved", async () => {
    const { patch } = await open();
    const scrollBy = stubLayout(false);
    patch({ items: [item(5), item(1)] });
    expect(scrollBy).toHaveBeenCalledWith(0, 60);
  });

  it("with native scroll anchoring, the page is not scrolled by the patch", async () => {
    const { patch } = await open();
    const scrollBy = stubLayout(true);
    patch({ items: [item(5), item(1)] });
    expect(scrollBy).not.toHaveBeenCalled();
  });
});

describe("conflicts and the action bar", () => {
  it("a typed quantity whose saved value someone else changed is kept, outlined, and the message line warns that saving replaces theirs", async () => {
    const { detail, patch } = await open();
    const qty = byId(`wo-line-qty-${id(1)}`);
    type(qty, "5");
    patch({ items: [item(1, { quantity: "3" }), ...detail.items.slice(1)] });
    expect(qty.value).toBe("5");
    expect(qty.classList.contains("wo-field-conflict")).toBe(true);
    expect(msg().textContent).toBe(CONFLICT);
  });

  it("a typed quantity whose saved value did not change raises no warning", async () => {
    const { detail, patch } = await open();
    const qty = byId(`wo-line-qty-${id(1)}`);
    type(qty, "5");
    patch({ items: [item(1, { item_name: "Lamp" }), ...detail.items.slice(1)] });
    expect(qty.classList.contains("wo-field-conflict")).toBe(false);
    expect(msg().textContent).toBe("");
  });

  it("across every pair of statuses and every role, no surviving element changes its data-action", async () => {
    mountShell();
    const html = await importView("views/workOrderCardHtml.js");
    const live = await importView("views/workOrderLiveBody.js");
    const host = document.getElementById("work-orders-list");
    const statuses = ["created", "assigned", "in_progress", "on_hold", "ready_to_complete", "completed", "review"];
    const roles = [["owner", false], ["supervisor", false], ["admin", false], ["technician", true], ["technician", false]];
    for (const [role, crew] of roles) {
      const me = await setTestUser({ role });
      const ids = crew ? [me.id] : [T1];
      for (const smr of [false, true]) {
        const base = { smr, assigned_to_ids: ids, assigned_to_names: ids.map(() => "Crew"), items: [item(1)],
          smr_lines: smr ? [smrLine(1)] : [], notes: "n" };
        for (const from of statuses) {
          for (const to of statuses) {
            host.innerHTML = `<details class="wo-card" open><summary></summary><div class="wo-body"></div></details>`;
            const body = host.querySelector(".wo-body");
            html.renderBody(workOrderDetail({ ...base, status: from, active_labor_session: null }), body);
            const before = [...body.querySelectorAll("[data-action]")].map((el) => [el, el.dataset.action]);
            live.patchBodyLive(workOrderDetail({ ...base, status: to, smr_stage: smr ? "ready" : null,
              active_labor_session: to === "in_progress" ? { started_at: "2026-11-15T14:00:00Z" } : null }),
            body, host.firstElementChild);
            const changed = before.filter(([el, action]) => el.isConnected && el.dataset.action !== action);
            expect(changed.map(([, a]) => a), `${role}/${crew}/${smr}/${from}->${to}`).toEqual([]);
          }
        }
      }
    }
  }, 120_000); // 490 full renders + patches: ~20 s alone, ~70 s beside the rest of the suite

  it("sections and the More menu keep the open state the user gave them", async () => {
    const { patch } = await open();
    $('.wo-tab[data-wo-tab="materials"]').click();
    const more = $(".wo-more");
    more.open = true;
    patch({ status: "in_progress", ...{ prior_work: PRIOR, notes: "Ann Lee began work\nmore" } });
    expect($(".wo-more").open).toBe(true);
    expect(byId("wo-sec-materials").open).toBe(true);
    expect(byId("wo-sec-notes").open).toBe(false);
  });

  it("actionsSettling is true after the action bar's buttons change, false after 500 ms, and false when they did not change", async () => {
    const { live, patch } = await open();
    vi.useFakeTimers({ toFake: ["Date"] });
    vi.setSystemTime(new Date("2026-11-15T12:00:00Z"));
    patch({ description: "Changed" });
    expect(live.actionsSettling(card())).toBe(false);
    patch({ status: "in_progress" });
    expect(live.actionsSettling(card())).toBe(true);
    vi.setSystemTime(new Date("2026-11-15T12:00:00.499Z"));
    expect(live.actionsSettling(card())).toBe(true);
    vi.setSystemTime(new Date("2026-11-15T12:00:00.500Z"));
    expect(live.actionsSettling(card())).toBe(false);
  });
});
