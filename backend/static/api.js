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
    throw { status: response.status, detail };
  }
  return body;
}

// Shared helper for POST/PATCH/PUT bodies. GETs and DELETEs go
// straight through `fetch` because they have no JSON payload.
async function jsonRequest(url, method, payload) {
  const response = await fetch(url, {
    method,
    headers: { "Content-Type": "application/json" },
    body: JSON.stringify(payload),
  });
  return parseResponse(response);
}

// --- Items -------------------------------------------------------
export async function apiListItems() {
  return parseResponse(await fetch("/items/"));
}

export async function apiCreateItem({ barcode, name, location, quantity }) {
  return jsonRequest("/items/", "POST", { barcode, name, location, quantity });
}

export async function apiDeleteItem(itemId) {
  return parseResponse(await fetch(`/items/${itemId}`, { method: "DELETE" }));
}

export async function apiUpdateNotes(itemId, notesDict) {
  return jsonRequest(`/items/${itemId}/notes`, "PATCH", { notes: notesDict });
}

export async function apiGetItemByBarcode(barcode) {
  // Barcodes may contain characters that need URL-escaping (e.g.
  // `/` or `#`); raw values would silently mis-route.
  return parseResponse(await fetch(`/items/${encodeURIComponent(barcode)}`));
}

// --- Users -------------------------------------------------------
export async function apiListUsers() {
  return parseResponse(await fetch("/users/"));
}

export async function apiCreateUser({ username }) {
  return jsonRequest("/users/", "POST", { username });
}

export async function apiDeleteUser(userId) {
  return parseResponse(await fetch(`/users/${userId}`, { method: "DELETE" }));
}

// --- Transactions ------------------------------------------------
export async function apiListTransactions({ page, pageSize, itemId, userId }) {
  const params = new URLSearchParams();
  params.set("page", page);
  params.set("page_size", pageSize);
  // Filters are omitted when null/undefined so the backend sees
  // them as "all" rather than as `item_id=null`.
  if (itemId) params.set("item_id", itemId);
  if (userId) params.set("user_id", userId);
  return parseResponse(await fetch(`/transactions/?${params.toString()}`));
}

export async function apiCreateTransaction(payload) {
  // Build the body explicitly rather than spreading -- the backend
  // schema rejects unknown keys, and dropping a missing
  // `work_order_number` keeps the wire format clean.
  const body = {
    item_id: payload.item_id,
    transaction_type: payload.transaction_type,
    quantity: payload.quantity,
    user_id: payload.user_id,
  };
  if (payload.work_order_number) body.work_order_number = payload.work_order_number;
  return jsonRequest("/transactions/", "POST", body);
}
