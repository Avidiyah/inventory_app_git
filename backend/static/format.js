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

// FastAPI returns validation errors as `detail: [{msg, loc, ...}]`
// and business errors as `detail: "text"`. This collapses both
// shapes into a single string for `setMessage`.
export function formatError(detail, fallback) {
  if (Array.isArray(detail)) {
    return detail.map(d => d.msg).join("; ");
  }
  return detail || fallback;
}
