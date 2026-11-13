# SMR page: instant search, filters and sort

Date: 2026-11-13 · Status: draft, awaiting go-ahead · Budget: ≤ 1,800 words

## 1. Problem

Every search, dropdown, date, Clear filters or sort click on the SMR page
asks the server to rebuild the matching tiles. Building a tile is the
expensive part of the page (the full before / after comparison per order),
so a filter change costs nearly as much as opening the page: about 1.2 s
measured on a production-sized copy, about 2 s on the server.

The browser already holds every tile's content from the page load. A filter
change only needs to know which tiles to show and in what order.

## 2. Idea

Keep the filter rules on the server, where they already live and are shared
with the Work Orders list. Stop rebuilding tiles to answer them.

| | Today | Proposed |
|---|---|---|
| Page entry, return from a card, Regenerate / Undo / Restore | Full payload; `tiles` holds only the orders the current filters match | Full payload; `tiles` holds every SMR order, plus `order`: the matching ids, in display order |
| Search, dropdown, date, Clear filters, sort | `summary=false`: rebuilds every matching tile | `ids_only=true`: returns `matched` and `order` only |
| What the browser does with a filter answer | Replaces the grid | Reorders and hides the tiles it already has |

The id query is the lightweight one the summary path already runs
(`filtered_smr_orders(ids_only=True)`): three columns, no lines, no tile
building. Expect tens of milliseconds.

Considered and dropped: filtering in the browser. The tiles would need
priority, Team Lead, technicians, community, scheduled date and description,
and the community and date rules would then exist in two languages.

## 3. Design

### 3.1 Backend

Files: `services/work_orders_smr.py`, `routers/work_orders_smr.py`,
`schemas/work_orders_smr.py`.

- `SmrTilesResponse` gains `order: list[UUID]`, the ids the request's
  filters match, in schedule-date order.
- Full request (the default): `tiles` is every SMR order. `matched` and
  `order` describe the filtered set. No extra work: the summary path already
  builds every tile and already runs the id query.
- `ids_only=true`: runs the id query alone and returns `matched` and `order`,
  with `tiles` empty and the summary fields null.
- `summary=false` is removed with its only caller (the page). No other
  caller sends it.
- `has_lines` and `block_stale_or_unpasted` stay on the full request, and
  narrow `order` rather than `tiles`. The page does not send them. They are
  rejected with a 422 alongside `ids_only=true`, since answering them needs
  the lines.

### 3.2 Frontend

Files: `views/smr.js`, `api.js` (`apiListSmrTiles`).

- `render` keeps the full payload's tiles in a map by id.
- A full payload draws every tile once, in `order` first, the rest after and
  hidden.
- An `ids_only` answer moves the existing tile elements into the new order
  and hides the ones not listed. No tile HTML is rebuilt.
- The state chips keep working as now: a tile shows when it is in `order`
  and passes the chips. `applyFilter` gains the first half of that test.
- The result count reads `matched` as it does today.
- `loadSmr({ tilesOnly: true })` sends `ids_only` when a full payload is
  held, and a full request when none has arrived yet (today's rule).
- The existing sequence guard (`loadSeq`) already drops a stale answer.

### 3.3 What the user sees

Nothing changes in layout, wording or controls. Filter changes answer at
once instead of after a second or two.

## 4. Trade-off to accept

Today a filter change also refreshes tile contents, because it rebuilds
them. After this, tile contents refresh only on a full load: page entry,
return from a card, Regenerate, Undo, Restore. Someone who keeps the page
open and only filters will not see another person's edits until one of
those. An order imported after the page loaded can appear in `order` with no
tile to show; the page skips it and it arrives with the next full load.

## 5. Edge cases

| Case | Behaviour |
|---|---|
| Filter answer arrives before any full payload | Cannot happen: the page sends a full request until one is held. |
| Filter answer lists an id the page has no tile for | Skipped; `matched` still counts it. A full load fixes the gap. |
| Saved filters on page entry | Full request carries them; `order` reflects them from the first paint. |
| Empty result | Same empty-state copy as today. |
| Full payload size with filters active | Now always every order (about 800 KB before compression), where it was the filtered subset. Unfiltered entry is unchanged. |
| Return from a card | Unchanged: last grid shows at once, full refresh replaces it. |

## 6. Tests

| Change | Test | File |
|---|---|---|
| `ids_only` returns ids in the list's order and builds no tiles | Compare `order` with the full request's; assert no line or block queries ran | `backend/tests/test_smr_tiles.py` |
| Full request returns every tile and the filtered `order` | Filter by number; `tiles` is the whole set, `order` the match | same file |
| `ids_only` with a paper-correction switch is refused | 422 through the real client | same file |
| A filter change reorders and hides without rebuilding | Tile elements keep identity across a filter change; hidden and order match the answer | `tests/frontend/views/smr.test.js` |
| Chips and filters combine | A tile outside `order` stays hidden when its chip matches | same file |

Docs: `docs/endpoint-map.md` row S2 and the `smr.js` line in
`docs/current-state.md`.

## 7. Decisions for the user

| # | Decision | Recommendation |
|---|---|---|
| 1 | Accept the trade-off in section 4 (tile contents refresh on full loads only)? | Yes. Full loads already happen at every point where the user's own edits land. |
| 2 | Remove `summary=false` outright, or keep it accepted for one release? | Remove. The page is its only caller and ships in the same deploy. |

## 8. Size

| Part | Files | Rough size |
|---|---|---|
| Backend | service, router, schema | about 25 lines |
| Frontend | `smr.js`, `api.js` | about 30 lines |
| Tests | two existing files | about 80 lines |

No schema change, no new endpoint, no new dependency.
