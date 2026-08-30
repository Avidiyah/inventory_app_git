# User Hub Graphs: per-community drill-down

Date: 2026-08-30 (expanded the same day after spec review; review-settled
points are marked *review*)
Status: approved design, not yet implemented

## Problem

The Graphs tab (`GET /hub/graphs`, `static/views/hubGraphs.js`) shows four
flat, independent cross-sections of every live work order in the company: two
priority donuts, one donut per community, and one donut per service type. Every
card answers a single-dimension question, so "which service types are backing up
in Commons?" cannot be asked at all — the community and service-type grids are
computed over disjoint groupings of the same rows and never intersect.

## Goal

Make community the primary axis, and let a viewer drill from a community into
its service types or its priority levels, then out to the matching Work Orders
list.

## Non-goals

- No change to who can see the tab. It stays TechFM OA+ and company-wide;
  `graphs_hub` keeps ignoring `user`.
- No new list-filter capability. The Work Orders list API already accepts
  `community`, `service_type`, `priority`, and `status` together.
- No change to the weekly age/close-out duration chart.
- No charting library. The hand-rolled SVG donut stays.

## Structure

```
Graphs tab
├─ header (range select, generated-at)
├─ community sub-tabs: Scholars (12) | Centennial (8) | Commons (23) | Young Hall (4) | Academics (17)
│   └─ for the active community:
│       ├─ big status donut for the whole community
│       └─ sub-sub-tabs: Service Type | Priority
│           └─ a grid of status donuts, one per distinct value
└─ Work-order age and close-out time   (company-wide, below the tabs)
```

Every donut in the tree — the community's big one and every card in either
grid — is a status distribution over the same seven statuses. Only the row set
narrows.

## §1 Payload

`GET /hub/graphs` keeps its URL, its `?weeks=` parameter, its `statuses` list,
and its `duration` block. Three top-level fields are removed —
`priority_high`, `priority_medium`, and the flat `service_types` list — and
`communities` changes element type.

`services/hub.py`:

```python
@dataclass(frozen=True)
class GraphCommunity:
    key: str                              # "commons"
    label: str                            # "Commons"
    total: int
    counts: dict[str, int]                # status -> count, the big donut
    service_types: list[GraphDistribution]
    priorities: list[GraphDistribution]


@dataclass(frozen=True)
class HubGraphsPayload:
    generated_at: datetime
    weeks: int
    statuses: list[GraphStatus]
    communities: list[GraphCommunity]
    duration: GraphDuration
```

`GraphDistribution` and `GraphStatus` are unchanged and reused verbatim for
both inner lists. `schemas/hub.py` gains `HubGraphCommunity` mirroring the
dataclass; `HubGraphsResponse` drops the three fields and re-types
`communities`. The SPA is the only consumer, so the contract change breaks
nothing outside this repo.

### Aggregation

The existing `live_rows` query is unchanged — it already selects exactly the
five columns needed (`status`, `community`, `location`, `service_type`,
`priority`) over non-archived rows. Only the accumulation loop changes. For
each row, for each key in `wo.community_memberships(community, location)`:

1. `community_counts[key][status] += 1`
2. `service_key, service_label = wo.normalize_service_type(service_type)`;
   increment `service_counts[key][service_key][status]`, keeping the display
   label per the tie-break below.
3. If `priority` is non-blank, `priority_key = priority.strip().casefold()`
   with the raw stripped text as label, same tie-break; increment
   `priority_counts[key][priority_key][status]`.

All five communities in `wo.ALL_COMMUNITY_FILTERS` are always emitted, in that
fixed order, even at zero total. Within a community, `service_types` and
`priorities` are each sorted by `(-total, label.casefold())` — the sort the
flat service-type list already uses.

### Label tie-break: the smallest raw spelling by code point

When rows differ only by case or padding (`High` / `high`, `HVAC ` /
`hvac`), one card is produced and its label must be a value the Work Orders
dropdown can select, because §3's click-through sets
`priorityFilter.value = label` and `serviceTypeFilter.value = label` and a
`<select>` silently ignores a value that matches no `<option>`.

Those dropdowns are populated by `services.work_orders._distinct_filter_values`,
which keeps the smallest raw spelling **by code point** (`High` beats
`high`; uppercase sorts first). Today's `graphs_hub` keeps whichever
spelling sorts lowest **after casefolding** — a comparison that is a tie for
exactly these variants, so the winner is whatever row the database returned
first, which can differ from the dropdown's winner between two requests.
That is a latent mismatch in the shipped flat grid; this design fixes it by
adopting the dropdown's rule for both inner lists: `if current is None or
label < current: keep label` on the raw stripped text. A test pins that a
card label is always exactly one of the values `get_work_order_filter_options`
returns for the same rows (the OA+ viewer's filter options are unscoped, so
the two see the same set).

### Priority is raw vendor text, not a bucket

The priority grid is built from the raw `WorkOrder.priority` string, matching
the Work Orders page's exact-text "Priority" dropdown — not `priority_bucket()`
and not the coarser "Priority level" dropdown. In production this yields High,
Medium, and Normal. Blank/NULL priority ("Not imported") gets **no** card and
is silently skipped, so a community's priority cards do **not** sum to its
total. This is deliberate and differs from the service-type grid, which keeps
its `Unspecified` bucket.

Grouping is casefolded for the same reason service type is — scraped vendor
text — and `_apply_priority_filter` already compares case- and
whitespace-insensitively, so a card's raw label round-trips through the filter
correctly.

The "Priority level" (bucket) dropdown on the Work Orders page and
`normalize_priority_bucket_filter` stay: they are a list feature, not a
graphs one. Three docstrings in `domain/work_orders.py` (on
`normalize_priority_bucket_filter`, the `PRIORITY_*` constants, and
`PRIORITY_BUCKET_KEYWORDS`) and the test
`test_priority_bucket_filter_matches_the_graphs_tab_grouping` name the
Graphs-tab priority pies as the reason the bucket exists; those comments
and that test name are reworded to describe the dropdown alone. No
behaviour changes in the domain module.

### Multi-community counting

`community_memberships` may return several keys for one row, and Academics is
the fallback when no named term matches. A work order naming two communities is
counted in both communities' totals, their service-type cards, and their
priority cards. Community totals therefore do not sum to a company total. The
existing on-page caveat text moves to sit under the community sub-tab bar.

## §2 Frontend structure

`hubGraphs.js` grows a small local tab helper rather than reusing
`views/subnav.js`. `subnav.js` is page-level — it binds one `.sub-nav` and its
`.feature-panel` siblings per `.page` element — and the Graphs tab is already a
panel inside the Hub's own tab strip, so it cannot host two further nesting
levels without being generalized. Generalizing it would touch Items, History,
Scan, and Tools for no benefit here.

The whole Graphs panel is rendered by `container.innerHTML` in `mountHubGraphs`
(there is no static markup for it in `pages/user-hub.html`), so the nested tabs
are generated markup. Switching tabs re-renders from the payload already in
memory — no refetch.

### Tab state (*review*)

Two values live in `userHub.js` alongside `graphWeeks` and are passed into
`mountHubGraphs`: `graphCommunity` (a community key or `null`) and
`graphInner` (`"service_type"` | `"priority"`, default `"service_type"`).
The removed `showAllServiceTypes` state and its toggle go away with the flat
grid.

- **First open lands on the largest community, Service Type inner tab.**
  When `graphCommunity` is `null` at render, it is set to the key with the
  highest `total`, ties broken by `ALL_COMMUNITY_FILTERS` order; on an empty
  database that is Scholars. Service Type is the inner default because it
  answers the motivating question ("which service types are backing up").
- **Once set, it stays.** A range change refetches the payload but does not
  clear `graphCommunity`, so the viewer keeps their place even if a
  different community is now the largest. Only a click changes it.
- **Reset with the rest of the admin state.** `loadUserHub` already resets
  `graphWeeks = 12` when the user changes or loses admin rank; both new
  values reset in the same branch (`null` / `"service_type"`).
- **Nothing persists across reloads.** No `localStorage`; a fresh page load
  re-derives the largest community.

### Tab labels (*review*)

Community sub-tabs carry their totals: `Commons (23)`. The inner Service
Type / Priority tabs are plain — every card beneath them already shows its
own total, and a Priority count would have to explain why it is lower than
the community's (blank priorities have no card).

Both tab strips use `role="tablist"` / `role="tab"` / `aria-selected`,
matching `pages/user-hub.html`'s existing hub tab strip. Tabs are real
`<button>`s, so Tab and Enter/Space work. No arrow-key roving focus: the
existing hub strip has none, and the two must behave alike.

### Every service type gets a card

Inside a community's Service Type grid, every distinct service type present is
rendered, sorted by total descending. There is no top-N cap and no "show all"
toggle.

## §3 Click-through

Cards become drillable at slice level, so the card can no longer be a
`<button>`: HTML forbids nested buttons, and the browser hoists an inner button
out into a sibling, silently breaking the layout. The structure becomes

```
<div class="hub-graph-card">
  <h3>…</h3>
  <svg class="hub-donut">
    <path class="hub-graph-slice hub-graph-slice-on_hold" data-status="on_hold" …/>
  </svg>
  <ul class="hub-graph-legend">
    <li><button type="button" data-status="on_hold">…</button></li>
  </ul>
  <button type="button" class="hub-graph-card-all" data-status="">View all N</button>
</div>
```

The community's big donut uses the same structure and the same "View all N"
button; only its `data-*` set differs (community alone).

The SVG `<path>` is a pointer-only target — it carries the `data-*` set and a
`cursor: pointer` rule but no `role` and no tab stop. Keyboard access comes
from the real `<button>` legend row for the same status, which is why every
slice must have one.

The dimension `data-*` live on the card, the status on the target. The one
delegated listener already bound on the container reads both — it resolves the
clicked target for `data-status`, then walks up to `.hub-graph-card` for the
rest:

- `data-community` — on the card, always present, the active community key.
- `data-service-type` — on the card, raw label, Service Type grid only.
- `data-priority` — on the card, raw label, Priority grid only.
- `data-status` — on the target: the status key for a slice or legend row,
  empty string for the card's "View all" button.

The listener's existing bind guard (`container.dataset.distributionClickBound`)
stays — `mountHubGraphs` re-runs against the same container on every tab switch
and range change, and `innerHTML` replaces children but not listeners bound to
the container itself. Tab-strip clicks are handled by the same delegated
listener, keyed on `data-graph-tab` / `data-graph-inner`, so there is still
exactly one listener on the container.

Both the SVG arc and its legend row are click targets for the same status, so
the interaction is reachable by keyboard and by pointer without relying on a
40px-radius arc as the only hit area.

`workOrders.js::openWorkOrdersFilteredByDistribution` is extended from
`{community, serviceType, priorityBucket}` to
`{community, serviceType, priority, status}`. `priorityBucket` is dropped —
nothing calls it once the flat priority donuts are gone, and the raw `priority`
dropdown is what the new cards map to. It keeps calling `resetFilterControls()`
first, so a drill-through always lands on exactly that slice's list and nothing
carried over from a previous visit. `status` sets `statusFilter`, the same
control `openWorkOrdersFilteredByStatus` sets.

Filter combinations produced:

| Clicked | Filters applied |
|---|---|
| Community donut slice | community + status |
| Community donut "View all" | community |
| Service Type card slice | community + service_type + status |
| Service Type card "View all" | community + service_type |
| Priority card slice | community + priority + status |
| Priority card "View all" | community + priority |

## §4 Empty states

- A community with zero live work orders: the big donut shows the existing
  `hub-graph-empty` "No circulating work orders" block, and both inner grids
  show a matching empty message. The sub-tab stays selectable and reads
  `Young Hall (0)` — an empty community is a real answer, not a missing one.
- A community with work orders but no non-blank priority on any of them: the
  Priority grid shows an empty message naming the reason ("No imported
  priorities in this community").

## §5 CSS

Mostly additive. `.hub-graph-card` stays; `.hub-graph-card-clickable` (which
exists to neutralize button styling) is dropped, replaced by hover/focus styles
on the new inner targets. Two new tab-strip rules reuse the existing `.hub-tab`
visual language; the community strip wraps on narrow screens rather than
scrolling. Status swatch and slice colors are untouched. Per the repo's CSP,
no inline `style=` attributes — all new styling goes through classes.

## §6 Copy

`static/tips.js` `hub.graphs` currently reads "…clicking a slice opens the
matching work orders." It gains one sentence naming the drill: pick a
community, then split it by service type or priority. `docs/open-work.md`'s
P4 line ("live status distributions by community and service type") and
`docs/current-state.md` are updated to describe the nested shape.

## §7 Testing

Backend, in `tests/test_hub_service.py` — the two existing graphs tests
(`test_graphs_hub_counts_live_statuses_by_community_and_service_type`,
`test_graphs_hub_adds_high_and_medium_priority_status_distributions`) are
rewritten against the nested shape; the duration test is untouched:

- A work order in Commons with service type "HVAC" and priority "High" appears
  in the Commons community's total, its HVAC service-type card, and its High
  priority card, all under the same status key.
- A work order whose text matches two communities is counted in both, in all
  three places.
- Blank priority produces no priority card but still counts in the community
  total and in its service-type card.
- Priority labels differing only by case group into one card whose label is
  the smallest spelling by code point, and the same rule holds for service
  types.
- Every service-type and priority label equals one of the values
  `get_work_order_filter_options` returns for an OA viewer over the same rows
  (the click-through guarantee).
- All five communities are present at zero total on an empty database.
- Within a community, both inner lists are sorted by total descending, then
  label.

Router, in `tests/test_hub_router.py`:
`test_graphs_route_serializes_the_two_priority_distributions` is replaced by
one asserting `HubGraphsResponse` serializes the nested community shape and no
longer carries the three removed fields; the week-count validation tests
still pass. Per the repo's FastAPI/Pydantic pinning, the over-HTTP test uses a
real `TestClient` rather than calling the handler directly.

`tests/test_work_orders_service.py::test_priority_bucket_filter_matches_the_graphs_tab_grouping`
keeps its assertions (the bucket filter is unchanged) under a name and
comment that no longer cite the graphs.

Frontend: manual validation on the running app — the JS has no test harness.
Check: first open lands on the largest community; a range change keeps the
chosen community; every row of the §3 table lands on the right filters,
including a case-variant priority.

## Files touched

| File | Change |
|---|---|
| `backend/app/services/hub.py` | `GraphCommunity` dataclass; nested accumulation in `graphs_hub`; code-point label tie-break; drop the two priority distributions and the flat service list |
| `backend/app/schemas/hub.py` | `HubGraphCommunity`; re-type `HubGraphsResponse.communities`; drop three fields |
| `backend/app/domain/work_orders.py` | Docstrings only: three comments that cite the Graphs-tab priority pies |
| `backend/static/views/hubGraphs.js` | Nested tab helper; card is no longer a button; slice + legend click targets; drop the service-type toggle |
| `backend/static/views/userHub.js` | `graphCommunity` / `graphInner` state, defaults, reset; new `onDistributionClick` payload; drop `showAllServiceTypes` |
| `backend/static/views/workOrders.js` | `openWorkOrdersFilteredByDistribution` takes `priority` and `status`, drops `priorityBucket` |
| `backend/static/styles.css` | Nested tab strips; card/slice hover-focus without the button reset |
| `backend/static/tips.js` | `hub.graphs` copy |
| `backend/tests/test_hub_service.py`, `test_hub_router.py`, `test_work_orders_service.py` | Rewrite the graphs assertions against the nested shape; rename the bucket-filter test |
| `docs/endpoint-map.md`, `docs/current-state.md`, `docs/open-work.md` | Record the changed `/hub/graphs` contract and the nested Graphs shape |

`community_memberships`, `normalize_service_type`, and the filter normalizers
are all reused as-is; the domain module's behaviour is untouched.
