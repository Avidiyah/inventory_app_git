# Profile day cards, Timesheets name links, work-order hand-off — design

Date: 2026-10-15
Status: approved in chat, awaiting written-spec review
Budget: ≤ 1,800 words
Builds on: `2026-10-15-user-profile-week-design.md` (D1–D10 stand unchanged).

## Problem

The per-person weekly profile exists but is reachable only from the Users
page; its day rows are plain text; a completed work order is a bare number;
an archived work order looks like a live one; and leaving the profile for a
work order loses the place.

## Goal

An Admin/Owner reaches a crew member's profile from the Timesheets grid as
well as the Users page, reads each day as a colour-coded card, opens a day to
see that day's completed work orders as cards (archived ones included and
marked), clicks a card to land on the work order, and comes straight back to
the same profile and week.

## Decisions (locked 2026-10-15)

| # | Decision | One-line rationale |
|---|---|---|
| E1 | Timesheets Hours grid: a crew name is a `hub-link-btn` for an Admin+ viewer when the row's role is Technician, Team Lead, or TechFM OA | Same gate as the Users page link |
| E2 | Clicking it mounts the profile **in place** of the leaderboard + grid, opening on the week Timesheets is showing; Back restores both from the cached week payload, no refetch | No page hop; the Admin is already looking at that week |
| E3 | Profile day rows become **cards**; still a native `<details>` — the card face is the summary, the body opens on click | No JS toggle state (D7 kept) |
| E4 | Card face unchanged: Day · Clocked · Charged · Completed count · review flag · "(on shift)" | Owner confirmed |
| E5 | Day colour is driven by **clocked** minutes: `0` none · `< 8 h` amber · `8–10 h` green · `> 10 h` red, shown as a left-edge accent on the profile day card only (not on the Timesheets grid) | Owner's thresholds; badge/edge only per the palette rule |
| E6 | Inside an open day, each completed work order is a **minimal card**: number · status badge (existing `statusBadge` / `wo-status-*` classes) · location · an `Archived` tag when archived | Status colour is the badge; archived is an extra tag, never a replacement |
| E7 | Click on a live card opens the solo work-order page **directly by id** (`openWorkOrderPage({ id, number })`); an archived card goes through `openWorkOrdersByNumberSearch` so the existing restore pop-up fires | The detail route 404s on archived; the number path already offers restore |
| E8 | The hand-off records an **origin** `{ page, userId, week }`; the solo card's Back control reads "‹ Back to profile" and re-opens that page with the profile mounted at that week. Browser Back keeps today's behaviour (unwinds the WO URL to the list) | App pages carry no history entries; a remembered origin is the smallest change |
| E9 | Week navigation is unbounded backwards; forwards stops at the current week (server 422, surfaced as today) | Already the resolver's contract |
| E10 | Out of scope: colouring the Timesheets grid cells, work-order cards in the grid drill-down, any new filter or export | Owner chose profile-only for both |

## Backend

`PersonWeekCompleted` (`schemas/hub.py`) and `PersonCompleted`
(`services/person_week.py`) gain two fields read off the already-loaded row:

```
status: str          # WorkOrder.status
archived: bool       # WorkOrder.archived_at is not None
```

The completed query already includes archived rows (no `archived_at`
filter); this makes that visible. No route, gate, or resolver change.

## Frontend

### Shared origin (`static/views/profileOrigin.js`, tiny)

```
setProfileOrigin({ page, userId, week })   // called by the profile on hand-off
peekProfileOrigin() -> origin | null       // read by the Back control's label
takeProfileOrigin() -> origin | null       // consumed once by the solo Back
clearProfileOrigin()                       // nav button click, logout
```

Module-level variable, cleared on take. Reset on logout alongside the other
caches.

### `userProfile.js`

- `mountUserProfile(container, user, { onBack, week })` — new optional
  `week` (a Monday ISO date) for the initial load.
- Day row → `<details class="user-profile-day user-profile-day-{none|short|full|over}">`;
  band from `clocked_minutes` (0 / <480 / 480–600 / >600). CSS puts the
  accent on `border-left`.
- Day body: Completed renders as `<button class="user-profile-wo-card
  wo-card-status-{status}" data-id data-number data-archived>` with
  `statusBadge(status)`, location, and `<span class="wo-archived-tag">Archived</span>`
  when archived. Charged, Adjustments, Punches lists unchanged (their numbers
  keep the number-search hand-off).
- Card click: `setProfileOrigin({ page, userId: user.id, week })`, then E7.
  `page` is passed in by the mounting caller (`"users"` or `"user-hub"`).

### `hubAttendanceHours.js` / `hubTimesheetsTab.js`

- Grid: `<th scope="row">` renders `<button class="hub-link-btn
  hub-hours-person" data-user>` when `onOpenProfile` is passed and the row's
  `user.role` is profilable; plain text otherwise.
- Tab: passes `onOpenProfile` only for an Admin+ viewer. On click, the week
  area (`.hub-timesheets-week`) is replaced by a `#hub-timesheets-profile`
  mount and `mountUserProfile(mount, row.user, { week, page: "user-hub",
  onBack })`; `onBack` re-runs `renderWeek` from `weekPayload`. A background
  week refresh (`refreshTimesheetsLive`) is skipped while the profile is
  open, the same way it is skipped while a drill-down is open.

### `users.js`

- Exports `openUserProfile(userId, { week })` so the Back path can re-open a
  profile without a click; it reuses `showProfile`. If the user list is not
  loaded yet, it loads it first (`loadUsers`).

### Work Orders Back (`workOrderActions.js`, `workOrderRouting.js`)

- `soloBackControl()` reads `peekProfileOrigin()`; when set, the label is
  "‹ Back to profile".
- `back-to-work-orders` handler: `const origin = takeProfileOrigin()`; if
  set → `exitSolo()`, `showPage(origin.page)`, then
  `openUserProfile(origin.userId, { week })` for `"users"` or
  `openTimesheetsProfile(origin.userId, { week })` (new export of
  `hubTimesheetsTab.js`) for `"user-hub"`. Otherwise today's logic.
- Origin is cleared on any other navigation (nav button click) so a stale
  origin cannot hijack a later Back.

### Styles (`styles.css`)

New rules only: `.user-profile-day-{short|full|over}` border-left accents
(amber `--status-dispense`, green `--status-stock`, red `--color-error`;
dark-mode text variants where the design system lists them),
`.user-profile-wo-card` (block button, card padding, inherits
`wo-card-status-*` border), `.wo-archived-tag` (muted pill). No `style=`.

## Error handling

| Case | Behaviour |
|---|---|
| Live card, detail fetch fails | Existing `renderSoloError` on the Work Orders page |
| Archived card | Lands on the filtered list, restore pop-up (Admin+) as today |
| Origin page no longer permitted (role changed) | `showPage` already refuses; Back falls through to the list |
| Profile week 422 (future) | Existing friendly error + Retry |

## Tests

| Layer | File | Pins |
|---|---|---|
| service | `tests/test_person_week_service.py` | an archived completed WO is returned with `archived=True` and its status; a live one `archived=False` |
| frontend | `tests/frontend/views/userProfile.test.js` | day card class by band (0, 479, 480, 600, 601); WO card shows badge + Archived tag; live click calls `openWorkOrderPage` with id and records origin; archived click calls `openWorkOrdersByNumberSearch`; `week` option drives the first fetch |
| frontend | `tests/frontend/views/hubAttendanceHours.test.js` | name is a button only with `onOpenProfile` and a profilable role; click passes the user |
| frontend | `tests/frontend/views/hubTimesheetsTab.test.js` | Admin click swaps week area for the profile at the shown week; Back restores leaderboard + grid without a fetch; live refresh skipped while open |
| frontend | `tests/frontend/views/workOrderActions.test.js` (or the existing routing test) | Back with origin → `showPage(origin.page)` + profile re-open; without origin → today's path; origin consumed once |

## Docs

One line each in `current-state.md` (User Hub) and `endpoint-map.md` H16
(new fields). No new doc.

## Files

| Area | Files |
|---|---|
| backend | `services/person_week.py`, `schemas/hub.py` |
| frontend | `static/views/profileOrigin.js` (new), `userProfile.js`, `hubAttendanceHours.js`, `hubTimesheetsTab.js`, `users.js`, `workOrderActions.js`, `workOrderRouting.js`, `styles.css` |
| tests | as above |
