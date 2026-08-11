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

// --- search normalization ------------------------------------------------
//
// The browser twin of `_separated` / `_squashed` in
// `app/services/items.py`. Most search boxes in the app filter a
// client-side list and never reach the backend, so the rule has to live
// in both places; `tests/test_search_parity.py` runs this file under node
// against the Python implementation so they cannot drift.
//
// Crews do not retype the symbols a manufacturer put in a product name, so
// punctuation must stop deciding whether an item can be found. Both the
// stored text and the typed query are reduced to two forms, and a token may
// match either:
//
//   separated  quotes deleted, every other non-alphanumeric run -> one space
//              'PL-C 26W Compact Fluorescent' -> 'pl c 26w compact fluorescent'
//   squashed   every non-alphanumeric character deleted, spaces included
//              'PL-C 26W Compact Fluorescent' -> 'plc26wcompactfluorescent'
//
// Quotes are DELETED rather than spaced so an inch mark closes up: `2"x4"`
// becomes `2x4`, which is what a crew member actually types. The squashed
// form is what lets `PLC` find `PL-C ...` and `gelcoat` find `Gel-Coat ...`.
//
// The class is deliberately ASCII `[^a-z0-9]`, not `\p{L}\p{N}` -- it has to
// agree exactly with Postgres and Python, and the three disagree on
// non-ASCII input.
const SEARCH_QUOTES_RE = /['"]/g;
const SEARCH_NON_ALNUM_RE = /[^a-z0-9]+/g;

export function separatedForSearch(text) {
  if (text === null || text === undefined) return "";
  return String(text)
    .toLowerCase()
    .replace(SEARCH_QUOTES_RE, "")
    .replace(SEARCH_NON_ALNUM_RE, " ")
    .trim();
}

export function squashedForSearch(text) {
  if (text === null || text === undefined) return "";
  return String(text).toLowerCase().replace(SEARCH_NON_ALNUM_RE, "");
}

// Normalized tokens of a raw query. `""` for a query that is blank or that
// normalizes away to nothing (`"""`, `---`) yields an empty array.
export function searchTokens(query) {
  const separated = separatedForSearch(query);
  return separated ? separated.split(" ") : [];
}

// Does `fields` satisfy `query`? Every token must appear as a substring of
// the separated or squashed form of at least one field. Null/undefined
// fields are skipped, so callers can pass an optional barcode directly.
//
// An empty query matches EVERYTHING -- a predicate with no criteria excludes
// nothing. Views where a blank box should show no rows (Find Item, Add
// Barcode) already return early before filtering and must keep doing so.
export function matchesSearch(fields, query) {
  const tokens = searchTokens(query);
  if (tokens.length === 0) return true;
  const haystacks = [];
  for (const field of fields) {
    if (field === null || field === undefined) continue;
    haystacks.push(separatedForSearch(field), squashedForSearch(field));
  }
  return tokens.every(token => haystacks.some(hay => hay.includes(token)));
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

// Human-facing identity. Usernames are login/account-management identifiers
// and must not leak onto operational pages.
export function formatUserName(user) {
  if (!user) return "Name unavailable";
  const fullName = typeof user.full_name === "string" ? user.full_name.trim() : "";
  if (fullName) return fullName;
  const parts = [user.first_name, user.last_name]
    .filter((part) => typeof part === "string" && part.trim())
    .map((part) => part.trim());
  return parts.join(" ") || "Name unavailable";
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
