# Work Orders save-time conflict check (W3): design

Date: 2026-11-15. Status: draft, awaiting owner review. Scope: three save paths on the Work Orders card. Builds on W2 (`2026-11-14-work-order-live-rendering-design.md`, Stage 2).

## Intent

Two people can edit the same value on one work order. Today the later save
silently wins. W2 warns the typist when a live update changes a field they are
editing (rule 12), but a save still replaces the other person's value. W3 makes
the save itself refuse, say who changed what and how long ago, and let the
person keep theirs or save their own in one tap.

## Roadmap (owner-approved 2026-11-15)

| W | Scope |
|---|---|
| W1 | Live list (built) |
| W2 | Live card body (building) |
| **W3** | **Save-time conflict check (this spec)** |
| W4 | Request section inside the card (`workOrderRequests.js`) patched instead of rebuilt |
| W5 | Requests page (`userRequests.js`) |
| W6 | Low Stock and SMR Admin Review |
| W7 | User Hub (tiles, crew/admin, Timesheets tab) |

## Owner decisions (2026-11-15)

| Question | Pick |
|---|---|
| Detection | Per-field expected value (generalises `expected_supervisor_id`); no whole-order version |
| Conflict UI | Theirs/mine choice, naming the field, the other value, who and how long ago |
| Time source | New per-field stamp table, accurate per field |
| Name | Shown; stamp table and line rows record who |
| Protected saves | Edit details form, material quantity and billing, labor minutes |

## Goals

- A save whose field someone else changed since the person saw it is refused with 409.
- The refusal names each field, its current value, who changed it and how long ago.
- One tap keeps theirs; one tap saves the person's own value.
- A save never sends a field the person did not change.

## Non-goals

- Notes (append-only, server-stamped; nothing can be lost).
- Entry mode select, status action buttons, signature, SMR lines and readings, add-material, add-labor.
- Edit locks, presence, live "Maria is typing".
- A whole-order version or `If-Match` header.

## Anti-goals

- Blocking a save because an unrelated field or line changed.
- A conflict check whose stamps depend on every route remembering to write them.
- Throwing away anything the person typed.

## Constraints

| Constraint | Source |
|---|---|
| Old cached clients send no expected values and must keep working | Rolling deploys; `expected_supervisor_id` precedent |
| Additive migration, applied at start-up | `backend/entrypoint.sh` runs `alembic upgrade head` |
| Compare and write under the row lock | `update_work_order` already uses `_get_locked` |
| No inline style or script | CSP `default-src 'self'` |
| Readable on a phone, no legend | Owner design rules |
| Message line keeps across live patches | W2: `#wo-sec-msg` carries `data-live-keep` and `role="status"` |

## Design

### Data

`work_order_field_stamps`: `work_order_id` (FK, cascade), `field` (text), `changed_at` (timestamptz), `changed_by_id` (FK users, set null). Primary key (`work_order_id`, `field`). At most one row per protected field per order.

`work_order_items.updated_by_id` and `work_order_labor.updated_by_id`: nullable FK users, set null. Their existing `updated_at` is the time.

### Rules

1. **Stamps are written in one place.** A SQLAlchemy `before_flush` listener upserts a stamp for each protected `WorkOrder` column whose attribute history changed, for crew changes (`work_order_technicians` rows added or removed → field `assigned_to_ids`), and sets `updated_by_id` on each dirty `WorkOrderItem` / `WorkOrderLabor`. The actor is `session.info["actor_id"]`, set by `get_current_user` (it shares the request's session through `Depends(get_db)`). No actor (scripts) → null. This catches every writer: the 15 field writes in `services/work_orders.py`, History voids in `services/transactions.py`, tracking, import.
2. **Protected details fields** are exactly what `save-details` sends: `status`, `location`, `service_type`, `schedule_date`, `output_to`, `vendor_assignee`, `description`, `priority`, `supervisor_id`, `assigned_to_ids`.
3. **Wire.** `PATCH /work-orders/{id}` accepts `expected: {field: value}`. Item `PATCH` accepts `expected_quantity`; billing `PATCH` accepts `expected_billable_quantity` (presence matters: `null` means "billed in full"); labor `PATCH` accepts `expected_minutes`. Absent means no check (old clients).
4. **Compare** after the same normalisation the update applies (trim, blank → null), crew as a set, numbers as `Decimal`. Any mismatch refuses the whole save; nothing is written.
5. **409 body:** `{"detail": {"code": "field_conflict", "message": "...", "conflicts": [{"field", "label", "current", "current_label", "changed_by", "seconds_ago"}]}}`. `current_label` is the display text (status label, supervisor and crew names). `seconds_ago` is computed by the server from the stamp, so a phone's wrong clock cannot skew it; null when no stamp exists.
6. **Legacy check kept.** `expected_supervisor_id` still works for cached clients. When both are sent, rule 4 runs first.
7. **Send only what changed.** `save-details` sends a field only when it is dirty (W2's `isDirty`; crew compared as a set against the rendered list), with its rendered value in `expected`. Nothing dirty → no request; the editor closes. This also ends today's silent revert of fields the person never touched.
8. **Expected lives on the edited element.** Details: each field's `defaultValue` / `defaultSelected`; crew: `data-original-crew` on the form beside `data-original-supervisor-id`. Quantity: the input's `defaultValue`. Labor: `data-expected-minutes` on the hours input (hours text is rounded; minutes are not). W2 leaves a typed field and an open form untouched, so their snapshot cannot be refreshed underneath the person; a row's own attributes can be, so they are never the source.
9. **Message.** In `#wo-sec-msg`, one sentence per conflict: "Maria Lopez changed Unit to 204 12 seconds ago." Age uses `Intl.RelativeTimeFormat`: seconds under a minute, then minutes, hours, days. No stamp: "Someone else changed Unit to 204." Null actor: "Unit was changed to 204 12 seconds ago." Then two buttons, ids `wo-act-keep-theirs` and `wo-act-save-mine`. The text does not tick.
10. **Keep theirs:** each conflicting field takes `current` as both value and default; its W2 `wo-field-conflict` outline is removed; nothing is sent; the message clears. Other typed fields stay typed.
11. **Save mine:** resend the same save with `expected` set to each conflict's `current`. A third change in between raises a fresh conflict.
12. **Offline replay.** A draft replayed on reconnect that gets a 409 takes the existing `markDraftError` path; the message line shows rule 9's sentence without buttons. The person reopens the editor, where the draft restores, and saves again.
13. **Billing editor.** The shared `billingEditor.js` stays open on a 409; the card's message line carries the choice. History's own billing path is unchanged.

### W2 interaction

W2 rule 12 still outlines a field and warns when a live update changes it mid-typing; W3 is what stops the save. Both use `#wo-sec-msg`; W3's buttons survive patches because the line is kept.

## Practice checks

| Rule | Practice | Source |
|---|---|---|
| Refuse a stale write instead of merging | Conditional requests: the client states what it expects, the server refuses on mismatch | [RFC 9110 §13.1.1](https://www.rfc-editor.org/rfc/rfc9110#section-13.1.1) |
| Per-field instead of whole-resource | A whole-resource version raises conflicts on unrelated edits; field-level checks avoid them | [Fowler, Optimistic Offline Lock](https://martinfowler.com/eaaCatalog/optimisticOfflineLock.html) |
| Send only changed fields | Merge-patch semantics: absent means untouched | [RFC 7396](https://www.rfc-editor.org/rfc/rfc7396) |
| Server computes the age | Device clocks drift; relative time from the server avoids skew | [MDN Date](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Date) |
| Relative time wording | Native `Intl.RelativeTimeFormat` | [MDN](https://developer.mozilla.org/en-US/docs/Web/JavaScript/Reference/Global_Objects/Intl/RelativeTimeFormat) |
| Conflict announced | `role="status"` present before text | [WCAG 4.1.3](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) |

## Risks

| # | Hazard | Handling |
|---|---|---|
| 1 | Snapshot refreshed by a live patch, so a real conflict passes | Rule 8: snapshot on the element W2 leaves untouched; test with a patch between render and save |
| 2 | Unchanged field sent, causing a false conflict or a silent revert | Rule 7; test: someone changes Priority, the person edits Unit, the save succeeds and Priority keeps theirs |
| 3 | A writer bypasses stamping | Rule 1 listener; tests: History void, tracking auto-status, CSV import each leave a stamp |
| 4 | Phone clock wrong | Rule 5 server age |
| 5 | Cached old client | Rule 3 absent = no check; test |
| 6 | Hours rounding raises false labor conflicts | Rule 8 minutes attribute; test with 95 minutes |
| 7 | Check and write race | Row lock (`FOR UPDATE`) on order, item and labor rows |
| 8 | `null` billing confused with absent | Rule 3 presence via `model_fields_set`; test both |
| 9 | Crew order or blank-vs-null raises false conflicts | Rule 4 normalisation; tests |
| 10 | Legacy and new supervisor checks disagree | Rule 6 order; test both sent |
| 11 | Replay conflict lost silently | Rule 12; test |
| 12 | Actor missing (listener sees no user) | Null actor wording; test a script write |
| 13 | Buttons too small on a phone | 44 px minimum targets; owner's phone check |
| 14 | Live patch moves or clears the buttons | `#wo-sec-msg` is kept (W2); test |
| 15 | Migration fails on deploy | Additive table and nullable columns only; downgrade drops them; run against a prod-sized local copy |

## Testing

Backend (`backend/tests`, real `TestClient`): one conflict and one clean save per protected route; normalisation cases (rule 4); legacy and new supervisor checks; listener stamps from each writer named in risk 3; 409 body shape including `seconds_ago` and null-stamp; old-client save without `expected`.

Frontend (Vitest, `importView`): only dirty fields sent; message wording for name/no-name/no-stamp and each age unit; Keep theirs and Save mine; snapshot survives a W2 patch; labor minutes attribute; replay conflict; buttons survive a live patch; census: every Edit details field has a snapshot source.

Owner's phone check with two logins: the conflict message, both buttons, and a save of an untouched field after the other login changed it.

## Left to the builder

- Message wording for multiple conflicts within one sentence budget.
- Where the conflict helper lives (`workOrderLiveBody.js` or a new `workOrderConflict.js`) by line count.
- The `docs/current-state.md` rows.

## Calls made by the author, not the owner

- One choice covers every conflict in a save; no per-field choice.
- A conflict refuses the whole save, including its non-conflicting fields.
- Age wording rolls up past 60 seconds (minutes, hours, days) rather than counting seconds forever.
- The message is a snapshot and does not tick.
- A replayed draft shows the conflict without buttons.
- `expected_supervisor_id` stays for cached clients; removal is a later clean-up.
