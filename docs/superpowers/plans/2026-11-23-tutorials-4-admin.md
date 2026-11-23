# Tutorials 4 (Admin and Owner) Implementation Plan

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

> **For agentic workers:** The orchestrator (Opus 5.5) runs Tasks 1 and 4 inline and dispatches Tasks 2 and 3 in parallel to Sonnet 5.5 agents (medium effort, never forks; the owner authorizes agents for this batch). Steps use checkbox syntax.

**Goal:** Extend the `user-hub` and `saved-users` tutorial script and sample files with the Admin/Owner scripts of the spec.

**Spec:** `docs/superpowers/specs/2026-11-23-tutorials-4-admin-design.md` (**S4**). Foundation: `2026-11-23-tutorials-0a-player-design.md` (**0a**) and `2026-11-23-tutorials-0b-progress-design.md` (**0b**, `minRole`). Section numbers below are theirs. Assumes 0a, 0b and batches 1-3 are built, so `backend/static/tutorials/<page>.js` and `<page>.sample.js` already exist for both pages (the directory does not exist in the checkout yet).

## Spec corrections

| # | S4 says | Code says | Handling |
|---|---|---|---|
| 1 | S4 §7: the guard needs an extra exemption for roles whose tab button is hidden | 0b settled `minRole`; the guard and Next offer check roles from `minRole` up | Drop the S4 §7 guard change. Scripts carry `minRole` instead: `user-hub.leaderboards` and `user-hub.report` `minRole: 'admin'`; `user-hub.graphs` `minRole: 'techfm_oa'`. Saved-users scripts need no `minRole` (page floor is Team Lead, equal to their audience) |
| 2 | S4 §3.2 role wording "strictly below" is right; `tips.js` is wrong | `roles.py` `assignable_roles` and `can_manage` are strictly below (`roles.py:150-160`); `tips.js:227` says "at or below" | Spec holds. Fix `tips.js` in Task 1 |
| 3 | S4 §3.1: `.hub-leaderboard-top` is a step target | It is a row class set only when `rank <= 3` (`hubPerformanceBoard.js:53`), not a component | No change; the sample must supply ranks 1-3 (S4 §4 already says medals) |
| 5 | S4 §4 and 0a 5.3: sample ids are negative | Ids are UUID strings; 0a plan C1 uses the reserved prefix `ffffffff-ffff-4fff-8fff-0000000000NN` | Both briefs use the prefix; the guard asserts it |
| 4 | S4 §5: the `.tip-btn[data-tip="hub.leaderboard"]` selector exists | The button comes from `tipHtml("hub.leaderboard")` (`hubLeaderboardsTab.js:57`); `data-tip` attribute emitted by the helper | Task 1 confirms the helper writes `data-tip`; if not, report |

Selectors verified present in source: every `.hub-*` class and `#hub-tab-*` / `#hub-tabpanel-*` id in S4 §3.1 (`hubLeaderboardsTab.js`, `hubPerformanceBoard.js`, `hubGraphs.js`, `hubGraphTrends.js`, `hubReport.js`, `user-hub.html`); every `#users-*`, `#user-*`, `.menu-trigger`, `.archived-user`, `[data-scope="archived"]` in S4 §3.2 (`saved-users.html`, `users.js`, `menus.js`). `.hub-graphs .hub-graph-seg` is a `div` wrapping buttons; the first match is the front grouping switch. No anchor needs adding.

## Global constraints

- Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git` (`npx vitest run <file>`); Git Bash fails with "failed to find the runner". Targeted runs only.
- Commit with explicit paths staged, never `git add -A`; no Co-Authored-By trailer; push nothing (pushing main deploys).
- Agents write only their own two files, never app code, never `tutorials/index.js`, never a file another agent owns. Agents run no tests, no git, no servers.
- Wording is verbatim from S4's wording tables; an agent never invents or edits wording. Any step over 240 characters or any wording problem is reported, not fixed.

---

### Task 1: Orchestrator prep

**Goal:** Anchors confirmed, `tips.js` role tip corrected.

**Files:** Modify `backend/static/tips.js:227` (key `user.role`). Read-only: `backend/static/tips.js` `tipHtml`, `backend/static/tutorials/index.js`.

- [ ] **Step 1:** In `user.role` replace "You can only create roles at or below your own." with "You can only create roles below your own." (confirmed against `roles.py:150-160`, Correction 2).
- [ ] **Step 2:** Grep `tipHtml` and confirm it emits `data-tip="<key>"` on a `.tip-btn` (Correction 4). If not, stop and report; Task 2's step 5 selector changes.
- [ ] **Step 3:** Confirm both pages are registered in `tutorials/index.js` and that `user-hub.js` / `saved-users.js` exist with the earlier batches' scripts. If either file is missing, batches 1-3 are not built: stop.
- [ ] **Step 4:** Read the first lines of both existing files and note the exact script-object shape, the `minRole` key spelling (0b) and the role id strings; paste these into the Task 2 and 3 briefs where marked `<SHAPE>`.

**Test:** `npx vitest run tests/frontend/unit/tips.test.js` if it exists (tips text may be pinned); otherwise none. Commit `fix(tips): role tip says below your own, as the code does`.

---

### Task 2: Agent brief, page `user-hub`

**Goal:** Append three scripts and their sample keys to the Hub files.

**Files:** Owns `backend/static/tutorials/user-hub.js` and `backend/static/tutorials/user-hub.sample.js`. Extend only; keep every earlier script and every earlier sample key (especially `GET /hub`) untouched.

**Steps:** Dispatch the brief below as is (fill `<SHAPE>` from Task 1).

```
You extend two existing files and touch nothing else. Do not run tests, git or servers. Do not edit app code or tutorials/index.js.

OWN: backend/static/tutorials/user-hub.js and backend/static/tutorials/user-hub.sample.js. Both exist. Extend; never rewrite or reorder what is there.

READ FIRST (all under C:\Users\mcclu\Desktop\inventory_app_git):
- docs/superpowers/specs/2026-11-23-tutorials-4-admin-design.md: sections 3.1 and 4 are your job. Wording in the tables is verbatim; copy it exactly.
- docs/superpowers/specs/2026-11-23-tutorials-0a-player-design.md: 5.2 (script format: an open click is skipped when what it reveals is already visible; a step whose target is missing or not visible is skipped), 5.3 (sample data: a sampled GET matches on path alone), 5.6 (house rules), 6 (guard test).
- docs/superpowers/specs/2026-11-23-tutorials-0b-progress-design.md: the optional minRole key.
- The two files you own, as the worked example. Shape: <SHAPE>
- backend/static/views/hubLeaderboardsTab.js, hubPerformanceBoard.js, hubGraphs.js, hubGraphTrends.js, hubReport.js; backend/static/pages/user-hub.html; backend/app/schemas/hub.py and performance.py; backend/static/tips.js keys starting hub.; backend/static/api.js (getters near lines 609-654 show the exact paths and query strings); tests/frontend/helpers/hub.js and factories.js for response shapes.

SCRIPTS TO ADD, in this order after the existing ones:
1. user-hub.leaderboards: title "Leaderboards"; audience admin, owner; minRole 'admin'; open ['#hub-tab-leaderboards']; here '#hub-tab-leaderboards[aria-selected="true"]'; five steps per S4 3.1.
2. user-hub.graphs: title "Graphs"; audience techfm_oa, admin, owner; minRole 'techfm_oa'; open ['#hub-tab-graphs']; here '#hub-tab-graphs[aria-selected="true"]'; no textFor; six steps per S4 3.1. Steps 4 and 5 both target [data-graph-pie="0"] and are only descriptions; never open the pop-up.
3. user-hub.report: title "Report"; audience admin, owner; minRole 'admin'; open ['#hub-tab-report']; here '#hub-tab-report[aria-selected="true"]'; six steps per S4 3.1.
Use the role id strings the existing files use, not the display names.

SAMPLE RULES (S4 4 and 0a 5.3): add keys, never redefine GET /hub. Answer exactly three GET paths, built inside sample(user) with dates computed from today (never fixed):
- GET /hub/performance?window=week: PerformanceResponse. 6 rows: 4 ranked (rank 1-4, scores falling), 2 below_floor true with rank null; one row with a day_reasons entry and one excluded_orders entry; floor_minutes 960; to_date true. Row fields from app/schemas/performance.py (user is a HubUser from hub.py; scaled, weights, billed_dollars, etc.).
- GET /hub/graphs?weeks=12: 7 statuses created..review, 5 communities (Scholars, Centennial, Commons, Young Hall, Academics), about 25 cells over 3-4 service types and priorities (one null priority; the first community non-zero so data-graph-pie="0" renders enabled); duration.buckets = 12 Mondays, last partial, one week under 5 samples, one null on-time. Field names from hub.py and hubGraphs.js/hubGraphTrends.js.
- GET /hub/report: one completed week (last week; frozen_at set so the week arrows and This week are enabled): 7 closed rows over 3 service types, new_work_order_count 4, numbers like S-101.
Every record id is a UUID string in the reserved namespace ffffffff-ffff-4fff-8fff-0000000000NN (NN unique within the file); never negative numbers. All people made up; never include the viewing user's real profile. Do not sample the Excel export, other weeks or months, or any write. Take every field name from the schemas or the helpers; list any you had to guess.

REPORT BACK (no file contents): the two file paths; any selector from S4 3.1 you could not find in the source; any step over 240 characters; any field name you guessed; any question.
```

**Test:** None by the agent. The orchestrator's Task 4 runs the guard.

---

### Task 3: Agent brief, page `saved-users`

**Goal:** Append three scripts and sample keys to the Users files.

**Files:** Owns `backend/static/tutorials/saved-users.js` and `backend/static/tutorials/saved-users.sample.js`. Extend only.

**Steps:** Dispatch in parallel with Task 2.

```
You extend two existing files and touch nothing else. Do not run tests, git or servers. Do not edit app code or tutorials/index.js.

OWN: backend/static/tutorials/saved-users.js and backend/static/tutorials/saved-users.sample.js. Both exist (batch 2 added scripts and keys). Extend; never rewrite or reorder.

READ FIRST (under C:\Users\mcclu\Desktop\inventory_app_git):
- docs/superpowers/specs/2026-11-23-tutorials-4-admin-design.md: sections 3.2 and 4 are your job. Wording and textFor lines are verbatim.
- docs/superpowers/specs/2026-11-23-tutorials-0a-player-design.md: 5.2, 5.3, 5.6, 6. An open click is skipped when the thing it reveals is already visible; a step with a missing or invisible target is skipped.
- docs/superpowers/specs/2026-11-23-tutorials-0b-progress-design.md: minRole (not needed for these three scripts).
- The two files you own, as the worked example. Shape: <SHAPE>
- backend/static/pages/saved-users.html, views/users.js, menus.js, roles.js; backend/app/schemas/users.py; backend/app/domain/roles.py; tips.js keys user.*; api.js near line 250 (the users getter); tests/frontend/helpers/factories.js for user shapes.

SCRIPTS TO ADD, in this order:
1. saved-users.add: title "Add a user"; audience supervisor, techfm_oa, admin, owner (use the role id strings the existing files use); open ['#users-add > summary']; here '#users-add[open]'; seven steps per S4 3.2, with the textFor on the #user-role step (keys owner, admin, techfm_oa, supervisor).
2. saved-users.actions: title "Reset or archive"; same audience; open []; no here; five steps per S4 3.2 (the textFor on the Edit Role step is keyed supervisor only).
3. saved-users.restore: title "Restore"; same audience; open ['#users-scope [data-scope="archived"]']; here '#users-scope [data-scope="archived"][aria-pressed="true"]'; two steps per S4 3.2.
Menus are never opened; steps only describe the closed Actions button.

SAMPLE RULES (S4 4 and 0a 5.3): add keys, never redefine an earlier key. Answer exactly:
- GET /users/?include_archived=true (the path match ignores the query): 8 made-up people: one Owner, one Admin, one TechFM OA, one Team Lead, three Technicians, plus one archived Technician. Every viewer from Team Lead up must own at least one active row they outrank and one archived row they outrank (ranks in roles.py; strictly outranking is the rule), so the archived Technician satisfies every viewer. Field names from schemas/users.py; archived flag as that schema spells it.
- GET /hub/attendance/week: { rows: [] } (keeps real people out of the Needs-a-fix counts). Skip if batch 2 already answers it with an empty set; do not duplicate.
Every record id is a UUID string in the reserved namespace ffffffff-ffff-4fff-8fff-0000000000NN (NN unique within the file); never negative numbers. Never include the viewing user's real profile. Do not sample any write (add, reset, archive, restore).

REPORT BACK (no file contents): the two file paths; any selector from S4 3.2 you could not find; any step over 240 characters; any field name you guessed; any question.
```

**Test:** None by the agent.

---

### Task 4: Orchestrator finish

**Goal:** Guard and gates green, one wording review table for the owner, committed.

**Files:** Modify `backend/static/tutorials/index.js` only if a new script key needs registering (the page entries already exist). Read: the four agent files. Docs: `docs/current-state.md` only if a fact changed.

- [ ] **Step 1:** Read the agents' reports. Resolve missing selectors by reading the source; an anchor that truly does not exist is a Spec correction for the owner, not an app edit made silently.
- [ ] **Step 2:** From PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git`: `npx vitest run tests/frontend/tutorials` (the 0a guard test file; use its real path from batch 1). It must check targets, step limits, `textFor` keys, reserved-prefix ids, and roles from `minRole` up. Fix data failures in the owning file by hand (agents are done); do not weaken the guard.
- [ ] **Step 3:** Run `npx vitest run tests/frontend/unit/staticImports.test.js` and any CSP/inline-style guard the repo has for static files; these catch a bad import or inline style.
- [ ] **Step 4:** Build one wording review table for the owner: columns script key / step number / wording / `textFor` variants. Wording is S4's verbatim, so the table is for reading rather than approving new copy. Add S4 §8's open calls as the table's footer (three Users scripts, trend-tile wording from the page hint, Report sample is a completed week, Restore leaves the filter on Archived, the player skips `open` when `here` already matches: confirm it against the built 0a player and report the result).
- [ ] **Step 5:** Stage explicit paths: `backend/static/tips.js` (if not committed in Task 1), `backend/static/tutorials/user-hub.js`, `user-hub.sample.js`, `saved-users.js`, `saved-users.sample.js`, `tutorials/index.js` only if changed. Commit `feat(tutorials): admin hub tabs and user management scripts (batch 4)`. No Co-Authored-By trailer; no push.
- [ ] **Step 6:** Update `docs/current-state.md` only if a fact changed (for example the tutorial script count); otherwise leave it.

**Test:** Step 2 and Step 3 runs green; `git status` shows only the paths named in Step 5 staged.
