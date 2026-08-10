# UX Review — the findings still open

Review period: 2026-07-01 through 2026-07-03. Reconciled as historical
2026-08-04. **De-cluttered 2026-08-10**: the completed items and their
browser-validation evidence moved to `docs/ux-review-archive.md`, leaving this
file as what it is actually for — the four July findings that were never
promoted or dismissed.

This is **not** a current-state authority. Use `docs/current-state.md` for
behavior, and `docs/open-work.md` for the cross-doc index of everything open.

Each item names the file(s) involved so a future change can go straight to the
relevant view. Move an entry to the archive once it ships rather than letting
this drift into a stale wishlist.

## Completed — moved to `docs/ux-review-archive.md`

The 390 lines of per-item detail and browser-validation evidence for the
shipped July findings now live in **`docs/ux-review-archive.md`**. Moved
2026-08-10; nothing deleted or edited.

Tier 1 and Tier 2 are both fully shipped. What remains open is Tier 3 below.

## Tier 3 — Polish and opportunities — **the only open tier**

Tier 1 and Tier 2 both shipped in full; see the archive. Everything below has
**never been re-audited as a current priority** — treat these as observations
from July 2026, not as agreed work. Numbers are the original review's and are
not renumbered.

### 19. Flat, text-only top nav — **closed 2026-08-10, shipped as IMP-033**

Promoted into `docs/improvement-tracker.md` as **IMP-033** and implemented the
same day: four task-domain groups separated by a hairline, an inline SVG icon on
every button, tap targets unchanged at 44px.

**The finding's own premise was half wrong, and the correction is worth
keeping.** It said "up to 8 nav buttons" and framed the benefit as faster
"one-handed, gloved use". Measured: the bar declares **11** buttons, but role
gating means a **Technician — the gloved phone user it was written for — only
ever sees four**, in two groups, and never wraps. The 11-button case belongs to
Admin and Owner, who work office-side. So the grouping serves Admin/Owner
scanning and the icons serve everyone; the gloved-use argument was aimed at the
role with the fewest buttons.

Files: `backend/static/shell-head.html`, `backend/static/styles.css`,
`backend/static/views/nav.js`.

### 21. Supervisor+ "Add Stock" path is one toggle deep

The direction toggle (Add Stock / Take Out) is hidden behind "Manual entry &
stock options" (`transaction.html`) by default. Reasonable given
dispense-only is the common case — flagging for confirmation this
discoverability tradeoff is intended, not accidental.

Files: `backend/static/pages/transaction.html`,
`backend/static/views/transactions.js`.

### 22. Work-order gate card search (addressed later)

This July finding is no longer open. IMP-003 added a compact Supervisor+
work-order-number search card above the scoped Scan / Stock cards with debounced
server-side filtering. Selecting a result card, rather than typing a number,
starts the batch; Created/Assigned selections now redirect through the IMP-011
In-Progress gate.

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

## Historical close-out

Tier 1 and Tier 2 were browser-validated on 2026-07-03 and later committed.
IMP-003 subsequently resolved #22, and **#19 was promoted to IMP-033 and shipped
on 2026-08-10**. The remaining Tier 3 observations (**#21, #23, #24**) have not
been re-audited as current priorities; promote one into
`docs/improvement-tracker.md` before treating it as active work — that promotion
step is what #19 followed, and it is not optional.
