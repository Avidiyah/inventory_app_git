# Work Orders Live Rendering (Stage 1) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A live update to the Work Orders list changes only the cards that differ, keeps what the user opened, and briefly highlights what changed.

**Architecture:** The list keeps building its grouped card tree with the existing builders, into a detached container. A new helper, `morphInto`, hands that tree to the vendored idiomorph library, which patches the on-screen list in place. Per-card tap handlers become one delegated handler per list, because patched-in cards are copies without handlers.

**Tech Stack:** Plain ES modules, idiomorph 0.7.4 (vendored, 0BSD), Vitest + jsdom.

**Spec:** `docs/superpowers/specs/2026-11-14-work-order-live-rendering-design.md` (Stage 1 only; Stage 2 is not planned here).

## Global Constraints

- Security policy is `default-src 'self'`: no inline style, no inline script, no `eval`. State changes use classes only.
- No build step, no new npm dependency. The library is a file in `backend/static/vendor`.
- `open` on any `<details>` belongs to the user; an update never changes it.
- `prefers-reduced-motion: reduce` disables the highlight.
- REST stays the source of truth; no change to events or endpoints.
- `workOrderList.js` is 857 lines; it must stay under 1,000. If a task would cross that, move the delegated handler into `backend/static/views/workOrderListTaps.js`.
- Shared checkout: stage explicit paths only, never `git add -A`. No `Co-Authored-By` trailer.
- Run targeted tests only: `npx vitest run <file>`.

## Review Focus

1. **Update lands while the list is filtered to nothing:** the hint shows, and cards return on the next update. Test in Task 3.
2. **Two updates back to back:** the second must not leave a stuck highlight or throw. Test in Task 1.
3. **Same order in the User Hub list and the page list:** distinct ids, and each list's Open button calls its own handler. Test in Task 2.
4. **Focused card is removed by an update:** no throw, and the next Tab press reaches a real element. Test in Task 3.
5. **Card data changes but its id does not:** Open uses the fresh data, not the data from first draw. Test in Task 2.

---

### Task 1: Vendor idiomorph and add the `morphInto` helper

**Files:**
- Create: `backend/static/vendor/idiomorph-0.7.4.esm.js` (from `https://unpkg.com/idiomorph@0.7.4/dist/idiomorph.esm.js`, unmodified)
- Create: `backend/static/vendor/idiomorph-LICENSE.txt` (from `https://unpkg.com/idiomorph@0.7.4/LICENSE`)
- Create: `backend/static/morph.js`
- Modify: `backend/static/styles.css` (append beside the work-order card rules)
- Test: `tests/frontend/unit/morph.test.js`

**Interfaces:**
- Produces: `export function morphInto(container, newNodes, { flashSelector = null, flashKey = (el) => el.textContent } = {})`. Returns nothing. `newNodes` is a `NodeList` or array of nodes. Elements matched by `flashSelector` must carry an `id`.
- Produces: CSS class `just-changed`.

- [ ] **Step 1: Write the failing tests**

Build small `<details id>` fixtures directly in the test; no app modules needed.

```js
test("keeps a details the user opened, and one the user folded")      // el.open unchanged both ways
test("a new details keeps the open state its builder gave it")
test("matched elements keep identity; unmatched are inserted/removed") // same object before/after by id
test("moves an element with an id to a new parent instead of rebuilding")
test("does not overwrite the focused input's value")                   // value stays "half-typed", focus kept
test("flags new elements and elements whose flashKey changed")         // classList.contains("just-changed")
test("does not flag unchanged elements")
test("a second morph clears flags left by the first")                  // Review Focus 2
test("removes the flag on animationend")                               // dispatch new Event("animationend")
test("with no flashSelector, adds no class")
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/frontend/unit/morph.test.js`
Expected: FAIL, cannot resolve `backend/static/morph.js`.

- [ ] **Step 3: Vendor the two files, then implement `morphInto`**

Import: `import { Idiomorph } from "./vendor/idiomorph-0.7.4.esm.js";`

Order inside `morphInto`:
1. Remove `just-changed` from every element in `container` that has it.
2. If `flashSelector`: record `Map<id, flashKey(el)>` for current matches.
3. `Idiomorph.morph(container, newNodes, { morphStyle: "innerHTML", ignoreActiveValue: true, callbacks: { beforeAttributeUpdated } })`, where `beforeAttributeUpdated(name, node)` returns `false` when `name === "open"` and `node.localName === "details"`.
4. If `flashSelector`: for each match now in `container`, add `just-changed` when its id was absent from the map or its key differs. Skip step 4 entirely when the map was empty (first draw must not flash every card).
5. One delegated `animationend` listener on `container`, installed once per container (track with a `WeakSet`), removes `just-changed` from `event.target`.

- [ ] **Step 4: Add the highlight CSS**

```css
.just-changed { animation: just-changed-fade 1s ease-out 1; }
@keyframes just-changed-fade { from { box-shadow: 0 0 0 4px rgba(200, 16, 46, .35); } }
@media (prefers-reduced-motion: reduce) { .just-changed { animation: none; } }
```

- [ ] **Step 5: Run to verify pass**

Run: `npx vitest run tests/frontend/unit/morph.test.js tests/frontend/unit/staticImports.test.js`
Expected: PASS. (If the static-import guard lives elsewhere, find it with `grep -rl staticImports tests/frontend` and run that file.)

- [ ] **Step 6: Commit**

```bash
git add backend/static/vendor/idiomorph-0.7.4.esm.js backend/static/vendor/idiomorph-LICENSE.txt backend/static/morph.js backend/static/styles.css tests/frontend/unit/morph.test.js
git commit -m "feat(ui): morphInto helper patches a container in place (vendored idiomorph 0.7.4)"
```

---

### Task 2: Ids on cards and groups; one tap handler per list

**Files:**
- Modify: `backend/static/views/workOrderList.js` (`buildCard` ~498, `appendGroupedCards` ~332, `renderCards` ~313, `mountWorkOrderList` ~635)
- Test: `tests/frontend/views/workOrders/listTaps.test.js` (use `tests/frontend/helpers/workOrders.js` and `importView`, as `actions.test.js` does)

**Interfaces:**
- Produces: `buildCard(card, { solo = false, idPrefix = "wo" } = {})`. The `onOpen` option is removed. Sets `el.id = \`${idPrefix}-card-${card.id}\``.
- Produces: `appendGroupedCards(container, cards, build, idPrefix = "wo")`. Sets `group.id = \`${idPrefix}-group-${key}\``.
- Produces: `installListTaps(container, { getCard, onOpen = null })`, module-private. Installs one `click` listener, once per container (`WeakSet`). On a click inside `[data-peek-open]` it finds `closest("details.wo-card")`, calls `getCard(cardEl.dataset.id)`, and then `onOpen(card)` or `openWorkOrderPage({ id: card.id, number: card.number })`. Does nothing if `getCard` returns nothing.
- Each list keeps a `Map<string, card>` keyed by `String(card.id)`, replaced on every render; `getCard` reads it. This is what keeps Open on fresh data.
- Prefixes: `wo` for the page list, `hubwo` for `mountWorkOrderList`.

- [ ] **Step 1: Write the failing tests**

```js
test("page list: Open on a card navigates to that work order")
test("page list cards and groups carry wo- ids")                       // #wo-card-<id>, #wo-group-<status>
test("hub mount: Open calls onOpen with the card's id and number")
test("hub mount uses hubwo- ids; no id is duplicated in the document")  // Review Focus 3
test("each list's Open calls its own handler when both hold the same order") // Review Focus 3
test("after a re-render with changed data, Open passes the new data")   // Review Focus 5: change card.number, re-render, click
test("a card appended to the list without its own listener still opens") // cloneNode(true) a card, append, click
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/frontend/views/workOrders/listTaps.test.js`
Expected: FAIL on the id and cloned-card assertions.

- [ ] **Step 3: Implement**

Remove the `body.addEventListener("click", ...)` block from `buildCard`. Leave the `solo` branch's two listeners untouched. Call `installListTaps` from `renderCards` (for `listEl`) and from `mountWorkOrderList` (for `container`, passing its `onOpen`).

- [ ] **Step 4: Run to verify pass, plus neighbours**

Run: `npx vitest run tests/frontend/views/workOrders tests/frontend/views/hubTechnician.test.js`
Expected: PASS. A failure in an existing test that clicked a card built outside a list means that test must mount the list first; fix the test, not the handler.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrderList.js tests/frontend/views/workOrders/listTaps.test.js
git commit -m "refactor(work-orders): cards and groups carry ids; one tap handler per list"
```

---

### Task 3: The page list redraws through `morphInto`

**Files:**
- Modify: `backend/static/views/workOrderList.js` (`renderCards` ~313)
- Test: `tests/frontend/views/workOrders/listLive.test.js`

**Interfaces:**
- Consumes: `morphInto` (Task 1); ids and `installListTaps` (Task 2).
- `renderCards(cards)` keeps its signature.

- [ ] **Step 1: Write the failing tests**

Drive each through `loadWorkOrders({ background: true })` with a changed API response.

```js
test("an opened preview stays open across an update")                  // same element, open === true
test("a folded group stays folded; an opened Completed group stays open")
test("a card whose status changed is the same element under its new group")
test("a new card is inserted in server order and its Open button works")
test("a card missing from the response is removed")
test("group counts update")
test("changed and new cards get just-changed; untouched cards do not")
test("first draw flags no card")
test("update to an empty result shows the hint; the next update restores cards") // Review Focus 1
test("update that removes the focused card does not throw; focus lands in the document") // Review Focus 4: document.activeElement is connected
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/frontend/views/workOrders/listLive.test.js`
Expected: FAIL on element-identity and open-state assertions.

- [ ] **Step 3: Implement**

`renderCards` builds into `const tree = document.createElement("div")`: either the hint paragraph or `appendGroupedCards(tree, cards, (c) => buildCard(c), "wo")`. Then:

```js
morphInto(listEl, tree.childNodes, {
  flashSelector: "details.wo-card",
  flashKey: (el) => el.querySelector("summary.wo-summary")?.textContent ?? "",
});
```

Remove the two `listEl.innerHTML = ...` lines in `renderCards`. Leave every other `listEl.innerHTML` write (error path, skeletons in `workOrderRouting.js`, the card page) as is.

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/frontend/views/workOrders`
Expected: PASS.

- [ ] **Step 5: Browser security gate (stop here if it fails)**

The first point the library runs in the real app. With the app on port 8124, open Work Orders as `owner`, then read the browser console.
Expected: no `Content-Security-Policy` violation, and the list renders. If a violation names the vendored file, stop, revert this task's commit candidate, and report; do not loosen the policy.

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/workOrderList.js tests/frontend/views/workOrders/listLive.test.js
git commit -m "feat(work-orders): live list updates patch in place and highlight what changed"
```

---

### Task 4: Highlight on single-card refresh; docs

**Files:**
- Modify: `backend/static/views/workOrderList.js` (`refreshCardSummary` ~401)
- Modify: `docs/current-state.md` (one row for `morph.js` and the vendored file; delete something stale in the same edit if one exists)
- Test: `tests/frontend/views/workOrders/listLive.test.js` (extend)

**Interfaces:**
- Consumes: class `just-changed` and its `animationend` clean-up. The clean-up listener exists on `listEl` because `renderCards` ran `morphInto` first.

- [ ] **Step 1: Write the failing tests**

```js
test("a status event for an on-screen card flags it when its summary text changed")
test("a status event that changes nothing visible does not flag the card")
```

- [ ] **Step 2: Run to verify failure**

Run: `npx vitest run tests/frontend/views/workOrders/listLive.test.js`
Expected: the two new tests FAIL.

- [ ] **Step 3: Implement**

In `refreshCardSummary`, read the summary's `textContent` before writing `summary.innerHTML`; after, `cardEl.classList.toggle("just-changed", before !== after)`. List cards only (the `!isSoloActive()` branch); the card page is Stage 2.

- [ ] **Step 4: Run to verify pass**

Run: `npx vitest run tests/frontend/views/workOrders tests/frontend/unit/morph.test.js tests/frontend/views/hubTechnician.test.js`
Expected: PASS.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrderList.js tests/frontend/views/workOrders/listLive.test.js docs/current-state.md
git commit -m "feat(work-orders): single-card live refresh highlights the card; document morph helper"
```

---

## After the last task

Not pushed until the owner's in-app check on a phone. Pushing `main` deploys.

| Owner checks | Passes when |
|---|---|
| Open a preview, have a second login change another order | Preview stays open; the changed card glows once |
| Fold a group, trigger an update | Group stays folded |
| Scroll mid-list on iOS Safari, have an order created above | Reading position does not jump |
| Tap Open on a card that arrived live | The work order opens |
| User Hub list | Cards still open from the hub |

If iOS Safari jumps, that is a follow-up task (restore the anchor card's position after the update), not part of this plan.
