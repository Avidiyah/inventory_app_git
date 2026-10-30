# Performance Score Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace the two client-computed Leaderboards boards with one server-scored board that ranks a week or month to date by a weighted score built only from trusted time.

**Architecture:** Pure rules in `domain/performance.py` (exclusions, weights, scaling, floor); one side-effect-free service `services/performance_score.py` that reuses the attendance week read, `labor_summary.crew_range_summaries` and `work_orders_smr.labor_split`; one new `GET /hub/performance` route; the Leaderboards tab fetches it and renders one table with a Week/Month switch.

**Tech Stack:** FastAPI + SQLAlchemy + pytest (backend/tests), vanilla ES modules + Vitest (tests/frontend).

**Spec:** `docs/superpowers/specs/2026-10-29-performance-score-design.md`

## Global Constraints

- Read is side-effect-free: no sweep, no row locks, no commit.
- Weights 40/25/20/15 (billed, efficiency, accuracy, clean days); floor 16 h week / 60 h month; off-shift grace 5 minutes; cap 720 minutes. All in `domain/performance.py`, nowhere else.
- Review never re-admits a day: punch `end_source` must be `manual`/`admin_edit`/`self_edit`; session `auto_closed_at` must be null.
- Files under 500 lines; no inline `style=`; no nested buttons.
- Commit per task; stage explicit paths only (shared checkout).

## Review Focus

1. A person with charged time but zero punches in the window (over-day on every day) must appear unranked with the reason, not divide by zero. → Task 1 `test_score_rows_zero_clocked_is_unranked`.
2. A month view opened on the 1st before anyone punched must render the empty line, not a table with a NaN best value. → Task 1 `test_score_rows_empty`, Task 5 empty-state test.
3. A work order completed in the window whose labor is all Skilled-Technician lines (no real minutes) must credit nobody and not divide by zero. → Task 2 `test_billed_shares_skip_orders_with_no_real_minutes`.
4. A session crossing Central midnight must flaw both days it touches, not only its start day. → Task 2 `test_session_over_cap_flaws_every_day_it_touches`.
5. A past month must be stable: `start` on a month boundary in the past returns the full month, not month-to-today. → Task 2 `test_month_window_in_the_past_runs_to_month_end`.

---

### Task 1: Pure scoring rules

**Files:**
- Create: `backend/app/domain/performance.py`
- Test: `backend/tests/test_performance_domain.py`

**Interfaces (produces):**
```python
WEIGHTS = {"billed": 40, "efficiency": 25, "accuracy": 20, "clean_days": 15}
FLOOR_MINUTES = {"week": 16 * 60, "month": 60 * 60}
OUTSIDE_SHIFT_GRACE_MINUTES = 5
# exclusion reason codes (str constants)
PUNCH_ESTIMATED = "punch_estimated"        # end_source auto_clock_out/self_reported, needs_review, or crosses_midnight
SESSION_AUTO_CLOSED = "session_auto_closed"  # auto_closed_at set, or running past cap
SESSION_OVER_CAP = "session_over_cap"      # closed span > LABOR_SESSION_MAX_MINUTES
CHARGED_OFF_SHIFT = "charged_off_shift"    # outside_shift_minutes > grace
CHARGED_OVER_CLOCKED = "charged_over_clocked"
REASON_LABELS: dict[str, str]  # user-facing: "forgotten clock-out", "job clock auto-closed", "job clock over 12 h", "charged off shift", "charged more than clocked"

def day_exclusions(*, punches, timeline, clocked_minutes: int, charged_minutes: int,
                   outside_shift_minutes: int, now: datetime) -> list[str]
    # punches: objects with end_source, needs_review, crosses_midnight (attendance_week.WeekPunch)
    # timeline: labor_summary.TimelineEntry list; over-cap = ended_at and (ended_at - started_at) > 720 min
    # returns distinct codes in the order above; empty = counted

@dataclass(frozen=True)
class PersonInput:
    user_id: uuid.UUID; clocked_minutes: int; session_minutes: int; adjustment_minutes: int
    billed_dollars: Decimal; counted_days: int; active_days: int
    day_reasons: dict[str, int]; excluded_orders: list[tuple[str, str]]  # (number, reason code)

@dataclass(frozen=True)
class PersonScore:
    user_id; raw: dict[str, Decimal|int]; scaled: dict[str, int]; score: int; rank: int | None
    clocked_minutes; counted_days; active_days; day_reasons; excluded_orders; below_floor: bool

def score_rows(people: list[PersonInput], *, window: str) -> list[PersonScore]
```

Rules the tests pin: efficiency = (session+adjustment)/clocked, accuracy = session/clocked, both as whole percent capped at 100, 0 when clocked is 0; clean_days = counted/active ×100 (0 when active is 0); billed raw = Decimal dollars. Scaled = raw ÷ best raw among **eligible** (clocked ≥ floor) ×100, rounded; best of 0 → everyone 0. Score = Σ scaled × weight ÷ 100, rounded. Eligible rows ranked by score desc, billed desc, then caller order; ineligible rows follow with `rank=None`, `below_floor=True`, still scaled against the eligible best.

- [ ] **Step 1: Write failing tests** in `backend/tests/test_performance_domain.py`:
  - `test_day_exclusions_each_reason` — parametrize over the five reasons, one trigger each, assert the single code; a 5-minute outside-shift figure is counted, 6 is not; a reviewed auto-closed session (`auto_closed=True`, `needs_review=False`) still returns `SESSION_AUTO_CLOSED`; `end_source="self_reported"` with `needs_review=False` returns `PUNCH_ESTIMATED`.
  - `test_score_rows_weights_and_scaling` — two eligible people, Ann billed 1000/eff 90/acc 80/clean 100, Bo billed 500/eff 100/acc 100/clean 50 → Ann scaled {100,90,80,100} score 94 (93.5 half-even), Bo {50,100,100,50} score 72 (72.5 half-even); Ann rank 1.
  - `test_score_rows_floor` — week window, 15 h clocked → `rank is None`, `below_floor`; 16 h → ranked.
  - `test_score_rows_zero_clocked_is_unranked` — clocked 0, session 60 → percents 0, unranked, no exception.
  - `test_score_rows_empty` — `score_rows([], window="month") == []`.
  - `test_score_rows_tie_breaks_on_billed_then_order`.
- [ ] **Step 2:** `pytest backend/tests/test_performance_domain.py -q` → ImportError.
- [ ] **Step 3:** Implement `backend/app/domain/performance.py` per the interface. Percent math with `Decimal` and `round()` half-even like the rest of the domain.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** `git add backend/app/domain/performance.py backend/tests/test_performance_domain.py && git commit -m "feat(performance): scoring rules, exclusions, weights"`.

### Task 2: Scoring service

**Files:**
- Create: `backend/app/services/performance_score.py`
- Test: `backend/tests/test_performance_service.py` (copy the helpers at the top of `test_attendance_compare_service.py`)

**Interfaces:**
- Consumes: Task 1; `attendance_week.week_payload(db, week_start=, now=)`; `labor_summary.crew_range_summaries(db, ids, start, end, now=, cap_running=True)`; `attendance.minutes_charged_outside_shift`; `labor_day.day_bounds`, `central_date_of`, `week_bounds_containing`; `work_orders_smr.labor_split`; `wo.labor_charge`, `wo.capped_session_end`.
- Produces:
```python
@dataclass(frozen=True)
class PerformanceWindow:
    window: str; start: date; end: date; to_date: bool; server_now: datetime
    weights: dict[str, int]; floor_minutes: int; rows: list[PersonRow]
@dataclass(frozen=True)
class PersonRow:            # PersonScore fields + user: User
def resolve_window(window: str, start: Optional[date], now: datetime) -> tuple[date, date, bool]
    # week: start via work_order_report.resolve_week; end = start+6
    # month: start None → first of current Central month; start.day != 1 → ReportWeekError("start must be the first of a month"); future → ReportWeekError; end = min(last day of month, Central today); to_date = end < last day
def window_payload(db, *, window: str, start: Optional[date], now: datetime) -> PerformanceWindow
```
Assembly: days = every Central date in [start, end]; punches via `attendance_week.week_payload` for each Monday covering the range (`week_bounds_containing`), keeping only days in range; sessions/adjustments via one `crew_range_summaries(start, end)`; per day call `day_exclusions`; active day = clocked>0 or charged>0. Billed: one query of `WorkOrder` with `completed_at` in the window's UTC bracket, `joinedload(labor_entries)`, `joinedload(labor_sessions)`; order flawed if any session has `auto_closed_at`, or is closed over cap, or running past cap (reuse the Task 1 predicates on sessions); else `split = labor_split(order.labor_entries)`, skip if `split.real_minutes == 0`, each technician's share = `labor_charge(split.real_minutes) × their real minutes / split.real_minutes` (Decimal, quantize to cents at the end). Flawed orders go to every technician on them as `(number, reason)`. People = union of attendance rows and technicians on counted/flawed orders; those with no attendance row get clocked 0.

- [ ] **Step 1: Failing tests**:
  - `test_week_counts_a_clean_day` — 8 h punch, 7 h session → efficiency 88, accuracy 88, counted 1/1.
  - `test_reviewed_estimate_stays_out` — punch `end_source="auto_clock_out"`, `needs_review=False` → counted 0/1, `day_reasons == {"punch_estimated": 1}`.
  - `test_session_over_cap_flaws_every_day_it_touches` — closed session 20:00→next day 10:00 (14 h) → both days excluded with `session_over_cap`.
  - `test_off_shift_grace` — 5 min outside counted, 6 min excluded.
  - `test_billed_split_by_labor_share` — order completed in window, Ann 90 min, Bo 30 min labor entries → Ann 93.75, Bo 31.25 (labor_charge(120)=125.00).
  - `test_billed_shares_skip_orders_with_no_real_minutes` — only a skilled (technician_id None) entry → no rows credited, no error.
  - `test_flawed_order_credits_nobody` — order with an `auto_closed_at` session → both techs `excluded_orders == [(number, "session_auto_closed")]`, billed 0.
  - `test_order_completed_outside_window_is_ignored`.
  - `test_month_window_in_the_past_runs_to_month_end` — `resolve_window("month", date(2026,9,1), now=Oct 29)` → `(2026-09-01, 2026-09-30, False)`; current month → end = Central today, `True`; `date(2026,9,2)` → `ReportWeekError`.
  - `test_read_is_side_effect_free` — call twice, assert no `auto_closed_at`/`needs_review` changed and `db.dirty` empty.
- [ ] **Step 2:** Run → fail.
- [ ] **Step 3:** Implement. Keep file < 500 lines; billing assembly in a private `_billed_shares(db, start, end, now) -> tuple[dict[uuid, Decimal], dict[uuid, list[tuple[str,str]]]]`.
- [ ] **Step 4:** Run → PASS. Also `pytest backend/tests/test_attendance_compare_service.py -q` still green.
- [ ] **Step 5:** Commit `feat(performance): window scoring service`.

### Task 3: Route and schema

**Files:**
- Create: `backend/app/schemas/performance.py`
- Modify: `backend/app/routers/hub.py` (after `get_hub_attendance_week`)
- Test: `backend/tests/test_performance_router.py`; add one case to `backend/tests/test_route_role_gates.py`

**Interfaces (produces):** `GET /hub/performance?window=week|month&start=YYYY-MM-DD`, Admin+ (`require_min_role(roles.ROLE_ADMIN)`), `response_model=PerformanceResponse`:
```python
class PerformanceUser(BaseModel): id, first_name, last_name, role
class PerformanceExcludedOrder(BaseModel): number: str; reason: str; label: str
class PerformanceRow(BaseModel):
    user: PerformanceUser; rank: Optional[int]; below_floor: bool; score: int
    billed_dollars: Decimal; efficiency_pct: int; accuracy_pct: int
    counted_days: int; active_days: int; clocked_minutes: int
    scaled: dict[str, int]; day_reasons: list[PerformanceReason]  # {code, label, days}
    excluded_orders: list[PerformanceExcludedOrder]
class PerformanceResponse(BaseModel):
    window: str; start: date; end: date; to_date: bool; server_now: datetime
    weights: dict[str, int]; floor_minutes: int; rows: list[PerformanceRow]
```
`window` is validated by hand (`str`, 422 on anything but `week`/`month`; see memory: int/str Literal Query params misbehave here). Reasons are labelled from `REASON_LABELS` in the router's projection.

- [ ] **Step 1: Failing tests** (real `TestClient`, pattern of `test_attendance_week_router.py`): `test_week_payload_shape`, `test_month_default_is_current_month_to_date`, `test_bad_window_is_422`, `test_non_first_month_start_is_422`, role gate: technician 403, admin 200.
- [ ] **Step 2:** Run → 404.
- [ ] **Step 3:** Implement schema + route; docstring states Admin+, side-effect-free, the window contract.
- [ ] **Step 4:** Run → PASS.
- [ ] **Step 5:** Commit `feat(hub): GET /hub/performance`.

### Task 4: API helper and factory

**Files:**
- Modify: `backend/static/api.js` (beside `apiGetHubAttendanceWeek`), `tests/frontend/helpers/factories.js`
- Test: `tests/frontend/api.test.js` if a sibling case exists for `apiGetHubAttendanceWeek`; else none.

**Produces:** `apiGetHubPerformance({ window = "week", start = null })` → `liveGet('/hub/performance?window=…&start=…')`; factory `performanceWindow(overrides)` returning a week payload with two rows (Ann rank 1 score 94, Bo rank 2 score 72) and a third `below_floor` row (Cy, rank null, clocked 300), matching Task 3's shape.

- [ ] Steps: add helper; add factory; run `npx vitest run tests/frontend/api.test.js` if touched; commit `feat(api): performance read + factory`.

### Task 5: The board view

**Files:**
- Create: `backend/static/views/hubPerformanceBoard.js` (replaces `hubTimesheetLeaderboard.js`; delete it and `tests/frontend/views/hubTimesheetLeaderboard.test.js`)
- Modify: `backend/static/styles.css` (rename `.hub-leaderboard-*` rules you keep; drop `-made/-lost`, `-grid`; add `.hub-performance-unranked`), `backend/static/tips.js` (`hub.leaderboard` text; delete `-accuracy`/`-efficiency`)
- Test: `tests/frontend/views/hubPerformanceBoard.test.js`

**Produces:** `mountPerformanceBoard(container, payload)` — pure render, no fetch. Columns: Rank, Person, Score, Billed $, Efficiency %, Accuracy %, Clean days (`n / m`), Clocked (`formatHm`). Medals for ranks 1–3 as today. Notes under the name in `.hub-leaderboard-pending` style: `"{days} left out: {label} ×{n}, …"` and `"WO {number} left out: {label}"`. Ranked rows, then a `<tr class="hub-performance-unranked">` divider row "Below {floor} h", then unranked rows greyed with "—" rank. Empty rows → `<p class="hint hub-leaderboard-empty">Nobody has trusted time {this week|this month} yet.</p>`. Caption names the window. New tip text states the four components, weights, the floor, and "Reviewing an estimate clears its warning but never counts it; key the real time."

- [ ] **Step 1: Failing tests**: renders ranked order and medals; billed formatted via `formatMoney`; exclusion notes text; unranked divider and rows; empty state per window; no `style=` attribute anywhere in output; no `<button>` inside the table.
- [ ] **Step 2:** `npx vitest run tests/frontend/views/hubPerformanceBoard.test.js` → fail.
- [ ] **Step 3:** Implement; delete the old view + test; `grep -rn hubTimesheetLeaderboard backend/static tests` must return nothing.
- [ ] **Step 4:** Run → PASS; `npx vitest run tests/frontend/staticImports.test.js` green.
- [ ] **Step 5:** Commit `feat(leaderboards): one scored board view`.

### Task 6: Tab with Week/Month switch

**Files:**
- Modify: `backend/static/views/hubLeaderboardsTab.js`, `backend/static/styles.css` (switch styling reusing `.secondary-btn` + `aria-pressed`)
- Test: `tests/frontend/views/hubLeaderboardsTab.test.js` (rewrite)

**Consumes:** Task 4 helper and factory; Task 5 `mountPerformanceBoard`.
State: `{ window: "week", start: null, payload, requestId }`. Toolbar: two buttons `Week` / `Month` (`aria-pressed`), ◀ label ▶, tip. Label: week via `weekLabel`; month `"October 2026"` plus `" (to date)"` when `to_date`. ◀ ▶ step 7 days via `shiftMonday` or one calendar month (`start` = first of prev/next month, ISO). ▶ disabled when the window is the current one. Switching window resets `start` to null and refetches. `resetLeaderboardsTab` clears all state.

- [ ] **Step 1: Failing tests**: first render fetches week; Month click fetches `window: "month", start: null`; ▶ disabled on current window; ◀ on month calls with previous first-of-month; error state with Retry; reset clears.
- [ ] **Step 2:** Run → fail. **Step 3:** Implement. **Step 4:** PASS; full `npx vitest run` green. **Step 5:** Commit `feat(leaderboards): week/month switch on the performance board`.

### Task 7: Docs

**Files:** `docs/current-state.md` (Leaderboards bullet + the attendance row's file list), `docs/endpoint-map.md` (new H-row after H8; H8/H14 lose `hubTimesheetLeaderboard.js`), `docs/open-work.md` only if an item is closed by this.

- [ ] Replace the client-side rule text with: components, weights, floor, trust rule (review never re-admits), billed split by labor share, orders with a flawed clock earn nothing. Delete stale lines; stay under budgets.
- [ ] `pytest backend/tests -q -k "performance or attendance_compare or route_role"` and `npx vitest run` green.
- [ ] Commit `docs: performance score board`.

## Verification before handoff

- `pytest backend/tests -q` and `npx vitest run` green on the branch.
- Manual in-app check is the user's (memory: don't auto-run the preview server). Push/deploy only when the user says so (CI gate = production).
