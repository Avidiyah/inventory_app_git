# Tutorials 4 — Admin and Owner: Hub Leaderboards, Graphs, Report; Users add / reset / archive

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

Date: 2026-11-23 · Status: awaiting approval · Budget: ≤ 1,800 words · Builds on `2026-11-23-tutorials-0a-player-design.md` (called **0a**)

## 1. Intent

Content batch. No player code. Two agents extend two pages' existing script and sample files (0a §5.1), so a new Admin or Owner can read the Hub's three management tabs and manage accounts without a walk-through. Format, sample rules, house rules and tone are 0a §5.2, §5.3, §5.6; not restated.

## 2. Scope and non-goals

| In | Out |
| --- | --- |
| Hub: Leaderboards, Graphs, Report tabs | Hub Home, Dashboard, Timesheets, My Work Orders (batches 1–2) |
| Users: add a user, role choice, Reset Password, Archive, Restore | Finding a person, the profile week, Needs a fix (batch 2); Edit Details |
| Describing pop-ups and links | Opening the pie pop-up; the Excel download; any write |

On the Hub the tutorial button sits at the end of the tab row (placement is settled in the earlier Hub batch; assumed here).

## 3. Scripts

### 3.1 `user-hub` (append after the earlier Hub scripts, in tab order)

Who sees which tab (`userHub.js`, current-state "Roles And Access"):

| Tab | Floor |
| --- | --- |
| Graphs | TechFM OA+ |
| Leaderboards, Report | Admin+ (a TechFM OA's tab button is hidden) |

The Owner clocks no time, so is not on the board; the board still shows for them.

**`user-hub.leaderboards`** — title "Leaderboards" · for Admin, Owner · `open: ['#hub-tab-leaderboards']` · `here: '#hub-tab-leaderboards[aria-selected="true"]'`

| Step points at | Wording |
| --- | --- |
| `#hub-tabpanel-leaderboards .hub-hours-toolbar` | Choose Week or Month, then use the arrows to look at earlier ones. |
| `.hub-leaderboard-top` | Best score first. Each score comes from trusted time only, and the figures beside it show what it is made of. |
| `.hub-performance-divider` | People below the line are listed but not ranked. They clocked under 16 hours this week, or 60 this month. |
| `.hub-leaderboard-pending` | A note under a name says which day or work order was left out, and why. Reviewing an estimate does not bring it back; key the real time instead. |
| `#hub-tabpanel-leaderboards .tip-btn[data-tip="hub.leaderboard"]` | Tap the ? for the full rule, including how much each part counts. |

Rows are targeted, not `thead`: on a phone the table stacks into labelled cards.

**`user-hub.graphs`** — title "Graphs" · for TechFM OA, Admin, Owner · `open: ['#hub-tab-graphs']` · `here: '#hub-tab-graphs[aria-selected="true"]'` · no `textFor`

| Step points at | Wording |
| --- | --- |
| `.hub-graphs-header` | These charts show the work orders in circulation now. A pie is a shape, not a readout. |
| `.hub-graphs .hub-graph-seg` | Group the pies by community, service type or priority. |
| `.hub-graph-status-key` | Each colour is a work-order status. |
| `[data-graph-pie="0"]` | Each pie is one group, with its work-order count in the middle. Tap one to open it. |
| `[data-graph-pie="0"]` | The pop-up lists exact counts and can break a pie down by the other two groupings. Its red button opens the matching work orders. |
| `.hub-trend-tiles` | Trend tiles track age and close-out time, and the share closed within 4 days of schedule. Tap a tile to open its full chart. |

The pie pop-up and trend chart are only described (steps 5 and 6).

**`user-hub.report`** — title "Report" · for Admin, Owner · `open: ['#hub-tab-report']` · `here: '#hub-tab-report[aria-selected="true"]'`

| Step points at | Wording |
| --- | --- |
| `.hub-report-weeknav` | Pick a week with the arrows. This week jumps back to the one in progress. |
| `.hub-report-status` | A finished week is a frozen record and will not change. The week in progress is generated live. |
| `.hub-report-count` | How many work orders closed that week, and how many new ones were created. |
| `.hub-report-section h3` | Closed work orders are grouped by service type. The number in the heading is how many it holds. |
| `.hub-report-row-btn` | Tap a work order number to search for that exact order. |
| `.hub-report-download` | Download Excel saves this week as a spreadsheet, with the new work orders listed last. |

### 3.2 `saved-users` (append after batch 2's scripts)

Page floor is Team Lead (`nav.js`); a Technician never reaches it. Role lists below come from `assignableRoles` (strictly below the actor) and the role-change rule (TechFM OA+).

**`saved-users.add`** — title "Add a user" · for Team Lead, TechFM OA, Admin, Owner · `open: ['#users-add > summary']` · `here: '#users-add[open]'`

| Step points at | Wording | Role wording |
| --- | --- | --- |
| `#users-add > summary` | Tap + Add user to open the new-user form. | |
| `#user-first-name` | Type their first and last name. | |
| `#username` | Pick the username they will sign in with. | |
| `#user-role` | Choose their role. You can only create roles below your own. | `textFor`: owner "Choose Admin, TechFM OA, Team Lead or Technician."; admin "Choose TechFM OA, Team Lead or Technician."; techfm_oa "Choose Team Lead or Technician."; supervisor "You can only create Technicians." |
| `label[for="user-role"] .tip-btn` | Tap the ? beside Role to see what each role can do. | |
| `#user-password` | Give them a first password of at least 4 characters. | |
| `#create-user-btn` | Tap Add User to create the account. | |

**`saved-users.actions`** — title "Reset or archive" · same audience · `open: []` · no `here` (reached by the Next offer from the earlier scripts)

| Step points at | Wording | Role wording |
| --- | --- | --- |
| `#users-scope` | Active shows people who can sign in. Archived shows people who cannot. | |
| `#users-tbody tr:not(.archived-user) .menu-trigger` | Each row has an Actions menu. It lists only what you may do to that person: you must outrank them. | |
| same | Edit Role changes someone's role. You can only pick roles below your own. | `textFor` supervisor: "A Team Lead's menu has no Edit Role. Ask a TechFM OA or above to change someone's role." |
| same | Reset Password sets a new password for someone you outrank. | |
| same | Archive stops a person signing in but keeps their history. Anyone holding tools must return them first, or the confirmation can check them all in. | |

**`saved-users.restore`** — title "Restore" · same audience · `open: ['#users-scope [data-scope="archived"]']` · `here: '#users-scope [data-scope="archived"][aria-pressed="true"]'`

| Step points at | Wording |
| --- | --- |
| `#users-tbody tr.archived-user` | Archived people are marked (archived) and cannot sign in. |
| `#users-tbody tr.archived-user .menu-trigger` | Restore brings an archived person back, with their history intact. |

Menus are never opened; steps describe the closed Actions button.

## 4. Sample data

Both files extend the earlier batches' files: add keys, never redefine `GET /hub`. Read exact field names from `app/schemas/hub.py`, `app/schemas/performance.py`, `app/schemas/users.py`. Dates are computed from today inside `sample(user)`, never fixed. All ids negative.

| Page | GET path answered | Made-up records |
| --- | --- | --- |
| user-hub | `GET /hub/performance?window=week` | 6 rows: 4 ranked (scores falling, top three get medals), 2 `below_floor` with `rank` null; one row with a `day_reasons` note and one `excluded_orders` entry; `floor_minutes` 960; `to_date` true |
| user-hub | `GET /hub/graphs?weeks=12` | 7 statuses (`created` … `review`), 5 communities (Scholars, Centennial, Commons, Young Hall, Academics), about 25 cells over 3–4 service types and priorities (one null priority, first community non-zero so `data-graph-pie="0"` is enabled); `duration.buckets` = 12 Mondays, last `partial`, one week under 5 samples, one `null` on-time |
| user-hub | `GET /hub/report` | One completed week (last week, `frozen_at` set so the arrows and This week are enabled): 7 closed rows over 3 service types, `new_work_order_count` 4; numbers like `S-101` |
| saved-users | `GET /users/?include_archived=true` | 8 people: one Owner, Admin, TechFM OA, Team Lead, 3 Technicians, plus 1 archived Technician. Every viewer from Team Lead up must own at least one manageable active row and one manageable archived row |
| saved-users | `GET /hub/attendance/week` | `{ rows: [] }` (keeps real people out of the fix counts) |

Not shown on sample data: the Excel download (a plain link to the real server), other weeks and months, the pie and trend pop-ups, every Users write. The Owner's and Admin's real profile never appears.

## 5. Anchors to add

All selectors above were read against the real markup and exist today; none must be added.

| Selector | Source | Note |
| --- | --- | --- |
| `.hub-hours-toolbar`, `.hub-leaderboard-top`, `.hub-performance-divider`, `.hub-leaderboard-pending`, `.tip-btn[data-tip="hub.leaderboard"]` | `hubLeaderboardsTab.js`, `hubPerformanceBoard.js` | Rows appear only if the sample supplies them (§4) |
| `.hub-graphs-header`, `.hub-graph-seg`, `.hub-graph-status-key`, `[data-graph-pie]`, `.hub-trend-tiles` | `hubGraphs.js`, `hubGraphTrends.js` | `.hub-graphs .hub-graph-seg` first match is the front grouping switch; the pop-up is never open |
| `.hub-report-weeknav`, `-status`, `-count`, `-section h3`, `-row-btn`, `-download` | `hubReport.js` | |
| `#users-add > summary`, `#user-*`, `#username`, `#create-user-btn`, `#users-scope`, `.menu-trigger`, `.archived-user` | `saved-users.html`, `users.js`, `menus.js` | |

## 6. Agent table

| Page | Owns | Must read | Reports back |
| --- | --- | --- | --- |
| user-hub | `backend/static/tutorials/user-hub.js`, `user-hub.sample.js` (extend) | This spec §3.1, §4; 0a §5.2–5.3; its existing two files; `hubLeaderboardsTab.js`, `hubPerformanceBoard.js`, `hubGraphs.js`, `hubGraphTrends.js`, `hubReport.js`; schemas `hub.py`, `performance.py`; `tips.js` `hub.*` | Paths; any selector not found; any step over 240 characters; field names guessed |
| saved-users | `backend/static/tutorials/saved-users.js`, `saved-users.sample.js` (extend) | This spec §3.2, §4; 0a §5.2–5.3; its existing two files; `users.js`, `menus.js`, `roles.js`, `pages/saved-users.html`; schema `users.py`; `tips.js` `user.*` | Same |

Neither touches app code or `tutorials/index.js`.

## 7. Tests

The 0a guard covers targets, steps, limits, `textFor` keys and negative ids. One extra, in the guard itself: a script is not required to have a visible step for a role whose `open` tab button is hidden (Leaderboards and Report for TechFM OA, Team Lead and Technician; Graphs for Team Lead and Technician). Without it the guard as written in 0a §6 fails on correct data. Nothing else is new.

## 8. Calls made by Claude, for the user to check

- Three Users scripts (add, actions, restore), because Restore needs the Archived filter and a step cannot click.
- Role wording says "below your own", matching the code and current-state; `tips.js` `user.role` says "at or below". The tip should be corrected.
- Trend-tile wording (age, close-out, within 4 days) comes from the page's own hint text in `hubGraphTrends.js`, not `tips.js` or current-state.
- Report sample is a completed week, so the frozen line and all arrows show.
- Restore leaves the Users filter on Archived afterwards; I judged that harmless.
- The player must skip `open` when `here` already matches, or tapping `#users-add > summary` on an open form closes it. Confirm in 0a.
