# Field-Help Tooltips (`?` bubbles) — Design Spec

Status: **designed 2026-08-23. Steps 0–4 and 6 done; steps 5 and 7 open.**
Written to be picked up cold by a later session — read this file top to bottom,
then work §8's numbered steps in order, starting at **step 5**. Step 5 is
gated on the owner's manual check of Work Orders (§8 step 4).

**Read §5.5 before wiring any anchor.** It records a constraint found during
step 4 that the original design missed and that changes nine of §7's anchors.

Adds a small `?` bubble beside labels, headings and controls that carry
non-obvious domain rules. Hovering (desktop) or tapping (mobile) opens a short
explanation. Tracks `IMP-037` in `docs/open-work.md`.

---

## 1. Why this exists

The app explains itself today with `<p class="hint">` / `<p class="field-hint">`
prose blocks sitting permanently under the thing they describe. That mechanism
has three problems:

1. **It costs vertical space forever.** `user-requests.html:10` spends seven
   lines of screen explaining three request types; `admin-review.html:10` spends
   three explaining the receipt. On a jobsite phone that pushes the actual
   controls below the fold.
2. **It only reaches static HTML.** Roughly half the places that need
   explanation — work-order cards, user-request cards, hub tiles — are built as
   `innerHTML` strings in JS views, where there is no natural place to hang a
   paragraph of prose.
3. **It is all-or-nothing.** A rule is either always on screen or nowhere. There
   is no "tell me only if I ask."

Native `title=` is not the answer: it exists in only six places app-wide
(`hubTechnician.js`, `itemEditor.js`, `notes.js`, `users.js`, `workOrders.js`),
it is invisible on touch devices, it cannot be styled, and its ~1s hover delay
is unreliable.

**This is a pure information-surface change.** It adds no endpoints, no state,
no data model, and — per §2/D7 — removes nothing on the first pass.

---

## 2. Decisions locked

Settled with the owner on 2026-08-23 via brainstorming. Changing any of these
reopens the design.

| # | Decision | Choice |
|---|---|---|
| D1 | Content authoring | **Central registry.** One module maps a stable string key → `{ label, text }`. Markup at each anchor declares only the key. |
| D2 | Trigger | A real `<button type="button">` rendering `?`. **Click/tap toggles on every device**; on `(hover: hover)` pointers, hover also opens. One code path, so mobile is not a second-class case. |
| D3 | Positioning | **One body-appended singleton `<div>`, `position: fixed`, coordinates set via CSSOM.** Not `position: absolute` inside the anchor. |
| D4 | Layout impact | **Strictly additive.** The trigger renders inside an existing `<label>` / `<h2>` / `<th>` text node — never as a new sibling in a flex row — and is height-constrained to the line box so nothing reflows. |
| D5 | Content shape | Plain text, 1–3 sentences, no markup, no links. Escaped through `escapeHtml` on render. |
| D6 | Wiring | **One delegated listener on `document`.** No per-view registration, no re-binding after a re-render. |
| D7 | Existing `.hint` prose | **Left in place on the first pass.** Deleting a hint paragraph *is* a layout change, which the owner's additive constraint forbids. Collapsing redundant hints is a separate, explicitly-approved phase (§9). |
| D8 | Testing | **Manual validation only**, consistent with the rest of the frontend (`PRO-008`: no automated frontend render coverage exists). |

---

## 3. Hard constraints discovered in the code

These are not preferences. Each one was verified and each one kills an obvious
implementation.

### 3.1 The CSP drops inline `style=` attributes

`backend/app/main.py:143-151` sets `default-src 'self'` with **no `style-src`
directive**. `style-src` therefore falls back to `default-src`, which does not
include `'unsafe-inline'`, so the browser discards `style` attributes parsed out
of markup. `views/hubTechnician.js:84-88` already documents this and works
around it by writing positions through CSSOM after insertion.

**Consequence:** the bubble's `left`/`top` must be assigned as
`bubble.style.left = ...` in JS (a CSSOM write, outside CSP's scope). A
template literal emitting `style="left:…"` will silently do nothing. There can
also be no `<style>` block — every rule goes in `styles.css`.

> **This already bit us once — fixed 2026-08-23 in commit `b008cc3`.**
> `skeleton.js` emitted `style="width: ${width}"` and `.skel-line` declared no
> `width`, so every skeleton bar from `IMP-036` rendered full-width instead of
> the intended varied widths. Nobody noticed because there is no error — the
> attribute simply vanishes. Widths now ride on a `.skel-w-NN` class ladder
> (25–95 in steps of 5, `styles.css`), with `snapWidth()` rounding
> caller-supplied percentage strings onto it so all ~12 call sites were
> unchanged.
>
> **Carry the lesson into the tooltip work:** the failure mode is silent. When
> the bubble does not appear where it should, check first whether the position
> was written as an attribute rather than through CSSOM — that will look like a
> positioning bug and is not one.

### 3.2 Table scroll containers clip anything positioned inside them

`styles.css:1237` and `styles.css:2284` set `overflow-x: auto` on table
wrappers. An `absolute`-positioned bubble anchored to a `<th>` or a cell inside
one of those gets cut at the container edge, and on a narrow phone that is most
of the bubble.

**Consequence:** D3. A `fixed`-positioned node parented to `<body>` is outside
every scroll container and every stacking context in the page, so it cannot be
clipped by an ancestor's `overflow`.

### 3.3 Icons must be text or inline SVG

Same CSP: no external font can load, so an icon font is unavailable. Existing
icons are inline SVG (`saved-items.html:15-19`, `shell-head.html:89`). A literal
`?` character is simpler than an SVG here and scales with the label's font-size
automatically — use the character.

### 3.4 There is an established floating-popover recipe — match it

`.wo-combo-list` (`styles.css:3794-3810`) and `.wo-tech-results`
(`styles.css:3700`) are the app's existing popovers: `z-index: 20`,
`background-color: var(--color-header)` (opaque, not translucent — a floating
layer over a frosted panel needs to be opaque to stay readable),
`border: 1px solid var(--gray-700)`, `border-radius: var(--radius-sm)`,
`box-shadow: var(--shadow-md)`.

**Consequence:** the tooltip bubble reuses that exact recipe. Do not invent a
new floating surface; `docs/design-system.md` explicitly warns against reusing
the `--glass-*` tokens for anything that isn't over brand art.

### 3.5 Red is reserved

`docs/design-system.md`: `--color-brand` is the primary-action colour, and it is
only 2.6:1 on the canvas. The `?` glyph is **not** red. It is
`--text-panel-mute` at rest, `--text-panel` on hover/open — a quiet affordance,
not a call to action.

---

## 4. Architecture

Three new files plus edits to `styles.css`. The split follows the precedent set
by `backend/static/skeleton.js` (a shared helper tier alongside `dom.js` /
`format.js`: pure functions in, HTML strings out).

```
backend/static/tips.js      — the copy registry (data only, no logic)
backend/static/tooltip.js   — the mechanism (markup helper + delegated runtime)
backend/static/styles.css   — .tip-btn and .tip-bubble rules
```

### 4.1 `tips.js` — the registry

Data only, so the whole body of field-help copy can be read and edited as prose
in one place. No imports, no functions.

```js
// Field-help copy for the `?` bubbles. Keys are stable ids referenced from
// markup via data-tip; see docs/superpowers/specs/2026-08-23-tooltips-design.md.
//
// `label` is the accessible name of the button ("Help: <thing>"); `text` is the
// bubble body. Plain text only -- both are escaped at render time.
export const TIPS = {
  "wo.priority-vs-level": {
    label: "Priority and Priority level",
    text: "Priority is the imported NetFacilities category. Priority level is TechFM's own High/Medium triage on top of it. They filter independently.",
  },
  // ...
};
```

**Key naming:** `<area>.<thing>`, lowercase, dot-separated —
`txn.quick-mode`, `item.product-link`, `history.date-range`. The area prefix
keeps the registry grouped by page when sorted, which is how it will be
reviewed.

### 4.2 `tooltip.js` — the mechanism

Two exports plus a self-installing runtime.

```js
tipHtml(key)   // -> '<button type="button" class="tip-btn" data-tip="KEY" aria-label="…">?</button>'
closeTip()     // imperative close, for nav/page-change hooks
installTooltips()  // called once from main.js: binds the delegated listeners
```

`tipHtml(key)` is a pure function returning a string, so JS views can
interpolate it into their existing `innerHTML` templates exactly the way they
interpolate `skeletonCard()` today. Static HTML pages hand-author the same
markup — the two paths produce identical DOM.

**Why the button carries only the key, never the copy:** it means the static
HTML partials contain no prose. All copy lives in `tips.js` (D1), and the
`aria-label` is filled in at runtime from the registry.

### 4.3 Why one delegated listener (D6)

About half the anchors live in markup that is destroyed and rebuilt on every
refresh — work-order cards (`workOrders.js`), user-request cards
(`userRequestCards.js`), hub tiles (`hubTechnician.js` et al.), search-result
rows (`items.js`, `tools.js`). Per-element listeners would need re-binding after
every render, in every view, forever, and one missed re-bind is a silently dead
`?`.

A single set of listeners on `document`, matching on
`event.target.closest("[data-tip]")`, works for markup that did not exist when
the listener was installed. The app already uses this pattern —
`views/itemRequest.js` delegates on `document` for exactly this reason
(`saved-items.html:53-59` documents why).

### 4.4 The singleton bubble

One `<div class="tip-bubble" role="tooltip" hidden>` is created on
`installTooltips()` and appended to `<body>`. It is reused for every tip: open
sets its `textContent` and coordinates, close hides it. Never more than one
open.

**Why a singleton rather than one bubble per trigger:** ~30 anchors, most of
them inside re-rendered markup. Per-trigger bubbles would be ~30 permanently
parked DOM nodes that views would have to clean up, and an orphaned bubble
whose trigger was re-rendered away would linger on screen. One node with one
lifecycle has neither problem.

### 4.5 Positioning algorithm

On open:

1. `rect = trigger.getBoundingClientRect()`
2. Unhide the bubble (it must be measurable), then
   `bubbleRect = bubble.getBoundingClientRect()`
3. Preferred placement: **below**, horizontally centred on the trigger.
   `top = rect.bottom + 8`, `left = rect.left + rect.width / 2 - bubbleRect.width / 2`
4. **Flip:** if `top + bubbleRect.height > innerHeight - 8`, place above instead
   (`top = rect.top - bubbleRect.height - 8`).
5. **Clamp:** `left = Math.max(8, Math.min(left, innerWidth - bubbleRect.width - 8))`.
   The bubble stays fully on screen even when its trigger is at the viewport
   edge — which is the normal case for a `?` on a right-hand table column.
6. Write `bubble.style.left` / `bubble.style.top` (CSSOM — §3.1).

Because the bubble is `position: fixed`, all of these are viewport coordinates
and no scroll-offset arithmetic is needed.

**No arrow/caret.** A caret has to be positioned independently of the bubble
once clamping kicks in, and it breaks whenever the bubble is clamped away from
its trigger. The 8px offset plus the centring is enough to read the association.

### 4.6 Close triggers

| Event | Why |
|---|---|
| Second click on the same trigger | Toggle — the tap-to-open affordance needs a tap-to-close |
| Click anywhere else | Standard light-dismiss |
| `Escape` keydown | Keyboard parity |
| `scroll` (capture phase, passive) | A `fixed` bubble does not move with the page, so it would visibly detach from its anchor. Closing is cheaper and honest; repositioning on every scroll frame is the thing `docs/design-system.md` warns about for iOS Safari |
| `resize` | Coordinates are stale |
| `pointerleave` on the trigger, if opened by hover and not pinned by a click | Normal hover behaviour |
| `closeTip()` from `nav.js` on page change | See §4.7 |

### 4.7 Page-change integration

`views/nav.js` already owns a per-page lifecycle (`SCANNERS_BY_PAGE`, stop on
page-leave / tab-hide). `closeTip()` is called from the same page-leave path.

Independently, guard against an orphan: before positioning on any interaction,
if `!document.contains(activeTrigger)` the bubble closes. That covers the case
where a background refresh re-rendered the card the open trigger was sitting in.

### 4.8 Unknown keys

If `data-tip` names a key not in `TIPS`, `installTooltips()`'s boot pass hides
that button and `console.warn`s. A visible `?` that opens an empty bubble is
worse than no `?`. This is an authoring error, not a runtime condition, so a
console warning is the right channel — unlike the user-facing errors that
`docs/open-work.md` item #6 covers.

---

## 5. Markup contract and the additive guarantee (D4)

This is the part the owner cares most about. **The `?` must not move a single
existing pixel.**

### 5.1 The rule

> The trigger goes **inside** the element whose text it annotates — the
> `<label>`, `<h2>`, `<h3>`, or `<th>` — as the last inline child, after the
> text.
>
> It never goes in as a new sibling.

```html
<!-- CORRECT: inside the label -->
<label for="quantity">Starting Quantity<button type="button" class="tip-btn" data-tip="item.quantity">?</button></label>

<!-- WRONG: new flex child, shifts the row -->
<label for="quantity">Starting Quantity</label>
<button type="button" class="tip-btn" data-tip="item.quantity">?</button>
```

**Why this specific rule:** several labels live inside `.filter-row`, which is a
flex container (`create-item.html:15`, `history.html:13`, `tools.html:105`,
`work-orders.html:67`). Adding a flex *child* to those rows redistributes space
across every sibling — inputs shrink, buttons wrap. Adding an *inline* child to
the `<label>` grows only the label's own line box.

### 5.2 The no-reflow CSS

```css
.tip-btn {
    display: inline-flex;
    align-items: center;
    justify-content: center;
    width: 1.05em;
    height: 1.05em;
    margin-left: .35em;
    padding: 0;
    border: 1px solid var(--panel-border);
    border-radius: var(--radius-pill);
    background: none;
    color: var(--text-panel-mute);
    font-size: .85em;
    line-height: 1;
    vertical-align: -.08em;
    cursor: help;
}
```

The height constraint is what makes this additive: at `font-size: .85em` and
`height: 1.05em`, the button's box is ~0.9× the parent's font-size, which sits
comfortably inside the inherited `line-height` (`--lh-heading` on headings,
default on labels). It cannot grow the line box, so nothing below it moves.

Note `background: none` and `padding: 0` — the app's global `button` rule sets a
brand-red fill and generous padding; both must be reset or the `?` renders as a
red pill the size of a Save button.

`cursor: help` rather than `pointer`: it is not an action.

### 5.3 Verification, not assumption

Step 5 of §8 is a screenshot diff of every touched page before and after. The
line-box arithmetic above is sound but it is arithmetic, and `--lh-heading`,
`.stack-table` cell padding, and the sub-nav buttons each have their own
metrics. Assume nothing; look at it.

### 5.4 Table headers are the one risky anchor

Adding to a `<th>` grows the header's intrinsic width, which can widen the
column. Exactly one anchor in §7 is a `<th>`: `history.charge-col`
(`history.html:83`). Every other anchor is a `<label>`, `<h2>`/`<h3>`, or a
button. Verify that one specifically at narrow widths, and if the column shifts,
drop the tip rather than fight it — the table layout matters more than the tip.

### 5.5 A `<button>` anchor is impossible — found during step 4

§5.4 called `<th>` the one risky anchor. It is not. **Nine of §7's anchors are
`<button>`s, and a `<button>` cannot contain a `<button>`.** This is not a
styling problem, it is the HTML parser: on a `<button>` start tag while another
button is open, the "in body" insertion mode acts as if `</button>` had been
seen and reprocesses the token. The nested trigger is silently hoisted out and
becomes a *sibling* — which is precisely the new-flex-child reflow §5.1 forbids.
Like the CSP trap in §3.1, the failure mode is silent: no error, valid-looking
markup, a shifted row.

**Owner's call, 2026-08-23:** move each of those tips to the nearest heading or
`<label>`, and drop the ones with no such neighbour rather than fight the
layout — the same reasoning §5.4 already applies to the `<th>`.

| Key | §7 said | Anchor instead |
|---|---|---|
| `tools.custody-vs-inventory` | sub-nav buttons | `<h2>Tool Custody</h2>` (`tools.html:12`) |
| `item.load-all` | Load All Items button | `<label for="items-search">Search</label>` (`saved-items.html:23`) |
| `history.pricing-list` | Pricing list button | `<h2>Transaction History</h2>` (`history.html:5`) |
| `review.reopen-vs-close` | the two action buttons | `<h3 id="admin-review-receipt-title">` (`admin-review.html:18`) |
| `hub.graphs` | Graphs tab button | the Graphs panel's own JS-rendered heading |
| `requests.types` | Type filter `<label>` | unchanged — it was already a label |
| `wo.export` | Export filtered CSV button | **dropped.** `.wo-number-search-row` has no heading, and its `flex: 1 1 260px` input would absorb the loss |
| `txn.quick-mode` | Quick mode toggle | **dropped.** `#scango-active` has no heading |
| `txn.advanced` | Manual entry toggle | **dropped.** Same |
| `txn.direction` | segmented toggle | `<h2>Scan item</h2>` (`transaction.html:71`) — that heading does head the section the toggle sits in. Judgment call at step 5; drop it if it reads as being about scanning rather than direction |

The copy for the dropped keys stays in `tips.js`. It is written and reviewed,
it costs nothing parked, and if any of those controls later grows a heading the
anchor is a one-line change. `installTooltips()` never looks at unreferenced
keys, so an unused entry is inert.

---

## 6. Accessibility

- The trigger is a real `<button type="button">` — focusable, `Enter`/`Space`
  activated, announced as a button. Not a `<span>` with a click handler.
- `aria-label` is set at boot from `TIPS[key].label`, giving "Help: Priority and
  Priority level" rather than "question mark".
- `aria-expanded` on the trigger tracks open state.
- The bubble carries `role="tooltip"` and a stable `id`; on open the trigger
  gets `aria-describedby="<that id>"`, removed on close. This is what makes the
  body text reachable to a screen reader at all.
- `Escape` closes and returns focus to the trigger.
- The bubble is not focusable and contains no interactive content (D5), so
  there is no focus trap to manage.
- Colour is not load-bearing: the `?` is legible by shape, and the bubble is
  text.

---

## 7. Content inventory

The anchors, from the code scan: **35 keys across 12 pages**
(`wo.priority-vs-level` covers two adjacent filters with one tip). Roughly a
third duplicate copy that already exists in a `.hint`; per D7 the paragraph
stays for now.

### Transaction (`pages/transaction.html`)
| Key | Anchor | Substance |
|---|---|---|
| `txn.quick-mode` | `:55` Quick mode toggle | Commits a dispense scan immediately, skipping the confirm. Add Stock always keeps its confirm. Supervisor+ get an Undo on each line; other roles do not. |
| `txn.advanced` | `:62` Manual entry & stock options | Reveals the Add Stock / Take Out direction toggle and browse-all-items mode. |
| `txn.wo-gate` | `:36` Select a work order | Work orders are import-only. A number that has not been imported cannot be scanned into. |
| `txn.direction` | `:96` direction toggle | Add Stock puts material back; Take Out Stock charges it to the work order. |

### Add Item / Tool (`pages/create-item.html`)
| Key | Anchor |
|---|---|
| `item.barcode` | `:14` Barcode |
| `item.location` | `:39` Location |
| `item.price` | `:46` Price (optional) — why it matters: unpriced material used on a work order raises a missing-price request |
| `item.product-link` | `:49` Product Link |
| `tool.quantity` | `:85` Quantity — 1 for a serialized tool, higher for an unserialized batch |

### Find Item (`pages/saved-items.html`)
| Key | Anchor |
|---|---|
| `item.extra-barcodes` | `:121` Additional barcodes |
| `item.correct-count` | `:143` Correct Count |
| `item.correct-reason` | `:152` Why are you changing it? — the reason is audited in History |
| `item.add-barcode` | `:164` Add Barcode to an Item |
| `item.load-all` | `:32` Load All Items — why nothing shows until you search |

### Tools (`pages/tools.html`)
| Key | Anchor |
|---|---|
| `tools.custody-vs-inventory` | `:5-7` sub-nav — user-first custody vs tool-first inventory |
| `tools.checkout-wo` | `:70` Work Order (optional) on checkout |
| `tools.return-wo` | `:90` Work Order (optional) on check-in |
| `tools.correct-reason` | `:146` correction reason |

### Work Orders (`pages/work-orders.html`)
| Key | Anchor |
|---|---|
| `wo.status` | `:18` Status filter — the seven lifecycle states, especially Ready to Complete vs Completed vs Review |
| `wo.priority-vs-level` | `:36` + `:42` — **highest-value tip in the app**; two adjacent filters with near-identical names. One tip, anchored on Priority level |
| `wo.community` | `:56` |
| `wo.scheduled-date` | `:62` |
| `wo.export` | `:72` Export filtered CSV |

### History (`pages/history.html`)
| Key | Anchor |
|---|---|
| `history.wo-filter` | `:14` — filters on the number stored per row, so it survives the work order being archived; an archived number offers restore to Supervisor+ |
| `history.date-range` | `:24` — either side may be blank; the To date is included in full |
| `history.pricing-list` | `:69` Pricing list |
| `history.charge-col` | `:83` Charge column (admin-only) |

### Admin Review (`pages/admin-review.html`)
| Key | Anchor |
|---|---|
| `review.receipt` | `:9` heading — the 41-character receipt |
| `review.reopen-vs-close` | `:22`/`:23` — Return to In-Progress vs Close |

### User Requests (`pages/user-requests.html`)
| Key | Anchor |
|---|---|
| `requests.types` | `:24` Type filter — the three request types, currently a seven-line `.hint` |

### Mass Stage (`pages/mass-stage.html`)
| Key | Anchor |
|---|---|
| `stage.new` | `:8` — plans around already-imported work orders; cannot create one |

### Add User (`pages/create-user.html`)
| Key | Anchor |
|---|---|
| `user.role` | `:16` Role — what each role can do |

### User Hub (`pages/user-hub.html`, JS-rendered)
| Key | Anchor |
|---|---|
| `hub.clock` | `:9` clock widget — auto-closed estimates |
| `hub.graphs` | `:15` Graphs tab — donut legends carry the exact values |

### Integrations (`pages/integrations.html`)
| Key | Anchor |
|---|---|
| `integrations.netfacilities` | `:16` LU card — sign-in flow, Import Tasks and Priority, For Client export |

Exact copy is written during step 2. Keep each to 1–3 sentences; if a tip needs
more, the underlying UI needs fixing instead.

---

## 8. Implementation steps

Work these in order. Each step is independently verifiable; do not batch them.

**Step 0 — Fix the skeleton width bug (§3.1). — ✅ DONE 2026-08-23, `b008cc3`.**
Widths moved onto a `.skel-w-NN` class ladder; `skeleton.js` stays a pure string
builder. Verified by asserting the rendered output contains zero `style=`
attributes, that every emitted `.skel-w-NN` class has a matching CSS rule, and
that non-percentage inputs (`"auto"`) fall back to the deterministic cycle.

*Two things to inherit from it:* the class-ladder pattern is the house answer
for "dynamic value that can't be an inline style" when the emitting module is a
pure string builder; CSSOM (`el.style.x = …`) is the answer when the module
already touches the DOM. `tooltip.js` is the second kind — it owns the bubble
node — so it uses CSSOM, per §4.5 step 6.

⚠️ **Note for whoever picks this up:** `b008cc3` is a broad auto-generated
commit that swept the skeleton fix together with unrelated pre-existing changes
to `docs/open-work.md` and the `IMP-036` plan file. The skeleton fix itself is
correct and verified; just don't expect that SHA to be a clean single-purpose
diff when reading history.

**Step 1 — `backend/static/tooltip.js`, mechanism only. — ✅ DONE, `7b0a828`.**
`tipHtml`, `closeTip`, `installTooltips`, the singleton bubble, the positioning
algorithm (§4.5), the delegated listeners (§4.6). Import a two-entry stub
registry so the module is testable before the copy exists.
Verify: nothing yet — no anchors are wired.

**Step 2 — `backend/static/tips.js`, the copy. — ✅ DONE, `a2d598a`.**
All 35 keys written. Four of them (`wo.export`, `txn.quick-mode`,
`txn.advanced`, and possibly `txn.direction`) are parked unreferenced per §5.5.

Write all ~30 entries from §7. This is a writing task, not a coding task; treat
it that way. Read the referenced `.hint` paragraphs and the code comments in
each page — most of the substance is already written there, just too verbosely.

**Step 3 — Styling in `styles.css`. — ✅ DONE, `79eaa7f`.**
Landed beside `.wo-combo-list`. No new tokens, no new surface type. One thing
§5.2 missed: the global `button` rule also sets `min-height: var(--btn-h)` and
`margin-top: var(--space-1)`, and `button:hover` re-fills brand red — all three
are reset in `.tip-btn` alongside the documented `background`/`padding`.
Note `--fw-normal` does **not** exist in `:root` (two pre-existing rules
reference it and silently get nothing); `.tip-btn` uses `--fw-regular`.

`.tip-btn` per §5.2 and `.tip-bubble` per §3.4. Place them near the other
floating-popover rules (~line 3700-3810), not in `:root` — this adds no tokens.
Add the `docs/design-system.md` note only if a new surface type emerged; it
should not have, since §3.4 reuses the existing recipe.

**Step 4 — Wire one page end to end: Work Orders. — ✅ DONE, `43f4ddb`.
Owner's visual check still outstanding; step 5 is gated on it.**
Four of the five anchors landed (`wo.status`, `wo.priority-vs-level`,
`wo.community`, `wo.scheduled-date`), each inside its existing `<label>`.
`wo.export` did not — see §5.5.
Machine-verified through `TestClient`: all four keys appear in the served DOM,
`tooltip.js` / `tips.js` / the CSS rules are all reachable, the assembled page
emits **zero** `style=` attributes, and the backend suite passes (1426).
What is *not* verified and needs eyes: hover / click / keyboard / Escape /
scroll behaviour, and the no-reflow claim against a before-screenshot.

Add the five `work-orders.html` anchors and call `installTooltips()` from
`main.js`. Work Orders first because it has the highest-value tip
(`wo.priority-vs-level`), it has both static filter labels and JS-rendered
cards, and its filter grid is the layout most likely to break — if the additive
guarantee holds here it holds everywhere.
Verify: open/close by hover, by click, by keyboard; Escape; scroll; rotate to
portrait; confirm no layout shift against a before-screenshot.

**Step 5 — Roll out the remaining pages. ← RESUME HERE, once the owner has
looked at Work Orders.**
Apply §5.5's revised anchor table as you go.
One page per commit, in this order: Transaction, Add Item, Find Item, History,
Tools, User Requests, Admin Review, Mass Stage, Add User, Integrations, User
Hub. Screenshot-diff each page before and after (§5.3). User Hub last because
it is entirely JS-rendered and depends on the delegation working.

**Step 6 — `nav.js` page-change hook. — ✅ DONE, `43f4ddb`.**
`closeTip()` is called from `showPage`'s page-leave path alongside the existing
scanner stop. It landed with step 4 rather than after step 5 because the hook
is needed the moment the first page has a live anchor.

**Step 7 — Docs.**
The `IMP-037` entry is already in `docs/open-work.md` (added late, at step 4,
carrying §5.5's constraint). At step 7, mark it closed there and mark it closed
at step 7, matching how `IMP-036` was tracked. Add a short section to
`docs/design-system.md` covering when a `?` is warranted versus a visible
`.hint` — the rule of thumb being: a `?` for a rule you need once while
learning, a `.hint` for a rule you need every time you use the control.

---

## 9. Explicitly out of scope (first pass)

- **Removing any existing `.hint` / `.field-hint` paragraph.** D7. Once the
  bubbles are in and the owner has used them, a second pass can propose specific
  paragraphs to collapse — as its own change, with its own approval, because it
  is a layout change by definition.
- **Replacing the six existing `title=` attributes.** They are harmless and
  orthogonal.
- **Rich content in bubbles** — links, lists, images (D5). A tip that needs a
  link is documentation, not a tooltip.
- **Any backend change.** No endpoint, no model, no migration.
- **Automated tests.** D8, `PRO-008`.

---

## 10. Considered and rejected

**Native `popover` attribute + CSS anchor positioning.** Would give top-layer
rendering, light-dismiss, and flip/clamp for free, deleting most of §4.5.
Rejected because CSS anchor positioning is Chromium-only at time of writing —
Safari and Firefox would need the JS fallback anyway, so the code would exist
regardless plus a second path to maintain. The `popover` attribute alone
(without anchor positioning) is worth revisiting later as a simplification of
§4.6's dismiss handling; it changes nothing about the design.

**Per-trigger bubble nodes.** §4.4 — orphan and cleanup problems.

**Copy inline at each anchor, matching the `.hint` convention.** Rejected by the
owner in favour of D1. The deciding factor: about half the anchors are in
JS-generated markup with no HTML file to hold prose, so an inline convention
would have forced two different authoring mechanisms.

**Expanding the `.hint` mechanism instead — a collapsible "Learn more" line.**
Cheaper, but it still occupies vertical space in its collapsed state, which is
the primary complaint (§1, problem 1), and it does not solve the
JS-rendered-markup gap (§1, problem 2).

---

## 11. Known tradeoffs

`docs/open-work.md` `N4`: static assets are served `Cache-Control: no-cache` and
re-read from disk per request, so two new JS modules plus a larger `styles.css`
add slightly to per-request cost. Small at current scale — the same tradeoff
`N4` already tracks and the same one the skeleton work accepted. Not a blocker.

The registry (D1) trades locality for auditability: to understand what a `?` on
Work Orders says, you open `tips.js`, not `work-orders.html`. That is the
correct trade for a body of ~30 short strings that wants to be reviewed as a
whole, but it does mean the key naming convention in §4.1 is load-bearing —
a sloppy key makes the registry unnavigable.
