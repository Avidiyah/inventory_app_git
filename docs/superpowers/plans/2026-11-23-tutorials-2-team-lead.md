# Tutorials 2 — Team Lead Batch Implementation Plan

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

> **For the orchestrator (Opus 5.5):** run Tasks 1 and 7 yourself; spawn Tasks 2–6 as five parallel Sonnet 5.5 agents (medium effort, never forks) once the owner authorizes agents for this batch. This repo bars subagents unless authorized.

**Goal:** Team Lead tutorial scripts and sample data for five pages (user-hub, work-orders, mass-stage, history, saved-users), written as data.

**Spec:** `docs/superpowers/specs/2026-11-23-tutorials-2-team-lead-design.md` (T2; `§` = its sections). Foundations: `...-0a-player-design.md` (0a) and its plan, `...-0b-progress-design.md` (0b, `minRole`), `plans/2026-11-23-tutorials-1-technician.md` (T1: `[data-tutorial-slot]`, `?` optional `open`, `tutorial:end`). Assumes 0a, 0b and batch 1 are built. Every file, function and test name below comes from the 0a plan, not the 0a spec.

## Spec corrections (verified in code 2026-11-23)

| # | Spec says | Code / settled rule says | Handled by |
|---|---|---|---|
| S1 | §4 "negative id"; paths with queries (`/transactions/?page=1&page_size=10`, `/users/?include_archived=true`); spec ids `-1`..`-5` in selectors | Ids are UUIDs; a sampled GET matches on path alone; list GETs carry one body per path | Every id is `ffffffff-ffff-4fff-8fff-` + 12 hex (blocks in the Common block). Selectors `[data-stage-id="-1"]`, `[data-slot-id="-1"]`, `[data-id="-1"]` take the sample UUID. Keys carry no query |
| S2 | §3.3 New step 5 `.stage-summary` | `.stage-card` sits inside a closed `details.community-group` (`massStage.js:158`); on New there is no `open`, and an `open` click would be skipped because step 1 is already visible. The step is never visible, so the guard fails | Move that step, wording verbatim, to be Planning's first step with target `.stage-card[open] > .stage-summary`. New has 4 steps, Planning 5 |
| S3 | §3.2 file order routing, approve, keying | The card page replaces the list (`openWorkOrderPage` empties `listEl`). 0a offers Next only when a later script's last `open` selector exists now, and Approve's last `open` is a list-card button. After Routing the chain would stop | File order: routing, keying-hours, approve (after the pilot's four). Approve is not offered by Next from a card page; it starts from the list chain, the Hub Tutorials tab (0b) or `startTutorial(key)`. **Question 1** |
| S4 | §3.2 Approve `open` "list head of card -3" | A list card is `details.wo-card`; its peek button is only visible once the details is open; when run after another script the page is a card page | `open`: `?[data-action="back-to-work-orders"]`, then `details.wo-card[data-number="SAMPLE-3"] > summary`, then `details.wo-card[data-number="SAMPLE-3"] [data-peek-open]` (the `?` step makes it work from a list or a card page) |
| S5 | §3.1 selectors unscoped | `.hub-hours-week-nav` and `.hub-hours-toolbar` also render in the Leaderboards panel; `.hub-hours-edit/-add/-lunch-line/-clear-review` also render in the week drill-down | Timesheets week: `#hub-tabpanel-timesheets .hub-hours-week-nav`. Day script: prefix every `.hub-hours-*` target with `.hub-day-page` |
| S6 | §3.1 Timesheets step 3 reads as available to Admin and above only | `.hub-timesheets-export` and Mark all reviewed render only for Admin+ (`hubTimesheetsTab.js:160-170`) | Step kept; Team Lead and TechFM OA skip it by the missing-target rule |
| S7 | §3.1 day step 6 and 7 | `.hub-hours-lunch-line` renders for everyone only on a person-day with a lunch deduction or waiver; its button is Admin only. `.hub-hours-clear-review` renders only for Admin and only on a needs-review punch | Sample must hold a lunch day and a needs-review punch (brief) |
| S8 | §4 History | `th.admin-col` and `#history-pricing-btn` carry `hidden` for a Team Lead (`history.js:276,316`) | Settled hidden-target rule skips them; no `textFor` |

Not a correction, a risk handled in Task 7: pages whose targets arrive after a fetch (History rows, Hub crew and roster panels) may be absent when the player resolves its steps.

## Global constraints

- CSP: classes only. No nested buttons. No sideways scroll.
- Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git`: `Set-Location C:\Users\mcclu\Desktop\inventory_app_git; npx vitest run <file>`. Never from Git Bash. Targeted files only.
- Commits: stage explicit paths (other sessions share this checkout), never `git add -A`, no `Co-Authored-By` trailer, nothing pushed (pushing main deploys).
- No agent edits a file another agent owns. Agents never touch app code, `tutorials/index.js`, tests or docs.
- Script keys, `open`, `here` and `minRole` come from the spec; wording comes verbatim from the spec tables.

---

### Task 1: Orchestrator prep, two history anchors

**Goal:** The two filter rows on History get ids (T2 §5), the only anchors the spec lists. Every other selector in §3 was checked against the markup (`hubAttendance*.js`, `hubTimesheetsTab.js`, `hubTechnician.js`, `hubSupervisor.js`, `hubAdmin.js`, `workOrderCardHtml.js`, `workOrderStatusActions.js`, `massStage.js`, `history.js`/`history.html`, `users.js`, `userProfile.js`, `menus.js` for `.action-menu`) and exists.

**Files:** Modify `backend/static/pages/history.html`; test `tests/frontend/views/history.test.js`.

**Steps:**
1. `history.html` line 13: `<div class="filter-row">` becomes `<div class="filter-row" id="history-wo-row">`. Line 23: same, `id="history-date-row"`. The By Item and By User rows stay unlabelled (`#history-item-search` and `#history-user-select` are unique already).
2. In `history.test.js` add one `it`: `#history-wo-row` contains `#history-wo-filter`; `#history-date-row` contains `#history-date-from`.
3. No id census covers History, so no census change.

**Test:** `npx vitest run tests/frontend/views/history.test.js tests/frontend/unit/staticImports.test.js` passes.
**Commit:** `feat(tutorials): history filter-row anchors (T2 prep)`.

---

## Agent briefs (Tasks 2–6)

Paste the **Common block** first, then the page's block. Do not summarize either. Authorize the five agents together before spawning.

### Common block

> You are writing tutorial data for one page of an existing app (FastAPI backend, no-build vanilla-JS frontend). Write ONLY the two files named in your page block. Never edit any other file, never run git, tests or a server, never spawn agents. Return paths, missing anchors and questions only, never file contents.
>
> **Read first, in full:** `docs/superpowers/specs/2026-11-23-tutorials-0a-player-design.md` sections 5.2, 5.3, 5.6; `docs/superpowers/plans/2026-11-23-tutorials-0a-player.md` (its Spec corrections table and "Plan's calls"; take every 0a name from the plan); `...-0b-progress-design.md` section 5.4; `docs/superpowers/plans/2026-11-23-tutorials-1-technician.md` (Spec corrections and Task 3: a leading `?` on an `open` selector makes it optional); `docs/superpowers/specs/2026-11-23-tutorials-2-team-lead-design.md` (your page's rows in sections 3 and 4); the "Spec corrections" table in `docs/superpowers/plans/2026-11-23-tutorials-2-team-lead.md` (it overrides the spec where they differ); the worked example `backend/static/tutorials/work-orders.js` and `work-orders.sample.js`; `tests/frontend/helpers/factories.js`; then your page's html and view modules.
>
> **Script file:** `export const SCRIPTS = [...]`, data only, no imports, no functions. Copy the field names and step shape from the worked example. Use the exact `key`, `title`, `open`, `here` from the spec (ids replaced by the sample UUIDs, per the plan's corrections). Wording is copied VERBATIM from the spec wording tables, never reworded. A leading audience tag in a wording cell ("OA+:", "TL+:", "Admin+:") is not text: the step simply has no target for other roles, so rely on the missing-or-hidden-target skip and add no `textFor`. Where a cell gives two role variants ("A · B"), `text` is the first variant and `textFor` carries the other, keyed by stored role (`technician`, `supervisor`, `techfm_oa`, `admin`, `owner`), one entry per role named. Add `minRole: "supervisor"` only where your block says so. If a spec selector is not in the real markup, keep the step, do NOT invent a selector, and report it. If wording breaks a house rule (8 steps, 2 sentences, 240 characters), keep it and report it.
>
> **Sample file:** `export function sample(user)` returns `{ "GET /path": body }`. Keys are the path alone, no query string. If the file already exists, ADD keys and records and never replace or reorder what is there. No imports. Every `id`, `*_id` and `*_ids` value is `ffffffff-ffff-4fff-8fff-` plus 12 hex digits, taken from your page's block (the viewer's own `user.id` is exempt; never hard-code a role, read `user`). Names are made up (Wren Alder, Tobin Marsh, Ila Brandt, Odell Rusk; Maple Court, Cedar Row). Response shapes come from the real API: the page's `api*` function in `backend/static/api.js`, the router and schema under `backend/app/routers` and `backend/app/schemas`, and the factories (copy their shapes, do not import them). List every GET the page's loader issues for each role; answer each one you can, answer nothing else.
>
> **Report back (under 200 words):** the two file paths; every selector not found (and what the markup gives instead); the GET paths you answered; every GET you saw but did not answer; any text over 240 characters or more than 2 sentences; any question only the owner can settle. No file contents.

Id blocks (12 hex digits after the prefix): user-hub `0000002100NN`, work-orders `0000002200NN`, mass-stage `0000002300NN`, history `0000002400NN`, saved-users `0000002500NN`, with `NN` counting up from `01` per page. The work-orders agent reuses the pilot's existing ids unchanged.

### Task 2: user-hub (extend, never rewrite)

**Goal:** Add `user-hub.hub.dashboard`, `user-hub.hub.timesheets` (`minRole: "supervisor"`), `user-hub.hub.timesheets-day` (`minRole: "supervisor"`) after batch 1's scripts (T2 §3.1).

**Files:** edit `backend/static/tutorials/user-hub.js` and `user-hub.sample.js`. Batch 1's `user-hub.home` and `user-hub.work-orders` and every existing sample key stay byte-for-byte; new scripts follow them in the §3.1 order.

**Steps (page block):**
- Read `pages/user-hub.html`, `views/userHub.js`, `hubTechnician.js` (the Dashboard panel: `DASH_SUB_MOUNTS` at line 158), `hubSupervisor.js`, `hubAdmin.js`, `hubAttendanceRoster.js`, `hubAttendanceDay.js`, `hubAttendanceHours.js`, `hubTimesheetsTab.js`, and `app/schemas/hub.py`, `attendance.py`.
- `open` and `here` as §3.1. `#hub-tab-timesheets` carries `hidden` until the role allows it; a programmatic click on a tab in a closed phone picker works (batch 1 proved it), so add no picker click.
- Dashboard per-role wording: step 1 is the three-way cell (TL default, technician, techfm_oa/admin/owner). Steps 2–8 take the spec's text for every role that has the target.
- Selector overrides (S5): Timesheets step 4 is `#hub-tabpanel-timesheets .hub-hours-week-nav`; every day-script target after `.hub-day-page .hub-hours-toolbar` is prefixed `.hub-day-page` (`.hub-day-page .hub-day-person`, `.hub-day-page .hub-hours-edit`, `.hub-day-page .hub-hours-add`, `.hub-day-page .hub-hours-lunch-line`, `.hub-day-page .hub-hours-clear-review`). Day script `open` is `#hub-tab-timesheets` then `#hub-tabpanel-timesheets .hub-day-cards .hub-day-card`.
- Sample: add `GET /hub/crew`, `GET /hub/admin`, `GET /hub/attendance/live`, `GET /hub/attendance/week` (shapes `hubCrew`, `hubAdmin`, `attendanceLive`, `attendanceWeek`). In batch 1's `GET /hub` body set ready-to-complete to 1 and add one tool out (`hubToolOut`); touch nothing else there and report the change. Records as T2 §4 row user-hub: crew of 2 (one running), led total 3, one attention row, priorities 2 with 1 unassigned; live roster with one charging, one idle, one shop, one absent; week built from `new Date()` so `week_start` is this week's Monday and `days` starts on Monday, three people on Monday with one open punch, one needs-review punch, one person-day with a lunch deduction (`lunch_minutes > 0`), `reviewable_count: 1`. Admin payload for `/hub/admin` is answered for every role (the page only asks when allowed).
- Report: the GETs the Dashboard and Timesheets issue per role; whether `.hub-day-card` first in the strip is Monday; whether any target appears only after a second fetch (crew, roster).

**Test:** the orchestrator's guard run in Task 7.

### Task 3: work-orders (extend, never rewrite)

**Goal:** Add `work-orders.card.routing` and `work-orders.card.approve` (both `minRole: "supervisor"`) and `work-orders.card.keying-hours` (no `minRole`) after the pilot and batch 1 scripts, in this file order: routing, keying-hours, approve (S3). All earlier scripts and keys stay byte-for-byte.

**Files:** edit `backend/static/tutorials/work-orders.js` and `work-orders.sample.js`.

**Steps (page block):**
- Read `pages/work-orders.html`, `views/workOrderCardHtml.js` (`detailsEditorHtml` line 421; `renderLaborEntryHtml` line 54; tabs line 545), `workOrderStatusActions.js`, `workOrderRouting.js` (`soloBackControl` line 165), the pilot files, and 0a spec 5.6 (the pilot's Labor wording).
- `open` arrays (peek and tab selectors copied from the pilot's scripts):
  - Routing: pilot peek button for `SAMPLE-1`, `.wo-tab[data-wo-tab="details"]`, `#wo-edit-card > summary`; `here` is `#wo-edit-card[open]`.
  - Keying hours: pilot peek button for `SAMPLE-1`, `.wo-tab[data-wo-tab="labor"]`; no `here`.
  - Approve: the three selectors in S4; no `here`.
- Targets from §3.2. Routing step 1 is OA+ only, so a Team Lead's first visible step is `.wo-supervisor-combo`. Keying step 2 has two variants (TL+ text, `textFor` technician).
- Keying hours and the pilot's Labor script coexist: the pilot keeps "Hours charged to this job, person by person." and "Key hours in by hand for anyone on the crew."; keying-hours adds the correct-and-remove, who-it-is-for, billing-rounding and auto-stopped explanations on different targets and has no `here`, so it runs only through Next after the pilot Labor script. Before finishing, compare every sentence of the new steps with every sentence already in the file and in `tips.js`; if any are word-for-word identical, keep the spec wording and report the pair (do not edit the older one).
- Sample: add order `SAMPLE-3`, status `ready_to_complete`, a Team Lead as `supervisor_id`, in the list (`GET /work-orders/`), with its own `GET /work-orders/<ID>` (shape `workOrderDetail`) and `GET /work-orders/<ID>/requests` (`[]`). Give order `SAMPLE-1` (pilot ids unchanged) a `supervisor_id` of a made-up Team Lead (Wren Alder), a second crew member in `assigned_to_ids`/names, and two more labor rows (three total with the pilot's 150-minute row), one with `auto_closed: true` and one hand-entered; edit the existing keys of order 1 only to add these, and keep the viewer on the crew. Extend `GET /users/` with a Team Lead, an Admin and two technicians beside the pilot's two entries; `GET /items/` and `GET /work-orders/filter-options` stay.
- Report: whether a Team Lead's first Routing step resolves; whether Approve's Back step runs from a card page and from the list; whether `#wo-act-complete-wo` renders for the viewer on `SAMPLE-3` for Team Lead and Owner.

**Test:** the guard run in Task 7.

### Task 4: mass-stage

**Goal:** Four scripts, `mass-stage.stage.new`, `.plan`, `.load`, `.again` (T2 §3.3), all Team Lead and above by page access, so no `minRole`.

**Files:** create `backend/static/tutorials/mass-stage.js` and `mass-stage.sample.js`.

**Steps (page block):**
- Read `pages/mass-stage.html`, `views/massStage.js` (list at 124, `buildStageCard` at 109, bodies at 205–300), `app/schemas/mass_stages.py`, `app/routers/mass_stages.py`, and the factories `massStageSummary`, `massStageDetail`, `stageWorkOrder`, `stageItem`.
- Apply S2: New has `#mass-stage-create-section`, `#mass-stage-community-select`, `#mass-stage-create-btn`, `#mass-stage-list .community-summary`; Planning begins with the moved step (`.stage-card[open] > .stage-summary`, the spec's "Each building shows its status..." wording) followed by the four spec steps.
- `open` and `here` as §3.3 with UUIDs. Community groups start closed, so the group summary is clicked first. The Planning `open` ends with the room summary so `.ms-add-item` is visible. Because chained scripts keep the Maple Court group open, 0a's skip rule leaves it open for Load list; do not add a `?`.
- Sample (T2 §4): `GET /mass-stages/` (summaries: Maple Court bldg 12 planning with 1 unit and 1 item; Maple Court bldg 14 loading with 2 units and 2 merged items; Cedar Row bldg 3 completed), `GET /mass-stages/<ID>` for each (details; bldg 14 has one merged item with `short > 0`, so `.ms-short` renders; Cedar Row has returned and consumed set; each unit's work order is a made-up imported number), `GET /items/` (three items), `GET /users/` (viewer plus two made-up people who can be assignees).
- Report: that the three stage ids and the first slot id in the selectors match the sample; whether `.ms-add-item` is inside the opened room card only; GETs the page issues per role.

**Test:** the guard run in Task 7.

### Task 5: history

**Goal:** `history.log.all`, `.by-item`, `.by-user` (T2 §3.4), no `minRole`.

**Files:** create `backend/static/tutorials/history.js` and `history.sample.js`.

**Steps (page block):**
- Read `pages/history.html` (including the two ids added in Task 1), `views/history.js` (load at 120–160, row render at 270–320, items at 385), `app/schemas/transactions.py`, `app/routers` for transactions, and the `transaction` and `user` factories.
- Targets as §3.4. The script keeps `open: ['#history-tabs [data-feature="item"]']` etc. as written; `here` for All uses `#history-tabs .sub-nav-btn[data-feature="all"].active` (write the full selector, not the spec's `...`).
- OA+ steps (Charge column, Pricing list) have audience tags; their targets are `hidden` for a Team Lead, so rely on the skip. Do not add `textFor`.
- Sample (T2 §4): `GET /transactions/` returns the real response envelope (read the schema; total 25, 10 rows): rows of type Added, Taken Out with a work-order number, and Correction with a reason; items priced so the Charge cell has a value; one row carries a work-order number so its charge shows a dash. `GET /items/` (three priced items), `GET /users/` (viewer, two made-up people, one archived).
- Report: whether results only appear after the transactions GET resolves (the table is shown with skeleton rows first); the GETs the page issues on load per role.

**Test:** the guard run in Task 7.

### Task 6: saved-users

**Goal:** `saved-users.users.list` and `saved-users.users.week` (T2 §3.5), no `minRole`.

**Files:** create `backend/static/tutorials/saved-users.js` and `saved-users.sample.js`.

**Steps (page block):**
- Read `pages/saved-users.html`, `views/users.js` (rows at 196–225, fix counts at 120–150), `views/userProfile.js` (days at 131–150, body at 74–100), `hubAttendanceHours.js` `PROFILABLE_ROLES`, `app/schemas/users.py`, `attendance.py`, and the factories `user`, `attendanceWeek`, `personWeek`.
- `open` for Week: `.user-profile-btn[data-id="<technician UUID>"]`, then `.user-profile-day > .user-profile-summary`; `here` as §3.5. `.user-profile-totals` is a `div` that also carries the class `user-profile-summary`; the `>` selector keeps the two apart.
- Sample (T2 §4): `GET /users/` returns the viewer's own row (from `user`), a technician, a Team Lead, a TechFM OA and one archived person (`archived_at` set); only technician, Team Lead and OA get a profile link (Owner rows do not). `GET /hub/attendance/week` has a row for the technician with one needs-review day, so `.users-fix-count` renders. `GET /hub/people/<technician UUID>/week` holds Monday first and open-able, two punches (one with an edit mark so `.day-tl-tag` renders), a completed work order, one hand-entered adjustment.
- Report: the real selector for the Actions menu if `#users-tbody .action-menu` fails for the viewer's role; the GETs issued per role.

**Test:** the guard run in Task 7.

---

### Task 7: Register, gate, review, commit

**Goal:** All five pages play for every allowed role in the guard test; the owner gets one wording table.

**Files:** Modify `backend/static/tutorials/index.js` (add `mass-stage`, `history`, `saved-users`; `user-hub` and `work-orders` already there), `docs/current-state.md` (only if a fact changed). Test: the guard (`tests/frontend/views/tutorialGuard.test.js`), `tutorialWiring.test.js`, `staticImports.test.js`, `hubIdsCensus.test.js`, `history.test.js`.

**Steps:**
1. Read the five reports. Resolve missing anchors: fix the selector in the agent's file when the markup already has it, or add the class or id yourself (and its census if the markup is a hub panel). Answer owner-only questions in the final message, never silently.
2. Register the three new pages with the entry shape `work-orders` uses.
3. Run each file one `npx vitest run` call at a time from PowerShell. Fix failures in this order: selector missing, `open` unreachable, a sample GET not answered, id prefix, `minRole` rejected, house-rule limits (shorten the wording and flag it in the table).
4. Async-target check. The player resolves its visible steps when a script starts, so History rows, Hub crew and roster panels and Mass Stage stage bodies may be missing then. If the guard reports a skipped step that the markup clearly renders after a fetch, do not reorder or reword the script. Ask the 0a owner for one change in the player (wait up to 3 s for every step target after an `open` or at start), record it as a note for the owner, and keep the script as written.
5. Reachability check from the guard's own run: every script reaches at least one visible step for each role from `minRole` (or the page minimum) up. The chain check: after Routing, Next offers Keying hours; Approve is reached from the list or the Tutorials tab (S3). If 0a's Next picks only the immediately next script and not the first qualifying one, say so in the table.
6. Look for unanswered GETs in the reports that would show real rows next to sample ones, and decide: leave or sample. Note any decision.
7. Produce one table for the owner: page, script key, step, final wording, role variants, anything changed from the spec's wording (S2's moved step first). Two checks stay with the owner (they start the server): the Hub Timesheets scripts at phone width and Mass Stage on a phone.
8. `docs/current-state.md`: change the Tutorials entry only if its facts changed (page list, `minRole` use). Delete something stale in the same edit if the doc nears its budget.
9. Commit with explicit paths only: the five pairs under `backend/static/tutorials/`, `index.js`, `history.html`, `history.test.js`, `docs/current-state.md` if changed. No trailer, no push.

**Test:** every file above green; `git status` shows nothing staged outside that list.

---

## Questions for the user

1. Approve is not offered by Next from a card page (S3), so a Team Lead reaches it from the Work Orders list chain, the Hub Tutorials tab, or after finishing the earlier scripts. Acceptable, or should Approve move first in the file (then the pilot chain would not offer Next from the Details script)?
2. S2 moves "Each building shows its status..." from New to Planning because the building rows sit in closed groups. Say if you would rather New open the first group itself (needs a player change).

## What the user checks by hand (running app, nothing pushed)

1. Hub as Team Lead and Admin: Dashboard step order, and Timesheets week and day scripts on a phone, where the tab sits behind the picker.
2. Work Orders as Team Lead: Routing lights the inline Edit details card and nothing saves; Approve and Keying hours as above; as Technician only the last three Keying steps show.
3. Mass Stage: four scripts run on Maple Court and Cedar Row; no stage appears on the real list after End.
4. History as Team Lead (no Charge or Pricing step) and as Owner (both); Users as Team Lead, with the Week script opening Technician's Monday.
5. The wording table: every sentence true against `tips.js` and `current-state.md` (not machine-checked).
