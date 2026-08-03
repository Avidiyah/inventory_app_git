// Foundation: HTTP client wrappers for every backend endpoint.
//
// Layer: foundation (no DOM access, no state imports). Each
// `api*` function corresponds to one route on the FastAPI server
// and returns the parsed JSON body, or throws `{status, detail}`
// on a non-2xx response. Views catch that shape and pass `detail`
// to `format.formatError` for display.
//
// Centralising fetch logic here means content-type, error
// parsing, and 204-handling are written once, and adding an
// endpoint never requires touching view code.

// A single callback the app registers (via `setUnauthorizedHandler`) so
// that ANY 401 -- an expired or missing session on any request -- drops
// the user back to the login screen without each view handling it. The
// login view's own handler still renders bad-credential messages; this
// hook just guarantees the gate re-appears.
let unauthorizedHandler = null;
export function setUnauthorizedHandler(fn) {
  unauthorizedHandler = fn;
}

async function parseResponse(response) {
  // 204 No Content has an empty body by definition -- short-circuit
  // so callers can branch on `null` without parsing an empty string.
  if (response.status === 204) return null;
  let body = null;
  const text = await response.text();
  if (text) {
    try { body = JSON.parse(text); } catch { body = text; }
  }
  if (!response.ok) {
    // FastAPI returns `{detail: ...}` for raised HTTPException; fall
    // back to plain text / statusText for unexpected responses.
    const detail = (body && typeof body === "object" && body.detail !== undefined)
      ? body.detail
      : (typeof body === "string" ? body : response.statusText);
    if (response.status === 401 && unauthorizedHandler) {
      unauthorizedHandler();
    }
    throw { status: response.status, detail };
  }
  return body;
}

// Shared helper for POST/PATCH/PUT bodies. GETs and DELETEs go
// straight through `fetch` because they have no JSON payload.
// `credentials: "include"` ensures the session cookie rides along even
// if the app is ever served from a different origin.
async function jsonRequest(url, method, payload) {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
    credentials: "include",
  });
  return parseResponse(response);
}

// Dynamic authenticated list data should always reflect the server. These
// feeds back pages that explicitly refresh on activation, so bypass the
// browser HTTP cache while retaining the session cookie.
async function liveGet(url) {
  return parseResponse(await fetch(url, {
    credentials: "include",
    cache: "no-store",
  }));
}

// --- Auth --------------------------------------------------------
export async function apiLogin({ username, password, remember = false }) {
  return jsonRequest("/auth/login", "POST", { username, password, remember });
}

export async function apiLogout() {
  return parseResponse(await fetch("/auth/logout", { method: "POST", credentials: "include" }));
}

export async function apiMe() {
  return parseResponse(await fetch("/auth/me", { credentials: "include" }));
}

// --- Items -------------------------------------------------------
export async function apiListItems({ query = null } = {}) {
  const params = new URLSearchParams();
  if (query !== null) params.set("q", query);
  const qs = params.toString();
  return liveGet(`/items/${qs ? `?${qs}` : ""}`);
}

export async function apiListItemSearchIndex() {
  return liveGet("/items/search-index");
}

export async function apiCreateItem({ barcode, name, location, quantity, price, product_link, override_archived = false }) {
  // `override_archived` confirms reuse of a barcode held only by an archived
  // (deleted) item: the first POST omits it (defaults false) and gets a 409;
  // the user confirms and we re-POST with it true to free the archived holder.
  return jsonRequest("/items/", "POST", { barcode, name, location, quantity, price, product_link, override_archived });
}

export async function apiDeleteItem(itemId) {
  return parseResponse(await fetch(`/items/${itemId}`, { method: "DELETE", credentials: "include" }));
}

export async function apiUpdateItem(itemId, payload) {
  // `payload` is `{barcode?, name?, location?}` — only fields the
  // caller wants to change. The backend requires at least one.
  return jsonRequest(`/items/${itemId}`, "PATCH", payload);
}

export async function apiUpdateNotes(itemId, notesDict) {
  return jsonRequest(`/items/${itemId}/notes`, "PATCH", { notes: notesDict });
}

export async function apiUpdateBarcodes(itemId, codes, overrideArchived = false) {
  // `codes` is the full list of an item's *additional* barcodes (the
  // primary is edited via apiUpdateItem). Wholesale replace, mirroring
  // apiUpdateNotes. `overrideArchived` confirms reuse of a code held only by
  // an archived item (a 409 on the first try); see apiCreateItem.
  return jsonRequest(`/items/${itemId}/barcodes`, "PATCH", { barcodes: codes, override_archived: overrideArchived });
}

export async function apiGetItemByBarcode(barcode) {
  // Barcodes may contain characters that need URL-escaping (e.g.
  // `/` or `#`); raw values would silently mis-route.
  return parseResponse(await fetch(`/items/${encodeURIComponent(barcode)}`, { credentials: "include" }));
}

// --- Tools ---------------------------------------------------------
// A tool is parallel to an item but smaller (no location/price/link) and
// tracks custody (checkout/return) instead of one-way consumption.
export async function apiListTools() {
  return parseResponse(await fetch("/tools/", { credentials: "include" }));
}

export async function apiCreateTool({ barcode, name, quantity }) {
  return jsonRequest("/tools/", "POST", { barcode, name, quantity });
}

export async function apiGetToolByBarcode(barcode) {
  return parseResponse(await fetch(`/tools/${encodeURIComponent(barcode)}`, { credentials: "include" }));
}

export async function apiUpdateTool(toolId, payload) {
  // `payload` is `{barcode?, name?}` -- only fields the caller wants to change.
  return jsonRequest(`/tools/${toolId}`, "PATCH", payload);
}

export async function apiDeleteTool(toolId) {
  return parseResponse(await fetch(`/tools/${toolId}`, { method: "DELETE", credentials: "include" }));
}

export async function apiCheckoutTool(toolId, { quantity, assignedToId, workOrderNumber = null }) {
  return jsonRequest(`/tools/${toolId}/checkout`, "POST", {
    quantity,
    assigned_to_id: assignedToId,
    work_order_number: workOrderNumber,
  });
}

export async function apiReturnTool(toolId, { quantity, assignedToId, workOrderNumber = null }) {
  return jsonRequest(`/tools/${toolId}/return`, "POST", {
    quantity,
    assigned_to_id: assignedToId,
    work_order_number: workOrderNumber,
  });
}

export async function apiAdjustTool(toolId, { newQuantity, reason }) {
  // "Correct Count": sets the absolute on-hand quantity with a required
  // reason (Admin+). Sibling of apiCreateCorrection for items.
  return jsonRequest(`/tools/${toolId}/adjust`, "POST", {
    new_quantity: newQuantity,
    reason,
  });
}

// --- Barcodes ----------------------------------------------------
export async function apiDecodeBarcode(file) {
  // multipart/form-data upload -- do NOT set Content-Type by hand; the
  // browser must add the multipart boundary itself. The decoded image is
  // never persisted server-side (see app/services/barcodes.py).
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/barcodes/decode", {
    method: "POST",
    body: form,
    credentials: "include",
  });
  return parseResponse(response);
}

// --- Users -------------------------------------------------------
export async function apiListUsers({ includeArchived = false } = {}) {
  const query = includeArchived ? "?include_archived=true" : "";
  return liveGet(`/users/${query}`);
}

export async function apiCreateUser({ username, firstName, lastName, password, role }) {
  return jsonRequest("/users/", "POST", {
    username,
    first_name: firstName,
    last_name: lastName,
    password,
    role,
  });
}

export async function apiUpdateUserName(userId, { firstName, lastName, username }) {
  const payload = {
    first_name: firstName,
    last_name: lastName,
  };
  // Omitted entirely (rather than sent as null) when the caller is only
  // editing the human name, so the server leaves the login name alone.
  if (username !== undefined) payload.username = username;
  return jsonRequest(`/users/${userId}/name`, "PATCH", payload);
}

export async function apiUpdateUserRole(userId, role) {
  return jsonRequest(`/users/${userId}/role`, "PATCH", { role });
}

export async function apiResetPassword(userId, password) {
  return jsonRequest(`/users/${userId}/reset-password`, "POST", { password });
}

// `forceReturnTools` retries an archive the server refused with 409 because
// the user still holds tools, checking those tools in as part of the archive.
export async function apiArchiveUser(userId, { forceReturnTools = false } = {}) {
  const query = forceReturnTools ? "?force_return_tools=true" : "";
  return parseResponse(await fetch(`/users/${userId}/archive${query}`, { method: "POST", credentials: "include" }));
}

export async function apiRestoreUser(userId) {
  return parseResponse(await fetch(`/users/${userId}/restore`, { method: "POST", credentials: "include" }));
}

export async function apiDeleteUser(userId) {
  return parseResponse(await fetch(`/users/${userId}`, { method: "DELETE", credentials: "include" }));
}

// --- Transactions ------------------------------------------------
export async function apiListTransactions({ page, pageSize, itemId, userId, workOrder, dateFrom, dateTo }) {
  const params = new URLSearchParams();
  params.set("page", page);
  params.set("page_size", pageSize);
  // Filters are omitted when null/undefined so the backend sees
  // them as "all" rather than as `item_id=null`.
  if (itemId) params.set("item_id", itemId);
  if (userId) params.set("user_id", userId);
  if (workOrder) params.set("work_order_number", workOrder);
  // `YYYY-MM-DD` calendar dates; the backend bounds `created_at` inclusively.
  if (dateFrom) params.set("date_from", dateFrom);
  if (dateTo) params.set("date_to", dateTo);
  return parseResponse(await fetch(`/transactions/?${params.toString()}`, { credentials: "include" }));
}

export async function apiCreateTransaction(payload) {
  // Build the body explicitly rather than spreading -- the backend
  // schema rejects unknown keys, and dropping a missing
  // `work_order_number` keeps the wire format clean. There is no
  // `user_id`: the server attributes the transaction to the logged-in
  // user from the session.
  const body = {
    item_id: payload.item_id,
    transaction_type: payload.transaction_type,
    quantity: payload.quantity,
  };
  // A scan from a work-order card sends `work_order_id`; manual/free-text sends
  // `work_order_number` (the backend find-or-creates it for Supervisor+).
  if (payload.work_order_id) body.work_order_id = payload.work_order_id;
  if (payload.work_order_number) body.work_order_number = payload.work_order_number;
  return jsonRequest("/transactions/", "POST", body);
}

export async function apiSetBillableQuantity(transactionId, billableQuantity) {
  // Admin/Owner only on the backend. Sets how many of the row's units to
  // charge the customer for (0 = recorded-but-not-charged), or pass `null`
  // to clear the override and bill the full recorded quantity. Pure billing
  // annotation -- does NOT touch the item's on-hand count. Returns the
  // updated transaction row.
  return jsonRequest(`/transactions/${transactionId}/billing`, "PATCH", {
    billable_quantity: billableQuantity,
  });
}

export async function apiVoidTransaction(transactionId) {
  // Soft-delete (void) a mis-clicked transaction. Supervisor+ on the
  // backend; reverses the row's effect on stock and hides it from
  // history. 204 on success.
  return parseResponse(await fetch(`/transactions/${transactionId}`, { method: "DELETE", credentials: "include" }));
}

export async function apiCreateCorrection({ itemId, newQuantity, reason }) {
  // Sibling of apiCreateTransaction, but for `transaction_type = "adjust"`
  // -- Admin+ only on the backend. The user sends the absolute new
  // quantity; the server computes the signed delta under FOR UPDATE.
  return jsonRequest("/transactions/adjust", "POST", {
    item_id: itemId,
    new_quantity: newQuantity,
    reason,
  });
}

// --- Mass Staging (planning) -------------------------------------
// All Supervisor+ on the backend. The frontend snake_cases the bodies the
// schemas expect; callers pass camelCase.
export async function apiListStages(status) {
  const qs = status ? `?status=${encodeURIComponent(status)}` : "";
  return liveGet(`/mass-stages/${qs}`);
}

export async function apiCreateStage(community, buildingName) {
  // `building_name` carries the building number (DB column name kept);
  // `community` is the new top tree level.
  return jsonRequest("/mass-stages/", "POST", {
    community,
    building_name: buildingName,
  });
}

export async function apiGetStage(stageId) {
  return parseResponse(await fetch(`/mass-stages/${stageId}`, { credentials: "include" }));
}

export async function apiUpdateStage(stageId, patch) {
  // `patch` is `{community?, building_name?, status?}` — at least one.
  return jsonRequest(`/mass-stages/${stageId}`, "PATCH", patch);
}

export async function apiDeleteStage(stageId) {
  return parseResponse(await fetch(`/mass-stages/${stageId}`, { method: "DELETE", credentials: "include" }));
}

// Add a work order to a stage's truck plan. The backend find-or-creates the
// work order by number (community/building from the stage), records its unit +
// optional technician assignee, and links it as a slot. Returns the slot detail.
export async function apiAddStageWorkOrder(stageId, { workOrderNumber, unitNumber = null, assignedToId = null }) {
  return jsonRequest(`/mass-stages/${stageId}/work-orders`, "POST", {
    work_order_number: workOrderNumber,
    unit_number: unitNumber,
    assigned_to_id: assignedToId,
  });
}

export async function apiDeleteStageWorkOrder(stageId, slotId) {
  return parseResponse(await fetch(`/mass-stages/${stageId}/work-orders/${slotId}`, { method: "DELETE", credentials: "include" }));
}

export async function apiAddStageItem(stageId, slotId, { itemId, plannedQuantity }) {
  return jsonRequest(`/mass-stages/${stageId}/work-orders/${slotId}/items`, "POST", {
    item_id: itemId,
    planned_quantity: plannedQuantity,
  });
}

export async function apiUpdateStageItem(stageId, slotId, stageItemId, { plannedQuantity }) {
  return jsonRequest(`/mass-stages/${stageId}/work-orders/${slotId}/items/${stageItemId}`, "PATCH", {
    planned_quantity: plannedQuantity,
  });
}

export async function apiDeleteStageItem(stageId, slotId, stageItemId) {
  return parseResponse(await fetch(`/mass-stages/${stageId}/work-orders/${slotId}/items/${stageItemId}`, { method: "DELETE", credentials: "include" }));
}

// Loading + returns (the stock-touching actions). Both return the item's
// updated merged rollup. `load` writes per-slot dispenses; `return` adds stock
// back silently (no ledger row). See docs/current-state.md.
export async function apiLoadStageItem(stageId, { itemId, quantity }) {
  return jsonRequest(`/mass-stages/${stageId}/load`, "POST", { item_id: itemId, quantity });
}

export async function apiReturnStageItem(stageId, { itemId, quantity }) {
  return jsonRequest(`/mass-stages/${stageId}/return`, "POST", { item_id: itemId, quantity });
}

export async function apiReuseStage(stageId) {
  // Fresh planning stage for the same community + building as a completed one.
  return jsonRequest(`/mass-stages/${stageId}/reuse`, "POST", {});
}

// --- Work Orders -------------------------------------------------------
// A work order is the standalone entity (identity = number). List/get/items are
// open to any authenticated user but server-scoped (technician -> assigned,
// supervisor -> created/routed, admin/owner -> all). Attribute edits / restore
// are Supervisor+; close/archive is Admin+ and only valid from Review.
//
// There is no create call: work orders are import-only, so apiImportWorkOrders
// is the only thing that brings one into existence. Every other surface looks an
// existing number up (apiListWorkOrders with `q`, or apiLookupWorkOrder).
export async function apiListWorkOrders({ status = null, q = null, limit = null } = {}) {
  const params = new URLSearchParams();
  if (status) params.set("status", status);
  if (q) params.set("q", q);
  if (limit != null) params.set("limit", limit);
  const qs = params.toString();
  return liveGet(`/work-orders/${qs ? `?${qs}` : ""}`);
}

export async function apiGetWorkOrder(workOrderId) {
  return parseResponse(await fetch(`/work-orders/${workOrderId}`, { credentials: "include" }));
}

// Bulk-import work orders from the mass CSV export (Admin+). multipart upload --
// do NOT set Content-Type by hand (the browser adds the multipart boundary),
// mirroring apiDecodeBarcode. Returns the WorkOrderImportResult summary.
export async function apiImportWorkOrders(file) {
  const form = new FormData();
  form.append("file", file);
  const response = await fetch("/work-orders/import", {
    method: "POST",
    body: form,
    credentials: "include",
  });
  return parseResponse(response);
}

// `patch` is any subset of {status, entry_mode, number, community,
// building_number, unit_number, description, notes, location, output_to,
// vendor_assignee, service_type, schedule_date, supervisor_id,
// assigned_to_ids}. `assigned_to_id` remains accepted by the backend for older
// clients, but this UI writes the plural assignment set.
// Notes / entry_mode / Set In-Progress / Mark Completed are available in-scope;
// manual rollback, On-Hold, Review, and the remaining fields are Supervisor+.
export async function apiUpdateWorkOrder(workOrderId, patch) {
  return jsonRequest(`/work-orders/${workOrderId}`, "PATCH", patch);
}

export async function apiArchiveWorkOrder(workOrderId) {
  // Close a Review work order. Kept as the archive URL because Closed is the
  // existing soft-archive state rather than a sixth stored status.
  return parseResponse(await fetch(`/work-orders/${workOrderId}/archive`, { method: "POST", credentials: "include" }));
}

// Does this number name a work order, and is it archived? Supervisor+. Returns
// {found, archived, id, number}. The only read that sees archived work orders --
// list/get hide them -- so History can spot a searched number whose work order
// has been archived and offer apiRestoreWorkOrder.
export async function apiLookupWorkOrder(number) {
  const qs = new URLSearchParams({ number }).toString();
  return parseResponse(await fetch(`/work-orders/lookup?${qs}`, { credentials: "include" }));
}

// Un-archive a work order (Supervisor+). The undo for apiArchiveWorkOrder;
// returns the restored WorkOrderDetail.
export async function apiRestoreWorkOrder(workOrderId) {
  return parseResponse(await fetch(`/work-orders/${workOrderId}/restore`, { method: "POST", credentials: "include" }));
}

export async function apiAddWorkOrderItem(workOrderId, { itemId, quantity }) {
  return jsonRequest(`/work-orders/${workOrderId}/items`, "POST", {
    item_id: itemId,
    quantity,
  });
}

export async function apiUpdateWorkOrderItem(workOrderId, woItemId, { quantity }) {
  return jsonRequest(`/work-orders/${workOrderId}/items/${woItemId}`, "PATCH", { quantity });
}

// Set or clear a material line's billing override (Admin/Owner). `billableQuantity`
// of null clears it (bill the full quantity); 0 bills nothing.
export async function apiSetWorkOrderItemBilling(workOrderId, woItemId, billableQuantity) {
  return jsonRequest(`/work-orders/${workOrderId}/items/${woItemId}/billing`, "PATCH", {
    billable_quantity: billableQuantity,
  });
}

export async function apiDeleteWorkOrderItem(workOrderId, woItemId) {
  return parseResponse(await fetch(`/work-orders/${workOrderId}/items/${woItemId}`, { method: "DELETE", credentials: "include" }));
}

// Labor is stored in whole minutes and billed from the combined work-order
// duration at $62.50/hour, rounded upward once to the next 30 minutes.
export async function apiAddWorkOrderLabor(workOrderId, { technicianId, minutes }) {
  return jsonRequest(`/work-orders/${workOrderId}/labor`, "POST", {
    technician_id: technicianId,
    minutes,
  });
}

export async function apiUpdateWorkOrderLabor(workOrderId, laborId, { minutes }) {
  return jsonRequest(`/work-orders/${workOrderId}/labor/${laborId}`, "PATCH", { minutes });
}

export async function apiDeleteWorkOrderLabor(workOrderId, laborId) {
  return parseResponse(await fetch(`/work-orders/${workOrderId}/labor/${laborId}`, {
    method: "DELETE",
    credentials: "include",
  }));
}
