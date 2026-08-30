# NetFacilities import reconciliation: auto-close absent work orders

Date: 2026-08-30 (expanded the same day after spec review)
Status: implemented (branch `worktree-netfacilities-reconcile`, migration `b3d5f7a9c1e2`)

## Problem

A work order lives in this app only because a NetFacilities CSV import
created it. Nothing brings it back out. When somebody closes a work order
*in NetFacilities*, the vendor simply stops exporting it -- and this app
keeps showing it as live, forever, on the Work Orders page and in every
supervisor's queue.

The signal is already sitting in the import and being thrown away: a work
order that is live here and **absent from the CSV** has been closed
upstream. This design reads that signal, closes those work orders, writes
a note saying why, reopens them if they ever come back, and gives the
operator one red button to undo the last day's sweeps if an import was
wrong.

## Decisions

Settled with the user before writing, then re-confirmed or revised on spec
review (marked *review*):

1. **The export is exhaustive.** The captured CSV is always the full list
   of open work orders, never a filtered subset. Absence therefore means
   closed upstream. The safety net is the undo button plus reopen-on-
   reappearance, not a scope filter.
2. **Undo covers the whole 24-hour window** (*review*, revised). Every
   sweep-closed work order still archived and closed inside the last 24
   hours is restored by one button, however many imports produced them.
   Two OAs importing in one day, or a manual import after an unattended
   one, must not leave an earlier sweep un-undoable from the UI.
3. **No status exclusions.** The sweep closes every absent live work order
   regardless of status, running clock, or logged materials.
4. **Notes are authored by `TechFM`.** Four texts, listed under Notes.
5. **Storage is two columns on `work_orders`**, not a batch table and not
   a derived-from-note-text scan.
6. **A restored work order is eligible to be auto-closed again by the next
   import** (*review*, confirmed). It is still absent from NetFacilities,
   so re-closing it is the correct read; the operator restores it again if
   they disagree. No exemption flag, permanent or temporary -- that would
   be invisible state, and once auto-capture ships (decision 9) it would
   have to survive imports the operator never sees.
7. **Reappearance reopens a sweep-closed work order** (*review*, new). An
   archived work order whose number is listed in a CSV is left archived
   today. That stays true for a work order a person archived. A work order
   the *sweep* archived is reopened, because its presence upstream is the
   same evidence the sweep itself relies on, read the other way. This is
   what makes a partial or wrong export self-healing after the undo window
   has lapsed.
8. **Restoring a sweep-closed work order writes a note** (*review*, new),
   whether by the undo button or by hand. Restores of hand-archived work
   orders stay silent, as today.
9. **Unattended imports sweep too** (*review*, new). The auto-capture
   chain (`2026-08-29-netfacilities-auto-capture-design.md`, E4/E11) calls
   the same `run_csv_import`, so it gets the sweep with no plumbing. Its
   push and status-line narration must carry the close and reopen counts;
   that spec is amended, not duplicated here.

## Data model

Two nullable columns on `work_orders`:

| Column | Type | Meaning |
| --- | --- | --- |
| `auto_closed_batch_id` | `UUID NULL` | The sweep that closed this row. One id per import that closed at least one work order. Provenance: it groups a sweep's rows for the pending count and lets the daily report mark them; nothing else reads it. |
| `auto_closed_at` | `TIMESTAMPTZ NULL` | When that sweep ran. Equal to the row's `archived_at` at the moment of the sweep. The undo window is measured from this. |

Both are set together by the sweep and cleared together by every path
that un-archives the row: the undo, the reopen, and `restore_work_order`.
A live row never carries either column, which is what keeps a restored
row from looking auto-closed forever and why hand-restored rows fall out
of the pending count for free.

`archived_at` remains the single source of truth for closed/live. Nothing
reads these two columns to decide visibility.

Migration `add_work_order_auto_close_batch`, `down_revision =
"fcbc2524ea62"` (current head). Adds both columns plus a partial index:

```sql
CREATE INDEX ix_work_orders_auto_closed_at
    ON work_orders (auto_closed_at DESC)
    WHERE auto_closed_at IS NOT NULL;
```

Almost every row is `NULL` here, and the only queries are "sweep rows
inside the window" and the daily report's marker.

## Notes

All four are module constants in `services/work_orders.py`, appended with
`wo.append_note_log(..., author_name="TechFM", occurred_at=now)`. `{name}`
is the acting user's `full_name`, the same string the export writes for
technicians.

| Constant | Text | Written by |
| --- | --- | --- |
| `AUTO_CLOSE_NOTE` | `closed automatically: this work order was not in the latest NetFacilities import. Review it in NetFacilities for details.` | the sweep |
| `AUTO_REOPEN_NOTE` | `reopened automatically: this work order is in the latest NetFacilities import again.` | the import row loop |
| `AUTO_CLOSE_UNDO_NOTE` | `restored: auto-close undone by {name}.` | the undo button |
| `AUTO_CLOSE_RESTORE_NOTE` | `restored by {name}.` | `restore_work_order`, only when the row carries a batch id |

A sweep-closed row that comes back therefore always reads as a pair --
closed automatically, then how it came back -- and a row that was never
swept keeps today's silent restore.

## The import

Both changes live in `services.work_orders.import_work_orders`, so both
import entry points (`POST /work-orders/import`,
`POST /integrations/netfacilities/cloud/downloads/import`) and the
auto-capture chain get them without any router growing a second call --
the same argument that put the realtime emits and the supervisor
notification in the shared `run_csv_import`.

### Reopen on reappearance (in the row loop)

Today the loop reads: `existing` archived -> `closed += 1`, skip. It
becomes:

1. `existing` archived and `existing.auto_closed_batch_id IS NULL` -- a
   person archived it: `closed += 1`, skip. Unchanged.
2. `existing` archived and the batch id is set -- the sweep archived it:
   re-lock the row (`_get_locked`, serializing against a concurrent
   sweep), clear `archived_at`, `auto_closed_batch_id`, `auto_closed_at`,
   append `AUTO_REOPEN_NOTE`, `reopened += 1`, and **fall through** to the
   normal live-row path so the CSV's metadata fill-blanks merge applies.
   The row is counted in `reopened`, not also in `opened`; the counters
   stay disjoint and `total` gains `reopened`.

Labor sessions do not come back on reopen, for the same reason they do
not on undo (below). Supervisor routing is untouched: the row keeps
whatever `supervisor_id` it had, exactly as a re-imported live row does,
and the batched supervisor notification still counts *created* rows only.

### The sweep (after the row loop, before the summary is returned)

1. **Collect what the CSV saw.** While parsing rows, accumulate
   `seen: set[str]` of `wo.normalize_number(number)` for every row with a
   non-blank number. Presence in the CSV is what counts, not import
   outcome -- a row that matched a hand-archived work order (`closed`) was
   still present upstream and must not be swept.
2. **Empty-CSV guard.** If `seen` is empty, skip the sweep entirely and
   report `auto_closed = 0`. A CSV with a valid `WORK ORDER` header and
   zero data rows parses cleanly; without this guard it would close every
   live work order in the system. This is a correctness floor, not a
   policy knob.
3. **Select victims.** Live work orders (`archived_at IS NULL`) whose
   `lower(btrim(number))` is not in `seen`, **excluding `legacy IS TRUE`**,
   locked `FOR UPDATE` so a concurrent stop or archive cannot bill a
   session twice (the same reason `archive_work_order` locks).
4. **Close each one**, then one commit for the whole sweep:
   - `_stop_all_sessions(db, row, actor=user)` -- the same call
     `archive_work_order` makes, with the importing user as the actor.
   - `row.notes = wo.append_note_log(row.notes, AUTO_CLOSE_NOTE,
     author_name="TechFM", occurred_at=now)`
   - `row.archived_at = now`, `row.auto_closed_batch_id = batch_id`,
     `row.auto_closed_at = now`
5. Return `auto_closed` and `reopened` in the summary dict alongside the
   existing seven counters.

**Transaction boundary.** The row loop commits per row through
`get_or_create_work_order`, as today. The sweep is one transaction: if it
fails midway, every row the loop imported stays imported and *no* victim
is closed. A half-swept import cannot exist.

`batch_id` is one `uuid4()` generated per import and stamped only if at
least one work order was closed, so an import that closes nothing leaves
no batch behind.

**Concurrency.** Two imports running at once each sweep against the live
set they see; the `archived_at IS NULL` predicate and the row lock mean a
row closed by the first is skipped by the second, so a work order can
only ever wear one batch id.

### Why `legacy` is excluded

Not a preference -- a loop. `legacy` rows predate NetFacilities and can
never appear in any export, so every import would close all of them, and
because undo is time-limited they would churn closed on each run with no
way to make it stop. They are not "absent," they are out of scope. This
mirrors the existing carve-out: legacy work orders already have their own
Owner-only bulk archive (`archive_live_legacy_work_orders`).

## The undo

Module constant `AUTO_CLOSE_UNDO_WINDOW = timedelta(hours=24)`. The
pending predicate, shared by both functions:

```
archived_at IS NOT NULL
AND auto_closed_at IS NOT NULL
AND auto_closed_at >= now - AUTO_CLOSE_UNDO_WINDOW
```

`pending_auto_close(db, *, user, now) -> dict | None` -- over that set:
`closed_count`, `batch_count` (distinct batch ids), `newest_ran_at`,
`oldest_ran_at`. Returns `None` when the count is zero.

`undo_auto_close(db, *, user, now) -> int` -- restores every row in that
set: clears `archived_at`, `auto_closed_batch_id`, `auto_closed_at`,
appends `AUTO_CLOSE_UNDO_NOTE` naming the operator. Row by row inside one
transaction rather than a bulk `UPDATE`, because each row gets its own
note line; one commit keeps it atomic. Returns the count actually
restored, which may be lower than the button's label if somebody restored
rows by hand, or a later import reopened some, in between -- the same
honesty `archive_live_legacy_work_orders` already practises about its own
preview. **Nothing pending is not an error:** the call returns `0` and the
route answers `200 {"restored": 0}`. That also covers "outside the
window" -- a window that has lapsed simply has nothing pending -- so no
special status is needed.

Both gated at `ROLE_TECHFM_OA` -- the role that can import and the role
that can archive. Deliberately *not* `ROLE_SUPERVISOR`, which is the gate
on single-work-order restore: a bulk undo is an import-operator action.
The set is company-wide, not per operator: any OA can undo another OA's
sweep, which is the point of decision 2.

**Labor sessions do not come back.** A session stopped by the sweep stays
stopped after restore, exactly as it does for a manual archive-then-restore
today. The undo returns the work order, not the running clock.

### `restore_work_order` is amended

Before clearing `archived_at`, if the row carries `auto_closed_batch_id`:
append `AUTO_CLOSE_RESTORE_NOTE` naming the restoring user and clear both
columns. A hand-archived row (no batch id) restores silently, as today.
Route and gate unchanged (`POST /work-orders/{id}/restore`, Supervisor+).

## API

Two routes on the work-orders router, declared **before** `/{work_order_id}`
so the path segments are not parsed as an id -- the same ordering constraint
`/filter-options`, `/export`, `/lookup`, and `/legacy/archive` already live
under. Both carry `responses=_forbidden(roles.ROLE_TECHFM_OA)` so the 403 is
documented (`test_every_gated_work_order_route_documents_its_403` gains
both endpoint names).

```
GET  /work-orders/auto-close/pending -> WorkOrderAutoClosePending | null
POST /work-orders/auto-close/undo    -> WorkOrderAutoCloseUndoResult
```

```python
class WorkOrderAutoClosePending(BaseModel):
    closed_count: int
    batch_count: int
    newest_ran_at: datetime
    oldest_ran_at: datetime


class WorkOrderAutoCloseUndoResult(BaseModel):
    restored: int
```

`WorkOrderImportResult` gains two fields:

```python
auto_closed: int   # live work orders closed because the CSV did not list them
reopened: int      # sweep-closed work orders reopened because the CSV listed them again
```

`total` includes `reopened`. The routing map the router pops is unchanged.

The undo route emits `_emit_review_queue_changed(None)` then
`_emit_status_changed(None)`, in that order, matching every other
collection-level command. The sweep and the reopen need no emits of their
own: they run inside the import, whose emits already fire afterwards.

## Reporting

### Summary line

`importSummary(r)` in `static/views/workOrders.js` becomes a list of
clauses joined by ` · `, ending with a period; each clause appears only
when its count is non-zero, and the created clause keeps its supervisor
match as today:

```
3 new work orders · 2 with a supervisor name match · 14 closed (not in NetFacilities) · 1 reopened (back in NetFacilities).
```

When every clause is empty the line reads `No new work orders.` as today.
An import that created nothing but closed fourteen is the single most
important thing the operator needs to see, and must never fall through to
that flat sentence.

The same function renders the auto-capture chain's "imported" narration
step, so the on-page story matches whether the import was clicked or
captured.

### The red button

In the same `.filter-row` in `static/pages/integrations.html`:

```html
<button id="wo-auto-close-undo-btn" type="button" class="btn-danger" hidden>Undo auto-close</button>
```

`.btn-danger` is the outline-red destructive treatment the design system
already reserves for exactly this (`styles.css:724`); brand red stays on
primary actions. The label is rewritten to `Undo auto-close (17)` from
`closed_count`. Because CSP drops inline `style` attributes, all state is
expressed through classes and the `hidden` attribute.

`refreshAutoClosePending()` calls `GET /work-orders/auto-close/pending` and
shows or hides the button from the result. It runs:

- on Integrations page entry, in the same hook that refreshes the
  NetFacilities cloud session status -- so the button survives a browser
  refresh inside the window;
- after **every** import summary, whatever its counts -- an import that
  reopened rows lowers the pending count, and one that closed rows raises
  it;
- after an undo.

Clicking it posts the undo, shows `17 work orders restored.` in the import
message slot (`0 work orders restored.` if the window emptied first), then
reloads the list and refreshes the pending state, which hides the button.

No confirmation dialog. This button *is* the safety valve; putting friction
in front of it defeats its purpose, and restoring work orders is not itself
destructive.

### Unattended imports

An auto-captured import has nobody looking at the summary line. Per
decision 9, the auto-capture spec's E10 push and its snapshot narration
carry `auto_closed` and `reopened`; the amendment is recorded in that
spec (§2a). The Integrations-page button still appears on the operator's
next visit inside the window.

## Interaction with other work

- **Daily report** (`2026-08-30-work-order-daily-report-design.md`): its
  Closed sections mark rows where `auto_closed_batch_id IS NOT NULL` as
  "Closed in NetFacilities". If the report ships first, that marker is a
  constant `false` until this migration lands; its contract does not
  change.
- **Auto-capture** (`2026-08-29-netfacilities-auto-capture-design.md`):
  amended §2a. Nothing here waits on it.

## Risks accepted

- **A running clock is stopped and does not restart on undo or reopen.**
  Chosen knowingly: the user asked for no status exclusions.
- **A work order in Admin Review can be swept mid-review.** Same call.
- **A wrong export closes a lot of work at once.** Bounded by the undo
  button, the empty-CSV guard, and reopen-on-reappearance -- not
  prevented.
- **A restored work order is closed again by the next import** if it is
  still absent upstream. Decision 6. With unattended imports this can be
  within the hour; the remedy is to close or reopen it in NetFacilities,
  which is where the truth lives.

## Out of scope

- **Notifying supervisors** that their work orders were auto-closed or
  reopened. The bulk notification machinery exists
  (`notify_supervisors_assigned_bulk`), but a sweep is an operator-facing
  event, and this app deliberately keeps exactly one batched notification.
- **Durable import history.** The app records nothing about any import
  today. That is a real gap, and a better feature built deliberately for
  all imports than smuggled in as a side effect of this one.
- **Per-batch undo.** Decision 2 makes the window the unit. The batch id
  stays as provenance so a per-batch surface can be added without a
  migration if one is ever wanted.
- **Surfacing the two columns in the CSV export.** No asked-for use.
- **The four other counters the UI still discards** (`opened`, `closed`,
  `skipped`, `supervisors_unmatched`). Separate change.

## Testing

Service-level, against a real session, following `test_work_order_import.py`:

Sweep:

- a live work order absent from the CSV is archived, carries
  `AUTO_CLOSE_NOTE`, and is stamped with the batch id and `auto_closed_at`
- a live work order present in the CSV is untouched
- a hand-archived work order present in the CSV stays counted as `closed`
  and is neither swept nor reopened
- a `legacy` live work order absent from the CSV is **not** touched
- a CSV with a valid header and zero data rows sweeps nothing
- a running labor session on a swept work order is stopped
- `auto_closed` matches the number of rows actually archived
- an import that closes nothing writes no batch id anywhere
- two work orders swept by one import share a batch id; a later sweep
  gets a different one

Reopen:

- a sweep-closed work order listed in the next CSV is un-archived, has
  both columns cleared, carries `AUTO_REOPEN_NOTE`, and receives the CSV's
  fill-blanks metadata
- it is counted in `reopened`, not `opened`; `total` includes it
- a stopped session on it stays stopped

Undo and restore:

- restores every sweep row inside the window across two batches,
  clearing all three columns and appending `AUTO_CLOSE_UNDO_NOTE`
- leaves a work order somebody archived by hand alone
- leaves a sweep row older than the window alone
- returns the true count when a row was hand-restored in between
- returns `0` with nothing pending
- refuses below `ROLE_TECHFM_OA`
- `restore_work_order` on a sweep-closed row clears both columns and
  appends `AUTO_CLOSE_RESTORE_NOTE`; on a hand-archived row it writes no
  note
- `pending_auto_close` reports `batch_count = 2` for two sweeps in the
  window and `None` once the last row is restored

Route-level, through a real `TestClient` (not direct handler calls -- the
FastAPI/Pydantic pin in this repo makes direct calls unrepresentative):

- both import routes report `auto_closed` and `reopened` identically
- `/work-orders/auto-close/pending` and `/undo` are not swallowed by
  `/{work_order_id}`
- undo with nothing pending answers `200 {"restored": 0}`
- undo emits the review-queue envelope before the status envelope

## Build order

1. Migration, the two columns, the four note constants.
2. Reopen in the row loop + sweep + summary fields, with their tests.
3. `pending_auto_close`, `undo_auto_close`, the `restore_work_order`
   amendment, the two routes, role-gate and 403-documentation tests.
4. Summary line, the button, `refreshAutoClosePending()`.
5. Docs: `endpoint-map.md`, `current-state.md`; the auto-capture spec's
   §2a is already written.
