# Design Spec: Field-Friendly UX/UI Overhaul

> **The build sheet.** [`plan-ux-overhaul.md`](plan-ux-overhaul.md) = intent/constraints.
> [`roadmap-ux-overhaul.md`](roadmap-ux-overhaul.md) = phases/tasks. **This doc = exact
> values.** Tokens, components, copy, and per-screen layouts are specified concretely so
> implementation is mechanical — no new design decisions during execution.
>
> If a value here conflicts with the roadmap or plan, **this doc wins** (it is downstream
> of all locked decisions). Drafted 2026-06-06.

---

## 1. Visual Identity (locked)

| Aspect | Decision |
|---|---|
| Palette | Red / Black / White (Belfor-style) |
| Brand red | `#C8102E` (deeper crimson) |
| Red's meaning | **Primary/brand action.** Destructive = treatment (outline + icon + confirm), not hue. |
| Status accents | Green/amber/blue retained **only** on `.type-badge.*` and stock/dispense affordances |
| Header | Near-black bar, white text, red active-tab pill |
| Typeface | System sans stack, bold headings (no web font) |
| Surfaces | Soft cards: ~8px radius, subtle shadows |
| Touch targets | Primary btn 52px / inputs 48px / body 16px on mobile |

---

## 2. Design Tokens (paste-ready)

Add at the top of [`styles.css`](../backend/static/styles.css) `:root`. All later CSS
references these — no raw hex elsewhere.

```css
:root {
  /* Brand */
  --color-brand:        #C8102E;  /* primary actions */
  --color-brand-hover:  #A50D25;
  --color-brand-active: #8E0B20;
  --color-brand-tint:   #FBE9EC;  /* faint red wash (hover on outline-red) */

  /* Ink / neutrals */
  --color-ink:          #1A1A1A;  /* body text */
  --color-header:       #141414;  /* header/nav bar */
  --color-white:        #FFFFFF;
  --gray-50:            #F7F7F7;   /* app background */
  --gray-100:           #EFEFEF;
  --gray-200:           #E2E2E2;   /* hairline borders */
  --gray-300:           #CFCFCF;   /* input borders */
  --gray-400:           #A8A8A8;
  --gray-500:           #6B6B6B;   /* secondary text, table headers */
  --gray-700:           #3A3A3A;
  --gray-900:           #141414;

  /* Status accents (badges + stock/dispense affordances ONLY) */
  --status-stock:        #16A34A; --status-stock-hover:    #15803D;
  --status-dispense:     #D97706; --status-dispense-hover: #B45309;
  --status-adjust:       #2563EB;

  /* Feedback text */
  --color-success: #15803D;
  --color-error:   #C8102E;   /* same family as brand; context (text vs button) disambiguates */

  /* Typography */
  --font-sans: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, Arial, sans-serif;
  --fs-xs: 12px; --fs-sm: 14px; --fs-base: 16px; --fs-lg: 18px;
  --fs-xl: 22px; --fs-2xl: 28px; --fs-3xl: 34px;
  --fw-regular: 400; --fw-semibold: 600; --fw-bold: 700;
  --lh-body: 1.45; --lh-heading: 1.2;

  /* Spacing (4px base) */
  --space-1: 4px; --space-2: 8px; --space-3: 12px; --space-4: 16px;
  --space-5: 20px; --space-6: 24px; --space-8: 32px; --space-10: 40px; --space-12: 48px;

  /* Radius / shadow / border */
  --radius-sm: 6px; --radius-md: 8px; --radius-pill: 999px;
  --shadow-sm:   0 1px 3px rgba(0,0,0,.12);
  --shadow-card: 0 1px 4px rgba(0,0,0,.10);
  --shadow-md:   0 2px 8px rgba(0,0,0,.12);
  --border:        1px solid var(--gray-200);
  --border-input:  1px solid var(--gray-300);

  /* Controls */
  --control-h: 48px;   /* inputs, selects */
  --btn-h: 52px;       /* primary buttons */
  --btn-h-sm: 44px;    /* compact/toolbar buttons (min touch) */
  --focus-ring: 0 0 0 3px rgba(200,16,46,.40);

  /* Breakpoints (reference; media queries use the px) */
  --bp-tablet: 640px; --bp-desktop: 960px;
}
```

**Breakpoint rule:** mobile-first base styles; `@media (min-width: 640px)` restores
tables and multi-column layouts. Worker tables stack **below 640px**.

---

## 3. Component Specs

### 3.1 Buttons

| Variant | Selector | Fill | Text | Border | Height | Notes |
|---|---|---|---|---|---|---|
| Primary | bare `button` | `--color-brand` | white | none | 52px | hover `--color-brand-hover`, active `--color-brand-active`, font 16/700 |
| Secondary | `.secondary-btn` | white | `--color-ink` | `--border-input` | 44–48px | hover bg `--gray-50` (replaces old gray fill) |
| Destructive | `.btn-danger` *(new class, add in markup/render)* | white | `--color-brand` | 1.5px solid `--color-brand` | 44–48px | leading ⚠/trash glyph; hover bg `--color-brand-tint`; **always confirm** |
| Stock affordance | `.stock-btn` | `--status-stock` | white | none | 44px | accent-exempt |
| Dispense affordance | `.dispense-btn` | `--status-dispense` | white | none | 44px | accent-exempt |
| Disabled | `:disabled` | `--gray-300` | `--gray-500` | none | — | not-allowed cursor |

All buttons: `--radius-md`, 16px font (≥14px for compact toolbar), `:focus-visible`
shows `--focus-ring`. **Solid red = "go"; outline red = "caution."** That contrast is the
core destructive cue, reinforced by icon + confirmation.

### 3.2 Inputs & selects

- Height `--control-h` (48px), font 16px (prevents iOS zoom), padding `0 12px`,
  border `--border-input`, radius `--radius-md`, white bg.
- `:focus-visible` → border `--color-brand` + `--focus-ring`.
- Labels: `--fs-sm`/700, `--color-ink`, tied via `for`/`id` (keep existing).
- Helper text (`.hint`): `--fs-sm`, `--gray-500`, sits under the relevant control.

### 3.3 Cards / sections

- `section`: white, `--radius-md`, `--shadow-card`, padding `--space-6` (desktop) /
  `--space-4` (mobile), `margin-bottom --space-6`.

### 3.4 Header & nav

- `header`: bg `--color-header`, white `h1`, padding `--space-4 --space-6` (mobile
  `--space-3 --space-4`).
- `.nav-btn`: transparent, text `--gray-200`, radius `--radius-md`, 44px tall, font
  14–16/600. Hover bg `#2A2A2A`. **`.active` → bg `--color-brand`, white text** (red pill).
- `#auth-bar`: white/`--gray-200` text; `#logout-btn` uses `.secondary-btn` on dark →
  white outline variant (border `--gray-400`, transparent fill, white text).

### 3.5 Segmented control — Stock / Dispense  *(replaces the type `<select>`)*

Two equal buttons sharing one row; full width on mobile. Backs a **hidden input**
`#transaction-type` holding `stock` | `dispense` (preserves the JS read contract).

| State | "Add Stock" | "Take Out Stock" |
|---|---|---|
| Selected | fill `--status-stock`, white text | fill `--status-dispense`, white text |
| Unselected | white, border `--gray-300`, ink text | white, border `--gray-300`, ink text |

- Min height 52px; the two cells form one rounded group (`--radius-md` outer corners).
- Default selected = **Add Stock**; one tap flips to Take Out.
- Accent-exempt (these are the stock/dispense affordances).

### 3.6 Type badges (history) — unchanged hues, friendlier labels

- `.type-badge` pill, `--fs-xs`/700, white text, `--radius-pill`, padding `2px 10px`.
- `.stock` → `--status-stock`; `.dispense` → `--status-dispense`; `.adjust` → `--status-adjust`.
- **Label text mapping** (render in `history.js`): `stock`→"Added", `dispense`→"Taken Out",
  `adjust`→"Correction".

### 3.7 Messages

- Inline `<p>` under the control. `.success` → `--color-success`; `.error` →
  `--color-error`; font `--fs-base`.
- Form-level errors get a left accent: `border-left: 3px solid currentColor; padding-left: 8px`.

### 3.8 Sub-tabs, pagination, action menu

- `.sub-tab-btn.active`: ink text + 3px `--color-brand` bottom border (red underline).
- `.pagination` buttons: `.secondary-btn` style, 44px.
- **Row action menu** (Find Item): keep the existing single-control pattern
  (`.row-actions-select` / Actions menu); restyle to 44px, keep its `aria-label`. On
  mobile it is the one obvious "Actions" control per row.

---

## 4. Mobile Stacked Rows (worker tables)

Applies to **`#items-table`, `#txn-items-table`, `#history-table`** below 640px.
Users table stays tabular at all sizes.

**CSS pattern:**

```css
@media (max-width: 639px) {
  .stack-table thead { display: none; }
  .stack-table tr {
    display: block; border: var(--border); border-radius: var(--radius-md);
    box-shadow: var(--shadow-sm); padding: var(--space-3);
    margin-bottom: var(--space-3); background: var(--color-white);
  }
  .stack-table td {
    display: flex; justify-content: space-between; gap: var(--space-3);
    padding: var(--space-2) 0; border-bottom: 1px solid var(--gray-100);
  }
  .stack-table tr td:last-child { border-bottom: none; }
  .stack-table td::before {
    content: attr(data-label); font-weight: var(--fw-bold);
    color: var(--gray-500); flex: 0 0 auto;
  }
  .stack-table td[data-primary] { font-size: var(--fs-lg); font-weight: var(--fw-bold); }
  .stack-table td[data-primary]::before { content: none; }   /* name needs no label */
}
```

**Render-JS deltas** (add `class="stack-table"` to each `<table>` in markup; emit
`data-label` per `<td>` in the render functions):

| Table | `<td>` → `data-label` (and which gets `data-primary`) |
|---|---|
| `#items-table` (`items.js`) | Name `data-primary`; "Barcode", "Quantity", "Location", "Notes", "Created", "Actions" |
| `#txn-items-table` (`transactions.js`) | Name `data-primary`; "Barcode", "Quantity", "Actions" |
| `#history-table` (`history.js`) | Item `data-primary`; "Time", "Type", "Quantity", "Work Order", "User" |

> Quantity should read large/bold on items + txn rows even within the stacked card —
> give the quantity `<td>` value a `<strong>` wrapper.

---

## 5. Copy & Messages (exact strings)

### 5.1 Navigation labels

| `data-page` | New label |
|---|---|
| `create-item` | Add Item |
| `saved-items` | Find Item |
| `create-user` | Add User |
| `saved-users` | Users |
| `transaction` | Scan / Stock |
| `history` | History |

### 5.2 Per-screen copy

**Login** — h1 "Inventory Management"; h2 "Sign In"; button **"Sign In"**.
- empty → "Enter a username and password."
- bad creds → "That sign-in did not work. Check the username and password, then try again."
- connection → "Could not reach the app. Check your signal and try again."

**Add Item** — h2 "Add Item". Field order: **Barcode (first/strongest)**, Item Name,
Location, Starting Quantity.
- Barcode helper: "Scan or type the label number." · placeholder "Scan or enter barcode"
- Location helper: "Where workers will find it."
- Starting Quantity placeholder "0" (default 0, visually clear)
- button **"Save Item"** · success **"Item saved."**
- validation → "Enter a barcode, name, and location."
- duplicate barcode (backend) → "That barcode is already used by another item."

**Find Item** — h2 (scan) "Scan or Search"; hint "Scan a barcode or search below to find
an item." Search placeholder "Search name or barcode".
- Row actions: **"Edit Details" · "Notes" · "Correct Count" · "Delete Item"**
- empty → "No items yet." · no filter match → "No items match that search."

**Scan / Stock** — scan h2 "Scan Barcode"; primary **"Scan Barcode"**; secondary
**"Upload Photo"**; **"Torch"**. Hint "Point your camera at a barcode, or upload a photo,
to open a transaction."
- Post-scan confirmation card: **item name large**, "On hand: {qty}", "Location: {location}"
- Items section h2 "Items"; hint "Tap Add Stock or Take Out on an item."
- Row buttons: **"Add Stock"** (`.stock-btn`) / **"Take Out"** (`.dispense-btn`)
- Form h2 "New Transaction"; segmented **"Add Stock" / "Take Out Stock"**; "Quantity";
  "Work Order Number (optional)"; button **"Save Transaction"**; "Cancel".
- success → stock: "Stock added." · dispense: "Stock taken out."
- scan fail → "Could not read that barcode. Move closer, hold steady, and try again."
- unknown barcode → "No item matches that barcode." (+ Owner/Admin "Add Item" shortcut)
- insufficient stock → "Not enough stock available. Check the count before taking more out."

**Correct Count** — h2 "Correct Count"; explainer "Use this when the shelf count is wrong."
- Shows "Current count: {qty}". New value label "New Count" (placeholder "0").
- Reason label "Why are you changing it?" placeholder "Reason for the correction".
- button **"Save Correct Count"** · success **"Count corrected."**
- no-change → "Enter a count that's different from the current one."

**Notes** — h2 "Notes"; row labels "Note name" / "Type" / "Value"; add **"Add Another
Note"**; **"Save Notes"** / "Cancel".
- success **"Notes saved."** · duplicate key → "Two notes share a name. Make each note name different."

**Add User / Users** — create h2 "Add User"; button **"Add User"**. Labels Username /
Role / Password (placeholder "At least 4 characters").
- Role helper (shown under Role select):
  - Technician — Scan items and do basic work.
  - Supervisor — Record stock, edit notes, view history.
  - Admin — Manage items and corrections.
  - Owner — Top-level setup.
- Users list h2 "Users"; delete is `.btn-danger` + confirm; reset-password separated.
- delete blocked → "This user has transaction history and can't be deleted."

**History** — h2 "Transaction History". WO filter label **"Filter by Work Order"**
(placeholder "Work order number"), "Clear". Sub-tabs "All Transactions" / "By Item" /
"By User". By-Item "Item Barcode" + "Look Up". By-User "User". Copy button "Copy table" →
success **"Copied history."**
- empty → "No history found for those filters."
- badge labels: "Added" / "Taken Out" / "Correction" (§3.6)

### 5.3 Global messages

- session expired → "You were signed out. Sign in again."
- permission denied → "Your account can't do that. Ask a supervisor if this seems wrong."
- connection → "Could not reach the app. Check your signal and try again."

---

## 6. Per-Screen Layout Specs

> All screens: card sections (§3.3), 16px body, primary action is the lone solid-red
> button, destructive actions outlined+confirmed (§7).

- **Login** — centered card, max-width 360px. Stacked: title, "Sign In", Username,
  Password, full-width red "Sign In", message. Enter submits (keep).
- **Find Item** *(landing for all roles)* — order top→bottom: **Scan/Search card**
  (dominant) → results (table desktop / stacked cards mobile) → editor/notes/correction
  sections (hidden until triggered). Quantity prominent in each row.
- **Scan / Stock** — order: **Scan card** (camera dominant) → post-scan confirmation →
  Items (table/stacked) → New Transaction form (segmented control, big quantity, red
  "Save Transaction"). Form scrolls into view on open (behavior exists).
- **Add Item** — single card, barcode first/strongest, helper copy, red "Save Item".
- **Correct Count** — current count beside new count; reason required; red "Save Correct
  Count"; visually distinct from routine stock movement.
- **Notes** — row-per-note grid (desktop) / stacked fields (mobile); "Add Another Note"
  secondary; red "Save Notes".
- **Users** — quieter than worker screens; Add User card with role helper; Users table
  stays tabular; destructive actions separated + outlined.
- **History** — filters read as filters; shared results table → stacked on mobile;
  pagination centered; "Copy table" secondary.

---

## 7. Destructive-Action Treatment

Applies to **Delete Item, Delete User, Correct Count** (and password reset = caution).

1. **Style:** `.btn-danger` — white fill, brand-red outline + text, leading ⚠/trash glyph.
   Never solid red (solid red = primary/go).
2. **Separation:** not adjacent to routine actions; on Find Item they live inside the
   Actions menu, set apart from "Notes"/"Edit Details".
3. **Confirmation:** keep/standardize a confirm step before the irreversible call (item
   delete, user delete; barcode-change confirm already exists).
4. **Never color-only:** glyph + label carry the meaning too (accessibility rule).

---

## 8. Accessibility & Contrast

- **Contrast:** white text on `#C8102E` ≈ 5.25:1 (passes AA for ≥16px/bold and normal
  text). White on `#141414` ≈ 18:1. Ink `#1A1A1A` on white ≈ 16:1. **Do not** put brand
  red text on the black header (muddy) — header accents use white.
- **Focus:** every interactive element shows `--focus-ring` on `:focus-visible`.
- **Labels:** all inputs keep `for`/`id`; compact controls keep `aria-label`.
- **Targets:** ≥44px tappable everywhere; 52/48 for primary/inputs.
- **Color independence:** stock/dispense/adjust carry text labels + (badges) shape;
  destructive carries glyph + label.

---

## 9. Implementation Contract Deltas

Changes that touch the **frozen DOM contract** → update [`interfaces.md`](interfaces.md)
in the same commit:

| Change | Detail | Roadmap task |
|---|---|---|
| `#transaction-type`: `<select>` → hidden `<input>` + segmented buttons | `.value` read path preserved; document new control | P2.4.T3 |
| `class="stack-table"` added to `#items-table`, `#txn-items-table`, `#history-table` | enables mobile stacking | P2.3.T2 / P3.5.T2 |
| `data-label` (+ `data-primary`) emitted per `<td>` in `items.js`, `transactions.js`, `history.js` | render-contract note | P2.3.T2 / P3.5.T2 |
| New `.btn-danger` class on destructive controls | styling only; note in interfaces | P2.3.T3 |
| Badge label text mapping in `history.js` | display-only; class hues unchanged | P3.5.T1 |

**Unchanged (do not touch):** all element IDs, `data-page` / `data-tab` values, state
classes `.active/.success/.error`, `.type-badge.*` hues, scanner hooks, every backend
route/schema/permission.

---

## 10. Execution Readiness

With tokens (§2), components (§3), stacked rows (§4), copy (§5), layouts (§6),
destructive treatment (§7), and contract deltas (§9) fixed, each roadmap task reduces to
applying these values. Remaining at execution time: only verification (mobile portrait,
desktop, `pytest`) and the lockstep doc updates.
