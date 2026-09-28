# Work Orders — Visual Clarity Pass

**Status:** Draft for review · **Date:** 2026-09-27 · **Scope:** Work Orders page
(list + expanded card + solo card page). Front-end only; no API or schema change.

## Goal

Make the Work Orders page quicker to read and act on for technicians and
supervisors without changing its layout, workflow, or palette identity. An
employee should be able to answer three questions at a glance:

1. **What state is this job in?** (status)
2. **Does it need attention now?** (priority / overdue)
3. **What do I press next?** (the one primary action)

Not an overhaul: the card structure, section order, filters, and the seven
`--wo-status-*` lifecycle hues stay.

## Problems found in the current page

| # | Problem | Where |
|---|---|---|
| P1 | Status and priority share one hue space, so color alone is ambiguous: On-Hold border `#C2410C` is the exact Urgent pill fill; Assigned red ≈ Emergency red ≈ brand red; Completed blue ≈ Normal-priority blue; Review green ≈ Low-priority green. | `styles.css` `.wo-card-status-*`, `.wo-priority-*` |
| P2 | Each status has two different shades: card outline uses `--wo-status-*`, the pill uses a darker hard-coded fill (`#7F1D1D`, `#854D0E`, …). Dark pill on dark panel is the weakest element on the card. | `.wo-status-*` |
| P3 | Status and priority are color-plus-text only; the pills are the same shape and size, so they read as one undifferentiated row of chips. | `statusBadge()`, `priorityBadge()` |
| P4 | Several primary (red) buttons compete in one controls row — e.g. a Supervisor on an In-Progress job sees Stop Charging, Mark Completed, and Open Netfacilities at equal weight next to Archive. | `renderBody()` status-action ladder |
| P5 | Whether *I* am on the clock is only implied by which button is showing. | expanded card controls |
| P6 | Ten filter inputs plus sort, but no summary of what is currently applied; a filtered-empty list and a genuinely empty list look alike. | `#work-orders-controls-section` |
| P7 | Nothing marks a job whose scheduled date has passed while it is still open. | card summary |

## Design principles applied

- **Never color alone** — every color-coded state also carries a glyph and a text label.
- **One color per meaning** — a hue on this page means one thing; status owns the lifecycle hues, "attention" owns red/orange/amber.
- **Neutral means normal** — routine priority renders quiet; only states that need someone to act get saturated color or motion.
- **One primary action per state** — the lifecycle's next step is the only filled red button; the rest are secondary or tertiary.
- **Contrast floors** — text ≥ 4.5:1 against its own fill; non-text state indicators (outlines, glyphs) ≥ 3:1 against the panel.
- **Touch** — every tappable control stays at or above `--btn-h-sm` (44px); primary actions keep `--btn-h` (52px).

## Changes

### C1 — Status pill: one hue, one glyph (fixes P2, P3)

- Pill fill becomes the same `--wo-status-*` token as the card outline; delete the seven hard-coded darker fills.
- Pill text color per status, chosen for ≥ 4.5:1 on the fill: dark text (`--color-ink`) on Created and In-Progress; white on the other five.
- Each pill gets a leading glyph, `aria-hidden`, drawn as a small inline SVG from a single presenter map (no inline `style=` — CSP):

| Status | Glyph | Text on pill |
|---|---|---|
| Created | hollow circle | dark |
| Assigned | person | white |
| In-Progress | play triangle | dark |
| On-Hold | pause bars | white |
| Ready to Complete | hourglass | white |
| Completed | check | white |
| Review | magnifier / clipboard-check | white |

- Shape stays pill (`--radius-pill`). The text label is unchanged, so screen readers and the grayscale test still read the state.

### C2 — Priority tag: quiet unless it needs attention (fixes P1, P3)

- Priority keeps its square-cornered tag shape (`--radius-sm`), visibly distinct from the round status pill.
- **Normal, Low, None, Unknown** become an outline tag: `--panel-border` outline, `--text-panel-mute` text, no fill. Their blue/green fills are removed — that is what collided with Completed/Review.
- **Emergency, Urgent, High** keep a filled tag and gain a leading warning-triangle glyph. Their hues stay (red / orange / amber) and are the only saturated reds and oranges on the card besides the Assigned / On-Hold outline, which is now disambiguated by glyph and shape.
- Urgent's pulse and fire stay exactly as they are, including the reduced-motion fallback and the settled-status rule in `urgentFireActive()`.

### C3 — Overdue tag (fixes P7)

- A card whose `schedule_date` is before today (browser-local date) and whose status is not Completed or Review shows an **Overdue** tag after the priority tag: outline tag, `--color-brand-light` text and outline, clock glyph. Static, no motion.
- Pure presenter predicate beside `urgentFireActive()` (same settled-status set), so list, repaint, and solo paths agree.
- A blank or unparseable `schedule_date` never shows the tag.

### C4 — Action hierarchy in the expanded card (fixes P4)

The status-action ladder is re-expressed as three tiers. Buttons, labels, `data-action` names, and who sees what do not change — only their class and order.

| Tier | Treatment | Contents |
|---|---|---|
| Primary | filled `--color-brand`, `--btn-h` | exactly one: the lifecycle's next step (table below) |
| Secondary | `.secondary-btn` | the other workflow buttons for that state |
| Tools | new trailing group, separated by a `--panel-rule` divider, compact height | Open Netfacilities (secondary style), Archive (keeps `.btn-danger` treatment) |

Primary by state:

| State / viewer | Primary | Demoted to secondary |
|---|---|---|
| Created / Assigned | Begin Charging | — |
| In-Progress, not charging | Begin Charging | Place On-Hold, Mark Completed |
| In-Progress, charging, Technician | Notify Supervisor | Stop Charging, Place On-Hold |
| In-Progress, charging, Supervisor+ | Mark Completed | Stop Charging, Place On-Hold |
| On-Hold | Begin Charging | Resume In-Progress, Mark Completed |
| Ready to Complete, Supervisor+ | Approve — Mark Completed | Send Back |
| Completed | Send to Review | Reopen |
| Review, Supervisor+ | — (label stays) | Reopen |

The disabled TechFM OA "Send to Review" keeps its current behavior and title text. The entry-mode selector stays first in the row.

### C5 — "Charging now" strip (fixes P5)

- When the expanded detail has `active_labor_session`, a strip sits directly above the controls row: static dot glyph + "Charging since 9:14 AM" (formatted from `started_at`, browser-local), In-Progress yellow left rule, `--text-panel` text.
- Absent when there is no running session. Repaints with the existing detail repaint path — no new timer.

### C6 — Applied-filter chips + result count (fixes P6)

- A chip row renders directly under the filter controls, one chip per non-default filter: `Status: On-Hold ×`, `Community: Oak Ridge ×`, `WO #: 1234 ×`, `Location: "bldg 4" ×`, and so on. Sort is not a chip.
- Tapping a chip's × resets that one control and reloads through the existing filter-change path. A **Clear all** chip appears when two or more are active and calls the existing Clear filters handler.
- Chips are real `<button>`s at `--btn-h-sm` height with an `aria-label` of "Remove filter Status: On-Hold".
- A count line replaces the silent state: "Showing 24 work orders" / "No work orders match these filters — clear a filter to widen the list" when chips are present and the list is empty. It uses the count already in hand from the loaded list; when the list is capped by `RECENT_LIMIT`, it reads "Showing the N most recent" (N = `RECENT_LIMIT`).
- The status filter's chip swatch carries the same glyph and hue as C1, so the chip doubles as a legend for that filter.

## Module placement and the line-count rule

Work-order modules may exceed the 500-line soft cap, but any work-order module past **1,000 lines** must move function bodies into helper modules and call them instead. Current sizes: `workOrderList.js` 769, `workOrderCardHtml.js` 661, `workOrderActions.js` 546. This pass adds new code in new helpers so no existing file grows much:

| Module | New / changed | Owns |
|---|---|---|
| `workOrderPresenters.js` | changed | `statusBadge()` gains glyph + text class; `priorityBadge()` outline vs filled; new `isOverdue(card)`; `overdueTag(card)` |
| `workOrderGlyphs.js` | **new** leaf | the status/priority/overdue/clock inline-SVG map; imports nothing from the group |
| `workOrderStatusActions.js` | **new** | the status-action ladder moved out of `renderBody()` as `statusActionsHtml(detail)` returning `{ primary, secondary, tools }` strings; plus `chargingStripHtml(detail)` |
| `workOrderCardHtml.js` | changed | `renderBody()` calls the two helpers above; net shrink |
| `workOrderFilterChips.js` | **new** | `renderFilterChips()`, `renderResultCount()`, chip click handling; reads filter state via `workOrderFilters.js` |
| `workOrderList.js` | changed | calls chip/count render after each load; no new logic inline |
| `pages/work-orders.html` | changed | empty `#work-orders-filter-chips` container + count line |
| `styles.css` | changed | status pill fills → tokens; priority outline variants; `.wo-tag-overdue`; `.wo-charging-strip`; `.wo-controls-tools`; `.wo-filter-chip` |

Leaf order becomes: `workOrderGlyphs` → `workOrderPresenters` → … → `workOrderStatusActions` → `workOrderCardHtml`; `workOrderFilterChips` sits beside `workOrderFilters`. No sibling imports the barrel.

## Docs to update in the same change

- `docs/design-system.md` — the work-order status pill/priority tag rule (one hue per status, glyph required, routine priority neutral) and the three-tier action rule.
- `docs/current-state.md` — module table rows for the three new modules and the 1,000-line rule for work-order modules.

## Out of scope

- Changing any `--wo-status-*` token value (they also drive the Hub Graphs donuts).
- Reordering card sections, the filter grid layout, or collapsing filters on mobile.
- Status counts in the chip row (would need an API change).
- The Scan/Stock and Admin Review cards that reuse `.wo-card-status-*` outlines — they pick up C1's pill change only where they render `statusBadge()`.

## Testing

- **Unit (presenters):** `statusBadge()` emits glyph + label for all seven statuses; `priorityBadge()` outline for normal/low/none/unknown and filled + glyph for emergency/urgent/high; `isOverdue()` true/false for past, today, future, blank, settled statuses.
- **Unit (status actions):** for each row of the primary-by-state table, exactly one primary button and the listed secondaries; tools group only for Admin+; OA disabled button unchanged.
- **View (characterization suite in `tests/frontend/views/workOrders/`):** existing role/action tests still pass unchanged (same `data-action`s); new cases for chip render, chip ×, Clear all, empty-with-filters message, charging strip present/absent.
- **Contrast check:** a test asserting each status pill's text/fill pair ≥ 4.5:1 from the token values.
- **Manual (user):** phone in daylight — status readable in grayscale screenshot; one red button per expanded card; urgent fire unchanged.
