# Work Orders Save-Time Conflict Check (W3) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** A save on Edit details, material quantity, material billing or labor hours that would overwrite someone else's newer value is refused with 409, names who changed what and when, and offers Keep theirs / Save mine.

**Architecture:** One SQLAlchemy flush listener stamps who changed each protected field (a stamp table for work-order fields, `updated_by_id` on item and labor rows). Each protected PATCH takes the values the client last saw and compares them under the row lock. The client sends only dirty fields, reads its expected values from the edited element, and shows the 409 in the kept `#wo-sec-msg` line through one helper.

**Tech Stack:** FastAPI, SQLAlchemy 2, Alembic, Pydantic 2, pytest (real `TestClient`); plain ES modules, Vitest + jsdom.

**Spec:** `docs/superpowers/specs/2026-11-15-work-order-save-conflict-check-design.md` (owner-approved 2026-11-15, all six author's calls accepted). Rule numbers below are the spec's.

## Global Constraints

- Absent `expected*` = no check. Cached old clients keep working (rule 3).
- `expected_supervisor_id` keeps working; when both are sent, the new check runs first (rule 6).
- Migration is additive: one table, two nullable columns, `ondelete="SET NULL"` on user FKs, cascade on `work_order_id`. Downgrade drops them. Down revision `a3c5e7b9d1f4`.
- CSP `default-src 'self'`: build the conflict message with DOM nodes and classes, no inline style or script.
- Buttons at least 44 px tall (`.wo-conflict-actions button` rule in `styles.css`).
- `workOrderActions.js` (624 lines) may grow but stays under 1,000; conflict logic lives in new `backend/static/views/workOrderConflict.js`.
- `services/work_orders.py` is 3,290 lines: compare/409 logic lives in new `backend/app/services/work_order_conflicts.py`.
- No push. One push after W1–W4 are built and the owner's local phone check passes.
- Shared checkout: stage explicit paths only. No `Co-Authored-By` trailer. Targeted tests only. Vitest from PowerShell at `C:\Users\mcclu\Desktop\inventory_app_git`; pytest from `backend\` with the main checkout's venv.
- An existing test that fails is a finding. Change it only when it asserts the retired "send every field" behaviour; name each in the commit body.

## Risk register

Spec risks 1–15 plus four found while reading the code (16–19).

| # | Hazard | Closed by |
|---|---|---|
| 1 | Snapshot refreshed by a live patch | T5/T6 expected read from defaults and `data-original-*`; test with a patch between render and save |
| 2 | Unchanged field sent | T5 dirty-only; test |
| 3 | A writer bypasses stamping | T1 listener; History void, tracking auto-hold, CSV import tests |
| 4 | Phone clock wrong | T2 server `seconds_ago` |
| 5 | Cached old client | T2/T3 absent-means-no-check tests |
| 6 | Hours rounding | T6 `data-expected-minutes`; 95-minute test |
| 7 | Check/write race | T2 order row already locked; T3 adds `FOR UPDATE` to line and labor lookups |
| 8 | `null` billing vs absent | T3 `model_fields_set`; both tested |
| 9 | Crew order, blank vs null | T2 normaliser tests |
| 10 | Legacy and new supervisor checks | T2 both-sent test |
| 11 | Replay conflict lost | T6 replay test |
| 12 | No actor | T1 null actor; T4 wording |
| 13 | Small buttons | Global constraint; phone |
| 14 | Patch clears buttons | T4 test (line is `data-live-keep`) |
| 15 | Migration fails on deploy | T7 upgrade/downgrade/upgrade on the local prod copy |
| 16 | `<input type="text">` strips line breaks, textarea turns CRLF into LF: multi-line imported Location raises a false conflict | T2 compare ignores `\r` and `\n` |
| 17 | Ready to Complete has no status option, so the select's default is the first option: a false conflict | T5 `data-original-status` |
| 18 | Double tap on Save mine: second request conflicts with your own first write | T4 buttons disabled on first tap |
| 19 | `FOR UPDATE` with the labor `joinedload` (outer join) errors in Postgres | T3 `with_for_update(of=WorkOrderLabor)` |

## Review Focus

1. Imported multi-line Location, person edits only Priority → saves clean (risk 16). Test in T2.
2. Order in Ready to Complete, person changes status → no false conflict (risk 17). Test in T5.
3. Double tap Save mine → one request (risk 18). Test in T4.
4. Quantity rendered `"2.50"`, server holds `2.5` → no conflict. Test in T3.
5. Two dirty fields, one conflicting; Keep theirs → conflicting field shows theirs, the other keeps the typed value and stays dirty. Test in T5.

---

### Task 1: Stamp table, `updated_by_id`, the flush listener

**Files:**
- Create: `backend/alembic/versions/b7d9f1a3c5e7_work_order_field_stamps.py`, `backend/app/field_stamps.py`
- Modify: `backend/app/models.py` (new model after `WorkOrderTechnician`; `updated_by_id` on `WorkOrderLabor`, `WorkOrderItem`; bottom-of-file import of `app.field_stamps`), `backend/app/auth_deps.py` (`get_current_user`)
- Test: `backend/tests/test_work_order_field_stamps.py`

**Interfaces:**
- Produces: `models.WorkOrderFieldStamp(work_order_id, field, changed_at, changed_by_id)`, PK (`work_order_id`, `field`); `WorkOrderItem.updated_by_id`, `WorkOrderLabor.updated_by_id`; `field_stamps.STAMPED_COLUMNS = ("status", "location", "service_type", "schedule_date", "output_to", "vendor_assignee", "description", "priority", "supervisor_id")`; crew stamp field name `"assigned_to_ids"`; actor key `session.info["actor_id"]`.

- [ ] **Step 1: Write failing tests** (service calls on the `db` fixture; set `db.info["actor_id"]` directly except where HTTP is named)
  - `test_changing_priority_stamps_it_with_the_actor`: stamp row `field="priority"`, `changed_by_id == actor.id`, `changed_at` within 5 s of now.
  - `test_resaving_an_unchanged_value_writes_no_stamp`: `update_work_order(fields={"priority": <same>})` → no row.
  - `test_crew_change_stamps_assigned_to_ids`.
  - `test_a_new_work_order_gets_no_stamps` (import creates rows; no stamps for them).
  - `test_csv_import_update_stamps_changed_fields` (re-import changing `location` of an existing order via `import_work_orders`).
  - `test_auto_hold_on_last_stop_stamps_status` (`stop_labor_session` on the only running session).
  - `test_history_void_sets_line_updated_by` (`services.transactions` void of a dispense → `line.updated_by_id == actor.id`).
  - `test_labor_edit_sets_updated_by`.
  - `test_no_actor_stamps_with_null` (`db.info.pop("actor_id", None)`).
  - `test_http_patch_records_the_signed_in_user` (real `TestClient`, `_http` helper pattern from `test_work_orders_router.py`).

- [ ] **Step 2:** Run `python -m pytest tests/test_work_order_field_stamps.py -q`. Expected: FAIL (no model).

- [ ] **Step 3: Implement**
  - Migration: create `work_order_field_stamps`; add the two columns with named FKs (precedent: `a3c5e7b9d1f4`).
  - `field_stamps.py`: `@event.listens_for(Session, "before_flush")` on `sqlalchemy.orm.Session` (covers `SessionLocal` and the test fixture's `Session`). It reads `actor = session.info.get("actor_id")`; for each persistent dirty `WorkOrder` collects `(id, column)` where `inspect(obj).attrs[column].history.has_changes()`; for each `WorkOrderTechnician` in `session.new`/`session.deleted` whose order is not in `session.new`, collects `(work_order_id, "assigned_to_ids")`; sets `updated_by_id = actor` on each `WorkOrderItem`/`WorkOrderLabor` where `session.is_modified(obj)`. Pending pairs go in `session.info["stamp_pending"]`.
  - An `after_flush` listener upserts them via `session.connection().execute(postgresql.insert(...).on_conflict_do_update(...))` with `changed_at = datetime.now(timezone.utc)`, then clears the list. After-flush, so the order row exists and no unit-of-work ordering is involved.
  - `get_current_user`: `db.info["actor_id"] = user.id` after `bind_user`.
  - `models.py` last line: `from app import field_stamps  # noqa: E402,F401  registers the stamp listener`.

- [ ] **Step 4:** Rerun Step 2 plus `tests/test_work_orders_service.py tests/test_work_order_import.py tests/test_work_order_line_sync.py`. Expected: PASS.

- [ ] **Step 5:** Commit `feat(work-orders): stamp who changed each protected field (W3 T1)`.

### Task 2: Edit details conflict check (backend)

**Files:**
- Create: `backend/app/services/work_order_conflicts.py`
- Modify: `backend/app/schemas/work_orders.py` (`WorkOrderExpected`, `WorkOrderUpdate.expected`), `backend/app/domain/errors.py` (`WorkOrderFieldConflictError`), `backend/app/routers/_errors.py` (409 + body), `backend/app/services/work_orders.py` (`update_work_order`), `backend/app/routers/work_orders.py` (pass `expected`), `backend/app/domain/work_orders.py` (`STATUS_LABELS`, moved from `services/hub._STATUS_LABELS`, hub imports it)
- Test: `backend/tests/test_work_order_conflicts.py`

**Interfaces:**
- Consumes: T1 stamps.
- Produces:
  - `WorkOrderExpected(BaseModel, extra="forbid")` with the ten fields of rule 2, all optional, same `_trim` validators; presence via `model_fields_set`.
  - `WorkOrderFieldConflictError(conflicts: list[dict])`; `.body = {"code": "field_conflict", "message": "Someone else changed this work order.", "conflicts": conflicts}`. `to_http` uses `getattr(exc, "body", None)` as `detail` when present.
  - Conflict dict: `{"field", "label", "current", "current_label", "changed_by", "seconds_ago"}`.
  - `work_order_conflicts.check_details(db, work_order, expected: dict) -> None` (raises).
  - `work_order_conflicts.conflict(db, *, field, label, current, current_label, changed_by_id, changed_at) -> dict` (shared with T3).
  - `update_work_order(..., expected: dict | None = None)`.

- [ ] **Step 1: Write failing tests** (real `TestClient`, two users)
  - `test_stale_priority_is_refused_with_who_and_when`: A sets Priority "P2"; B patches `{"priority": "P3", "expected": {"priority": "P1"}}` → 409; `detail.code == "field_conflict"`; conflict `{"field": "priority", "label": "Priority", "current": "P2", "current_label": "P2", "changed_by": A.full_name}`, `0 <= seconds_ago < 5`; order still "P2".
  - `test_clean_save_with_matching_expected_succeeds`.
  - `test_no_expected_means_no_check` (old client).
  - `test_conflict_refuses_the_whole_save` (stale priority + fresh location → neither written).
  - `test_blank_and_null_compare_equal`; `test_expected_text_is_trimmed`.
  - `test_multiline_location_compares_without_line_breaks`: stored `"Bldg 4\r\nUnit 2"`, expected `"Bldg 4Unit 2"` → 200 (Review Focus 1).
  - `test_crew_compares_as_a_set` (reversed order → 200); `test_crew_conflict_labels_names` (`current` = id list, `current_label` = names joined `", "` in list order).
  - `test_status_conflict_uses_the_status_label` (`current_label == "In-Progress"` or whatever `STATUS_LABELS` holds).
  - `test_supervisor_conflict_labels_the_name`; null current → `current_label == "(blank)"`; same for any null text.
  - `test_no_stamp_gives_null_seconds_and_name` (field changed by a raw SQL update, no stamp).
  - `test_new_check_runs_before_legacy_supervisor_check`: both sent, both stale → body is `field_conflict`.
  - `test_legacy_expected_supervisor_still_409s` (unchanged string detail).
  - `test_unknown_expected_key_is_422`.

- [ ] **Step 2:** Run `python -m pytest tests/test_work_order_conflicts.py -q`. Expected: FAIL.

- [ ] **Step 3: Implement**
  - Comparison normaliser for text: `(v or "").replace("\r", "").replace("\n", "").strip() or None` on both sides (risk 16; `ponytail:` comment — a change only in line breaks is not detected). Crew: `set()` against `_assigned_technician_ids(work_order)`. Status and supervisor: equality.
  - Labels: Status, Location, Service type, Schedule date, Output to, Vendor contact, Symptom / task, Priority, Team Lead, Assigned technicians (the editor's own captions).
  - `seconds_ago = int((now - stamp.changed_at).total_seconds())`, floored at 0; `changed_by` = stamp user's `full_name`, null when either is missing.
  - Call `check_details` in `update_work_order` right after the archived check, before the legacy supervisor block.
  - `_at_least_one` also ignores `expected`.

- [ ] **Step 4:** Rerun Step 2 plus `tests/test_work_orders_router.py tests/test_route_role_gates.py tests/test_work_orders_service.py tests/test_hub*.py`. Expected: PASS.

- [ ] **Step 5:** Commit `feat(work-orders): refuse a stale Edit details save with 409 field_conflict (W3 T2)`.

### Task 3: Quantity, billing and labor checks (backend)

**Files:**
- Modify: `backend/app/schemas/work_orders.py` (`expected_quantity: Optional[Decimal]` on `WorkOrderItemUpdate`, `expected_billable_quantity: Optional[Decimal]` on `WorkOrderItemBilling`, `expected_minutes: Optional[int]` on `WorkOrderLaborUpdate`), `backend/app/services/work_orders.py` (`_get_line` and `_get_labor_entry` lock; the three update functions), `backend/app/routers/work_orders.py` (three handlers), `backend/app/services/work_order_conflicts.py` (`check_row`)
- Test: `backend/tests/test_work_order_conflicts.py`

**Interfaces:**
- Consumes: T2 `conflict(...)`, `WorkOrderFieldConflictError`.
- Produces: `check_row(db, row, *, field, label, expected, current, current_label) -> None` using `row.updated_by_id` / `row.updated_at`; service kwargs `expected_quantity`, `expected_billable_quantity`, `expected_minutes`, each defaulting to `_UNSET` (absent = no check).

- [ ] **Step 1: Write failing tests**
  - `test_stale_quantity_is_refused` (`field "quantity"`, label `"Quantity"`, `current_label "3"`); stock unchanged.
  - `test_quantity_trailing_zeros_compare_equal` (`expected_quantity "2.50"` vs 2.5 → 200; Review Focus 4).
  - `test_stale_billing_is_refused` and `test_billing_null_expected_means_billed_in_full`: expected `null` when the line is billed in full → 200; expected `null` when it now bills 1 → 409, `current_label "1"`; current null → `current_label "all 3"`.
  - `test_billing_without_expected_key_is_not_checked`.
  - `test_stale_minutes_are_refused`: 95 minutes, other user changes to 120, `expected_minutes 95` → 409, label `"Hours"`, `current_label "2 h"`; 95 → `"1.58 h"`, 90 → `"1.5 h"`.
  - `test_matching_minutes_save` (95 → 200; risk 6).
  - `test_row_conflict_names_the_last_editor`.

- [ ] **Step 2:** Run `python -m pytest tests/test_work_order_conflicts.py -q`. Expected: new tests FAIL.

- [ ] **Step 3: Implement**
  - `_get_line`: `.with_for_update()`. `_get_labor_entry`: `.with_for_update(of=WorkOrderLabor)` (risk 19).
  - Run each check after the line/entry lookup and before any write. Routers pass a kwarg only when the key is in `payload.model_fields_set`.
  - Number labels: `format(d.normalize(), "f")`; hours `f"{m / 60:.2f}".rstrip("0").rstrip(".") + " h"`.

- [ ] **Step 4:** Rerun Step 2 plus `tests/test_work_order_billing.py tests/test_work_order_line_sync.py tests/test_work_order_skilled_labor.py tests/test_realtime_emit.py`. Expected: PASS.

- [ ] **Step 5:** Commit `feat(work-orders): conflict check on material quantity, billing and labor hours (W3 T3)`.

### Task 4: The conflict message and its two buttons (frontend)

**Files:**
- Create: `backend/static/views/workOrderConflict.js`, `tests/frontend/views/workOrders/conflict.test.js`
- Modify: `backend/static/menus.js` (export `setComboValue`; the pick branch calls it), `backend/static/views/workOrderActions.js` (two action branches), `backend/static/styles.css`, `tests/frontend/views/workOrders/actionCoverage.test.js` (`ACTIONS` gains both)

**Interfaces:**
- Produces:
  - `isFieldConflict(err) -> boolean` (`err?.status === 409 && err.detail?.code === "field_conflict"`).
  - `conflictAge(seconds) -> string` via `new Intl.RelativeTimeFormat("en", { numeric: "always" })`: under 60 seconds, under 3,600 minutes, under 86,400 hours, else days; floors.
  - `conflictSentence(c) -> string` (rule 9): `"${changed_by} changed ${label} to ${current_label} ${age}."`; null `seconds_ago` → `"Someone else changed ${label} to ${current_label}."`; null `changed_by` → `"${label} was changed to ${current_label} ${age}."`.
  - `showConflict(cardEl, conflicts, { keep, retry } = {})`: fills `#wo-sec-msg` (class `error`) with one sentence per conflict joined by a space, then, when `keep`/`retry` are given, a `.wo-conflict-actions` div with `<button id="wo-act-keep-theirs" data-action="keep-theirs-wo">Keep theirs</button>` and `<button id="wo-act-save-mine" data-action="save-mine-wo">Save mine</button>`. Stores `{ conflicts, keep, retry }` in a module `WeakMap` keyed by `cardEl`.
  - `resolveConflict(cardEl, choice: "keep" | "mine") -> Promise<void>`: disables both buttons first (risk 18), clears the message, calls `keep(conflicts)` or `await retry(conflicts)`.
  - `setComboValue(menu, value)` in `menus.js`: sets the native select, trigger label and `aria-selected`; no `change` event.

- [ ] **Step 1: Write failing tests** (`importView` inside each test)
  - `conflictSentence` for name/no-name/no-stamp; `conflictAge` 1 → `"1 second ago"`, 59 → `"59 seconds ago"`, 60 → `"1 minute ago"`, 7,200 → `"2 hours ago"`, 172,800 → `"2 days ago"`.
  - Two conflicts → two sentences in one line, then both buttons with the ids above.
  - `test_keep_theirs_calls_keep_and_sends_nothing` (no fetch).
  - `test_save_mine_calls_retry_once_on_double_tap` (Review Focus 3).
  - `test_buttons_survive_a_live_patch` (render conflict, run a socket refresh through `patchBodyLive`, buttons still connected).
  - `test_no_buttons_without_handlers` (replay wording, rule 12).

- [ ] **Step 2:** Run `npx vitest run tests/frontend/views/workOrders/conflict.test.js`. Expected: FAIL.

- [ ] **Step 3: Implement** the module; in `workOrderActions.js` add `keep-theirs-wo` → `resolveConflict(cardEl, "keep")` and `save-mine-wo` → `await resolveConflict(cardEl, "mine")` inside the shared `try` (a fresh 409 from `retry` is shown by the save path itself). These branches must run before the generic `setMessage(msg, "", "")` at the top of the card section, or that clear wipes the message before `resolveConflict` reads it; place them right after `cardEl` is found. CSS: `.wo-conflict-actions { display: flex; gap: .5rem; flex-wrap: wrap; margin-top: .5rem }`, buttons `min-height: 44px`.

- [ ] **Step 4:** Run `npx vitest run tests/frontend/views/workOrders tests/frontend/unit/staticImports.test.js`. Expected: PASS.

- [ ] **Step 5:** Commit `feat(work-orders): conflict message with Keep theirs / Save mine (W3 T4)`.

### Task 5: Edit details sends only what changed, with expected values

**Files:**
- Modify: `backend/static/views/workOrderCardHtml.js` (`.wo-edit` gains `data-original-status` and `data-original-crew`), `backend/static/views/workOrderActions.js` (`save-details` branch), `backend/static/views/workOrderConflict.js` (`detailsPatch`, `keepDetails`)
- Test: `tests/frontend/views/workOrders/conflict.test.js`, `tests/frontend/views/workOrders/editorActions.test.js`, `tests/frontend/views/workOrders/bodyLiveCensus.test.js`

**Interfaces:**
- Consumes: T4 `showConflict`, `isFieldConflict`, `setComboValue`; W2 `isDirty`.
- Produces: `detailsPatch(bodyEl) -> object | null`: `null` when nothing is dirty; otherwise `{ <dirty fields>, expected: { <same keys>: <rendered value> } }`. `keepDetails(bodyEl, conflicts)`.

Field table (rule 2, rules 7–8):

| Field | Element | Dirty when | Expected |
|---|---|---|---|
| text fields (location, service_type, schedule_date, output_to, vendor_assignee, priority) | `.wo-edit-<x>` input | `isDirty` | `defaultValue.trim() \|\| null` |
| description | `.wo-edit-description` | `isDirty` | same |
| status | `.wo-edit-status` | `value !== data-original-status` | `data-original-status` |
| supervisor_id | `.wo-edit-supervisor` | `value !== data-original-supervisor-id` | that attribute `\|\| null` |
| assigned_to_ids | `.wo-tech-selected-row` ids | set differs from `data-original-crew` | `data-original-crew` split on `,` (empty → `[]`) |

- [ ] **Step 1: Write failing tests**
  - `test_only_the_edited_field_is_sent`: edit Location only → body `{location, expected: {location}}`, no `expected_supervisor_id`.
  - `test_nothing_dirty_sends_nothing_and_closes_the_editor`.
  - `test_ready_to_complete_status_has_its_own_expected` (Review Focus 2).
  - `test_crew_reorder_is_not_dirty`.
  - `test_expected_survives_a_live_patch` (open editor, socket patch changes Priority, save Location → expected Location is the rendered one; risk 1).
  - `test_409_shows_sentence_and_buttons`.
  - `test_keep_theirs_takes_current_and_keeps_other_typing` (Review Focus 5): conflict on priority, typed location → priority input value and `defaultValue` = current, no `wo-field-conflict`, location still typed and dirty.
  - `test_keep_theirs_on_status_and_crew` (combo label and `data-original-*` updated; crew list rebuilt from `getAllTechnicians()`).
  - `test_save_mine_resends_with_current_as_expected`; `test_second_conflict_shows_again` (rule 11).
  - Census in `bodyLiveCensus.test.js`: every field the editor renders for an Admin maps to a row of the table above.

- [ ] **Step 2:** Run `npx vitest run tests/frontend/views/workOrders/conflict.test.js tests/frontend/views/workOrders/editorActions.test.js`. Expected: FAIL.

- [ ] **Step 3: Implement.** `save-details`: `patch = detailsPatch(body)`; null → `refreshCard(cardEl)`, return. `send = (over) => { const p = over ? { ...patch, expected: { ...patch.expected, ...over } } : patch; saveDraft(...p); return apiUpdateWorkOrder(id, p); }`. On `isFieldConflict`: `showConflict(cardEl, err.detail.conflicts, { keep: (c) => keepDetails(body, c), retry: (c) => send(Object.fromEntries(c.map((x) => [x.field, x.current]))).then(() => { clearDraft(...); return refreshCard(cardEl); }) })`. Success path unchanged.

- [ ] **Step 4:** Run `npx vitest run tests/frontend/views/workOrders tests/frontend/unit/staticImports.test.js`. Expected: PASS; any changed old test named in the commit body.

- [ ] **Step 5:** Commit `feat(work-orders): Edit details sends only changed fields with expected values (W3 T5)`.

### Task 6: Quantity, billing, labor and replay (frontend)

**Files:**
- Modify: `backend/static/api.js` (three wrappers), `backend/static/views/workOrderCardHtml.js` (labor hours input `data-expected-minutes="${entry.minutes}"`), `backend/static/views/workOrderPresenters.js` (`lineChargeHtml` adds `data-billable-quantity`, `""` for null), `backend/static/views/billingEditor.js` (skip its own message when `err?.handled`), `backend/static/views/workOrderActions.js` (`edit-item`, `edit-labor`, billing `onSave`), `backend/static/views/workOrderRetry.js` (409 conflict)
- Test: `tests/frontend/views/workOrders/conflict.test.js`, `tests/frontend/views/workOrders/offlineRecovery.test.js`

**Interfaces:**
- Consumes: T4 helpers, T3 wire fields.
- Produces: `apiUpdateWorkOrderItem(woId, itemId, { quantity, expectedQuantity })` (sends `expected_quantity` only when defined); `apiSetWorkOrderItemBilling(woId, itemId, value, opts)` (sends `expected_billable_quantity` only when `"expected" in opts`, `null` allowed); `apiUpdateWorkOrderLabor(woId, laborId, { minutes, expectedMinutes })`.

- [ ] **Step 1: Write failing tests**
  - `edit-item` sends `expectedQuantity` = the input's `defaultValue`; Keep theirs sets value and `defaultValue` to `current`.
  - `edit-labor` with 95 minutes sends `expected_minutes: 95` (risk 6); Keep theirs sets the hours text and `data-expected-minutes`.
  - Billing: editor opened on a full-billed line sends `expected_billable_quantity: null`; on 409 the editor stays open, its own message stays empty, the card line shows the conflict; Save mine resends with `current`.
  - Replay (`offlineRecovery.test.js`): a drafted `save-details` replays into a 409 → draft marked with `lastError`, `#wo-sec-msg` shows the sentence, no buttons (rule 12).

- [ ] **Step 2:** Run `npx vitest run tests/frontend/views/workOrders/conflict.test.js tests/frontend/views/workOrders/offlineRecovery.test.js`. Expected: FAIL.

- [ ] **Step 3: Implement.** Same `send`/`showConflict` shape as T5 for each path. Billing captures `expected` from `data-billable-quantity` when the editor opens (W2 holds the row while the editor is open); on conflict `onSave` calls `showConflict` and throws `{ handled: true }`; Keep theirs sets the editor input to `current ?? ""` and the captured expected to `current`. Replay: `isFieldConflict(err)` → `showConflict(cardEl, err.detail.conflicts)` instead of `friendlyError`.

- [ ] **Step 4:** Run `npx vitest run tests/frontend/views/workOrders tests/frontend/unit/staticImports.test.js`. Expected: PASS.

- [ ] **Step 5:** Commit `feat(work-orders): conflict check on quantity, billing, labor and replay (W3 T6)`.

### Task 7: Migration rehearsal and docs

**Files:**
- Modify: `docs/current-state.md` (Work Orders row in the Task Routing Map: add `services/work_order_conflicts.py`, `field_stamps.py`, `workOrderConflict.js`, the two new test files; one Hard Invariants line: "Protected work-order saves carry expected values; the flush listener in `app/field_stamps.py` is the only stamp writer"), `docs/endpoint-map.md` (the four PATCH bodies gain `expected*`; 409 `field_conflict` shape)

- [ ] **Step 1:** Against the local Postgres (port 8801, a prod copy): `alembic upgrade head`, `alembic downgrade -1`, `alembic upgrade head`. Expected: all three succeed; `\d work_order_field_stamps` shows the PK and both FKs.
- [ ] **Step 2:** Edit the two docs within their word budgets.
- [ ] **Step 3:** Commit `docs: W3 save-time conflict check`.

## After the last task

Not pushed (W1–W4 ship together). Owner's check, two logins on one order, on a phone:

| Owner checks | Passes when |
|---|---|
| Login B changes Priority; login A, editor already open, edits Priority and saves | Message names B, the new Priority and an age; both buttons are easy to tap |
| Keep theirs | Priority shows B's value; nothing saved; other typed fields stay |
| Save mine | A's value saved; card repaints |
| B changes Priority; A edits only Location and saves | Saves; Priority keeps B's value |
| B changes a material quantity; A edits the same line | Conflict on that line; the other lines untouched |
| B changes labor hours; A edits the same entry | Conflict names hours |
| Live update arrives while the conflict message shows | Message and buttons stay |
