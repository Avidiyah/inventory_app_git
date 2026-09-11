# Frontend Test Harness — P4 (Split `views/workOrders.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Break the 2,842-line `backend/static/views/workOrders.js` into eight focused modules, none over 900 lines, with the P2 Vitest suite and P3 E2E suite green after every single commit and no behaviour change of any kind.

**Architecture:** `workOrders.js` becomes a ~40-line **barrel** that re-exports the eleven public names and imports the side-effect modules. The implementation moves to `workOrderList.js` plus seven siblings arranged in one acyclic layer stack. The rename happens **first** (Task 2), before any extraction — that is what keeps every later extraction free of import cycles, because a module needing `loadWorkOrders` imports `workOrderList.js` (never the barrel).

**Tech Stack:** ES modules (native, no bundler), Vitest + jsdom + MSW, Playwright (P3).

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md`
**Roadmap:** `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md` (P4)

**Entry gate:** P2 merged (done) **and** P3 merged and green (`docs/superpowers/plans/2026-09-10-frontend-test-harness-p3.md`, not yet implemented as of 2026-09-10). Do not start Task 2 until `pytest -m e2e` passes in CI. The E2E layer is the only thing that proves the new module graph actually loads in a real browser under the app's CSP — jsdom cannot see that.

## Global Constraints

- **Mechanical motion only.** Move code verbatim, including its comment block. Change nothing but `import`/`export` lines and the four state-accessor rewrites named in Task 4/5. No renames, no signature changes, no cleanups, no "while I'm here" fixes. `git diff -M --stat` should read as lines leaving one file and entering another.
- **Every move carries its comments.** This file's comments are load-bearing (they record why `soloActive` is passed to `buildCard`, why `toggle` listens in capture phase, why the combo trigger precedes the native select). A move that drops them is not mechanical.
- **The eleven public exports never change.** `soloNumberFromPath`, `focusWorkOrder`, `focusWorkOrderNumber`, `workOrderCardClass`, `comboHtml`, `loadWorkOrders`, `loadIntegrationsPage`, `mountWorkOrderList`, `openWorkOrdersByNumberSearch`, `openWorkOrdersFilteredByStatus`, `openWorkOrdersFilteredByDistribution`. The nine importing modules (`adminReview`, `auth`, `hubAdmin`, `hubReport`, `hubTechnician`, `massStage`, `nav`, `transactions`, `userHub`) are not touched in this phase.
- **Behaviour tests are frozen.** Not one file under `tests/frontend/views/workOrders/` may be edited except `actionCoverage.test.js`, which is a source-*shape* assertion and is adapted once, in Task 1, before anything moves. If a behaviour test needs an edit to pass, the move was not mechanical — revert and redo it.
- **The five pinned defects stay pinned.** `docs/open-work.md` → `N-WO-CHARACTERIZED` lists five bugs the P2 suite records as green. Do not fix any of them here.
- **Each module declares the DOM refs it uses.** A repeated `const listEl = document.getElementById("work-orders-list")` in two modules is correct and intended — both resolve the same node, and it avoids a coupling module that exists only to pass elements around.
- **No import cycles.** The layer stack below is the whole rule. Verify after each task with the Task 10 check.
- **CSP:** no inline `style=` attributes anywhere (see `docs/open-work.md`; style attributes are silently dropped in this app).
- Run `npm test` after every task. Green before the next.
- Commit messages end with `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`.

## The layer stack

Arrows point from importer to imported. There are no cycles and no injection except the one marked seam.

```
workOrderPresenters.js      (leaf: pure formatting + role predicates)
        ↑
workOrderReferenceData.js   (allItems / allTechs / allSupers + ensureReferenceData)
workOrderFilters.js         (filter controls, sort, showAll, filter options)
        ↑
workOrderCardHtml.js        (every HTML string builder + picker/combo DOM helpers)
        ↑
workOrderRouting.js         (solo mode, URL, scroll — list deps INJECTED, see Task 7)
        ↑
workOrderList.js            (list load, cards, realtime, control wiring)
        ↑                ↑
workOrderActions.js   workOrderIntegrations.js
        ↑                ↑
workOrders.js               (barrel: 11 re-exports + side-effect imports)
```

`workOrderRouting.js` is the one genuine mutual recursion (`loadWorkOrders` → `openWorkOrderPageByNumber` → `showSoloCard`, and Back → `loadWorkOrders`). It imports nothing from the list; `workOrderList.js` calls `installWorkOrderRouting({ buildCard, paintDetail, loadWorkOrders })` at the bottom of its own module body, so routing is always installed whenever the list module loads.

## File Structure

| File | Responsibility | Approx. lines |
| --- | --- | --- |
| `views/workOrders.js` (rewrite) | Barrel. Eleven re-exports plus side-effect imports. Nothing else. | 40 |
| `views/workOrderList.js` (create, via `git mv`) | List load, filters wiring, card build, realtime, held/deferred refresh, the four `openWorkOrders*` entry points, `mountWorkOrderList` | 790 |
| `views/workOrderCardHtml.js` (create) | Every HTML string builder, plus the picker/combo open-close DOM helpers that only they produce markup for | 640 |
| `views/workOrderActions.js` (create) | The six delegated `listEl` listeners: input, click (26 branches), keydown, focusout, charge editor, mode change | 445 |
| `views/workOrderIntegrations.js` (create) | NetFacilities enrichment + cloud auth, CSV import, CSV export, `loadIntegrationsPage` | 440 |
| `views/workOrderRouting.js` (create) | Solo/card-page mode, `/workorder_card/` URL, scroll stamp/restore, popstate | 300 |
| `views/workOrderPresenters.js` (create) | Pure formatting and role predicates: status, priority, place, money, minutes, assignment | 240 |
| `views/workOrderFilters.js` (create) | Filter control reads, filter-option population, sort direction, `showAll`, `RECENT_LIMIT` | 155 |
| `views/workOrderReferenceData.js` (create) | `allItems` / `allTechs` / `allSupers` + `ensureReferenceData` behind getters | 75 |
| `tests/frontend/views/workOrders/actionCoverage.test.js` (modify) | Widen to the module set; accept re-export declarations | — |
| `docs/current-state.md`, `docs/endpoint-map.md`, `docs/open-work.md` (modify) | Record the new file map and consumer columns | — |

**Line ranges below refer to `views/workOrders.js` at commit `2168808`.** After Task 2 the same content is at the same line numbers in `workOrderList.js`; after each later task the numbers shift, so **locate blocks by function name, not by number**. The ranges are given to size the work and to prove nothing was missed.

---

### Task 1: Adapt the coverage meta-test before anything moves

**Files:** Modify `tests/frontend/views/workOrders/actionCoverage.test.js`

**Interfaces:** Produces the guarantee every later task leans on — the 26 actions and the 11 exports stay auditable across a multi-file module.

The test as written reads one `SOURCE` path and asserts each export is declared with a literal `export function`. Both break on a correct split. It is a source-shape assertion, not a behaviour assertion, so adapting it is legitimate; adapting it *now*, while the source is still one file and the test must stay green, is what makes it a safety net rather than a rubber stamp.

- [ ] **Step 1: Replace the single-file source read with the module set**

Replace the `SOURCE`/`source` constants with a directory scan, and derive the export list from the barrel's re-export forms as well as literal declarations:

```js
const VIEWS = join(REPO_ROOT, "backend", "static", "views");
// Every module the Work Orders view is split across. A new sibling is picked
// up automatically; a renamed one shows up as a missing action, loudly.
const SOURCE_FILES = readdirSync(VIEWS)
  .filter((n) => n === "workOrders.js" || /^workOrder[A-Z]/.test(n))
  .map((n) => join(VIEWS, n));
const source = SOURCE_FILES.map((p) => readFileSync(p, "utf8")).join("\n");
```

- [ ] **Step 2: Accept re-export declarations in the export-surface test**

Replace the `declared` matcher so both forms count:

```js
// `export function x` in the module that owns it, or `export { x } from "..."`
// in the barrel. Both are declarations of the public surface.
const declaredNames = (text) => [
  ...matchAll(text, /^export (?:async )?function ([A-Za-z]+)/gm),
  ...[...text.matchAll(/^export \{([^}]+)\} from/gm)]
      .flatMap((m) => m[1].split(",").map((s) => s.trim()).filter(Boolean)),
];
```

Use `declaredNames(source)` in both export tests, deduped and sorted.

- [ ] **Step 3: Add a barrel-completeness assertion**

```js
it("re-exports all eleven from the barrel itself", () => {
  const barrel = readFileSync(join(VIEWS, "workOrders.js"), "utf8");
  expect(declaredNames(barrel).sort()).toEqual(EXPORTS);
});
```

- [ ] **Step 4: Run it — it must be green against the unsplit file**

Run: `npm test -- tests/frontend/views/workOrders/actionCoverage.test.js`
Expected: PASS. `SOURCE_FILES` currently resolves to `workOrders.js` alone; the regex `^workOrder[A-Z]/` matches `workOrderRequests.js` too, which is harmless (it renders no `data-action` in the frozen 26 and declares none of the eleven). If the barrel assertion fails, it is because Task 2 has not run — comment it out with a `TODO(Task 2)` and enable it in Task 2, and note that in the commit body.

- [ ] **Step 5: Run the whole suite, then commit**

```bash
npm test
git add tests/frontend/views/workOrders/actionCoverage.test.js
git commit -m "widen the work-order action audit to the coming module set"
```

**Test.** `npm test` green with the source still monolithic.

---

### Task 2: Rename to `workOrderList.js` and stand up the barrel

**Files:** Rename `backend/static/views/workOrders.js` → `backend/static/views/workOrderList.js`; create `backend/static/views/workOrders.js`

**Interfaces:** Produces `workOrderList.js` exporting all eleven names. Consumes nothing. **Every later task extracts out of `workOrderList.js`, and any sibling needing `loadWorkOrders` imports `workOrderList.js` directly** — never the barrel. That is the whole cycle-avoidance strategy.

- [ ] **Step 1: Rename, preserving history**

```bash
git mv backend/static/views/workOrders.js backend/static/views/workOrderList.js
```

- [ ] **Step 2: Fix the relative import depth**

None needed — the new file is a sibling in the same directory, so every `../api.js`, `./billingEditor.js` etc. still resolves. Confirm with a grep that no import string contains `workOrders.js`.

- [ ] **Step 3: Write the barrel**

Create `backend/static/views/workOrders.js`:

```js
// View: Work Orders page — public surface.
//
// The implementation lives in workOrderList.js and its siblings. This file is
// the name the other nine views import, and it exists so that split can happen
// without touching any of them. Siblings that need the list must import
// workOrderList.js directly: importing this barrel from inside the group would
// create a cycle.
export {
  loadWorkOrders,
  focusWorkOrder,
  focusWorkOrderNumber,
  soloNumberFromPath,
  workOrderCardClass,
  comboHtml,
  loadIntegrationsPage,
  mountWorkOrderList,
  openWorkOrdersByNumberSearch,
  openWorkOrdersFilteredByStatus,
  openWorkOrdersFilteredByDistribution,
} from "./workOrderList.js";
```

- [ ] **Step 4: Enable the Task 1 barrel assertion if it was deferred**

- [ ] **Step 5: Run the suite and commit**

```bash
npm test
git add -A backend/static/views tests/frontend
git commit -m "make views/workOrders.js a barrel over workOrderList.js"
```

**Test.** `npm test` green, all 9 importing views unchanged. `grep -rn "views/workOrders.js" backend/static` returns only the nine importers.

---

### Task 3: Extract `workOrderPresenters.js`

**Files:** Create `backend/static/views/workOrderPresenters.js`; modify `workOrderList.js`

**Interfaces:** Produces, all `export`ed with unchanged signatures: `isSupervisorPlus()`, `isAdminPlus()`, `MARKUP_RATE`, `effectiveBillable(it)`, `lineChargeHtml(it)`, `materialsTotalHtml(detail)`, `notesLogContentsHtml(notes)`, `formatMinutes(minutes)`, `hoursInputValue(minutes)`, `hoursToMinutes(value)`, `laborSummaryHtml(detail)`, `canEditLabor()`, `statusLabel(status)`, `statusBadge(status)`, `priorityBucket(priority)`, `urgentFireActive(card)`, `priorityBadgeClass(card)`, `priorityBadge(card)`, `workOrderCardClass(card)`, `modeLabel(mode)`, `placeMeta(c)`, `assignedIds(detail)`, `assignedNames(detail)`, `isAssignedToCurrentUser(detail)`, `canCurrentUserSendToReview(detail)`.

- [ ] **Step 1: Move three blocks verbatim** — lines 273–286 (`isSupervisorPlus`, `isAdminPlus`), 392–471 (`MARKUP_RATE` through `canEditLabor`), 550–661 (`statusLabel` through `canCurrentUserSendToReview`), each with its full comment block, plus the `SETTLED_STATUSES` const at 587.
- [ ] **Step 2: Add `export` to each and write the module's imports** — `escapeHtml, formatMoney` from `../format.js`; `getCurrentUser, getRole` from `../state.js`; `roleAtLeast` from `../roles.js`. Nothing else.
- [ ] **Step 3: Import them back into `workOrderList.js`** as one named import from `./workOrderPresenters.js`, and change `export function workOrderCardClass` in the barrel to `export { workOrderCardClass } from "./workOrderPresenters.js"` — the barrel now sources it from its owner rather than through the list.
- [ ] **Step 4: Remove any now-unused imports from `workOrderList.js`** (do NOT remove one still used elsewhere in the file — grep before deleting).
- [ ] **Step 5: Run and commit**

```bash
npm test
git add -A backend/static/views
git commit -m "extract the work-order presenters"
```

**Test.** `npm test` green. `render.test.js` and `roles.test.js` untouched and passing — they exercise nearly all of this surface.

---

### Task 4: Extract `workOrderReferenceData.js`

**Files:** Create `backend/static/views/workOrderReferenceData.js`; modify `workOrderList.js`

**Interfaces:** Produces `ensureReferenceData({ refresh = false } = {})`, `getAllItems()`, `getAllTechnicians()`, `getAllSupervisors()`, `invalidateUsers()`.

This is the first task with a non-verbatim delta, and it is the reason `let` state needs an owner: ESM live bindings are read-only across modules, so `allItems` cannot be assigned from a sibling.

- [ ] **Step 1: Move the state and its loader** — lines 107–115 (`allItems`/`itemsLoaded`/`allTechs`/`allSupers`/`usersLoaded` with the comment above them) and 1076–1097 (`ensureReferenceData` with its comment).
- [ ] **Step 2: Move the reference half of the `user-names-updated` listener** (117–122). Keep only the four reference-data resets here; `filterOptionsLoaded = false` moves to `workOrderFilters.js` in Task 5, which registers its own listener on the same event. Two listeners, each owning its own state.
- [ ] **Step 3: Add the accessors**

```js
export function getAllItems() { return allItems; }
export function getAllTechnicians() { return allTechs; }
export function getAllSupervisors() { return allSupers; }
// Import and enrichment both invalidate the user lists so a re-import reflects
// fresh data. The flag, not the arrays: the next ensureReferenceData refetches.
export function invalidateUsers() { usersLoaded = false; }
```

- [ ] **Step 4: Rewrite the three read sites in `workOrderList.js`** — `paintDetail`'s `{ items: allItems }` becomes `{ items: getAllItems() }`. The reads in `technicianPickerHtml`, `renderTechnicianSearch`, `supervisorOptions`, `supervisorChoices` and the add-material input listener stay as bare `allItems`/`allTechs`/`allSupers` for now; they move to their own modules in Tasks 6 and 8 and are converted there.
- [ ] **Step 5: Run and commit** — `npm test`, then `git commit -m "give the work-order reference lists an owner"`.

**Test.** `npm test` green. The technician picker tests in `editorActions.test.js` are the ones that would catch a stale-array mistake.

---

### Task 5: Extract `workOrderFilters.js`

**Files:** Create `backend/static/views/workOrderFilters.js`; modify `workOrderList.js`

**Interfaces:** Produces `PRIORITY_NOT_IMPORTED`, `RECENT_LIMIT`, `loadFilterOptions()`, `invalidateFilterOptions()`, `isFilterOptionsLoaded()`, `renderSortControl()`, `getSortDir()`, `setSortDir(value)`, `SORT_VALUES`, `SORT_STORAGE_KEY`, `currentFilters()`, `hasActiveFilters()`, `listParams()`, `resetFilterControls()`, `getShowAll()`, `setShowAll(value)`, `livePriorityValues()`.

- [ ] **Step 1: Move, with each block's comments** — 287–299 (`PRIORITY_NOT_IMPORTED`, `populateFilterSelect`), 301–336 (`loadFilterOptions`), 338–353 (sort consts, the `localStorage` boot read, `renderSortControl`), 355–390 (`currentFilters`, `hasActiveFilters`, `listParams`, `resetFilterControls`), 126–130 (`RECENT_LIMIT` and `showAll` with their comment).
- [ ] **Step 2: Declare this module's own DOM refs** — `statusFilter`, `serviceTypeFilter`, `priorityFilter`, `supervisorFilter`, `communityFilter`, `scheduledDateFilter`, `searchInput`, `locationSearchInput`, `taskSearchInput`, `sortSeg`. Copy the `getElementById` lines verbatim from 76–87. `workOrderList.js` keeps its own copies for the control wiring it still owns.
- [ ] **Step 3: Add the state accessors and the filter-options invalidation listener**

```js
export function getShowAll() { return showAll; }
export function setShowAll(value) { showAll = value; }
export function getSortDir() { return sortDir; }
export function setSortDir(value) { sortDir = value; }
export function invalidateFilterOptions() { filterOptionsLoaded = false; }
export function isFilterOptionsLoaded() { return filterOptionsLoaded; }
// The filter-options half of the reset workOrderReferenceData.js also listens
// for. Each module resets only the state it owns.
document.addEventListener("user-names-updated", () => { filterOptionsLoaded = false; });
```

- [ ] **Step 4: Add `livePriorityValues()`** — lift the `priorityFilter.options` read out of `priorityEditField` (889–893) so the card-HTML module never touches a filter control:

```js
// The vendor priority levels currently live on the page, for the editor's
// datalist. Excludes the "not imported" sentinel, which is a filter, not a level.
export function livePriorityValues() {
  if (!priorityFilter) return [];
  return Array.from(priorityFilter.options)
    .map((option) => option.value)
    .filter((value) => value && value !== PRIORITY_NOT_IMPORTED);
}
```

Rewrite `priorityEditField` (still in `workOrderList.js` at this point) to call it.

- [ ] **Step 5: Rewrite every `showAll` / `sortDir` / `filterOptionsLoaded` read and write in `workOrderList.js`** to the accessors. There are exactly nine sites: `loadWorkOrders` (three), `renderMoreControl` (one), the `moreEl` listener (two), the filter-change listener (one), the clear-filters listener (one), the sort-segment listener (two `sortDir`), and the three `openWorkOrders*` exports (one each). Grep for each identifier and convert until the grep is empty.
- [ ] **Step 6: Run and commit** — `npm test`, then `git commit -m "give the work-order filter and sort state an owner"`.

**Test.** `npm test` green. `filters.test.js` covers sort persistence through `localStorage`, the `RECENT_LIMIT` cap and `resetFilterControls` — it is the check for this task.

---

### Task 6: Extract `workOrderCardHtml.js`

**Files:** Create `backend/static/views/workOrderCardHtml.js`; modify `workOrderList.js`, `workOrders.js`

**Interfaces:** Produces `renderLaborEntryHtml`, `laborTechnicianControl`, `laborSectionHtml`, `technicianSelectionHtml`, `emptyTechnicianSelectionHtml`, `technicianPickerHtml`, `closeTechnicianResults(picker)`, `renderTechnicianSearch(input)`, `supervisorOptions`, `supervisorChoices`, `comboHtml({...})`, `closeCombo(combo)`, `hasLegacyPlace`, `detailsViewHtml`, `editField`, `priorityEditField`, `editableStatusValues`, `editableStatusOptions`, `statusEditorHtml`, `detailsEditorHtml`, `summaryHtml(card)`, `renderBody(detail, bodyEl)`, `renderLineHtml(it)`.

The picker/combo open-close helpers (`closeTechnicianResults`, `closeCombo`, `renderTechnicianSearch`) travel with the builders that emit the markup they operate on, not with the delegator — they are the other half of one widget.

- [ ] **Step 1: Move six blocks verbatim** — 473–549 (labor entry/technician control/section), 662–815 (technician picker, supervisor options, combo), 816–1021 (`hasLegacyPlace` through `detailsEditorHtml`, including `MANUAL_PRIORITY` and `importedDetailValueHtml`), 1261–1284 (`summaryHtml`), 1679–1817 (`renderBody`), 1819–1838 (`renderLineHtml`).
- [ ] **Step 2: Write the imports** — `escapeHtml, formatMoney, formatUserName, filterRanked, safeHttpUrl` from `../format.js`; `tipHtml` from `../tooltip.js`; `getCurrentUser, getRole` from `../state.js`; `catalogueRequestPromptHtml` from `./catalogueRequest.js` is **not** needed here (it belongs to the input delegator, Task 8); the presenter set from `./workOrderPresenters.js`; `getAllTechnicians, getAllSupervisors` from `./workOrderReferenceData.js`; `livePriorityValues` from `./workOrderFilters.js`.
- [ ] **Step 3: Convert the four reference-data reads** — `allTechs` in `technicianPickerHtml` and `renderTechnicianSearch` becomes `getAllTechnicians()`; `allSupers` in `supervisorOptions` and `supervisorChoices` becomes `getAllSupervisors()`. In `renderTechnicianSearch`, call the getter once into a local `const technicians` and use it for both the `.map` and the `!technicians.length` check — a second call would be a second read of the same array, harmless but noisier.
- [ ] **Step 4: Point the barrel's `comboHtml` at its new owner** — `export { comboHtml } from "./workOrderCardHtml.js"` in `workOrders.js`.
- [ ] **Step 5: Run and commit** — `npm test`, then `git commit -m "extract the work-order card HTML builders"`.

**Test.** `npm test` green. `render.test.js` is the direct check; `roles.test.js` covers the Admin+/Supervisor editor branches.

---

### Task 7: Extract `workOrderRouting.js`

**Files:** Create `backend/static/views/workOrderRouting.js`; modify `workOrderList.js`, `workOrders.js`

**Interfaces:** Produces `soloNumberFromPath(pathname?)`, `focusWorkOrderNumber(number)`, `installWorkOrderRouting({ buildCard, paintDetail, loadWorkOrders })`, `openWorkOrderPage({ id, number })`, `openWorkOrderPageByNumber(number)`, `renderSoloError(message)`, `exitSolo()`, `stampListScrollY()`, `restoreListScrollY()`, `isSoloActive()`, `takePendingSoloNumber()`, `clearPendingListScrollY()`, `armListScrollY(y)`.

This is the one injected seam. Routing imports nothing from the list; the list hands it three functions once, at load.

- [ ] **Step 1: Move, with comments** — 132–157 (solo-mode comment block, `soloActive`, `soloNumber`, `SOLO_PATH_PREFIX`, `pendingSoloNumber`), 159–210 (scroll comment, `scrollRestoration` boot, `pendingListScrollY`, `stampListScrollY`, `restoreListScrollY`), 214–264 (`soloNumberFromPath`, `setSoloChrome`, `exitSolo`, `soloBackControl`), 1433–1495 (`openWorkOrderPage`, `openWorkOrderPageByNumber`), 1496–1499 (`focusWorkOrderNumber`), 1592–1641 (`showSoloCard`, `renderSoloError`), 2822–2842 (the `popstate` listener).
- [ ] **Step 2: Declare this module's DOM refs** — `listEl`, `listMessage`, `controlsSection`, `moreEl`. Copy verbatim from 74–92.
- [ ] **Step 3: Add the installer and the accessors**

```js
// The list half of card-page mode. Injected rather than imported: the two
// call each other (loadWorkOrders opens a pending card page; Back returns to
// the list), and an import both ways would be a cycle. workOrderList.js calls
// this at the bottom of its own module body, so routing is installed for
// anything that can reach it.
let deps = null;
export function installWorkOrderRouting(next) { deps = next; }

export function isSoloActive() { return soloActive; }
// One-shot: the caller consumes the pending number and clears it, so two
// renders cannot both claim it.
export function takePendingSoloNumber() {
  const number = pendingSoloNumber;
  pendingSoloNumber = null;
  return number;
}
export function clearPendingListScrollY() { pendingListScrollY = null; }
export function armListScrollY(y) { pendingListScrollY = y; }
```

Inside the moved bodies, replace `buildCard(` with `deps.buildCard(`, `paintDetail(` with `deps.paintDetail(`, and `loadWorkOrders(` with `deps.loadWorkOrders(`. `apiGetWorkOrder`, `apiListWorkOrders`, `skeletonCard`, `setMessage`, `friendlyError`, `escapeHtml` and `ensureReferenceData` come in as ordinary imports.

- [ ] **Step 4: Rewrite the list's routing reads** — in `workOrderList.js`, `loadWorkOrders`'s `pendingSoloNumber` block becomes `const number = takePendingSoloNumber(); if (number !== null) { clearPendingListScrollY(); ... await openWorkOrderPageByNumber(number); return; }`; `refreshCardSummary` and `runOrDeferListRefresh` read `isSoloActive()`; `exitSolo()`, `stampListScrollY()` and `restoreListScrollY()` are plain imported calls. The `popstate` handler moves with this module and keeps its own `pendingListScrollY` write directly, so `armListScrollY` exists only for a future caller outside routing — if nothing uses it at the end of this task, delete it rather than leave dead surface.
- [ ] **Step 5: Install routing at the bottom of `workOrderList.js`**

```js
// Routing's three list dependencies, handed over once. Placed last so every
// function it names is defined.
installWorkOrderRouting({ buildCard, paintDetail, loadWorkOrders });
```

- [ ] **Step 6: Point the barrel's two routing exports at their owner** — `export { soloNumberFromPath, focusWorkOrderNumber } from "./workOrderRouting.js"`.
- [ ] **Step 7: Run and commit** — `npm test`, then `git commit -m "extract work-order card-page routing"`.

**Test.** `npm test` green. `solo.test.js` covers `soloNumberFromPath`, enter/exit, the `pushState` payload, popstate both directions, the scroll stamp/restore and `renderSoloError` — this is the task most likely to go red, and that suite is the reason it is safe to attempt.

---

### Task 8: Extract `workOrderActions.js`

**Files:** Create `backend/static/views/workOrderActions.js`; modify `workOrderList.js`, `workOrders.js`

**Interfaces:** Consumes `refreshCard(cardEl, reopenSelector)` and `loadWorkOrders(...)` from `./workOrderList.js` (plain imports — no cycle, because the list never imports this module; the barrel does). Produces no exports: the module registers its six listeners as a side effect of being imported, exactly as the code does today.

- [ ] **Step 1: Move five blocks verbatim, comments included** — 1849–1894 (the `input` delegator), 1895–2203 (the 26-branch `click` delegator), 2205–2235 (`keydown` and `focusout`), 2237–2257 (the inline charge editor), 2259–2277 (the mode-select `change` handler).
- [ ] **Step 2: Declare `listEl`** and write the imports — the fourteen `api*` functions these branches actually call (grep the moved text; do not copy the whole import block), `setMessage, confirmDialog, messageDialog` from `../dom.js`, `escapeHtml, friendlyError, filterRanked` from `../format.js`, `openBillingEditor` from `./billingEditor.js`, `catalogueRequestPromptHtml` from `./catalogueRequest.js`, `hoursToMinutes, notesLogContentsHtml, modeLabel` from `./workOrderPresenters.js`, `technicianSelectionHtml, emptyTechnicianSelectionHtml, closeTechnicianResults, closeCombo, renderTechnicianSearch` from `./workOrderCardHtml.js`, `getAllItems` from `./workOrderReferenceData.js`, `refreshCard, loadWorkOrders` from `./workOrderList.js`.
- [ ] **Step 3: Convert the one reference-data read** — `filterRanked(allItems, …)` in the input delegator becomes `filterRanked(getAllItems(), …)`.
- [ ] **Step 4: Export `refreshCard` from `workOrderList.js`** — it is currently module-private at 1840–1847. Adding `export` is the only change to it.
- [ ] **Step 5: Import for side effect from the barrel** — add `import "./workOrderActions.js";` to `workOrders.js`, above the re-exports, with a comment saying it registers the delegated listeners and is not optional.
- [ ] **Step 6: Run and commit** — `npm test`, then `git commit -m "extract the work-order click delegation"`.

**Test.** `npm test` green, and specifically `actionCoverage.test.js`: after this move the rendered actions live in `workOrderCardHtml.js` while the handled ones live here, so the audit is now genuinely cross-module. If it reports orphans, a branch or a button was dropped — find it before continuing.

---

### Task 9: Extract `workOrderIntegrations.js`

**Files:** Create `backend/static/views/workOrderIntegrations.js`; modify `workOrderList.js`, `workOrders.js`

**Interfaces:** Produces `loadIntegrationsPage()`. Consumes `loadWorkOrders` from `./workOrderList.js`, `currentFilters` from `./workOrderFilters.js`, `invalidateFilterOptions` from `./workOrderFilters.js`, `invalidateUsers` from `./workOrderReferenceData.js`, `isAdminPlus` from `./workOrderPresenters.js`.

- [ ] **Step 1: Move, with comments** — 2279–2685 in full (NetFacilities enrichment, cloud auth, `importSummary`, `afterWorkOrderImport`, `handleImport`, the export helpers, and all seven `addEventListener` wirings), plus 1208–1213 (`loadIntegrationsPage`) and the `netFacilitiesPollingJobId` declaration at 116.
- [ ] **Step 2: Declare this module's DOM refs** — copy 94–105 verbatim (`importSection` through `exportClientBtn`), plus `exportMessage` from line 88.
- [ ] **Step 3: Convert the invalidation writes** — the four `usersLoaded = false; filterOptionsLoaded = false;` pairs (in `pollNetFacilitiesJob`, `maybeHandleChainCompletion`, `afterWorkOrderImport`) become `invalidateUsers(); invalidateFilterOptions();`.
- [ ] **Step 4: Handle the one line the list keeps** — `loadWorkOrders` sets `exportBtn.hidden = !isAdminPlus()` at 1148. Leave it in `workOrderList.js` with its own `const exportBtn = document.getElementById("wo-export-btn")`; it is a list-load concern (the button sits on the Work Orders page, not the Integrations page) and moving it would change when it runs.
- [ ] **Step 5: Point the barrel's `loadIntegrationsPage` at its owner** — `export { loadIntegrationsPage } from "./workOrderIntegrations.js"`, and add `import "./workOrderIntegrations.js"` only if the re-export does not already pull it in (it does — the re-export is enough; do not add a redundant import).
- [ ] **Step 6: Run and commit** — `npm test`, then `git commit -m "extract the work-order integrations block"`.

**Test.** `npm test` green. `integrations.test.js` covers the import summary, export scopes, NetFacilities poll states and cloud sign-in control states.

---

### Task 10: Verify the split and record it

**Files:** Modify `docs/current-state.md`, `docs/endpoint-map.md`, `docs/open-work.md`

- [ ] **Step 1: Prove no file is over 900 lines**

```bash
wc -l backend/static/views/workOrder*.js backend/static/views/workOrders.js | sort -n
```

Expected: every entry under 900. If one is over, split it further before proceeding — do not relax the check.

- [ ] **Step 2: Prove there are no import cycles**

```bash
cd backend/static/views && grep -n "^import\|^export {.*} from" workOrder*.js | grep -v "\.\./"
```

Read the result against the layer stack at the top of this plan. `workOrderList.js` must not appear as an import target inside `workOrderRouting.js`; `workOrders.js` (the barrel) must not appear as an import target inside any `workOrder*.js` sibling.

- [ ] **Step 3: Run the full gate**

```bash
npm test
cd backend && python -m pytest -m e2e
```

Both green. Record the E2E runtime; if it now exceeds ~3 minutes, that is a P3 concern, not a P4 regression — note it and move on.

- [ ] **Step 4: Run the roadmap's success check by hand**

State each new module's purpose in one sentence. If a sentence needs an "and", the seam is wrong — say so in the completion report rather than silently accepting it.

- [ ] **Step 5: Update `docs/current-state.md`**

Replace the single `backend/static/views/workOrders.js Work Orders page view` line in the file map (line 182) with the eight-line block, one clause each. Update the two "where to look" rows (lines 110, 112) and the billing row (line 102) to name the specific sibling rather than `workOrders.js`. Delete nothing else — this is an addition and a redirection, not a rewrite.

- [ ] **Step 6: Update the `docs/endpoint-map.md` consumer column**

Roughly 25 rows name `workOrders.js`. Apply this mapping, leaving `workOrders.js` in place only where the barrel really is the consumer:

| Endpoints | New consumer |
| --- | --- |
| `/work-orders/import`, `/work-orders/export`, all `/netfacilities/*` and `/cloud/*` | `workOrderIntegrations.js` |
| `/work-orders/{id}` PATCH, `/items` POST/PATCH/DELETE, `/items/{wid}/billing`, `/labor` *, `/tracking/*`, `/hold`, `/resume`, `/archive` | `workOrderActions.js` |
| `/work-orders/` GET, `/work-orders/filter-options`, `/work-orders/lookup`, `/work-orders/{id}/restore`, `/items/` GET, `/users/` GET | `workOrderList.js` |
| `/work-orders/{id}` GET | `workOrderList.js`, `workOrderRouting.js` |

- [ ] **Step 7: Update `docs/open-work.md`**

In `N-WO-CHARACTERIZED`, retarget the two file references that moved: `workOrders.js:840 detailsViewHtml` → `workOrderCardHtml.js`, and `showSoloCard` → `workOrderRouting.js`. Do not restate the defects or add narrative. Add nothing about "the split" itself — that is history, and `docs/` is current-truth only.

- [ ] **Step 8: Commit**

```bash
git add -A docs
git commit -m "record the work-order module split"
```

**Test.** `npm test` and `pytest -m e2e` green; no file over 900 lines; no cycles; `git log --oneline -9` shows nine commits, each one a green step.

**Success check.** Delete one `data-action` branch from `workOrderActions.js` and confirm `actionCoverage.test.js` names it; revert. Then rename one export in `workOrderPresenters.js` and confirm the barrel assertion fails; revert.

---

## Self-review notes

- **Roadmap deviations, deliberate.** Three: (1) eight modules rather than five, because `let` state cannot be assigned across an ESM boundary and the four-module shape leaves `workOrders.js` at ~940 lines; (2) `actionCoverage.test.js` is edited, in Task 1, because it asserts source shape rather than behaviour — every behaviour test stays frozen; (3) the split is not byte-for-byte verbatim at the ~20 state-access sites named in Tasks 4, 5, 6, 7 and 8, each of which is enumerated rather than left to judgment.
- **Not in scope.** Moving the nine consumers off the barrel; fixing any of the five pinned defects; any P5 coverage of the new modules.
- **Highest risk.** Task 7. Solo mode is the only place where two modules genuinely call each other, and `solo.test.js` is the only thing standing between a correct move and a card page whose buttons are all silently dead.
