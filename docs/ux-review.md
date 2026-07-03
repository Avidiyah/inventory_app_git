# UX Review — Proposed Changes

Last reviewed: 2026-07-01

Purpose: a standing list of user-experience findings from a code-level review
of the frontend (no behavior changed by this review itself). Organized by
impact for the primary user — a field crew scanning items on a phone, plus
supervisors/admins doing office-side review and billing.

Each item names the file(s) involved so a future change can go straight to
the relevant view. Update or remove entries here as they're addressed or as
the code moves; delete this file's items once shipped rather than letting it
drift into a stale wishlist.

## Completed

> **Validation pass 2026-07-03** — everything below was exercised end-to-end
> in the browser (preview server, logged in as owner): login UX (#20/#5),
> #16/#17 (debounce + labels, incl. the "+ New community…" reveal), #12/#13
> (search-and-pick, date params on request + export, Clear), #6+#9
> (loading/error rows on History and Find Item), #18 (both pages: validation,
> Cancel byte-restore, partial-bill Save, Don't charge, full-quantity clears
> the override), #4 (reset modal validation/toggle/Esc-clear; void/remove/
> change-WO confirms), #11 (stepper seeds from page field, +/- with floor at
> 1, commits adjusted count, hidden on generic confirms), #3 (quick commit +
> Undo reverts tallies/cache, no double-undo), #7 (Retry re-posts captured
> payload, converts line in place, Retry→Undo swap), #8 (timeout copy gated
> to a real mid-session 401; re-login resumes WO/log/tallies/quick-mode;
> deliberate logout still starts fresh), #10 (audio primes in the tap
> gesture, degrades silently; audible beep needs a real device). Backend
> suite re-run after: 226 passed. Two defects found and fixed during the
> pass — see the #18 and #8 entries.

### Login autofocus + password visibility toggle (was Tier 3 #20)

Shipped 2026-07-01. Username field autofocuses whenever the login screen is
shown (fresh load, logout, session expiry); password field gained a
Show/Hide toggle (`#login-password-toggle`) with `aria-pressed`/`aria-label`
state, resetting to masked on every fresh login screen.

Files: `backend/static/shell-head.html`, `backend/static/views/auth.js`,
`backend/static/styles.css`.

### "Remember this device" label mismatch (was Tier 1 #5)

Shipped 2026-07-01. Checkbox copy changed from "Remember this device" to
"Stay signed in for this shift" to honestly reflect the 12-hour absolute
session cap. Copy-only change; no backend/session behavior touched.

Files: `backend/static/shell-head.html`, `backend/static/styles.css`
(comment only).

### History "Work Order" column overloaded for corrections (was Tier 2 #14)

Shipped 2026-07-01. Column header renamed from "Work Order" to "WO / Reason"
so the header matches what `adjust` (correction) rows actually show in that
cell (the reason, not a work-order number). Updated both the `<th>` and the
matching `data-label` used by the mobile stacked-card view. The "Filter by
Work Order" overlay filter label is unrelated (it genuinely filters by work
order) and was left as-is.

Files: `backend/static/pages/history.html`, `backend/static/views/history.js`.

### Pricing-list export truncation is silent (was Tier 2 #15)

Shipped 2026-07-01. `fetchAllMatchingRows()` now returns `{ rows, total,
truncated }` instead of a bare array. When the 100-page / 10,000-row export
cap is hit, the `historyPricingBtn` click handler shows "Pricing incomplete
— showing N of M matching rows. Narrow the filters for a complete list."
instead of the normal "Pricing ready" success message, reusing the `.error`
style since this is a billing-relevant shortfall worth flagging.

Files: `backend/static/views/history.js`.

### "Delete" meant three different things across the app (was Tier 1 #1)

Shipped 2026-07-01. Standardized on three distinct verbs matching actual
behavior everywhere:

- History's void button now reads "Void" (was "Delete", disagreeing with
  its own `aria-label`); confirm and error text updated to say "void."
- Find Item's row action reads "Archive Item" (was "Delete Item"); confirm
  text now says "Archive ... hidden from lookup and lists, but its history
  is kept" instead of the unqualified "delete." (Checked
  `docs/current-state.md`: items have no restore action like Users does, so
  the confirm text doesn't promise one.)
- Users' icon-only 🗑️ button gained `title`/`aria-label="Archive user
  {name}"` — its confirm text already said "Archive," but the button itself
  had no accessible name.
- Mass Stage's "Delete" stays a true hard delete (unchanged label — it's
  accurate), but its confirm text is now conditional: the `loading`/
  `completed` body's delete button carries `data-stage-loaded`, and when set
  the confirm reads "Items already loaded stay dispensed — this does not
  return them to stock. This cannot be undone." The `planning`-stage delete
  (nothing dispensed yet) keeps the plain "This cannot be undone."

Files: `backend/static/views/history.js`, `backend/static/views/items.js`,
`backend/static/views/users.js`, `backend/static/views/massStage.js`.

### Active work-order batch was lost on reload/eviction (was Tier 1 #2)

Shipped 2026-07-01. Traced the actual mechanism first: it wasn't just that
`transactions.js` kept the batch in module memory (expected), it was that
`auth.js`'s `enterApp()` — called both on an explicit login *and* on every
boot-time session check via `initAuth()` — unconditionally called
`resetBatch()`. So a plain reload with a still-valid session cookie was
wiped exactly like a fresh login.

Fix: `transactions.js` now snapshots the active batch (work order `{id,
number}`, scan/dispense type, running tallies, and the log lines) to
`sessionStorage` on every commit and type toggle (`persistBatch`), and
clears it on `changeWorkOrder`/`resetBatch`. `auth.js`'s `initAuth()` now
calls `enterApp(user, { resume: true })`; only on that boot-check path does
`enterApp` call the new `tryResumeBatch(userId)` before falling back to
`resetBatch()`. `tryResumeBatch`:

- Rejects a snapshot owned by a different user (no cross-account leakage on
  a shared device).
- Re-validates the work order via `apiGetWorkOrder` before trusting it —
  archived/completed/unknown all fail resume (matches the gate's existing
  `status: "in_progress"` card list), clearing the stale snapshot and
  showing "Your previous work order is no longer active — pick another to
  continue." on the gate.
- Treats a network failure (no HTTP response at all) as inconclusive rather
  than "gone" — keeps the snapshot for the next boot attempt instead of
  discarding a possibly-still-valid batch because of a flaky connection,
  which would defeat the point of a field-reliability fix.
- An explicit login submit still always calls `resetBatch()` unconditionally
  (typing credentials back in reads as "start fresh," and covers a different
  user signing into a shared device).

Files: `backend/static/views/transactions.js`, `backend/static/views/auth.js`.

### Every scan required a confirm-modal tap (was Tier 1 #3)

Shipped 2026-07-01. Added a per-batch "Quick mode" toggle (visible to every
role inside an active batch, `#scango-quickmode-toggle`) that, when on,
skips the confirm dialog for a **dispense** commit — Add Stock always
confirms regardless of the toggle, since a mistake there is costlier to
reverse and it's a Supervisor+-only path anyway.

Permission check before implementing surfaced a fork worth recording: voiding
a transaction (`DELETE /transactions/{id}`) is Supervisor+ only, and
Technicians can't reach History either, so a Technician has no self-service
way to undo their own mistake today. Asked the user how Undo should behave
for a Technician's quick-mode scan; decided **Supervisor+-only Undo** — quick
mode ships for everyone (the field crew gets the speed-up), but the Undo
button on a log line only renders (and only works) for Supervisor+. A
Technician's mis-scan still requires flagging a supervisor after the fact,
same as before quick mode existed.

Implementation: `commitScannedItem` captures the created transaction's `id`;
a log line gets an Undo button only when the commit was quick-mode AND the
actor is Supervisor+. Undo calls `apiVoidTransaction`, backs out the
batch tallies and the manual-entry on-hand cache, and marks the line
struck-through so it can't be double-undone. Undo eligibility travels
through the item #2 batch snapshot, so it survives a reload too.

Files: `backend/static/views/transactions.js`, `backend/static/pages/transaction.html`,
`backend/static/styles.css`.

### Native `prompt()`/`confirm()`/`alert()` for sensitive actions (was Tier 1 #4)

Shipped 2026-07-01. Closes out Tier 1. Every remaining native browser dialog
was replaced so the app's own focus-trapped, styled, mobile-reliable UI is
used everywhere.

- **Password reset** (`views/users.js`) — the bare `prompt()` (one field, no
  confirmation, no show/hide, length checked only *after* typing) is now a
  real modal: new `promptPasswordReset(username)` in `dom.js` driving a new
  `#pw-reset-overlay` (`shell-tail.html`) with a new + confirm field, a
  show/hide toggle (reusing the #20 `.password-field`/`.password-toggle-btn`
  CSS), live inline validation (min length + match), Esc/backdrop cancel, a
  Tab focus-trap, and field-clearing on close so a plaintext password isn't
  left in the DOM. It resolves the password on Save or `null` on cancel and
  never resolves an invalid value.
- **Yes/No confirms** — every `confirm()`/`window.confirm()` swapped for the
  existing `await confirmDialog(...)`: Users archive, History void, Find Item
  archive, five Mass Stage confirms, plus three sites outside the original
  finding that had the same pattern (Scan/Stock "change work order" in
  `transactions.js` — its handler is now `async`; the barcode-change warning
  in `itemEditor.js`; the add-barcode confirm in `addBarcode.js`).
- **`alert()` notifications → inline messages** (`setMessage`, the app's
  established pattern). Added a message slot where a page lacked one:
  `#users-message` (Users), `#history-results-message` (History results
  toolbar), `#items-message` (Find Item), `#scango-message` (active batch,
  for the quick-mode Undo failure). Password-reset / restore / archive now
  report success inline too, not just failure.

Files: `backend/static/dom.js`, `backend/static/shell-tail.html`,
`backend/static/pages/saved-users.html`, `backend/static/pages/history.html`,
`backend/static/pages/saved-items.html`, `backend/static/pages/transaction.html`,
`backend/static/views/users.js`, `backend/static/views/history.js`,
`backend/static/views/items.js`, `backend/static/views/massStage.js`,
`backend/static/views/transactions.js`, `backend/static/views/itemEditor.js`,
`backend/static/views/addBarcode.js`.

### History "By Item" required a barcode, not a name search (was Tier 2 #12)

Shipped 2026-07-01. First Tier 2 item. The By Item tab's exact-barcode
lookup (`apiGetItemByBarcode` + a "Look Up" button) is replaced with the
name-or-barcode search-and-pick used everywhere else in the app: the item
list is cached once (`apiListItems`, warmed when the tab opens) and filtered
client-side, results render as tappable `.manual-item-card`s (reusing the
manual-entry / add-item styles), and picking one sets the item filter and
loads its history. Editing the text afterward just searches again — an
explicit pick is still what commits the filter, matching the old
click-to-apply behavior. Only live items are searchable, the same limit the
barcode lookup already had (archived items are hidden from lookup), so this
is not a behavior change — just a much easier way to find the item.

Files: `backend/static/pages/history.html`, `backend/static/views/history.js`.

### History had no date-range filter (was Tier 2 #13)

Shipped 2026-07-01. **First backend change of this effort.** History gains a
From/To date-range overlay filter that, like the work-order filter, shows on
every sub-tab and combines with the others via AND.

- Backend: `GET /transactions/` takes optional `date_from` / `date_to`
  (`YYYY-MM-DD`) query params (`routers/transactions.py`), passed to
  `list_history`. A new pure helper `_date_range_bounds` (`services/history.py`)
  turns the two dates into half-open, tz-aware **UTC** datetime bounds
  (`created_at >= midnight(from)` AND `< midnight(to + 1 day)`), so `to` is
  included in full and there are no inclusive-upper-bound microsecond edge
  cases. A reversed range matches nothing (empty page, not an error). UTC
  boundaries are a documented simplification (a row near local midnight can
  land on the adjacent UTC day) — fine for a filter convenience.
- Tests: `test_history_date_filter.py` — pure, DB-free, mirroring
  `test_history_wo_filter.py` (8 cases: absent sides, single-day window,
  month rollover, tz-awareness, reversed range). Full suite: 226 passed.
- Frontend: two `<input type="date">` + Clear in a filter row
  (`history.html`); `dateFrom`/`dateTo` added to `historyState`
  (`state.js`) and to `apiListTransactions` (`api.js`); wired via `change`
  (no debounce needed) with the empty-state message naming the active date
  range. The **pricing export** (`fetchAllMatchingRows`) sends the same date
  params, so a filtered export stays consistent with the on-screen table.

Files: `backend/app/routers/transactions.py`, `backend/app/services/history.py`,
`backend/tests/test_history_date_filter.py`, `backend/static/state.js`,
`backend/static/api.js`, `backend/static/pages/history.html`,
`backend/static/views/history.js`.

### List-page loads were silent on both pending and failure (was Tier 2 #6 + #9)

Shipped 2026-07-01. Done together because they are two points in one
request's lifecycle on the same three loaders (`loadItems`, `loadUsers`,
`loadHistory`), which previously showed nothing while a fetch was in flight
(#9) and swallowed failures to `console.error` + a blank table (#6) — both
indistinguishable from "empty" on a phone with spotty signal.

Both states now render in the **table body**, deliberately NOT in the
`#4` message slots (`#items-message` / `#users-message` /
`#history-results-message`): those carry row-action success text (e.g.
"Archived …") set immediately before a reload, so routing load state through
them would wipe it. Body rows keep the two concerns separate and reuse the
existing `<p class="hint">Loading…</p>` pattern from Work Orders / Mass
Stage.

- Items, Users: a `Loading…` hint row before every fetch; a red `.error`
  row (via `friendlyError`) on failure. These load on page activation, so a
  brief flash on a post-action reload reads as "refreshing".
- History: the same, but the loading row shows only when results aren't
  already on screen (`historyResults.hidden`), so the debounced work-order /
  date filters don't flicker on every change; failures always show the
  error row.
- Work Orders / Mass Stage list loads were already surfacing errors
  (`setMessage(listMessage, …)`) and are the `Loading…` pattern this borrows
  — left as-is, out of scope.

Files: `backend/static/views/items.js`, `backend/static/views/users.js`,
`backend/static/views/history.js`.

### Search-trigger behavior differed between sibling pages (was Tier 2 #16)

Shipped 2026-07-02. The Work Orders page search required clicking "Search" or
pressing Enter, while History's work-order filter already live-debounced on
every keystroke — the same kind of control on adjacent pages behaving two
different ways. The Work Orders search now live-updates as you type on a
250 ms debounce, matching History (`views/workOrders.js`). The Search button
and Enter are kept as redundant explicit triggers — each clears the pending
debounce and fires immediately — so no one who relied on click-to-search
loses it.

Files: `backend/static/views/workOrders.js`.

### Placeholder-only labels on multi-field forms (was Tier 2 #17)

Shipped 2026-07-02. The New Work Order and New Mass Stage create forms used
input placeholders as their only labels, which disappear once a field is
filled — leaving a row of similar-looking inputs hard to re-check. Both forms
moved from `.filter-row` to a `.form-stack` (vertical, full-width on phones)
with a real `<label for>` on every field; placeholders were demoted to example
hints ("e.g. 19", "e.g. 1121"). The Supervisor+ inline work-order attribute
editor (community / building / unit / assignee) is prefilled with visible
values, so the placeholder-disappears problem doesn't apply there — those
controls got `aria-label`s for an accessible name rather than visible labels,
keeping the inline editor compact.

Files: `backend/static/pages/work-orders.html`,
`backend/static/pages/mass-stage.html`, `backend/static/views/workOrders.js`.

### Billing "Edit charge" editor was duplicated across two pages (was Tier 2 #18)

Shipped 2026-07-02. The inline "Edit charge" editor — its markup plus the
Save / Don't charge / Cancel + validation handler — existed nearly
line-for-line in both `history.js` and `workOrders.js`, a billing-UI drift
risk. Extracted to a shared `views/billingEditor.js` exporting
`openBillingEditor(cell, { quantity, billable, onSave })`: it swaps the cell
for the editor, focuses/selects the input, validates (empty or full-quantity
→ `null` override, out-of-range → inline error), and on Save / Don't charge
calls the page-supplied `onSave(value)` inside a disable-buttons/try-catch,
showing the shared error copy on failure; Cancel and a failed save restore the
cell. Each page keeps only what differs: History passes
`apiSetBillableQuantity(id, …)` + `loadHistory()`, Work Orders passes
`apiSetWorkOrderItemBilling(workOrderId, woItemId, …)` + `refreshCard(cardEl)`.
No behavior change — the extracted logic is identical to what both sites ran
before, and the editor markup / CSS classes were already byte-identical.
Backend suite still green: 226 passed.

Files: `backend/static/views/billingEditor.js` (new),
`backend/static/views/history.js`, `backend/static/views/workOrders.js`.

**Found in the 2026-07-03 validation pass (pre-existing, not a refactor
regression):** the editor's message `<p>` carried its `charge-editor-msg`
styles via that class, but `setMessage()` replaces `className` wholesale
(e.g. with `error`), so the first validation message stripped the compact
styling. Fixed with a structural CSS selector (`.charge-editor p`) that
survives the class swap (`styles.css`).

### Failed scan commit forced a re-scan (was Tier 2 #7)

Shipped 2026-07-02. When `apiCreateTransaction` failed mid-batch, the log
showed "✗ … Could not save. Try again." and the only recourse was to
physically re-scan the item. A failed line now carries a **Retry** button that
re-posts the exact same commit — item, quantity, and type are captured at
failure time (the page quantity field resets to 1 after each scan, so it can't
be trusted later; `quickCommit` rides along too). On success the line converts
in place to a normal commit line (tallies, on-hand cache, summary, and a
Supervisor+ Undo when the original was a quick-mode dispense); on a repeat
failure the message refreshes and Retry stays. The retry payload rides in the
batch snapshot, so it survives a reload like the rest of the batch.

Files: `backend/static/views/transactions.js`, `backend/static/styles.css`.

### Committed scans had no non-visual confirmation on iOS (was Tier 2 #10)

Shipped 2026-07-02. `buzz()` uses the Vibration API, a documented no-op on iOS
Safari, so an iPhone gave zero physical feedback on a committed scan. Added a
short WebAudio blip (`beep`) alongside every `buzz()`: one bright tone on a
successful commit, two low tones on a failure/refusal, silent on a plain
decline (saying No is not an error). The audio context is created and resumed
from the Scan/Upload tap (a user gesture) so autoplay policies don't block it;
where WebAudio is unavailable it's a silent no-op, same as `buzz`.

Files: `backend/static/views/scan.js`.

### Quantity control sat below the camera viewport (was Tier 2 #11)

Shipped 2026-07-02. Adjusting a non-1 quantity meant scrolling past the live
camera to the page field and back, and it reset to 1 after each commit. The
scan-and-go confirm modal now carries an inline +/- quantity **stepper**: the
shared `dom.confirmDialog` gained an optional `{ quantity }` mode (generic
yes/no callers unchanged) that reveals the stepper and returns the chosen count
instead of a bare boolean. `commitScannedItem` seeds the stepper from the page
field and commits the value the operator confirms. Quick mode has no modal, so
it still commits the page-field quantity; the page field stays (it seeds the
stepper and serves quick mode).

Files: `backend/static/shell-tail.html`, `backend/static/dom.js`,
`backend/static/views/transactions.js`, `backend/static/styles.css`.

### Session expiry mid-batch was unexplained, and lost the work order (was Tier 2 #8)

Shipped 2026-07-02. Two parts:

- **Reassurance copy.** A mid-session 401 used to drop the operator to the
  login screen with no message at all; it now shows "Your session timed out —
  any scans you already saved are safe in the work order's history. Sign in to
  pick up where you left off." The message is gated to a real mid-session
  expiry (the app was open when the 401 fired), so a plain not-signed-in boot —
  where the global 401 handler also fires — stays quiet; explicit logout is
  unaffected.
- **Resume the work order after re-login.** A timeout now *preserves* the batch
  snapshot (`resetBatch({ keepSaved: true })`) instead of clearing it, and the
  login submit passes `enterApp(user, { resume: true })`. The resume itself is
  still gated by the #2 `tryResumeBatch`: it only proceeds when the snapshot
  survived (preserved on a timeout, cleared on a deliberate logout) AND the
  re-authenticating user owns it AND the work order is still active. So a
  same-user expiry re-login picks the batch back up (matching #2's
  reload-resume), while a clean logout, a different user on a shared device, or
  a since-archived WO all fall through to a fresh gate. This extends #2's
  "login = fresh" *only* for the expiry case — a deliberate product call given
  the shared-device / re-auth boundary.

Files: `backend/static/views/auth.js`, `backend/static/views/transactions.js`.

**Found in the 2026-07-03 validation pass:** an undone log line's
strike-through did not survive the snapshot round-trip — the entry recorded
the "— Undone" text but not the state, so after a resume an undone line
looked like a normal commit. Fixed by persisting `entry.undone = true` in the
undo handler and re-applying `scango-log-undone` in `renderLogLine` on
restore (`transactions.js`); verified across a reload.

## Tier 2 — Feedback, discoverability, and consistency

_All Tier 2 items are now in the Completed section above._

## Tier 3 — Polish and opportunities

### 19. Flat, text-only top nav

Up to 8 nav buttons render as plain text at `--fs-sm` (`shell-head.html`),
wrapping to 2–3 rows on a phone. Icons plus grouping related pairs (Add/Find
Item, Add/Users) would speed one-handed, gloved use and reduce vertical
space taken by the header.

Files: `backend/static/shell-head.html`, `backend/static/styles.css`,
`backend/static/views/nav.js`.

### 21. Supervisor+ "Add Stock" path is one toggle deep

The direction toggle (Add Stock / Take Out) is hidden behind "Manual entry &
stock options" (`transaction.html`) by default. Reasonable given
dispense-only is the common case — flagging for confirmation this
discoverability tradeoff is intended, not accidental.

Files: `backend/static/pages/transaction.html`,
`backend/static/views/transactions.js`.

### 22. No search on the Supervisor/Admin work-order gate cards

Technicians see only their assigned cards, but a Supervisor/Admin/Owner's
gate (`transactions.js` `refreshWoCards`) lists every in-progress work
order as an unfiltered card grid. Past roughly 20 work orders this becomes
a wall of cards; the Work Orders page already has a working search pattern
that could be reused above the grid.

Files: `backend/static/views/transactions.js`,
`backend/static/pages/transaction.html`.

### 23. No hardware (keyboard-wedge) barcode scanner support

A Bluetooth laser scanner typically types the barcode plus Enter, faster
and more reliable in warehouse lighting than camera decoding. Today those
keystrokes go nowhere unless a text input happens to be focused. A global
fast-keystroke accumulator on the Transaction page feeding into the existing
`resolveBarcode` path would add this without disturbing the current camera
flow.

Files: `backend/static/views/scan.js`, `backend/static/views/transactions.js`.

### 24. No low-stock signal until a dispense is rejected

Mass Stage already computes and displays "short by N" during staging
(`massStage.js` `shortBy`/`coverageHtml`), but Find Item never surfaces low
stock — the first signal is a rejected dispense on the floor. Highlighting
quantity at or below a threshold on the Find Item table would let
supervisors act before the crew hits a wall, even without a formal
reorder-point field.

Files: `backend/static/views/items.js`, `backend/static/pages/saved-items.html`.

## Suggested starting point

**Tier 1 and Tier 2 are fully cleared** (#6+#9, #12, #13, #16, #17, #18, and
the scan-loop cluster #7, #8, #10, #11 — including #8's resume-after-re-login).
What remains is **Tier 3 polish** (#19 nav icons, #21/#22 discoverability, #23
hardware/keyboard-wedge scanner, #24 low-stock signal on Find Item) — none of
it discussed with the user yet.

Note: the whole effort is still uncommitted on `main` and none of Tier 2 has
been manually validated. Suggested before Tier 3: a hands-on pass over the
scan-loop cluster, then a commit to checkpoint the batch.
