# Edited time, the profile day timeline, and the Leaderboards tab — design

Date 2026-10-16. Builds on `2026-10-15-user-profile-week-design.md`,
`2026-10-14-work-order-self-assignment-design.md` and
`2026-10-15-attendance-midnight-close-and-lunch-design.md`; does not restate them.

## Problem

The 10-14 change locked hand-keyed labor to Admin/Owner, and punches were
already Admin-only, so a worker who forgets a clock has to wait for an Admin.
The lock existed to stop padding time. Admins now read every worker's day on
the User Profile, so the safeguard can be *visibility* instead: a worker's own
edits are allowed and marked, and anything still under review is left out of
the numbers.

## Goals

- Workers fix their own time: punches on the Home tab, labor on a work
  order's Labor card.
- Every edited block is visibly marked, and a worker's own edit looks different
  from an Admin's.
- The profile's opened day shows a colour-coded timeline of punched and
  charged time, with hand-entered labor set slightly apart.
- Hand-entered labor counts toward the profile's Charged total, with the split
  shown.
- Needs-review shifts are left out of the totals everywhere hours are added up.
- A new Admin/Owner **Leaderboards** tab ranks Accuracy and Efficiency.

## Non-goals

- No approval queue for self-edits. The marks and the audit are the safeguard.
- A worker never edits another person's time, and Team Leads get no crew-wide editing.
- Workers never see the profile. It stays Admin-gated.
- Live work-order labor sessions (Begin/Stop Charging) are not editable by
  workers. Only hand-entered labor rows are.

## Anti-goals (a failure even if it works)

- An edit that does not show on the profile, or that shows without saying who made it.
- A needs-review day that quietly inflates any total.
- A timeline that implies a time of day for hand-entered labor, which has none.

## Decisions (user, 2026-10-16)

| # | Decision |
|---|---|
| U1 | Workers get self-edit for both punches and labor. **Punches:** Home tab of the User Hub, with fix, add and delete. **Labor:** the work order's Labor entry card, and nowhere else. |
| U2 | Every recognised working role gets this for its **own** time only: Technician, Team Lead, TechFM OA. Admin and Owner keep editing anyone's. |
| U3 | Two marks: **Self-edited** and **Admin-edited**. |
| U4 | Workers can self-edit until the week closes. After that, only Admins can edit. |
| U5 | "Manual labor entries" means hand-entered work-order labor (today's *Adjustments*). |
| U6 | Hand-entered labor counts as Charged on the profile, and the total shows the split, e.g. `6h 30m (1h hand-entered)`. |
| U7 | The timeline sits inside an opened profile day, above the existing lists. |
| U8 | A flagged shift is one with **needs-review** set: a forgotten clock, an auto-stop, or a midnight crossing. Edited shifts are not flagged and they count. |
| U9 | Flagged shifts are left out of the profile day and week totals, and the Timesheets Hours grid. The leaderboard already does this. The Hub weekly report holds no hours and is out of scope. |
| U10 | New **Leaderboards** tab, Admin/Owner only. The existing board moves there. It holds two rankings: **Accuracy** = live-charged ÷ clocked, and **Efficiency** = (live + hand-entered) ÷ clocked. |
| U11 | A worker who fixes their own flagged punch clears the flag. The shift counts again, marked Self-edited, and the audit shows the change. |

## Builder's calls (marked; the user can overturn)

- **B1 — Week close.** No attendance week-close record exists ("Mark all
  reviewed" only clears flags). Closed means the Central week has ended: Monday
  00:00 `America/Chicago`. A punch is placed in a week by `started_at`, and a
  labor row by `created_at`, which is the same rule the profile already files
  them under.
- **B2 — Self vs Admin.**
  - **Punch:** take every `attendance_punch_edits` row on it. An edit by the
    punch's owner is Self, and an edit by anyone else is Admin. If both apply,
    both tags show. A punch the worker added through self-edit is Self, and the
    add writes an audit row the way `admin_add_punch` does.
  - **Labor row:** `recorded_by_id == technician_id` is Self, anything else is
    Admin. A self-revision of a row an Admin entered sets `recorded_by_id` to
    the worker, so the latest editor wins. Builder: confirm that the
    labor-revise path writes `recorded_by_id`. If it doesn't, add that.
- **B3 — Uncharged** on the profile = Paid − Charged, floored at 0. Charged
  includes hand-entered labor (U6). The leaderboard keeps its own clocked-based
  formula, because its rate maths already depends on it.
- **B4 — A self-delete** needs a reason, the same as an Admin delete. Deletes stay soft.
- **B5 — Labor self-edit** needs the worker to be on the crew. This is the
  existing Technician write-lock, and Begin Charging adds them to it.
- **B6 — Efficiency over 100%** (more hand-entered labor than clocked time) is
  shown as the real figure, not capped, and ranks normally. It is the signal an
  Admin wants to see.

## Permissions

- **Punch routes** (`POST/PATCH/DELETE /hub/attendance/punches`) open from
  `ROLE_ADMIN` to any signed-in user. The service checks the row: a non-Admin
  may act only where the punch owner is the actor (and, for an add, the
  `user_id`), and only when the punch's week is still open (B1). A refusal is
  403 with the message "You can only change your own time in the current week."
  Overlap and other validation is shared with the Admin path.
- **Labor:** `_require_labor_editor` passes Admin/Owner as now. Anyone else
  passes when `entry.technician_id == actor.id` (for an add, the target
  technician is the actor), the row's week is open, and B5 holds.
- Owner is never a punch-holder. The existing rules stand.

## Totals rule (U8, U9)

A day with `pending_review` set is shown and greyed, with a ⚠. Its clocked,
paid, charged (live and hand-entered) and uncharged minutes are all left out of
day and week totals, just as the leaderboard sets the whole day aside today.
The rule lives in one server helper, used by `person_week`, the Hours payload
and every CSV built from them, so screen and export can't drift apart.

When a worker edit sets or changes the end of their own needs-review punch, it
clears `needs_review` (U11), the same as an Admin edit does today. The audit
row records it.

## The profile day timeline (U7)

Inside each opened `<details>` day, above the lists. The layout is three
stacked lanes on a shared hour axis, plus one lane set slightly apart:

```
 6a    8a    10a   12p   2p    4p
 ├─────┼─────┼─────┼─────┼─────┤
 Punched  ███████████████████░░░███████     ← neutral; ░ = lunch gap
 Charged     ▓WO1234▓▓  ▓WO1301▓▓▓          ← brand red
 Uncharged ▁▁▁       ▁▁         ▁▁▁         ← thin hatched bar, derived
 ┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄┄
 Hand-entered  [WO1310 · 1h · Self] [WO1288 · 30m · Admin]   ← no time axis
 Legend: ■ Punched ■ Charged ▨ Uncharged ▧ Edited ⚠ Needs review
```

- **Axis:** reuse the Technician Dashboard strip (`hubTechnician.js`
  `timelineRangeMinutes` / axis / block helpers, and the `.hub-timeline*` CSS).
  Lift them into `hubWeek.js` or a small `timelineStrip.js` rather than copying
  them. Range = earliest punch or session start to latest end, padded to whole
  hours.
- **Colours** (TechFM palette, red = primary; status accents stay badge-only):

  | Lane | Fill | Text |
  |---|---|---|
  | Punched | neutral surface (white-at-alpha on dark, grey on light) | — |
  | Charged | brand red | WO number |
  | Uncharged | thin bar, neutral hatch | — |
  | Hand-entered | red **outline**, hollow chip | `WO · minutes · Self`/`Admin` |

- **Edited:** a diagonal-stripe overlay on any punched block or hand-entered
  chip, plus a tag inside or above it: **Self-edited** (brand red, outlined) or
  **Admin-edited** (neutral, outlined). The colour never carries the meaning on
  its own; the text tag always does.
- **Needs-review day:** the whole strip is desaturated, with a ⚠ and the label
  "Not counted — needs review".
- **Hand-entered lane:** a dashed divider and roughly 8 px of space separate it
  from the timed lanes (U5). The chips are laid out left to right, because they
  have no time of day (anti-goal). Chip width is proportional to minutes against
  the same scale as the axis, with a minimum width so the label fits.
- **Interaction:**
  - Clicking a charged block or a chip opens the work order (the same hand-off
    the lists use).
  - Clicking a punched block opens the existing punch editor for an Admin
    viewer.
  - Each block has a `title` and an `aria-label` that read the full fact, e.g.
    "Punch 7:02–11:30, self-edited by J. Smith 10/14: end 11:00→11:30". The
    old→new values come from the audit rows, which the payload adds per punch
    as `edits: [{by_name, self, field, old, new, at}]`.
- **Narrow widths:** the strip is always full width. Labels hide on blocks
  under ~40 px wide, and the tooltip or tap still carries them. Chips wrap. No
  horizontal scroll.
- **CSP:** no `style=`. Left and width are set through CSSOM from
  `data-left` and `data-width`, as the dashboard strip does. No nested buttons:
  a block is a single `<button>` and its tag is a `<span>`.

**Summary row columns** become Day · Paid · Charged · Uncharged · Completed.
Charged reads `6h 30m` with a muted `incl. 1h hand-entered` under it when any
hand-entered labor exists. The week row does the same. The hint line "not
counted as charged" is deleted.

## Home tab punch editing (U1)

Below the punch block in `hubHome.js`, a **"This week's punches"** disclosure.
It lists the worker's punches for the open week (from `me_payload`, extended
with this week's punches, ids and edit tags). Each punch has **Edit**, and the
list has **+ Add punch**. These mount the existing `mountPunchEditor`, with
Delete available. A punch from a closed week is not listed. Self-edited tags
show here too, so the worker can see what an Admin will see.

## Labor card (U1)

The work order's Labor entry card shows Add/Edit/Remove to a non-Admin only on
that person's own rows, and only while the row's week is open (B1, B5). Each
row shows its Self/Admin tag.

## Leaderboards tab (U10)

- A new User Hub tab, **Leaderboards**, shown to Admin/Owner only. The
  existing board moves out of the Timesheets tab whole, with its CSV export and
  week picker. Timesheets keeps the day strip and Hours grid.
- The tab holds two boards side by side, stacking on narrow widths. Each ranks
  by its percentage. Columns: name, %, clocked, charged, uncharged, made, lost.

  | Board | % | Charged counts |
  |---|---|---|
  | **Accuracy** | live ÷ clocked | live work-order clock only (today's board) |
  | **Efficiency** | (live + hand-entered) ÷ clocked | live + hand-entered |

- Both boards drop `pending_review` days whole, as today. Hand-entered labor is
  dated by `created_at`, as on the profile. A one-line tip under each title
  says what it rewards. The CSV gets one sheet or section per board.

## Data and endpoints

- `person_week` day: add `uncharged_minutes`, `hand_entered_minutes`, and
  per-punch / per-adjustment `edit_tags: ["self"|"admin"]` plus `edits[]`
  (punch only). `charged_minutes` now includes hand-entered labor. Week totals
  follow the totals rule.
- The Hours week payload carries the per-person efficiency inputs the board
  needs (`hand_entered_minutes` per day already exists as
  `adjustment_minutes`), so the board stays a pure view of the payload.
- `me_payload` adds `week_punches` (the open week, with ids and tags).
- No migration.

## Tests (targeted)

- **Service:**
  - A worker can add, edit and delete their own punch in the open week.
  - Another person's punch is 403.
  - A punch in a closed week is 403.
  - Each self-edit writes audit rows by the worker.
  - Labor follows the same matrix.
- **Totals:** a pending-review day is excluded from profile day and week totals
  and from the Hours grid totals and CSV.
- **`person_week`:**
  - Charged includes hand-entered labor.
  - Uncharged is floored at 0.
  - The self and admin tags come out right for: owner-only edits,
    Admin-only edits, both, a worker-added punch, and an Admin-recorded labor
    row revised by the worker.
- **Frontend:**
  - Timeline lanes render.
  - The hand-entered lane is separated.
  - Tags render as text.
  - A needs-review day is greyed and labelled.
  - The Leaderboards tab is hidden for non-Admins.
  - The two boards rank by their own %.
  - The Home tab lists and edits only open-week punches.

## Docs

Update `current-state.md` (self-edit rule, totals rule, Leaderboards tab) and
`endpoint-map.md` (punch route gate change, payload additions). Supersede the
"Admin/Owner only" labor line from the 10-14 spec in current truth.
