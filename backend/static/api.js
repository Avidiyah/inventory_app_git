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
export async function apiListItems() {
  return parseResponse(await fetch("/items/", { credentials: "include" }));
}

export async function apiCreateItem({ barcode, name, location, quantity, price, product_link }) {
  return jsonRequest("/items/", "POST", { barcode, name, location, quantity, price, product_link });
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

export async function apiUpdateBarcodes(itemId, codes) {
  // `codes` is the full list of an item's *additional* barcodes (the
  // primary is edited via apiUpdateItem). Wholesale replace, mirroring
  // apiUpdateNotes.
  return jsonRequest(`/items/${itemId}/barcodes`, "PATCH", { barcodes: codes });
}

export async function apiGetItemByBarcode(barcode) {
  // Barcodes may contain characters that need URL-escaping (e.g.
  // `/` or `#`); raw values would silently mis-route.
  return parseResponse(await fetch(`/items/${encodeURIComponent(barcode)}`, { credentials: "include" }));
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
export async function apiListUsers() {
  return parseResponse(await fetch("/users/", { credentials: "include" }));
}

export async function apiCreateUser({ username, password, role }) {
  return jsonRequest("/users/", "POST", { username, password, role });
}

export async function apiResetPassword(userId, password) {
  return jsonRequest(`/users/${userId}/reset-password`, "POST", { password });
}

export async function apiDeleteUser(userId) {
  return parseResponse(await fetch(`/users/${userId}`, { method: "DELETE", credentials: "include" }));
}

// --- Transactions ------------------------------------------------
export async function apiListTransactions({ page, pageSize, itemId, userId, workOrder }) {
  const params = new URLSearchParams();
  params.set("page", page);
  params.set("page_size", pageSize);
  // Filters are omitted when null/undefined so the backend sees
  // them as "all" rather than as `item_id=null`.
  if (itemId) params.set("item_id", itemId);
  if (userId) params.set("user_id", userId);
  if (workOrder) params.set("work_order_number", workOrder);
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
  if (payload.work_order_number) body.work_order_number = payload.work_order_number;
  return jsonRequest("/transactions/", "POST", body);
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
  return parseResponse(await fetch(`/mass-stages/${qs}`, { credentials: "include" }));
}

export async function apiCreateStage(buildingName) {
  return jsonRequest("/mass-stages/", "POST", { building_name: buildingName });
}

export async function apiGetStage(stageId) {
  return parseResponse(await fetch(`/mass-stages/${stageId}`, { credentials: "include" }));
}

export async function apiUpdateStage(stageId, patch) {
  // `patch` is `{building_name?, status?}` — at least one.
  return jsonRequest(`/mass-stages/${stageId}`, "PATCH", patch);
}

export async function apiDeleteStage(stageId) {
  return parseResponse(await fetch(`/mass-stages/${stageId}`, { method: "DELETE", credentials: "include" }));
}

export async function apiAddRoom(stageId, { roomNumber, workOrderNumber, assignedToId = null }) {
  return jsonRequest(`/mass-stages/${stageId}/rooms`, "POST", {
    room_number: roomNumber,
    work_order_number: workOrderNumber,
    assigned_to_id: assignedToId,
  });
}

// Assign a work order (room) to a technician, or clear it (assignedToId = null).
export async function apiAssignRoom(stageId, roomId, assignedToId) {
  return jsonRequest(`/mass-stages/${stageId}/rooms/${roomId}/assign`, "PATCH", {
    assigned_to_id: assignedToId,
  });
}

export async function apiUpdateRoom(stageId, roomId, patch) {
  return jsonRequest(`/mass-stages/${stageId}/rooms/${roomId}`, "PATCH", patch);
}

export async function apiDeleteRoom(stageId, roomId) {
  return parseResponse(await fetch(`/mass-stages/${stageId}/rooms/${roomId}`, { method: "DELETE", credentials: "include" }));
}

export async function apiAddStageItem(stageId, roomId, { itemId, plannedQuantity }) {
  return jsonRequest(`/mass-stages/${stageId}/rooms/${roomId}/items`, "POST", {
    item_id: itemId,
    planned_quantity: plannedQuantity,
  });
}

export async function apiUpdateStageItem(stageId, roomId, stageItemId, { plannedQuantity }) {
  return jsonRequest(`/mass-stages/${stageId}/rooms/${roomId}/items/${stageItemId}`, "PATCH", {
    planned_quantity: plannedQuantity,
  });
}

export async function apiDeleteStageItem(stageId, roomId, stageItemId) {
  return parseResponse(await fetch(`/mass-stages/${stageId}/rooms/${roomId}/items/${stageItemId}`, { method: "DELETE", credentials: "include" }));
}

// Loading + returns (the stock-touching actions). Both return the item's
// updated merged rollup. `load` writes per-room dispenses; `return` adds stock
// back silently (no ledger row). See docs/mass-staging/phase-5-load-return.md.
export async function apiLoadStageItem(stageId, { itemId, quantity }) {
  return jsonRequest(`/mass-stages/${stageId}/load`, "POST", { item_id: itemId, quantity });
}

export async function apiReturnStageItem(stageId, { itemId, quantity }) {
  return jsonRequest(`/mass-stages/${stageId}/return`, "POST", { item_id: itemId, quantity });
}

export async function apiReuseStage(stageId) {
  // Spin off a fresh planning stage from a completed one (same building + rooms,
  // work orders cleared, no items). Returns the new MassStageSummary.
  return jsonRequest(`/mass-stages/${stageId}/reuse`, "POST", {});
}

// Scan-gate quick-add: save a work order with a room. The backend find-or-creates
// the building's active stage and appends the room. Returns the parent
// MassStageSummary (the gate reads room_count). See
// docs/mass-staging/phase-10-saved-workorders.md.
export async function apiQuickAddRoom({ buildingName, roomNumber, workOrderNumber, assignedToId = null }) {
  return jsonRequest("/mass-stages/quick-room", "POST", {
    building_name: buildingName,
    room_number: roomNumber,
    work_order_number: workOrderNumber,
    assigned_to_id: assignedToId,
  });
}

// Flat list of rooms (with work orders) across non-completed stages -- the
// scan gate's tappable work-order cards.
export async function apiListActiveRooms() {
  return parseResponse(await fetch("/mass-stages/active-rooms", { credentials: "include" }));
}
