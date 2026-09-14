# Frontend Test Harness — P7d (The Request card and the catalogue prompt) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-14 ("Begin P7d"). Fourth P7 chunk; two follow.**

**Goal:** Characterization coverage for `views/workOrderRequests.js` (286 lines: the card's Request section, the stocked Materials lines, the in-form item search, the four `data-request-action`s, the realtime refetch) and `views/catalogueRequest.js` (128 lines: the pure prompt builder and the document-level form lifecycle), plus the action audit for the Request card's four actions.

**Architecture:** Tests only, on the P0 harness. The Request card mounts through P2's `helpers/workOrders.js` (`mountWorkOrders` + `openCard`): `workOrderList.js::paintDetail` calls `mountWorkOrderRequests(cardEl, detail, {items: getAllItems()})`, so the fixture's `requests` and `items` arguments are the whole setup (parent deviation 5). A local `openCardWithRequests()` waits for the section to settle past "Loading requests…" and clears the recorder. `catalogueRequest.js` mounts directly (parent deviation 4): `mountView` then the prompt injected into `#app-root`, with P5d's `helpers/requests.js` recorder. No factory: `userRequest()` (P7a) is the request shape, `item()` the catalogue. No timers in either module; fake timers nowhere. Realtime through `helpers/realtime.js` (deviation 9).

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-14-frontend-test-harness-p7.md` (the P7d bullets are the requirement set; deviations 4, 5, 8 and 9 apply)
**Depends on:** P2 (`helpers/workOrders.js`, `editorActions.test.js` owns the `add-item` wire and the `work_orders` prompt), P5c (`items.test.js` owns the `find_item` prompt), P5d (`helpers/requests.js`), P7a (`userRequest()`, `helpers/realtime.js`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P7-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), `WebSocket` (`helpers/realtime.js`), the real confirm overlay.
- `onUnhandledRequest: "error"` stays on.
- One mount per test. `helpers/workOrders.js` registers its own `afterEach`; the realtime handle is disconnected in the file's `afterEach`; `catalogueRequest.test.js` calls `stopRecording()`.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P2 `editorActions.test.js`: the `add-item` POST carries `material_request_id` from `.wo-add-item`'s dataset and clears it after; the `work_orders` prompt's dataset. This chunk asserts `add-requested` at the dataset stamp and no further.
- P5c `items.test.js`: the `find_item` prompt's dataset.
- P2 `realtime.test.js`: the transport, the generation guards, the reconnect ladder.

## Deviations from the parent's P7d text, decided here

| # | Deviation | Why |
| --- | --- | --- |
| D1 | The send form's `qty ≤ 0 / NaN` validation and the catalogue form's are pinned the way P7a and P7c pinned theirs: a `type="number"` input sanitises non-numeric text to `""`, `Number("")` is `0`, and the `<= 0` half answers. The `!Number.isFinite` half is dead. Filed as the same class. | Same shape as the N-P7 rows already on file. |
| D2 | The send form's message is pinned as losing `.wo-request-message` after its first message (`setMessage` writes `className = type`), the way P7c pinned Low Stock's. A second Send after a validation message rejects inside the un-awaited handler on a null `msg`; the suite pins the class loss and never clicks twice. | Same defect class as the N-P7 Low Stock row; the rejection is unhandled and would fail the run for the wrong reason. |
| D3 | The realtime "every open card" case uses P2's `expandCard` twice on a two-card list, not `openCard`. | `openCard` navigates to the card page, which paints one card; only `expandCard` leaves two open in one list. |
| D4 | The audit's behaviour files are the two requests files only (every other file in the directory excluded by name), the way P7c's was. | `"cancel"` and `"send"` are ordinary enough to be quoted in a sibling file's prose or table. |
| D5 | `helpers/shell.js::mountShell` now drops every listener a view registered on `document` while `importView` was evaluating it. A browser-global seam, not an app-module mock; runtime registrations (dom.js's dialog keydown, user-event's value trackers) are untouched. | `document` is one object per test file while each test re-imports the view, so a module that delegates off `document` (this chunk's two, plus `tools.js`, `nav.js`) had every earlier test's handler still attached. For `workOrderRequests.js` that is fatal: the first stacked send handler renames the message element (`setMessage` overwrites className) and the second rejects on null, 288 unhandled rejections in the first run. A first cut dropped every registration and broke two `history.test.js` tests: user-event installs its trackers once per document and never reinstalls, so a cleared filter typed as "70017001". Import-time only is the exact stacking case. |
| D6 | `requests.test.js` is two files: `requests.test.js` (mount, list, stocked lines, search) and `requestsActions.test.js` (the four actions, realtime). The audit reads both. | The one file came to 643 lines against the repo's 500-line cap; P2 split `actions` / `editorActions` the same way. |

---

### Task 1: `views/workOrders/requests.test.js` + `requestsActions.test.js` (D6)

- [x] Mount: `requestFormHtml` + "Loading requests…" then the list and the stocked lines; a failed `GET /work-orders/{id}/requests` → `<p class="error">` "Could not load requests." with `.wo-requested-lines` left empty.
- [x] `requestListHtml`: live vs resolved, the empty copy, the resolved `<details>` summary, a line's type tag / name (both fallbacks) / qty fallback / status label / creator fallback / `formatWhen` (blank, raw, `toLocaleString`), the Cancel four-way matrix.
- [x] `stockedLinesHtml`: material ∧ stocked only; dataset request / item / name / quantity; `on hand item_quantity ?? "?"`.
- [x] Search: other inputs ignored; typing clears `dataset.itemId` and the on-hand line; blank → hidden + emptied; `filterRanked` by name and barcode, ≤ 8 pick buttons with dataset id / name / quantity; no match → "No matching items." + the `request_card` prompt.
- [x] `pick`, `send` (four validations, the POST body, the refetch, the two success copies, the failure copy + re-enable), `cancel` (No, Yes → POST + refetch, failure → re-enable + the card's positional message), `add-requested` (the dataset stamp, the prefill, the Materials section opened, qty focused).
- [x] Realtime `user_request.changed`: two expanded cards both refetch; a card with focus inside an open section is skipped; a closed card is skipped; a foreign `activePage` does not gate.

### Task 2: `views/workOrders/requestsActionCoverage.test.js`

- [x] `auditActions` — sources `[workOrderRequests.js]`, `renderedPattern: /data-request-action="([a-z-]+)"/g`, `handledPattern: /action === "([a-z-]+)"/g`, frozen `["add-requested", "cancel", "pick", "send"]`, behaviour files the two requests files only (D6).

### Task 3: `views/catalogueRequest.test.js`

- [x] `catalogueRequestPromptHtml`: an unknown source throws by name; blank / whitespace text → `""`; the three sources; `data-work-order-id` only when given; escaping.
- [x] Open → the form with the text prefilled, qty 1, text focused; Cancel → the button again; Submit: blank text, qty ≤ 0 / blank, the POST body (`note|null`, `work_order_id|null`, `source`), "Sending…" + disabled, the whole prompt replaced by "Catalogue request sent to staff.", failure → re-enabled + `friendlyError` copy; a click outside any `.catalogue-request` ignored.

### Task 4: the run, the findings, the commit

- [x] Success checks: delete one action's tests and the audit names it; rename `data-request-action="send"` in the source and the audit plus the send tests go red. Restore both.
- [x] Findings → `N-P7-CHARACTERIZED` (two rows: the dead `isFinite` halves in both forms, the send message class loss).
- [x] `npm test` green (1983 / 74, 174 s; a first full run failed two `history.test.js` tests under the D5 first cut, green after the narrowing); wall-clock in the parent's table; committed. No push.
