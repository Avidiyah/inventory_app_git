# Flagged clock: work-order details and stop-time edit — design

Date: 2026-11-27 · Status: awaiting approval · Size: project ·
Builds on `2026-11-25-flagged-time-step-through-design.md`

## Intent

Fix flagged time can only Accept an auto-stopped work-order clock or send
the Team Lead off to the work order. The Team Lead wants to judge and correct
the hours inside the same pop-up: see the order's details there, set when
the work really stopped, and move on. The tutorial must teach this step.

## Goals

- The clock step shows the order: number, location, task, status, crew, its
  other labor lines, and its recent notes.
- The Team Lead sets the real stop time; the clock, the Timesheets hours and
  the billed labor line all change together, and the clock is accepted in
  the same save.
- Readable on a phone as well as a desktop.
- A guided tutorial chapter walks the step on sample data.

## Non-goals

- Editing the start time (only the stop moves).
- A desktop-only feature or a "not for mobile" notice (raised, then dropped
  by the user).
- Re-admitting the order to the Leaderboard: an auto-stopped clock keeps the
  order out, corrected or not (existing rule).
- Workers: they still never see clock steps.
- Changes to punch steps.

## Anti-goals

- Two numbers that disagree: a save must never change billing without the
  Timesheets hours, or the reverse.
- A long scroll on a phone before the buttons.

## Approaches

Save:

| Option | Trade-off |
|---|---|
| **Extend the accept route with an optional stop time (picked; the only sensible way)** | One transaction; everything agrees |
| Labor PATCH, then accept | Timesheets reads the clock's times, not the labor line, so it keeps showing 12 h — ruled out |

Step layout:

| Option | Trade-off |
|---|---|
| **A. Edit first, details folded (picked)** | Short on a phone; the decision is always on screen; details one tap away |
| B. Everything open, stacked | Nothing hidden; long phone scroll before the buttons |
| C. Side by side on desktop, A on phone | Best desktop view; two layouts to build and test |

Tutorial:

| Option | Trade-off |
|---|---|
| **Guided chapter on sample data (picked)** | Shows the real step; needs a sample flagged clock and sample order |
| Reworded text line only | Cheap; never shows the step |

User picks, 2026-11-27: real stop time (not an hours number, not start and
stop); all four detail groups; layout A; guided chapter.

## The step

```
Flagged time · 2 of 5                                  [✕]
Dana R · Tue Nov 24
The clock on WO 4412 was stopped automatically after 12 hours.

WO 4412 · Bldg C Rm 210 · Replace ceiling tile · In Progress

Started Tue 7:02 AM    Stopped [Tue 7:02 PM]    12.0 h
                       (set 3:30 PM → 8.5 h, shown live)

[Save & accept]  [Accept as is]  [Open work order]  [Skip]
Save & accept sets the clock and the billed hours to the new
stop time. Accept as is keeps 12 hours.

▸ Crew and labor (3)
▸ Recent notes (5)
```

- **Order line**: number · location · task · status, wrapping on a phone. It
  reads the same way as the Work Orders card header.
- **Stopped**: the shell's time picker, as the punch editor's End field uses
  it, including a stop on the day after the start. Hours update as the time
  changes.
- **Save & accept** is disabled until the stop differs from the current one.
  It writes, then advances, like every other write in the flow. A refused
  write shows the server message in the step and stays put.
- **Accept as is**, **Open work order** and **Skip** behave as today
  (Accept renamed).
- **Crew and labor (N)**: closed `<details>`. Inside: the assigned names,
  then one row per labor line (name, hours, Self/Admin mark). This clock's
  own line is marked "this clock". N = labor line count.
- **Recent notes (N)**: closed `<details>`, the last 5 note-log lines,
  newest first, with author and time. N = lines shown. If there are no
  notes, it reads "No notes".
- **Loading**: the edit part draws at once from the queue item. The details
  show "Loading work order…" until the order arrives. If the order can't be
  read, the step says "Could not load the work order." and the edit still
  works.

## Backend

| Change | Detail |
|---|---|
| Accept route takes a stop time | `POST /hub/attendance/sessions/{session_id}/review` gains an optional body `{ "ended_at": <instant> }`. With no body or no `ended_at`, it behaves as today. |
| Validation | Team Lead+, as today. The same 404 as today when the clock is not an unaccepted auto-stop. A 400 (`PunchTimeInvalidError`, as a bad punch end) with a plain message when `ended_at` is not after `started_at` or is later than the clock's current (capped) stop. |
| Write, one transaction | The existing sweep runs first, as today. Then `session.ended_at = ended_at`, the session's labor line `minutes` = whole minutes from start to the new stop, `recorded_by_id` = actor (the labor PATCH convention: the latest editor sets the Self/Admin mark), then `reviewed_at = now`. `auto_closed_at` stays set: it is the record that the clock was auto-stopped, and the Leaderboard rule reads it. |
| Note log | A line authored by the actor, e.g. "Stop time corrected to 3:30 PM (was 7:02 PM)", appended with the existing note-log helper. |
| Events | `attendance.changed` as today, plus whatever a labor PATCH emits for the work order, so open cards refresh. |
| Payload for the step | The flow already has `work_order_id`, `number`, `started_at` and `ended_at` from `flagged_sessions`. Everything else comes from the existing `GET` work-order detail (`apiGetWorkOrder`): location, description, status, assigned names, `labor`, `notes`. The labor detail must say which line belongs to which session. If it doesn't, add the session id to the labor detail. |

No migration.

## Frontend

| Piece | Detail |
|---|---|
| `views/flaggedClockStep.js` (new) | The clock step: order line, Stopped field, Save & accept, the two folded sections. Mounted by `flaggedTimeFlow.js` the way the punch step mounts `mountPunchEditor`. No requests. |
| `views/flaggedTimeFlow.js` | Mounts the clock step. New actions: `loadWorkOrder(workOrderId)` and `saveSession(id, endedAt)`. |
| `hubTimesheetsTab.js` | Wires `loadWorkOrder` → `apiGetWorkOrder`, and `saveSession` → the accept wrapper with a body. One load per step; the result is kept for that queue item while the pop-up is open. |
| `api.js` | `apiReviewAttendanceSession(id, { endedAt } = {})` sends the body when it is given. |
| Note-log lines | The Notes tab shows the log as one text block (no parser exists). Split on the blank line `append_note_log` writes between entries; take the last 5, newest first. |
| CSS | Within `docs/design-system.md`. One column. Buttons wrap. No sideways scroll at phone width. |

## Tutorial

A new chapter in `tutorials/user-hub.js`: "Fix an auto-stopped clock",
Team Lead+.

- **Opens**: the Timesheets tab, then "Fix flagged time". On sample data,
  the first step must be the sample clock, so the sample clock sorts before
  the sample punch, or the chapter clicks Skip once.
- **Steps**: why it's flagged → order line → Stopped field and live hours →
  Save & accept vs Accept as is → Crew and labor / Recent notes →
  Skip / Open work order.
- **Sample data** (`user-hub.sample.js`): one `flagged_sessions` entry
  (`reviewable_count` counts it), and a sample work-order detail served for
  its `work_order_id`, with two labor lines and three note lines.
- The tour points and never writes. The existing Timesheets line
  ("…walks each flagged punch and clock…") stays.
- Every line stays under the 120-character limit.

## Constraints

- No `style=` attributes (CSP), no button inside a button, phone and desktop
  alike, no sideways scroll, times in Central.
- Local `main` has diverged from `origin/main` (the flagged-time commits were
  pushed as rebased copies, Takeoff is unpushed). That must be reconciled,
  with the user's go-ahead, before building.

## Docs to update in the same change

- `current-state.md`: the accept route now takes an optional stop time and
  the save updates the billed labor line.

## Tests

| Area | Test |
|---|---|
| Accept route (real TestClient) | With `ended_at`: session stop, labor minutes and `reviewed_at` all set, `auto_closed_at` kept, note line added. No body: unchanged behaviour. Stop before start, or after the cap: 400. Technician: 403. Not flagged: 404. |
| Week payload after save | The day's minutes follow the new stop; the item is no longer flagged |
| Flow module (Vitest) | Order line and folded sections render; Save & accept is disabled until the stop changes and then calls `saveSession`; a load failure still allows the edit; a refusal stays on the step |
| Tutorial | The chapter's targets exist on sample data (the existing tutorial target guard) |
| House guards | `staticImports.test.js`; `endpointTable.js` / memprobe only if a route shape check covers the body |

## My calls (not the user's; correct any)

- Only the stop time moves; it can be earlier than the auto-stop, never
  later.
- A note-log line records the correction. There is no audit table row, the
  same as the accept it extends.
- The labor line's Self/Admin mark follows the actor (the labor PATCH rule).
- If the clock's labor line was deleted on the order, the clock is still
  moved and accepted, and no labor line is created.
- "Accept" is renamed "Accept as is" now that there are two accept buttons.
- Recent notes shows 5 lines.

## Left to the builder

- Focus after the order details load (stays on the step heading).
- Exact note wording, within the note-log helper's style.
- The sample IDs and dates for the tutorial data.
