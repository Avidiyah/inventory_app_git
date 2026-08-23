# Tooltip Coverage Phase 2 - Spec, Plan, and Handoff

Status: **implementation complete 2026-08-23; browser acceptance remains
open because no connected browser was available.**

Implementation result (2026-08-23): all 19 registry entries, five existing-key
reuses, and 25 source anchor placements are implemented. The registry has 54
keys and the source references 51; only `wo.export`, `txn.quick-mode`, and
`txn.advanced` remain parked. The owner approved minimal scoped wrappers for
the two login checkbox rows and recount editor, keeping each tooltip button a
sibling of the real form-control label instead of a second interactive label
descendant. This required scoped additions to `styles.css` and a corresponding
wrapper exception in `docs/design-system.md`; the runtime remains unchanged.

Code review also corrected planned copy to shipped behavior: auto-stop is lazy
and applies when a clock is found past the cap; Supervisor+ can record time on
visible orders without technician assignment; Hub thresholds are inclusive;
stale work can have no session activity at all; company timesheets include live
Supervisor and Technician accounts; and matching item requests can lack a work
order. These are behavior reconciliations, not product-rule changes.

Changed files for Phase 2: `backend/static/tips.js`, `shell-head.html`,
`styles.css`, `pages/create-item.html`, `pages/saved-items.html`,
`pages/saved-users.html`, `views/billingEditor.js`, `views/workOrders.js`,
`views/hubPriorities.js`, `views/hubSupervisor.js`, `views/hubTimesheets.js`,
`views/hubAdmin.js`, `views/massStage.js`, `views/userRequestCards.js`,
`docs/current-state.md`, `docs/design-system.md`, `docs/open-work.md`, and this
plan. The User Request sibling hint was corrected alongside its tooltip so the
always-visible guidance does not contradict requests with closed or absent work
orders.

Machine verification: all changed JavaScript passed `node --check`; 208 focused
auth/billing/Work Order tests, 148 Hub/Mass Stage/User Request audit tests, and
25 focused item/request tests passed. Registry/reference scanning found no
unknown keys; the assembled shell contains 39 static anchors, both login keys,
no tooltip nested in a button or summary, and no inline `style=`. `/`,
`tooltip.js`, `tips.js`, `styles.css`, and `main.js` returned 200, the dynamic
recount markup preserved its `for`/`id` association with the tip outside the
label, and `git diff --check` passed. Browser hover/tap/keyboard/viewport checks
and screenshots were attempted but could not run because the browser controller
reported no available browser; `IMP-038` remains open for that acceptance.

Tracks `IMP-038` in `docs/open-work.md`. This is a second, curated coverage
pass over the tooltip system implemented by `IMP-037`; it does not replace or
reopen the mechanism design in
`docs/superpowers/specs/2026-08-23-tooltips-design.md`.

## 1. Goal

Add field-help to the remaining places where the app exposes a non-obvious
domain rule but currently relies on code comments, browser-native `title`
text, or no explanation at all.

This is not a target to put a `?` beside every control. Success means the hard
rules are discoverable without turning routine fields into visual noise.

The implemented inventory is:

- 19 new `TIPS` keys.
- 5 additional placements that reuse an existing key.
- 25 new source anchor placements across the login shell, Users, Find
  Item, Add Tool, Work Orders, User Hub, Mass Stage, and User Requests.
- 54 registry keys total, of which 51 are expected to be referenced.
- The existing parked keys `wo.export`, `txn.quick-mode`, and
  `txn.advanced` remain unreferenced unless their control layout is redesigned
  in a separately approved change.

Counts are acceptance targets. If implementation inspection invalidates an
anchor or rule, document the deviation in this file instead of forcing the
count.

## 2. Starting Point

The first pass already provides:

- `backend/static/tips.js`: 35-key plain-text registry.
- `backend/static/tooltip.js`: `tipHtml`, `closeTip`, and one delegated runtime.
- `backend/static/styles.css`: `.tip-btn` and `.tip-bubble` styling.
- `backend/static/main.js`: one `installTooltips()` call.
- `backend/static/views/nav.js`: closes an open tip on page leave.
- 32 referenced keys across the existing static pages and User Hub clock/graphs.

Do not rewrite the runtime, add a second tooltip component, or add per-view
event listeners. Dynamic markup only needs `tipHtml(key)` because the document
listener is already delegated.

The planning session started with the first-pass rollout still modified in the
working tree. A future implementer must begin with `git status --short`, inspect
the overlapping diff, and preserve it. Do not reset or re-create the phase-one
work from `HEAD`.

## 3. Sources and Reconciliation

Use these sources in order:

1. `docs/superpowers/specs/2026-08-23-tooltips-design.md` for the mechanism and
   locked first-pass constraints.
2. This file for phase-two coverage, copy, and implementation order.
3. `docs/design-system.md` for the `?` versus `.hint` rule.
4. Current frontend and domain/service code for the business facts behind each
   string.

One documentation conflict must be resolved before shipping
`auth.shift-session`: `docs/current-state.md` currently says a non-remembered
session has no server cap, while `backend/app/services/auth.py` and its tests
give both remembered and non-remembered sessions a 12-hour absolute cap. The
code says the checkbox only controls whether the cookie survives a browser
restart. Treat the code/tests as current behavior and correct
`docs/current-state.md` in the implementation closeout.

## 4. Inherited Constraints

All first-pass decisions D1-D8 still apply:

- Copy lives only in `tips.js`; anchors carry stable keys.
- A trigger is a real button and works by click/tap, hover, and keyboard.
- The singleton fixed-position bubble and delegated runtime remain unchanged.
- Copy is plain text, one to three short sentences, with no links or markup.
- Existing `.hint` and `.field-hint` prose stays unless a separate layout
  change is approved.
- No backend route, schema, service, model, or migration changes.
- Browser interaction remains the authoritative visual/accessibility check.

The nested-button rule is absolute: never put `tipHtml()` or hand-authored
`.tip-btn` markup inside another `<button>`, including a graph card or pipeline
tile. Also treat `<summary>` as an interactive host and do not put a tooltip
button inside it.

## 5. Phase-Two Decisions

| ID | Decision | Locked choice |
|---|---|---|
| P2-D1 | Coverage | Curated domain help, not blanket field coverage. |
| P2-D2 | Reuse | Reuse an existing key whenever the same rule appears in another editor. Do not fork copy by page. |
| P2-D3 | Anchor order | Existing label/heading/legend first; then an inline text label whose trigger remains inside the text flow. Never add a flex-row sibling just to host a tip. |
| P2-D4 | Dynamic markup | Import and call `tipHtml`; no hand-authored dynamic tooltip button strings. |
| P2-D5 | Repeated rows | Prefer one section-level tip over a trigger on every repeated card or table row. |
| P2-D6 | Visible guidance | Keep instructions needed during every use as `.hint`; a tooltip supplements rather than replaces them. |
| P2-D7 | Native titles | Replace only the static domain explanation on `auto-stopped`. Dynamic-value titles and icon command names remain outside the registry. |
| P2-D8 | Layout | No CSS or mechanism change is expected. Any new visible heading or wrapper requires owner approval and before/after screenshots. |
| P2-D9 | Testing | No frontend framework or new test harness. Use source/served-shell probes plus a real browser role and viewport matrix. |

## 6. Existing-Key Reuse

These placements add no registry copy:

| Existing key | New anchor | File |
|---|---|---|
| `item.barcode` | Edit Item `Barcode` label | `backend/static/pages/saved-items.html` |
| `item.location` | Edit Item `Location` label | `backend/static/pages/saved-items.html` |
| `item.price` | Edit Item `Price` label | `backend/static/pages/saved-items.html` |
| `item.product-link` | Edit Item `Product Link` label | `backend/static/pages/saved-items.html` |
| `wo.status` | Work Order Edit details `Status` text label | `backend/static/views/workOrders.js` |

## 7. New Copy Inventory

The strings below are implementation-ready. Preserve the substance; small
copy edits for length or voice are allowed if they do not change a rule.

### Login and accounts

| Key | Anchor | Copy |
|---|---|---|
| `auth.shift-session` | `Stay signed in for this shift` label in `shell-head.html` | Every sign-in expires after 12 hours. Turn this on only to keep the session cookie when the browser closes; it does not extend the 12-hour limit. |
| `auth.notifications` | `Enable notifications` label in `shell-head.html` | Allows this device to receive work-order alerts for the signed-in account. On iPhone and iPad, push works only when the app is installed to the Home Screen; logging out removes this device's subscription. |
| `user.lifecycle` | `Users` heading in `saved-users.html` | Archiving blocks sign-in but keeps the user's history and allows restoration later. A user holding tools must return them first, or the archive confirmation can check them all in. |

### Items and tools

| Key | Anchor | Copy |
|---|---|---|
| `item.notes` | contextual `Notes` heading in `saved-items.html` | Each note has a unique name and a stored type: text, number, or true/false. Choosing the right type keeps later displays and edits consistent. |
| `tool.barcode` | Add Tool `Barcode` label in `create-item.html` | The label used to find this tool for checkout, return, and inventory. It must be unique among active tools; archiving a tool frees its barcode for reuse. |

### Work Orders and billing

| Key | Anchor | Copy |
|---|---|---|
| `wo.routing` | `Assigned technicians` legend in `workOrders.js` | The Supervisor owns routing and approval. Assigned technicians are the people who can work the order and record time; more than one can be assigned. |
| `wo.entry-mode` | `New entries:` label in `workOrders.js` | Dispense records new material as stock-moving usage. Retroactive adds a paper-sheet entry to the work order without changing on-hand stock; the mode applies only to entries added after the selection changes. |
| `billing.quantity` | shared `Bill for` label in `billingEditor.js` | This changes the invoice only; it never puts material back in stock. Zero keeps the line but charges nothing, while a blank value or the full recorded quantity clears the override and bills all units. |
| `wo.auto-stopped` | inline after the `auto-stopped` labor badge in `workOrders.js` | A clock left running for 12 hours is closed at the cap and marked as an estimate. Review the entry before billing it. |

### User Hub

| Key | Anchor | Copy |
|---|---|---|
| `hub.priorities` | `Priorities` text label in `hubPriorities.js` | Technicians see high-priority work assigned to them. Supervisors see their routed crew, and TechFM OA and above see company-wide counts; unassigned means no technician is attached within that scope. |
| `hub.crew` | `My crew` text label in both crew states in `hubSupervisor.js` | Crew membership is derived from live work orders routed to you, not from a permanent team list. A person appears after a work order is assigned under your supervision. |
| `hub.timesheets` | week-range `<strong>` in `hubTimesheets.js` | Each day includes tracked sessions plus manual adjustments. Supervisors see their routed crew; TechFM OA and above see the company. Open a day cell to see the tracked/adjustment split and any estimate flags. |
| `hub.attention` | `Needs attention` text label in `hubSupervisor.js` | Long session appears after 8 hours and approaching cap after 11. Idle means assigned work with no tracked time after 10:00 a.m. Central; stale means an In-Progress or On-Hold work order has no labor-session activity for three days. |
| `hub.clock-attention` | `On the clock now` text label in `hubAdmin.js` | Long session appears after 8 hours and approaching cap after 11. A clock still open at 12 hours is auto-stopped and should be reviewed as an estimate. |
| `hub.exceptions` | `Exceptions` text label in `hubAdmin.js` | Counts open recount, missing-price, and item requests, plus the Admin Review queue. Stale work orders are live In-Progress or On-Hold orders with no labor-session activity for three days. |
| `hub.billing-week` | `Billing - this week` text label in `hubAdmin.js` | Material and labor dollars use receipt billing for work orders completed in the current Central-time week. Average completion time and the daily sparkline use the trailing 14 Central days, so they do not share the dollar totals' date window. |

### Mass Stage and User Requests

| Key | Anchor | Copy |
|---|---|---|
| `stage.load-list` | `Load list` heading in `massStage.js` | The load list merges the same item across every unit. Planned is the requested total, Loaded is what has been staged, Remaining is still needed, and Return records unused staged stock back into inventory. |
| `requests.recount` | `Correct count to` label in `userRequestCards.js` | Saving a corrected count writes an inventory adjustment with this reason. Mark resolved only closes the request; it does not change stock. |
| `requests.siblings` | `Also close these requests...` text in `userRequestCards.js` | Matching item requests start checked because one catalogue fix can close them together. Each selected request adds its own quantity to its own live work order; closed work orders are skipped, and unchecked requests stay open. |

## 8. Deliberate Exclusions

Do not add tips to these areas in this phase:

- Routine labels: names, usernames, ordinary search fields, dates, quantities,
  and obvious Save/Cancel/Edit commands.
- Work Order Labor rounding and correction instructions. They are billing
  critical and needed every time, so the existing visible hints stay visible.
- Request edit snapshot guidance and Graphs overlap/duration explanations. They
  are needed whenever the user reads those views and remain `.hint` text.
- `wo.export`, `txn.quick-mode`, and `txn.advanced`. Their existing controls
  still have no safe label/heading anchor; do not introduce wrapper/layout work
  in a tooltip-only phase.
- Tooltip buttons inside Work Order action buttons, graph-card buttons,
  pipeline tiles, row-action buttons, or `<summary>` elements.
- `title` strings that describe a dynamic value (`hubTechnician` timeline) or
  merely name an icon command (remove/archive). Those are not central field-help
  copy.
- Rich content, links, images, per-row generated copy, or backend-driven tips.
- Removing existing hints or changing the tooltip runtime/CSS.

## 9. File Plan

Expected modifications:

- `backend/static/tips.js`
- `backend/static/shell-head.html`
- `backend/static/pages/create-item.html`
- `backend/static/pages/saved-items.html`
- `backend/static/pages/saved-users.html`
- `backend/static/views/billingEditor.js`
- `backend/static/views/workOrders.js`
- `backend/static/views/hubPriorities.js`
- `backend/static/views/hubSupervisor.js`
- `backend/static/views/hubTimesheets.js`
- `backend/static/views/hubAdmin.js`
- `backend/static/views/massStage.js`
- `backend/static/views/userRequestCards.js`
- `docs/current-state.md`
- `docs/open-work.md`
- this plan at closeout

No changes are expected in `tooltip.js`, `styles.css`, backend Python behavior,
database migrations, or API schemas.

## 10. Implementation Tasks

### Task 0 - Baseline and copy confirmation

- [x] Read the first-pass tooltip spec, especially D1-D8 and section 5.5.
- [x] Run `git status --short` and preserve all pre-existing tooltip changes.
- [x] Confirm the current baseline: 35 registry keys and 32 referenced keys.
- [x] Confirm the 19 strings in section 7 against current domain/service code.
- [x] Reconcile the remembered-session statement in `docs/current-state.md`.
- [x] Do not proceed if any string would describe intended rather than shipped
      behavior.

### Task 1 - Registry and static shell/pages

Files: `tips.js`, `shell-head.html`, `create-item.html`, `saved-items.html`,
`saved-users.html`.

- [x] Add all 19 new keys to `TIPS`, grouped by page/domain.
- [x] Add the two login triggers beside their existing checkbox labels using
      the owner-approved scoped wrappers.
- [x] Add `user.lifecycle` to the Users heading.
- [x] Add `item.notes` to the contextual Notes heading.
- [x] Add `tool.barcode` to the Add Tool Barcode label.
- [x] Add the four existing item keys to their Edit Item labels.
- [x] Confirm no static source line contains more than one opening `<button>`
      when it contains `data-tip`.

### Task 2 - Work Orders and shared billing editor

Files: `workOrders.js`, `billingEditor.js`.

- [x] Import `tipHtml` from `../tooltip.js` in both modules.
- [x] Reuse `wo.status` inside the status editor's existing text label.
- [x] Add `wo.routing` inside the Assigned technicians legend.
- [x] Add `wo.entry-mode` inside the New entries label, not inside either
      option or action button.
- [x] Render `wo.auto-stopped` after the textual badge in the same inline text
      container and remove only that badge's obsolete static `title` copy.
- [x] Add `billing.quantity` inside the shared Bill for label. Verify it appears
      in both History and Work Order billing editors without caller changes.
- [x] Run `node --check` for both files.

### Task 3 - User Hub

Files: `hubPriorities.js`, `hubSupervisor.js`, `hubTimesheets.js`, `hubAdmin.js`.

- [x] Import `tipHtml` in each changed module.
- [x] Add `hub.priorities` to the one section label, not each count tile.
- [x] Add `hub.crew` to both empty and populated My crew labels.
- [x] Add `hub.attention` to the Needs attention label.
- [x] Add `hub.timesheets` inside the existing week-range `<strong>` so no new
      toolbar child or visible heading is introduced.
- [x] Add `hub.clock-attention`, `hub.exceptions`, and `hub.billing-week` to
      their section text labels, never to a pipeline tile button.
- [x] Run `node --check` for all four modules.

### Task 4 - Mass Stage and User Requests

Files: `massStage.js`, `userRequestCards.js`.

- [x] Import `tipHtml` in both modules.
- [x] Add `stage.load-list` to the existing Load list heading.
- [x] Add `requests.recount` beside the Correct count to label using its
      owner-approved scoped wrapper.
- [x] Add `requests.siblings` beside the existing Also close these requests
      text, outside every checkbox label.
- [x] Run `node --check` for both modules.

### Task 5 - Machine verification

- [x] Run `node --check` for every changed JavaScript module.
- [x] Scan all `data-tip` and `tipHtml("...")` references and assert every key
      exists in `TIPS`.
- [x] Expected registry: 54 keys. Expected referenced-key set: 51 keys.
- [x] Assert the only unreferenced keys are `wo.export`, `txn.quick-mode`, and
      `txn.advanced`.
- [x] Assert there are no tooltip buttons nested in buttons or summaries.
- [x] Run a FastAPI `TestClient` served-shell probe: `/`, `tooltip.js`,
      `tips.js`, `styles.css`, and `main.js` all return 200; the two login
      triggers appear in the served root.
- [x] Confirm the assembled shell still contains zero inline `style=`
      attributes.
- [x] Run `git diff --check`.

No new frontend test framework or test file is required by this plan. These
machine checks complement, but do not replace, Task 6.

### Task 6 - Browser acceptance

Run against a freshly loaded shell, not a tab that predates the edit.

- [ ] Unauthenticated: both login tips open by click and keyboard without
      blocking checkbox or Sign In interaction. Clicking the `?` itself must
      not toggle its checkbox.
- [ ] Technician: login, Hub Priorities, and reachable item tips work; gated
      Users, billing, routing, and Admin Hub tips do not render.
- [ ] Supervisor: routing, entry mode, auto-stopped labor, crew, attention, and
      timesheet tips render after repeated card/Hub rerenders.
- [ ] TechFM OA/Admin/Owner: Users lifecycle, billing quantity, admin Hub,
      Mass Stage, and request-resolution tips render in their gated views.
- [ ] Desktop mouse: hover opens, pointer leave closes, click toggles, only one
      bubble is visible.
- [ ] Keyboard: Tab reaches each trigger, Enter/Space opens, Escape closes and
      returns focus.
- [ ] Mobile/touch: tap opens, outside tap closes, portrait rotation and scroll
      reposition or close cleanly.
- [ ] Representative viewports: 1440x900 and 390x844. Confirm no label wrapping,
      toolbar shift, clipped bubble, or card-height jump caused by a trigger.
- [ ] Capture before/after screenshots for Login, one Work Order card, User Hub
      Timesheets, Mass Stage Load list, and a User Request fulfilment flow.

### Task 7 - Documentation and handoff closeout

- [x] Correct the session-lifetime statement in `docs/current-state.md` based
      on code/tests.
- [ ] Remove `IMP-038` from `docs/open-work.md` once implementation and browser
      acceptance are complete; that file is the backlog, not shipped history.
- [x] Record the implementation-complete/browser-acceptance-open status plus
      actual key/reference counts, changed files, deviations, tests, and the
      unavailable manual result.
- [x] Update `docs/design-system.md` only if implementation changed a tooltip
      rule. Do not duplicate the guidance already present.
- [x] Update Obsidian repository memory from the final diff and verification.

## 11. Browser-Acceptance Handoff

Resume here when a connected browser is available:

1. Retrieve targeted Obsidian context for `inventory-app-git` and tooltips.
2. Read this implementation result and run `git status --short`; preserve the
   existing Phase 1 and Phase 2 working-tree changes.
3. Start the local app, load a fresh shell, and execute Task 6's role,
   interaction, viewport, rerender, and screenshot matrix.
4. If Task 6 passes, remove `IMP-038` from `docs/open-work.md`, change this
   status from implementation-complete to implemented/accepted, record the
   browser results, and update Obsidian repository memory.
5. Do not merge or push without explicit approval.

The principal failure modes are silent: an unknown key hides the trigger, a
nested button is reparented by the HTML parser, a new flex child shifts a row,
and a stale browser tab makes correct source look absent. Check those before
changing the runtime.
