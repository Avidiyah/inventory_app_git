# Tutorials 0b — Progress Record Implementation Plan

> **Added 2026-11-23 for the Starter batch (overrides anything below):** For the Starter batch (starter spec section 10 item 3): `relevant()` and `catalogue()` must accept a page absent from `PAGE_ACCESS` when the script sets `minRole`, and `startTutorial(page, key)` must work for the page name "starter" without calling `showPage`. The Hub tab is built so a third sub-tab can be added.

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

**Goal:** A per-person tutorial progress record, a red dot on page buttons, a Hub Tutorials tab, and a completed-count on the Users page.

**Spec:** `docs/superpowers/specs/2026-11-23-tutorials-0b-progress-design.md` ("spec"; section numbers below are its). Foundation: `...-0a-player-design.md` ("0a"). 0a plan: `2026-11-23-tutorials-0a-player.md`; 0a names below are from it (`tutorial.js`, `tutorials/index.js` `TUTORIALS = {page: {scripts, sample}}`, `installTutorials`, `startTutorial(page)`, `runSteps`, `visibleSteps`, `.tut-btn`, `tutorialGuard.test.js`).

## Spec corrections

- The e2e overflow, gate and memprobe tests live under `backend/tests/` (spec 5.7, 6), e.g. `backend/tests/e2e/test_mobile_overflow.py`.
- `GET /tutorials/progress/users` returns one entry per active user, so it is a list endpoint: it must use `capped(...)` and get a row in `test_list_caps_applied.py` (current-state Test Map). Spec 5.2 does not say so.
- `PAGE_ACCESS` (`views/nav.js`) lists roles explicitly rather than "role and above". Every current entry happens to be a contiguous top slice, and the guard test (T6) pins that, so spec 5.4 holds.
- Sample records use the reserved UUID prefix `ffffffff-ffff-4fff-8fff-`, never negative ids (0a plan C1); nothing in 0b depends on sample ids.
- Spec 5.6 says `startTutorial(key)`; 0a builds `startTutorial(page)`, which picks the script by `here`. T7 widens it to `startTutorial(page, key = null)` (a key overrides `here`).
- A `PUT` route has no delete partner, so its memprobe entry (T3) writes one dev-DB row (`memprobe.sample`) for the probe's owner user. Accepted: one row, owner-only, harmless orphan (spec 5.1).

## Global constraints

- Layering `routers -> schemas/services -> domain/models` (current-state "Architecture Rules"); services own commits.
- Routes tested through the real `TestClient` (pattern: `_client`/`_as` in `backend/tests/test_attendance_router.py`), never by calling handlers. No query parameters on these routes; if one is added, `int` plus manual validation (int-Literal Query 422s on every real request).
- Local DB is Postgres on 8801; never touch `backend/.env`.
- Three cascade tests fail on the dev DB for environmental reasons: targeted backend runs only.
- CSP drops `style=`: classes only (CSSOM in modules that own a node). No nested buttons. No sideways scroll on a phone. UI text reads without a legend.
- Files under 500 lines; `userHub.js` is at 499, so add at most one line there.
- Vitest runs from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (`npx vitest run <file>`); Git Bash fails with "failed to find the runner". pytest from `backend\` with `backend\venv\Scripts\python.exe -m pytest`.
- Commits: one per task, `git add` explicit paths only (peer sessions share this checkout), no `Co-Authored-By` trailer. **Nothing is pushed**: pushing main deploys, and this batch carries a migration.

## Plan's calls

| Call | Choice |
| --- | --- |
| Domain errors | `InvalidTutorialKeyError`, `TutorialProgressLimitError`, both 400 in `routers/_errors.py::_STATUS_MAP` |
| Client `catalogue()` | sync; flattens `TUTORIALS[page].scripts` (0a loads every file statically with the app) into `{page, ...script}` |
| `relevant` home | `backend/static/tutorials/relevance.js` (`relevant`, `audienceLabel`), imports `PAGE_ACCESS` and `roles.js` only |
| `loadProgress()` timing | called in `enterApp` without awaiting; dots appear a moment late (spec 8) |
| Failed PUT | logged, not retried (spec 8); the cache keeps the optimistic value for the session |
| Dot repaint | `tutorialProgress.js` exposes `onChange(fn)`; `tutorialDots.js` subscribes and repaints |
| Users-row wording | `9 of 14 tutorials` as a `users-tut-count` span after the to-fix tag, wraps under the name by the existing row flex rules |

---

### Task 1: Migration and model

**Goal:** `tutorial_progress` table exists in model and schema (spec 5.1).

**Files:**
- Create `backend/alembic/versions/c4e6a8b0d2f3_add_tutorial_progress.py`
- Modify `backend/app/models.py` (add `TutorialProgress` after `PushSubscription`, ~line 1195; add `Index`/`PrimaryKeyConstraint` imports only if missing)
- Create `backend/tests/test_tutorial_progress_model.py`

**Steps:**
1. Find the real head: `backend\venv\Scripts\python.exe -m alembic heads` from `backend\`. Expected `b7d9f1a3c5e7` (newest file); use whatever it prints as `down_revision`.
2. Write the cascade tests first: insert a `TutorialProgress` for a seeded user (seed helper as in `test_push_subscriptions.py::_seed_user`), `db.delete(user)`, flush, assert no row remains; second test: setting `user.archived_at` leaves the row (spec 6 "Cascade"). Run: both FAIL (no model).
3. Model: `user_id` UUID FK `users.id` ON DELETE CASCADE, `script_key` Text, `seen_at` timestamptz not null (default now UTC), `completed_at` timestamptz null; composite primary key `(user_id, script_key)`. Docstring: first-write-wins, keys only, orphans harmless.
4. Migration mirroring `b7d9f1a3c5e7_work_order_field_stamps.py` (`op.create_table`, `postgresql.UUID(as_uuid=True)`, `ForeignKeyConstraint(..., ondelete="CASCADE")`, `PrimaryKeyConstraint`); `downgrade` drops the table. Additive, no backfill.
5. Apply to the dev DB: `python -m alembic upgrade head` from `backend\` .
6. Commit `feat(tutorials): tutorial_progress table and model (0b T1)`.

**Test:** `backend\venv\Scripts\python.exe -m pytest backend\tests\test_tutorial_progress_model.py -q` → 2 passed. Also `python -m alembic upgrade head` then `downgrade -1` then `upgrade head` all exit 0.

---

### Task 2: Domain rules, schema, service

**Goal:** The write and read rules of spec 5.1/5.2 as tested service functions.

**Files:**
- Create `backend/app/domain/tutorials.py` (`KEY_RE = ^[a-z0-9][a-z0-9.-]{0,79}$`, `MAX_ROWS_PER_USER = 500`, `validate_key`)
- Modify `backend/app/domain/errors.py` (two errors), `backend/app/routers/_errors.py` (`_STATUS_MAP` +2, 400)
- Create `backend/app/schemas/tutorials.py` (`ProgressEvent` str-Enum `seen|completed`, `ProgressEventRequest{event}`, `ProgressEntry{key, seen_at, completed_at}`)
- Create `backend/app/services/tutorials.py` (`list_mine`, `record`, `completed_by_user`)
- Create `backend/tests/test_tutorials_service.py`; modify `backend/tests/test_list_caps_applied.py`

**Steps:**
1. Write service tests (db fixture): first `seen` sets `seen_at`; second `seen` later does not move it; `completed` on a new key fills both timestamps equal; `completed` then `seen` or a second `completed` changes nothing; `seen` then `completed` keeps the original `seen_at`; bad keys (`""`, `Upper`, `a b`, 81 chars, leading dot) raise `InvalidTutorialKeyError`; the 501st distinct key raises `TutorialProgressLimitError` while rewriting an existing key at the cap still succeeds; `completed_by_user` returns only active users' completed keys, omits archived users, and omits users with none. Run: FAIL.
2. Add a `test_list_caps_applied.py` case in that file's style (lower `MAX_LIST_ROWS` to 1, two users, one survives, `list.truncated` logged).
3. Implement. `record`: `INSERT ... ON CONFLICT DO NOTHING` (concurrent devices cannot clobber, spec 4), then a guarded `UPDATE ... SET completed_at = now WHERE completed_at IS NULL` for `completed`; the cap counts the caller's rows before a new key. `completed_by_user`: `User.archived_at.is_(None)`, `.limit(fetch_limit())`, `capped(rows, what="tutorial progress")`.
4. Run the service tests: PASS. Commit `feat(tutorials): progress service with first-write-wins and row cap (0b T2)`.

**Test:** `backend\venv\Scripts\python.exe -m pytest backend\tests\test_tutorials_service.py backend\tests\test_list_caps_applied.py -q` → all passed (the list-caps file also has the original cases).

---

### Task 3: Router and the two route guards

**Goal:** The three routes of spec 5.2, mounted, gated and catalogued.

**Files:**
- Create `backend/app/routers/tutorials.py`
- Modify `backend/app/main.py` (import `tutorials` in the `from app.routers import (...)` block at ~line 50 and `app.include_router(tutorials.router)` after `tools`, ~line 344)
- Modify `backend/tests/test_route_role_gates.py`, `backend/scripts/memprobe_routes.py`
- Create `backend/tests/test_tutorials_router.py`

**Steps:**
1. Router tests first, real `TestClient` with the `_as(db, user)` helper from `test_attendance_router.py`:
   - `me` returns only the caller's rows, `[]` for a new user; `PUT .../work-orders.card.notes` `seen` → 204 with `completed_at` null, then `completed` → 204 with both set; user B's `me` is unchanged after A writes.
   - Bad key `Bad_Key` → 400; bad event `"done"` → 422 (Pydantic enum); 501st key → 400.
   - `GET /tutorials/progress/users` as technician → 403, as supervisor → 200 with `{ "<id>": [keys] }` listing an active user's completed keys only, no archived user.
   - Unauthenticated `me` → 401.
2. Route gate tests in `test_route_role_gates.py`, following the `is None` pattern (line ~92) and the supervisor pattern: `_min_role_for(tutorials_router, "my_tutorial_progress") is None`, `"record_tutorial_progress"` `is None`, `"tutorial_progress_users"` `== roles.ROLE_SUPERVISOR`; add `403 in _route(...).responses` for the last. Add the `from app.routers import tutorials as tutorials_router` import beside the others (~line 36).
3. Implement the router (`APIRouter(prefix="/tutorials", tags=["tutorials"])`; module docstring in the `push.py` style stating who may call what). Handlers: `my_tutorial_progress` (`get_current_user`), `record_tutorial_progress` (`get_current_user`, `Response(status_code=204)`, `DomainError` → `to_http`), `tutorial_progress_users` (`dependencies=[Depends(require_min_role(roles.ROLE_SUPERVISOR))]`, `responses={403: ...}`). The key never maps to a user id; the caller's id is `user.id`.
4. Memprobe: in `CATALOGUE` add `"GET /tutorials/progress/me": Entry()`, `"GET /tutorials/progress/users": Entry()`, `"PUT /tutorials/progress/{key}": Entry(path="/tutorials/progress/memprobe.sample", body=J({"event": "seen"}))` beside `# --- push ---` (~line 311). No `EXCLUDED` change.
5. Run router, gates, memprobe tests: PASS. Commit `feat(tutorials): progress routes, gates and probe catalogue (0b T3)`.

**Test:** `backend\venv\Scripts\python.exe -m pytest backend\tests\test_tutorials_router.py backend\tests\test_route_role_gates.py backend\tests\test_memprobe.py -q` → all passed. `test_every_route_is_catalogued_or_excluded` and `test_catalogue_keys_are_real_routes` are the two that fail if a route is uncatalogued or a key is mistyped. The three environmental cascade failures are not in these files.

---

### Task 4: API wrappers

**Goal:** `api.js` can call the three routes, registered in the endpoint tables.

**Files:**
- Modify `backend/static/api.js` (three wrappers beside `apiPushSubscribe`, ~line 995, using `jsonRequest` and the existing GET helper)
- Modify `tests/frontend/helpers/endpointTable.js`; `tests/frontend/unit/api.contract.test.js` only if its meta-test demands a response row

**Steps:**
1. Add rows to `ENDPOINTS` first: `apiGetTutorialProgress` (GET `/tutorials/progress/me`), `apiSetTutorialProgress("k.a", "completed")` (PUT `/tutorials/progress/k.a`, body `{event:"completed"}`), `apiGetTutorialProgressUsers` (GET `/tutorials/progress/users`). Run `api.endpoints.test.js`: FAIL (no such export; the meta-test also fails).
2. Implement the wrappers. `apiSetTutorialProgress` resolves to nothing on 204 (check how `parseResponse` treats an empty body, as the other 204 wrappers do) and URL-encodes the key.
3. Add `api.contract.test.js` rows if its meta-test demands them.
4. Commit `feat(tutorials): api wrappers for progress (0b T4)`.

**Test:** From PowerShell, `npx vitest run tests/frontend/unit/api.endpoints.test.js tests/frontend/unit/api.contract.test.js tests/frontend/unit/api.shapes.test.js` → all passed.

---

### Task 5: Client record module and sign-in wiring

**Goal:** `tutorialProgress.js` per spec 5.3, loaded on sign-in and cleared on sign-out and 401.

**Files:**
- Create `backend/static/tutorialProgress.js`
- Modify `backend/static/views/auth.js` (`enterApp` ~line 111 calls `void loadProgress()`; `showLoginScreen` ~line 63 calls `clearProgress()`, so both sign-out and the 401 handler at line 180 are covered)
- Create `tests/frontend/unit/tutorialProgress.test.js`
- Modify `tests/frontend/unit/staticImports.test.js` if it lists modules

**Steps:**
1. Tests first (MSW; fresh module import per test, it holds state): `loadProgress` fetches `me` once; `mark` flips the cache before the PUT resolves; `completed` implies seen; repeating a true state sends nothing; a 500 PUT is logged and the cache stays; `clearProgress()` empties it and allows a refetch; a load resolving after a clear does not repopulate (generation counter); `onChange` fires on load, mark and clear and unsubscribes. Run: FAIL.
2. Implement: module-level `Map`, `loaded` promise, generation counter, `listeners` Set. Imports only `api.js` (no view imports, spec 5.3). `loadProgress` swallows a failed GET (logs, leaves the cache empty, so no dot is shown, matching "no new request ... nothing to track").
3. Wire `auth.js`; run `auth` view tests to confirm they stay green with an extra MSW-unhandled request (add a default `/tutorials/progress/me` returning `[]` to `tests/frontend/helpers/handlers.js` if needed).
4. Commit `feat(tutorials): client progress cache wired to sign-in and sign-out (0b T5)`.

**Test:** `npx vitest run tests/frontend/unit/tutorialProgress.test.js tests/frontend/unit/staticImports.test.js` plus the auth view test file (find with Glob `tests/frontend/views/auth*.test.js`) → all passed.

---

### Task 6: Relevance, catalogue and guard-test additions

**Goal:** `relevant`, `audienceLabel` and `catalogue()` (spec 5.4, 5.8) with the two new guard checks (spec 6).

**Files:**
- Create `backend/static/tutorials/relevance.js`, `backend/static/tutorials/catalogue.js`
- Create `tests/frontend/unit/tutorialRelevance.test.js`, `tests/frontend/unit/tutorialCatalogue.test.js`
- Modify `tests/frontend/views/tutorialGuard.test.js` (0a T5): add `minRole` valid, keys unique across pages, and the `minRole`-aware visible-step rule
- Modify `backend/static/tutorial.js` (the Next-offer check, 0a T3: later scripts' last-`open` scan) and `tests/frontend/unit/tutorial.test.js`
- Modify `tests/frontend/unit/staticImports.test.js` if needed

**Steps:**
1. `catalogue()` reads `TUTORIALS` from `tutorials/index.js`; no sample module is touched by it.
2. Relevance tests first: `relevant({page:"work-orders"}, "technician")` true; `{page:"saved-users"}` false for technician, true for supervisor; `minRole:"supervisor"` on a `user-hub` script hides it from technician, shows to supervisor and above; unknown role false; `audienceLabel` returns "Everyone" when the page minimum is technician and no `minRole`, else `"Team Lead and above"` built from `roleLabel(minRole)` (never a hard-coded label). Run: FAIL.
3. Implement `relevance.js`: `pageMinRole(page)` = lowest-ranked role in `PAGE_ACCESS[page]` by `ROLE_RANK`; `relevant(entry, role)` = `canAccessPage` rule plus `roleAtLeast(role, entry.minRole)`; `audienceLabel(entry)` from the higher of page minimum and `minRole`. `entry` is the catalogue shape `{page, key, title, minRole?}`.
4. Catalogue tests: with the real scripts files, `catalogue()` returns one flat list, each entry carrying its `page`; a test passes its own `tutorials` object to `catalogue(tutorials = TUTORIALS)`. Implement.
5. Guard additions: for every entry, `minRole` (if present) is in `ALL_ROLES` and `ROLE_RANK[minRole] >= ROLE_RANK[pageMinRole(page)]`; for every page, `PAGE_ACCESS[page]` is a contiguous top slice of `ALL_ROLES` (the correction above); all keys across pages unique, each matching the server key regex and at most 80 characters (extend the 0a per-script data rules in `tutorialGuard.test.js`).
6. `minRole` in the guard (spec 5.4): the rule "every script has a visible step for each role that can open the page" iterates only roles from `minRole` up (`roleAtLeast(role, script.minRole)`) in the guard's per-role loop over `PAGE_ACCESS[page]` (skip that script for lower roles, record its targets only from eligible roles) for a script that carries one; a script with no `minRole` is unchanged. Test first with a fixture script whose `minRole:"supervisor"` has steps only a supervisor sees: the guard passes, and a variant with no visible step for an admin (above `minRole`) still fails it.
7. Player Next offer (0a T3, `tutorial.js`; role from `getCurrentUser()`): the "Next: <title>" candidate scan skips any later script whose `minRole` is above the person's role (`!roleAtLeast(role, minRole)`), in addition to 0a's last-`open`-selector-exists rule; if none remain, only Done shows. Tests first in `tutorial.test.js`: a technician finishing script A with a later `minRole:"supervisor"` script B and no other gets Done only; with a later non-restricted script C after B, Next is "Next: C"; a supervisor gets "Next: B".
8. Commit `feat(tutorials): relevance and catalogue helpers, minRole guard and Next skip (0b T6)`.

**Test:** `npx vitest run tests/frontend/unit/tutorialRelevance.test.js tests/frontend/unit/tutorialCatalogue.test.js tests/frontend/unit/tutorial.test.js tests/frontend/views/tutorialGuard.test.js` → all passed.

---

### Task 7: Player hook, `startTutorial`, red dot

**Goal:** The player records progress and the page button shows the dot (spec 5.3, 5.5, 5.9 contract).

**Files:**
- Modify `backend/static/tutorial.js` (0a asks for it under 450 lines; dots go in the new `backend/static/tutorialDots.js`), `backend/static/main.js` (call `installDots()` right after `installTutorials(...)`)
- Create `backend/static/tutorialDots.js`
- Modify `backend/static/styles.css` (one `.tut-btn-dot` rule beside the 0a `.tut-btn` rules: brand red via the existing badge token, `::after` dot, class-only)
- Create `tests/frontend/views/tutorialDots.test.js` (`bootApp`, as `tutorialWiring.test.js`); extend `tests/frontend/unit/tutorial.test.js`

**Steps:**
1. Tests first.
   - Player (`runSteps`, so a Next jump marks too): entering marks `seen` once; reaching the last **visible** step marks `completed` (a skipped final step completes on the previous one); End early never completes; a sample-data run still PUTs (0a 5.3).
   - `startTutorial("demo", "demo.b")` plays that script regardless of `here`; `startTutorial("demo")` is unchanged; an unknown key falls back to the `here` rule.
   - Dots: with progress cache `{}` and role technician, the work-orders button has `.tut-btn-dot`, `aria-label` and `title` both "How this page works, you have not finished it yet"; after marking every relevant script on that page completed the class and both attributes are removed (original label restored); a `minRole`-hidden script does not hold the dot; a role change plus repaint recomputes; a cleared cache shows no dot; seen-not-completed keeps it. Run: FAIL.
2. Implement: `repaintDots()` iterates the `.tut-btn[data-tut-page]` buttons 0a T4 added, computes `catalogue()` entries for that page filtered by `relevant(entry, getRole())` and `!isDone(key)`; subscribes via `onChange`; `installDots()` repaints once, and `enterApp` (T5) repaints after `loadProgress` resolves. Dot is not colour alone because of the label change (spec 5.5).
3. Hook `mark` into `runSteps` (seen on entry, completed when the last of `visibleSteps` is shown); widen `startTutorial(page, key = null)`.
4. Commit `feat(tutorials): player records progress; red dot on page buttons (0b T7)`.

**Test:** `npx vitest run tests/frontend/views/tutorialDots.test.js tests/frontend/unit/tutorial.test.js tests/frontend/views/tutorialWiring.test.js tests/frontend/views/tutorialGuard.test.js tests/frontend/views/tutorialLeak.test.js` → all passed.

---

### Task 8: Hub Tutorials tab

**Goal:** The eighth Hub tab with To do and Completed sub-tabs (spec 5.6, 5.7). The second sub-tab is labelled **Completed** wherever this plan or the spec says Done or Review, and the Tutorials tab button carries a red dot while any relevant script is unfinished (user's picks, 2026-11-23; add a test for each).

**Files:**
- Create `backend/static/views/hubTutorials.js`
- Modify `backend/static/pages/user-hub.html` (eighth button and panel), `backend/static/styles.css` (`--hub-ico-tutorials`, picker-current rule, tab icon rule, sub-tab and entry classes), `backend/static/views/userHub.js` (`tabPanels` gains `tutorials`; one line in `renderActiveTab` is the only other edit, so the file stays under 500: if it does not, delete a comment line in the same edit)
- Create `tests/frontend/views/hubTutorials.test.js`
- Modify `tests/frontend/views/hubIdsCensus.test.js`, `tests/frontend/views/userHub.test.js` only where they count tabs or ids
- Modify `backend/tests/e2e/test_mobile_overflow.py`

**Steps:**
1. Tests first, with `openHub({tab:"tutorials"})` from `tests/frontend/helpers/hub.js` and progress seeded through `tutorialProgress` (MSW `me` handler): To do groups relevant unfinished scripts by page with the `audienceLabel` text; a seen-not-finished one says "Started"; Done lists finished ones with "Replay"; counts equal list lengths; empty strings exactly as spec 5.6; pages the role cannot open never appear; a tap calls `showPage(page)` then `startTutorial(page, key)`; replay sends no PUT; each entry is one `button`, none nested; the panel repaints on `onChange`; the tab shows for all five roles; the picker label reads "Tutorials". Run: FAIL.
2. HTML: add after Report: `<button ... id="hub-tab-tutorials" data-hub-tab="tutorials" aria-controls="hub-tabpanel-tutorials" aria-selected="false" role="tab">Tutorials</button>` (no `hidden`: every role) and the matching `hub-tabpanel-tutorials` div, copying the attribute set of the neighbouring Report entries.
3. CSS beside the other seven icons (`styles.css` ~6353-6429): `--hub-ico-tutorials` (same data-URI stroke style) plus the `.hub-picker[data-current="tutorials"]` and `#hub-tabs #hub-tab-tutorials` rules. Entries are a flex row that wraps the label under the title below 600 px. No inline styles.
4. `hubTutorials.js`: `mountHubTutorials(panel)` renders through `innerHTML` with `escapeHtml` (static content, no feed) and a delegated click listener bound once (`data-wired`); catalogue read synchronously; subscribes to `onChange` while mounted and unsubscribes when the panel is hidden or on `resetHubTutorials()`. `userHub.js` registers the panel and calls `mountHubTutorials(tabPanels.tutorials)` in `renderActiveTab`'s final branch chain (read the current code first; the `else` currently means work-orders).
5. Update the id census and any tab-count assertion in `userHub.test.js`.
6. E2E: add `"tutorials"` to `HUB_TABS`. Spec 5.7 last row: apply `flex-wrap: wrap` on `.hub-tabs` and add widths 640 and 768 to the e2e parametrisation if eight labels overflow 601-900 px; without Chromium here, apply the wrap rule anyway (harmless when it fits) and leave the check to the user.
7. Commit `feat(tutorials): Hub Tutorials tab (0b T8)`.

**Test:** `npx vitest run tests/frontend/views/hubTutorials.test.js tests/frontend/views/hubIdsCensus.test.js tests/frontend/views/userHub.test.js tests/frontend/unit/staticImports.test.js` → all passed. Optional where Chromium is installed: `backend\venv\Scripts\python.exe -m pytest backend\tests\e2e\test_mobile_overflow.py -m e2e` from `backend\` (it commits `E2E-` rows to the dev DB and sweeps them; skip locally if unsure) → the Tutorials tab at 375 and 320 shows no horizontal overflow.

---

### Task 9: Users page count and profile block

**Goal:** "N of M tutorials" per row and a not-finished list on the profile (spec 5.8).

**Files:**
- Modify `backend/static/views/users.js` (474 lines: extract new code into a new module to stay under the cap)
- Create `backend/static/views/usersTutorials.js` (`fetchTutorialCounts()`, `countFor(user)`, `tutorialTagHtml(user)`; owns the `GET .../users` map and the catalogue)
- Modify `backend/static/views/userProfile.js` (a "Tutorials" block; mount function receives or fetches the map through `usersTutorials.js`)
- Modify `backend/static/styles.css` (`.users-tut-count`, a `.users-profile-tut` list; wrap-friendly)
- Create `tests/frontend/views/usersTutorials.test.js`
- Modify `tests/frontend/helpers/users.js` (default MSW handler for `GET /tutorials/progress/users` returning `{}` in `mountUsers`) and `tests/frontend/views/users*.test.js` / `usersActionCoverage.test.js` if row text or request counts are asserted

**Steps:**
1. Tests first: a row for a technician with 2 of 3 relevant completed shows "2 of 3 tutorials", with `relevant` judged on that person's role (a supervisor's total includes `minRole:"supervisor"` scripts and a technician's does not); no map entry shows "0 of N"; orphan keys are ignored; the map is fetched with the list and on the 60 s tick (fake timers, same gate as `refreshFixCounts`); a 500 hides the line and leaves other cells and the to-fix tag intact; the profile lists only unfinished relevant scripts by page as plain text (no buttons) and "Everything finished." when none. Run: FAIL.
2. Implement `usersTutorials.js`. In `users.js`, `loadUsersNow` also calls `fetchTutorialCounts()` (parallel with the existing fetches, failure caught inside the module), `startFixPolling`'s tick also refreshes it, `renderUsersTable` appends `tutorialTagHtml(user)` after `fixTag` (line ~211). Net added lines in `users.js` stay under 10; if it would pass 500, move `fixTag` construction into `usersTutorials.js` too.
3. Profile: in `mountUserProfile`, after the week block, append the Tutorials block from the same module; it uses the cached map and `user.role`.
4. Commit `feat(tutorials): Users-page tutorial counts and profile block (0b T9)`.

**Test:** `npx vitest run tests/frontend/views/usersTutorials.test.js tests/frontend/views/users.test.js tests/frontend/views/usersActions.test.js tests/frontend/views/usersActionCoverage.test.js tests/frontend/unit/staticImports.test.js` → all passed.

---

### Task 10: Docs, full frontend run, hand-check list

**Goal:** `docs/current-state.md` is current truth for 0b; one full frontend run is green.

**Files:**
- Modify `docs/current-state.md` (data model after `push_subscriptions`, ~line 637; API Surface bullets ~line 872; Frontend Feature Context ~line 914; Roles And Access ~line 539; Test Map table ~line 1010). Update `docs/open-work.md` only if it lists tutorials 0b.

**Steps:**
1. Data model: `### tutorial_progress` (composite key, timestamps first-write-wins and never cleared, keys only, 500-row cap, cascades on delete, archive keeps rows). API Surface: one bullet for the three routes, gates and key regex. Frontend context: `tutorialProgress.js`, `tutorials/relevance.js` (live role, `minRole`), `hubTutorials.js`, `usersTutorials.js`, the dot rule, browser-side totals. Roles section: the all-users gate. Test Map: the new files. Current truth only; mind the header word budget.
2. From PowerShell run `npx vitest run` once. Expected all passed, coverage gate (94/84/96/96) green; name any pre-existing hub timer-leak failure, do not fix it.
3. Re-run the targeted backend set below. No full backend run.
4. Commit `docs: tutorials 0b progress, routes and tabs (0b T10)`. Do not push.

**Test:** `npx vitest run` → all files passed with the coverage gate green; `backend\venv\Scripts\python.exe -m pytest backend\tests\test_tutorial_progress_model.py backend\tests\test_tutorials_service.py backend\tests\test_tutorials_router.py backend\tests\test_route_role_gates.py backend\tests\test_memprobe.py backend\tests\test_list_caps_applied.py -q` → all passed.

---

## What the user checks by hand (running app, after the owner's go-ahead on a local migration; deploy only on their say)

1. Technician on a phone: the work-orders button is dotted; finish all four pilot tutorials, the dot goes and stays after reload. End another tutorial midway: dot stays, Hub To do shows it as "Started".
2. Second device, same person: progress follows. Sign out and in as someone else: no leftover dots.
3. Hub, every role: Tutorials tab present, counts match lists, tapping plays the script, Replay changes nothing. Phone picker lists Tutorials; no sideways scroll at 320 and 375 px; 601-900 px labels fit or wrap.
4. Team Lead, Users page: "N of M tutorials" per row (wraps on a phone), profile lists unfinished ones. A Technician's direct call to the all-users route is refused.
5. Change a role: the dot and totals follow it.
6. Confirm the local migration applied cleanly before any push (pushing main deploys it).
