# Session handoff — edited time, profile timeline, Leaderboards (2026-10-16)

**Spec:** `docs/superpowers/specs/2026-10-16-edited-time-timeline-and-leaderboards-design.md` (ffdd4c6)
**Plan:** `docs/superpowers/plans/2026-10-16-edited-time-timeline-and-leaderboards.md` (e16b418)
**Executor:** superpowers:executing-plans (Native, inline, on `main`). **Not pushed**: pushing main deploys.
**Ledger:** `.superpowers/sdd/2026-10-16-edited-time-timeline-and-leaderboards/progress.md` (git-ignored). It holds every `Ruling:` line. Read it first.

## Done (Tasks 1–8, commits 6a766f8..7d3332d)

| Task | Result |
|---|---|
| 1 | `labor_day.week_is_open`, `attendance.day_pending_review`, `END_SOURCE_SELF_EDIT`, `TimeEditForbiddenError` (403) |
| 2 | Workers add, edit and delete their own punches in the open week. Routes are `get_current_user`; the guard is `_require_punch_editor`. |
| 3 | `punch_marks()` builds the Self/Admin tags. `/attendance/me` gains `week_punches`. |
| 4 | Workers key and revise their own hand-entered labor (they must be on the crew and in the open week). `WorkOrderLaborDetail` gains `hand_entered`, `recorded_by_self` and `week_open`. |
| 5 | The compare payload's totals and the CSV leave out pending days. The row gains `adjustment_minutes`. The CSV gets a "Pending review" row. |
| 6 | `person_week`: charged includes hand-entered labor; adds `uncharged`, `pending_review`, `punch_marks`. Adjustments carry `labor_id` and `recorded_by_self`. |
| 7 | `views/dayTimeline.js` and the profile summary (Uncharged column, hand-entered split), plus CSS |
| 8 | The Hours grid and day page grey pending days and don't count them |

## Next: Task 9 (Leaderboards tab). Nothing edited yet.

Decisions already made for Task 9, not yet in the ledger:
- **Move Export CSV and Mark all reviewed** into a new small module `views/hubTimesheetActions.js`. It is mounted on the Timesheets tab in place of `.hub-timesheets-leaderboard`. Rename the classes to `.hub-timesheets-review-all` and `.hub-timesheets-message`. **Ledger this as a ruling**: the plan said to put them in `hubTimesheetsTab.js`.
- **`hubTimesheetLeaderboard.js`** becomes a pure board, `mountHubTimesheetLeaderboard(container, payload, { kind })`. It adds a % column, ranks by %, and uses the `hub.leaderboard-accuracy` and `hub.leaderboard-efficiency` tips. `computeLeaderboard` stops subtracting pending days, because the server already does that.
- **Tests to update:**
  - `hubTimesheetLeaderboard.test.js`: a rewrite. Move the CSV and review tests to a new `hubTimesheetActions.test.js`.
  - `hubTimesheetsTab.test.js`: the order test, the "renders the week…" test, the "marks the week reviewed" test, and the profile test that asserts `.hub-leaderboard-table` is null.
  - `userHub.test.js`: the role matrix at line 39 gets a `leaderboards` key.
- **Factory:** add `adjustment_minutes: 0` to the `attendanceWeek()` row in `tests/frontend/helpers/factories.js`.

Then run Task 10 (Home tab punches), Task 11 (Labor card), and Task 12 (docs). After that, do the final whole-branch review and the finishing skill.

## Gotchas

- **Bash heredocs** break on nested `'''`. Write edit specs with Write, then run `python .superpowers/sdd/<plan>/edit.py <spec.py>`; the helper preserves CRLF.
- **`test_list_priority_none_filter_matches_null_and_blank`** fails on base too, from dev-DB rows. It is environmental.
- **`userHub.js`** is already 575 lines. Add 15 lines at most.

## Still owed to the user

An in-app check of the profile timeline, Home-tab punch editing and the Labor card once Tasks 9–11 land. The user validates manually.
