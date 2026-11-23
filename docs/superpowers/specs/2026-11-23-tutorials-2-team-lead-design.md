# Tutorials 2 — Team Lead batch (Hub, Work Orders, Mass Stage, History, Users)

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

Date: 2026-11-23 · Status: awaiting approval · Builds on 0a (`§` = its sections)

## 1. Intent

Content only: no player code. Five page agents write scripts and sample data
for the pages a Team Lead (stored `supervisor`) runs. "TL+" = Team Lead and
above, "OA+" = TechFM OA and above. Wording obeys 0a §5.2 house rules.

## 2. Scope and non-goals

| In | Out |
| --- | --- |
| Hub Dashboard, Timesheets (week, day); card routing, approval, hours; Mass Stage; History; Users list and profile | Hub Home / My Work Orders (batch 1), Leaderboards / Graphs / Report, creating users, role changes (batch 4), SMR |
| Describing the punch editor and every confirm | Opening a pop-up or the inline punch editor |

## 3. Scripts

Key form `<page>.<area>.<tab>`. "none" = no `here`, reached by Next or as the
page's first script. Order below is file order.

### 3.1 user-hub (`hub` area; the button sits at the end of the tab row)

| Key / title | For | open | here |
| --- | --- | --- | --- |
| `user-hub.hub.dashboard` Dashboard | every role | `#hub-tab-dashboard` | `#hub-tab-dashboard[aria-selected="true"]` |
| `user-hub.hub.timesheets` Timesheets | TL+ | `#hub-tab-timesheets` | `#hub-tab-timesheets[aria-selected="true"]` |
| `user-hub.hub.timesheets-day` A person's day | TL+ | `#hub-tab-timesheets`, `.hub-day-cards .hub-day-card` | `#hub-tabpanel-timesheets .hub-day-page` |

Dashboard (roles that lack a target skip it: Technician sees 1–4; Team Lead
1–7; OA+ 1, 2, 5–8 only if they lead orders, else 1, 2, 8):

| # | Points at | Wording |
| --- | --- | --- |
| 1 | `#hub-priorities-mount` | TL: High-priority work routed to you. The unassigned count is part of the main count. |
| | | technician: High-priority work assigned to you. · techfm_oa, admin, owner: Company-wide counts of high-priority work. The unassigned count is part of the main count. |
| 2 | `.hub-dash-mine` | Your own jobs: assigned to you, in progress, and ready to complete. Ready to complete means waiting on a Team Lead. |
| 3 | `.hub-time-today` | Your clock for today. Charged is the part put on work orders, and the bar shows each job through the day. |
| 4 | `.hub-tools-out` | Tools checked out to you right now, and since when. |
| 5 | `#hub-crew-mount .hub-tile-grid` | Your crew at a glance: work orders you lead, crew on the clock, and crew time today. |
| 6 | `#hub-crew-mount .hub-attention` | Things to look at: a session of 8 hours or more, one near the 11-hour cap, or assigned work with no time by 10:00 a.m. Central. |
| 7 | `#hub-crew-mount .hub-crew` | One card per person on your crew: on or off the clock, today's time and job counts. People appear once a work order is assigned under your lead. |
| 8 | `#hub-admin-mount` | The company-wide picture: work orders by status, who is on the clock now, and open requests. |

Timesheets (week):

| # | Points at | Wording |
| --- | --- | --- |
| 1 | `.hub-roster .hub-roster-head` | Who is on shift now, live. The counts show on shift, charging and idle. |
| 2 | `.hub-roster-strip` | Each card says what the person is doing: charging a work order, idle, or in the shop. Clock out ends the shift of someone who forgot. |
| 3 | `.hub-timesheets-export` | Export CSV downloads the week for payroll. Admin and above also get Mark all reviewed when days are flagged. (Admin+, else skipped) |
| 4 | `.hub-hours-week-nav` | Use the arrows to move to the previous or next week. Weeks start on Monday. |
| 5 | `.hub-day-cards` | One card per day, with how many clocked in and the paid hours. Tap a day to see who clocked in. |
| 6 | `.hub-hours-flag-open` | A dot on a day means someone is still on shift. |

Timesheets day (the punch editor is described, not opened):

| # | Points at | Wording |
| --- | --- | --- |
| 1 | `.hub-day-page .hub-hours-toolbar` | Back to week returns to the seven days. The arrows step to the previous or next day. |
| 2 | `.hub-day-page .hub-hours-heading` | Counts who clocked in and adds their paid time. A day that needs review is listed but left out of the total. |
| 3 | `.hub-day-person` | One block per person with each punch, start to end. Tap a name to open that person's week. |
| 4 | `.hub-hours-edit` | Edit opens an editor with the start and end times and an optional reason. Fixing a time clears the punch's needs-review mark. |
| 5 | `.hub-hours-add` | + Add punch records time someone forgot to clock. Choose the start and end, then Save. |
| 6 | `.hub-hours-lunch-line` | Admin+: A lunch is taken off the day automatically. Remove lunch stops that, and Restore lunch puts it back. · supervisor, techfm_oa: A lunch is taken off the day automatically. Only an Admin can remove it. |
| 7 | `.hub-hours-clear-review` | Looks right clears a needs-review flag once the times are correct. (Admin+, else skipped) |

### 3.2 work-orders (area `card`; sample = 0a's card plus order -3)

Three scripts, all after the pilot's four. None has a `here` except routing.

| Key / title | For | open | here |
| --- | --- | --- | --- |
| `work-orders.card.routing` Crew and routing | TL+ | card -1 header, Details tab, `#wo-edit-card > summary` (inline card, not a pop-up) | `#wo-edit-card[open]` |
| `work-orders.card.approve` Approving finished work | TL+ | list head of card -3 (Ready to Complete) | none |
| `work-orders.card.keying-hours` Keying hours | all with a Labor tab | card -1 header, Labor tab | none |

| Script | Points at | Wording |
| --- | --- | --- |
| Routing | `#wo-edit-card .wo-edit-location` | OA+: You can also correct the imported details here, such as location and schedule date. |
| | `.wo-supervisor-combo` | The routed Team Lead oversees this job. Pick a different one if it moves to someone else. |
| | `.wo-edit-technicians` | More than one person can be assigned. Search by name to add someone, and Remove takes them off the crew. |
| | `.wo-edit-status-field` | Start work, roll back to an earlier step, or place the job On-Hold. Ready to Complete and Review are not offered here. |
| | `[data-action="save-details"]` | Nothing changes until you tap Save details. Cancel keeps the job as it was. |
| Approve | `#wo-act-complete-wo` | Ready to Complete means a technician says the job is done and is waiting on a Team Lead. Approve agrees; the job becomes Completed, which the billing queue reads. |
| | `#wo-act-send-back-wo` | Send Back puts the job back to In-Progress so the crew finishes it. |
| | `.wo-more-btn` | Less common actions live behind this button, including Edit details. |
| Keying hours | `.wo-labor-actions` | Change a row's hours and tap Update, or Remove it. You can fix anyone's row. |
| | `#wo-add-labor .wo-labor-technician` | TL+: Pick whose hours these are. The list shows the crew, and you are added if you are not on it. · technician: This is you. A worker keys only their own hours. |
| | `#wo-add-labor` | Enter the actual hours and tap Add labor, only to correct a missed clock-in. Billing rounds the combined time up to the next 30 minutes. |
| | `.wo-labor-auto-stopped` | Auto-stopped means a clock ran past 12 hours and was closed at the cap as an estimate. Review it before billing. |

Role notes: a Technician gets none of Routing or Approve (every target is
absent) but the last three Keying steps; TechFM OA, Admin and Owner see all
Team Lead steps, plus Routing step 1.

### 3.3 mass-stage (area `stage`; Team Lead+ only, so no role gaps)

Community groups start closed, so `open` clicks the group, then the stage.

| Key / title | open | here |
| --- | --- | --- |
| `mass-stage.stage.new` New stage | none | none (first) |
| `mass-stage.stage.plan` Planning | `.community-group[data-community="Maple Court"] > .community-summary`, `.stage-card[data-stage-id="-1"] > .stage-summary`, `.room-card[data-slot-id="-1"] > .room-summary` | `.stage-card[open] .ms-add-room` |
| `mass-stage.stage.load` Load list | group, `.stage-card[data-stage-id="-2"] > .stage-summary` | `.stage-card[open] .ms-merged-actions` |
| `mass-stage.stage.again` Stage Again | `.community-group[data-community="Cedar Row"] > .community-summary`, `.stage-card[data-stage-id="-3"] > .stage-summary` | `.stage-card[open] [data-action="reuse-stage"]` |

| Script | Points at | Wording |
| --- | --- | --- |
| New | `#mass-stage-create-section` | A stage plans truck loading around work orders that are already imported. It cannot create a work order. |
| | `#mass-stage-community-select` | Pick the community, or add a new one, then enter the building number. |
| | `#mass-stage-create-btn` | Create starts the stage. Only one active stage exists for each community and building. |
| | `#mass-stage-list .community-summary` | Stages are grouped by community, then building. A Team Lead sees their own; TechFM OA and above see everyone's. |
| | `.stage-summary` | Each building shows its status: planning, loading or completed. The count shows units and items. |
| Planning | `.ms-add-room` | Type an imported work order number, an optional unit number and who is assigned, then tap Add work order. A number that was not imported is refused. |
| | `.room-summary` | Each unit is one work order. Open work order jumps to its card. |
| | `.ms-add-item` | Search an item by name or barcode, enter the planned quantity and tap Add. |
| | `[data-action="save-stage"]` | Save Mass Stage moves the stage to loading and locks the plan. |
| Load list | `.ms-merged` | The load list merges the same item across every unit. Planned is the requested total, Loaded is what is staged, Remaining is what is left to load. |
| | `.ms-merged-actions` | Staged records what you loaded, which takes it out of stock. Return puts unused staged stock back into inventory. |
| | `.ms-short` | Short by means the shelf holds fewer than the plan calls for. |
| | `.ms-rooms` | Units lists each work order in the stage. Open work order jumps to its card. |
| | `[data-action="complete-stage"]` | Mark Completed ends the stage and makes it read-only. |
| | `[data-action="delete-stage"]` | Delete removes the stage. Items already loaded stay dispensed. |
| Stage Again | `.ms-merged-stats-ro` | A completed stage is read-only. Each item shows what was returned and consumed. |
| | `[data-action="reuse-stage"]` | Stage again starts a fresh stage for the same community and building. Its item lists start empty; nothing is copied. |

### 3.4 history (area `log`; Team Lead+ only; OA+ extras skip for Team Lead)

| Key / title | open | here |
| --- | --- | --- |
| `history.log.all` All Transactions | none | `#history-tabs .sub-nav-btn[data-feature="all"].active` |
| `history.log.by-item` By Item | `#history-tabs [data-feature="item"]` | `... [data-feature="item"].active` |
| `history.log.by-user` By User | `#history-tabs [data-feature="user"]` | `... [data-feature="user"].active` |

| Script | Points at | Wording |
| --- | --- | --- |
| All | `#history-wo-row` | Type a work order number to see only its transactions; archived work orders still match. If it names an archived one, you are offered a restore. |
| | `#history-date-row` | Pick From and To dates, or leave one blank for an open range. The To date counts in full. |
| | `#history-tabs` | Switch between all transactions, one item, or one user. The filters above apply in every view. |
| | `#history-table` | Newest first. Type says added, taken out or correction, and WO / Reason shows the work order or the correction reason. |
| | `#history-table thead .admin-col` | OA+: Charge shows the base value and the marked-up value. A work-order row shows a dash, because it bills through its work-order line. |
| | `.void-txn-btn` | Void undoes a mistaken transaction: it reverses the effect on the on-hand count and removes the row from history. You confirm first. |
| | `#history-pricing-btn` | OA+: Pricing list builds a plain-text list of every priced row matching your filters, with a total. It fits the client's 41-character box, so paste it as-is. |
| | `#history-pagination` | Ten rows to a page. Prev and Next move through the matches. |
| By Item | `#history-item-search` | Search by name or barcode, then pick the item to list its transactions. |
| | `#history-wo-row` | The work order and date filters apply here too. |
| By User | `#history-user-select` | Pick a person to list their transactions. Archived users can still be picked. |
| | `#history-date-row` | The work order and date filters apply here too. |

### 3.5 saved-users (area `users`; Team Lead+ only; creating users is batch 4)

| Key / title | open | here |
| --- | --- | --- |
| `saved-users.users.list` Finding a person | none | none (first) |
| `saved-users.users.week` A person's week | `.user-profile-btn[data-id="-1"]`, `.user-profile-day > .user-profile-summary` | `#user-profile:not([hidden]) .user-profile` |

| Script | Points at | Wording |
| --- | --- | --- |
| List | `#users-search` | Type part of a name or username to narrow the list. |
| | `#users-scope` | Active, Archived, or Needs a fix. Archived people cannot sign in but keep their history. |
| | `#users-table` | One row per person with their role. A name that is a link opens that person's week. |
| | `.users-fix-count` | This flag means the person has days this week that need a fix. Tap the name to see which. |
| | `#users-tbody .action-menu` | Edit details, reset a password or archive from the Actions menu, for people you outrank. Archiving blocks sign-in but keeps their history. |
| Week | `.user-profile-header` | The person's name and role. Everything below is one week. |
| | `.user-profile-toolbar` | The arrows move between weeks. Back to users returns to the list. |
| | `.user-profile-totals` | Paid, charged to work orders, not charged, and work orders completed. Days marked with a warning need review and are left out. |
| | `.user-profile-day` | Each day shows a band (under 8h, 8–10h, over 10h) and how much paid time was charged. Tap a day to open it. |
| | `.user-profile-day .hub-hours-edit` | Under Punches, Edit fixes a punch's start or end time. + Add punch records a missed one. |
| | `.user-profile-wo-card` | Work orders completed that day. Tap one to open its card. |
| | `.day-tl-tag` | Tags such as Self-edited show who changed a punch or entered hours: the person or an Admin. |

## 4. Sample data

All lists extend a page's existing sample map (batch 1 may own the file):
add keys, never replace. People use negative ids and made-up names (e.g.
Wren Alder, Tobin Marsh, Ila Brandt, Odell Rusk); the viewer is placed by
`sample(user)` as in 0a §5.3.

| Page | GET paths answered | Made-up records |
| --- | --- | --- |
| user-hub | `/hub`, `/hub/crew`, `/hub/admin`, `/hub/attendance/live`, `/hub/attendance/week` | Viewer with 2 assigned, 1 in progress, 1 ready; one tool out. Crew: 2 people (one running), led total 3, one attention row, priority 2 / 1 unassigned. Live: one charging, one idle, one shop, one absent. Week: Monday of the current week built from the clock, 3 people on Monday with one open punch, one needs-review punch, one lunch day; reviewable_count 1 |
| work-orders | pilot's paths plus `/work-orders/-3`, `/users/`, `/items/`, `/work-orders/filter-options` | Order -3 Ready to Complete. Order -1 gets Team Lead -5, a two-person crew and 3 labor rows, one auto-closed. Users: a Team Lead, an Admin, two technicians |
| mass-stage | `/mass-stages/`, `/mass-stages/-1`, `/-2`, `/-3`, `/items/`, `/users/` | Maple Court bldg 12 planning (1 unit, 1 item), Maple Court bldg 14 loading (2 units, 2 merged items, one short), Cedar Row bldg 3 completed (returned and consumed set) |
| history | `/transactions/?page=1&page_size=10`, `/items/`, `/users/?include_archived=true` | Total 25 rows, 10 returned: Added, Taken Out with a WO number, Correction with a reason; items priced so OA+ sees Charge |
| saved-users | `/users/?include_archived=true`, `/hub/attendance/week`, `/hub/people/-1/week` | Technician -1, Team Lead -2, TechFM OA -3, one archived. Week row for -1 with one needs-review day. Profile: Monday open with 2 punches (one edit mark), a completed order, one hand entry |

Not showable on sample data: any save, confirm or its result; the time
picker and punch editor; CSV export and the pricing text; ticking clocks and
live updates; the item-search results; SMR cards.

## 5. Anchors to add (orchestrator)

Every selector above was read from the real markup and exists, except:

| Page | Add | Why |
| --- | --- | --- |
| history | `id="history-wo-row"` and `id="history-date-row"` on the two `.filter-row` divs | The three filter rows share a class |

Also verify at build: `.hub-day-card` first in the strip is Monday, and
`#hub-tab-timesheets` clicks cleanly on a phone, where tabs sit behind the
picker.

## 6. Agent table

| Agent | Owns | Must read | Reports |
| --- | --- | --- | --- |
| user-hub | `tutorials/user-hub.js`, `user-hub.sample.js` | 0a §5.2–5.3; §3.1, §4; `views/userHub.js`, `hub*.js`; `app/schemas/hub.py`, `attendance.py` | Paths; missing selectors; any text over 240 characters |
| work-orders | `tutorials/work-orders.js`, `.sample.js` | §3.2, §4; `workOrderCardHtml.js`, `workOrderStatusActions.js`; the pilot files | Same |
| mass-stage | `tutorials/mass-stage.js`, `.sample.js` | §3.3, §4; `views/massStage.js`; `app/schemas/mass_stages.py` | Same |
| history | `tutorials/history.js`, `.sample.js` | §3.4, §4; `views/history.js`; `schemas/transactions.py` | Same |
| saved-users | `tutorials/saved-users.js`, `.sample.js` | §3.5, §4; `views/users.js`, `userProfile.js`; `schemas/attendance.py` | Same |

## 7. Tests

The guard covers everything. Two small extensions are needed in it (and the
player): (1) a script may carry `minRole`, so TL-only scripts are skipped for
a Technician in the guard, the Next offer and the first-script fallback; (2)
a target that exists but is `hidden` counts as missing (History Charge and
Pricing list are hidden for Team Lead). No new test file.

## 8. Calls made by Claude, for the user to check

- Timesheets is two scripts (week, day), because `open` cannot click mid-script.
- Keying hours overlaps the pilot's "Add hours" step; it has no `here`, so it runs only through Next and never shadows the pilot Labor script.
- Edit details is opened by `open` (an inline card, not a pop-up) so its fields can be lit.
- History's "copy table" is the Pricing list button, OA+ only; a Team Lead gets no step for it.
- Dashboard carries per-role wording for Technician and OA+, since it serves every role.
- Approving needs its own sample order (-3), and chained scripts restart from the page top.
- Sample names: Maple Court, Cedar Row; people as listed in §4.
