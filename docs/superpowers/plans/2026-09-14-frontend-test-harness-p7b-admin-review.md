# Frontend Test Harness — P7b (Admin Review) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-14 ("Start P7B"). Second P7 chunk; four follow.**

**Goal:** Characterization coverage for `views/adminReview.js` (210 lines) — the Review queue, the receipt build on select, Reopen and Close through the real confirm overlay, the two request-ordering guards, and the realtime background reload.

**Architecture:** Tests only, on the P0 harness. `adminReview.js` imports the `workOrders.js` barrel and nothing imports it back, so it is the entry point of its own graph: `mountView("views/adminReview.js")` after `setTestUser`. One consumer, so no fixture file — a local `mountAdminReview()` in the test file, as P6g's push test did (parent deviation 6). No factory: P2's `workOrderCard()`, `workOrderDetail()`, `workOrderItem()` are the shapes. No timers in the module; fake timers only for the reconnect backoff.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-14-frontend-test-harness-p7.md` (the P7b bullets are the requirement set; deviations 6 and 9 apply)
**Depends on:** P1 (`unit/adminReviewReceipt.test.js` owns the receipt text), P2 (`workOrderCardClass`, the three factories), P5d (`helpers/dialogs.js::answerConfirm`), P7a (`helpers/realtime.js`).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P7-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), `WebSocket` (`helpers/realtime.js`), the real confirm overlay.
- `onUnhandledRequest: "error"` stays on.
- One mount per test. `afterEach`: realtime disconnect, `stopRecording`, real timers.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P1: `buildAdminReviewReceipt` text and `missingPrices`; the test computes the expected textarea value through the real builder and asserts equality only.
- P2: `workOrderCardClass` (status + urgent); this file asserts `admin-review-card` and the urgent outcome only.
- P5 (`views/nav.test.js`): `showPage("admin-review")` calls `loadAdminReview`.

## Deviations from the parent's P7b text, decided here

| # | Deviation | Why |
| --- | --- | --- |
| D1 | The "urgent class" assertion pins its **absence**: `SETTLED_STATUSES` in `workOrderPresenters.js` contains `review`, so `urgentFireActive` is false for every card the queue can hold and `buildCard`'s comment ("an urgent work order pulses here the way it does everywhere else") describes a branch that cannot run. Filed. | Asserting presence would be asserting a falsehood; the parent wrote "the urgent class" before reading the set. |
| D2 | The disabled-Close guard (`closeBtn.disabled` inside the click handler) is driven through `.click()` on the disabled button, which the DOM never delivers — the test pins the observable contract (no confirm, no request), not the guard line. | jsdom and browsers agree a disabled button gets no click; the guard is belt-and-braces. |

---

### Task 1: `views/adminReview.test.js`

- [x] Local `mountAdminReview({role, cards, details, handlers, load})` — handlers first, then `GET /work-orders/:id` off `details`, `GET /work-orders/` → `cards`; `setTestUser`; `startRecording`; `mountView`; `loadAdminReview()` unless `load: false`; `clearRequests()`. `connect(page)` wraps `connectFakeRealtime`.
- [x] Load: the loading copy, the `?status=review` query, the button's class / dataset / `aria-label` / four spans, `locationText` and `assignedNames` tables, the three message forms, foreground vs background failure, `background: true` skipping the loading copy, the request-id race (an older answer and an older failure both discarded).
- [x] Select: "Building receipt…", the receipt equal to the builder's text, the section, `.selected`, the two buttons, the ready vs missing-price copy, focus and scroll origin, the list message cleared, a failed detail, a stale selection discarded.
- [x] Reopen: no selection; No; Yes → disabled → `PATCH` → reload → copy, both buttons still disabled (filed); failure with and without a missing price.
- [x] Close: confirm copy; Yes → `POST …/archive` → reload → copy; failure; a disabled Close does nothing.
- [x] Realtime: the event on the page (receipt and selection kept, `.selected` re-applied), elsewhere, reconnect.

### Task 2: the run, the findings, the commit

- [x] Success check: rename `admin-review-close-btn` in `pages/admin-review.html`; the import throws on the null listener and the file goes red. Revert.
- [x] Findings → `N-P7-CHARACTERIZED` (two rows: the reopen buttons, the unreachable urgent class).
- [x] `npm test` green; wall-clock in the parent's table; committed. No push.
