# Plan / decision record: Scan-and-go work-order batches

Status: **shipped**. This records the design and the decisions behind the
work-order-gated batch transaction flow on the Transaction page. For the
day-to-day behavior see `docs/spec.md` → "Transaction Page (scan-and-go)".

## Problem

The old Transaction page was scan-*then*-form: scan an item, a form opens,
then you pick a direction, type a quantity, and Save. For a construction
crew stocking/dispensing many items against a single work order on a phone,
that is too many steps per item and the work order had to be re-typed every
time.

## Goal

After sign-in the operator should: enter a work order **once**, then for
each item pick a direction + quantity and **scan** — the scan itself
records the transaction (item from the barcode, user from the session,
work order from the batch). The crew should be able to run many items
through one work order with no re-typing of the work order.

## Decisions

1. **Everyone lands on the Transaction page** (was: Find Item). It opens on
   a work-order gate so the first action after sign-in is to start a batch.
   `auth.js` `enterApp` → `resetBatch()` + `showPage("transaction")`.

2. **Two-state page.** State A is the work-order gate (one big input +
   Start; a non-empty work order is required). State B is the active batch:
   work-order header + Change button, direction control, big quantity, the
   scanner, and a running log with a `N scans, M units` summary. State is a
   module variable `batchWorkOrder` in `views/transactions.js` (null = gate).

3. **Scan commits in place.** The Transaction-page scanner runs in a new
   **continuous mode** (`views/scan.js`): a decode is looked up
   (`GET /items/{barcode}`) and committed (`POST /transactions/`) via
   `commitScannedItem`, instead of opening the form. Both live and upload
   paths funnel through `resolveAndCommit`. The legacy `focusItemByBarcode`
   table-narrowing path was removed (it had no caller left).

4. **Technicians are dispense-only.** New domain predicate
   `roles.can_transact(role, type)`: any recognised role may `dispense`,
   `stock` requires Supervisor+. Enforced in `create_transaction` (the
   route gate dropped from `require_min_role(SUPERVISOR)` to
   `get_current_user` + the predicate; a Technician stocking gets 403).
   `PAGE_ACCESS.transaction` gained `technician`. The UI hides the
   Stock/Dispense toggle for Technicians and shows a fixed "Taking out
   stock" indicator. Other transaction routes are unchanged
   (`adjust` = Admin+, void = Supervisor+).

5. **Manual fallback kept for Supervisor+.** The items table + per-row
   buttons + New Transaction form remain below the scan-and-go flow for
   Supervisor/Admin/Owner. Technicians never see them.

6. **Quantity resets after each commit.** Forces a deliberate count per
   item and doubles as a guard (a scan is refused unless quantity > 0 —
   `scanGoArmed`). Only the work order persists across scans.

7. **Continuous camera + double-count guards.** Rather than stop/restart
   the camera per item (slow, can re-prompt for permission), the camera
   stays live for the whole batch. Two guards stop a label still in frame
   from being counted twice:
   - **Dwell** (`DWELL_MS = 1200`): every decode is ignored for ~1.2 s
     after a commit, while the confirmation shows.
   - **Same-barcode cooldown** (`COOLDOWN_MS = 3000`): for ~3 s only the
     just-committed barcode is suppressed; a *different* item commits
     immediately. Set only on a successful commit, so a refused scan
     (no quantity / overdraw / unknown) does not block the eventual commit.

8. **Haptic feedback.** `navigator.vibrate(60)` on a committed scan,
   `vibrate([40,40,40])` on any failure; silent no-op where unsupported.

9. **Change work order** returns to the gate; if any scans were logged it
   confirms first, then clears the on-screen log. Saved scans stay in
   history. It calls the injected `resetScanUi` (= `scan.js` `resetScan`)
   to stop the camera, keeping the view dependency one-way (scan →
   transactions).

10. **Unknown-barcode "Create Item" shortcut suppressed** in this flow —
    it would derail a hands-busy batch, and the floor crew cannot create
    items anyway.

## Notable implementation detail

`[hidden] { display: none !important; }` was added to `styles.css`. The
scan-and-go containers set `display: flex` (and `.segmented` sets it too),
which silently defeated the `hidden` attribute the JS toggles. The global
rule makes `hidden` authoritative everywhere. (Caught during preview
verification — both states were rendering at once.)

## Files

- Backend: `app/domain/roles.py` (`can_transact`), `app/routers/transactions.py`
  (conditional gate), tests in `tests/test_roles.py` + `tests/test_route_role_gates.py`.
- Frontend: `static/index.html` (gate + State B markup), `static/views/scan.js`
  (continuous mode), `static/views/transactions.js` (orchestration),
  `static/views/nav.js` (access + page-enter), `static/views/auth.js` (landing
  + batch reset), `static/main.js` (inject `setScanResetter`), `static/styles.css`.

## Verification

- `pytest` (51 passed) including the new `can_transact` and route-gate tests.
- Live preview (owner + technician sessions): landing on the gate, gate →
  State B transition, role-correct State B (toggle + manual table for
  Supervisor+, fixed dispense + no table for Technician), commit wire format
  end-to-end (`GET /items/{barcode}` → `POST /transactions/` with the work
  order, on-hand decremented), and the backend gate (technician dispense
  201, technician stock 403).

## Follow-ups / not done

- The continuous-camera guard timings (1.2 s / 3 s) were validated by code
  review, not on real devices in the field; revisit if double-counts or
  sluggishness show up, alongside `docs/plan-scan-tuning.md`.
- Obsidian project memory (per `AGENTS.md`) was **not** updated — no Obsidian
  MCP access in this session. Sync the repo-doc area when next available.

## Addendum — 2026-06-10: simplified per-scan flow

Field feedback wanted the floor job to be "open, sign in, scan, move on." Three
decisions above were revised:

- **Decision #1 (direction default).** Supervisor+ now default to **dispense**
  (Take Out Stock), not Add Stock — work orders are usually about taking parts
  out. Techs were already dispense-only.
- **Decision #6 (quantity).** Quantity no longer starts empty / resets to empty
  to force a per-item count. It now **defaults to 1 and resets to 1** after each
  commit; a non-1 amount is a deliberate per-item opt-in that does not carry
  over. The field is no longer auto-focused (that popped the mobile keyboard).
  `scanGoArmed` still refuses an emptied/zeroed field; double-count protection
  now rests entirely on the DWELL/COOLDOWN guards (decision #7), which remain.
- **Decision #3 (scan = commit).** A scan no longer commits instantly. After the
  barcode resolves to an item, a **custom confirmation modal** (`#scan-confirm-overlay`,
  `confirmScan` in `views/transactions.js`) asks `Take out 1 × [item]?`; the
  transaction is committed only on **Yes** (No / Esc / backdrop cancels). The Yes
  click is the flow's "Save." The live decoder stays paused for the dialog's whole
  lifetime because `handleLiveAccept` awaits the resolve+confirm+commit chain
  before starting its dwell timer, so modals never stack. The same-barcode
  cooldown is now set on a **decline** too (not just a commit), and a decline is
  not error-buzzed.

Files touched: `static/index.html` (scango defaults + `#scan-confirm-overlay`
markup), `static/views/transactions.js` (`confirmScan`, quantity/direction
defaults), `static/views/scan.js` (buzz/cooldown for decline),
`static/styles.css` (`.modal-overlay`/`.modal-box`). Backend unchanged.

- **Decision #5 (manual fallback).** Supervisor+ no longer see the manual items
  table / form (or the direction toggle) by default — they now get the *same*
  streamlined dispense-only flow as a Technician. A Supervisor+-only opt-in
  button (`#scango-advanced-toggle`, "Manual entry & stock options") reveals the
  direction toggle + table + form; toggling off reverts to dispense-only. The
  flag (`supervisorAdvanced` in `views/transactions.js`) resets on each login;
  `loadTxnItems()` is now only called when that opted-in table is actually
  visible. Technicians can never opt in. (`static/index.html` +
  `static/views/transactions.js`; backend unchanged.)
- **Decision #7 (camera lifecycle) extended.** The camera now **auto-starts**
  when a batch begins (`startBatch`) or when returning to an in-progress batch
  (`enterTransactionPage`), so there's no "Scan Barcode" tap before the fast
  loop. It is strictly prompt-free: `BarcodeDecoder.permissionGranted()` (a new
  static that returns true only on a Permissions API `granted` state) gates
  `mountScanner`'s new `autoStartIfPermitted()`. On first use / denied / no
  Permissions API it does nothing and the manual button remains. Wired one-way
  via `setScanAutostarter` (main.js → `autoStartTxnScan` in `views/scan.js`),
  mirroring `setScanResetter`. The existing reordering (scan controls above
  quantity) and the page reordering land the live camera at the top of State B.
