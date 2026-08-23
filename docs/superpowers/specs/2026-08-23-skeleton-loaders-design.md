# App-wide Skeleton Loading States — Design Spec

Status: **draft, iteration 1.** Written 2026-08-23. Not yet approved; not yet planned.

Replaces the app's text-only `Loading…` placeholders with shape-matched skeleton
blocks, shown immediately while a DB-backed view's data is in flight. Tracks
`IMP-036` in `docs/open-work.md`.

---

## 1. Why this exists

Every DB-backed view in the app currently shows a bare `<td class="hint">Loading…</td>`
or `<p class="hint">Loading…</p>` while its fetch is in flight, then swaps in real
content once the response lands. The owner flagged this as a masked-latency
problem, not a real-latency one: the page reads as blank/frozen for that window
rather than showing structure the user can already parse.

This is a **perceived-latency fix only**. It does not reduce query time, change
endpoint behavior, or substitute for the real-latency work already tracked in
`PRO-012` (SLOs/capacity) or the `SCL-` (query-count/index) items — those stay
exactly as scoped.

---

## 2. Decisions locked

Settled with the owner on 2026-08-23 via brainstorming. Changing any of these
reopens the design.

| # | Decision | Choice |
|---|---|---|
| D1 | Fidelity | **Shape-matched.** Skeleton blocks mirror the real layout being loaded (table rows in real column proportions, card outlines matching the real card), not a single generic placeholder reused everywhere. |
| D2 | Motion | **Subtle pulse** — a slow opacity tween on skeleton blocks, not a shimmer sweep. Falls back to static (no animation) under `prefers-reduced-motion: reduce`. |
| D3 | Color | **Reuse existing panel tokens.** `--panel-well` (rest state) / `--panel-hover` (pulse peak). No new color tokens added to `styles.css` `:root`. |
| D4 | Architecture | **Shared helper module**, not per-view hand-written markup. One place to fix or retune the look across ~10+ views. |
| D5 | Scope | **Every content-area `Loading…` placeholder app-wide**, per `IMP-036`'s confirmed app-wide scope. Status-line loading messages (`setMessage(..., "Loading…")`) are out of scope — see §5. |
| D6 | Testing | **Manual validation only**, consistent with the rest of the frontend (`PRO-008`: no automated frontend render coverage exists). No test harness added as part of this work. |

---

## 3. Shared module

New file: `backend/static/skeleton.js`. Exports plain functions returning HTML
strings, matching this codebase's existing pattern of view files building
`innerHTML` directly (no framework, no virtual DOM — confirmed by `items.js`,
`tools.js`, etc.).

```js
skeletonTableRows(colCount, rowCount = 5, { widths } = {})
```
Returns `rowCount` `<tr>` elements, each with `colCount` `<td>`s containing a
`.skel-line`. `widths` is an optional array (same length as `colCount`) of
CSS width values (e.g. `["10%", "auto", "20%"]`) so a view can narrow columns
that are visually narrow in the real table (checkbox/icon columns, short status
badges) instead of every cell getting a full-width bar.

```js
skeletonCard({ lines = 3, hasHeader = true })
```
Returns one card-shaped block: an optional header bar (wider, taller — mimics a
title) followed by `lines` body bars of varying width (each line randomized
between ~60–95% width so a repeated card doesn't look mechanically identical).

```js
skeletonList(itemCount = 4)
```
Returns `itemCount` stacked two-line groups (a "title" bar + a shorter
"subtitle" bar), for list-style panels like the crew board or search-result
lists that aren't tables or cards.

All three are pure functions (input → HTML string), no DOM access, no state —
consistent with how views currently build `innerHTML` snippets. A view swaps
its existing `Loading…` line for a call into this module; the busy-state logic
around it (request-id guards, button disabling, etc.) is untouched.

Example (`items.js:137`):
```js
// before
itemsTbody.innerHTML = `<tr><td colspan="8" class="hint">Loading…</td></tr>`;
// after
itemsTbody.innerHTML = skeletonTableRows(8, 6);
```

---

## 4. Styling

New rules added to `backend/static/styles.css`, placed with the other
panel/token-consuming component rules (not in the `:root` token block, since
D3 adds no new tokens):

```css
.skel-line, .skel-block {
  display: block;
  background: var(--panel-well);
  border-radius: var(--radius-sm);
  animation: skel-pulse 1.5s ease-in-out infinite;
}

.skel-card {
  background: var(--panel-nested);
  border: var(--border);
  border-radius: var(--radius-md);
  padding: var(--space-4);
}

@keyframes skel-pulse {
  0%, 100% { background-color: var(--panel-well); }
  50%      { background-color: var(--panel-hover); }
}

@media (prefers-reduced-motion: reduce) {
  .skel-line, .skel-block {
    animation: none;
    background: var(--panel-well);
  }
}
```

`.skel-line` height and margin are set per-context (table cell line vs. card
body line) via a modifier class rather than a fixed default, since row heights
differ across the Items table, Work Orders cards, and Hub tiles.

---

## 5. Rollout scope

Converted in one pass, since `IMP-036` confirms app-wide scope:

- `items.js` — search results table (`itemsTbody`)
- `workOrders.js` — list + card-loading paths
- `history.js` — history table
- `massStage.js` — stage body loading state
- `tools.js` — custody table
- `transactions.js` — item search results, work-order gate cards
- `hubClock.js`, `hubAdmin.js`, `hubSupervisor.js`, `hubTechnician.js`,
  `hubTimesheets.js`, `hubPriorities.js`, `hubGraphs.js` — Hub tab content

**Out of scope:** views using `setMessage(el, "Loading…", "")` on a dedicated
status/message line (e.g. `adminReview.js`, parts of `tools.js` and
`transactions.js`). Those are transient status text next to already-visible
content, not a content-area placeholder standing in for not-yet-rendered
structure — converting them to skeleton blocks would be misapplying the
pattern to something it wasn't designed for.

---

## 6. Non-goals

- No change to actual fetch/query latency (`PRO-012`, `SCL-*` own that).
- No new design tokens (D3).
- No automated test coverage added (D6, `PRO-008`).
- No skeleton state for anything that isn't a DB-backed fetch (e.g. client-side
  filter/sort of already-loaded data doesn't get a skeleton — the data is
  already in memory, so there is nothing to mask).

---

## 7. Known tradeoffs

Per `docs/open-work.md`, worth checking against `N4` at implementation time:
static assets are served with `Cache-Control: no-cache` and re-read from disk
on every request, so a heavier `skeleton.js` module and larger `styles.css`
add slightly to that per-request cost. Small at current scale — same tradeoff
`N4` already tracks, not a blocker here.
