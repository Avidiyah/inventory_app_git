# User Hub Graphs: per-community drill-down

Date: 2026-08-30
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
├─ community sub-tabs: Scholars | Centennial | Commons | Young Hall | Academics
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
`communities`.

### Aggregation

The existing `live_rows` query is unchanged — it already selects exactly the
five columns needed (`status`, `community`, `location`, `service_type`,
`priority`) over non-archived rows. Only the accumulation loop changes. For
each row, for each key in `wo.community_memberships(community, location)`:

1. `community_counts[key][status] += 1`
2. `service_key, service_label = wo.normalize_service_type(service_type)`;
   increment `service_counts[key][service_key][status]`, keeping the
   lowest-casefolded raw label as the display label (same tie-break as today).
3. If `priority` is non-blank, `priority_key = priority.strip().casefold()`
   with the raw stripped text as label; increment
   `priority_counts[key][priority_key][status]`.

All five communities in `wo.ALL_COMMUNITY_FILTERS` are always emitted, in that
fixed order, even at zero total. Within a community, `service_types` and
`priorities` are each sorted by `(-total, label.casefold())` — the sort the
flat service-type list already uses.

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
are generated markup. Tab state — active community key, and active inner tab —
lives in `userHub.js` alongside the existing `graphWeeks`, and is passed into
`mountHubGraphs`, so a range change or a re-render does not reset the viewer's
place. The removed `showAllServiceTypes` state and its toggle button go away
with the flat grid.

Both tab strips use `role="tablist"` / `role="tab"` / `aria-selected`, matching
`pages/user-hub.html`'s existing hub tab strip. Switching tabs re-renders from
the payload already in memory — no refetch.

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
the container itself.

Both the SVG arc and its legend row are click targets for the same status, so
the interaction is reachable by keyboard and by pointer without relying on a
40px-radius arc as the only hit area.

`workOrders.js::openWorkOrdersFilteredByDistribution` is extended from
`{community, serviceType, priorityBucket}` to
`{community, serviceType, priority, status}`. `priorityBucket` is dropped —
nothing calls it once the flat priority donuts are gone, and the raw `priority`
dropdown is what the new cards map to. It keeps calling `resetFilterControls()`
first, so a drill-through always lands on exactly that slice's list and nothing
carried over from a previous visit.

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
  show a matching empty message. The sub-tab stays selectable — an empty
  community is a real answer, not a missing one.
- A community with work orders but no non-blank priority on any of them: the
  Priority grid shows an empty message naming the reason ("No imported
  priorities in this community").

## §5 CSS

Mostly additive. `.hub-graph-card` stays; `.hub-graph-card-clickable` (which
exists to neutralize button styling) is dropped, replaced by hover/focus styles
on the new inner targets. Two new tab-strip rules reuse the existing `.hub-tab`
visual language. Status swatch and slice colors are untouched. Per the repo's
CSP, no inline `style=` attributes — all new styling goes through classes.

## §6 Testing

Backend, in `tests/test_hub_service.py`:

- A work order in Commons with service type "HVAC" and priority "High" appears
  in the Commons community's total, its HVAC service-type card, and its High
  priority card, all under the same status key.
- A work order whose text matches two communities is counted in both, in all
  three places.
- Blank priority produces no priority card but still counts in the community
  total and in its service-type card.
- Priority labels differing only by case group into one card.
- All five communities are present at zero total on an empty database.
- Within a community, both inner lists are sorted by total descending, then
  label.

Router, in `tests/test_hub_router.py`: `HubGraphsResponse` serializes the
nested community shape, and the existing week-count validation tests still
pass. Per the repo's FastAPI/Pydantic pinning, the over-HTTP test uses a real
`TestClient` rather than calling the handler directly.

Frontend: manual validation on the running app — the JS has no test harness.

## Files touched

| File | Change |
|---|---|
| `backend/app/services/hub.py` | `GraphCommunity` dataclass; nested accumulation in `graphs_hub`; drop the two priority distributions and the flat service list |
| `backend/app/schemas/hub.py` | `HubGraphCommunity`; re-type `HubGraphsResponse.communities`; drop three fields |
| `backend/static/views/hubGraphs.js` | Nested tab helper; card is no longer a button; slice + legend click targets; drop the service-type toggle |
| `backend/static/views/userHub.js` | Tab state; new `onDistributionClick` payload; drop `showAllServiceTypes` |
| `backend/static/views/workOrders.js` | `openWorkOrdersFilteredByDistribution` takes `priority` and `status`, drops `priorityBucket` |
| `backend/static/styles.css` | Nested tab strips; card/slice hover-focus without the button reset |
| `backend/tests/test_hub_service.py`, `test_hub_router.py` | Rewrite the graphs assertions against the nested shape |
| `docs/endpoint-map.md`, `docs/current-state.md` | Record the changed `/hub/graphs` contract |

`backend/app/domain/work_orders.py` is **not** touched — `community_memberships`,
`normalize_service_type`, and the filter normalizers are all reused as-is.
