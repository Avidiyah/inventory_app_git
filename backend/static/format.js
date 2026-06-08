// Foundation: pure value formatting helpers.
//
// Layer: foundation. Imported by every view. No DOM access, no
// fetches, no state -- just `value in / string out` so the
// functions are trivially testable and safe to reuse.

// XSS guard for any backend-supplied text that the view injects
// into `innerHTML`. Views that build strings (history rows, item
// cards, notes summaries) MUST run user content through this.
export function escapeHtml(value) {
  if (value === null || value === undefined) return "";
  return String(value)
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&#39;");
}

// Booleans need to render as the literal text "true"/"false"
// rather than empty string (which is what default `String(false)`
// would produce in many template contexts).
export function formatNoteValue(v) {
  if (typeof v === "boolean") return v ? "true" : "false";
  return v;
}

// Used by the notes editor to pick the correct input control
// (checkbox / number / text) when editing an existing note.
export function detectNoteType(v) {
  if (typeof v === "boolean") return "boolean";
  if (typeof v === "number") return "number";
  return "string";
}

// Format a numeric/string amount as USD currency (e.g. 12.5 -> "$12.50").
// Returns "" for null/undefined/blank/non-numeric so callers can fall
// back to an em dash. Prices arrive from the API as JSON numbers or
// strings (serialised Decimal); Number() handles both.
export function formatMoney(value) {
  if (value === null || value === undefined || value === "") return "";
  const n = Number(value);
  if (Number.isNaN(n)) return "";
  return n.toLocaleString(undefined, { style: "currency", currency: "USD" });
}

// Return `url` only if it is a safe http(s) link, else "". Guards the
// product-link cell against `javascript:` / `data:` URLs being placed in
// an href. The value is still passed through `escapeHtml` by the caller.
export function safeHttpUrl(url) {
  if (typeof url !== "string") return "";
  const trimmed = url.trim();
  if (/^https?:\/\//i.test(trimmed)) return trimmed;
  return "";
}

// FastAPI returns validation errors as `detail: [{msg, loc, ...}]`
// and business errors as `detail: "text"`. This collapses both
// shapes into a single string for `setMessage`.
export function formatError(detail, fallback) {
  if (Array.isArray(detail)) {
    return detail.map(d => d.msg).join("; ");
  }
  return detail || fallback;
}

// Map a thrown API error to a short, field-friendly message. `err` is
// the `{ status, detail }` shape thrown by api.js, or a network failure
// with no `status`. Connection / session / permission / insufficient-stock
// get crew-friendly wording with a next step; anything else falls back to
// the backend detail via `formatError`, then to `fallback`.
export function friendlyError(err, fallback) {
  if (!err || err.status === undefined) {
    return "Could not reach the app. Check your signal and try again.";
  }
  if (err.status === 401) {
    return "You were signed out. Sign in again.";
  }
  if (err.status === 403) {
    return "Your account can't do that. Ask a supervisor if this seems wrong.";
  }
  if (err.detail === "Insufficient stock to dispense.") {
    return "Not enough stock available. Check the count before taking more out.";
  }
  return formatError(err.detail, fallback);
}
