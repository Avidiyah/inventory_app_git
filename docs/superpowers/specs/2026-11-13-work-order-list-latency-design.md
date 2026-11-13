# Work Orders list: open and search latency

Date: 2026-11-13 · Status: draft, awaiting go-ahead · Budget: ≤ 1,800 words

## 1. Problem

Opening the Work Orders page takes about one to two seconds before any card
shows. The list query is not the cause. The page waits for the whole item
catalogue, the users list and the filter options before it even asks for the
list.

Production timings (Render request logs, 2026-11-13, one-hour sample):

| Request | n | p50 | p90 | max |
|---|---|---|---|---|
| `GET /work-orders/` (browse and search) | 31 | 52 ms | 185 ms | 329 ms |
| `GET /items/` (whole catalogue) | 11 | 881 ms | 1,420 ms | 2,080 ms |

`/users/` and `/work-orders/filter-options` did not appear in the sample;
their cost is unmeasured.

## 2. Today's flow

`nav.js:71` calls `loadWorkOrders({ refreshReferenceData: true })` on every
page entry. Inside `loadWorkOrders` (`workOrderList.js:188`):

| Step | Line | Waits for |
|---|---|---|
| 1 | 233 | `ensureReferenceData`: `/items/` and `/users/` together |
| 2 | 237 | `loadFilterOptions`: `/work-orders/filter-options` |
| 3 | 253 | `apiListWorkOrders`: the cards |

Steps run one after another, so the first card appears after roughly
items + options + list. What each step is actually needed for:

| Data | Read by | Needed before cards paint? |
|---|---|---|
| Items | Add-material search in the card body (`workOrderActions.js:84`), a name lookup (`workOrderRouting.js:331`) | No. Both readers already handle an in-flight load through `itemsLoading()`. |
| Users | Technician filter dropdown (`workOrderFilters.js:83`); Team Lead picker in the card body | No for the list. The card page already awaits `ensureUsers()` itself (`workOrderRouting.js:204`). |
| Filter options | The four dropdowns | No. Cards do not read them. |

A search inside one visit is already short: reference data is loaded, so the
cost is the 250 ms typing debounce plus one list request.

## 3. Goals and non-goals

Goals:

- Cards appear after one request on page entry, not three in a row.
- A broad search or Show all does not cost one query per material line.
- A slow, older list response can never overwrite a newer one.

Non-goals (see section 7 for why each stays):

- Changing the 250 ms debounce.
- Moving the scheduled-date sort into SQL.
- A search index.
- Pagination or virtual scrolling of long results.
- The SMR page and `/items/` itself. Uncommitted changes in the working tree
  already cover both (`services/items.py`, `services/work_orders_smr.py`,
  `services/work_orders_smr_weekly.py`, `views/smr.js`). This spec does not
  touch those files.

## 4. Design

### 4.1 Ask for the list first (frontend)

File: `backend/static/views/workOrderList.js`, `loadWorkOrders` only.

- Start `ensureReferenceData({ refresh })` without awaiting it, as the solo
  branch at line 219 already does.
- Start the filter options as a background task: wait for `ensureUsers()`
  (the technician dropdown reads the roster), then `loadFilterOptions()`.
  Keep today's failure handling: on error, `invalidateFilterOptions()` and
  carry on.
- Send `apiListWorkOrders` at once and render when it lands.

No new module, no new state. `ensureReferenceData` and `ensureUsers` already
share in-flight requests, so starting them early costs nothing extra.

The role-dependent toggles at lines 244-245 (`exportBtn`,
`technicianFilterField`) read the session role, not the fetched data. They
stay where they are.

### 4.2 A filter choice that disappears on refresh

Today the options load before the list reads the filter values. With 4.1 the
list is sent first. `populateFilterSelect` (`workOrderFilters.js:40`) keeps
the current selection when the option still exists and silently resets it to
blank when it does not, for example a Team Lead whose last live work order
was archived elsewhere.

Rule: when a repopulate drops a selection, reload the list once.

- `loadFilterOptions` returns `true` when any dropdown's value changed during
  the repopulate.
- The background task in 4.1 calls `loadWorkOrders()` again on `true`.

This costs one extra request in a rare case and keeps the dropdowns and the
cards in agreement.

### 4.3 Latest request wins (frontend)

`loadWorkOrders` has no guard against responses landing out of order. Two
searches typed quickly can finish in reverse, and the older result then
replaces the newer one. The archived-number lookup beside it already uses a
counter for exactly this (`archivedSearchToken`, line 232).

Reuse that counter: after `apiListWorkOrders` resolves, return without
rendering when the token is no longer current. The counter is already bumped
once per load, so this is a single comparison, not a second mechanism.

The focus branch at lines 254-258 makes a second list call inside the same
load; it shares the same token and needs no extra handling.

### 4.4 Load each line's item with the list (backend)

File: `backend/app/services/work_orders.py`, `_LIST_EAGER_LOADS` (line 1120).

`_card` (`routers/work_orders.py:431`) reads `line.item.price` for every
material line to set `has_unpriced_items`. The list loads the lines but not
their items, so each distinct item costs its own query. Ten browse cards hide
this; a broad search or Show all (up to 5,000 cards) does not.

Change one entry:

    selectinload(WorkOrder.items).joinedload(WorkOrderItem.item)

This is the same load the detail path already uses at line 558. The only
callers of `_card` are the list route and `_detail` (graph: two inbound
callers), and `_detail` already has the item loaded, so nothing else changes.

The SMR branch inside `_card` (line 425) is not reached from this list:
`live_work_orders()` excludes SMR orders.

## 5. Edge cases

| Case | Behaviour |
|---|---|
| Cards painted, user taps one before items land | Unchanged. The card page awaits `ensureUsers()` and the material search waits on `itemsLoading()`. |
| Filter options request fails | Unchanged. Dropdowns keep their old choices; retried on the next page entry. |
| Users request fails | Technician dropdown stays empty, as today. Cards still show. |
| User opens a dropdown before options land | It shows the previous visit's choices, or only the "All ..." entry on a cold load, then fills. Typical gap is well under a second. |
| Technician (below Team Lead) | `ensureUsers` already resolves at once for this role; the technician field is hidden. No change. |
| Background refresh from the live socket (`background: true`) | Same path; the token guard also protects it. |
| Pending card-page open (solo branch, line 212) | Untouched. |
| Held editor open in a card | Untouched. `runOrDeferListRefresh` still defers. |

## 6. Tests

Following the repo's targeted-test preference: one check per change, no new
harness.

| Change | Test | File |
|---|---|---|
| 4.1 | With `/items/` held open, the list request is sent and cards render. | `tests/frontend/views/workOrders/filters.test.js` (MSW handlers in `tests/frontend/helpers/workOrders.js`) |
| 4.2 | A selected Team Lead missing from refreshed options triggers one further list request without that filter. | same file |
| 4.3 | Two loads resolved in reverse order leave the newer result on screen. | same file |
| 4.4 | Statement count for `GET /work-orders/` does not grow with the number of distinct items on the listed orders. | new `backend/tests/test_work_order_list_queries.py`, copying the counter from `test_work_order_open_queries.py` |

Existing tests that assert request counts on page entry
(`filters.test.js:386-409`) should still pass: the same requests are made,
only earlier. Any test that relies on the old ordering is updated, not
deleted.

Acceptance in production, after deploy:

- In-app check by the user: cards appear at once on page entry; dropdowns
  fill a moment later.
- Render logs: `GET /work-orders/` p50 is unchanged or lower. Server timings
  cannot show the removed wait, since it was time spent in the browser.

## 7. Limits that remain

These are what bounds latency once the changes above ship. None is worth
building now; each row names the signal that would change that.

| Limit | Why it exists | Cost today | Revisit when |
|---|---|---|---|
| 250 ms typing debounce | Avoids one request per keystroke | The largest part of a search's wait | The user wants snappier search and accepts more requests. A one-number change. |
| Scheduled-date sort runs in Python | `schedule_date` is raw vendor text; decisions X2 and X3 in `list_work_orders`' docstring | Every list call reads id, date and created time for all matching orders | The list request's p50 climbs past about 200 ms. Fix is a parsed date column filled at import. |
| Substring search scans the table | `ILIKE '%text%'` cannot use an ordinary index | Negligible at thousands of rows | Search p50 climbs. Fix is a `pg_trgm` index, one migration. |
| Uncapped search and Show all | A filter must return every match (line 248) | Up to 5,000 cards built into the page at once | Users report slow Show all. Fix is paging. |
| Catalogue reloads on every page entry | Keeps item changes made elsewhere from going stale | No longer blocks the cards; still a large download | Mobile data use becomes a complaint. |
| Network round trip to Oregon, single 1-CPU instance | Hosting plan | A floor of tens of milliseconds per request | Not a software matter. |

## 8. Decisions for the user

| # | Decision | Recommendation |
|---|---|---|
| 1 | Include 4.3 (latest request wins)? It is a correctness fix, not a speed fix. | Yes. One comparison, reuses an existing counter. |
| 2 | Shorten the search debounce? | No. Keep 250 ms until search feels slow after this ships. |
| 3 | Fold the uncommitted items and SMR speed-ups into this work? | No. They are separate, already written, and need their own commit by whoever owns them. |

## 9. Size

| Change | Files | Rough size |
|---|---|---|
| 4.1 + 4.3 | `workOrderList.js` | about 15 lines changed |
| 4.2 | `workOrderFilters.js`, `workOrderList.js` | about 8 lines |
| 4.4 | `services/work_orders.py` | 1 line |
| Tests | 1 new backend file, 3 cases added to an existing frontend file | about 90 lines |
| Docs | `docs/current-state.md` list-load note, if one exists | a line or two |

No schema change, no new endpoint, no new dependency.
