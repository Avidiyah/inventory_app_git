# Work Orders live rendering: design

Date: 2026-11-14. Status: awaiting approval. Scope: the Work Orders page only.

## Intent

The owner wants the app to feel live everywhere, starting with Work Orders, the
most-used page. Today a live update redraws by wiping and rebuilding, so the
list jumps, open previews close and folded groups reopen. Each live screen
avoids the worst of this with its own hand-written guard code.

This design gives Work Orders one shared way to redraw: build the new HTML as
now, then change only the parts of the page that differ. It must stay small.
The owner has ruled out an over-engineered live-view system.

## Goals

- A live update to the list changes only the cards that changed.
- Open previews, folded groups, focus and scroll position survive an update.
- A card that changed is briefly highlighted so the change is noticed.
- New, moved and removed cards are inserted, moved and removed in place.
- The existing HTML builders stay. No screen is rewritten.

## Non-goals

- Any page other than Work Orders (the User Hub's embedded list is touched only
  because it shares `buildCard`).
- New live event types or wider event coverage.
- Two users saving the same field. That is a separate save-time version check
  with its own design.
- Edit locks, presence ("Maria is editing"), or showing who made a change.
- Sliding or other motion beyond the one highlight.
- A templating library, a framework, a build step, or TypeScript.

## Anti-goals

- A general rendering layer other pages are expected to adopt. One helper, one
  caller family. Other pages adopt it later only by their own design.
- Any update that discards typed input or closes something the user opened.
- A second code path for "draw" versus "update".

## Constraints

| Constraint | Source |
|---|---|
| Scripts must be same-origin; no `eval`, no inline script or style | `CONTENT_SECURITY_POLICY` in `backend/app/main.py` (`default-src 'self'`) |
| No build step; ES modules served from `backend/static` | current setup |
| Vendored libraries live in `backend/static/vendor` with their licence | zxing precedent |
| REST stays the source of truth; socket frames are invalidations | `backend/static/realtime.js` header |
| `workOrder*.js` may pass 500 lines; past 1,000 must delegate | repo rule |
| Readable on a phone with no legend; no horizontal scroll | owner design rules |
| `prefers-reduced-motion` must disable the highlight | existing pattern in `styles.css` |

## Approaches considered

| Approach | Trade-off | Outcome |
|---|---|---|
| Hand-wired listener per field | Most code; every new field needs wiring; lists need separate handling | Rejected |
| Compare-and-patch helper (idiomorph) | Keeps builders; needs ids on rows and one shared tap handler | **Picked** |
| Templating library (lit-html) | Cleanest long term; rewrites the 680-line card builder and its tests | Deferred; revisit only if string builders still hurt after this ships |
| Preact + htm | Brings a component and state model the app does not need | Rejected |
| Alpine.js | Normal build needs `unsafe-eval`; safe build is heavily restricted | Rejected |
| htmx / server-sent HTML | Moves drawing into Python; rewrite of the JSON front end | Rejected |
| React or Svelte with a build step | Months, features stalled | Rejected |

The owner picked the helper after a cited research pass and a throwaway trial
(2026-11-14).

## What the trial showed

Run in jsdom against a stand-in list with the same structure (status groups
holding cards), not the real modules or a real browser.

| Finding | Consequence for this design |
|---|---|
| Without an `id`, a card moving between groups is rebuilt, not moved | Cards and groups get ids |
| By default the helper removes `open` from a card the user opened | `open` on cards and groups is never changed by an update |
| By default the server value overwrites the focused field | `ignoreActiveValue: true` |
| A newly inserted card is copied without its tap handler, so it is dead | One delegated handler per list replaces the per-card handler |
| Library has no `eval` or generated code | Expected to pass the security policy; confirm in a browser |

## Design

### Stage 1: the list (this approval)

**1. Vendor the library.** `backend/static/vendor/idiomorph-0.7.4.esm.js`
(about 50 KB unminified) plus its licence file. Imported as an ES module.
Already excluded from coverage by `vitest.config`.

**2. One helper module**, `backend/static/morph.js`, exporting one function:

```js
morphInto(container, newNodes, { flashSelector, flashKey } = {})
```

It does three things and nothing else:

- Calls `Idiomorph.morph(container, newNodes, { morphStyle: "innerHTML", ignoreActiveValue: true, callbacks })`.
- `callbacks.beforeAttributeUpdated` returns `false` for the `open` attribute on
  any `<details>`, so open and folded state always belongs to the user. A
  `<details>` that is new takes whatever the builder gave it.
- If `flashSelector` is given: before the update it records `flashKey(el)` for
  each matching element by `id`; after, any element that is new or whose key
  changed gets the class `just-changed`, removed on `animationend`.

**3. Ids.** `buildCard` sets `id = <prefix>-card-<id>`; `appendGroupedCards`
sets `id = <prefix>-group-<status>` on each group. The prefix differs per list
(`wo` for the page, `hubwo` for the User Hub mount) because both lists can be
in the document at once.

**4. One tap handler per list.** The per-card `body.addEventListener("click")`
in `buildCard` is removed. `renderCards` and `mountWorkOrderList` each install
one delegated listener on their container, once. It finds `[data-peek-open]`,
walks to the enclosing `details.wo-card`, reads `dataset.id` and
`dataset.number`, then calls `onOpen` or `openWorkOrderPage`. The card page's
own card (`solo`) keeps its two direct listeners; it is not part of a list
update.

**5. `renderCards` uses the helper.** It builds the grouped tree into a
detached container exactly as today, then calls
`morphInto(listEl, tree.childNodes, { flashSelector: "details.wo-card", flashKey: summary text })`.
The empty-list hint goes through the same call. There is one path for first
draw, filter change and live update.

**6. Single-card refresh keeps working.** `refreshCardSummary` already touches
one card. It stays, and adds `just-changed` to that card when its summary text
changed. When a card changes group it still calls `runOrDeferListRefresh`,
which now moves the card instead of rebuilding the list.

**7. Highlight.** One CSS rule: `.just-changed` runs a one-second background
fade using the existing accent token, with the `prefers-reduced-motion` guard
turning it off. Class only; no inline style.

**What the user sees**

```
before:  ▾ Assigned · 2          after:  ▾ Assigned · 3
           WO-1042  Roof patch             WO-1051  Gutter      (glows 1 s)
           WO-1047  Drywall                WO-1042  Roof patch
                                           WO-1047  Drywall
```

Nothing else on the page moves; a preview the user had open stays open.

### Stage 2: the card page body (separate approval)

The card page is where a technician reads an order while a supervisor changes
it. Today an update repaints the whole body, or is deferred entirely while any
editor section is open.

Stage 2 would route `paintDetail` through `morphInto` and skip only the open
editor sections, so the rest of a held card (status, materials list, labor
total) stays current while the user types. It is not approved here because
three things are unproven:

- whether handlers inside the body are attached per element (same hazard as
  the list);
- how tab selection and the signature canvas behave under an update;
- whether updating around an open editor can ever show a state the editor's
  save would contradict.

Stage 2 starts with its own trial against the real `renderBody` output.

## Testing

Frontend tests in `tests/frontend`, loading view modules through `importView`:

| Test | Asserts |
|---|---|
| Preview stays open across a list update | same element, `open` true |
| Folded group stays folded; new group takes its default | `open` unchanged / default |
| Card changing status moves group | same element object, new parent |
| New card responds to its Open button | handler fires with the new id |
| Removed card is gone; empty list shows the hint | DOM content |
| Changed and new cards get `just-changed`; unchanged do not | class presence |
| Hub mount and page list in one document have distinct ids | no duplicate ids |
| Static import guard covers the vendored file | `staticImports.test.js` passes |

The owner's in-app check on a phone covers what jsdom cannot: the security
policy in a real browser, the highlight, and scroll position on iOS Safari
when a card is inserted above the reading position.

## Risks

| Risk | Handling |
|---|---|
| Library blocked by the security policy in a browser | Check first, before any other build step; if blocked, stop and report |
| iOS Safari jumps when a card is inserted above the viewport | Verify on a phone; if it jumps, restore the anchor card's position after the update |
| Another module relies on the per-card handler or on cards being rebuilt | Planner audits `workOrderRouting.js`, `workOrderRetry.js`, `hubTechnician.js` |
| Coverage gate drops | New helper is fully tested; vendor file is excluded |

## Left to the builder

- Exact name and colour of the highlight keyframe, reusing an existing one if
  it fits.
- Whether the delegated handler lives in `workOrderList.js` or a helper, by
  line count.
- The `docs/current-state.md` row for the new helper.

## Calls made by the author, not the owner

- Highlight is a one-second background fade, with no text or icon.
- Stage 2 is split out and needs its own approval.
- The embedded User Hub list gets ids and the shared tap handler but no other
  change.
- The save-time conflict check is a separate design, to follow this one.
