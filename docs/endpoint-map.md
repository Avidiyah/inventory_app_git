# Endpoint Map: Database ↔ User View

Last reviewed: 2026-08-31 · Soft word budget: 11,000 (CLAUDE.md → Documentation
conventions)

Endpoint wiring, contracts, rules, and error behavior — answers "what does this
endpoint send/return/do?" without opening `schemas/`, `services/`, `domain/`,
or `routers/`. Companion to `docs/current-state.md` (invariants/data model).

Every feature is the same layer chain; reads flow up it, writes flow down:

```
DB table ─▶ models.py ─▶ services/*.py ─▶ routers/*.py ─▶ (HTTP) ─▶ static/api.js ─▶ static/views/*.js
```

Paths are relative to `backend/` (`domain/*`, `routers/*`, `services/*`,
`models.py` under `backend/app/`; `api.js`, `views/*` under
`backend/static/`). Gates are enforced server-side (`auth_deps.py`); see
`current-state.md` → Roles And Access.

---

## Master Endpoint Index

Every endpoint, one row each: 4 app-level routes in `main.py` plus every
router operation (the `/ws` WebSocket is row WS1; exact counts are volatile —
verify against `app.openapi()`). "Tables" lists what the call reads (r) and
writes (w).

| # | Method | Path | Gate | Router → Service | Tables | api.js wrapper | View(s) |
|---|--------|------|------|------------------|--------|----------------|---------|
| 1 | GET | `/` | public | `main.py` (shell assembly) | — | — (browser) | SPA boot |
| 1a | GET | `/healthz` | public | `main.py` → `database.check_connection` | — | — | (platform health check) |
| 1b | GET | `/workorder_card/{number}` | public | `main.py` (shell assembly) | — | — (browser) | SPA boot (deep-linked work-order card) |
| 2 | GET | `/db-test` | techfm_oa+ | `main.py` → `database.test_connection` | — | — | (diagnostic) |
| 3 | POST | `/auth/login` | public | `auth.py` → `auth.authenticate` + `create_session` | users (r), sessions (w) | `apiLogin` | `auth.js` |
| 4 | POST | `/auth/logout` | session | `auth.py` → `auth.delete_session` | sessions (w) | `apiLogout` | `auth.js` |
| 5 | GET | `/auth/me` | session | `auth_deps.get_current_user` | sessions (r), users (r) | `apiMe` | `auth.js`, `tools.js` (self profile) |
| 6 | GET | `/items/` | session | `items.py` → `items.list_items` (optional `q`) | items (r) | `apiListItems` | `items.js`, `addBarcode.js`, `transactions.js`, `massStage.js`, `workOrders.js` |
| 7 | GET | `/items/{barcode}` | session | `items.py` → `items.get_item_by_barcode` | items (r), item_barcodes (r) | `apiGetItemByBarcode` | `scan.js`, `addBarcode.js`, `history.js` |
| 8 | POST | `/items/` | techfm_oa+ | `items.py` → `items.create_item` | items (w), item_barcodes (r) | `apiCreateItem` | `items.js` |
| 9 | PATCH | `/items/{id}` | techfm_oa+ | `items.py` → `items.update_item` (+ `user_requests.resolve_missing_price_requests`) | items (w/lock), item_barcodes (r), user_requests (w when price+link complete) | `apiUpdateItem` | `itemEditor.js`, `userRequests.js` |
| 10 | PATCH | `/items/{id}/notes` | supervisor+ | `items.py` → `notes.replace_notes` | items (w) | `apiUpdateNotes` | `notes.js` |
| 11 | PATCH | `/items/{id}/barcodes` | techfm_oa+ | `items.py` → `items.replace_barcodes` | item_barcodes (w), items (r) | `apiUpdateBarcodes` | `itemEditor.js`, `addBarcode.js` |
| 12 | DELETE | `/items/{id}` | techfm_oa+ | `items.py` → `items.delete_item` | items (w, archive) | `apiDeleteItem` | `items.js` |
| 13 | POST | `/barcodes/decode` | session | `barcodes.py` → `barcodes.decode_image` | — (no persistence) | `apiDecodeBarcode` | `scan.js` |
| 14 | GET | `/users/` | supervisor+ | `users.py` → `users.list_users` | users (r) | `apiListUsers` | `users.js`, `transactions.js`, `massStage.js`, `workOrders.js`, `tools.js` (TechFM OA and above only) |
| 15 | POST | `/users/` | outranks target | `users.py` → `users.create_user` | users (w) | `apiCreateUser` | `users.js` |
| 16 | POST | `/users/{id}/reset-password` | outranks target | `users.py` → `users.reset_password` | users (w) | `apiResetPassword` | `users.js` |
| 17 | POST | `/users/{id}/archive` | outranks target | `users.py` → `users.archive_user` + `tools.user_custody` (+ `tools.return_all_for_user` when `?force_return_tools=true`) | users (w), sessions (w, revoke), tools/tool_transactions (r, custody guard; w on force check-in) | `apiArchiveUser` | `users.js` |
| 18 | POST | `/users/{id}/restore` | outranks target | `users.py` → `users.restore_user` | users (w) | `apiRestoreUser` | `users.js` |
| 19 | DELETE | `/users/{id}` | outranks target | `users.py` → `users.delete_user` | users (w, hard) | `apiDeleteUser` | **API-only** (no UI; UI uses archive) |
| 20 | GET | `/transactions/` | supervisor+ | `transactions.py` → `history.list_history` | transactions (r), items (r), users (r) | `apiListTransactions` | `history.js` |
| 21 | POST | `/transactions/` | session + direction¹ | `transactions.py` → `transactions.apply_transaction` (+ `work_orders.resolve_work_order`, `attach_dispense_line`; User Request producers for shortage/missing price) | items (w), transactions (w), work_orders (r/w²), work_order_items (w³), user_requests (w on shortage or NULL/non-positive work-order price) | `apiCreateTransaction` | `transactions.js` |
| 22 | POST | `/transactions/adjust` | techfm_oa+ | `transactions.py` → `transactions.apply_correction` | items (w), transactions (w) | `apiCreateCorrection` | `correction.js` |
| 23 | PATCH | `/transactions/{id}/billing` | techfm_oa+ | `transactions.py` → `transactions.set_billable_quantity` | transactions (w) | `apiSetBillableQuantity` | `history.js` |
| 24 | DELETE | `/transactions/{id}` | supervisor+, or Technician's own linked dispense | `transactions.py` → `transactions.void_transaction` (+ `user_requests.resolve_for_transaction`) | transactions (w, soft), items (w), work_order_items (w⁴), user_requests (w if linked) | `apiVoidTransaction` | `history.js`, `transactions.js` |
| 25 | GET | `/work-orders/` | session scoped | `work_orders.py` → `work_orders.list_work_orders` (scheduled-date descending; joinable status/service/supervisor/community/date/number/location/task filters) | work_orders (r), work_order_items (r), work_order_technicians (r), users (r) | `apiListWorkOrders` | `workOrders.js`, `transactions.js`, `history.js`, `adminReview.js` |
| 26 | GET | `/work-orders/{id}` | session scoped | `work_orders.py` → `work_orders.get_work_order` | work_orders (r), work_order_items (r/w⁵), work_order_technicians (r), work_order_labor (r), items (r), users (r) | `apiGetWorkOrder` | `workOrders.js`, `history.js`, `adminReview.js` |
| 27 | GET | `/work-orders/lookup?number=` | supervisor+ scoped | `work_orders.py` → `work_orders.lookup_work_order` | work_orders (r, **incl. archived**) | `apiLookupWorkOrder` | `history.js`, `workOrders.js` (TechFM OA+ exact search) |
| 28 | PATCH | `/work-orders/{id}` | scoped; notes→tech+, operations→sup+, metadata→techfm_oa+; stale supervisor precondition→409 | `work_orders.py` → `work_orders.update_work_order` | work_orders (r/w, row lock; incl. notes/primary mirror), work_order_technicians (w), users (r) | `apiUpdateWorkOrder` | `workOrders.js`, `adminReview.js` (Return to In-Progress) |
| 29 | POST | `/work-orders/{id}/archive` | techfm_oa+ scoped; any live status | `work_orders.py` → `work_orders.archive_work_order` | work_orders (w, Closed/archive) | `apiArchiveWorkOrder` | `workOrders.js`, `adminReview.js` |
| 30 | POST | `/work-orders/{id}/items` | Technician+ scoped | `work_orders.py` → `work_orders.add_work_order_item` | items (w; negative expected count allowed in dispense mode), transactions (w), work_order_items (w), user_requests (w if stock is short or item is unpriced) | `apiAddWorkOrderItem` | `workOrders.js` |
| 31 | PATCH | `/work-orders/{id}/items/{wid}` | supervisor+ scoped | `work_orders.py` → `work_orders.update_work_order_item` | items (w), transactions (w, adjust), work_order_items (w) | `apiUpdateWorkOrderItem` | `workOrders.js` |
| 32 | PATCH | `/work-orders/{id}/items/{wid}/billing` | techfm_oa+ scoped | `work_orders.py` → `work_orders.set_work_order_item_billable` | work_order_items (w) | `apiSetWorkOrderItemBilling` | `workOrders.js` |
| 33 | DELETE | `/work-orders/{id}/items/{wid}` | supervisor+ scoped | `work_orders.py` → `work_orders.delete_work_order_item` | items (w), transactions (w, void), work_order_items (w), user_requests (w, resolve source-linked) | `apiDeleteWorkOrderItem` | `workOrders.js` |
| 34 | POST | `/mass-stages/` | supervisor+ | `mass_stages.py` → `mass_staging.create_stage` | mass_stages (w) | `apiCreateStage` | `massStage.js` |
| 35 | GET | `/mass-stages/` | supervisor+ scoped | `mass_stages.py` → `mass_staging.list_stages` | mass_stages (r) | `apiListStages` | `massStage.js` |
| 36 | GET | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.get_stage` | mass_stages (r), mass_stage_work_orders (r), mass_stage_items (r), work_orders (r), items (r) | `apiGetStage` | `massStage.js` |
| 37 | PATCH | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.update_stage` | mass_stages (w) | `apiUpdateStage` | `massStage.js` |
| 38 | DELETE | `/mass-stages/{id}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_stage` | mass_stages (w), slots/items (cascade) | `apiDeleteStage` | `massStage.js` |
| 39 | POST | `/mass-stages/{id}/reuse` | supervisor+ | `mass_stages.py` → `mass_staging.reuse_stage` | mass_stages (w) | `apiReuseStage` | `massStage.js` |
| 40 | POST | `/mass-stages/{id}/work-orders` | supervisor+ | `mass_stages.py` → `mass_staging.add_work_order_to_stage` | mass_stage_work_orders (w), work_orders (r/w, **resolve** — 404 if not imported) | `apiAddStageWorkOrder` | `massStage.js` |
| 41 | DELETE | `/mass-stages/{id}/work-orders/{slot}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_slot` | mass_stage_work_orders (w), mass_stage_items (cascade) | `apiDeleteStageWorkOrder` | `massStage.js` |
| 42 | POST | `/mass-stages/{id}/work-orders/{slot}/items` | supervisor+ | `mass_stages.py` → `mass_staging.add_item` | mass_stage_items (w) | `apiAddStageItem` | `massStage.js` |
| 43 | PATCH | `/mass-stages/{id}/work-orders/{slot}/items/{sid}` | supervisor+ | `mass_stages.py` → `mass_staging.update_item` | mass_stage_items (w) | `apiUpdateStageItem` | `massStage.js` |
| 44 | DELETE | `/mass-stages/{id}/work-orders/{slot}/items/{sid}` | supervisor+ | `mass_stages.py` → `mass_staging.delete_item` | mass_stage_items (w) | `apiDeleteStageItem` | `massStage.js` |
| 45 | POST | `/mass-stages/{id}/load` | supervisor+ | `mass_stages.py` → `mass_staging.load_item` | items (w), transactions (w), work_order_items (w), mass_stage_items (w), user_requests (w if unpriced) | `apiLoadStageItem` | `massStage.js` |
| 46 | POST | `/mass-stages/{id}/return` | supervisor+ | `mass_stages.py` → `mass_staging.return_item` | items (w, silent), work_order_items (w), mass_stage_items (w) | `apiReturnStageItem` | `massStage.js` |
| 47 | POST | `/tools/` | techfm_oa+ | `tools.py` → `tools_service.create_tool` | tools (w) | `apiCreateTool` | `tools.js` |
| 48 | GET | `/tools/` | session | `tools.py` → `tools_service.list_tools` + `tool_custody` | tools (r), tool_transactions (r), users (r) | `apiListTools` | `tools.js` |
| 49 | GET | `/tools/{barcode}` | session | `tools.py` → `tools_service.get_tool_by_barcode` + `tool_custody` | tools (r), tool_transactions (r), users (r) | `apiGetToolByBarcode` | `tools.js` |
| 50 | PATCH | `/tools/{tool_id}` | techfm_oa+ | `tools.py` → `tools_service.update_tool` | tools (w) | `apiUpdateTool` | `tools.js` |
| 51 | DELETE | `/tools/{tool_id}` | techfm_oa+ | `tools.py` → `tools_service.delete_tool` + `tool_custody` | tools (r/w, archive), tool_transactions (r, custody guard) | `apiDeleteTool` | `tools.js` |
| 52 | POST | `/tools/{tool_id}/checkout` | techfm_oa+ | `tools.py` → `tools_service.checkout_tool` | users (r, active-target guard), tools (w), tool_transactions (w) | `apiCheckoutTool` | `toolCheckout.js` |
| 53 | POST | `/tools/{tool_id}/return` | session | `tools.py` → `tools_service.return_tool` | tools (w), tool_transactions (w, r for cap check) | `apiReturnTool` | `toolReturn.js` |
| 54 | POST | `/tools/{tool_id}/adjust` | techfm_oa+ | `tools.py` → `tools_service.adjust_tool_quantity` | tools (w), tool_transactions (w) | `apiAdjustTool` | `toolCorrection.js` |
| 55 | POST | `/work-orders/import` | techfm_oa+ | `work_orders.py` → `work_orders.import_work_orders` | work_orders (r/w, locked find-or-create — **the only create path**), users (r, active-supervisor name-match) | `apiImportWorkOrders` | `workOrders.js` |
| 56 | POST | `/work-orders/{id}/restore` | supervisor+ scoped | `work_orders.py` → `work_orders.restore_work_order` | work_orders (w, un-archive) | `apiRestoreWorkOrder` | `history.js`, `workOrders.js` (TechFM OA+ exact search) |
| 57 | PATCH | `/users/{id}/name` | self or outranks target | `users.py` → `users.update_name` | users (w; first/last name + optional `username`) | `apiUpdateUserName` | `users.js` |
| 58 | POST | `/work-orders/{id}/labor` | supervisor+ scoped (assigned worker, or self) | `work_orders.py` → `work_orders.add_work_order_labor` | work_orders (r/w status), work_order_technicians (r), work_order_labor (w), users (r) | `apiAddWorkOrderLabor` | `workOrders.js` |
| 59 | PATCH | `/work-orders/{id}/labor/{labor_id}` | supervisor+ scoped | `work_orders.py` → `work_orders.update_work_order_labor` | work_order_labor (r/w) | `apiUpdateWorkOrderLabor` | `workOrders.js` |
| 60 | DELETE | `/work-orders/{id}/labor/{labor_id}` | supervisor+ scoped | `work_orders.py` → `work_orders.delete_work_order_labor` | work_order_labor (r/w) | `apiDeleteWorkOrderLabor` | `workOrders.js` |
| 61 | PATCH | `/users/{id}/role` | techfm_oa+ AND outranks both current and new role | `users.py` → `users.update_role` | users (w), sessions (w, revoke) | `apiUpdateUserRole` | `users.js` |
| 62 | GET | `/work-orders/export` | techfm_oa+, server-scoped | `work_orders.py` → `work_orders.export_work_orders_csv` (full: current live filters incl. location/task keyword search; client: unchanged scope dropdown; + `domain.receipt`) | work_orders (r), work_order_items (r), items (r), work_order_labor (r), users (r) | `apiExportWorkOrders` | `workOrders.js` |
| 63 | GET | `/work-orders/filter-options` | session scoped | `work_orders.py` → `work_orders.get_work_order_filter_options` | work_orders (r), work_order_technicians (r, scope), users (r) | `apiGetWorkOrderFilterOptions` | `workOrders.js` |
| 64 | GET | `/work-orders/legacy/archive` | owner exactly | `work_orders.py` → `work_orders.count_live_legacy_work_orders` | work_orders (r; live legacy count) | `apiGetLegacyWorkOrderArchivePreview` | `workOrders.js` |
| 65 | POST | `/work-orders/legacy/archive` | owner exactly | `work_orders.py` → `work_orders.archive_live_legacy_work_orders` | work_orders (w; atomic bulk soft-archive) | `apiArchiveLegacyWorkOrders` | `workOrders.js` |
| 66 | POST | `/work-orders/{id}/start` | technician+ scoped | `work_orders.py` → `work_orders.start_work_order` | work_orders (r/w, row lock) | `apiStartWorkOrder` | `transactions.js`, `workOrders.js` |
| 67 | GET | `/user-requests/` | techfm_oa+ | `user_requests.py` → `user_requests.list_user_requests` | user_requests (r), items (r), work_orders (r), users (r) | `apiListUserRequests` | `userRequests.js` |
| 68 | PATCH | `/user-requests/{id}` | techfm_oa+ | `user_requests.py` → `user_requests.update_user_request` / `update_user_request_fields` | user_requests (r/w), users (r) | `apiUpdateUserRequest` | `userRequests.js` |
| 68a | POST | `/user-requests/item-request` | session (any role) | `user_requests.py` → `user_requests.create_item_request` | user_requests (w), work_orders (r) | `apiCreateItemRequest` | `itemRequest.js` |
| 68b | GET | `/user-requests/{id}/siblings` | techfm_oa+ | `user_requests.py` → `user_requests.find_sibling_item_requests` | user_requests (r), work_orders (r), users (r) | `apiListRequestSiblings` | `userRequests.js` |
| 68c | POST | `/user-requests/{id}/fulfill` | techfm_oa+ | `user_requests.py` → `items.create_item` (optional) + `user_requests.fulfill_item_request` → `work_orders.attach_dispense_line` | user_requests (r/w, row lock), items (r/w on create), work_orders (r/w status), work_order_items (w, retroactive) | `apiFulfillItemRequest` | `userRequests.js` |
| 69 | POST | `/work-orders/{id}/complete` | assigned Technician/Supervisor | `work_orders.py` → `work_orders.complete_work_order` | work_orders (r/w status + notes, row lock), work_order_technicians (r), push_subscriptions (r, via notify) | `apiCompleteWorkOrder` | `workOrders.js` |
| 70 | POST | `/work-orders/{id}/hold` | assigned Technician/Supervisor | `work_orders.py` → `work_orders.hold_work_order` | work_orders (r/w, row lock), work_order_technicians (r), push_subscriptions (r, via notify) | `apiHoldWorkOrder` | `workOrders.js` |
| 71 | POST | `/work-orders/{id}/resume` | assigned Technician/Supervisor | `work_orders.py` → `work_orders.resume_work_order` | work_orders (r/w, row lock), work_order_technicians (r) | `apiResumeWorkOrder` | `workOrders.js` |
| 71a | POST | `/work-orders/{id}/tracking/start` | assigned Technician, or Supervisor+ on any visible row | `work_orders.py` → `work_orders.start_labor_session` | work_orders (r/w status + notes, row lock), work_order_technicians (r), work_order_labor_sessions (r/w), work_order_labor (w, when it closes a clock elsewhere), push_subscriptions (r, via notify on that row's auto-hold) | `apiStartWorkOrderTracking` | `workOrders.js` |
| 71b | POST | `/work-orders/{id}/tracking/stop` | assigned Technician, or Supervisor+ on any visible row | `work_orders.py` → `work_orders.stop_labor_session` | work_orders (r/w status + notes, row lock), work_order_technicians (r), work_order_labor_sessions (r/w), work_order_labor (w), push_subscriptions (r, via notify on auto-hold) | `apiStopWorkOrderTracking` | `workOrders.js` |
| 72 | GET | `/work-orders/auto-close/pending` | techfm_oa+ | `work_orders.py` → `work_orders.pending_auto_close` | work_orders (r; sweep-closed rows inside the 24h window) | `apiGetWorkOrderAutoClosePending` | `workOrders.js` (Integrations card) |
| 73 | POST | `/work-orders/auto-close/undo` | techfm_oa+ | `work_orders.py` → `work_orders.undo_auto_close` | work_orders (r/w, row lock; un-archive + note per row) | `apiUndoWorkOrderAutoClose` | `workOrders.js` (Integrations card) |
| NF2 | POST | `/integrations/netfacilities/work-orders/enrich` | techfm_oa+ | `netfacilities.py` → `_resolve_cloud_enrichment_context` (the caller's own cloud session) → `netfacilities_jobs.start` → `netfacilities.enrich_work_orders` | work_orders (r/w, existing live candidates only; short compare-and-set locks); netfacilities_cloud_sessions (r, caller's own row only) | `apiStartNetFacilitiesEnrichment` | `workOrders.js` |
| NF3 | GET | `/integrations/netfacilities/work-orders/enrich/{job_id}` | techfm_oa+ | `netfacilities.py` → `netfacilities_jobs.get` | no DB; process-local aggregate-only job snapshot | `apiGetNetFacilitiesEnrichment` | `workOrders.js` |
| NF5 | GET | `/integrations/netfacilities/cloud/session` | techfm_oa+ | `netfacilities.py` → `netfacilities_cloud_auth.latest` + `NetFacilitiesCloudSession` existence check | netfacilities_cloud_sessions (r, existence only) | `apiGetNetFacilitiesCloudSession` | `workOrders.js` (Integrations card, cloud sign-in) |
| NF5a | POST | `/integrations/netfacilities/cloud/auth/start` | techfm_oa+ | `netfacilities.py` → `netfacilities_cloud_auth.start` → `SteelCloudBrowserProvider.open_login_session` | no DB; opens a Steel cloud session, per-user in-memory ceremony state | `apiStartNetFacilitiesCloudAuthentication` | `workOrders.js` |
| NF5b | POST | `/integrations/netfacilities/cloud/auth/cancel` | techfm_oa+ | `netfacilities.py` → `netfacilities_cloud_auth.cancel` → `SteelCloudBrowserProvider.close_login_session` | no DB; releases the Steel session | `apiCancelNetFacilitiesCloudAuthentication` | `workOrders.js` |
| NF6 | POST | `/integrations/netfacilities/cloud/downloads/import` | techfm_oa+ | `netfacilities.py` → `netfacilities_cloud_auth.dispatch_capture` → `work_orders.run_csv_import` → close session → `netfacilities_jobs.start` → chain push | **work_orders** (find-or-create by number, same realtime + push side effects as WO import), netfacilities_cloud_sessions (r), push_subscriptions (r, chain outcome push) | `apiImportNetFacilitiesCloudDownload` | `workOrders.js` (Integrations card, **Import downloaded CSV** — returns `NetFacilitiesCloudSessionStatus`, runs the same chain the automatic capture trigger does) |
| WS1 | WS | `/ws` | session cookie + same-origin | `realtime.py` → `services/realtime` registry → `domain/realtime` policy | **none** — carries no row data, reads and writes nothing | — (`static/realtime.js` owns the socket; not an `api.js` wrapper) | `adminReview.js`, `workOrders.js`, `userHub.js` (subscribers), `auth.js` + `nav.js` (lifecycle) |
| H1 | GET | `/hub` | any authenticated | `hub.py` → `hub.personal_hub` → `work_orders.sweep_stale_sessions` + `labor_summary.day_summary` + `tools.user_custody_detail` | work_order_labor_sessions (r/w on sweep), work_order_labor (r; w on sweep), work_orders (r; row lock on sweep), work_order_technicians (r), tool_transactions (r), tools (r), users (r) | `apiGetHub` | `userHub.js`, `hubClock.js`, `hubTechnician.js` |
| H2 | GET | `/hub/crew` | supervisor+ | `hub.py` → `hub.crew_hub` → `work_orders.sweep_stale_sessions` (per crew member) + `labor_summary.crew_day_summaries` + `labor_summary.last_worked` | work_order_labor_sessions (r/w on per-member sweep), work_order_labor (r; w on sweep), work_orders (r; row lock on sweep), work_order_technicians (r), users (r) | `apiGetHubCrew` | `userHub.js`, `hubSupervisor.js` |
| H3 | GET | `/hub/timesheets` | supervisor+ | `hub.py` → `hub.timesheets_hub` → `work_orders.sweep_stale_sessions` (per crew member) + `labor_summary.crew_range_summaries` | work_order_labor_sessions (r/w on per-member sweep), work_order_labor (r; w on sweep), work_orders (r; row lock on sweep), work_order_technicians (r), users (r) | `apiGetHubTimesheets` | `userHub.js`, `hubTimesheets.js` |
| H4 | GET | `/hub/timesheets/export` | supervisor+ | `hub.py` → `hub.timesheets_hub` + `hub.timesheet_csv` | same as H3 | `apiExportHubTimesheets` | `hubTimesheets.js` |
| H5 | GET | `/hub/graphs?weeks=12\|26\|52` | techfm_oa+ | `hub.py` → `hub.graphs_hub` → shared graph/community rules | work_orders (narrow status/location/service/timestamp projections; read-only) | `apiGetHubGraphs` | `userHub.js`, `hubGraphs.js` |
| H6 | GET | `/hub/report` | **admin only** | `hub.py` → `work_order_report.daily_report` → `labor_day` windows + `work_orders.export_row` / `work_order_totals` | work_orders (r), work_order_items + items (r), work_order_labor (r), work_order_technicians (r), users (r) | `apiGetHubReport` | `userHub.js`, `hubReport.js` |
| H7 | GET | `/hub/report/export` | **admin only** | `hub.py` → `work_order_report.daily_report` + `work_order_report_xlsx.report_xlsx` | same as H6 | — (plain link, as H4 is) | `hubReport.js` |
| P1 | GET | `/push/config` | any authenticated | `push.py` → `services/push.is_configured` | — (503 when `VAPID_PRIVATE_KEY` unset) | `apiPushConfig` | `push.js` |
| P2 | POST | `/push/subscribe` | any authenticated | `push.py` → subscription store | push_subscriptions (w — upsert; **reassigns** the endpoint row to the caller) | `apiPushSubscribe` | `push.js` |
| P3 | POST | `/push/unsubscribe` | any authenticated | `push.py` → subscription store | push_subscriptions (w, delete caller's device row) | `apiPushUnsubscribe` | `push.js`, `auth.js` (logout, this device only) |
| P4 | POST | `/push/test` | **owner** | `push.py` → `services/push` fan-out | push_subscriptions (r; w on 404/410 prune), users (r, Admin+ audience) | `apiPushTest` | `push.js` (Owner test trigger) |

(Numbering is append-only and stable — other docs cite it. Gaps (NF1, NF1a–c,
NF4) are removed endpoints; WS1 and the H*/NF* rows are numbered apart from the
resource rows.)

Footnotes:
1. `POST /transactions/`: dispense = any authenticated user; stock = supervisor+ (`domain.roles.can_transact`). A Scan/Stock dispense may take expected quantity below zero and opens a recount request. Work Orders Add Item has the same deliberate exception; Work Order quantity edits and the other stock-out paths retain the strict no-overdraft domain rule.
2. work_orders: read when a scanned card passes `work_order_id`; resolved (read, plus a fill-blanks write) when a Supervisor+ passes a free-text `work_order_number` — 404 if that number was never imported.
3. work_order_items: a line is created/accumulated only for a `dispense` carrying a `work_order_id` (a stock-in writes none).
4. void walks the work_order_items line back (drops it at zero) when the voided row carries a `work_order_id`; it also resolves any request linked to the source transaction. Supervisor+ may void any eligible row, while a Technician may remove only their own work-order-linked dispense.
5. `get_work_order` lazily self-heals orphaned linked dispenses into lines on read (a write inside a read).

---

## Read & Write Flows

Wiring lives in the Master Index; this section records only semantics the index
cannot carry. Read: table → service → endpoint → wrapper → view. Write: view
action → wrapper → endpoint → service → table effect.

### Boot / session
- `GET /auth/me` on load: 200 ⇒ enter app (nav visibility applied), 401 ⇒ login
  screen. Identity includes `created_at`/`archived_at`; `tools.js` uses them
  for the self-only custody profile below TechFM OA.
- `GET /` and `GET /workorder_card/{number}` serve the identical SPA shell,
  unauthenticated, rate-limit exempt. The `number` segment is routing only and
  never reflected into the HTML; `workOrders.js` reads it from
  `location.pathname` and resolves it via the server-scoped list search.

### Items
- Find Item fires no request on entry; results render only on explicit
  Search/Enter or Load All Items (TechFM OA+ see price/link columns).
- `GET /items/` also feeds `addBarcode.js` (debounced name picker),
  `transactions.js` (manual pick panel; Supervisor+ may browse-all with an
  empty search), and the massStage/workOrders item pickers.
- `GET /items/{barcode}` resolves scans (`scan.js`), attach-target confirms
  (`addBarcode.js`), and History's by-item lookup.

### Users / history
- `GET /users/` feeds the account table (archived included, dimmed), full-name
  technician dropdowns, workOrders' local assignee search, and tools' active-
  user custody search (TechFM OA+). Supervisor/Technician use `/auth/me` for a
  self-only tools card instead.
- History renders full names, never login usernames. The Charge column
  (`item_price` × qty × 1.15) is TechFM OA+ and **null for work-order rows** —
  they bill via the line.
- Copy-table cross-read: History's copy button reads `GET /transactions/`
  plus, per distinct work order in the set, `GET /work-orders/{id}` (resolved
  from number via `?q=`) to price rows and append the authoritative Work Order
  Summary (`materials_total` + 15%).

### Stock movement
- Scan gate: `GET /work-orders/` keeps scoped Created/Assigned/In-Progress
  cards; search only filters. Picking In-Progress arms the batch; picking
  Assigned confirms then `POST /work-orders/{id}/start` (atomic
  Assigned → In-Progress, no navigation); picking Created offers navigating to
  the expanded Work Order. Unknown numbers are refused client-side and 404
  server-side (`resolve_work_order`). The manual item picker is hidden until a
  card is selected.
- `POST /transactions/`: items.quantity ±, transactions insert; a dispense
  carrying `work_order_id` creates/accumulates a work_order_items line (stock-
  in writes none). A dispense beyond counted stock commits a negative expected
  count and opens one linked `inventory_recount` request (UI: red `Please
  re-count stock`). Work-order material with a NULL/non-positive price creates
  or extends one item-level `missing_item_price` request accumulating every
  affected work-order number.
- Void (`DELETE /transactions/{id}`): reverses stock, walks the
  work_order_items line back (deletes at zero), soft-voids the row, resolves
  the linked request. Supervisor+ may void any eligible row; a Technician only
  their own work-order-linked dispense.
- Correction (`POST /transactions/adjust`): absolute target quantity, signed
  `adjust` row. Billing edit (`PATCH .../billing`): no stock change.

### User requests
- Price+link saves go through `PATCH /items/{id}` (inline input `min="0.01"`);
  open missing-price requests auto-resolve only when a positive price AND
  nonblank link both exist. Recount cards resolve/reopen via
  `PATCH /user-requests/{id}` (TechFM OA+; reopen clears resolution fields).
  Resolved missing-price cards are read-only in the UI, though the generic
  endpoint accepts an API reopen.

### Users (writes)
- Archive: 409 while the target holds tools; the retry
  (`?force_return_tools=true`) writes a return row per held tool and restores
  tools.quantity before archiving. Archive and role change both revoke the
  target's sessions.
- Role change requires TechFM OA+ and strictly outranking both the current and
  the new role. `DELETE /users/{id}` is API-only hard delete (blocked by
  transaction FKs); the UI archives.

### Work orders
Import-only: `POST /work-orders/import` is the sole create path. No create
endpoint or form exists; every other surface resolves an existing number and
404s on one no import brought in.

- Import: per row, locked find-or-create with idempotent fill-blanks merge.
  A blank task stores the canonical NetFacilities URL, replaceable by a later
  real CSV task; real/manual tasks stay authoritative. Supervisor routing
  (name-matched from `ASSIGNED TO` against active supervisors; miss/ambiguity
  stays unassigned) fills only a still-NULL `supervisor_id`, so a manual
  reroute wins. A person-archived match counts as closed and is ignored; a
  sweep-archived one is reopened and merged. After the row loop, one
  transaction auto-closes every live non-legacy work order the CSV did not
  list (stops clocks, stamps `auto_closed_batch_id`/`auto_closed_at`) — an
  all-blank-number CSV sweeps nothing. Each matched supervisor gets one bulk
  push (`work_order.supervisor_assigned_bulk`, created rows only).
- Auto-close undo: `GET /work-orders/auto-close/pending` (company-wide, 24 h
  window) gates the Integrations button; the POST un-archives with a per-row
  note.
- Cloud auth (Steel): `POST .../cloud/auth/start` opens a cloud browser and
  returns its live-view URL; credentials/CAPTCHA/MFA are completed there; the
  coordinator auto-confirms once a page leaves the login screen and encrypts
  the captured session into netfacilities_cloud_sessions (one row per user).
  Cancel releases the Steel session. Responses never carry credentials,
  storage state, or paths.
- Enrichment: after a CSV import succeeds and the caller has a saved or live
  session, `POST .../work-orders/enrich` replays the decrypted session into a
  fresh short-lived Steel session, snapshots eligible rows, performs serial
  allowlisted reads, then briefly locks/rechecks each row — filling only the
  exact generated Task/Symptom fallback and a blank Priority. Polling is
  aggregate-only; missing/expired auth preserves the completed import and
  expires the saved row.
- Auto-capture: a CSV exported in the cloud window is dispatched unattended
  (`dispatch_capture` → the same `run_csv_import` the upload route uses →
  close the Steel session on success, kept open on a failed import →
  enrichment via the caller's saved session → outcome push). The manual
  **Import downloaded CSV** button (`POST .../cloud/downloads/import`, shown
  only for an unconsumed capture) runs the same chain, so manual and automatic
  cannot drift; the session poll narrates it (`chain_stage`, `import_result`,
  `enrichment_job_id`).
- Edit details (`PATCH /work-orders/{id}`): Supervisor sees routing and
  status; TechFM OA+ also imported metadata. `number` is not editable — the
  import matches on it. The patch carries the editor's original
  `supervisor_id` as `expected_supervisor_id`; a stale value returns 409
  naming the current supervisor and the UI reloads on dismiss. The status
  selector offers In-Progress from Created/Assigned (replacing the old
  standalone start action), rollback, and On-Hold; Review stays outside it.
  Created/Assigned is normalized from technician presence.
- Assigned-worker walkthrough (built on the clock, not status buttons): the
  seven-status lifecycle is created → assigned → in_progress →
  ready_to_complete → completed → review, with on_hold as the pause. Where
  `POST .../complete` ("Notify Supervisor") lands is the **caller's role**
  (`domain.work_orders.completion_target_status`): Supervisor+ reaches
  Completed; a Technician's finish lands **Ready to Complete** with a
  server-authored note, and Supervisor+ then Approve (PATCH completed) or
  Send Back (PATCH in_progress). Complete/hold stop every clock; resume
  starts none. These narrow routes require current assignment and grant no
  general status authority. Material/labor activity still auto-advances
  pre-work rows; tracking start rejects Ready to Complete and Completed.
- Notes: any in-scope user; the server prefixes Central `MM/DD/YY hh:MM AM/PM`
  and the author's full name; append-only (null cannot clear); the response
  returns the whole log. A Symptom/Task that is a safe HTTP(S) URL renders as
  an escaped link (`noopener noreferrer`).
- Tracking start/stop → work_order_labor_sessions (+ work_order_labor on
  stop). Start advances pre-work rows or resumes On-Hold and first closes the
  caller's clock on any other work order (that row auto-holds and notifies);
  stopping the last clock on an In-Progress row moves it to On-Hold and the
  card says so. Every close appends a `stopped work` note authored by the
  session's technician. Each response is the full refreshed detail.
- Manual labor (Supervisor+ only): whole minutes; the picker also offers the
  supervisor themselves. A Technician's labor card is read-only — hand entry
  is the supervisor's correction route for a missed clock. Entries show their
  session window; auto-capped ones are tagged "auto-stopped". Billing: sum
  minutes, round up once to 30 min, × $62.50/hr (rate/charge TechFM OA+ only).
- Admin Review: `apiListWorkOrders({status:"review"})` → receipt via
  `adminReviewReceipt.js` — override-aware material lines +15%, `[x] Labor
  Hours` from billed minutes with no second markup, 41-char lines via shared
  `pricingText.js`, no number header. Missing prices render `NO PRICE`, mark
  the total incomplete, and disable Close. Return to In-Progress is the same
  PATCH with `{status:"in_progress"}`.
- Archive (TechFM OA+, any live status) keeps rows/lines/transactions; Admin
  Review's Close uses the same endpoint. Restore is the undo, reached via
  `GET /work-orders/lookup?number=` — the one read that reports an archived
  row (History filter, or the TechFM OA+ exact search, which guards against
  stale lookups with a search-generation token). Owner-only legacy re-archive:
  preview count, then one atomic bulk update returning the actual affected
  count.
- Exports: `variant=full` applies every current live filter (the first seven
  columns are the import's own headers, so rows re-import cleanly);
  `variant=client` is scope-only with four columns — `WORK ORDER`,
  `MATERIAL TOTAL`, `LABOR TOTAL`, `RECEIPT` — whose billed totals sum to the
  receipt (`domain.receipt`, pinned to the frontend by
  `tests/test_receipt.py`). Filenames `MM-DD-YY_HH-MM_<filters>.csv` (UTC;
  `-` replaces the time colon).
- Materials: add (Technician+) may drive the expected count negative (recount
  request, red banner); qty update (Supervisor+) applies a reconciling
  `adjust` and clears a now-too-large billable override; delete (Supervisor+)
  returns stock, voids the line's whole contributing transaction set, and
  resolves linked requests.

### User Hub reads
- Day aggregation is **interval overlap** against the Central calendar day
  (`[00:00, 24:00)` `America/Chicago`, DST-correct via zoneinfo) — a session
  crossing midnight credits both days at real weight. Hand-entered labor (no
  session row) reports as an `Adjustments` line: counted in day totals, absent
  from the timeline, filed under the Central date of `created_at`.
- Hub minutes are **tracked** wall-clock minutes — never
  `capped_session_minutes` (floor 1, cap 720) and never
  `billed_labor_minutes`; no hub surface labels a billed figure "time worked".
- Assignment matching unions legacy `assigned_to_id` with
  `work_order_technicians` (the same pair `_scoped_to_user` uses), so hub
  counts and the Work Orders page cannot disagree. `HubCounts` are a total and
  two subsets, not three buckets.
- `GET /hub`, `/hub/crew`, `/hub/timesheets` are **not side-effect-free**:
  each sweeps stale sessions before reading (H1 for the caller; H2/H3 per
  crew member individually), bounded to ≤1 row per person by the partial
  unique index, idempotent, under the stop path's row lock. Sweeping never
  auto-holds, and a swept session still closes at `started_at + 720min`.
- Crew board: membership derives from routing — distinct technicians on
  non-archived work orders the caller supervises; the caller's own row is
  excluded from cards and `crew_minutes_today`. `last_worked` = most recent
  session `ended_at` (a running session has none and is excluded). Attention
  flags (`domain/hub.py`, pure): `long_session` >8 h, `approaching_cap` >11 h,
  `assigned_idle` (≥1 assigned, 0 minutes, past 10:00 AM Central),
  `stale_work_order` (in_progress/on_hold, 3 days without session activity);
  rendered icon + word, never color alone.
- Graphs: five membership-based community distributions, each nesting
  normalized service-type and raw-priority distributions, over every live
  status. Multi-location rows may match several communities; Academics is the
  no-community fallback (totals don't sum company-wide); a blank priority gets
  no card; a blank service type keeps its Unspecified bucket. Labels use the
  smallest raw spelling by code point, company-wide — the Work Orders
  dropdowns can select every one. Weekly duration buckets are Central Mon–Sun
  snapshots: circulating age = `snapshot − created_at`; close-out time =
  `archived_at − created_at`.
- `labor.session.changed` (audience Supervisor+) fires from both tracking
  routes after every clock start/stop with `id: null`; recipients refetch the
  crew board. See `docs/notification-events.md`.

### Mass staging / tools
- Stage delete cascades slots/items but never reverses dispenses. Reuse
  requires a completed source stage. Add-work-order **resolves** the number
  (404 if never imported) and enforces the building match. Slot/item edits are
  planning-only; load/return loading-only.
- Load allocates across the item's slot plans by `sort_order`, writing a
  per-slot dispense + line. Return caps at net loaded, reverse-fills, and adds
  stock back **with no transaction row** (the one deliberate silent stock
  change), reducing lines via `reduce_dispense_line`.
- Tool checkout requires an active target user; return is capped to that
  user's outstanding balance; adjust is absolute-target with a required reason
  and is the only way to raise a bulk tool's count. Tool barcodes are unique
  among live tools only — no archived-conflict/override flow, unlike items.

---

## Per-Table Index (who reads / who writes)

Quick reverse lookup: "which endpoints touch table X?"

| Table | Written by (endpoint #) | Read by (endpoint #) |
|-------|-------------------------|----------------------|
| `users` | 15, 16, 17, 18, 19, 58, 62 | 3, 5, 14, 20, 25–28 (assignee validation), 40, 55 (supervisor name-match), 59–61, 63–64, 68–69 |
| `sessions` | 3 (insert), 4 (delete), 17 (revoke), 19 (cascade), 62 (revoke) | every authenticated request (5 + all gated) |
| `items` | 8, 9, 10, 12, 21, 22, 24, 30, 31, 33, 45, 46 | 6, 7, 20, 26, 36, 63, 68 |
| `item_barcodes` | 8 (check), 11 | 7, 8 (uniqueness) |
| `transactions` | 21, 22, 23, 24, 30, 31, 33, 45 | 20, 24, 26 (self-heal) |
| `work_orders` | 21 (activity status), 28, 29, 40 (fill-blanks), 55 (import f-o-c), 59 (activity status), 67 (start) | 20–21, 25–29, 36, 40, 55, 59–61, 63–64, 67–68 |
| `work_order_items` | 21, 24, 30, 31, 32, 33, 45, 46 | 25, 26, 63 |
| `work_order_technicians` | 28, 40, 55 | 25, 26, 28, 59, 64 |
| `work_order_labor` | 59, 60, 61, 71a, 71b | 26, 60, 61, 63 |
| `work_order_labor_sessions` | 71a, 71b, 69, 70, 26 (PATCH into a stopping status), 64 (archive), 27 (lazy 12-hour cap on read) | 71a, 71b, 27, 69, 70 |
| `mass_stages` | 34, 37, 38, 39 | 35, 36 |
| `mass_stage_work_orders` | 40, 41 | 36 |
| `mass_stage_items` | 42, 43, 44, 45, 46 | 36 |
| `tools` | 47, 50, 51, 52, 53, 54 | 48, 49, 52, 53, 54 |
| `tool_transactions` | 52, 53, 54 | 48, 49, 53 (outstanding-balance check) |
| `user_requests` | 9 (price/link auto-resolve), 21 (shortage/unpriced), 24 (recount auto-resolve), 30/45 (unpriced), 69 | 68–69 |
| `push_subscriptions` | P2 (upsert/reassign), P3 (delete own), sends prune dead rows on 404/410 | P4 and the notify fan-outs (rows 69/70/71a/71b, NF6) |

f-o-c = find-or-create.

---

## Request / Response Contracts

Every wire shape, field by field. Types are Python/Pydantic; `?` = optional,
`=x` = default. "Validation" is what the schema rejects before the service runs.
Source: `app/schemas/*.py`.

### Auth (`schemas/auth.py`)

**`LoginRequest`** — body of `POST /auth/login`:
| Field | Type | Validation |
|-------|------|-----------|
| `username` | str | — |
| `password` | str | case-sensitive, not stripped |
| `remember` | bool=False | True ⇒ 12h-capped persistent session |

**`MeResponse`** — `POST /auth/login`, `GET /auth/me` return: `id: UUID`,
`username: str`, `first_name?`, `last_name?`, derived `full_name: str`,
`role: str`, `created_at: datetime`, `archived_at: datetime? = null` (the
timestamps feed the self-service custody card).

**`PasswordResetRequest`** — body of `POST /users/{id}/reset-password`:
`password: str` (≥ 4 chars, `MIN_PASSWORD_LENGTH`).

### Items (`schemas/items.py`)

**`ItemCreate`** — `POST /items/`:
| Field | Type | Validation |
|-------|------|-----------|
| `barcode` | str | uniqueness checked in service (cross-table) |
| `name` | str | — |
| `quantity` | Decimal=0 | ≥ 0 |
| `location` | str | non-blank (trimmed) |
| `price` | Decimal?=null | — |
| `product_link` | str?=null | — |
| `override_archived` | bool=False | confirm reuse of a barcode held by an archived item (see Error Catalog → 409) |

**`ItemUpdate`** — `PATCH /items/{id}` (partial): all of `barcode`, `name`,
`location`, `price`, `product_link` optional, plus `override_archived: bool=False`.
Rules: **≥ 1 real field required** (override flag alone doesn't count); `barcode`/
`name`/`location` are NOT NULL → sending them null/blank is rejected; `price`/
`product_link` sent as explicit `null` **clears** the column; **quantity is not
editable here** (use `POST /transactions/adjust`). Router forwards only sent
fields via `model_dump(exclude_unset=True)`.

**`ItemNotesUpdate`** — `PATCH /items/{id}/notes`: `notes: dict` (full replace),
validated by the notes whitelist (Domain Rules → Notes).

**`ItemBarcodesUpdate`** — `PATCH /items/{id}/barcodes`: `barcodes: list[str]`
(each trimmed, blanks dropped, in-list duplicate rejected) + `override_archived:
bool=False`. Full replace of *additional* codes only.

**`ItemResponse`** — any item return: `id`, `barcode`, `name`, `quantity`,
`location`, `notes: dict={}`, `barcodes: list[str]=[]` (additional codes),
`price?`, `product_link?`, `created_at`. **`price`/`product_link` are nulled
server-side below Admin** (`routers/items.py::_item_response`).

### Users (`schemas/users.py`)

**`UserCreate`** — `POST /users/`: `username`, `first_name`, and `last_name`
(all trimmed/non-blank), `password: str` (≥ 4), `role: str` (must be a recognized
role; whether the *caller* may assign it is checked in the router, not here).

**`UserNameUpdate`** — `PATCH /users/{id}/name`: required trimmed/non-blank
`first_name` + `last_name`, plus optional trimmed/non-blank `username`. The
target may be self or a subordinate; username uniqueness is enforced by the
database and a conflict returns 400.

**`UserRoleUpdate`** — `PATCH /users/{id}/role`: `role: str` (recognized role).
The TechFM OA+ router requires the actor to strictly outrank both the target's
current role and the requested role; a successful service update revokes the
target's sessions.

**`UserResponse`** — `id`, `username`, nullable `first_name`/`last_name`, derived
`full_name`, `role`, `created_at`, `archived_at?` (null = active). Password hash
is never serialized. Legacy NULL names derive to `Name unavailable`.

### Transactions & History (`schemas/transactions.py`)

**`TransactionCreate`** — `POST /transactions/`: `item_id: UUID`,
`transaction_type: "stock"|"dispense"` (literal; `adjust` is a separate route),
`quantity: Decimal` (> 0), `work_order_number: str?=null`, `work_order_id: UUID?=null`.

**`CorrectionCreate`** — `POST /transactions/adjust`: `item_id: UUID`,
`new_quantity: Decimal` (≥ 0; **absolute** target, service computes signed delta),
`reason: str` (non-blank).

**`BillingUpdate`** — `PATCH /transactions/{id}/billing`: `billable_quantity:
Decimal?=null` (bounds enforced in `domain.billing`).

**`TransactionResponse`** — create/adjust/billing return: `id`, `item_id`,
`user_id?`, `transaction_type`, `quantity`, `billable_quantity?`,
`work_order_number?`, `reason?`, `created_at`, plus immediate-write fields
`recount_required: bool=false` and `item_quantity?` (authoritative post-write
expected stock; may be negative for an insufficient Scan/Stock or Work Orders
Add Item dispense).

**`TransactionHistoryItem`** — each row of `GET /transactions/`: `id`, `item_id`,
`item_barcode`, `item_name`, `user_id?`, `user_name?`, `transaction_type`,
`quantity`, `work_order_number?`, `work_order_id?`, `reason?`, `item_price?`,
`billable_quantity?`, `created_at`. `item_price`/`billable_quantity` are Admin/
Owner-only **and null for work-order rows** (they bill via the line); `work_order_id`
is always present (lets the copy-table resolve the work order). **`TransactionHistoryPage`**:
`items: list[...]`, `total: int`, `page: int`, `page_size: int`.

### User Requests (`schemas/user_requests.py`)

**`UserRequestUpdate`** — `PATCH /user-requests/{id}`: `status:
"open"|"resolved"?=null`, `resolution_note: str?=null` (trimmed; blank becomes
null), `message: str?=null` (trimmed), `details: dict?=null`. All optional, but
at least one of `status`/`message`/`details` is required. `details` keys are
whitelisted per request type by `EDITABLE_DETAILS`; a recount's frozen audit
numbers are not on any list and a rejected key returns 409.

**`ItemRequestCreate`** — `POST /user-requests/item-request`: `searched_text:
str` (1–200, trimmed), `quantity: Decimal=1` (>0), `note: str?=null` (≤500,
trimmed), `work_order_id: UUID?=null`, `source: "work_orders"|"find_item"`.

**`NewItemPayload`** — the Add Item fields for creating the catalogue row inline:
`barcode`, `name`, `location` (all non-blank), `quantity: Decimal=0` (≥0),
`price: Decimal?=null`, `product_link: str?=null`, `override_archived:
bool=false`.

**`ItemRequestFulfill`** — `POST /user-requests/{id}/fulfill`: `item_id: UUID?`
XOR `new_item: NewItemPayload?` (exactly one, enforced by a model validator),
`sibling_ids: list[UUID]=[]` — the other open requests the admin **confirmed**
name the same material.

**`UserRequestResponse`** — `id`, `request_type`, `status`, `message`, nullable
`item_id`/`item_name`/`item_barcode`/`item_price`/`item_product_link`,
`transaction_id`, `work_order_id`/
`work_order_number`, `created_by_id`/`created_by_name`, generic `details: dict`,
`created_at`, nullable `resolved_at`, `resolved_by_id`/`resolved_by_name`, and
`resolution_note`. The list endpoint returns `list[UserRequestResponse]` and
requires `status=open|resolved` (default `open`).

### Barcodes (`schemas/barcodes.py`)

Request is `multipart/form-data` file upload (FastAPI `UploadFile`), no JSON body,
capped at **10 MB** by `routers/_uploads.py::read_capped` (413 above it, before
Pillow sees the bytes). **`BarcodeDecodeResponse`**: `barcodes: list[BarcodeMatch]`,
each `BarcodeMatch = { text: str, format: str }`. Empty list = readable image, no
symbol (200); an unreadable image is a 400.

### Work Orders (`schemas/work_orders.py`)

There is no `WorkOrderCreate`: work orders are import-only, so the CSV upload is
the only request that can bring one into existence.

**List query** — `GET /work-orders/`: optional `status`, `service_type`,
`supervisor_id`, `community`, `priority`, `scheduled_date` (ISO calendar date),
`q`, and
`limit`. All filters combine with AND;
`service_type` is an exact trimmed case-insensitive match, `q` is a literal
case-insensitive number substring, and community values are `scholars`,
`centennial`, `commons`, `young_hall`, or `academics`. `priority` is an exact
trimmed case-insensitive match against raw vendor text, so unlike `community` it
has no fixed vocabulary and an unrecognized value filters on itself rather than
returning 400; the sentinel `__none__` selects the work orders whose priority is
NULL or blank — the ones NetFacilities enrichment never reached.

**`WorkOrderFilterOptions`** — return of `GET /work-orders/filter-options`:
`service_types: list[str]`, `priorities: list[str]`,
`supervisors: list[{id, name}]`, and
`communities: list[{value, label}]`. Dynamic values come only from live work
orders visible to the caller; the community vocabulary is stable. `service_types`
and `priorities` collapse values differing only in case or padding, keeping the
lowest-code-point spelling so the choices do not reshuffle between requests.
`priorities` omits the blank/NULL group; the page appends its own "Not imported"
choice carrying `__none__`.

**CSV export query** — `GET /work-orders/export`: `scope=all|archived|<live
status>` and `variant=full|client`; optional `service_type`, `supervisor_id`,
`community`, `priority`, `scheduled_date`, and `q` are applied only to `full`.
Invalid values
return 400. The response is a UTF-8 `text/csv` attachment, not a Pydantic
response. `full` leads with the seven import headers and adds status,
assignments, billing totals, and timestamps. `client` remains scope-only and
returns `WORK ORDER`, `MATERIAL TOTAL`, `LABOR TOTAL`, and `RECEIPT`.

**`WorkOrderUpdate`** — `PATCH /work-orders/{id}` (partial, overwrite): `number?`,
`community?`, `building_number?`, `unit_number?`, `description?`, `notes?`, `status?`,
`entry_mode?`, `assigned_to_ids?` (complete replacement; empty clears).
`assigned_to_id?` remains a legacy-compatible singular alternative. ≥ 1 field
required; `status`/`entry_mode`
validated in the service. Live statuses are `created`, `assigned`,
`in_progress`, `on_hold`, `ready_to_complete`, `completed`, and `review`;
Closed is `archived_at`, not a PATCH value. A PATCH into `on_hold`,
`ready_to_complete`, or `completed` stops every running clock; the general
selector does not offer `ready_to_complete` (reached by a Technician's
complete action only).
Notes are trimmed per-entry text; every in-scope user may append one. The
service supplies timestamp/date/author metadata and preserves the prior log.
`status`, `entry_mode`, supervisor, and technician assignment require
Supervisor+; imported/legacy text metadata and number require TechFM OA+. A Review
status is accepted only while the stored row is Completed and only from TechFM OA+
or its routed Supervisor when the caller is not an assigned worker.
`supervisor_id` may target an active Admin or Supervisor; `assigned_to_ids` may
contain active Technician or Supervisor accounts (including the acting
Supervisor). Owners retain global authority but are not assignment targets.
`supervisor_id?` may be paired with `expected_supervisor_id?`, including an
explicit NULL expectation for pickup. The expectation is a concurrency
precondition, not a stored field and not an update by itself.

**`WorkOrderLookup`** — return of `GET /work-orders/lookup?number=`: `found: bool`,
`archived: bool`, `id: UUID?`, `number: str?`. Deliberately reports an *archived*
work order (which the list and detail routes hide) so History can offer a restore;
a work order the caller may not see reports `found=false`.

**`LegacyWorkOrderArchivePreview`** — return of Owner-only
`GET /work-orders/legacy/archive`: `count: int`, the number of rows currently
matching `legacy=true AND archived_at IS NULL`.

**`LegacyWorkOrderArchiveResult`** — return of Owner-only
`POST /work-orders/legacy/archive`: `archived: int`, the bulk update's actual
affected-row count (not a replay of the earlier preview).

**`WorkOrderAutoClosePending`** — return of TechFM OA+
`GET /work-orders/auto-close/pending`: `closed_count: int`, `batch_count: int`,
`newest_ran_at`, `oldest_ran_at` (datetimes) — or **`null`** when nothing is
pending, which is what hides the Integrations page's "Undo auto-close" button.
The set is company-wide and covers every sweep still inside the 24-hour window,
so `batch_count` can exceed one when two imports ran the same day.

**`WorkOrderAutoCloseUndoResult`** — return of TechFM OA+
`POST /work-orders/auto-close/undo`: `restored: int`, the number actually
un-archived. Can be lower than a count read a moment earlier if rows were
restored by hand or reopened by a later import in between. Nothing pending is
`200 {"restored": 0}`, not an error.

**`WorkOrderItemCreate`** — `POST .../items`: `item_id: UUID`, `quantity: Decimal`
(> 0). **`WorkOrderItemUpdate`** — `PATCH .../items/{wid}`: `quantity: Decimal`
(> 0). **`WorkOrderItemBilling`** — `PATCH .../items/{wid}/billing`:
`billable_quantity: Decimal?=null` (≥ 0; upper bound vs line quantity enforced in
service).

**`WorkOrderLaborCreate`** — `POST .../labor`: `technician_id: UUID`,
`minutes: int` (> 0). **`WorkOrderLaborUpdate`** — `PATCH
.../labor/{labor_id}`: `minutes: int` (> 0). **`WorkOrderLaborDetail`**:
`id`, `technician_id`, `technician_name`, `minutes`.

**`WorkOrderCard`** — list rows: `id`, `number`, `community?`, `building_number?`,
`unit_number?`, `description?`, `priority?`, `status`, `entry_mode`, `created_by_id?`,
`assigned_to_id?`, `assigned_to_name?` (compatibility primary),
`assigned_to_ids`, `assigned_to_names`, `item_count`, plus the CSV-import
fields `location?`, `output_to?`, `vendor_assignee?`, `service_type?`,
`schedule_date?`, `supervisor_id?`, `supervisor_name?`, and `legacy` (bool).
`WorkOrderUpdate` additionally accepts `supervisor_id` and those text fields.
The service applies the Technician-notes / Supervisor-operations / Admin-metadata
matrix. **`WorkOrderImportResult`** (return of
`POST /work-orders/import`): `total`, `created`, `opened`, `closed`, `supervisors_matched`,
`supervisors_unmatched`, `skipped`, `auto_closed`, `reopened` (all int).
`auto_closed` are live work orders the import closed because the CSV did not
list them; `reopened` are sweep-closed work orders it brought back because the
CSV listed them again. `total` includes `reopened` but not `auto_closed` — a
swept work order is by definition one the CSV did not contain. The request is a `multipart/form-data`
CSV file upload (`UploadFile`), no JSON body, capped at **25 MB** by
`routers/_uploads.py::read_capped` (413 above it; the TechFM OA+ gate resolves
before the form body is read, so an unauthorised oversized upload is 403). **`WorkOrderItemDetail`**:
`id`, `item_id`, `item_name`, `item_barcode`, `item_quantity` (live on-hand),
`quantity`, `mode`, `unit_price?`, `billable_quantity?` (last two TechFM OA and above-only).
**`WorkOrderDetail`** = `WorkOrderCard` + `notes: str?` +
`items: list[WorkOrderItemDetail]` + `labor: list[WorkOrderLaborDetail]` +
`labor_minutes` + `labor_billed_minutes` + `materials_total?` (TechFM OA and above; Σ
`effective_billable × unit_price`) + `labor_rate?` / `labor_total?`
(TechFM OA and above; fixed rate after combined-duration rounding).

### NetFacilities (`schemas/netfacilities.py`)

All six routes are TechFM OA+; cloud auth is the only path.
**`NetFacilitiesEnrichmentJob`** returns `job_id`, one of
`queued|running|completed|authentication_required|timed_out|failed|cancelled`, optional
UTC `started_at` / `finished_at`, optional safe `failure`, optional aggregate
`counts`, and `source` -- now `cloud_session` only. Counts contain
candidate/request/fetch/update/unchanged/failure/remaining
integers and `timed_out`; no work-order number or source value is returned.

Start has no request body. It returns 202, including for a duplicate that resolves to
the active job; a caller with no saved cloud session is 409 and disabled/unavailable
capability is 503. Polling accepts only the UUID path parameter and returns 404 after a
process restart or when the id is not the coordinator's latest job.

**`NetFacilitiesCloudCapability`** (NF5) returns `available`, a secret-safe `message`,
`has_saved_session` (a persisted row exists, independent of any live ceremony), and
optional `status` — the calling user's own state, never another user's.
**`NetFacilitiesCloudSessionStatus`** carries an attempt ID, lifecycle state,
timestamps, a safe failure class, and `last_download_filename` / `last_download_at`
(filename only, naming the CSV most recently captured from the window), plus
`live_view_url` while a ceremony is open — Steel's `debug_url`
(a bare WebRTC session player), never `session_viewer_url` (account-gated; only
`debug_url` renders an interactive view without a Steel login). Lifecycle states are
`starting|awaiting_sign_in|signed_in|closed|failed|cancelled|timed_out` — there is no
manual-confirm state, since the ceremony auto-polls with no confirm click. Neither
schema, nor any other NetFacilities response, ever carries `storage_state` or
`steel_profile_id`.

`POST /cloud/downloads/import` has no request body and returns `WorkOrderImportResult`
(the upload route's schema). 409 when no CSV has been captured for that user in this
process; `DomainError`s map exactly as on the upload route.

### Real-time (`domain/realtime.py` — no Pydantic schema)

`/ws` is the one operation with no request or response *body*. It has no
`schemas/` module because nothing is parsed from a client: the socket is
**server→client only**. There is no application-level inbound vocabulary — Uvicorn
owns protocol ping/pong, and application frames within the size limit are
*ignored* rather than rejected, so adding a client→server message later is an
additive change. The socket never mutates anything (P3, permanent).

**Server→client envelope** — exactly three keys, always:

| Key | Type | Meaning |
|---|---|---|
| `type` | `str` | event name — one of the three in the vocabulary table below |
| `id` | `str \| null` | the affected work-order UUID, or `null` for collection/membership commands (CSV import, bulk legacy archive, restore, auto-close undo — and always for `labor.session.changed`) |
| `req` | `str` | the 12-hex request id of the HTTP write that caused it, copied from `logging_config.current_request_id()` so the socket event stays on the causal trace |

The envelope deliberately carries **no row data and no actor**. It is a cache
invalidation, not a data feed: the client refetches over REST, so there is no
second serialization path to keep in agreement with the REST contract, and no
authorization decision is embedded in the message. Audience is enforced
server-side at send time (`domain/realtime.audience_allows`); it is delivery
policy, not a security boundary — the envelope has nothing to leak, and an
out-of-scope refetch returns nothing.

**Event vocabulary and emitters** — three types, all emitted after the
mutating service returns. `test_realtime_emit.py` pins each emitter set; a new
route that can change what a subscriber shows must join the right set
deliberately:

| Event | Audience | Emitters | Subscribers |
|---|---|---|---|
| `work_order.review_queue.changed` | TechFM OA+ | import, bulk legacy archive, update, archive, restore, auto-close undo | `adminReview.js` |
| `work_order.status.changed` | any role | those six plus start, complete, hold, resume, tracking start/stop — card **summary** invalidation (status/assignee/item count); tracking start also emits for a side-transitioned row | `workOrders.js`, `userHub.js` |
| `labor.session.changed` | Supervisor+ | exactly the two tracking routes; always `id: null` | `userHub.js` (crew board) |

Materials, billing, and manual-labor CRUD deliberately emit **nothing** — no
consumer refreshes an open card body.

**Failure behavior** — emission is non-blocking and best-effort. A saturated
handoff drops and counts the newest invalidation and never fails the durable
HTTP write. REST remains the source of truth.

**Handshake refusals are HTTP, not close codes.** Close codes only exist after
`accept()`, and Starlette maps a pre-accept `close()` to a bare HTTP 403, so a
foreign origin, an unresolvable session, and a user at capacity are all refused
before acceptance with explicit statuses instead: **401** for auth, **429 +
`Retry-After`** for the handshake-attempt limit, and **429 without
`Retry-After`** for the per-user cap — capacity is not a timed limit, so there
is no honest retry interval to give. Policy constants (6 connections/user,
10 handshakes/60s, 20 inbound frames/s, 64 KiB frame ceiling) live in
`domain/realtime.py`.

### Mass Stages (`schemas/mass_stages.py`)

**`MassStageCreate`** — `POST /mass-stages/`: `community: str`, `building_name: str`
(holds the building *number*); both non-blank. **`MassStageUpdate`** — `PATCH
/mass-stages/{id}`: `community?`, `building_name?`, `status?`; ≥ 1 required.
**`StageWorkOrderCreate`** — add slot: `work_order_number: str` (non-blank),
`unit_number?`, `assigned_to_id?`. **`StageItemCreate`** / **`StageItemUpdate`**:
`item_id`, `planned_quantity: Decimal` (> 0). **`LoadRequest`** / **`ReturnRequest`**:
`item_id: UUID`, `quantity: Decimal` (> 0).

Responses: **`MassStageSummary`** (list card): `id`, `community`, `building_name`,
`status`, `unit_count` (slots), `item_count` (distinct items), `created_at`.
**`MassStageDetail`**: + `work_orders: list[StageWorkOrderDetail]` +
`merged_items: list[MergedItem]`. **`StageWorkOrderDetail`** (a slot): `id` (slot
id), `work_order_id`, `work_order_number`, `unit_number?`, `status`, `sort_order`,
`assigned_to_id?`, `assigned_to_name?`, `items: list[StageItemDetail]`.
**`StageItemDetail`**: `id`, `item_id`, `item_name`, `item_barcode`,
`item_quantity` (on-hand), `planned_quantity`, `loaded_quantity`,
`returned_quantity`. **`MergedItem`** (per-item rollup for the load screen):
`item_id`, `item_name`, `item_barcode`, `on_hand`, `planned_total`,
`loaded_total`, `returned_total`, `overflow` (loaded beyond planned),
`net_consumed` (loaded − returned), `remaining_to_load` (planned − loaded).

### Tools (`schemas/tools.py`)

**`ToolCreate`** — `POST /tools/`: `barcode: str` (non-blank, trimmed),
`name: str` (non-blank, trimmed), `quantity: Decimal = 1` (≥ 0 — defaults to
1, not 0 like `ItemCreate`, since a tool is usually added because you have
one in hand).

**`ToolUpdate`** — `PATCH /tools/{id}` (partial): `barcode?`, `name?`; ≥ 1
field required, non-blank if sent. `quantity` is NOT editable here — only
via checkout/return.

**`ToolCustodyEntry`**: `user_id`, `user_name`, `quantity` — one user's current
outstanding balance for a tool (net > 0). Login usernames are omitted.

**`ToolResponse`** — any tool return: `id`, `barcode`, `name`, `quantity`,
`created_at`, `custody: list[ToolCustodyEntry] = []`. `custody` is
computed (`services.tools.tool_custody`) and set explicitly by the router,
not an ORM-mapped field — mirrors `ItemResponse.barcodes`.

**`ToolCheckoutCreate`** / **`ToolReturnCreate`** — same shape: `quantity:
Decimal` (> 0), `assigned_to_id: UUID` (required — the custody holder),
`work_order_id: UUID? = null`, `work_order_number: str? = null` (optional,
never required; no find-or-create — stored as-is).

**`ToolAdjustCreate`** — `POST /tools/{id}/adjust` ("Correct Count",
mirrors `CorrectionCreate`): `new_quantity: Decimal` (≥ 0, **absolute**
target — the service computes the signed delta), `reason: str` (non-blank).
No custody holder involved.

### User Hub (`schemas/hub.py`)

**`HubResponse`** — `GET /hub` (any authenticated role): `user: HubUser`,
`server_now: datetime`, `day: date` (Central), `clock: HubClock`,
`timeline: list[HubTimelineEntry] = []`, `counts: HubCounts`,
`startable: list[HubStartable] = []`, `tools_out: list[HubToolOut] = []`.
`server_now` is the client's clock-skew anchor — it records
`skew = server_now − Date.now()` at fetch time and renders elapsed against
it, so a field phone with a wrong system clock still shows the right number.

**`HubUser`**: `id`, `first_name?`, `last_name?`, `role`. Deliberately not the
full user record — no username, no timestamps; the hub needs an identity, not
an account.

**`HubClock`**: `running_session: HubRunningSession? = null`,
`closed_minutes_today: int`, `running_minutes_today: int`,
`adjustment_minutes_today: int`, `adjustments: list[HubAdjustment] = []`, and
a computed `total_minutes_today` = the sum of the three. Anchors, not a
ticking number: the server sends what is fixed and the client renders the live
figure on a 1-second interval, so nothing polls for a value that changes once
a minute. **`total_minutes_today` includes adjustments** — one number means
one thing on every surface, and the tracked/adjusted split is one expand away.

**`HubRunningSession`**: `work_order_id`, `number`, `started_at`,
`day_counting_from`. **Two anchors, and they are not interchangeable.**
`started_at` drives the widget's session elapsed ("started 8:12 AM");
`day_counting_from` drives *today's* total and equals midnight Central for a
clock inherited from yesterday. Ticking the day total from `started_at` would
report an hour for a session that has given today thirty minutes.

**`HubTimelineEntry`**: `work_order_id`, `number`, `started_at`, `ended_at?`,
`auto_closed: bool`, `minutes: int`. `minutes` is that session's share of
**this** day, so a midnight crossing appears on both days at its real weight
and is not `ended_at − started_at`. `auto_closed` marks a session the 12-hour
cap ended — an estimate a supervisor should correct, not a fact. A session
that only touches the day (a stop at exactly midnight) is omitted.

**`HubAdjustment`**: `minutes`, `recorded_by_name` (`"Name unavailable"` when
the recorder is unset), `work_order_number`.

**`HubCounts`**: `assigned`, `in_progress`, `ready_to_complete` — a **total and
two subsets of it**. `assigned` is every non-archived work order the caller is
an assigned technician on, whatever its status; the other two count members of
that same set. "8 assigned, 1 in progress, 2 ready" describes 8 work orders,
not 11.

**`HubStartable`**: `work_order_id`, `number`, `status`, `community?`,
`building_number?`, `unit_number?`, `location?` — one option in the
`Start on…` picker, limited to `work_orders.TRACKING_START_STATUSES` so the
picker can never offer a row `start_labor_session` would refuse. Ordered
In-Progress → On-Hold → Assigned → Created, then by number. Place fields are
raw; `static/views/workOrders.js::placeMeta` composes them, so one composer
owns every address in the app.

**`HubToolOut`**: `tool_id`, `name`, `barcode`, `quantity: Decimal`,
`since: datetime?` — oldest spell first.

**`HubCrewResponse`** — `GET /hub/crew` (supervisor+): `server_now: datetime`,
`led: HubLedCounts`, `crew_on_clock: int`, `crew_total: int`,
`crew_minutes_today: int`, `technicians: list[HubCrewTechnician] = []`,
`attention: list[HubAttentionItem] = []`. Minutes only — cost figures stay
redacted below TechFM OA per the existing role rule; nothing here needs one.

**`HubLedCounts`**: `total`, `in_progress`, `ready_to_complete` — a total and
two subsets of the work orders this supervisor leads, same convention as
`HubCounts`.

**`HubCrewTechnician`**: `user: HubUser`, `running_session: HubRunningSession?
= null`, `minutes_today: int`, `assigned`, `in_progress`,
`ready_to_complete`, `last_worked: datetime? = null`, `flags: list[str] = []`.
`flags` is drawn from `domain/hub.py`'s vocabulary
(`long_session`/`approaching_cap`/`assigned_idle`); rendered as icon + word.

**`HubAttentionItem`**: `kind` (`"technician"` | `"work_order"`), `subject`,
`detail` — a server-composed sentence, matching spec §7's abbreviated
`{kind, subject, detail}` contract for this list.

**`HubReportResponse`** — `GET /hub/report` (**admin only** — the one route in
this app floored at Admin, which `tests/test_route_role_gates.py` records as a
deliberate exemption). Parameterless: both windows are derived from server time
via `domain/labor_day.py`. `day` is the Central calendar day; `week` is the
Monday–Sunday week containing it, labelled in full but evaluated **week-to-date**,
so This Week always *includes* Today. `sections` carries five keys —
`closed_today`, `closed_week` (`archived_at` windows minus sweep closes;
`auto_closed_count` = closes left out), `closing` (live rows in `ready_to_complete` / `completed` /
`review`, with `by_status` and `truncated`), and `new_today`, `new_week`
(`created_at` windows). Rows nest: a work order closed today appears in both
`closed_*` sections. `closing` is the only capped section
(`list=hub_report_closing`); its `count` and `by_status` stay true when the cap
bites. `GET /hub/report/export` serializes the same payload as an `.xlsx` workbook
(`work_order_report_xlsx.report_xlsx`, styled by `_xlsx_theme`): a `Report`
overview (KPI strip, company four-bucket pie, activity, dollars, by-community
table), one chart sheet per community (status pie plus a 3×3 service-type
grid over the same four buckets — Accepted / In progress / Ready to close /
Closed, `work_order_report_buckets.REPORT_BUCKETS`), a deduped `Work Orders`
sheet (Notes in column C) over the live-plus-closed-this-week population
(`DailyReport.all_rows`, uncapped), and — last, after a hidden `Chart Data`
sheet — a `Data` sheet that is the `SECTION`-prefixed CSV cell for cell —
header `SECTION` + the 26 `EXPORT_HEADERS` — so a save-as-CSV from Excel still
re-imports through `POST /work-orders/import`. `distribution` and `all_rows`
are not in the JSON response. **A live view, not an archival record:** a restore
clears `archived_at`, so a past close can vanish from these numbers.

**`HubTimesheetResponse`** — `GET /hub/timesheets` (supervisor+; P3b scopes
every caller to their own routed crew): `range: HubTimesheetRange`, `rows:
list[HubTimesheetRow] = []`, and `crew_totals_by_day:
list[HubTimesheetDayTotal] = []`. The range is inclusive Central calendar
dates, defaults to the current Monday–Sunday week, and is capped at 92 days.
The two range-spanning source queries use `MAX_LIST_ROWS` and emit the shared
`list.truncated` warning if that ceiling bites.

**`HubTimesheetRow`**: `user: HubUser`, `days: list[HubTimesheetDay]`, and
`total_minutes`. **`HubTimesheetDay`** carries `date`, `tracked_minutes`,
`adjustment_minutes`, computed `total_minutes`, `flags`, and the session plus
adjustment rows used by the inline drill-down. D15 applies at every level:
cell, row, crew, and CSV totals all include adjustments. `running` marks a
cell with an open clock; `assigned_idle` is never applied to a future day.

**`HubTimesheetDayTotal`**: `date`, `minutes` — the adjustment-aware crew
sum for one day. `GET /hub/timesheets/export` serializes the same payload as
`H:MM` CSV named `timesheet_<start>_to_<end>[_<user>].csv`.

---

## Error Catalog

Every `DomainError` subclass, its HTTP status (`routers/_errors.py::_STATUS_MAP`),
and the condition that raises it. Routers catch `DomainError` and call
`to_http(exc)`; an unmapped subclass defaults to **400**. `NegativeQuantityError`'s
user message is overridden to `"Insufficient stock to dispense."`. Unmapped
non-domain exceptions become FastAPI's default 500.

| Exception | HTTP | Raised when |
|-----------|------|-------------|
| `ItemNotFoundError` | 404 | item id/barcode unknown, or archived on a barcode lookup |
| `UserNotFoundError` | 404 | user id unknown; tool checkout also uses it when the target is archived (not an active checkout target) |
| `TransactionNotFoundError` | 404 | txn id unknown or already voided |
| `UserRequestNotFoundError` | 404 | user-request id unknown |
| `ItemRequestStateError` | 409 | fulfilling something that is not an open item request, or editing a `details` key the request's type does not expose (notably a recount's frozen audit numbers) |
| `StageNotFoundError` | 404 | mass-stage id unknown |
| `RoomNotFoundError` | 404 | stage **slot** not found / not in the stage (name retains old "room") |
| `StageItemNotFoundError` | 404 | planned stage item not found (incl. loading an unplanned item) |
| `WorkOrderNotFoundError` | 404 | work order unknown, archived, or **out of visibility scope** (404 hides existence) |
| `WorkOrderAssignmentConflictError` | **409** | a routing patch's `expected_supervisor_id` differs from the freshly locked row; names its current supervisor when assigned |
| `WorkOrderStateError` | 400 | invalid live status/mode, assigned-worker completion/hold outside In-Progress, assigned-worker resume outside On-Hold, Review before Completed, or number collision on edit |
| `ToolNotFoundError` | 404 | tool id/barcode unknown or archived |
| `DuplicateToolBarcodeError` | 400 | barcode held by a **live** tool (no archived-conflict/override flow, unlike items) |
| `ToolReturnExceedsCheckedOutError` | 400 | return quantity exceeds that user's current outstanding balance for the tool |
| `ToolHasOutstandingCustodyError` | 400 | archiving a tool while any user still has a positive outstanding balance |
| `TimesheetRangeInvalidError` | 400 | a timesheet range ends before it starts |
| `TimesheetRangeTooLargeError` | **422** | an inclusive timesheet range exceeds 92 days |
| `DuplicateBarcodeError` | 400 | barcode held by a **live** item (primary or additional) |
| `ArchivedBarcodeConflictError` | **409** | barcode held only by an **archived** item; retry with `override_archived=true` |
| `DuplicateUsernameError` | 400 | username UNIQUE constraint fired |
| `DuplicateBuildingStageError` | 400 | a (community, building) already has an active stage |
| `InvalidStageTransitionError` | 400 | stage status move not `planning→loading→completed` |
| `InvalidAssigneeError` | 400 | work-order worker missing, archived, or not a Technician/Supervisor |
| `InvalidSupervisorError` | 400 | work-order routing target missing, archived, or not an Admin/Supervisor |
| `ReturnExceedsLoadedError` | 400 | mass-stage return > net loaded |
| `StageStateError` | 400 | mass-stage op illegal for current status (edit after planning, load before loading) |
| `ItemHasTransactionsError` | 400 | hard-deleting an item with txns/stage rows (FK RESTRICT) |
| `UserHasTransactionsError` | 400 | hard-deleting a user referenced by txns (FK RESTRICT) |
| `UserHasCheckedOutToolsError` | 400 | archiving a user before all outstanding tool custody is returned |
| `NegativeQuantityError` | 400 | a strict stock path (Work Order quantity edit, Mass Stage, correction, or reverse) would drive on-hand < 0; Scan/Stock and Work Orders Add Item dispenses deliberately bypass this and open recount requests |
| `NoChangeError` | 400 | correction `new_quantity` equals current (empty audit row) |
| `BillingQuantityError` | 400 | billing override negative, > recorded qty, or targets an `adjust` |
| `TransactionVoidError` | 400 | voiding would drive stock < 0 ("make a correction instead") |
| `UnreadableImageError` | 400 | uploaded bytes are not a decodable image |
| `InvalidCredentialsError` | **401** | bad username/password **or archived user** (indistinguishable) |
| `RoleManagementError` | **403** | actor fails a role/ownership gate, including unassigned completion, assigned-worker Review, or a Technician removing a transaction other than their own work-order-linked dispense |

Auth/gate errors are raised directly by `auth_deps.py` (not `DomainError`): **401**
no/invalid/expired session (`get_current_user`); **403** valid session but role too
low (`require_min_role`).

`auth_deps.py:73` is the **only** place in the app that raises a role 403,
with one deliberate exception: `routers/transactions.py:55`
gates `POST /transactions/` on `can_transact(role, transaction_type)`, which
needs the parsed body because a stock and a dispense are the same route with
different minimums. Everything else uses `Depends(require_min_role(...))`. The
eight gated routes in `routers/work_orders.py` additionally declare
`responses={403: ...}`, so the gate appears in the schema — FastAPI does not
infer a 403 from a dependency that is merely able to raise one. On
`PATCH /work-orders/{id}/items/{wid}/billing` the dependency resolves before
Pydantic, so a request that is both malformed and unauthorized answers **403,
not 422**.

**429 has two independent sources and neither is a `DomainError` route error.**
`routers/auth.py` returns one on `POST /auth/login` when the login backoff is
engaged (`LoginThrottledError`, mapped in `_STATUS_MAP` as a safety net but
handled directly so it can carry `Retry-After`). The `rate_limit`
middleware in `main.py` returns the other on **any** non-exempt path, before
routing, when one caller exceeds 60 requests/second — so a 429 can appear on a
route whose OpenAPI `responses` do not mention it, including a 404 path. Exempt:
`/`, `/static/*`, `/healthz`. Both carry `Retry-After` in whole seconds.

Upload size is also raised directly, by `routers/_uploads.py::read_capped` (not a
`DomainError` — a byte cap is a transport limit, not a business rule, so it stays
out of the framework-agnostic `domain/errors.py`): **413** on
`POST /barcodes/decode` over 10 MB and `POST /work-orders/import` over 25 MB, with
`detail` naming the limit. Both routes declare it in their OpenAPI `responses`. On
the import route the TechFM OA+ gate runs first, so an unauthorised oversized upload is
a 403. Note: a few error class names (`RoomNotFoundError`,
`DuplicateBuildingStageError`) and their docstrings retain pre-rebuild "room"/
"building" wording but now apply to work-order slots / (community, building) stages.

---

## Domain Rules Quick Reference

Pure functions (no DB) in `domain/*.py` — the business rules, testable in isolation.

### Roles (`domain/roles.py`)
- Ranks: `technician 0 < supervisor 1 < techfm_oa 2 < admin 3 < owner 4`. Unknown
  role → rank −1.
- `role_at_least(role, min)` — the route-gate primitive (`>=` on rank).
- `can_be_work_order_supervisor(role)` — true for TechFM OA, Admin, and Supervisor.
- `label(role)` / `ROLE_LABELS` — display names; "TechFM OA" is not derivable by
  capitalising its slug, so UI copy and OpenAPI 403 descriptions read from here.
- TechFM OA holds the Admin toolkit minus two things, both consequences of its
  rank: it fails `role_at_least(role, ROLE_ADMIN)`, which is the Review handoff
  floor, and `can_manage` is false against Admin and Owner.
- `can_be_work_order_technician(role)` — true only for Supervisor and Technician.
  These assignment predicates intentionally exclude Owner despite Owner's global
  authority.
- `can_transact(role, type)` — `dispense`: any valid role; `stock`: supervisor+; else False.
- `can_manage(actor, target)` — actor rank **strictly >** target rank (so no one
  manages their own level or an owner).
- `assignable_roles(actor)` — every role ranked strictly below the actor.

### Stock arithmetic (`domain/quantity.py`)
- `apply_delta(current, type, qty)`: `stock` → `current+qty`; `dispense` →
  `current−qty` (raise `NegativeQuantityError` if < 0); `adjust` → `current+qty`
  (signed; same < 0 guard). Inputs assumed pre-validated.
- `services.transactions.apply_transaction` and
  `services.work_orders.add_work_order_item` are the intentional exceptions:
  Scan/Stock and Work Orders Add Item `dispense` operations subtract under the
  item-row lock even when the result is negative, then record a recount
  request. Work Order quantity edits and Mass Stage stock-outs continue to call
  strict `apply_delta`.
- `reverse_delta(current, type, qty)` (for void): undo `stock` = dispense, undo
  `dispense` = stock, undo `adjust` = apply negated delta. Same overdraft guard.

### Notes whitelist (`domain/notes_validation.py`)
- `notes` is a flat dict: keys non-blank strings (trimmed); values exactly one of
  `str | int | float | bool`. **`bool` checked before `int`** (bool subclasses int).
  Nested objects/arrays/None/other → `ValueError`.

### Work-order rules (`domain/work_orders.py`)
- Identity: `normalize_number(n) = n.strip().lower()` — mirrors the DB index
  `lower(btrim(number))`. Internal whitespace preserved.
- Stored/live statuses: `created`, `assigned`, `in_progress`, `on_hold`,
  `ready_to_complete`, `completed`, `review`; Closed is archive state.
  `completion_target_status(role)`: Supervisor+ → completed, Technician →
  ready_to_complete. `initial_status(assigned_to_id)` and
  `reconcile_assignment_status` align only Created/Assigned with technician
  assignment without rewinding work underway. `status_after_activity` advances
  either pre-work state to In-Progress for material/labor activity but preserves
  On-Hold until an explicit supervisor edit. Modes: `dispense`,
  `retroactive`; `affects_stock(mode)` = `mode == "dispense"`.
- `validate_status` / `validate_mode` → `WorkOrderStateError` on anything else.
- `fill_blank(current, incoming)` = keep non-blank `current`, else `incoming`
  (the find-or-create merge; `is_blank` = None or all-whitespace).
- `can_view_work_order(role, created_by_id, assigned_to_id, assigned_to_ids,
  user_id, supervisor_id)`: admin/owner (and `None` internal role) → all;
  supervisor → unrouted or routed to them; technician → present in the plural assignment set (with the
  singular compatibility fallback).
- Labor constants/rules: `LABOR_RATE = Decimal("62.50")`, increment = 30 minutes;
  `billed_labor_minutes(total)` rounds the combined duration upward once and
  `labor_charge(total)` applies the hourly rate.
- Export constants/rules: scope is `all`, `archived`, or one live status;
  variants are `full` and `client`. `validate_export_scope` /
  `validate_export_variant` reject unknown values with `WorkOrderStateError`.

### Billing (`domain/billing.py`)
- `validate_billable_value(qty, billable)` — None passes (clear); else `0 ≤
  billable ≤ qty`, raise `BillingQuantityError`. Used by **work-order lines**.
- `validate_billable_quantity(type, qty, billable)` — same, plus only `stock`/
  `dispense` rows may be overridden (an `adjust` cannot). Used by **transactions**.

### Fixed-width receipt (`domain/receipt.py`)
- `build_work_order_receipt(materials, labor_billed_minutes, labor_total)` builds
  the client-export receipt with the same 41-character layout as
  `static/adminReviewReceipt.js`: effective material quantity, 15% markup,
  quantity/name truncation, `NO PRICE` / `Total (incomplete)`, an always-present
  labor line, and the grand total. `tests/test_receipt.py` pins the Python output
  against the frontend contract.

### Tool custody (`domain/tools.py`)
- `validate_return(outstanding, requested)` — raises
  `ToolReturnExceedsCheckedOutError` if `requested > outstanding`; the
  caller (`services.tools.return_tool`) computes `outstanding` via the
  same aggregate query `tool_custody` uses, scoped to one user. This is
  the only new arithmetic for tools — the on-hand quantity math itself
  directly reuses `domain.quantity.apply_delta` (checkout = `"dispense"`,
  return = `"stock"`), no tool-specific version exists.

### Mass-stage lifecycle (`domain/mass_staging.py`)
- Status is forward-only: `planning → loading → completed`
  (`validate_transition`; any backward/same/unknown → `InvalidStageTransitionError`).
- Slots/items editable only in `planning`; load/return only in `loading`
  (else `StageStateError`).
- `allocate_return` caps a return at net-loaded across the item's slots
  (`ReturnExceedsLoadedError` if exceeded).

### Auth policy (`services/auth.py`, `auth_deps.py`)
- Password hash format: `scrypt$n$r$p$salt_hex$hash_hex` (n=2¹⁴, r=8, p=1,
  dklen=32, 16-byte salt). `verify_password` is constant-time (`hmac.compare_digest`)
  and returns False (never raises) on a malformed hash.
- Sessions: opaque `token_urlsafe(32)` row in `sessions`, carried by the HttpOnly,
  SameSite=Lax `session` cookie (Secure when `COOKIE_SECURE=true`). `remember=true`
  → `expires_at = now + 12h` (absolute cap, deleted on first request after expiry);
  else `expires_at = NULL` (browser-session, no server cap). **No idle timeout.**

---

## Service Invariants

Per-function service internals are code-owned: use codebase-memory-mcp
(`get_code_snippet`, `trace_path`) for "what does this function do". What stays
recorded here is cross-cutting:

- Stock changes happen only inside a service under a `SELECT … FOR UPDATE`
  item-row lock. The one silent stock change with no transaction row is
  mass-stage **return**.
- `attach_dispense_line` is the single "show a stock-out on the work order"
  funnel every path (scan dispense, work-order add item, mass-stage load) goes
  through. It advances Created/Assigned to In-Progress, leaves On-Hold alone,
  accumulates or inserts the line, and **never touches `items.quantity`** (the
  caller owns the lock). An unpriced item makes it create/extend the deduped
  missing-price request.
- Strict no-overdraft (`domain.quantity.apply_delta`) governs corrections,
  reversals, work-order quantity edits, and mass-stage stock-outs. Scan/Stock
  and Work Orders Add Item dispenses deliberately bypass it, commit negative,
  and open a recount request.
- Work orders are import-only: `get_or_create_work_order` (CSV import, its
  sole caller) is the only creating path; everything else uses
  `resolve_work_order`, which attaches to an existing number or 404s. Both
  share the `_merge_reference` fill-blanks merge.
- Reads that write: `get_work_order` heals orphaned linked dispenses into
  lines and applies the lazy 12-hour session cap (row-locked first — it
  produces a labor row, and two racing readers would bill twice); the hub
  routes sweep stale sessions.
- Barcode uniqueness for items is cross-table (primary + additional), checked
  in `_ensure_barcode_free`; an archived holder is a 409 override flow that
  deletes a history-less shell or retires just the code.
- Cost/billing fields (`item_price`, `billable_quantity`, `unit_price`,
  `materials_total`) are redacted server-side below Admin on #20, #25, #26.
- Tools reuse `domain.quantity.apply_delta` for custody math (checkout =
  dispense, return = stock) — no tool-specific arithmetic exists.
- Adding an endpoint touches all four layers (router → service → `api.js`
  wrapper → view) plus the Master Index and Per-Table Index here.

