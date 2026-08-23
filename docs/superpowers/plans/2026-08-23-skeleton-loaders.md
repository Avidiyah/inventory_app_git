# App-wide Skeleton Loading States — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to
> implement this plan task-by-task. (This repo's `CLAUDE.md` forbids subagents, so
> superpowers:subagent-driven-development does **not** apply here.) Steps use
> checkbox (`- [ ]`) syntax for tracking.

**Goal:** Replace every content-area `Loading…` text placeholder in the frontend
with a shape-matched skeleton block rendered from one shared helper module.

**Architecture:** A new pure-function module `backend/static/skeleton.js` returns
HTML strings (`skeletonTableRows`, `skeletonCard`, `skeletonList`), matching this
codebase's existing "view files build `innerHTML` directly" pattern — no
framework, no DOM access, no state. A new CSS section in
`backend/static/styles.css` styles `.skel-*` classes using existing panel tokens.
Each view swaps its `Loading…` string for a call into the module; all
surrounding busy-state logic (request-id guards, button disabling, error paths)
is untouched.

**Tech Stack:** Vanilla ES modules served statically by FastAPI, plain CSS with
custom properties. No build step, no frontend test runner.

**Spec:** `docs/superpowers/specs/2026-08-23-skeleton-loaders-design.md`

---

## Global Constraints

- **D1 Fidelity:** shape-matched — column counts and card shapes mirror the real
  layout, never one generic placeholder reused everywhere.
- **D2 Motion:** slow opacity/color pulse (`1.5s ease-in-out infinite`), never a
  shimmer sweep. Static under `prefers-reduced-motion: reduce`.
- **D3 Color:** `--panel-well` at rest, `--panel-hover` at pulse peak,
  `--panel-nested` for card surfaces. **No new tokens in `:root`.**
- **D4 Architecture:** all skeleton markup comes from `backend/static/skeleton.js`.
  No view hand-writes `.skel-*` HTML.
- **D5 Scope:** content-area placeholders only. `setMessage(el, "Loading…", "")`
  status-line messages stay text (`adminReview.js:125`, `tools.js:688`,
  `transactions.js:489`, `userRequests.js:75`) — do not touch them.
- **D6 Testing:** manual validation only. No frontend test harness is added.
  Per the owner's standing preference, **do not start the preview server
  yourself** — each task ends by handing the owner an explicit check list.
- Files stay under 500 lines; read a file before editing it; run
  `node --check <file>` after every JS edit; commit after every task.
- Never weaken the CI gate. Do not merge to `main` without asking — merging
  deploys to production.

### Locked module interface (every task depends on this)

```js
// backend/static/skeleton.js
export function skeletonTableRows(colCount, rowCount = 5, { widths = null } = {}) // -> string of <tr>…</tr>
export function skeletonCard({ lines = 3, hasHeader = true } = {})                // -> string, one .skel-card block
export function skeletonList(itemCount = 4)                                       // -> string, stacked two-line groups
```

### Spec-vs-code reconciliation (read before Task 2)

The spec's §5 rollout list was written from memory and does not match the code.
The authoritative list of content-area placeholders, verified against the tree at
commit `e588981`, is:

| Site | File:line | Shape |
|---|---|---|
| Items search results | `views/items.js:137` | table, 5–8 cols by role |
| History results | `views/history.js:122` | table, 7 or 8 cols by role |
| Tools inventory | `views/tools.js:686` | table, 4 or 5 cols by role |
| Users table | `views/users.js:70` | table, 6 cols (**not in spec §5 — added**) |
| Add-barcode item search | `views/addBarcode.js:87` | list (**not in spec §5 — added**) |
| Mass-stage card body | `views/massStage.js:120` | card |
| Work-order card body | `views/workOrders.js:1222` | card |
| Work-order solo page (by id) | `views/workOrders.js:1269` | card |
| Work-order solo page (by number) | `views/workOrders.js:1296` | card |
| Embedded work-order list | `views/workOrders.js:1375` | card list |
| Hub timesheets mount | `views/userHub.js:232, 234` | card |
| Hub graphs mount | `views/userHub.js:263` | card grid |
| Hub dashboard first load | `views/userHub.js:360` (`loadUserHub`) | card grid — **no placeholder today, renders blank** |
| Hub crew board | `views/userHub.js:281` (`refreshCrew`) | card — **no placeholder today, renders blank** |

The two "renders blank" rows are not in spec §5 but are named explicitly in
`IMP-036` ("the Hub dashboard and crew board"), so they are in scope here.
`hubClock.js`, `hubAdmin.js`, `hubSupervisor.js`, `hubTechnician.js`,
`hubTimesheets.js`, `hubPriorities.js`, `hubGraphs.js` are **not edited** — they
are pure mount functions with no loading state of their own; their loading
states live in `userHub.js`.

### Deliberate deviation from the spec

Spec §3 says `skeletonCard` randomizes body-line widths "between ~60–95%". This
plan uses a **deterministic repeating cycle** of the same widths instead
(`92%, 78%, 85%, 66%, 95%, 72%`). Same visual goal — repeated cards don't look
mechanically identical — without nondeterministic rendering, which would make
the owner's side-by-side manual checks non-reproducible. Flag to the owner at
review; reverting to `Math.random()` is a one-line change if they prefer it.

### Accessibility note (applies to every conversion)

The visible `Loading…` text was announced by screen readers. Removing it without
a replacement is a regression, so every skeleton block carries a
`<span class="sr-only">Loading…</span>` (the `.sr-only` class already exists and
is used in `items.js:214`) and the decorative bars are `aria-hidden="true"`.
This is handled inside `skeleton.js` — views get it for free.

---

## File Structure

**Created:**
- `backend/static/skeleton.js` — the three generator functions plus their shared
  private helpers. Pure string builders, no imports, no DOM.

**Modified:**
- `backend/static/styles.css` — one new `SKELETON LOADERS` section inserted
  immediately before `/* =================== TABLES =================== */`
  (currently line 785).
- `backend/static/views/items.js` — hoist the column model out of
  `renderItems`, add `renderItemsSkeleton()`.
- `backend/static/views/history.js`, `views/tools.js`, `views/users.js` — table
  placeholder swaps.
- `backend/static/views/workOrders.js`, `views/massStage.js` — card placeholder
  swaps.
- `backend/static/views/addBarcode.js` — list placeholder swap.
- `backend/static/views/userHub.js` — tab-mount placeholder swaps plus the two
  new blank-mount skeletons.
- `docs/open-work.md`, `docs/design-system.md`,
  `docs/superpowers/specs/2026-08-23-skeleton-loaders-design.md` — closeout.

---

## Task 1: Skeleton module and styles

**Files:**
- Create: `backend/static/skeleton.js`
- Modify: `backend/static/styles.css` (insert new section before line 785)
- Test: none (D6 — manual validation only)

**Interfaces:**
- Consumes: nothing.
- Produces: `skeletonTableRows(colCount, rowCount = 5, { widths = null } = {})`,
  `skeletonCard({ lines = 3, hasHeader = true } = {})`,
  `skeletonList(itemCount = 4)` — all return HTML strings. CSS classes
  `.skel-line`, `.skel-line--head`, `.skel-line--sub`, `.skel-card`,
  `.skel-list-item`, `.skel-grid`.

- [ ] **Step 1: Write `backend/static/skeleton.js`**

```js
// Shared skeleton-loader markup for in-flight, DB-backed views.
//
// Layer: shared helper (same tier as format.js / dom.js). Pure functions in,
// HTML strings out -- no DOM access and no state, matching how every view in
// this app builds `innerHTML` directly.
//
// These replace the app's old `<p class="hint">Loading…</p>` /
// `<td class="hint">Loading…</td>` placeholders. Callers keep their own
// busy-state machinery (request-id guards, disabled buttons, error paths)
// exactly as it was -- only the in-flight markup changes.
//
// Screen readers: the visible "Loading…" text these replace was announced,
// so every block carries an .sr-only "Loading…" and marks the decorative
// bars aria-hidden. Callers get that for free and must not add their own.
//
// See docs/superpowers/specs/2026-08-23-skeleton-loaders-design.md.

// Deterministic width cycle for body lines. Deterministic rather than random
// (spec §3) so a repeated card still looks organic but two renders of the
// same view are pixel-identical -- manual visual checks stay reproducible.
const BODY_WIDTHS = ["92%", "78%", "85%", "66%", "95%", "72%"];

const SR_LOADING = `<span class="sr-only">Loading…</span>`;

function bodyWidth(index) {
  return BODY_WIDTHS[index % BODY_WIDTHS.length];
}

function line(width, extraClass = "") {
  const cls = extraClass ? `skel-line ${extraClass}` : "skel-line";
  return `<span class="${cls}" style="width: ${width}" aria-hidden="true"></span>`;
}

// `rowCount` skeleton table rows of `colCount` cells each. `widths` is an
// optional array (same length as colCount) of CSS widths, so a view can keep
// its narrow columns narrow instead of every cell getting a full-width bar.
export function skeletonTableRows(colCount, rowCount = 5, { widths = null } = {}) {
  const cells = [];
  for (let row = 0; row < rowCount; row += 1) {
    const tds = [];
    for (let col = 0; col < colCount; col += 1) {
      const width = widths && widths[col] ? widths[col] : bodyWidth(row + col);
      // The sr-only text rides in the first cell of the first row only --
      // one announcement per loading region, not one per bar.
      const sr = row === 0 && col === 0 ? SR_LOADING : "";
      tds.push(`<td>${sr}${line(width)}</td>`);
    }
    cells.push(`<tr class="skel-row">${tds.join("")}</tr>`);
  }
  return cells.join("");
}

// One card-shaped block: an optional wider/taller header bar over `lines`
// body bars of varying width.
export function skeletonCard({ lines = 3, hasHeader = true } = {}) {
  const head = hasHeader ? line("42%", "skel-line--head") : "";
  const body = [];
  for (let i = 0; i < lines; i += 1) body.push(line(bodyWidth(i)));
  return `<div class="skel-card">${SR_LOADING}${head}${body.join("")}</div>`;
}

// `itemCount` stacked two-line groups (title bar + shorter subtitle bar), for
// list-style panels that are neither tables nor cards.
export function skeletonList(itemCount = 4) {
  const items = [];
  for (let i = 0; i < itemCount; i += 1) {
    const sr = i === 0 ? SR_LOADING : "";
    items.push(
      `<div class="skel-list-item">${sr}` +
      line(bodyWidth(i)) +
      line(bodyWidth(i + 3), "skel-line--sub") +
      `</div>`
    );
  }
  return items.join("");
}
```

- [ ] **Step 2: Verify the module parses**

Run: `node --check backend/static/skeleton.js`
Expected: no output, exit code 0.

- [ ] **Step 3: Add the CSS section**

Open `backend/static/styles.css`, find line 785
(`/* =================== TABLES =================== */`), and insert this
block **immediately above** it:

```css
/* =================== SKELETON LOADERS =================== */
/* In-flight placeholders for DB-backed views (IMP-036). Markup comes from
   static/skeleton.js -- no view hand-writes these classes. Colors reuse the
   existing panel tokens (spec D3): --panel-well at rest, --panel-hover at the
   pulse peak, so no new :root token is introduced. */

.skel-line {
    display: block;
    height: .8em;
    margin: var(--space-1) 0;
    background-color: var(--panel-well);
    border-radius: var(--radius-sm);
    animation: skel-pulse 1.5s ease-in-out infinite;
}

.skel-line--head {
    height: 1.15em;
    margin-bottom: var(--space-3);
}

.skel-line--sub {
    height: .65em;
}

.skel-card {
    background: var(--panel-nested);
    border: var(--border);
    border-radius: var(--radius-md);
    padding: var(--space-4);
    margin-bottom: var(--space-3);
}

.skel-list-item {
    padding: var(--space-2) 0;
}

/* Card-grid loading state, sized to match .hub-graph-grid so the Hub tabs
   don't reflow when the real cards land. */
.skel-grid {
    display: grid;
    grid-template-columns: repeat(auto-fit, minmax(245px, 1fr));
    gap: var(--space-4);
}

@keyframes skel-pulse {
    0%, 100% { background-color: var(--panel-well); }
    50%      { background-color: var(--panel-hover); }
}

/* Spec D2: the pulse is decoration, not information -- it goes away entirely
   rather than slowing down. */
@media (prefers-reduced-motion: reduce) {
    .skel-line {
        animation: none;
        background-color: var(--panel-well);
    }
}

```

- [ ] **Step 4: Confirm no token was invented**

Run: `git diff -U0 backend/static/styles.css | grep -E "^\+.*--[a-z-]+:" || echo "no new custom properties — OK"`
Expected: `no new custom properties — OK`. If any line prints, you declared a
new custom property, which violates D3 — remove it and reuse an existing token.

- [ ] **Step 5: Commit**

```bash
git add backend/static/skeleton.js backend/static/styles.css
git commit -m "feat(ui): add shared skeleton-loader module and styles (IMP-036)"
```

---

## Task 2: Items search results table

The reference conversion — every later table task follows its shape. Items also
needs a small refactor: the column model lives inside `renderItems`, but the
loading path needs the same model to know how many columns to draw, so it moves
to module scope.

**Files:**
- Modify: `backend/static/views/items.js` (imports; `loadItemResults` at :131;
  `renderItems` column block at :193-250)
- Test: none (D6)

**Interfaces:**
- Consumes: `skeletonTableRows` from Task 1.
- Produces: module-level `itemColumns()` in `items.js`, returning an array of
  `{ label, cell, primary?, tdClass?, skelWidth }`. Nothing outside `items.js`
  consumes it.

- [ ] **Step 1: Add the import**

After the existing `import { toolScanWidget } from "./tools.js";` line (`:47`),
add:

```js
import { skeletonTableRows } from "../skeleton.js";
```

- [ ] **Step 2: Hoist the column model to module scope**

In `renderItems`, the block currently running from `const role = getRole();`
(`:193`) through the `if (canAdmin || canNotes) { columns.push(...) }` block
(`:245-247`) moves out of the function. Delete it from `renderItems` and insert
this at module scope, just above `export function renderItems(...)`:

```js
// Column model in render order, shared by the real table and its skeleton so
// they can never desync. `primary` marks the name cell (hoisted big on mobile
// cards); `tdClass` styles the cell; `skelWidth` is the placeholder bar width
// for that column, chosen to echo how wide the real content usually is.
//
// Items are read/write for TechFM OA and above; Supervisor may edit notes
// only; Technician is read-only. The backend is still the source of truth --
// this is purely UI gating.
function itemColumns() {
  const role = getRole();
  const canAdmin = roleAtLeast(role, "techfm_oa");
  const canNotes = roleAtLeast(role, "supervisor");
  // A "worker" here is a Technician: no row actions, so we declutter their
  // lookup table (drop the empty Actions column and the Created timestamp)
  // and lead with the fields they care about on the floor -- quantity and
  // location -- closest to the item name. Supervisor+ keep the full table.
  const isWorker = !canNotes;

  // Per-row Actions menu (only the actions this role can perform). Returns
  // the empty string for a role with no actions, so the column is omitted.
  function actionsCell(item) {
    const options = [];
    if (canAdmin) options.push(`<option value="edit">Edit Details</option>`);
    if (canNotes) options.push(`<option value="notes">Notes</option>`);
    if (canAdmin) {
      options.push(`<option value="correct">Correct Count</option>`);
      options.push(`<option value="delete">Archive Item</option>`);
    }
    if (options.length === 0) return "";
    const ariaLabel = `Actions for ${item.name}`;
    return `<label class="sr-only" for="row-actions-${item.id}">${escapeHtml(ariaLabel)}</label>
       <select id="row-actions-${item.id}" class="row-actions-select" data-id="${item.id}" aria-label="${escapeHtml(ariaLabel)}">
         <option value="" disabled selected>Actions</option>
         ${options.join("")}
       </select>`;
  }

  const cols = {
    barcode: { label: "Barcode", skelWidth: "70%", cell: i => escapeHtml(i.barcode) },
    name: { label: "Name", primary: true, skelWidth: "88%", cell: i => escapeHtml(i.name) },
    quantity: { label: "Quantity", skelWidth: "30%", cell: i => `<strong>${escapeHtml(i.quantity)}</strong>` },
    location: { label: "Location", skelWidth: "55%", cell: i => escapeHtml(i.location) },
    notes: { label: "Notes", tdClass: "notes-cell", skelWidth: "80%", cell: i => renderNotesSummary(i.notes) },
  };

  // Technicians lead with quantity/location and drop barcode-first ordering;
  // Supervisor+ keep the original column order.
  const columns = isWorker
    ? [cols.name, cols.quantity, cols.location, cols.barcode, cols.notes]
    : [cols.barcode, cols.name, cols.quantity, cols.location, cols.notes];

  if (canAdmin) {
    columns.push({ label: "Price", skelWidth: "40%", cell: i => escapeHtml(formatMoney(i.price)) || "—" });
    columns.push({ label: "Link", skelWidth: "28%", cell: i => productLinkCell(i.product_link) });
  }
  if (!isWorker) {
    columns.push({ label: "Created", skelWidth: "72%", cell: i => escapeHtml(new Date(i.created_at).toLocaleString()) });
  }
  if (canAdmin || canNotes) {
    columns.push({ label: "Actions", skelWidth: "50%", cell: actionsCell });
  }
  return columns;
}
```

Then, in `renderItems`, immediately after `const items = getItems();`, add the
single line that replaces everything you deleted:

```js
  const columns = itemColumns();
```

Everything below that in `renderItems` (the `itemsTheadRow.innerHTML = ...`
header line, the empty-state branch, the row loop) stays exactly as it is.

- [ ] **Step 3: Replace the loading placeholder**

In `loadItemResults` (`:131`), replace this line:

```js
  itemsTbody.innerHTML = `<tr><td colspan="8" class="hint">Loading…</td></tr>`;
```

with:

```js
  renderItemsSkeleton();
```

and add this function directly above `loadItemResults`:

```js
// Shape-matched in-flight state: the real header row is painted too, so the
// skeleton has the same column count and widths the results will land in
// (on a first search the header would otherwise be empty).
function renderItemsSkeleton() {
  const columns = itemColumns();
  itemsTheadRow.innerHTML = columns.map(c => `<th>${escapeHtml(c.label)}</th>`).join("");
  itemsTbody.innerHTML = skeletonTableRows(columns.length, 6, {
    widths: columns.map(c => c.skelWidth),
  });
}
```

- [ ] **Step 4: Verify the file parses and no stale reference survives**

```bash
node --check backend/static/views/items.js
grep -n "Loading…" backend/static/views/items.js
```
Expected: `node --check` silent (exit 0). `grep` prints **only** the comment at
`:103` (`// The results area shows exactly one of: the table (rows, "Loading…", or a`).
Update that comment's wording to say `a skeleton` instead of `"Loading…"`, then
re-run `grep` and expect no matches.

- [ ] **Step 5: Hand the owner the visual check**

Do **not** start the server yourself. Post this to the owner:

> Entry page → Find Item → search for anything. Expect: 6 grey bar rows under a
> correctly-labelled header, pulsing slowly, replaced by real rows when the
> fetch lands. Check as both an owner and a technician login — the technician's
> skeleton should have 5 columns in technician order (Name, Quantity, Location,
> Barcode, Notes), the owner's 8. Then set OS "reduce motion" and confirm the
> bars go static rather than pulsing.

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/items.js
git commit -m "feat(items): shape-matched skeleton for search results (IMP-036)"
```

---

## Task 3: History, Tools, and Users tables

Same pattern as Task 2, but none of these need a column-model refactor — each
already computes its own column count next to the loading call.

**Files:**
- Modify: `backend/static/views/history.js` (`loadHistory` at :122)
- Modify: `backend/static/views/tools.js` (`loadTools` at :686)
- Modify: `backend/static/views/users.js` (`loadUsers` at :70)
- Test: none (D6)

**Interfaces:**
- Consumes: `skeletonTableRows` from Task 1.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Convert `history.js`**

Add to the imports:

```js
import { skeletonTableRows } from "../skeleton.js";
```

Replace, inside the `if (historyResults.hidden) {` block at `:121-124`:

```js
    historyTbody.innerHTML = `<tr><td colspan="8" class="hint">Loading…</td></tr>`;
```

with:

```js
    // Same column count the results will use: 7 base columns, plus Charge for
    // Admin/Owner (see renderHistory).
    const skelCols = roleAtLeast(getRole(), "techfm_oa") ? 8 : 7;
    historyTbody.innerHTML = skeletonTableRows(skelCols, 6, {
      widths: skelCols === 8
        ? ["78%", "85%", "40%", "25%", "60%", "55%", "35%", "45%"]
        : ["78%", "85%", "40%", "25%", "60%", "55%", "45%"],
    });
```

`roleAtLeast` and `getRole` are already imported in this file (used by
`renderHistory` at `:263`) — confirm with
`grep -n "roleAtLeast\|getRole" backend/static/views/history.js | head -5`
before assuming it; add the import if it is missing.

- [ ] **Step 2: Convert `tools.js`**

Add to the imports:

```js
import { skeletonTableRows } from "../skeleton.js";
```

Replace at `:686`:

```js
  toolsTbody.innerHTML = '<tr><td colspan="5" class="hint">Loading…</td></tr>';
```

with:

```js
  // 4 base columns (Barcode, Name, On Hand, Checked Out); Actions is the 5th
  // for a custody manager -- the same split renderTools uses.
  const toolSkelCols = canManageCustody() ? 5 : 4;
  toolsTbody.innerHTML = skeletonTableRows(toolSkelCols, 5, {
    widths: toolSkelCols === 5
      ? ["70%", "88%", "25%", "30%", "50%"]
      : ["70%", "88%", "25%", "30%"],
  });
```

Leave `setMessage(custodyMessage, "Loading tool custody…", "")` on the next
line **untouched** — it is a status-line message (D5, spec §5 out-of-scope).

- [ ] **Step 3: Convert `users.js`**

Add to the imports:

```js
import { skeletonTableRows } from "../skeleton.js";
```

Replace at `:70`:

```js
  usersTbody.innerHTML = `<tr><td colspan="6" class="hint">Loading…</td></tr>`;
```

with:

```js
  usersTbody.innerHTML = skeletonTableRows(6, 5, {
    widths: ["55%", "60%", "70%", "40%", "75%", "50%"],
  });
```

Keep the `// #9: in-progress placeholder ...` comment above it; it still
describes why the placeholder lives in the table body.

- [ ] **Step 4: Verify all three parse and are converted**

```bash
node --check backend/static/views/history.js
node --check backend/static/views/tools.js
node --check backend/static/views/users.js
grep -n "Loading…" backend/static/views/history.js backend/static/views/users.js
grep -n "Loading…" backend/static/views/tools.js
```
Expected: three silent `node --check` runs; the first `grep` (history + users)
prints nothing; the second prints exactly one line — the `custodyMessage` status
line `setMessage(custodyMessage, "Loading tool custody…", "")`, which is
intentionally kept per D5.

- [ ] **Step 5: Hand the owner the visual check**

> History page (as Owner, then as a Technician) — expect 6 skeleton rows with
> 8 columns for Owner and 7 for the Technician. Tools page → Inventory — 5
> skeleton rows, 5 columns for a custody manager and 4 otherwise, with the
> "Loading tool custody…" text still on the message line below. Saved Users —
> 5 skeleton rows, 6 columns.

- [ ] **Step 6: Commit**

```bash
git add backend/static/views/history.js backend/static/views/tools.js backend/static/views/users.js
git commit -m "feat(ui): skeleton rows for history, tools, and users tables (IMP-036)"
```

---

## Task 4: Work-order and mass-stage card bodies

**Files:**
- Modify: `backend/static/views/workOrders.js` (`buildCard` :1222,
  `openWorkOrderPage` :1269, `openWorkOrderPageByNumber` :1296,
  `mountWorkOrderList.refresh` :1375)
- Modify: `backend/static/views/massStage.js` (`buildStageCard` :120)
- Test: none (D6)

**Interfaces:**
- Consumes: `skeletonCard` from Task 1.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Convert the four `workOrders.js` sites**

Add to the imports:

```js
import { skeletonCard } from "../skeleton.js";
```

In `buildCard` (`:1222`), a collapsed card's body is the small detail area, so
it gets one headerless card of 3 lines:

```js
  body.innerHTML = skeletonCard({ lines: 3, hasHeader: false });
```

In `openWorkOrderPage` (`:1269`) and `openWorkOrderPageByNumber` (`:1296`), the
list element is standing in for a whole card page, so it gets a headed card
with more body lines:

```js
  listEl.innerHTML = skeletonCard({ lines: 6 });
```

In `mountWorkOrderList`'s `refresh` (`:1375`), the container is standing in for
a *list* of collapsed cards, so it gets three summary-sized cards:

```js
    container.innerHTML = skeletonCard({ lines: 1 }).repeat(3);
```

- [ ] **Step 2: Convert `massStage.js`**

Add to the imports:

```js
import { skeletonCard } from "../skeleton.js";
```

Replace at `:120`, inside `buildStageCard`:

```js
  body.innerHTML = `<p class="hint">Loading…</p>`;
```

with:

```js
  body.innerHTML = skeletonCard({ lines: 4, hasHeader: false });
```

Note: `renderLoadingBody` in this file is **not** a loading state — it renders
a stage whose *status* is "loading". Do not touch it.

- [ ] **Step 3: Verify**

```bash
node --check backend/static/views/workOrders.js
node --check backend/static/views/massStage.js
grep -n "Loading…" backend/static/views/workOrders.js backend/static/views/massStage.js
```
Expected: both `node --check` silent; `grep` prints nothing.

- [ ] **Step 4: Hand the owner the visual check**

> Work Orders page: the list should show three skeleton cards before the real
> cards land. Click one — the card page shows a headed skeleton card while the
> detail loads. Open a work order by URL/bookmark (the by-number path) and
> confirm the same. Mass Stage: expand a stage card and watch its body show a
> 4-line skeleton before the load list appears.

- [ ] **Step 5: Commit**

```bash
git add backend/static/views/workOrders.js backend/static/views/massStage.js
git commit -m "feat(work-orders): skeleton card bodies for work orders and mass stage (IMP-036)"
```

---

## Task 5: Add-barcode item search list

**Files:**
- Modify: `backend/static/views/addBarcode.js` (`renderResults` :87)
- Test: none (D6)

**Interfaces:**
- Consumes: `skeletonList` from Task 1.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Convert the placeholder**

Add to the imports:

```js
import { skeletonList } from "../skeleton.js";
```

Replace at `:87`:

```js
  resultsEl.innerHTML = `<p class="hint">Loading…</p>`;
```

with:

```js
  resultsEl.innerHTML = skeletonList(3);
```

Three, not four: this list is capped by `MAX_RESULTS` and sits inside a
narrow editor panel, so a taller placeholder would push the form controls
around when it collapses to real results.

- [ ] **Step 2: Verify**

```bash
node --check backend/static/views/addBarcode.js
grep -n "Loading…" backend/static/views/addBarcode.js
```
Expected: silent, then no matches.

- [ ] **Step 3: Hand the owner the visual check**

> Entry page → an item's Actions → Add Barcode → type a partial item name.
> Expect three two-line skeleton groups during the 200ms debounce + fetch,
> replaced by the real result buttons. Confirm the panel doesn't jump when they
> swap.

- [ ] **Step 4: Commit**

```bash
git add backend/static/views/addBarcode.js
git commit -m "feat(items): skeleton list for add-barcode item search (IMP-036)"
```

---

## Task 6: User Hub tabs, dashboard, and crew board

Four sites: two existing `Loading…` placeholders (timesheets, graphs) and two
areas that currently render **blank** while their fetch is in flight (the
dashboard on first load, the crew board). `IMP-036` names both blanks
explicitly, so they are converted here.

**Files:**
- Modify: `backend/static/views/userHub.js` (`loadTimesheets` :225-235,
  `loadGraphs` :259-264, `refreshCrew` :281-295, `loadUserHub` :359-365)
- Test: none (D6)

**Interfaces:**
- Consumes: `skeletonCard` from Task 1.
- Produces: nothing consumed elsewhere.

- [ ] **Step 1: Add the import and a local grid helper**

Add to the imports:

```js
import { skeletonCard } from "../skeleton.js";
```

and add this helper at module scope, just above `function showTab(name)`:

```js
// Hub tabs are card grids, so their in-flight state is a grid of skeleton
// cards rather than one block -- the tab keeps roughly the height it will
// have once the payload lands, so the page doesn't jump on arrival.
function hubSkeletonGrid(cardCount = 4, { lines = 3 } = {}) {
  return `<div class="skel-grid">${skeletonCard({ lines }).repeat(cardCount)}</div>`;
}
```

- [ ] **Step 2: Convert the timesheets tab**

In `loadTimesheets`, the `else` branch at `:233-235` currently reads:

```js
  } else {
    mount.innerHTML = `<p class="hint hub-timesheet-message">Loading…</p>`;
  }
```

Replace the inner line with:

```js
    mount.innerHTML = hubSkeletonGrid(2, { lines: 6 });
```

Leave the `if (latestTimesheetPayload && existingStatus)` branch above it
**unchanged** — that path sets `existingStatus.textContent = "Loading…"` on a
status line while a fully-rendered grid is still on screen, which is exactly
the out-of-scope case in spec §5.

- [ ] **Step 3: Convert the graphs tab**

In `loadGraphs`, replace `:263`:

```js
    mount.innerHTML = `<p class="hint">Loading graphs…</p>`;
```

with:

```js
    mount.innerHTML = hubSkeletonGrid(4);
```

- [ ] **Step 4: Add the crew-board skeleton**

In `refreshCrew`, insert one line immediately after
`const requestId = ++crewRequestId;`:

```js
  // Foreground first load only: a background refresh keeps the last good
  // board on screen (same rule the error path below follows).
  if (!background && !latestCrewPayload) mount.innerHTML = skeletonCard({ lines: 4 });
```

- [ ] **Step 5: Add the dashboard first-load skeleton**

In `loadUserHub`, insert immediately before the `try {` that wraps
`await apiGetHub()`:

```js
  // First entry only: the dashboard tab is empty until the payload lands, so
  // it gets structure to look at. On a return visit the previous render is
  // still mounted and is better than a skeleton.
  if (!latestPayload) tabPanels.dashboard.innerHTML = hubSkeletonGrid(3);
```

This is safe because `mountHubDashboard` rebuilds the tab body wholesale on
every render (see the comment at `:129-131`) — the skeleton is discarded, not
merged.

- [ ] **Step 6: Verify**

```bash
node --check backend/static/views/userHub.js
grep -n "Loading…" backend/static/views/userHub.js
```
Expected: `node --check` silent; `grep` prints **only** `:232`
(`existingStatus.textContent = "Loading…";`), the intentionally-kept status line.

- [ ] **Step 7: Hand the owner the visual check**

> Log in fresh and open User Hub. Expect: dashboard shows 3 skeleton cards in a
> grid, then the real tiles; the crew board area (Supervisor+) shows its own
> skeleton card before the crew payload lands. Switch to Timesheets — two tall
> skeleton cards, then the grid; change the week and confirm the *status line*
> still shows plain "Loading…" over the existing grid rather than blanking it.
> Switch to Graphs (Admin/Owner) — four skeleton cards, then the donuts.

- [ ] **Step 8: Commit**

```bash
git add backend/static/views/userHub.js
git commit -m "feat(hub): skeleton loading states for hub dashboard, crew, timesheets, graphs (IMP-036)"
```

---

## Task 7: Documentation closeout

**Files:**
- Modify: `docs/open-work.md` (IMP-036 entry at :99)
- Modify: `docs/design-system.md`
- Modify: `docs/superpowers/specs/2026-08-23-skeleton-loaders-design.md` (status
  line at :3)
- Test: none

**Interfaces:**
- Consumes: the finished implementation from Tasks 1-6.
- Produces: nothing.

- [ ] **Step 1: Remove IMP-036 from `docs/open-work.md`**

`open-work.md` is titled *"every named improvement **not yet implemented**"* and
its preamble states shipped history is dropped because git holds it — so an
implemented item is **deleted**, not annotated. Delete the whole
`### IMP-036 — App-wide skeleton loading states` section (currently lines 99-123,
from that heading down to and including `Request logged only; no implementation
yet.`, stopping before `### IMP-034 — User Hub (role-scoped landing page)`).

Do not touch `PRO-008`, `PRO-012`, `SCL-*`, or `N4` — all four remain open, and
this work deliberately changed none of them.

> **Note:** `docs/open-work.md` already had uncommitted edits in the working tree
> before this plan started. Stage only your IMP-036 deletion
> (`git add -p docs/open-work.md`); do not sweep the unrelated changes into this
> commit.

- [ ] **Step 2: Document the pattern in `docs/design-system.md`**

That file's sections are `## Brand`, `## The canvas`, `## Two surface types`,
`## Color on a dark surface`, `## Brand art assets`. Insert a new `## Loading
states` section **immediately before `## Brand art assets`**, matching the
surrounding prose style:

```markdown
## Loading states

A DB-backed view shows shape-matched skeleton blocks while its fetch is in
flight — never bare "Loading…" text. All of the markup comes from
`backend/static/skeleton.js`; a view calls a helper and never hand-writes
`.skel-*` HTML, so the look is retuned in one place:

- `skeletonTableRows(colCount, rowCount = 5, { widths })` — table bodies. Pass
  `widths` so narrow columns (quantity, status, actions) get narrow bars.
- `skeletonCard({ lines = 3, hasHeader = true })` — one card-shaped block.
- `skeletonList(itemCount = 4)` — stacked title/subtitle pairs for list panels.

Color reuses the panel tokens rather than adding its own: `--panel-well` at
rest pulsing to `--panel-hover` over 1.5s, on `--panel-nested` card surfaces.
The pulse is decoration, not information, so it is removed outright under
`prefers-reduced-motion: reduce` rather than slowed. Each block carries an
`.sr-only` "Loading…" and marks its bars `aria-hidden`, preserving the
announcement the old text placeholder made.

Skeletons are for a *fetch*, not for work: client-side filtering or sorting of
data already in memory has nothing to mask and gets no skeleton. Transient
status text beside already-rendered content (`setMessage(el, "Loading…")`)
stays text.
```

- [ ] **Step 3: Update the spec's status line**

In `docs/superpowers/specs/2026-08-23-skeleton-loaders-design.md`, change
line 3 from:

```markdown
Status: **draft, iteration 1.** Written 2026-08-23. Not yet approved; not yet planned.
```

to:

```markdown
Status: **implemented 2026-08-23.** Planned in
`docs/superpowers/plans/2026-08-23-skeleton-loaders.md`; see that plan's
"Spec-vs-code reconciliation" section for the corrections to §5's file list.
```

- [ ] **Step 4: Verify the docs contract still holds**

Run: `ls docs/*.md`
Expected: exactly the seven existing files — `adding-a-notification-trigger.md`,
`current-state.md`, `design-system.md`, `endpoint-map.md`,
`notification-events.md`, `open-work.md`, `project-summary.md`. No new file was
created in `docs/`; `open-work.md` is still the only backlog.

- [ ] **Step 5: Commit**

```bash
git add docs/open-work.md docs/design-system.md docs/superpowers/specs/2026-08-23-skeleton-loaders-design.md
git commit -m "docs: close IMP-036 and document the skeleton-loader pattern"
```

---

## Final verification (after all tasks)

- [ ] Every content-area placeholder is gone and only the four status-line
  messages remain:

```bash
grep -rn "Loading" backend/static/views/ backend/static/*.js
```
Expected — exactly these five, and nothing else:
- `views/adminReview.js` — `setMessage(listMessage, "Loading Review work orders…", "")`
- `views/tools.js` — `setMessage(custodyMessage, "Loading tool custody…", "")`
- `views/transactions.js` — `setMessage(woGateCardsMessage, … "Loading work orders…", "")`
- `views/userRequests.js` — `setMessage(messageEl, \`Loading ${status} requests...\`, "")`
- `views/userHub.js:232` — `existingStatus.textContent = "Loading…"`
- (plus the unrelated `api.js:426` code comment)

- [ ] No new design token was added:

```bash
git diff main --stat -- backend/static/styles.css
git diff main -- backend/static/styles.css | grep -E "^\+\s+--" || echo "no new tokens — OK"
```
Expected: `no new tokens — OK`.

- [ ] Spec §7 / `N4` sanity check — every static asset is a Python round-trip
  re-read from disk on each request, so record what this branch added:

```bash
wc -c backend/static/skeleton.js backend/static/styles.css
git show main:backend/static/styles.css | wc -c
```
Expected: `skeleton.js` in the low single-digit KB and `styles.css` grown by
roughly 1 KB. Report the actual numbers to the owner. This is not a blocker —
it is the same tradeoff `N4` already tracks — but the figures belong in the
review so `N4`'s trigger stays evidence-backed.

- [ ] Backend tests still pass (nothing here touches Python, so this is a
  regression check that no static asset the app serves is malformed):

```bash
cd backend && python -m pytest -q
```
Expected: the same pass count as before this branch. Report the actual output —
do not claim it passed without pasting it.

- [ ] Owner has confirmed the visual checks from Tasks 2-6. **Do not merge to
  `main` without asking** — merging deploys to production.
