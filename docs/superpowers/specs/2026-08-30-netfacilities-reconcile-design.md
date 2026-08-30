# NetFacilities import reconciliation: auto-close absent work orders

Date: 2026-08-30
Status: approved design, not yet implemented

## Problem

A work order lives in this app only because a NetFacilities CSV import
created it. Nothing brings it back out. When somebody closes a work order
*in NetFacilities*, the vendor simply stops exporting it -- and this app
keeps showing it as live, forever, on the Work Orders page and in every
supervisor's queue.

The signal is already sitting in the import and being thrown away: a work
order that is live here and **absent from the CSV** has been closed
upstream. This design reads that signal, closes those work orders, writes
a note saying why, and gives the operator one red button to undo the whole
sweep if the import was wrong.

## Decisions

Settled with the user before writing this:

1. **The export is exhaustive.** The captured CSV is always the full list
   of open work orders, never a filtered subset. Absence therefore means
   closed upstream. The safety net is the undo button, not a scope filter.
2. **Undo is the last sweep, time-limited.** One import's sweep is one
   batch. The red button restores exactly that batch and disappears after
   24 hours.
3. **No status exclusions.** The sweep closes every absent live work order
   regardless of status, running clock, or logged materials. (The two
   consequences of this are recorded under Risks.)
4. **The note is authored by `TechFM`**, reading: `closed automatically:
   this work order was not in the latest NetFacilities import. Review it in
   NetFacilities for details.`
5. **Storage is two columns on `work_orders`** (Approach A), not a batch
   table and not a derived-from-note-text scan.

### Assumption carried into implementation

**A restored work order is eligible to be auto-closed again by the next
import.** It is still absent from NetFacilities, so re-closing it is
arguably the correct read; the operator restores it again if they disagree.
The rejected alternative was a permanent `reconcile_exempt` flag, which
creates invisible state that is hard to discover months later. Flag this on
spec review if you want it the other way -- it is a one-column change, but
it is much cheaper to decide now than after the migration ships.

## Data model

Two nullable columns on `work_orders`:

| Column | Type | Meaning |
| --- | --- | --- |
| `auto_closed_batch_id` | `UUID NULL` | The sweep that closed this row. One id per import that closed at least one work order. |
| `auto_closed_at` | `TIMESTAMPTZ NULL` | When that sweep ran. Equal to the row's `archived_at` at the moment of the sweep. |

Both are cleared on restore. The undo button clears them, and
`restore_work_order` is amended to clear them too, so the existing
per-work-order restore cannot leave a live row still wearing a batch id.
That is what keeps a restored row from looking auto-closed forever, and it
is why "already manually restored" rows fall out of the undo query for free.

`archived_at` remains the single source of truth for closed/live. These two
columns are provenance only; nothing reads them to decide visibility.

Migration `add_work_order_auto_close_batch`, `down_revision =
"fcbc2524ea62"` (current head). Adds both columns plus a partial index:

```sql
CREATE INDEX ix_work_orders_auto_closed_at
    ON work_orders (auto_closed_at DESC)
    WHERE auto_closed_at IS NOT NULL;
```

The partial predicate matters: almost every row is `NULL` here, and the
only queries are "newest batch" and "rows in batch X".

## The sweep

Runs inside `services.work_orders.import_work_orders`, after the row loop
and before the summary is returned, so both import entry points
(`POST /work-orders/import` and
`POST /integrations/netfacilities/cloud/downloads/import`) get it without
either router growing a second call. This is the same argument that put the
realtime emits and the supervisor notification in the shared
`run_csv_import`.

1. **Collect what the CSV saw.** While parsing rows, accumulate
   `seen: set[str]` of `wo.normalize_number(number)` for every row with a
   non-blank number. Presence in the CSV is what counts, not import
   outcome -- a row that matched an archived work order (`closed`) was
   still present upstream and must not be swept.
2. **Empty-CSV guard.** If `seen` is empty, skip the sweep entirely and
   report `auto_closed = 0`. A CSV with a valid `WORK ORDER` header and
   zero data rows currently parses cleanly; without this guard it would
   close every live work order in the system. This is not a policy knob,
   it is a correctness floor.
3. **Select victims.** Live work orders (`archived_at IS NULL`) whose
   `lower(btrim(number))` is not in `seen`, **excluding `legacy IS TRUE`**.
4. **Close each one**, in a single pass with one commit:
   - `_stop_all_sessions(db, row, actor=user)` -- the same call
     `archive_work_order` makes, with the importing user as the actor.
   - `row.notes = wo.append_note_log(row.notes, AUTO_CLOSE_NOTE,
     author_name="TechFM", occurred_at=now)`
   - `row.archived_at = now`, `row.auto_closed_batch_id = batch_id`,
     `row.auto_closed_at = now`
5. Return `auto_closed` in the summary dict alongside the existing seven
   counters.

`batch_id` is generated per import and stamped only if at least one work
order was closed, so an import that closes nothing leaves no batch behind
and the red button stays hidden.

### Why `legacy` is excluded

Not a preference -- a loop. `legacy` rows predate NetFacilities and can
never appear in any export, so every import would close all of them, and
because undo is time-limited they would churn closed on each run with no
way to make it stop. They are not "absent," they are out of scope. This
mirrors the existing carve-out: legacy work orders already have their own
Owner-only bulk archive (`archive_live_legacy_work_orders`).

## The undo

Module constant `AUTO_CLOSE_UNDO_WINDOW = timedelta(hours=24)`.

`latest_auto_close_batch(db, *, user) -> dict | None` -- the newest
`auto_closed_at` among rows that are **still archived**, have a non-null
`auto_closed_batch_id`, and fall inside the window. Returns `batch_id`,
`closed_count`, `ran_at`, or `None`.

`undo_auto_close_batch(db, *, batch_id, user) -> int` -- restores every row
in that batch that is still archived and still inside the window: clears
`archived_at`, `auto_closed_batch_id`, and `auto_closed_at`. Returns the
count actually restored, which may be lower than the preview if somebody
restored rows by hand in between (the same honesty
`archive_live_legacy_work_orders` already practises about its own preview).

Both gated at `ROLE_TECHFM_OA` -- the role that can import and the role
that can archive. Deliberately *not* `ROLE_SUPERVISOR`, which is the gate
on single-work-order restore: a bulk undo is an import-operator action.

**Labor sessions do not come back.** A session stopped by the sweep stays
stopped after restore, exactly as it does for a manual archive-then-restore
today. The undo returns the work order, not the running clock.

## API

Two routes on the work-orders router, declared **before** `/{work_order_id}`
so the path segments are not parsed as an id -- the same ordering constraint
`/filter-options` and `/legacy/archive` already live under.

```
GET  /work-orders/auto-close/latest          -> WorkOrderAutoCloseBatch | null
POST /work-orders/auto-close/{batch_id}/undo -> WorkOrderAutoCloseUndoResult
```

```python
class WorkOrderAutoCloseBatch(BaseModel):
    batch_id: UUID
    closed_count: int
    ran_at: datetime


class WorkOrderAutoCloseUndoResult(BaseModel):
    restored: int
```

`WorkOrderImportResult` gains one field:

```python
auto_closed: int   # live work orders closed because the CSV did not list them
```

The undo route emits `_emit_review_queue_changed(None)` then
`_emit_status_changed(None)`, in that order, matching every other
collection-level command. The sweep needs no emits of its own: it runs
inside the import, whose emits already fire afterwards.

## Reporting

The import summary line in `static/views/workOrders.js` (`importSummary`)
gains a third clause, shown only when the count is non-zero:

```
3 new work orders · 2 with a supervisor name match · 14 closed (not in NetFacilities).
```

When `created` is zero but `auto_closed` is not, the line must still
report the closes rather than falling through to today's flat
`"No new work orders."` -- an import that closed fourteen work orders and
created none is the single most important thing the operator needs to see.

A new red button lives in the same `.filter-row` in
`static/pages/integrations.html`:

```html
<button id="wo-auto-close-undo-btn" type="button" class="btn-danger" hidden>Undo auto-close</button>
```

`.btn-danger` is the outline-red destructive treatment the design system
already reserves for exactly this (`styles.css:724`); brand red stays on
primary actions. The label is rewritten to `Undo auto-close (14)` from the
count. Because CSP drops inline `style` attributes, all state is expressed
through classes and the `hidden` attribute -- no style strings.

Visibility: the button is shown after any import that reports
`auto_closed > 0`, and also on page load from
`GET /work-orders/auto-close/latest`, so it survives a browser refresh
inside the 24-hour window. It hides itself once undo succeeds or the window
lapses.

No confirmation dialog. This button *is* the safety valve; putting friction
in front of it defeats its purpose, and restoring work orders is not itself
destructive.

## Risks accepted

- **A running clock is stopped and does not restart on undo.** Chosen
  knowingly: the user asked for no status exclusions.
- **A work order in Admin Review can be swept mid-review.** Same call.
- **A wrong export closes a lot of work at once.** Bounded by the undo
  button and the empty-CSV guard, not prevented.
- **A restored work order is closed again by the next import.** See the
  Assumption section above.

## Out of scope

- **Notifying supervisors** that their work orders were auto-closed. The
  bulk notification machinery exists (`notify_supervisors_assigned_bulk`),
  but a sweep is an operator-facing event, and this app deliberately keeps
  exactly one batched notification. Revisit only if the operator asks.
- **Durable import history.** The app records nothing about any import
  today -- counts live in one HTTP response and vanish on refresh. That is
  a real gap, and a better feature built deliberately for all imports than
  smuggled in as a side effect of this one. Explicitly rejected as
  Approach B.
- **Surfacing `auto_closed_at` in the CSV export.** No asked-for use.
- **The four other counters the UI still discards** (`opened`, `closed`,
  `skipped`, `supervisors_unmatched`). Separate change.

## Testing

Service-level, against a real session, following `test_work_order_import.py`:

- a live work order absent from the CSV is archived, carries the note, and
  is stamped with the batch id
- a live work order present in the CSV is untouched
- an archived work order present in the CSV stays counted as `closed` and
  is never swept
- a `legacy` live work order absent from the CSV is **not** touched
- a CSV with a valid header and zero data rows sweeps nothing
- a running labor session on a swept work order is stopped
- `auto_closed` matches the number of rows actually archived
- an import that closes nothing writes no batch id anywhere

Undo:

- restores exactly the batch, clearing all three columns
- leaves a work order somebody archived by hand alone
- returns the true count when a row was hand-restored in between
- refuses outside the 24-hour window
- refuses below `ROLE_TECHFM_OA`

Route-level, through a real `TestClient` (not direct handler calls -- the
FastAPI/Pydantic pin in this repo makes direct calls unrepresentative):

- both import routes report `auto_closed` identically
- `/work-orders/auto-close/latest` is not swallowed by `/{work_order_id}`
- undo emits the review-queue envelope before the status envelope
