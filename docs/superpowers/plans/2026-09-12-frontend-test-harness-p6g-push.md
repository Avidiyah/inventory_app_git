# Frontend Test Harness — P6g (`views/push.js`) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task, **inline in the session — no subagents** (`CLAUDE.md` forbids them here). Steps use checkbox (`- [ ]`) syntax for tracking.
>
> **Status: go-ahead given 2026-09-12 ("finish p6"). Seventh and last P6 chunk; the phase close-out follows it.**

**Goal:** Characterization coverage for `views/push.js` (177 lines) — `initPushForUser`'s eligibility gate and the whole subscription ladder, `unsubscribeThisDevice`'s logout path, `resetPushView`, `requestPermissionAtLogin`, and the Owner's test button through the real message overlay. Then the P6 close-out: findings filed, `current-state.md` and the roadmap updated, coverage recorded.

**Architecture:** Tests only, on the P0 harness. `push.js` imports nothing from `views/`, so — like `users.js` — it is the entry point of its own graph: a plain `mountView("views/push.js")` after `setTestUser({role})` and `stubPush({…})`. `stubPush` (P5b, `helpers/media.js`) already supplies the three globals `pushSupported()` checks, a registration whose `register` / `getRegistration` / `getSubscription` / `subscribe` / `unsubscribe` are all `vi.fn()`, and a `Notification` whose `permission` the test chooses. Every branch the parent names is reachable by overriding those spies or the `/push/config` handler, so **no helper change is needed** — the knobs the parent allowed (a rejecting `subscribe`, a non-`QUJD` key) are a `mockRejectedValueOnce` and a `server.use` respectively.

**Tech Stack:** Vitest, jsdom, @testing-library/user-event, msw.

**Spec:** `docs/superpowers/specs/2026-09-10-frontend-test-harness-design.md` §3.2–3.3
**Parent plan:** `docs/superpowers/plans/2026-09-11-frontend-test-harness-p6.md` (the P6g bullets are the requirement set)
**Depends on:** P5b (`helpers/media.js::stubPush` / `restorePush`), P5d (`helpers/requests.js`), P1 (`unit/dom.dialogs.test.js` owns `confirmDialog`; `helpers/dialogs.js::answerConfirm` drives it).

## Global constraints

- Tests only. No edit under `backend/static/` or `backend/app/`.
- Characterization, not correction. Findings → `docs/open-work.md` → `N-P6-CHARACTERIZED`.
- No `vi.mock` of any app module. Seams: `fetch` (MSW), the browser push globals, the real overlay.
- `onUnhandledRequest: "error"` stays on.
- One mount per test (`setup.js` resets modules per test). `afterEach`: `restorePush()` + `stopRecording()`.
- No fake timers: `push.js` has no timer.
- Commit messages end with the attribution lines the session provides.

## Already pinned — do not re-cover

- P5b (`views/auth.test.js`): the login checkbox → `requestPermissionAtLogin` ordering (permission before the login request), the checkbox-off path, and logout calling `unsubscribeThisDevice` before `POST /auth/logout`. This chunk owns the module's own branches, not that wiring.
- P1 (`unit/dom.dialogs.test.js`): `confirmDialog`'s `dismissOnly` button, focus trap and Escape.
- P1 (`unit/api.endpoints.test.js`): the four `apiPush*` wrappers' method/URL/body.

## Two deviations from the parent's P6g text, decided here

| # | Deviation | Why |
| --- | --- | --- |
| D1 | **No `helpers/push.js`.** A 12-line local `mountPush()` lives in the test file. | The parent's own instruction is to mount directly; one caller does not earn a fixture, and `stubPush` already is the fixture. |
| D2 | **`vapidKeyToBytes` is asserted at the `subscribe()` call, not by name.** It is private; the bytes handed to `pushManager.subscribe` are its only observable output. The parent calls this "its only seam", so a `/push/config` answer of `"-_8"` (needs one `=` of padding, carries both URL-safe characters) pinning `Uint8Array [251, 255]` is the whole test. | Matches P6f's D2 — a private function is driven through its caller. |

## Entry gate

- [x] `npm test` green: 1716 tests / 61 files, 167 s (2026-09-12). The 266 s / 312 s pair recorded at P6f's close did not reproduce — it was machine load, as suspected; record that in the phase close.

---

### Task 1: `views/push.test.js` — the module's four exports and its button

**Files:** Create `tests/frontend/views/push.test.js`.

- [x] **`mountPush({role, permission, subscription, handlers})`:** `server.use(...handlers)`; `setTestUser({role})` (omitted → no user at all, for the no-role gate); `stubPush({permission, subscription})` unless `permission === "unsupported"`; `startRecording()`; `mountView("views/push.js")`; `clearRequests()`. Returns `{mod, push}`.
- [x] **The test button across the five roles:** unsupported browser so nothing else runs — `initPushForUser()` leaves `#push-test-btn` hidden for technician, supervisor, techfm_oa and admin, visible for owner. No request on any of them.
- [x] **The eligibility gate:** no user at all → no request and the button stays hidden. `SUBSCRIBE_MIN_ROLE` is `"technician"`, rank 0, so `roleAtLeast` is true for every real role — the only way past that gate is no role. **Finding.**
- [x] **Permission states:** `default` and `denied` → `register` not called, no request. `granted` → `GET /push/config`, `register("/service-worker.js")`, `getSubscription()`.
- [x] **Fresh device:** no existing subscription → `subscribe({userVisibleOnly: true, applicationServerKey})`; with `/push/config` answering `"-_8"` the key bytes are `[251, 255]` (padding restored, `-`→`+`, `_`→`/`); then `POST /push/subscribe` carrying the subscription's `toJSON()` (endpoint + `keys`).
- [x] **Same key:** an existing subscription minted against the config key → no `unsubscribe`, no `subscribe`, **still** `POST /push/subscribe` (the shared-device re-POST).
- [x] **Rotated key:** an existing subscription whose `applicationServerKey` differs → `unsubscribe()` then `subscribe()`, in that order.
- [x] **Swallowed failures:** `/push/config` 500 → no `POST /push/subscribe`, no throw. `subscribe` rejecting → same. Both leave the button state untouched.
- [x] **`unsubscribeThisDevice`:** unsupported → nothing; `getRegistration` → null → nothing; no subscription → nothing; otherwise `POST /push/unsubscribe {endpoint}` **then** the browser `unsubscribe()`, in that order; a 500 on that POST is swallowed **and the browser subscription is kept** — server-side-first leaves a dead endpoint on the device. **Finding.**
- [x] **`resetPushView`** hides the button after `initPushForUser` showed it to an owner.
- [x] **`requestPermissionAtLogin`:** `default` → `requestPermission` once; `granted` / `denied` → never; unsupported → never; a rejecting prompt is swallowed.
- [x] **The test button:** click → `disabled` while in flight → `POST /push/test` → the real `#scan-confirm-overlay` carries "Sent to 3 device(s). 1 stale subscription(s) removed, 2 failed."; answered, the button is re-enabled. A 500 → `friendlyError`'s copy in the same overlay, button re-enabled.
- [x] Every export called by name: `initPushForUser`, `unsubscribeThisDevice`, `resetPushView`, `requestPermissionAtLogin`.

**Test.** `npm test` green; `vi.getTimerCount()` is 0 without fake timers, so no timer assertion is needed.

**Success check.** Change `"/service-worker.js"` in `push.js` to `"/sw.js"`; the registration test names it. Revert.

---

### Task 2: P6 close-out

**Files:** Modify `docs/open-work.md`, `docs/current-state.md`, `docs/superpowers/plans/2026-09-11-frontend-test-harness-p6.md`, `docs/superpowers/plans/2026-09-10-frontend-test-harness-roadmap.md`.

- [x] **Findings** → `N-P6-CHARACTERIZED`, in the existing table form: the unreachable `SUBSCRIBE_MIN_ROLE` gate, and the kept-subscription-on-a-failed-unsubscribe dead endpoint. Extend the section's trigger line with the push module.
- [x] **`current-state.md`:** the Web Push row names `tests/frontend/views/push.test.js`; the Vitest bullet's count / time updated and its "roadmap P6-P7" tail reads P7 only.
- [x] **Parent plan:** tick P6g's boxes, the wall-clock table row, the "Done when" list, and record the wall-clock re-measurement that closes the raised budget concern.
- [x] **Roadmap:** P6 status row in the P5 form (date, chunk count, suite size, wall-clock, `npm run test:ci` statements / lines); P7 becomes the only uncovered phase. Update the commits-ahead number.
- [x] `npm run test:ci` once for the coverage figure. Still advisory — P7 gates.

**Test.** `npm test` green; the doc budgets in `CLAUDE.md` respected.

**Closed 2026-09-14.** `npm run test:ci`: 1738 tests / 62 files, 217 s, green; 82.56% statements / 84.16% lines (6324/7659, 5721/6797). `open-work.md` and `current-state.md` were already over their soft budgets before this chunk; this close-out is net negative on `open-work.md`.
