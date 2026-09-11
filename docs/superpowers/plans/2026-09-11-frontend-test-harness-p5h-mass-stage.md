# Frontend Test Harness — P5h (`views/massStage.js` + `helpers/actionAudit.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: NOT STARTED. Do not begin until P5a–P5g are committed on `main` and the user gives an explicit go-ahead. This is the last P5 chunk; Task 8 closes the phase.**

**Goal:** Characterization coverage for `backend/static/views/massStage.js` (573 lines, thirteen delegated actions), and `tests/frontend/helpers/actionAudit.js` — P2's action-coverage meta-test lifted into a helper that every delegated view can run, applied here to Mass Stage, Items, and (unchanged in result) Work Orders.

**Architecture:** Tests only. `massStage.js` imports `nav.js` and the work-order barrel but fetches nothing at import; `loadStages()` is the entry point, and every stage detail loads lazily when its `<details>` opens (jsdom fires `toggle` asynchronously, so the fixture awaits it). The audit is the phase's other deliverable: `auditActions({ sources, fragments, frozen, behaviourDir, renderedPattern, handledPattern })` produces the same three checks P2 wrote by hand (rendered-vs-handled orphans, the frozen inventory, every action named by a behaviour test). `actionCoverage.test.js` is re-pointed at it first, with its export-surface tests untouched, and its result must be identical before and after — that is the gate for applying the audit anywhere else. Items' actions are `<option value="…">` in a `<select>`, not `data-action`, so the audit takes a `renderedPattern`.

**Tech Stack:** Vitest, jsdom, @testing-library/dom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md` (P5h bullets are the requirement set)
**Depends on:** P2 (`actionCoverage.test.js`), P5c (`items.test.js`), P5d (`helpers/requests.js`, `helpers/dialogs.js`), P5a (`pageHandlers()`, media stubs).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), the shell's confirm overlay, `document` events.
- `onUnhandledRequest: "error"` stays on.
- `mountView()` before import — `massStage.js` captures 7 element ids at import.
- The audit refactor is behaviour-preserving: `actionCoverage.test.js` passes with the same test names and count before and after Task 1, verified by running it and diffing the reporter output.
- Five new factories pass the drift guard against `backend/app/schemas/mass_stages.py`; rows added in the same commit.
- Commit messages end with the attribution lines the session provides.

## Entry gate — verify before Task 1

- [ ] P5a–P5g on `main`; `tests/frontend/views/items.test.js` names its four actions as literal strings (`"edit"`, `"correct"`, `"notes"`, `"delete"`) — the audit greps for them.
- [ ] `npx vitest run tests/frontend/views/workOrders/actionCoverage.test.js --reporter=verbose > /tmp/audit-before.txt` (or the scratchpad); keep it for the Task 1 diff.
- [ ] `npm test` green to completion; record count and wall-clock.

## The thirteen Mass Stage actions

| Action | Where rendered | Confirm | Request |
| --- | --- | --- | --- |
| `pick-item` | search results | — | none (fills the add-item row) |
| `open-wo` | slot | — | none; `focusWorkOrder` + `showPage("work-orders")` |
| `add-work-order` | planning body | — | `POST /mass-stages/{id}/work-orders` |
| `remove-slot` | planning slot | yes | `DELETE /mass-stages/{id}/work-orders/{slot}` |
| `add-item` | planning slot | — | `POST /mass-stages/{id}/work-orders/{slot}/items` |
| `edit-item` | planning item | — | `PATCH …/items/{stageItem}` |
| `remove-item` | planning item | — | `DELETE …/items/{stageItem}` |
| `save-stage` | planning body | yes | `PATCH /mass-stages/{id}` `{status:"loading"}` |
| `load-item` | loading merged row | yes | `POST /mass-stages/{id}/load` |
| `return-item` | loading merged row | — | `POST /mass-stages/{id}/return` |
| `complete-stage` | loading body | yes | `PATCH /mass-stages/{id}` `{status:"completed"}` |
| `reuse-stage` | completed body | yes | `POST /mass-stages/{id}/reuse` |
| `delete-stage` | every body | yes (two copies) | `DELETE /mass-stages/{id}` |

After every mutating action except `open-wo`/`pick-item`: `refreshStage` (re-`GET /mass-stages/{id}`, open slots preserved) or `loadStages()` (the list again).

---

### Task 1: `helpers/actionAudit.js`, and re-point `actionCoverage.test.js` with no behaviour change

**Files:**
- Create: `tests/frontend/helpers/actionAudit.js`
- Modify: `tests/frontend/views/workOrders/actionCoverage.test.js` (the three action describes → one `auditActions` call; the export-surface describe stays as-is)

**Interfaces:**
- `auditActions({ name, sources, fragments = [], frozen, behaviourDir, behaviourExclude = [], renderedPattern = /data-action="([a-z-]+)"/g, handledPattern = /action === "([a-z-]+)"/g })` — registers a `describe(name)` containing exactly P2's four `it`s: "is exactly the frozen N", "renders no action the delegation does not handle", "handles no action nothing renders", "every action is exercised by a behaviour test → names the ones that are not". `sources`/`fragments` are absolute paths; `behaviourDir` is scanned for `*.test.js` minus `behaviourExclude`.
- Also exports the pure pieces for tests that want them: `readActionInventory({ sources, fragments, renderedPattern, handledPattern })` → `{ rendered: Set, handled: Set }`, `REPO_ROOT`, `VIEWS_DIR`, `PAGES_DIR`.

- [ ] **Step 1: Write the helper**

```js
// tests/frontend/helpers/actionAudit.js
//
// P2's mechanical completeness guarantee, generalised. A characterization
// suite is only as good as its coverage, and "we think every branch has a
// test" is not checkable by reading. This greps a view's delegated actions
// out of its source, freezes the inventory, checks rendered and handled
// agree, and fails BY NAME when a behaviour file never mentions one.
//
// Nothing here is view-specific: what counts as "rendered" and "handled" is
// a pair of regexes, because the views disagree -- Work Orders and Mass Stage
// write `data-action="x"` and branch on `action === "x"`; Items writes
// `<option value="x">` and branches the same way.

import { readFileSync, readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { describe, expect, it } from "vitest";

const HELPERS_DIR = dirname(fileURLToPath(import.meta.url));
export const REPO_ROOT = join(HELPERS_DIR, "..", "..", "..");
export const VIEWS_DIR = join(REPO_ROOT, "backend", "static", "views");
export const PAGES_DIR = join(REPO_ROOT, "backend", "static", "pages");

const matchAll = (text, pattern) => [...text.matchAll(pattern)].map((m) => m[1]);
const readAll = (paths) => paths.map((p) => readFileSync(p, "utf8")).join("\n");

export function readActionInventory({
  sources, fragments = [],
  renderedPattern = /data-action="([a-z-]+)"/g,
  handledPattern = /action === "([a-z-]+)"/g,
}) {
  const source = readAll(sources);
  const fragment = readAll(fragments);
  return {
    rendered: new Set([...matchAll(source, renderedPattern), ...matchAll(fragment, renderedPattern)]),
    handled: new Set(matchAll(source, handledPattern)),
  };
}

export function auditActions({
  name, sources, fragments = [], frozen, behaviourDir, behaviourExclude = [],
  renderedPattern, handledPattern,
}) {
  const { rendered, handled } = readActionInventory({ sources, fragments, renderedPattern, handledPattern });
  const behaviourFiles = readdirSync(behaviourDir)
    .filter((f) => f.endsWith(".test.js") && !behaviourExclude.includes(f));
  const behaviourText = readAll(behaviourFiles.map((f) => join(behaviourDir, f)));

  describe(name, () => {
    describe("the action inventory", () => {
      it(`is exactly the frozen ${frozen.length}`, () => {
        expect([...rendered].sort()).toEqual([...frozen].sort());
      });
      it("renders no action the delegation does not handle", () => {
        const orphans = [...rendered].filter((a) => !handled.has(a)).sort();
        expect(orphans, `rendered but never handled: ${orphans.join(", ")}`).toEqual([]);
      });
      it("handles no action nothing renders", () => {
        const orphans = [...handled].filter((a) => !rendered.has(a)).sort();
        expect(orphans, `handled but never rendered: ${orphans.join(", ")}`).toEqual([]);
      });
    });
    describe("every action is exercised by a behaviour test", () => {
      it("names the ones that are not", () => {
        expect(behaviourFiles.length).toBeGreaterThan(0);
        const missing = frozen.filter((a) => !behaviourText.includes(`"${a}"`));
        expect(missing, `no test mentions: ${missing.join(", ")}`).toEqual([]);
      });
    });
  });
}
```

One deliberate tightening, called out so the diff in Step 3 is understood: the behaviour check matches the **quoted** action (`"add-item"`), where P2 matched the bare substring. P2's bare match let `"add-item"` be satisfied by `"add-item-row"` or by prose in a comment; the quoted form is what a `data-action`/`selectOptions` literal looks like. If any of the 26 stops matching under the quoted form, that is a real gap P2 missed — add the literal to the behaviour test that covers it, do not loosen the pattern.

- [ ] **Step 2: Re-point `actionCoverage.test.js`**

Replace everything from `const rendered = new Set([` through the end of the `describe("every action is exercised…")` block with:

```js
import { auditActions, PAGES_DIR } from "../../helpers/actionAudit.js";

auditActions({
  name: "Work Orders actions",
  sources: SOURCE_FILES,
  fragments: [join(PAGES_DIR, "work-orders.html")],
  frozen: ACTIONS,
  behaviourDir: HERE,
  behaviourExclude: ["actionCoverage.test.js"],
});
```

Keep `SOURCE_FILES`, `ACTIONS`, `EXPORTS`, `declaredNames`, and the whole `describe("the export surface")` block. Delete the now-unused `FRAGMENT`, `fragment`, `rendered`, `handled`, `behaviourFiles`, `behaviourText`, `matchAll` (keep `matchAll` only if `declaredNames` still uses it — it does; keep it).

- [ ] **Step 3: Diff the result**

Run: `npx vitest run tests/frontend/views/workOrders/actionCoverage.test.js --reporter=verbose > <scratch>/audit-after.txt`
Diff against the before file: same test names (the outer `describe` gains the "Work Orders actions" wrapper — that is the only allowed difference), same pass count, zero failures. If "names the ones that are not" now fails, see the Step 1 note.

- [ ] **Step 4: Commit**

```bash
git add tests/frontend/helpers/actionAudit.js tests/frontend/views/workOrders/actionCoverage.test.js
git commit -m "test(p5h): lift the action audit into a helper; re-point Work Orders with no behaviour change"
```

---

### Task 2: Apply the audit to Items

**Files:** Create `tests/frontend/views/itemsActionCoverage.test.js`.

- [ ] **Step 1: Write it**

```js
// tests/frontend/views/itemsActionCoverage.test.js
//
// Items delegates on a <select> `change`, so "rendered" is an <option value>,
// not a data-action. Same guarantee, different regex.
import { readdirSync } from "node:fs";
import { dirname, join } from "node:path";
import { fileURLToPath } from "node:url";
import { auditActions, VIEWS_DIR } from "../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

auditActions({
  name: "Items row actions",
  sources: [join(VIEWS_DIR, "items.js")],
  frozen: ["correct", "delete", "edit", "notes"],
  behaviourDir: HERE,
  // Only items.test.js may satisfy the check; the other view files in this
  // directory mention "delete" and "edit" for their own reasons.
  behaviourExclude: readdirSync(HERE).filter((f) => f !== "items.test.js"),
  renderedPattern: /<option value="([a-z-]+)">/g,
});
```

The placeholder `<option value="" disabled selected>` does not match: the pattern requires `[a-z-]+`, so only the four real options are counted.

- [ ] **Step 2: Run** → PASS with 4 frozen. Then delete the `"correct"` test body from `items.test.js` locally (or comment its `selectOptions(actionSelect(0), "correct")` line), run again → "no test mentions: correct". Restore. That is the parent plan's success check, applied to Items.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/itemsActionCoverage.test.js
git commit -m "test(p5h): action audit over the Items row actions"
```

---

### Task 3: Mass Stage factories, drift rows, and the fixture

**Files:**
- Modify: `tests/frontend/helpers/factories.js` (append five), `tests/frontend/unit/api.endpoints.test.js` (five rows)
- Create: `tests/frontend/helpers/massStage.js`
- Test: `tests/frontend/views/massStage.test.js` (smoke)

**Interfaces:**
- `massStageSummary(overrides)`, `massStageDetail(overrides)`, `stageWorkOrder(overrides)`, `stageItem(overrides)`, `mergedItem(overrides)`.
- `helpers/massStage.js`:
  - `mountMassStage({ role = "supervisor", stages = [], details = [], items = [], users = [], handlers = [] })` → `{ mod }`. Registers `GET /mass-stages/` (summaries), `GET /mass-stages/:id` (details keyed by id, 404 otherwise), `GET /items/`, `GET /users/`. Does not load.
  - `openStages(opts)` → mount + `await mod.loadStages({ refreshReferenceData: true })`.
  - `openCard(stageId)` → sets the card's `open`, awaits the `toggle`-driven detail load (`data-loaded="1"`), returns the card element.
  - `respond(method, path, body, { status })` — same shape as P2's helper.
  - `el`: `list`, `listMessage`, `communitySelect`, `communityNew`, `buildingInput`, `createBtn`, `createMessage`; `groupEls()`, `cardEls()`, `card(stageId)`, `stageMessage(card)`, `slotEls(card)`.

- [ ] **Step 1: Write the smoke test**

```js
// tests/frontend/views/massStage.test.js
import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server, pageHandlers } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { answerConfirm, confirmOverlay, confirmTitle } from "../helpers/dialogs.js";
import {
  cardEls, el, groupEls, mountMassStage, openCard, openStages, respond, restoreMassStage, slotEls, stageMessage,
} from "../helpers/massStage.js";
import {
  item as itemFactory, massStageDetail, massStageSummary, mergedItem, stageItem, stageWorkOrder, user as userFactory,
} from "../helpers/factories.js";

afterEach(() => restoreMassStage());
const user = () => userEvent.setup();

describe("mountMassStage", () => {
  it("mounts with an empty list and nothing fetched", async () => {
    const { mod } = await mountMassStage();
    expect(typeof mod.loadStages).toBe("function");
    expect(el.list().children).toHaveLength(0);
    expect(requests()).toHaveLength(0);
  });
});
```

- [ ] **Step 2: Run to verify it fails** — missing helper.
- [ ] **Step 3: Append the factories**

```js
// --- Mass stage (backend/app/schemas/mass_stages.py) ------------------------
export function stageItem(overrides = {}) {
  return {
    id: uuid(), item_id: uuid(), item_name: "Bulb", item_barcode: "B1",
    item_quantity: "10", planned_quantity: "2", loaded_quantity: "0", returned_quantity: "0",
    ...overrides,
  };
}

export function stageWorkOrder(overrides = {}) {
  return {
    id: uuid(), work_order_id: uuid(), work_order_number: "7001", unit_number: "12",
    status: "assigned", sort_order: 0, assigned_to_id: null, assigned_to_name: null, items: [],
    ...overrides,
  };
}

export function mergedItem(overrides = {}) {
  return {
    item_id: uuid(), item_name: "Bulb", item_barcode: "B1", on_hand: "10",
    planned_total: "4", loaded_total: "0", returned_total: "0", overflow: "0",
    net_consumed: "0", remaining_to_load: "4",
    ...overrides,
  };
}

export function massStageSummary(overrides = {}) {
  return {
    id: uuid(), community: "Scholars", building_name: "19", status: "planning",
    unit_count: 0, item_count: 0, created_at: "2026-09-10T12:00:00Z",
    ...overrides,
  };
}

export function massStageDetail(overrides = {}) {
  return {
    id: uuid(), community: "Scholars", building_name: "19", status: "planning",
    created_at: "2026-09-10T12:00:00Z", work_orders: [], merged_items: [],
    ...overrides,
  };
}
```

Drift rows: `["stageItem", "backend/app/schemas/mass_stages.py"]`, `["stageWorkOrder", …]`, `["mergedItem", …]`, `["massStageSummary", …]`, `["massStageDetail", …]`.

- [ ] **Step 4: Write `helpers/massStage.js`**

```js
// tests/frontend/helpers/massStage.js
//
// The Mass Stage fixture. massStage.js fetches nothing at import; loadStages()
// fetches the reference data and the summary list, and each stage's detail
// loads when its <details> opens -- jsdom dispatches `toggle` asynchronously,
// so openCard() waits for the module to mark the card loaded.

import { expect, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "./handlers.js";
import { mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { restoreMediaStubs, stubPermissions, stubUserMedia } from "./media.js";
import { startRecording, stopRecording, clearRequests } from "./requests.js";

const byId = (id) => () => document.getElementById(id);
export const el = {
  list: byId("mass-stage-list"), listMessage: byId("mass-stage-list-message"),
  communitySelect: byId("mass-stage-community-select"), communityNew: byId("mass-stage-community-new"),
  buildingInput: byId("mass-stage-building-input"), createBtn: byId("mass-stage-create-btn"),
  createMessage: byId("mass-stage-create-message"),
};
export const groupEls = () => Array.from(el.list().querySelectorAll("details.community-group"));
export const cardEls = () => Array.from(el.list().querySelectorAll("details.stage-card"));
export const card = (stageId) => el.list().querySelector(`details.stage-card[data-stage-id="${stageId}"]`);
export const stageMessage = (cardEl) => cardEl.querySelector(".ms-stage-message");
export const slotEls = (cardEl) => Array.from(cardEl.querySelectorAll("details.room-card"));

export const state = { stages: [], details: new Map() };

export function respond(method, path, body, { status = 200 } = {}) {
  server.use(http[method.toLowerCase()](path, () =>
    body === null && status === 204 ? new HttpResponse(null, { status }) : HttpResponse.json(body, { status })));
}

export async function mountMassStage({ role = "supervisor", stages = [], details = [], items = [], users = [], handlers = [] } = {}) {
  state.stages = stages;
  state.details = new Map(details.map((d) => [String(d.id), d]));
  server.use(
    ...handlers,
    http.get("/mass-stages/:id", ({ params }) => {
      const d = state.details.get(params.id);
      return d ? HttpResponse.json(d) : HttpResponse.json({ detail: "Not found" }, { status: 404 });
    }),
    http.get("/mass-stages/", () => HttpResponse.json(state.stages)),
    http.get("/items/", () => HttpResponse.json(items)),
    http.get("/users/", () => HttpResponse.json(users)),
  );
  stubUserMedia();
  stubPermissions("prompt");
  await setTestUser({ role });
  startRecording();
  const mod = await mountView("views/massStage.js");
  clearRequests();
  return { mod };
}

export async function openStages(opts = {}) {
  const mounted = await mountMassStage(opts);
  await mounted.mod.loadStages({ refreshReferenceData: true });
  clearRequests();
  return mounted;
}

// Open a community group (if closed) and a stage card; wait for its detail.
export async function openCard(stageId) {
  const c = card(stageId);
  const group = c.closest("details.community-group");
  if (group && !group.open) group.open = true;
  c.open = true;
  await vi.waitFor(() => expect(c.dataset.loaded).toBe("1"));
  return c;
}

export function restoreMassStage() {
  stopRecording();
  restoreMediaStubs();
}
```

- [ ] **Step 5: Run the smoke test and the drift test** → PASS. If `openCard` times out in a later task, jsdom's `toggle` did not fire on the property set: fall back to `c.dispatchEvent(new Event("toggle"))` after setting `open` and note it in the helper.
- [ ] **Step 6: Commit**

```bash
git add tests/frontend/helpers/factories.js tests/frontend/unit/api.endpoints.test.js tests/frontend/helpers/massStage.js tests/frontend/views/massStage.test.js
git commit -m "test(p5h): mass-stage factories and fixture"
```

---

### Task 4: `loadStages`, the list tree, lazy detail, create stage, community select

**Files:** Modify `tests/frontend/views/massStage.test.js`.

- [ ] **Step 1: Write the tests**

```js
describe("loadStages", () => {
  it("refreshReferenceData: items and users fetched, technicians filtered by canBeWorkOrderTechnician", async () => {
    const users = [userFactory({ role: "technician", full_name: "Tech One" }), userFactory({ role: "supervisor", full_name: "Sup" }),
      userFactory({ role: "admin", full_name: "Adm" }), userFactory({ role: "techfm_oa", full_name: "OA" })];
    const detail = massStageDetail();
    const { mod } = await mountMassStage({ stages: [massStageSummary({ id: detail.id })], details: [detail], users });
    await mod.loadStages({ refreshReferenceData: true });
    expect(requests().map((r) => r.url)).toEqual(["/items/", "/users/", "/mass-stages/"]);
    await openCard(detail.id);
    const options = Array.from(card(detail.id).querySelector(".ms-add-assignee").options).map((o) => o.textContent);
    expect(options).toEqual(["Unassigned", "Tech One", "Sup"]);
  });

  it("without refreshReferenceData the caches are reused; user-names-updated invalidates techs", async () => {
    const { mod } = await openStages({ stages: [] });
    await mod.loadStages();
    expect(requests().map((r) => r.url)).toEqual(["/mass-stages/"]);
    clearRequests();
    document.dispatchEvent(new Event("user-names-updated"));
    await mod.loadStages();
    expect(requests().map((r) => r.url)).toEqual(["/users/", "/mass-stages/"]);
  });

  it("a failed reference load is swallowed; a failed list load renders the error", async () => {
    await openStages({ handlers: [http.get("/items/", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    expect(el.listMessage().textContent).toBe("");
    const { mod } = await mountMassStage({ handlers: [http.get("/mass-stages/", () => HttpResponse.json({ detail: "x" }, { status: 500 }))] });
    await mod.loadStages();
    expect(el.listMessage().className).toBe("error");
    expect(el.list().children).toHaveLength(0);
  });

  it("empty list: the hint; otherwise community groups sorted, buildings inside, status badge and meta", async () => {
    await openStages({ stages: [] });
    expect(el.list().querySelector("p.hint").textContent).toBe("No mass stages yet. Create one above.");
    await openStages({ stages: [
      massStageSummary({ community: "Scholars", building_name: "19", status: "planning", unit_count: 0, item_count: 0 }),
      massStageSummary({ community: "Centennial", building_name: "3", status: "loading", unit_count: 1, item_count: 2 }),
      massStageSummary({ community: "Centennial", building_name: "4", status: "completed", unit_count: 2, item_count: 5 }),
      massStageSummary({ community: null, building_name: "x" }),
    ] });
    expect(groupEls().map((g) => g.dataset.community)).toEqual(["Centennial", "Scholars", "Unfiled"]);
    expect(groupEls()[0].querySelector(".community-meta").textContent).toBe("2 buildings");
    expect(groupEls()[1].querySelector(".community-meta").textContent).toBe("1 building");
    const cards = cardEls();
    expect(cards[0].querySelector(".stage-status").className).toBe("stage-status stage-status-loading");
    expect(cards[0].querySelector(".stage-meta").textContent).toBe("1 unit · 2 items");
    expect(cards[1].querySelector(".stage-meta").textContent).toBe("2 units · 5 items");
    expect(cards[2].querySelector(".stage-meta").textContent).toBe("no units");
    expect(cards[0].querySelector(".stage-body .skel-card")).not.toBeNull(); // lazy body
  });

  it("opening a card fetches its detail once and recomputes the meta from distinct items", async () => {
    const shared = uuidLike();
    const detail = massStageDetail({ work_orders: [
      stageWorkOrder({ items: [stageItem({ item_id: shared }), stageItem()] }),
      stageWorkOrder({ items: [stageItem({ item_id: shared })] }),
    ] });
    await openStages({ stages: [massStageSummary({ id: detail.id })], details: [detail] });
    const c = await openCard(detail.id);
    expect(requestFor(`/mass-stages/${detail.id}`, "GET")).not.toBeNull();
    expect(c.querySelector(".stage-meta").textContent).toBe("2 units · 2 items");
    c.open = false; c.open = true;
    await new Promise((r) => setTimeout(r, 10));
    expect(requests().filter((r) => r.url === `/mass-stages/${detail.id}`)).toHaveLength(1);
  });

  it("a failing detail renders the error inside the card", async () => {
    const s = massStageSummary();
    await openStages({ stages: [s] });                  // no detail seeded → 404
    const c = card(s.id); c.closest("details.community-group").open = true; c.open = true;
    await vi.waitFor(() => expect(c.querySelector(".stage-body p.error")).not.toBeNull());
  });
});

const uuidLike = () => `00000000-0000-4000-8000-${String(Math.floor(Math.random() * 1e12)).padStart(12, "0")}`;

describe("create stage", () => {
  it("community select: seeds + used names sorted, New community reveals the input", async () => {
    await openStages({ stages: [massStageSummary({ community: "Aspen" })] });
    expect(Array.from(el.communitySelect().options).map((o) => o.value)).toEqual(["Aspen", "Centennial", "Cimarron", "Scholars", "__new__"]);
    expect(el.communityNew().hidden).toBe(true);
    await user().selectOptions(el.communitySelect(), "__new__");
    expect(el.communityNew().hidden).toBe(false);
  });

  it("validation: community first, then building; no request", async () => {
    await openStages();
    await user().selectOptions(el.communitySelect(), "__new__");
    await user().click(el.createBtn());
    expect(el.createMessage().textContent).toBe("Choose or enter a community.");
    await user().selectOptions(el.communitySelect(), "Scholars");
    await user().click(el.createBtn());
    expect(el.createMessage().textContent).toBe("Enter a building number.");
    expect(requestFor("/mass-stages/", "POST")).toBeNull();
  });

  it("posts, clears the form, reloads, and auto-opens the new community and card", async () => {
    const created = massStageDetail({ community: "Scholars", building_name: "19" });
    const { mod } = await openStages({ stages: [], details: [created] });
    respond("POST", "/mass-stages/", created, { status: 201 });
    server.use(http.get("/mass-stages/", () => HttpResponse.json([massStageSummary({ id: created.id, community: "Scholars", building_name: "19" })])));
    await user().type(el.buildingInput(), "19{Enter}");
    await vi.waitFor(() => expect(el.createMessage().textContent).toBe("Mass stage created."));
    expect(requestFor("/mass-stages/", "POST").body).toEqual({ community: "Scholars", building_name: "19" });
    expect(el.buildingInput().value).toBe("");
    expect(groupEls()[0].open).toBe(true);
    expect(card(created.id).open).toBe(true);
    await vi.waitFor(() => expect(card(created.id).dataset.loaded).toBe("1"));
    expect(mod).toBeTruthy();
  });

  it("a failing create shows friendlyError with the fallback", async () => {
    await openStages();
    respond("POST", "/mass-stages/", { detail: "" }, { status: 500 });
    await user().type(el.buildingInput(), "19");
    await user().click(el.createBtn());
    await vi.waitFor(() => expect(el.createMessage().className).toBe("error"));
  });
});
```

Request bodies verified against `api.js` on 2026-09-11: create `{ community, building_name }`; add-work-order `{ work_order_number, unit_number, assigned_to_id }`; add-item `{ item_id, planned_quantity }`; edit-item `{ planned_quantity }`; load/return `{ item_id, quantity }`. jsdom dispatches `toggle` when `open` is set (checked), so `openCard()` needs no manual event.

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/massStage.test.js
git commit -m "test(p5h): loadStages, the list tree, lazy detail, create stage"
```

---

### Task 5: Planning-body actions — `pick-item`, `add-item`, `edit-item`, `remove-item`, `add-work-order`, `remove-slot`, `open-wo`, `save-stage`

**Files:** Modify `tests/frontend/views/massStage.test.js`.

- [ ] **Step 1: Write the tests**

```js
async function planningCard({ slots = [stageWorkOrder()], items = [], role = "supervisor", users = [] } = {}) {
  const detail = massStageDetail({ status: "planning", work_orders: slots });
  const ctx = await openStages({ role, stages: [massStageSummary({ id: detail.id })], details: [detail], items, users });
  const c = await openCard(detail.id);
  clearRequests();
  return { ...ctx, detail, c, slot: slots[0] };
}
const S = (detail) => `/mass-stages/${detail.id}`;

describe("planning body", () => {
  it("renders slots, the add-work-order row with tech options, Save and Delete; tipHtml absent here", async () => {
    const { c, slot } = await planningCard({ slots: [stageWorkOrder({ unit_number: "12", work_order_number: "7001", assigned_to_name: "Pat", items: [stageItem()] })] });
    expect(slotEls(c)).toHaveLength(1);
    expect(c.querySelector(".room-title").textContent).toBe("Unit 12");
    expect(c.querySelector(".room-meta").textContent).toBe("WO 7001 · 1 items · Pat");
    expect(c.querySelector('[data-action="add-work-order"]')).not.toBeNull();
    expect(c.querySelector('[data-action="save-stage"]')).not.toBeNull();
    expect(c.querySelector('[data-action="delete-stage"]').dataset.stageLoaded).toBeUndefined();
    expect(c.querySelector(".ms-item .ms-onhand").textContent).toBe("On hand: 10");
    expect(c.querySelector(".ms-item .ms-short")).toBeNull();
    expect(slot).toBeTruthy();
  });

  it("a slot with no unit number renders a dash; a short item flags 'short by N'", async () => {
    const { c } = await planningCard({ slots: [stageWorkOrder({ unit_number: null, items: [stageItem({ planned_quantity: "15", item_quantity: "10" })] })] });
    expect(c.querySelector(".room-title").textContent).toBe("Unit —");
    expect(c.querySelector(".ms-short").textContent).toBe("short by 5");
  });

  it("pick-item: search filters the item cache, picking fills the row and focuses qty, no request", async () => {
    const bulb = itemFactory({ name: "Bulb A19", barcode: "111" });
    const { c } = await planningCard({ items: [bulb, itemFactory({ name: "Fuse", barcode: "222" })] });
    c.querySelector("details.room-card").open = true;
    await user().type(c.querySelector(".ms-item-search"), "bulb");
    const results = c.querySelector(".ms-item-results");
    expect(results.hidden).toBe(false);
    expect(results.querySelectorAll('[data-action="pick-item"]')).toHaveLength(1);
    await user().click(results.querySelector('[data-action="pick-item"]'));
    expect(c.querySelector(".ms-add-item").dataset.itemId).toBe(bulb.id);
    expect(c.querySelector(".ms-item-search").value).toBe("Bulb A19");
    expect(results.hidden).toBe(true);
    expect(document.activeElement).toBe(c.querySelector(".ms-item-qty"));
    expect(requests()).toHaveLength(0);
    await user().clear(c.querySelector(".ms-item-search"));
    await user().type(c.querySelector(".ms-item-search"), "zzz");
    expect(results.querySelector("p.hint").textContent).toBe("No matching items.");
    expect(c.querySelector(".ms-add-item").dataset.itemId).toBeUndefined(); // typing again drops the pick
  });

  it("add-item: needs a pick, then a positive qty; posts and refreshes with the slot kept open", async () => {
    const bulb = itemFactory({ name: "Bulb" });
    const { c, detail, slot } = await planningCard({ items: [bulb] });
    const room = c.querySelector("details.room-card"); room.open = true;
    await user().click(c.querySelector('[data-action="add-item"]'));
    expect(stageMessage(c).textContent).toBe("Search and pick an item first.");
    await user().type(c.querySelector(".ms-item-search"), "bulb");
    await user().click(c.querySelector('[data-action="pick-item"]'));
    await user().click(c.querySelector('[data-action="add-item"]'));
    expect(stageMessage(c).textContent).toBe("Enter a quantity greater than zero.");
    await user().type(c.querySelector(".ms-item-qty"), "3");
    respond("POST", `${S(detail)}/work-orders/${slot.id}/items`, stageItem(), { status: 201 });
    state.details.set(detail.id, massStageDetail({ ...detail, work_orders: [stageWorkOrder({ ...slot, items: [stageItem({ item_name: "Bulb" })] })] }));
    await user().click(c.querySelector('[data-action="add-item"]'));
    await vi.waitFor(() => expect(c.querySelector(".ms-item")).not.toBeNull());
    expect(requestFor("/items", "POST").body).toEqual({ item_id: bulb.id, planned_quantity: 3 });
    expect(c.querySelector("details.room-card").open).toBe(true);   // refreshStage preserved it
  });

  it("edit-item: rejects 0, PATCHes planned_quantity, refreshes", async () => {
    const it0 = stageItem();
    const { c, detail, slot } = await planningCard({ slots: [stageWorkOrder({ items: [it0] })] });
    c.querySelector("details.room-card").open = true;
    const qty = c.querySelector(".ms-item-planned");
    await user().clear(qty); await user().type(qty, "0");
    await user().click(c.querySelector('[data-action="edit-item"]'));
    expect(stageMessage(c).textContent).toBe("Enter a quantity greater than zero.");
    await user().clear(qty); await user().type(qty, "7");
    respond("PATCH", `${S(detail)}/work-orders/${slot.id}/items/${it0.id}`, it0);
    await user().click(c.querySelector('[data-action="edit-item"]'));
    await vi.waitFor(() => expect(requestFor(`/items/${it0.id}`, "PATCH")).not.toBeNull());
    expect(requestFor(`/items/${it0.id}`, "PATCH").body).toEqual({ planned_quantity: 7 });
    await vi.waitFor(() => expect(requests().filter((r) => r.url === S(detail)).length).toBe(1));
  });

  it("remove-item: DELETE without confirm, then refresh", async () => {
    const it0 = stageItem();
    const { c, detail, slot } = await planningCard({ slots: [stageWorkOrder({ items: [it0] })] });
    c.querySelector("details.room-card").open = true;
    respond("DELETE", `${S(detail)}/work-orders/${slot.id}/items/${it0.id}`, null, { status: 204 });
    await user().click(c.querySelector('[data-action="remove-item"]'));
    await vi.waitFor(() => expect(requestFor(`/items/${it0.id}`, "DELETE")).not.toBeNull());
    expect(confirmOverlay().hidden).toBe(true);
  });

  it("add-work-order: needs a number; posts number, unit, assignee; a 404 surfaces in the stage message", async () => {
    const tech = userFactory({ role: "technician", full_name: "Tech" });
    const { c, detail } = await planningCard({ users: [tech] });
    await user().click(c.querySelector('[data-action="add-work-order"]'));
    expect(stageMessage(c).textContent).toBe("Enter a work order number.");
    await user().type(c.querySelector(".ms-unit-number"), "12");
    await user().type(c.querySelector(".ms-room-wo"), "7002");
    await user().selectOptions(c.querySelector(".ms-add-assignee"), tech.id);
    respond("POST", `${S(detail)}/work-orders`, { detail: "Work order not found" }, { status: 404 });
    await user().click(c.querySelector('[data-action="add-work-order"]'));
    await vi.waitFor(() => expect(stageMessage(c).className).toBe("error"));
    expect(requestFor("/work-orders", "POST").body).toEqual({ work_order_number: "7002", unit_number: "12", assigned_to_id: tech.id });
    respond("POST", `${S(detail)}/work-orders`, stageWorkOrder(), { status: 201 });
    await user().click(c.querySelector('[data-action="add-work-order"]'));
    await vi.waitFor(() => expect(requests().filter((r) => r.url === S(detail)).length).toBe(1));
  });

  it("remove-slot: confirm copy; No sends nothing; Yes DELETEs and refreshes", async () => {
    const { c, detail, slot } = await planningCard();
    c.querySelector("details.room-card").open = true;
    const first = user().click(c.querySelector('[data-action="remove-slot"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Remove this unit from the plan? (The work order itself is kept.)"));
    await answerConfirm(false); await first;
    expect(requests()).toHaveLength(0);
    respond("DELETE", `${S(detail)}/work-orders/${slot.id}`, null, { status: 204 });
    const second = user().click(c.querySelector('[data-action="remove-slot"]'));
    await answerConfirm(true); await second;
    await vi.waitFor(() => expect(requestFor(`/work-orders/${slot.id}`, "DELETE")).not.toBeNull());
  });

  it("open-wo hands off to Work Orders with the card focused", async () => {
    const { c, slot } = await planningCard();
    server.use(...pageHandlers());
    c.querySelector("details.room-card").open = true;
    await user().click(c.querySelector('[data-action="open-wo"]'));
    expect(document.getElementById("work-orders-page").classList.contains("active")).toBe(true);
    await vi.waitFor(() => expect(requestFor("/work-orders/", "GET")).not.toBeNull());
    expect(slot.work_order_id).toBeTruthy();
  });

  it("save-stage: confirm copy; Yes PATCHes status loading and reloads the list", async () => {
    const { c, detail } = await planningCard();
    respond("PATCH", S(detail), massStageDetail({ ...detail, status: "loading" }));
    const clicking = user().click(c.querySelector('[data-action="save-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Save this mass stage? It moves to loading and the plan is locked."));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(requestFor(S(detail), "PATCH").body).toEqual({ status: "loading" }));
    await vi.waitFor(() => expect(requestFor("/mass-stages/", "GET")).not.toBeNull());
  });

  it("a failing action surfaces friendlyError in the stage message", async () => {
    const { c, detail } = await planningCard();
    respond("PATCH", S(detail), { detail: "" }, { status: 500 });
    const clicking = user().click(c.querySelector('[data-action="save-stage"]'));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(stageMessage(c).className).toBe("error"));
  });
});
```

Import `state` from `helpers/massStage.js` at the top of the file (the add-item test mutates the seeded detail so the refresh shows the new row).

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/massStage.test.js
git commit -m "test(p5h): planning-body actions"
```

---

### Task 6: Loading/completed-body actions — `load-item`, `return-item`, `complete-stage`, `reuse-stage`, `delete-stage`

**Files:** Modify `tests/frontend/views/massStage.test.js`.

- [ ] **Step 1: Write the tests**

```js
async function loadingCard({ status = "loading", merged = [mergedItem()], slots = [stageWorkOrder()] } = {}) {
  const detail = massStageDetail({ status, merged_items: merged, work_orders: slots });
  const ctx = await openStages({ stages: [massStageSummary({ id: detail.id, status })], details: [detail] });
  const c = await openCard(detail.id);
  clearRequests();
  return { ...ctx, detail, c };
}

describe("loading body", () => {
  it("renders the load list with stats, short/overflow flags, tipHtml on the heading, read-only slots", async () => {
    const { c } = await loadingCard({ merged: [
      mergedItem({ item_name: "Bulb", planned_total: "4", loaded_total: "1", remaining_to_load: "3", on_hand: "2", overflow: "0" }),
      mergedItem({ item_name: "Fuse", overflow: "2", remaining_to_load: "0" }),
    ], slots: [stageWorkOrder({ items: [stageItem()] })] });
    const rows = c.querySelectorAll(".ms-merged-item");
    expect(rows[0].querySelector(".ms-merged-stats").textContent).toBe("Planned 4 · Loaded 1 · Remaining 3 · On hand 2");
    expect(rows[0].querySelector(".ms-short").textContent).toBe("short by 1");
    expect(rows[0].querySelector(".ms-load-qty").value).toBe("3");
    expect(rows[1].querySelector(".ms-overflow").textContent).toBe("+2 over");
    expect(c.querySelector(".ms-subhead .tip-btn")).not.toBeNull();   // tipHtml("stage.load-list")
    expect(c.querySelector('[data-action="complete-stage"]')).not.toBeNull();
    expect(c.querySelector('[data-action="reuse-stage"]')).toBeNull();
    expect(c.querySelector('[data-action="delete-stage"]').dataset.stageLoaded).toBe("1");
    expect(c.querySelector('[data-action="add-item"]')).toBeNull();
    expect(c.querySelector(".ms-item-planned-ro").textContent).toBe("Planned: 2");
    expect(c.querySelector('[data-action="remove-slot"]')).toBeNull();
  });

  it("load-item: rejects 0; confirm names qty × item; Yes posts item_id + quantity and refreshes", async () => {
    const m = mergedItem({ item_name: "Bulb", remaining_to_load: "3" });
    const { c, detail } = await loadingCard({ merged: [m] });
    const qty = c.querySelector(".ms-load-qty");
    await user().clear(qty); await user().type(qty, "0");
    await user().click(c.querySelector('[data-action="load-item"]'));
    expect(stageMessage(c).textContent).toBe("Enter a quantity greater than zero.");
    await user().clear(qty); await user().type(qty, "2");
    respond("POST", `${S(detail)}/load`, {});
    const clicking = user().click(c.querySelector('[data-action="load-item"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Load 2 × Bulb onto the truck?"));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(requestFor("/load", "POST").body).toEqual({ item_id: m.item_id, quantity: 2 }));
    await vi.waitFor(() => expect(requestFor(S(detail), "GET")).not.toBeNull());
  });

  it("load-item: No sends nothing", async () => {
    const { c } = await loadingCard();
    const clicking = user().click(c.querySelector('[data-action="load-item"]'));
    await answerConfirm(false); await clicking;
    expect(requests()).toHaveLength(0);
  });

  it("return-item: no confirm; rejects blank; posts item_id + quantity", async () => {
    const m = mergedItem();
    const { c, detail } = await loadingCard({ merged: [m] });
    await user().click(c.querySelector('[data-action="return-item"]'));
    expect(stageMessage(c).textContent).toBe("Enter a quantity to return.");
    await user().type(c.querySelector(".ms-return-qty"), "1");
    respond("POST", `${S(detail)}/return`, {});
    await user().click(c.querySelector('[data-action="return-item"]'));
    await vi.waitFor(() => expect(requestFor("/return", "POST").body).toEqual({ item_id: m.item_id, quantity: 1 }));
    expect(confirmOverlay().hidden).toBe(true);
  });

  it("complete-stage: confirm; Yes PATCHes completed and reloads; No does nothing", async () => {
    const { c, detail } = await loadingCard();
    const no = user().click(c.querySelector('[data-action="complete-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Mark this building complete? The stage becomes read-only."));
    await answerConfirm(false); await no;
    expect(requests()).toHaveLength(0);
    respond("PATCH", S(detail), massStageDetail({ ...detail, status: "completed" }));
    const yes = user().click(c.querySelector('[data-action="complete-stage"]'));
    await answerConfirm(true); await yes;
    await vi.waitFor(() => expect(requestFor(S(detail), "PATCH").body).toEqual({ status: "completed" }));
    await vi.waitFor(() => expect(requestFor("/mass-stages/", "GET")).not.toBeNull());
  });

  it("delete-stage on a loaded stage uses the dispensed-stock copy; Yes DELETEs and reloads", async () => {
    const { c, detail } = await loadingCard();
    respond("DELETE", S(detail), null, { status: 204 });
    const clicking = user().click(c.querySelector('[data-action="delete-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe(
      "Delete this mass stage? Items already loaded stay dispensed — this does not return them to stock. This cannot be undone."));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(requestFor(S(detail), "DELETE")).not.toBeNull());
    await vi.waitFor(() => expect(requestFor("/mass-stages/", "GET")).not.toBeNull());
  });

  it("delete-stage on a planning stage uses the short copy; No sends nothing", async () => {
    const { c } = await planningCard();
    const clicking = user().click(c.querySelector('[data-action="delete-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Delete this mass stage? This cannot be undone."));
    await answerConfirm(false); await clicking;
    expect(requests()).toHaveLength(0);
  });
});

describe("completed body", () => {
  it("read-only stats, Stage again, no Mark Completed, no load controls", async () => {
    const { c } = await loadingCard({ status: "completed", merged: [mergedItem({ returned_total: "1", net_consumed: "3" })] });
    expect(c.querySelector(".ms-merged-stats-ro").textContent).toBe("Returned 1 · Consumed 3");
    expect(c.querySelector('[data-action="load-item"]')).toBeNull();
    expect(c.querySelector('[data-action="complete-stage"]')).toBeNull();
    expect(c.querySelector('[data-action="reuse-stage"]')).not.toBeNull();
  });

  it("reuse-stage: confirm; Yes POSTs /reuse, reloads, and auto-opens the fresh stage", async () => {
    const { c, detail } = await loadingCard({ status: "completed" });
    const fresh = massStageDetail({ community: detail.community, building_name: detail.building_name });
    respond("POST", `${S(detail)}/reuse`, fresh, { status: 201 });
    state.details.set(fresh.id, fresh);
    server.use(http.get("/mass-stages/", () => HttpResponse.json([
      massStageSummary({ id: detail.id, status: "completed" }), massStageSummary({ id: fresh.id, status: "planning" }),
    ])));
    const clicking = user().click(c.querySelector('[data-action="reuse-stage"]'));
    await vi.waitFor(() => expect(confirmTitle()).toBe("Start a new staging for this community + building? Item lists start empty."));
    await answerConfirm(true); await clicking;
    await vi.waitFor(() => expect(card(fresh.id)).not.toBeNull());
    expect(card(fresh.id).open).toBe(true);
    // The community group is NOT auto-opened on reuse (only autoOpenId is set,
    // not autoOpenCommunity) -- so the open card sits inside a closed group.
    // Characterization; file it.
    expect(card(fresh.id).closest("details.community-group").open).toBe(false);
  });
});
```

- [ ] **Step 2: Run** → PASS.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/massStage.test.js
git commit -m "test(p5h): loading and completed body actions"
```

---

### Task 7: Apply the audit to Mass Stage; the phase-wide success check

**Files:** Create `tests/frontend/views/massStageActionCoverage.test.js`.

- [ ] **Step 1: Write it**

```js
// tests/frontend/views/massStageActionCoverage.test.js
import { join, dirname } from "node:path";
import { fileURLToPath } from "node:url";
import { readdirSync } from "node:fs";
import { auditActions, VIEWS_DIR, PAGES_DIR } from "../helpers/actionAudit.js";

const HERE = dirname(fileURLToPath(import.meta.url));

auditActions({
  name: "Mass Stage actions",
  sources: [join(VIEWS_DIR, "massStage.js")],
  fragments: [join(PAGES_DIR, "mass-stage.html")],
  frozen: [
    "add-item", "add-work-order", "complete-stage", "delete-stage", "edit-item", "load-item",
    "open-wo", "pick-item", "remove-item", "remove-slot", "return-item", "reuse-stage", "save-stage",
  ],
  behaviourDir: HERE,
  behaviourExclude: readdirSync(HERE).filter((f) => f !== "massStage.test.js"),
});
```

- [ ] **Step 2: Run** → PASS with 13. **Success check (parent plan):** comment out the `return-item` test in `massStage.test.js`, run → `no test mentions: return-item`. Restore. Then the same for Work Orders once more (`start-tracking-wo` in `workOrders/actions.test.js`) to prove the re-pointed audit still bites. Restore.
- [ ] **Step 3: Commit**

```bash
git add tests/frontend/views/massStageActionCoverage.test.js
git commit -m "test(p5h): action audit over the thirteen Mass Stage actions"
```

---

### Task 8: Findings, docs, and closing P5

**Files:** Modify `docs/open-work.md`, `docs/current-state.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md`.

- [ ] **Step 1: Findings.** Append to `### N-P5-CHARACTERIZED` only rows the tests confirmed. Candidates:

| Defect | Pinned by |
| --- | --- |
| `reuse-stage` sets `autoOpenId` but not `autoOpenCommunity`, so the fresh stage opens inside a collapsed community group and is not visible until the group is expanded. | `massStage.test.js` → "reuse-stage … auto-opens the fresh stage" |
| The community `<select>` seeds three fixed names (`Scholars`, `Centennial`, `Cimarron`) in source — a deployment-specific list in a view module. | → "community select" |
| `stageMetaText` pluralises units but never items (`1 unit · 1 items`), and the slot's `room-meta` does the same (`· 1 items`). | → "renders slots … room-meta" |
| Typing in the item search after a pick clears `dataset.itemId` silently, so Add with the picked name still visible fails with "Search and pick an item first." | → "pick-item … typing again drops the pick" |

- [ ] **Step 2: `docs/current-state.md`.** Mass Stage task-area row gains `tests/frontend/views/massStage.test.js`; the Vitest bullet is rewritten for the end of P5: final count, wall-clock, and the list of what is covered (nav, main, auth, items, transactions, history, userHub, scan + two units, massStage; the shared fixtures `helpers/{app,auth,items,transactions,history,hub,scanner,massStage,requests,dialogs,actionAudit}.js`). Delete "no Vitest suite for these views yet" wherever P5 covered the view.
- [ ] **Step 3: Parent plan and roadmap — close P5.**
  - P5 plan: tick every P5h bullet and the "Done when" list; fill the suite-budget rows (wall-clock per chunk from the commit bodies); if any chunk pushed the suite past ~6 min locally, record the decision taken (`maxWorkers`, shell memoisation) — not here, in the roadmap status.
  - Roadmap status: `P5 | Landed 2026-MM-DD in eight chunks (P5a–P5h). Suite: N tests / M files, ~S s. Findings under N-P5-CHARACTERIZED.` P6 step text points at `helpers/hub.js` (P5f) and `helpers/actionAudit.js` (this chunk) for its own delegated views (`tools.js`, `users.js`, `userRequests.js`).
  - Roadmap P7: the coverage gate (`thresholds` in `vitest.config.js`) is still advisory — say so, with the number `npm run test:ci` reports at P5 close.
- [ ] **Step 4: Verify and commit** — `npm test` and `npm run test:ci` green; record the coverage summary line in the commit body.

```bash
git add docs/open-work.md docs/current-state.md docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md docs/superpowers/plans/2026-09-10-frontend-test-harness-p5.md
git commit -m "docs: close P5 — mass stage coverage, the generalised action audit, phase status"
```

---

## Done when

- [ ] `npm test` green at every commit; count and wall-clock in the Task 7 and Task 8 commit bodies.
- [ ] `actionCoverage.test.js` produces the same names and count before and after Task 1 (the diff is kept in the scratchpad, not committed).
- [ ] All thirteen Mass Stage actions and all four Items actions are named by the audit, and deleting any one test locally is reported by name.
- [ ] Both exports exercised (`loadStages` with and without `refreshReferenceData`); every `confirmDialog` in the module answered both ways.
- [ ] Five new factories pass the drift guard.
- [ ] P5 status closed in the roadmap; coverage recorded, still advisory.
- [ ] No file under `backend/` touched.

## Deliberately not in P5h

- `focusWorkOrder`'s effect after `open-wo` (P2 `solo.test.js`); `filterRanked` ranking (P1).
- Re-pointing `helpers/workOrders.js` (P2) at `helpers/requests.js` — its own recorder stays; it is imported by five behaviour files and the swap buys nothing P5 needs.
- The `user-names-updated` event's producer (`users.js`, P6); only the consumer here.
- Fixing anything above.
