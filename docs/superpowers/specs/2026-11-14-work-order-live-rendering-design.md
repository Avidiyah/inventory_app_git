# Work Orders live rendering: design

Date: 2026-11-14. Status: Stage 1 built (b433dff); Stage 2 design picked 2026-11-15, plan awaiting go-ahead. Scope: the Work Orders page only.

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

### Stage 2: the card page body

The card page is where a technician reads an order while a supervisor changes
it. Today an update repaints the whole body, or is deferred entirely while any
editor section is open.

**Picked by the owner 2026-11-15:** a live update patches the whole body and
leaves alone only what the user has touched (option B), not whole open
sections. Plan: `docs/superpowers/plans/2026-11-15-work-order-live-card-body.md`.

**Trial results** (real `renderBody` output, jsdom, 2026-11-15):

| Finding | Consequence |
|---|---|
| Body handlers are all delegated; the signature pad lives outside the body | No handler rework. The charge editor's Cancel is the one direct listener; its row is left alone while it is open |
| Tab bar resets to Details after a patch | Re-sync the tab bar after every patch |
| Typed but unfocused fields are wiped; the message line is blanked | Protection rules below |
| Without ids, removing a line above a typed row left a duplicate row and dropped a new one | Every repeating row and top-level block gets an id |
| With ids, the typed row kept its own line, value and place | Ids are a precondition, not polish |

**Rules for a live patch**

1. *Entry forms are one unit:* the add-material row and each add-labor row are
   left alone whole while touched (focused, a typed or picked value, a picked
   item or request, a line being edited). A form's fields mean something only
   together: a typed hours box must not end up beside a different default
   technician.
2. *Left alone whole while open:* the Edit details form, and a material line
   whose charge editor is open.
3. *Left alone by itself:* any other focused or typed field (a line's quantity
   or hours, the note box, the SMR description). Its row updates around it.
   The entry-mode select saves on change, so only focus protects it.
4. *Never rewritten:* the two message lines.
5. Everything else takes the server's value, including a row the server
   removed. If that discards something typed, the card says so in its message
   line; it is never dropped silently.
6. "I have read the notes" survives a patch only when the notes did not
   change; new notes lock Begin Charging again.
7. Responses apply in order: one live fetch per card at a time; a fetch that a
   newer paint overtook is dropped and refetched; a response for a card no
   longer on screen is ignored.
8. Anything left alone for focus or an open form catches up when focus leaves
   or the form closes.
9. A button never changes its action under a finger: action buttons carry an
   id per action, so a changed button is removed and a new one inserted, never
   relabelled; and the action bar ignores taps for 500 ms after its buttons
   change (it glows once to show why).
10. The tab the user was on, keyboard focus and reading position are restored
    after a patch.
11. A live refresh never signs the user out: an expired session is left for
    the user's next save, which keeps a draft.

12. If someone else changed the very field the user is typing in, the typed
    value stays, the field is outlined, and the message line warns that saving
    will replace their change.

**Checked against current practice (2026-11-15)**

| Rule | Practice it follows | Source |
|---|---|---|
| Ids on everything kept | Preserved elements need a stable id; "give important elements ids so they survive morphs" | [htmx hx-preserve](https://htmx.org/attributes/hx-preserve/), [htmx morphing guide](https://four.htmx.org/docs/morphing-swaps-guide) |
| Focused field wins | LiveView keeps a focused input's value over a server patch; its known gap (stale after blur) is our rule 8 | [Elixir Forum](https://elixirforum.com/t/liveview-input-forms-are-not-controlled-by-the-server-state-when-input-is-in-focus/41342) |
| Typed value kept, server change surfaced | htmx keeps an unfocused value unless the server's value changed | [htmx morphing guide](https://four.htmx.org/docs/morphing-swaps-guide) |
| Refocus after a patch | Turbo's kept inputs hold their value but lose focus; the fix is to refocus | [hotwired/turbo #436](https://github.com/hotwired/turbo/pull/436) |
| Manual reading-position fix, feature-checked | iOS Safari has no scroll anchoring through 26.5 | [caniuse](https://caniuse.com/css-overflow-anchor) |
| Focus lost on move on iOS | `moveBefore` is unsupported on iOS Safari | [caniuse](https://caniuse.com/mdn-api_element_movebefore), [Chrome](https://developer.chrome.com/blog/movebefore-api) |
| Drop stale responses | "add a cleanup function to ignore stale responses" | [react.dev](https://react.dev/learn/you-might-not-need-an-effect) |
| Socket event invalidates, REST refetches | Invalidation "plays really nice together with WebSockets" | [TkDodo](https://tkdodo.eu/blog/using-web-sockets-with-react-query) |
| No relabelled buttons; settle delay | A click goes to the common ancestor of press and release, and never to a removed element; shifts under a finger cause misclicks; Firefox delays sensitive buttons for the same reason | [WPT click target](https://searchfox.org/firefox-main/source/testing/web-platform/tests/pointerevents/pointerevent_click_during_parent_capture.html), [web.dev CLS](https://web.dev/articles/cls), [Mozilla bug 1717426](https://bugzilla.mozilla.org/show_bug.cgi?id=1717426) |
| Message line announces | `role="status"` must exist before the text | [WCAG 4.1.3](https://www.w3.org/WAI/WCAG22/Understanding/status-messages.html) |
| Library version | 0.8.0 warns on duplicate ids and fixes focus restoration | [npm](https://www.npmjs.com/package/idiomorph), [openproject #25142](https://github.com/opf/openproject/pull/25142) |

**Where this design is below the standard.** Lost updates are properly
prevented with a version check on save (`If-Match` and 412): see
[http.dev](https://http.dev/if-match). This app has that for one field only
(`expected_supervisor_id`). Rule 12 warns but does not prevent. The full check
is the next design, not part of Stage 2.

**Identity invariant.** The patcher pairs an element that has an id only with
the same id. So every element these rules can leave alone, and every direct
child of the body, carries a unique id. Without that, a kept element can be
paired with the wrong neighbour (proved in the trial).

**Event coverage.** The server sends a live event for status, details, notes,
charging and signature changes. Adding, editing or removing a material, a
labor entry or an SMR line sends none. Extending those routes is the owner's
call (plan Task 5).

**Two paths, on purpose.** A repaint after the user's own save still rebuilds
the body, because a saved field must come back empty. Only socket-driven
updates patch. This is the one exception to "no second code path".

**Not changed:** two users saving the same field is still last-write-wins
(the separate save-time check). List cards and the User Hub list.

A test fails when a new field appears in the body outside these rules, so a
future field cannot go unprotected silently.

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
