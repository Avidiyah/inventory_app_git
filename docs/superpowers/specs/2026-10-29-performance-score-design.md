# Performance score: weekly boards and a month-to-date report — design

Date: 2026-10-29. Status: approved 2026-10-29. Supersedes the Leaderboards
section of `2026-10-16-edited-time-timeline-and-leaderboards-design.md`.

## Intent

The Leaderboards tab today ranks one ratio (job-clock time ÷ punch-clock
time) and the owner does not trust it: estimated times reviewed in by "Mark
all reviewed", job clocks running with nobody punched in, and tiny
denominators all climb the board. The owner wants one composite
**performance score** per person, built only from times that are real,
shown as weekly boards and a monthly report that fills in as the month goes.

## Goals

- One ranked list per window (week, month to date) with a single score and
  its visible components, so any rank can be explained from the row.
- Billed dollars per person, split by labor share on each work order.
- Estimated or implausible time never scores. Only keying the actual time
  brings a day back.

## Non-goals

- Replacing the Timesheets tab, the CSV export, the profile Hours grid, or
  the invoice math. Billing's 30-minute rounding stays per work order.
- Materials revenue per person. Materials belong to the order.
- Changing what "Mark all reviewed" does for payroll. It keeps clearing
  the warning; it just no longer admits a day to the score.
- Role changes: Leaderboards stays Admin+.

## Anti-goals

- A score that a person can raise by keying more hand-entered labor or
  by charging while not clocked in.
- A short week beating a full one on percentages alone.
- A silent exclusion. Every day or order left out is named on the row.

## Decisions (the owner's)

| # | Decision |
|---|---|
| D1 | Components: Efficiency, Accuracy, total $ billed, combined by weights into one score. |
| D2 | Weekly boards stay; a monthly view is added, recomputed on every read (month to date). |
| D3 | A work order's billed labor is credited to its people by their share of its labor minutes. |
| D4 | An estimated day (midnight close, 12-hour auto-close, reviewed or not) stays out of the score until someone edits the actual time. Review alone never counts it. |
| D5 | No "Lost $" / wasted-money figure. Billed $ plus the percentages is enough. |
| D6 | A flawed job clock is fixed by deleting its labor entry and re-keying the hours; no session editing in this work. |
| D7 | Off-shift charging gets a 5-minute grace per day before the day is excluded. |

## Design (the builder's calls, marked ◇ where the owner has not ruled)

### Window

- Week: Monday–Sunday Central, resolved by `work_order_report.resolve_week`,
  exactly as today.
- Month: first of the month through today (or month end), Central. ◇ The
  month picker steps whole calendar months; a past month is closed and
  stable, the current one is month to date.
- Both windows are one read of the same new payload shape; the week payload
  is not reused for scoring.

### Trusted time (the filter every component reads)

A person's day is **counted** only when none of these hold:

| Excluded when | Source today |
|---|---|
| Any punch that day was midnight-closed or is flagged `needs_review` | `AttendancePunch.needs_review`, `auto_clock_out` |
| Any job session that day was auto-closed at the 12-hour cap or is running past it | `WorkOrderLaborSession.auto_closed_at`, `capped_session_end` |
| Any closed job session that day is longer than 12 hours | session span |
| Charged time outside any punch that day is more than 5 minutes (owner, 2026-10-29) | `attendance.minutes_charged_outside_shift` |
| Charged time (sessions + hand-keyed) exceeds clocked time | existing over-day rule |

`reviewed_at` on a session and a cleared `needs_review` on a punch do **not**
re-admit the day (D4). What does:

- Punch: `end_source` is `manual`, `admin_edit` or `self_edit`. The
  estimate sources `auto_clock_out` and `self_reported` exclude the day
  whatever the flag says. No new column.
- Session: `auto_closed_at` is null. A session's end cannot be edited
  today, so the only fix is deleting its labor entry (which deletes the
  session, per 5f7aa69) and keying the labor by hand. That day then counts
  again, with the hand-keyed minutes in Efficiency only. No new column.

A **counted work order** for Billed $ is one completed inside the window
(`completed_at`, Central) none of whose labor sessions are excluded by the
rows above. ◇ An order with one flawed session is out for everyone on it,
named on each of their rows, until that session is fixed.

### Components (per person, over counted days / orders)

| Component | Definition | Weight ◇ |
|---|---|---|
| Billed $ | Σ over counted orders of `labor_charge(real_minutes)` × (person's real labor minutes on that order ÷ the order's real labor minutes). Skilled-Technician lines are ignored. | 40% |
| Efficiency | (session minutes + hand-keyed minutes) ÷ clocked minutes | 25% |
| Accuracy | session minutes ÷ clocked minutes | 20% |
| Clean days | counted days ÷ days with any punch or charge in the window | 15% |

Scaling: each component is divided by the best value in the window among
ranked people, giving 0–100, then weighted and summed. The best person on
every component scores 100. Percent components cap at 100 before scaling
(the over-day rule already keeps them there).

Eligibility floor ◇: ranked only with at least 16 counted clocked hours in a
week, 60 in a month. Below the floor the person is listed under the ranked
rows, greyed, with "below N h" instead of a rank. The company total row is
dropped (D5 makes it meaningless).

Ties: score, then Billed $, then name.

### Server vs client

The current boards sum client-side from the Timesheets week payload. The
score needs labor-share splits across work orders and a month of days, so
it moves server-side:

- New read `GET /hub/performance?window=week|month&start=YYYY-MM-DD`
  (Admin+, side-effect-free, no sweep, no locks). Returns the window, the
  weights, the floor, and one row per person: components raw and scaled,
  score, rank or null, counted/excluded day counts, excluded order numbers,
  and the exclusion reasons as a fixed enum list.
- New service `services/performance_score.py` (pure scoring in
  `domain/performance.py` so the weights and scaling are unit-tested with
  no database). Reuses `attendance_week.week_payload` logic for punches,
  `labor_summary.crew_range_summaries` for sessions, `work_orders_smr.labor_split`
  for the real/skilled split.
- The front end (`hubLeaderboardsTab.js`, `hubTimesheetLeaderboard.js`)
  renders; it computes nothing but formatting.

### What the Admin sees

Leaderboards tab, one board instead of two:

- Toolbar: Week | Month switch, ◀ label ▶, and the existing tooltip.
- Columns: Rank, Person, Score, Billed $, Efficiency %, Accuracy %, Clean
  days (n / m), Clocked h. Medals on the top three as today.
- Under a name, in the existing warning style, one note per reason with a
  count: "3 days left out: 2 forgotten clock-out, 1 charged off shift",
  "WO 4471 left out: job clock auto-closed".
- Unranked people below a thin rule with "below 16 h".
- Tooltip text rewritten to state the components, weights and the rule
  that reviewing never counts a day in. Self-explanatory, no legend.
- Empty window: "Nobody has trusted time this week yet."

Monthly view uses the same table; the label reads "October 2026 (to date)".

### Docs

`docs/current-state.md` Leaderboards bullet and `docs/endpoint-map.md`
gain the new read; the old client-side rule text is deleted. Tips updated.

## Constraints

- Side-effect-free read (spec §4 of the attendance design); pollable.
- Files under 500 lines; `hubTimesheetLeaderboard.js` is rewritten, not
  grown.
- Weights, floor and cap live as constants in `domain/performance.py`, one
  place, no settings UI.
- Tests: domain scoring (weights, scaling, floor, ties), service exclusion
  rules one per table row above, router role gate, Vitest for the board
  render including the unranked rows and the notes.

## Left to the builder

- Query shape for labor shares over a month without N+1.
- Exact enum names for exclusion reasons and their user-facing wording.
