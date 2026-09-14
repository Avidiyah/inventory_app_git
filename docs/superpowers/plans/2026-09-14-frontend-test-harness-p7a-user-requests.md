# Frontend Test Harness — P7a (User Requests) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-14 ("Begin inline execution start with P7A"). First P7 chunk; five follow.**

**Goal:** Characterization coverage for `views/userRequests.js` (458 lines) and `views/userRequestCards.js` (420) — the tab / status queue, the four card types across their statuses, and the seven row-level actions — plus the fixture, the shared realtime helper, the `userRequest()` factory, and the audit that names any action no test drives.

**Architecture:** Tests only, on the P0 harness. `userRequests.js` imports nothing from `views/` except its own cards module, so it is the entry point of its own graph: `mountView("views/userRequests.js")` after `setTestUser`. The list handler narrows by the `status` and `type` query params so a tab switch is observable as different cards, not just a different URL. The 250 ms search debounce runs on fake timers; nothing else in the module has a timer.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-14-frontend-test-harness-p7.md` (the P7a bullets are the requirement set; deviations 8 and 9 apply)
**Depends on:** P5d (`helpers/requests.js`, `helpers/dialogs.js::answerConfirm`), P5h (`helpers/actionAudit.js`), P1 (`unit/api.endpoints.test.js` owns the wrappers' bodies; `unit/tooltip.test.js` owns `tipHtml`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P7-CHARACTERIZED` (section created by this chunk).
- No `vi.mock` of any app module. Seams: `fetch` (MSW), `WebSocket` (`helpers/realtime.js`), timers, the real confirm overlay.
- `onUnhandledRequest: "error"` stays on.
- One mount per test. `afterEach`: `restoreUserRequests()`; `vi.getTimerCount()` is 0 where fake timers were used.
- `userRequest()` gets a drift row in `unit/api.endpoints.test.js` in the same commit.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P1: the six `apiUserRequest*` wrappers' method / URL / body shapes; `tipHtml`'s unknown-key warning; `friendlyError`'s copy table.
- P5 (`views/nav.test.js`): `showPage("user-requests")` calls `loadUserRequests`.
- P7d will own the Request card's own filing (`workOrderRequests.js`) and the catalogue prompt.

## Deviations from the parent's P7a text, decided here

| # | Deviation | Why |
| --- | --- | --- |
| D1 | `helpers/realtime.js::connectFakeRealtime` emits the socket's `open` itself, as `helpers/hub.js::connectHub` does. | The transport only routes events once open; every caller would otherwise repeat the line. |
| D2 | The `type` narrowing in the list handler filters on `request_type`; the `status` narrowing on `status`. Both mirror `routers/user_requests.py::list_user_requests`. | So a tab click's reload paints the tab's own requests — the assertion the parent asks for. |
| D3 | **Three view files, not two:** `userRequests.test.js` (page + cards), `userRequestsActions.test.js` (resolve, stocked, edit, count, price), `userRequestsFulfil.test.js` (the fulfilment panel). | Two would have run ~700 lines against the 500-line cap — P6e's D1 again. |
| D4 | Tests name actions by their bare class through a `sel(name)` helper, never as a dotted selector literal. | The audit matches the quoted bare name (P5h's deliberate tightening); the first run named six actions no test "mentioned" because every mention carried the dot. |

---

### Task 1: `userRequest()` + `helpers/realtime.js` + `helpers/userRequests.js`

- [x] `helpers/factories.js`: `userRequest(overrides)` with every `UserRequestResponse` field; drift row.
- [x] `helpers/realtime.js`: `connectFakeRealtime(activePage)` → `{ws, emit, reconnect, setActivePage, disconnect}`.
- [x] `helpers/userRequests.js`: `mountUserRequests`, `openUserRequests`, `el`, `cards`, `cardFor`, `tab`, `panelOf`, `answerConfirm`, `restoreUserRequests`.

### Task 2: `views/userRequests.test.js` — the page and the cards

- [x] Tabs, status, counts, refresh, the message copy, the failed list, realtime (event, other page, reconnect).
- [x] Every card type × status: heading, body lines, actions, resolution block, the missing-price prefill, the three tips.
- [x] `formatDate`, `requestTypeLabel`, `statusLabel` and the five html builders by name.

### Task 3: `views/userRequestsActions.test.js` + `views/userRequestsFulfil.test.js` — the row actions

- [x] Resolve / reopen, mark stocked, edit (per type and its validation), count correction, price + link.
- [x] Fulfil: siblings (none, three shapes, singular, the failed check), the debounced search on fake timers, the pick, both modes' payloads, the confirm clause, `skipped`, No, failure.

### Task 4: the audit, the run, the findings, the commit

- [x] `views/userRequestsActionCoverage.test.js` with the parent's patterns and frozen eleven.
- [x] Success check: with `userRequestsActions.test.js` hidden the audit names the three actions only it drives (`edit-cancel`, `edit-open`, `edit-save`); restored.
- [x] Findings → `N-P7-CHARACTERIZED` (one row: the dead `!Number.isFinite` halves, the P6 class).
- [x] `npm test` green: 1812 tests / 66 files, 198 s (2026-09-14); wall-clock in the parent's table; committed.
