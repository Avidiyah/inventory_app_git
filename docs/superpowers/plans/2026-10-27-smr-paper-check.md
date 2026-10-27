# SMR27 paper check — plan

Spec: `docs/superpowers/specs/2026-10-27-smr-paper-check-design.md`.
Branch: `main` (consolidate-to-one-branch). Fetch first; commit per task,
explicit paths only (shared checkout). Push only after the user says so
(push = production deploy).

Paths below are relative to `backend/` unless they start with `tests/`.

## Task 1 — columns + migration

- **Goal:** two nullable columns on `work_orders`.
- **Files:** `app/models.py` (beside `smr_target`, ~line 432);
  `alembic/versions/7d9e1f3a4b52_smr_paper_check_columns.py` (new,
  `down_revision = "6c8d0e2f3a41"`, same layout as that file).
- **Steps:**
  1. Model: `smr_paper_checked_at = Column(DateTime(timezone=True), nullable=True)`;
     `smr_paper_checked_by_id = Column(<users.id type>, ForeignKey("users.id", ondelete="SET NULL"), nullable=True)`
     plus a `relationship("User", foreign_keys=...)` named
     `smr_paper_checked_by` (lazy select; the tile loader eager-loads it in
     Task 3). One comment line like the `smr_target` one.
  2. Migration: `add_column` ×2 + named FK; downgrade drops both.
  3. `alembic upgrade head` on the dev DB (port 8801).
- **Test:** `tests/test_models_smr.py`: new columns default NULL; deleting the
  checking user nulls `smr_paper_checked_by_id` and keeps the timestamp.

## Task 2 — schema + toggle service + route

- **Goal:** `PUT /work-orders/smr/{work_order_id}/paper-check`, any role.
- **Files:** `app/schemas/work_orders_smr.py`, `app/services/work_orders_smr.py`,
  `app/routers/work_orders_smr.py`, `docs/endpoint-map.md`.
- **Steps:**
  1. Schemas: `SmrPaperCheckIn { checked: bool }`;
     `SmrPaperCheckOut { checked_at: datetime, checked_by_name: Optional[str] }`
     with `@classmethod from_order(order) -> Optional[Self]` (None when
     `smr_paper_checked_at` is None; name = `checked_by.full_name` or None).
  2. Service `set_paper_check(db, *, work_order_id, checked, user)`:
     order missing → `NotFoundError`; `smr_imported_at is None` →
     `WorkOrderStateError("Not an SMR order")`. `checked` and already set →
     no change (keeps original who/when). `checked` → set now + user.id.
     `not checked` → both NULL. Commit, refresh, return `from_order`.
     Use the domain error classes the target import already raises.
  3. Route: `require_min_role(roles.ROLE_TECHNICIAN)` (lowest role = any
     signed-in user; confirm against how `GET ""` gates), `response_model=Optional[SmrPaperCheckOut]`,
     `DomainError → to_http`. Path parameter typed as the id type the
     `/{work_order_id}/archive` route uses.
  4. `endpoint-map.md`: row **S5** under S4; one line in the SMR27 prose
     block noting the mark is separate from Edited / Matched / archive.
- **Test:** new `tests/test_smr_paper_check.py` through the real `TestClient`
  (FastAPI pitfall memory): set → 200 with who/when; set again keeps the
  original timestamp; clear → `null`; non-SMR order → 422; unknown id → 404;
  Technician allowed; signed-out → 401; setting doesn't change `is_edited`.

## Task 3 — detail + tile + counts carry the mark

- **Goal:** editor and SMR page both see the mark; bar counts it.
- **Files:** `app/schemas/work_orders.py` (`WorkOrderDetail`),
  `app/routers/work_orders.py` (detail builder ~line 536),
  `app/schemas/work_orders_smr.py` (`SmrTile`, `SmrCounts`),
  `app/services/work_orders_smr.py` (`_with_lines`, `tile_for`, `list_smr_tiles`).
- **Steps:**
  1. `WorkOrderDetail.smr_paper_check: Optional[SmrPaperCheckOut] = None`;
     builder sets `SmrPaperCheckOut.from_order(work_order)` when
     `smr_imported_at` is set. Import direction mirrors `SmrTargetOut`
     (it already crosses the two schema modules without a cycle).
  2. `_with_lines`: add `selectinload(WorkOrder.smr_paper_checked_by)` so the
     688-tile list doesn't issue one user query per order.
  3. `SmrTile.paper_check: Optional[SmrPaperCheckOut] = None`, set in `tile_for`.
  4. `SmrCounts.paper_checked: int = 0`, `short_checked: int = 0`
     (target present, not matched, checked); computed in `list_smr_tiles`
     from `all_tiles`.
- **Test:** `tests/test_smr_tiles.py`: checked tile carries name + time;
  counts for a mix of checked / unchecked × short / matched / no-target.
  Detail: one case in the same file (or `test_smr_paper_check.py`) that
  `GET /work-orders/{id}` returns `smr_paper_check`.

## Task 4 — export columns

- **Goal:** `PAPER CHECKED`, `PAPER CHECKED AT`, `PAPER CHECKED BY` on the
  Orders sheet, after `TARGET IMPORTED AT`.
- **Files:** `app/services/work_orders_smr_xlsx.py`.
- **Steps:** append the three headers to `_TARGET` (they are per-order and
  sit in the right place); extend `_target_values` to always append
  `["YES" if checked else None, _when(checked_at), name]`. The early
  `[None] * len(_TARGET)` return then needs the paper values appended
  instead, since a no-target order can still be paper-checked; split the
  three into a tiny `_paper_values(order)` and concatenate in
  `_orders_sheet`. Name via the eager-loaded relationship.
- **Test:** `tests/test_smr_export_xlsx.py`: header order; a checked
  no-target order still fills the three columns; unchecked → blanks.

## Task 5 — API client + editor button

- **Goal:** one-click mark / clear in the Materials section.
- **Files:** `static/api.js`, `static/views/workOrderPresenters.js`,
  `static/views/workOrderCardHtml.js`, `static/views/workOrderActions.js`,
  CSS file holding `.wo-target--*` (same file), `tests/frontend/helpers/endpointTable.js`.
- **Steps:**
  1. `api.js`: `apiSetSmrPaperCheck(id, checked)` → `PUT
     /work-orders/smr/${id}/paper-check` JSON `{ checked }`, beside
     `apiImportSmrTargets`. Endpoint table row added.
  2. Presenter `paperCheckHtml(detail)`: `""` unless `detail.smr`. Unchecked:
     `<button type="button" class="secondary-btn" data-action="smr-paper-check" data-checked="true">Mark paper checked</button>`.
     Checked: `Paper checked by {name} · {formatted time}` line (class
     `wo-paper-check`) + `Clear paper check` button with `data-checked="false"`.
     Reuse the existing date formatter the notes log uses. Escape the name.
  3. Card: `${paperCheckHtml(detail)}` directly after
     `${targetMaterialsHtml(detail)}`, outside the `locked` branch (any role
     may mark; SMR orders are never locked anyway).
  4. Actions: branch `action === "smr-paper-check"` → `await
     apiSetSmrPaperCheck(workOrderId, btn.dataset.checked === "true")` →
     `refreshCard(cardEl, ".wo-materials-section")`; errors go to the
     section message like the others. `workOrderActions.js` is at 557
     (over 500, under the 1,000 work-order cap memo): ~6 lines is fine.
- **Test:** `tests/frontend/views/workOrders/render.test.js`: unchecked SMR
  detail shows the Mark button; checked shows name line + Clear; non-SMR
  shows neither. `editorActions.test.js`: clicking sends the PUT with the
  right body and re-renders. `staticImports` guard stays green.

## Task 6 — SMR page filters, badge, bar

- **Goal:** `PAPER ✓` badge, two new filters, two bar counts.
- **Files:** `static/pages/smr.html`, `static/views/smr.js`, SMR CSS (where
  `.smr-tile--matched` lives), `tests/frontend/views/smr.test.js`.
- **Steps:**
  1. HTML: after the Short button, add
     `data-filter="short_checked"` **Checked, still short** and
     `data-filter="checked"` **Paper checked** (ids `smr-filter-short-checked`,
     `smr-filter-checked`).
  2. `matches()`: `"checked"` → `Boolean(tile.paper_check)`;
     `"short_checked"` → short rule `&& Boolean(tile.paper_check)`.
     Short stays unchanged (D3).
  3. Bar: append `${c.paper_checked || 0} PAPER CHECKED` and
     `${c.short_checked || 0} CHECKED, STILL SHORT`.
  4. Tile: `smr-tile--checked` class + a `PAPER ✓` badge span when
     `tile.paper_check`; style per `docs/design-system.md` (SMR page is
     white-on-black brutalist, badge-only accent).
  5. Update the comment at line ~152 listing the local buttons.
- **Test:** `smr.test.js`: payload with a checked short, a checked matched
  and an unchecked short tile → Paper checked shows 2, Checked-still-short
  shows 1, Short shows 2; badge only on checked; bar text has both counts.

## Task 7 — docs + verification

- **Goal:** current-truth docs, everything green.
- **Files:** `docs/current-state.md` (SMR section: one line for the mark),
  `docs/endpoint-map.md` (done in Task 2), spec status → shipped.
- **Steps:**
  1. Targeted pytest: `tests/test_smr_paper_check.py test_smr_tiles.py
     test_smr_export_xlsx.py test_models_smr.py test_smr_exclusion.py`.
  2. Vitest: `smr.test.js`, `render.test.js`, `editorActions.test.js`,
     `staticImports`, endpoint-table test.
  3. Rebuild `inventory-local` so the user can check it in the app; don't
     auto-run the preview (manual validation memo).
  4. Report and ask before pushing main.
- **Test:** the runs above; paste counts in the completion report.
