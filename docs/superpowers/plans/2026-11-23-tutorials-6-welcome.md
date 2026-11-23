# Tutorials 6 — Welcome Implementation Plan

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

**Spec:** `docs/superpowers/specs/2026-11-23-tutorials-6-welcome-design.md` (cited as W§). Builds on 0a and 0b as already built (0a§, 0b§).

**Constraints for every task:** CSP (classes/CSSOM, no `style=`), no nested buttons, no sideways scroll on a phone, files under 500 lines. Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (`npx vitest run <file>`), never Git Bash. pytest from `backend\`. Commit once per task, stage explicit paths (never `git add -A`), no Co-Authored-By, push nothing (pushing main deploys).

## Spec corrections

| # | Welcome assumes (W§) | 0a/0b actually provide | Smallest addition |
| --- | --- | --- | --- |
| C1 | `POST seen` replies `{first}` (W§5.1, §6) | 0b§5.2: `PUT /tutorials/progress/{key}` returns 204, no `first` | T2: the same `PUT` returns 200 `{first: bool}` ("this call set the timestamp"). Any 0b test pinning 204 changes; name it in the commit body |
| C2 | A caller can wait for the seen write (W§5.1 step 3) | 0b§5.3 `mark()` is optimistic and background | T3: `claimSeen(key)` in `tutorialProgress.js`, awaited, returns bool |
| C3 | `onEnd(reason)`, standalone scripts, no `showPage` reload, targetless step (W§5.3, §6) | None of these in 0a | T4 |
| C4 | Step 4 "Review" sub-tab (W§5.5) | 0b§5.6 names it **Done** | User picked **Completed** (2026-11-23); use it in step 4 and everywhere this plan says Done or Review for the sub-tab |
| C5 | Step 5 targets the Hub's "How this page works" button | `user-hub.html` has no `h2`; 0a§5.5 adds the button to the first `h2` of listed pages only, Hub is not listed by 0a | T6 checks at build time; if the Hub has no button the missing-target rule skips step 5 (Q3) |
| C6 | Desktop step 2 lights `#hub-tab-tutorials` | Exists once 0b§5.7 lands; on phone it is inside `#hub-tabs`, hidden until `#hub-picker-toggle` is open | T4/T5 `open` list |

## Task 1: Obtain the greeting from the user

**Goal:** Text of the greeting, up to 480 characters, plain words. Not invented by the builder.
**Files:** none yet (lands in T5).
**Steps:** 1. Ask the user for the text. 2. Do not start T5's constant until supplied; T2–T4 and the T5 wiring proceed with the placeholder `"[GREETING — written by the user]"`, which the guard (T6) rejects.
**Test:** n/a. Done when the user has pasted the text.

## Task 2: Server — `first` on the progress write

**Goal:** `PUT /tutorials/progress/{key}` says whether this call was the first (C1).
**Files:** the 0b progress service (`backend/app/services/tutorial_progress*.py`, find by grep), `backend/app/routers/tutorials.py`, their pytest files, `backend/tests/test_route_role_gates.py` only if the status code is asserted.
**Steps:**
1. Test first: first `seen` → `{first: true}`; second `seen` → `{first: false}`; `completed` after `seen` → `first: true` once, then `false`; two sequential calls race-free by construction (assert the row's `seen_at` unchanged by the second).
2. Make the service return a bool from a single conditional write (`UPDATE … WHERE seen_at IS NULL` / insert-on-conflict-do-nothing, rowcount) so two devices cannot both win (W§5.2). Router returns it as 200 JSON.
3. Fix 0b tests that expected 204.
**Test:** `pytest tests/test_tutorial_progress*.py tests/test_route_role_gates.py tests/test_memprobe.py -q` → pass (no new route, so the memprobe catalogue is untouched).

## Task 3: Client — `claimSeen` and the welcome's own state

**Goal:** An awaited "claim seen" that fails closed (W§5.1 step 3).
**Files:** `backend/static/tutorialProgress.js`, `tests/frontend/tutorialProgress.test.js` (the 0b test file).
**Steps:**
1. Test first: `claimSeen("welcome")` resolves `true` when the PUT answers `{first:true}`; `false` for `{first:false}`, a 500, and a network error; the cache shows seen after a `true` or `false` reply, not after a failure.
2. Implement with `api.js`'s existing request helper; no DOM import.
**Test:** `npx vitest run tests/frontend/tutorialProgress.test.js` → pass.

## Task 4: Player — targetless step, standalone scripts, `onEnd`

**Goal:** What W§5.3 and §6 need from 0a, no more.
**Files:** `backend/static/tutorial.js`, `backend/static/tutorials/index.js` (standalone entry shape), `backend/static/styles.css` (centred box variant, a class), the 0a player test file in `tests/frontend/` (find: `tutorial*.test.js`).
**Steps:**
1. Tests first (W§7 Player): a step with no `target` key shows a centred box, nothing lit, two-tap rule unchanged, counter "1 of N"; a step whose `target` is given but absent still skips; a standalone script runs with no sample responder set (a listed GET still reaches the server) and makes no closing `showPage` call; `onEnd("ended")` fires on End/Esc/leave, `onEnd("done")` on Done; a standalone script restores the hub tab that was active when it began (click it at the end; for an already-active tab the picker still ends collapsed).
2. Implement: `startTutorial(key, { onEnd })`; index entry `{ standalone: true }` skips sample, `showPage` and the page button; before `open`, snapshot `.hub-tab.active`. Visible-target test for "missing" must use layout visibility, not just presence, so a tab hidden inside a collapsed phone picker counts as missing until `open` expands it.
3. Phone overlay tap: `hubPicker.js` closes the picker on any document click outside it. Test that a tap on the overlay (two-tap rule) does not collapse the picker mid-tour; if it does, the player's blocked-input handler must stop propagation at capture.
4. `open` support: an entry that is already satisfied (`#hub-picker-toggle` with `aria-expanded="true"`) is skipped, not clicked.
**Test:** `npx vitest run tests/frontend/tutorial*.test.js tests/frontend/unit/staticImports.test.js` → pass; the 0a Leak and Draft tests stay green.

## Task 5: `welcome.js` script and `views/welcome.js` sequencing

**Goal:** The script (W§5.5) and `runWelcomeThenClockIn` (W§5.1).
**Files:** create `backend/static/tutorials/welcome.js` (data only), `backend/static/views/welcome.js`; modify `backend/static/tutorials/index.js` (list `welcome`, standalone), `tests/frontend/views/welcome.test.js` (create).
**Steps:**
1. Script: key `welcome`, step 1 no `target`, title "Welcome", `text` = the greeting from T1 (placeholder until then, stored in one exported constant `GREETING_PLACEHOLDER` next to it so the guard can compare). Steps 2–5 per W§5.5, wording per C4/Q2. `open` for step 3: `["#hub-picker-toggle", "#hub-tab-tutorials"]`; for step 2 the picker expansion must happen before step 2 shows (so it also sits in the script's top-level `open`). Real selectors for steps 3–5 come from `views/hubTutorials.js`; add an id there if none and update the id census.
2. Tests first, using `mountAuth`/`signedIn` from `tests/frontend/helpers/auth.js`, `userFactory`, `server.use` handlers for `GET /tutorials/progress/me`, `PUT /tutorials/progress/welcome`, `GET /attendance/me`; recorded requests via `requests()`. Cases (W§7): due → tour shown, no clock-in modal until `onEnd`, then modal appears; not due (`seen_at` set) → modal only; `first:false` and PUT 500 → neither tour nor extra PUT, modal still follows; `resumed` and deep-link → no tutorials request at all; sign-out (`setCurrentUser(null)` / `showLoginScreen`) mid-tour → no clock-in prompt; PUT recorded before `.tutorial-box` is in the DOM; End never PUTs `completed`, Done does; a manual run from the Tutorials tab PUTs no `seen`; Owner gets the welcome and no clock-in modal.
3. Implement `runWelcomeThenClockIn(user, { plain })`: if not `plain` → straight to clock-in path? **No**: skipped welcome still needs the clock-in prompt, so call `maybePromptClockIn(user)` directly. Otherwise `loadProgress()` (failure → clock-in only), `hasSeen("welcome")` → clock-in only, `await claimSeen("welcome")` false → clock-in only, else `await new Promise(r => startTutorial("welcome", { onEnd: r }))`, then `maybePromptClockIn(user)` only if `getCurrentUser() === user`. Any thrown error ends in the clock-in prompt, never a dead sign-in.
**Test:** `npx vitest run tests/frontend/views/welcome.test.js` → pass.

## Task 6: Wire `enterApp`; guard; default handler

**Goal:** One line in `auth.js`, plus the guard that keeps the placeholder from shipping.
**Files:** `backend/static/views/auth.js:111-161`, `tests/frontend/helpers/handlers.js` (`pageHandlers()`), `tests/frontend/views/auth.test.js`, `tests/frontend/views/clockInPrompt.test.js`, the 0a guard test file (find: `tutorials*guard*.test.js`), `tests/frontend/unit/staticImports.test.js`.
**Steps:**
1. `enterApp` already knows `resumed` and `deepLinkNumber` (lines 113, 143). Compute `const plain = !resumed && deepLinkNumber === null;` after line 143 and replace line 161 with `void runWelcomeThenClockIn(user, { plain });`. `initPushForUser` and `replayPendingDrafts` stay as they are.
2. Add default MSW handlers to `pageHandlers()` for `GET /tutorials/progress/me` (a seen `welcome` row, so existing auth and clock-in suites see no tour) and `PUT /tutorials/progress/:key` (`{first:false}`). Run the existing auth and clock-in suites unchanged; any failure is a finding, not a test to loosen.
3. Guard test additions (W§7 Guard): welcome targets exist on the mounted Hub for each of the five roles, at desktop width and with the phone picker; ≤ 5 steps; step 1 limit is 480 characters, steps 2–5 keep 240/2 sentences; **the test fails while step 1's text equals `GREETING_PLACEHOLDER`**. Lift the 240/2-sentence limits for `welcome` step 1 only.
4. Check C5: if the Hub shows no "How this page works" button, record it in the commit body and raise Q3 before shipping.
**Test:** `npx vitest run tests/frontend/views/auth.test.js tests/frontend/views/clockInPrompt.test.js tests/frontend/views/welcome.test.js tests/frontend/unit/staticImports.test.js` and the guard file → pass, except the placeholder test, which must fail until T1 text is in; then pass.

## Task 7: Greeting, docs, hand check before pushing

**Goal:** Switch on only after the user has looked.
**Files:** `backend/static/tutorials/welcome.js` (the user's text), `docs/current-state.md` (one entry: welcome flow, trigger point in `enterApp`, once-ever rule, `first` on the PUT; current truth only, delete anything stale it replaces).
**Steps:**
1. Put the user's greeting in step 1; run the guard (now green); full Vitest run for the touched files from T3–T6 and `pytest tests/test_tutorial_progress*.py -q`.
2. Commit. Do **not** push. Pushing main switches the welcome on for every account at once and deploys.
3. Give the user this checklist to run locally before any push:
   - A brand-new account: greeting, then five steps, lands on Home, clock-in prompt after; sign out and in again, nothing shows.
   - An existing account: same, once.
   - End on step 1, mid-way and via Esc: never returns at the next sign-in; Tutorials tab lists "Welcome" as not completed and runs it from there without changing anything.
   - A phone (and 320 px): box fits, picker expands for step 2, tab opens at step 3, no sideways scroll, Home and collapsed picker after.
   - A resumed scanning batch: signs in straight to the batch, no welcome; the next plain sign-in shows it.
   - A shared work-order link: lands on the order, no welcome; same next time.
   - Clock-in order: welcome first, clock-in modal only after it closes; the Owner sees the welcome and no modal; a user already clocked in sees the welcome only.
   - Two devices signing in at once: only one shows it.
**Test:** user sign-off on every line above; `git status` shows only the named paths staged.

## Questions only the user can answer

- Q1: the greeting text (T1).
- Q2: settled, the sub-tab is "Completed".
- Q3: if the Hub has no "How this page works" button when this ships, drop step 5 or add the button?
