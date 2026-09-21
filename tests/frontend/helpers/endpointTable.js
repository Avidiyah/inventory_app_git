// The wire contract of every api.js wrapper, in api.js order.
//
// A row records what the wrapper SENDS. Response handling is covered by
// api.contract.test.js, odd shapes by api.shapes.test.js. `method` defaults
// to GET; `body` is the parsed JSON payload, absent for GET/DELETE and for
// the two `multipart: true` uploads (asserted as FormData instead).
//
// A new endpoint without a row here fails the meta-test in
// api.endpoints.test.js. That is the point: adding a wrapper must be a
// deliberate act, not a silent one.
//
// For a wrapper whose URL depends on optional arguments, the row carries the
// no-arguments form; the permutations live in api.shapes.test.js.

const uploadFile = () => new File(["x"], "upload.png", { type: "image/png" });

export const ENDPOINTS = [
  // --- Auth ---
  { fn: "apiLogin", args: [{ username: "u", password: "p" }], method: "POST", url: "/auth/login",
    body: { username: "u", password: "p", remember: false } },
  { fn: "apiLogout", args: [], method: "POST", url: "/auth/logout" },
  { fn: "apiMe", args: [], url: "/auth/me" },

  // --- Items ---
  { fn: "apiListItems", args: [{}], url: "/items/", cache: "no-store" },
  { fn: "apiCreateItem", args: [{ barcode: "b", name: "n", location: "l", quantity: 1, price: 2, product_link: null }],
    method: "POST", url: "/items/",
    body: { barcode: "b", name: "n", location: "l", quantity: 1, price: 2, product_link: null, override_archived: false } },
  { fn: "apiDeleteItem", args: [3], method: "DELETE", url: "/items/3" },
  { fn: "apiUpdateItem", args: [3, { name: "n" }], method: "PATCH", url: "/items/3", body: { name: "n" } },
  { fn: "apiUpdateNotes", args: [3, { a: 1 }], method: "PATCH", url: "/items/3/notes", body: { notes: { a: 1 } } },
  { fn: "apiUpdateBarcodes", args: [3, ["x"]], method: "PATCH", url: "/items/3/barcodes",
    body: { barcodes: ["x"], override_archived: false } },
  { fn: "apiListLowStock", args: [], url: "/items/low-stock", cache: "no-store" },
  { fn: "apiSetLowStockThreshold", args: [3, 5], method: "PATCH", url: "/items/3/low-stock-threshold",
    body: { low_stock_threshold: 5 } },
  { fn: "apiGetItemByBarcode", args: ["abc"], url: "/items/abc" },

  // --- Tools ---
  { fn: "apiListTools", args: [], url: "/tools/" },
  { fn: "apiCreateTool", args: [{ barcode: "b", name: "n", quantity: 1 }], method: "POST", url: "/tools/",
    body: { barcode: "b", name: "n", quantity: 1 } },
  { fn: "apiGetToolByBarcode", args: ["abc"], url: "/tools/abc" },
  { fn: "apiUpdateTool", args: [3, { name: "n" }], method: "PATCH", url: "/tools/3", body: { name: "n" } },
  { fn: "apiDeleteTool", args: [3], method: "DELETE", url: "/tools/3" },
  { fn: "apiCheckoutTool", args: [3, { quantity: 1, assignedToId: 2 }], method: "POST", url: "/tools/3/checkout",
    body: { quantity: 1, assigned_to_id: 2, work_order_number: null } },
  { fn: "apiReturnTool", args: [3, { quantity: 1, assignedToId: 2 }], method: "POST", url: "/tools/3/return",
    body: { quantity: 1, assigned_to_id: 2, work_order_number: null } },
  { fn: "apiAdjustTool", args: [3, { newQuantity: 5, reason: "recount" }], method: "POST", url: "/tools/3/adjust",
    body: { new_quantity: 5, reason: "recount" } },

  // --- Barcodes ---
  { fn: "apiDecodeBarcode", args: [uploadFile()], method: "POST", url: "/barcodes/decode", multipart: true },

  // --- Users ---
  { fn: "apiListUsers", args: [{}], url: "/users/", cache: "no-store" },
  { fn: "apiCreateUser", args: [{ username: "u", firstName: "f", lastName: "l", password: "p", role: "technician" }],
    method: "POST", url: "/users/",
    body: { username: "u", first_name: "f", last_name: "l", password: "p", role: "technician" } },
  { fn: "apiUpdateUserName", args: [3, { firstName: "f", lastName: "l" }], method: "PATCH", url: "/users/3/name",
    body: { first_name: "f", last_name: "l" } },
  { fn: "apiUpdateUserRole", args: [3, "admin"], method: "PATCH", url: "/users/3/role", body: { role: "admin" } },
  { fn: "apiResetPassword", args: [3, "p"], method: "POST", url: "/users/3/reset-password", body: { password: "p" } },
  { fn: "apiArchiveUser", args: [3], method: "POST", url: "/users/3/archive" },
  { fn: "apiRestoreUser", args: [3], method: "POST", url: "/users/3/restore" },
  { fn: "apiDeleteUser", args: [3], method: "DELETE", url: "/users/3" },

  // --- Transactions ---
  { fn: "apiListTransactions", args: [{ page: 1, pageSize: 20 }], url: "/transactions/?page=1&page_size=20" },
  { fn: "apiCreateTransaction", args: [{ item_id: 1, transaction_type: "out", quantity: 2 }],
    method: "POST", url: "/transactions/", body: { item_id: 1, transaction_type: "out", quantity: 2 } },
  { fn: "apiSetBillableQuantity", args: [7, 2], method: "PATCH", url: "/transactions/7/billing",
    body: { billable_quantity: 2 } },
  { fn: "apiVoidTransaction", args: [7], method: "DELETE", url: "/transactions/7" },

  // --- User Requests ---
  { fn: "apiListUserRequests", args: [], url: "/user-requests/?status=open", cache: "no-store" },
  { fn: "apiListUserRequestCounts", args: [], url: "/user-requests/counts", cache: "no-store" },
  { fn: "apiCreateMaterialRequest", args: [{ itemId: 1, workOrderId: 2 }], method: "POST",
    url: "/user-requests/material-request",
    body: { item_id: 1, work_order_id: 2, quantity: 1, product_link: null, note: null } },
  { fn: "apiMarkRequestStocked", args: [5], method: "POST", url: "/user-requests/5/mark-stocked", body: {} },
  { fn: "apiCancelMaterialRequest", args: [5], method: "POST", url: "/user-requests/5/cancel", body: {} },
  { fn: "apiUpdateUserRequest", args: [5, { status: "open" }], method: "PATCH", url: "/user-requests/5",
    body: { status: "open", resolution_note: null, message: null, details: null } },
  { fn: "apiCreateCatalogueRequest", args: [{ searchedText: "x", source: "find_item" }], method: "POST",
    url: "/user-requests/catalogue-request",
    body: { searched_text: "x", quantity: 1, note: null, work_order_id: null, source: "find_item" } },
  { fn: "apiListRequestSiblings", args: [5], url: "/user-requests/5/siblings", cache: "no-store" },
  { fn: "apiFulfillCatalogueRequest", args: [5, { itemId: 1 }], method: "POST", url: "/user-requests/5/fulfill",
    body: { item_id: 1, new_item: null, sibling_ids: [] } },
  { fn: "apiCreateCorrection", args: [{ itemId: 1, newQuantity: 5, reason: "recount" }], method: "POST",
    url: "/transactions/adjust", body: { item_id: 1, new_quantity: 5, reason: "recount" } },

  // --- Mass Staging ---
  { fn: "apiListStages", args: [], url: "/mass-stages/", cache: "no-store" },
  { fn: "apiCreateStage", args: ["c", "b"], method: "POST", url: "/mass-stages/",
    body: { community: "c", building_name: "b" } },
  { fn: "apiGetStage", args: [4], url: "/mass-stages/4" },
  { fn: "apiUpdateStage", args: [4, { status: "active" }], method: "PATCH", url: "/mass-stages/4",
    body: { status: "active" } },
  { fn: "apiDeleteStage", args: [4], method: "DELETE", url: "/mass-stages/4" },
  { fn: "apiAddStageWorkOrder", args: [4, { workOrderNumber: "WO1" }], method: "POST",
    url: "/mass-stages/4/work-orders",
    body: { work_order_number: "WO1", unit_number: null, assigned_to_id: null } },
  { fn: "apiDeleteStageWorkOrder", args: [4, 9], method: "DELETE", url: "/mass-stages/4/work-orders/9" },
  { fn: "apiAddStageItem", args: [4, 9, { itemId: 1, plannedQuantity: 2 }], method: "POST",
    url: "/mass-stages/4/work-orders/9/items", body: { item_id: 1, planned_quantity: 2 } },
  { fn: "apiUpdateStageItem", args: [4, 9, 11, { plannedQuantity: 3 }], method: "PATCH",
    url: "/mass-stages/4/work-orders/9/items/11", body: { planned_quantity: 3 } },
  { fn: "apiDeleteStageItem", args: [4, 9, 11], method: "DELETE",
    url: "/mass-stages/4/work-orders/9/items/11" },
  { fn: "apiLoadStageItem", args: [4, { itemId: 1, quantity: 2 }], method: "POST", url: "/mass-stages/4/load",
    body: { item_id: 1, quantity: 2 } },
  { fn: "apiReturnStageItem", args: [4, { itemId: 1, quantity: 2 }], method: "POST", url: "/mass-stages/4/return",
    body: { item_id: 1, quantity: 2 } },
  { fn: "apiReuseStage", args: [4], method: "POST", url: "/mass-stages/4/reuse", body: {} },

  // --- Work Orders ---
  { fn: "apiListWorkOrders", args: [{}], url: "/work-orders/", cache: "no-store" },
  { fn: "apiGetWorkOrderFilterOptions", args: [], url: "/work-orders/filter-options", cache: "no-store" },
  { fn: "apiGetWorkOrder", args: [12], url: "/work-orders/12" },
  { fn: "apiListWorkOrderRequests", args: [12], url: "/work-orders/12/requests", cache: "no-store" },

  // --- User Hub ---
  { fn: "apiGetHub", args: [], url: "/hub", cache: "no-store" },
  { fn: "apiGetHubCrew", args: [], url: "/hub/crew", cache: "no-store" },
  { fn: "apiGetHubAdmin", args: [], url: "/hub/admin", cache: "no-store" },
  { fn: "apiGetHubGraphs", args: [{}], url: "/hub/graphs?weeks=12", cache: "no-store" },
  { fn: "apiGetHubReport", args: [], url: "/hub/report", cache: "no-store" },
  { fn: "apiGetHubTimesheets", args: [{}], url: "/hub/timesheets", cache: "no-store" },
  { fn: "apiExportHubTimesheets", args: [{}], url: "/hub/timesheets/export", cache: "no-store" },
  { fn: "apiImportWorkOrders", args: [uploadFile()], method: "POST", url: "/work-orders/import", multipart: true },

  // --- Attendance ---
  { fn: "apiGetAttendanceMe", args: [], url: "/attendance/me", cache: "no-store" },
  { fn: "apiPunchIn", args: [], method: "POST", url: "/attendance/punch-in", body: {} },
  { fn: "apiPunchOut", args: [], method: "POST", url: "/attendance/punch-out", body: {} },
  { fn: "apiSelfClosePunch", args: ["2026-09-21T18:00:00.000Z"], method: "POST",
    url: "/attendance/self-close", body: { ended_at: "2026-09-21T18:00:00.000Z" } },

  // --- NetFacilities integration ---
  { fn: "apiStartNetFacilitiesEnrichment", args: [], method: "POST",
    url: "/integrations/netfacilities/work-orders/enrich" },
  { fn: "apiGetNetFacilitiesEnrichment", args: ["job1"],
    url: "/integrations/netfacilities/work-orders/enrich/job1", cache: "no-store" },
  { fn: "apiGetNetFacilitiesCloudSession", args: [],
    url: "/integrations/netfacilities/cloud/session", cache: "no-store" },
  { fn: "apiStartNetFacilitiesCloudAuthentication", args: [], method: "POST",
    url: "/integrations/netfacilities/cloud/auth/start" },
  { fn: "apiCancelNetFacilitiesCloudAuthentication", args: [], method: "POST",
    url: "/integrations/netfacilities/cloud/auth/cancel" },
  { fn: "apiImportNetFacilitiesCloudDownload", args: [], method: "POST",
    url: "/integrations/netfacilities/cloud/downloads/import" },

  // --- Work-order exports and legacy archive ---
  { fn: "apiExportWorkOrders", args: [], url: "/work-orders/export?scope=all&variant=full", cache: "no-store" },
  { fn: "apiGetLegacyWorkOrderArchivePreview", args: [], url: "/work-orders/legacy/archive", cache: "no-store" },
  { fn: "apiArchiveLegacyWorkOrders", args: [], method: "POST", url: "/work-orders/legacy/archive" },

  // --- Work-order lifecycle ---
  { fn: "apiUpdateWorkOrder", args: [12, { status: "Assigned" }], method: "PATCH", url: "/work-orders/12",
    body: { status: "Assigned" } },
  { fn: "apiStartWorkOrder", args: [12], method: "POST", url: "/work-orders/12/start", body: {} },
  { fn: "apiCompleteWorkOrder", args: [12], method: "POST", url: "/work-orders/12/complete", body: {} },
  { fn: "apiStartWorkOrderTracking", args: [12], method: "POST", url: "/work-orders/12/tracking/start", body: {} },
  { fn: "apiStopWorkOrderTracking", args: [12], method: "POST", url: "/work-orders/12/tracking/stop", body: {} },
  { fn: "apiHoldWorkOrder", args: [12], method: "POST", url: "/work-orders/12/hold", body: {} },
  { fn: "apiResumeWorkOrder", args: [12], method: "POST", url: "/work-orders/12/resume", body: {} },
  { fn: "apiArchiveWorkOrder", args: [12], method: "POST", url: "/work-orders/12/archive" },
  { fn: "apiLookupWorkOrder", args: ["WO-1"], url: "/work-orders/lookup?number=WO-1" },
  { fn: "apiRestoreWorkOrder", args: [12], method: "POST", url: "/work-orders/12/restore" },

  // --- Work-order lines ---
  { fn: "apiAddWorkOrderItem", args: [12, { itemId: 1, quantity: 2 }], method: "POST", url: "/work-orders/12/items",
    body: { item_id: 1, quantity: 2, material_request_id: null } },
  { fn: "apiUpdateWorkOrderItem", args: [12, 5, { quantity: 3 }], method: "PATCH", url: "/work-orders/12/items/5",
    body: { quantity: 3 } },
  { fn: "apiSetWorkOrderItemBilling", args: [12, 5, 2], method: "PATCH", url: "/work-orders/12/items/5/billing",
    body: { billable_quantity: 2 } },
  { fn: "apiDeleteWorkOrderItem", args: [12, 5], method: "DELETE", url: "/work-orders/12/items/5" },
  { fn: "apiAddWorkOrderLabor", args: [12, { technicianId: 3, minutes: 30 }], method: "POST",
    url: "/work-orders/12/labor", body: { technician_id: 3, minutes: 30 } },
  { fn: "apiUpdateWorkOrderLabor", args: [12, 7, { minutes: 45 }], method: "PATCH", url: "/work-orders/12/labor/7",
    body: { minutes: 45 } },
  { fn: "apiDeleteWorkOrderLabor", args: [12, 7], method: "DELETE", url: "/work-orders/12/labor/7" },

  // --- Web Push ---
  { fn: "apiPushConfig", args: [], url: "/push/config" },
  { fn: "apiPushSubscribe", args: [{ toJSON: () => ({ endpoint: "https://push/e" }) }], method: "POST",
    url: "/push/subscribe", body: { endpoint: "https://push/e" } },
  { fn: "apiPushUnsubscribe", args: ["https://push/e"], method: "POST", url: "/push/unsubscribe",
    body: { endpoint: "https://push/e" } },
  { fn: "apiPushTest", args: [], method: "POST", url: "/push/test" },
];
