# Roadmap: Field-Friendly UX/UI Overhaul

> **Companion to [`plan-ux-overhaul.md`](plan-ux-overhaul.md).** The plan states the
> *intent, principles, and constraints*. This roadmap is the *executable breakdown*:
> phases → slices → tasks, each with files touched, acceptance criteria, and contract
> notes. When the two disagree, the **Locked Decisions** section below wins, because it
> records choices the owner made directly.

Status: **Roadmap drafted 2026-06-06.** No implementation has started. Phase work is
gated — do not begin a phase until its preconditions (decisions + verification of the
prior phase) are met.

---

## How To Use This Document

- Work top-to-bottom. Phases are ordered by dependency, not preference.
- Each task has a stable ID (e.g. `P2.S2.T3`). Reference it in commits and PRs.
- Before editing a frozen contract hook (see **Contract Guardrails**), update
  [`interfaces.md`](interfaces.md) in the *same* change.
- After each slice, run the **Per-Slice Verification** checklist before moving on.
- This overhaul is a **frontend UX pass**. No backend routes, schemas, DB, auth, or
  role rules change. See `plan-ux-overhaul.md` → "Non-Goals" and "AI Execution Contract".

---

## Locked Decisions (this session — 2026-06-06)

These were confirmed with the owner and override any conflicting "current assumption"
in `plan-ux-overhaul.md`.

| # | Decision | Choice | Impact |
|---|---|---|---|
| 1 | First screen after login | **All roles land on Find Item.** *(Supersedes the plan's role-based first-pass assumption.)* | One-line behavior change in `views/auth.js`. |
| 2 | Mobile table strategy | **Stacked rows on worker pages** (Find Item, Scan/Stock, History). Desktop keeps tables; Users table stays tabular on all sizes. | Render JS must emit `data-label` per `<td>`. |
| 3 | Touch-target sizing | **52px primary buttons / 48px inputs / 16px body text on mobile.** | Drives the global CSS scale. |
| 4 | Wording set | **Approved as written:** nav = Add Item, Find Item, Add User, Users, Scan/Stock, History; stock control = "Add Stock" / "Take Out Stock" (submitted values stay `stock`/`dispense`); correction = "Correct Count"; login = "Sign In". | Copy changes across views + headings. |
| 5 | Roadmap format | Task-level breakdown in this dedicated doc. | — |
| 6 | Phase structure | Keep the plan's **4 phases**. | Design-system foundation folds into Phase 1, Slice 1 (not a new Phase 0). |
| 7 | Color palette | **Red / Black / White**, Belfor Property Restoration style. Brand red ≈ `#D6001C` (tunable — match exact hex from Belfor's brand guide if desired). | Replaces the blue-led chrome (`#2563eb` etc.) throughout `styles.css`. |
| 8 | Meaning of red | **Red = primary / brand action** (Sign In, Save, Scan). Destructive actions (Delete, Correct Count) are distinguished by *treatment* — outlined/ghost style, trash icon, mandatory confirmation, visual separation — **not** by hue. | `styles.css` button system; destructive controls in `items.js`, `correction.js`. |
| 9 | Status accents | Palette is red/black/white **except** a minimal functional set retained for inventory-direction signalling: green = stock-in, amber = take-out, blue = adjust. These appear **only** on history `.type-badge.*` and the stock/dispense affordances. | The frozen `.type-badge.stock/.dispense/.adjust` classes keep their hues — no contract change. |

### Still open (decide at the start of the owning phase)

- **Phase 3** screen-level wording details for Notes labels, History filter labels, and
  Users role descriptions — approved in spirit by the wording set, but confirm exact
  strings when Phase 3 begins.
- **Field-trial scorecard** specifics (Phase 4).

---

## Audit Findings (code vs. docs, 2026-06-06)

Grounding facts from reading the current frontend. These shaped the tasks below.

1. **No renaming has happened yet.** All nav labels, page headings, the login button
   ("Log In"), the correction header ("Correct Quantity"), and the type `<select>`
   ("Stock (add)" / "Dispense (remove)") are still original. Phase 1 is greenfield.
2. **No responsive CSS exists.** [`styles.css`](../backend/static/styles.css) has **zero
   `@media` queries**. Base font 14px, buttons ~30px tall, inputs ~32px — all below the
   locked 52/48/16 targets. Mobile is the largest body of work.
3. **The current color system is blue-led** (blue chrome/nav/primary; green stock,
   amber dispense, blue adjust, red delete). Per Decisions #7–9 this is being replaced
   with a red/black/white palette: blue chrome → red/black/white, red repurposed to
   *primary* (not delete), and green/amber/blue retained **only** as status accents on
   badges/affordances.
4. **Current landing logic** ([`auth.js`](../backend/static/views/auth.js) lines ~59–61):
   Owner/Admin → Create Item, others → Saved Items. Decision #1 replaces this.
5. **Two "visual" changes actually touch JS / the DOM contract:**
   - Segmented Stock/Dispense control — `views/transactions.js` reads
     `transactionType.value`.
   - Stacked mobile rows — tables are built via `innerHTML` in `transactions.js`,
     `items.js`, `history.js`, `users.js`; CSS stacking needs `data-label` attributes
     added there.
6. **Messages are scattered across view files**, and some surface backend `detail`
   strings via `format.js::formatError`. Client-side rewrites fully control only
   client-originated strings; backend error text needs client-side mapping to be
   field-friendly.

---

## Contract Guardrails

**Safe to change without touching `interfaces.md`:**

- Visible button text, `<h2>`/`<h1>` heading text, input `placeholder`s, `.hint` copy.
- All CSS (layout, spacing, type scale, colors, responsive rules).
- Client-side message strings.

**Frozen — changing any of these requires a matching `interfaces.md` update in the same change:**

- Element **IDs** (the markup↔JS contract; see `index.html` header comment referencing
  the "Frozen DOM contract").
- `data-page` values on nav buttons (`create-item`, `saved-items`, `create-user`,
  `saved-users`, `transaction`, `history`) and `data-tab` values on history sub-tabs.
- State/role classes JS toggles: `.active`, `.success`, `.error`,
  `.type-badge.stock` / `.dispense` / `.adjust`, `.nav-btn`, `.stock-btn`,
  `.dispense-btn`, `.row-actions`, scanner hooks (`*-scan-video`, `*-scan-scan-btn`,
  `*-scan-upload-btn`, `*-scan-torch-btn`, `*-scan-aimbox`).

> Note: nav **labels** are button *text* and are NOT frozen. Renaming "Transaction" →
> "Scan / Stock" changes text only; `data-page="transaction"` stays.

---

## Phase 1 — Language And Hierarchy

**Status: ✅ Complete (2026-06-06).** All four slices landed; verified in-browser (login,
chrome, landing, computed 52/48/16 + palette) and `pytest` green (34 passed). spec.md +
interfaces.md updated.

**Goal:** the app reads in plain jobsite language and primary actions stand out, with
layout largely intact. This is also where the global visual system gets built so every
later phase inherits it.

**Preconditions:** Locked Decisions 1, 3, 4. Backend tests green at baseline.

### Slice 1.1 — Global visual system (design tokens + scale)

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P1.1.T1 | Add CSS custom properties at `:root` for the **red/black/white** palette (Decisions #7–9): brand red, near-black, white, and a neutral gray ramp; plus the retained status accents (`--status-stock` green, `--status-dispense` amber, `--status-adjust` blue) scoped to badges/affordances only. Add spacing scale, radius, and type scale. Replace the current blue-led hard-coded hex values throughout. | `styles.css` | Palette tokens defined; chrome reads red/black/white; status accents present but used only on `.type-badge.*` and stock/dispense controls; no blue chrome remains. |
| P1.1.T1b | Recolor the button system for Decision #8: **primary = red**, secondary = black/neutral, **destructive = ghost/outlined red** (not solid-red-as-default). Keep all button IDs/classes. | `styles.css` | Primary actions are red; destructive actions are visually distinct via outline + (later) icon/confirmation, not by being the only red elements; `.stock-btn`/`.dispense-btn` retain their status hues. |
| P1.1.T2 | Raise the global control scale to the locked minimums: primary `button` ≥52px tall, `input`/`select` ≥48px, base body ≥16px. Keep secondary/compact controls usable. | `styles.css` | Primary buttons render ≥52px; inputs ≥48px; body text ≥16px — verified in preview. No control overflows its container on desktop. |
| P1.1.T3 | Strengthen contrast and focus states: visible `:focus-visible` outlines on all interactive elements; ensure no faint-gray-only text conveys required info. | `styles.css` | Every interactive element shows a visible focus ring on keyboard nav. Contrast meets the plan's "high contrast" intent. |

### Slice 1.2 — Navigation labels + landing behavior

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P1.2.T1 | Rename nav button text per the wording set (Create Item→Add Item, Saved Items→Find Item, Create User→Add User, Saved Users→Users, Transaction→Scan / Stock; History unchanged). `data-page` values untouched. | `index.html` | Nav shows new labels; navigation still works; no `data-page` changed. |
| P1.2.T2 | Make the active page unmistakable (stronger `.active` treatment than the rest of the bar). | `styles.css` | Active nav item is obvious at a glance on phone and desktop. |
| P1.2.T3 | **Behavior change (Decision #1):** all roles land on Find Item after login. Update the landing computation in `enterApp`. | `views/auth.js` | Owner, Admin, Supervisor, Technician all land on `saved-items` (Find Item) after login. No role lands on Create Item by default. Update `spec.md` data-flow + `auth.js` comment. |

### Slice 1.3 — Page headings + primary button labels

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P1.3.T1 | Update visible `<h2>` headings to match new names (Create Item→"Add Item", Saved Items→"Find Item", Create User→"Add User", Saved Users→"Users", "Correct Quantity"→"Correct Count"). | `index.html` | Headings match nav/wording set. IDs unchanged. |
| P1.3.T2 | Update primary button text: login "Log In"→"Sign In"; "Create Item"→"Save Item"; "Create User"→"Create User" (keep) / confirm; "Save Correction"→"Save Correct Count". | `index.html` | Buttons read in jobsite language; button IDs unchanged. |
| P1.3.T3 | Make each page's primary action the visually dominant control (size/weight/color), with destructive/secondary actions visually quieter. | `styles.css` | On each page the main action is clearly the strongest button; secondary/danger actions are visually subordinate. |

### Slice 1.4 — Message rewrite (client-side strings)

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P1.4.T1 | Rewrite client-originated messages per the plan's Message Rewrite Guide (connection, session-expired, scan failure, insufficient stock, permission, empty history, validation). | `views/auth.js`, `views/transactions.js`, `views/scan.js`, `views/items.js`, `views/history.js`, `views/correction.js`, `views/notes.js` | Listed messages match the guide's field-friendly wording and include a recovery action. |
| P1.4.T2 | Audit backend `detail` strings surfaced via `format.js::formatError`. Where a raw backend message is user-hostile, add a client-side friendly mapping/fallback. | `format.js`, calling views | No dead-end/technical error reaches the user for the common failure paths; each shows a next step. |
| P1.4.T3 | Confirm success confirmations are short and present ("Item saved", "Stock added", "Quantity corrected", "Notes saved"). | relevant views | Each successful action shows a clear, brief confirmation near the control. |

**Phase 1 exit criteria:** new labels/headings/messages live; all roles land on Find
Item; global control scale meets 52/48/16; backend tests still pass; `spec.md` +
`interfaces.md` updated for the landing behavior and any heading/label notes.

---

## Phase 2 — Mobile Worker Screens

**Status: ✅ Complete (2026-06-06).** Responsive foundation + stacked worker tables
(Find Item, Scan/Stock), segmented Add Stock/Take Out control (hidden `#transaction-type`
preserved), post-scan confirmation. Verified: no h-scroll at 375px, stacked rows on
mobile / real tables on desktop, segmented toggle drives `stock`/`dispense`. `pytest`
green; spec.md + interfaces.md updated.

**Goal:** Login, Find Item, and Scan/Stock are excellent on a phone in portrait. Scan
is dominant; the transaction task feels active; worker tables stack on narrow screens.

**Preconditions:** Phase 1 exit criteria met. Locked Decisions 2 and 3.

### Slice 2.1 — Responsive foundation

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P2.1.T1 | Introduce CSS breakpoints (mobile portrait first; tablet/desktop as min-width overrides). No device-specific branches — CSS breakpoints only. | `styles.css` | A single, documented set of breakpoints; layout reflows cleanly across widths. |
| P2.1.T2 | Ensure no routine horizontal scrolling on worker-facing pages at phone widths; reduce header/nav density on small screens. | `styles.css`, `index.html` (only if structure needs it) | At 360–414px width, Login/Find Item/Scan-Stock have no horizontal scroll for routine use. |

### Slice 2.2 — Login screen (mobile)

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P2.2.T1 | Larger title, bigger username/password fields, full-width "Sign In" button; comfortable spacing on phone. | `styles.css`, `index.html` | Login is easy to use one-handed at phone width; fields/button meet 48/52 targets. |
| P2.2.T2 | Field-friendly login error already from P1.4; confirm it appears close to the form and is legible. | `views/auth.js`, `styles.css` | Failed sign-in shows the rewritten message directly under the form. |

### Slice 2.3 — Find Item (scan-dominant + stacked rows)

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P2.3.T1 | Make scan/search the visual top of the page; search placeholder "Search name or barcode". | `index.html`, `styles.css` | Scan + search sit above and visually dominate the results on phone. |
| P2.3.T2 | Convert the items render to emit `data-label` on each `<td>`; add CSS so the table becomes stacked rows on mobile (item name large, barcode/location secondary, quantity prominent). Desktop table unchanged. | `views/items.js`, `styles.css` | At phone width each item is a readable stacked card; at desktop width the table is unchanged. `interfaces.md` updated (render emits `data-label`). |
| P2.3.T3 | Collapse row actions behind one clear "Actions" control on mobile; keep role-based availability; keep Supervisor Notes access distinct from Admin-only edit/delete/correct. Apply Decision #8 destructive treatment to Delete/Correct Count: ghost/outlined red + trash/warning icon + confirmation, set apart from routine actions. | `views/items.js`, `styles.css` | Actions reachable via one obvious control on phone; destructive actions visually distinct (outline + icon + confirm) and not adjacent to routine ones; role gating unchanged. `aria-label` preserved on compact controls. |
| P2.3.T4 | Apply Find Item action wording: Edit→"Edit Details", Edit Notes→"Notes", Correct→"Correct Count", Delete→"Delete Item". | `views/items.js` | Action labels match the wording set. |

### Slice 2.4 — Scan / Stock transaction page

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P2.4.T1 | Make the camera/scan area the main visual element; primary "Scan Barcode", secondary "Upload Photo". | `index.html`, `styles.css` | Scan area dominates the page; buttons meet size targets. |
| P2.4.T2 | Large post-scan confirmation: item name, current quantity, location, prominently shown before the form. | `views/transactions.js`/`views/scan.js`, `styles.css` | After a successful scan the matched item is shown large and clearly before/at the form. |
| P2.4.T3 | **Segmented Stock/Dispense control (DOM-contract touch).** Replace the `<select id="transaction-type">` with two large segmented buttons "Add Stock" / "Take Out Stock" while preserving submitted values `stock`/`dispense`. Keep a hidden field at the same ID *or* update the read path — whichever is chosen, document it. | `index.html`, `views/transactions.js`, `styles.css`, `interfaces.md` | Two big segmented choices; submitted `transaction_type` is still `stock`/`dispense`; default is Add Stock with one tap to switch; `interfaces.md` reflects the control change. Backend unchanged. |
| P2.4.T4 | Big quantity field, large "Save Transaction", secondary "Cancel"; scroll the active form into view after selection (behavior already partly present — verify on mobile). | `styles.css`, `views/transactions.js` | The transaction form reads as the active task; quantity is the obvious next field after scan; form scrolls into view. |

**Phase 2 exit criteria:** Login, Find Item, Scan/Stock are comfortable at phone
portrait widths with no routine horizontal scroll; worker tables stack on mobile;
segmented stock control submits correct values; scan/stock/dispense still work end to
end; backend tests pass; `interfaces.md` + `spec.md` updated for the segmented control
and stacked-row render changes.

---

## Phase 3 — Admin And History Polish

**Goal:** Add Item, Users, History, Notes, and Correction inherit the new system and
read clearly, while staying visually quieter than field workflows.

**Preconditions:** Phase 2 exit criteria met. Confirm Phase 3 open wording (Notes
labels, History filter labels, Users role descriptions) at phase start.

### Slice 3.1 — Add Item

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P3.1.T1 | Make barcode the first, strongest field; helper copy ("Scan or type the label number." / "Where workers will find it."); "Save Item" primary; default quantity `0` visually clear; success "Item saved." | `index.html`, `views/items.js`, `styles.css` | Add Item reads in plain language; barcode is primary; helper copy present; success message correct. |

### Slice 3.2 — Correction (Correct Count)

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P3.2.T1 | Label "Correct Count"; one-line explainer "Use this when the shelf count is wrong."; show current quantity near the new-quantity field; reason label "Why are you changing it?"; primary "Save Correct Count". Keep Admin+ gate. | `index.html`, `views/correction.js`, `styles.css` | Correction reads distinctly from routine stock movement; current qty visible; Admin+ gate unchanged. |

### Slice 3.3 — Notes

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P3.3.T1 | Rename "Edit Notes"→"Notes"; clearer row labels (Note name / Type / Value); add button "Add Another Note"; success "Notes saved." Rows easier to scan. | `index.html`, `views/notes.js`, `styles.css` | Notes editor reads clearly; labels/buttons match wording; duplicate-key validation preserved. |

### Slice 3.4 — Users

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P3.4.T1 | Keep visually quieter than field workflows; add plain role descriptions; separate password-reset/delete from ordinary viewing. Users table stays tabular (Decision #2). | `index.html`, `views/users.js`, `styles.css` | Role descriptions present; destructive actions visually separated; management rules unchanged. |

### Slice 3.5 — History

| Task | Description | Files | Acceptance |
|---|---|---|---|
| P3.5.T1 | Make filters look like filters; rename "Work Order"→"Filter by Work Order"; copy success "Copied history." | `index.html`, `views/history.js` | Filters read as filters; labels/messages updated. |
| P3.5.T2 | Stacked history rows on mobile (date/time, item, type, quantity, work order/reason, user) via `data-label` + CSS; desktop table unchanged; preserve `.type-badge.*` styling. | `views/history.js`, `styles.css`, `interfaces.md` | History stacks readably on phone; badges intact; desktop unchanged; `interfaces.md` updated. |

**Phase 3 exit criteria:** all admin/history screens inherit the new system and match
the wording; History stacks on mobile; backend tests pass; `spec.md` + `interfaces.md`
updated for any label/DOM/behavior-visible changes.

---

## Phase 4 — Field Trial

**Goal:** validate with real crew before any second-round changes.

| Task | Description | Output |
|---|---|---|
| P4.T1 | Put the app in front of actual crew members on their phones. | Observation session. |
| P4.T2 | Observe the plan's Field Trial Questions (first tap, Stock vs Dispense understanding, success-message noticing, scan-failure recovery, glove tap size, accidental destructive taps, quantity-field obviousness, "office software" feel). | Notes against each question. |
| P4.T3 | Record findings in `plan-ux-overhaul.md` (Field Trial Validation Points) **before** making second-round changes. | Updated plan doc. |

**Phase 4 exit criteria:** findings recorded in `plan-ux-overhaul.md`; any follow-up
work captured as a new roadmap revision.

---

## Per-Slice Verification Checklist

Run after every slice that changes previewable behavior:

1. Start/refresh the dev server (port 8124) and load the app.
2. Check console + server logs for errors.
3. Mobile portrait (≈360–414px): no routine horizontal scroll on worker pages;
   targets meet 52/48/16.
4. Desktop: layout intact; tables unchanged where they should be.
5. Exercise the affected workflow end to end (scan, stock, dispense, notes, correction,
   users, history as relevant).
6. `cd backend; pytest` — backend tests green.
7. If any frozen hook, label-with-behavior, or DOM structure changed: update
   `docs/spec.md` and `docs/interfaces.md` in the same change.
8. Capture a screenshot for visual changes as proof.

---

## Risks & Sequencing Notes

- **DOM-contract touches are the riskiest tasks** (P2.3.T2, P2.4.T3, P3.5.T2). Do them
  deliberately, update `interfaces.md` in lockstep, and verify the JS read/write paths
  before/after.
- **Stacked-row work depends on the responsive foundation** (Slice 2.1) — don't start
  P2.3.T2 before P2.1 lands.
- **Backend error strings** (P1.4.T2) are partially outside frontend control; treat the
  mapping as best-effort for common paths, not a guarantee for every backend message.
- **Scope discipline:** if any task appears to require a backend route, schema, or
  permission change, stop and raise it — that is out of scope per the plan.

---

## Doc Update Obligations

Keep these living docs in step as phases land:

- `docs/spec.md` — behavior-visible copy, landing behavior, control changes.
- `docs/interfaces.md` — any frozen-hook, DOM-structure, or render-contract change.
- `docs/plan-ux-overhaul.md` — Field Trial findings (Phase 4) and any superseded
  assumptions.
- This roadmap — check off slices and capture second-round work.
