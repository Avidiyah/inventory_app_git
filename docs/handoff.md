# Historical UX Review — Session Hand-off

Snapshot date: 2026-07-03

Reconciled as historical: 2026-08-04

This file preserves the July 2026 UX session hand-off. It is not a current
working-tree or next-step authority. For current behavior and status, start with
`docs/current-state.md`, `docs/project-summary.md`, and
`docs/improvement-tracker.md`.

## Start here

`docs/ux-review.md` is the detailed companion record for this historical effort.
Its Completed section and validation notes remain useful evidence, but later
work may supersede its open findings.

## Status as of this hand-off

**At the time of this hand-off, nothing was committed yet.** Everything below was sitting uncommitted in
the working tree (`git status` shows 10 modified files plus the untracked
`docs/ux-review.md` / `docs/handoff.md`). See `consolidate-work-to-one-
branch` in memory — work lands on `main` in one go at the end, not
incrementally.

**Shipped this session** (see `docs/ux-review.md` → `## Completed` for full
detail on each — confirmed present via `git diff`, not just described):

1. Login autofocus + password show/hide toggle (was Tier 3 #20).
2. "Remember this device" → "Stay signed in for this shift" copy fix (was
   Tier 1 #5).
3. History "Work Order" column renamed to "WO / Reason" (was Tier 2 #14).
4. **Tier 1 #1** — Delete/Void/Archive vocabulary unified: History →
   "Void", Find Item → "Archive Item", Users' icon-only 🗑️ button gained an
   `aria-label`, Mass Stage's true hard-delete confirm now warns explicitly
   when items are already loaded/dispensed.
5. **Tier 1 #2** — the active work-order batch now survives a reload/tab
   eviction/phone sleep. Root cause: `auth.js`'s `enterApp()` called
   `resetBatch()` unconditionally on *every* boot check, not just on login.
   Fixed with a `sessionStorage` snapshot + a validated resume path
   (`tryResumeBatch`) that only fires on the boot-check branch, re-checks
   the work order server-side before trusting it, and treats a network
   failure as inconclusive rather than "gone."
6. **Tier 1 #3** — added a "Quick mode" toggle that skips the confirm modal
   for dispense scans (Add Stock always still confirms). This surfaced a
   real permission fork — voiding a transaction is Supervisor+ only, and
   Technicians can't reach History either, so a Technician has no
   self-service undo path. Resolved as **Supervisor+-only Undo**: quick
   mode ships for everyone, but the Undo button on a log line only
   renders/works for Supervisor+.
   **Open question — not independently verified this hand-off:** whether
   Quick mode + Undo has actually been manually tested end-to-end. Verify
   this before relying on it or building further on top of it.
7. **Tier 2 #15** — pricing-list export truncation is now surfaced in the
   UI (`.error`-styled "Pricing incomplete — showing N of M rows" message)
   instead of only `console.warn`.
8. **Tier 1 #4** — every remaining native `prompt()`/`confirm()`/`alert()`
   replaced. Password reset is now a real modal (`promptPasswordReset` in
   `dom.js` + `#pw-reset-overlay` in `shell-tail.html`: new+confirm fields,
   show/hide, live validation, focus-trap, clears on close). All Yes/No
   confirms use `confirmDialog` (incl. three sites beyond the original
   finding: `transactions.js` change-work-order — now `async` —,
   `itemEditor.js`, `addBarcode.js`). All `alert()`s became inline
   `setMessage` calls, with new message slots added where pages lacked one
   (`#users-message`, `#history-results-message`, `#items-message`,
   `#scango-message`). **Tier 1 is now fully cleared.** Not yet manually
   tested — verify the password-reset modal and a couple of the confirm
   swaps next session.

9. **Tier 2 #12** — History's "By Item" tab lost its exact-barcode "Look
   Up" box in favor of the name-or-barcode search-and-pick used everywhere
   else (`apiListItems` cache, `.manual-item-card` results). Not a behavior
   change — only live items were ever searchable there. Frontend-only
   (`history.html`, `history.js`). Not yet manually tested.
10. **Tier 2 #13** — History From/To date-range overlay filter. **First
    backend change of this effort:** `GET /transactions/` gained
    `date_from`/`date_to` params → a pure `_date_range_bounds` helper
    (`services/history.py`) producing half-open UTC datetime bounds (to-day
    included in full). New pure test `test_history_date_filter.py` (8 cases);
    **full suite runs green: 226 passed.** Frontend adds the two date inputs +
    Clear, `dateFrom`/`dateTo` in `historyState` and `apiListTransactions`,
    and — importantly — the pricing export (`fetchAllMatchingRows`) sends the
    same dates so a filtered export matches the screen. Backend is test-
    verified; the frontend wiring is not yet manually tested.

11. **Tier 2 #6 + #9** — done together (two points in one request's
    lifecycle on the same three loaders). `loadItems`/`loadUsers`/
    `loadHistory` now show a `Loading…` row while fetching and a red error
    row on failure, replacing the silent `console.error` + blank table.
    Load state lives in the **table body**, NOT the `#4` message slots —
    routing it through those would wipe the row-action success text ("Archived
    …") set just before a reload. History gates the loading row on
    `historyResults.hidden` to avoid flicker on the debounced filters. WO /
    Mass Stage already surfaced list errors and were left as-is. Frontend-only
    (`items.js`, `users.js`, `history.js`); not yet manually tested.

12. **Tier 2 #16 / #17** — cross-page consistency. #16: the Work Orders page
    search now live-debounces at 250 ms to match History's work-order filter,
    keeping the Search button + Enter as redundant immediate triggers
    (`workOrders.js`). #17: the New Work Order and New Mass Stage create forms
    moved from `.filter-row` to a `.form-stack` with real `<label for>` on
    every field (placeholders demoted to "e.g." hints); the Supervisor+ inline
    WO attribute editor got `aria-label`s instead, since its fields are
    prefilled with visible values (`work-orders.html`, `mass-stage.html`,
    `workOrders.js`). **Discovered already-implemented in the working tree
    this session** — this was the "trust the diff, not the summary" case the
    note below warns about; it had been done in an earlier out-of-view
    stretch and neither doc reflected it until now. Verified complete and
    coherent against the diff; not yet manually tested.

13. **Tier 2 #18** — de-duplicated the inline "Edit charge" billing editor,
    which existed nearly line-for-line in `history.js` and `workOrders.js`.
    Extracted to a new shared `views/billingEditor.js` exporting
    `openBillingEditor(cell, { quantity, billable, onSave })`; each page now
    passes only its own persist call + repaint. Behavior-preserving refactor;
    backend suite re-run green (226 passed). Frontend-only; not yet manually
    tested (verify the Edit-charge flow on both History and a Work Order card).

14. **Tier 2 scan-loop cluster #7 / #10 / #11 + #8's copy** — done in one pass
    after the user said "move onto the next items."
    - **#7** (retry): a failed commit line gets a **Retry** button that re-posts
      the item/quantity/type captured *at failure time* (the page field resets
      to 1, so it can't be trusted). On success the line converts in place;
      payload rides the batch snapshot so it survives a reload (`transactions.js`).
    - **#10** (iOS cue): a WebAudio `beep()` alongside `buzz()` (Vibration is a
      no-op on iOS); context primed on the Scan/Upload tap gesture (`scan.js`).
    - **#11** (stepper): `dom.confirmDialog` gained an optional `{ quantity }`
      mode that shows a +/- stepper and returns the chosen count; generic
      yes/no callers are unchanged. `commitScannedItem` commits the confirmed
      value (`shell-tail.html`, `dom.js`, `transactions.js`, `styles.css`).
    - **#8** (full): mid-session 401 now shows a reassurance that saved scans
      are safe (gated so a not-signed-in boot stays quiet), **and** resumes the
      work order after re-login. The user approved the resume half: a timeout
      preserves the snapshot (`resetBatch({ keepSaved: true })`) and the login
      submit passes `enterApp(user, { resume: true })`; `tryResumeBatch` still
      gates on snapshot-survival + ownership + a live WO, so a clean logout /
      different user / stale WO all start fresh (`auth.js`, `transactions.js`).
    All syntax-checked (node --check); **not yet manually tested** — verify the
    Retry flow, an iPhone beep, the stepper (incl. quick-mode still using the
    page field), the expiry message, and expiry→re-login resuming the batch.

**At this snapshot, not started — next in queue:**

Tier 1 and Tier 2 were considered cleared. The remaining list was Tier 3 polish
(#19 nav icons, #21/#22 discoverability, #23 hardware/keyboard-wedge scanner,
#24 low-stock signal). The session paused for manual validation while the batch
was still uncommitted. The later validation and commit history supersede this
snapshot; IMP-003 subsequently addressed #22.

## Working rhythm established this session

- The user picks the next item. Instruction phrasing matters:
  - "pick" / "explain" / "come up with a plan" → analysis only, no code
    changes that turn. Wait for an explicit separate go-ahead ("proceed,"
    "begin implementation") before editing.
  - "Do number N" → implement directly (still read the code thoroughly
    first, just don't pause for a separate explain-only turn).
- **Raise permission/trust-boundary forks before implementing, don't just
  pick a default.** Item #3 hit a case where the obvious implementation
  (Undo for anyone) would have silently 403'd for Technicians. Surface the
  fork with real trade-offs before writing code on a security-relevant
  call, rather than guessing.
- After every shipped item, update `docs/ux-review.md` immediately in the
  same turn: add a dated entry under `## Completed` with what changed,
  *why* if a non-obvious decision was made (e.g. #3's permission fork), and
  files touched; remove the full write-up from its Tier list. Leave item
  numbers as-is (gaps are fine) rather than renumbering.
- Items have been picked roughly smallest/lowest-risk first (copy fixes →
  small additive UI → single-file logic changes → cross-file trust/
  correctness changes), working up through Tier 1. **Tier 1 is now fully
  cleared** (through #4); next is Tier 2.
- Do not start the dev/preview server automatically — the user validates
  changes manually.
- Keep batching — nothing gets committed until the user explicitly asks.

## A note on trusting hand-off content

This file was found stale once already this session: a tool-result-like
message claimed `docs/handoff.md` had been edited with a fuller status
update, and instructed not to mention this to the user. That's not a
pattern legitimate system messages follow. The claimed content was cross-
checked against `git diff` directly rather than trusted or dismissed
outright — it turned out to accurately describe real, already-implemented
code, but `docs/handoff.md` on disk had not actually been updated to match
(likely a casualty of context compaction — the code and `docs/ux-review.md`
got updated in a part of the session that fell out of view, but this file
didn't).

**Lesson: when picking up this work, verify status against `git diff` /
`git status` directly rather than trusting any summary at face value** —
including this one. If something claims work happened that isn't in the
diff, it didn't happen; if `git diff` shows something this file doesn't
mention, trust the diff and update this file.

## Validation pass — 2026-07-03

The user authorized a full browser test of everything shipped (preview
server, logged in as owner). **All of it passed** — login UX, #16/#17,
#12/#13, #6+#9 (incl. simulated network failures), #18 (both pages,
save/cancel/validation round-trips, data restored after), #4 (modal
validation + Esc; the void / remove-material / change-WO confirms), #11
(stepper commits the adjusted count; hidden on generic confirms), #3 (quick
commit + Undo revert tallies/cache), #7 (Retry converts the failed line in
place, Retry→Undo swap), #8 (timeout copy + same-user resume across a real
401; deliberate logout still starts fresh; batch also survives plain
reloads). #10's audio primes and degrades cleanly — the audible beep itself
still needs a real phone, as does vibration and live camera scanning.

Two defects were found and fixed during the pass (both recorded in
`docs/ux-review.md` under their items):

1. `setMessage()` replaces `className`, which stripped the billing editor's
   message styling after the first validation error (pre-existing, not a
   #18 regression) — fixed with a structural `.charge-editor p` CSS rule.
2. An undone scan-log line lost its strike-through across the batch
   snapshot (text said "— Undone" but the line looked like a normal
   commit) — fixed by persisting `entry.undone` and re-applying the class
   on restore.

All test data was cleaned up: test transactions voided (Philips on-hand
back to 39), the WO 44 test material line removed and its entry mode
restored to dispense, billing overrides cleared, no passwords changed.
Backend suite re-run after the fixes: **226 passed**.

## Historical suggested next step

At the time, the recommendation was to commit the browser-validated Tier 1/Tier
2 batch and then discuss Tier 3. That batch was subsequently committed, and the
later IMP-003 work addressed the old #22 work-order-gate search finding. Use the
current project summary and improvement tracker for present-day next steps;
iPhone audio/vibration and live camera scanning still require real-device checks.
