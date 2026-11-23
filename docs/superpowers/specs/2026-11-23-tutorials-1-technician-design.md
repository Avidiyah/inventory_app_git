# Tutorials 1 — the Technician's daily loop

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

Date: 2026-11-23 · Status: awaiting approval · Budget: ≤ 1,800 words

Builds on `2026-11-23-tutorials-0a-player-design.md` (0a). Script format is 0a §5.2, sample rules §5.3, house rules §5.2 end, wording-table form §5.6. Not restated here.

## 1. Intent

Five pages, nine scripts, written as data by one agent per page. No player code, no new test. Every sentence is traceable to `tips.js`, `current-state.md` (Roles, Frontend Feature Context) or the page markup.

## 2. Scope and non-goals

| In | Out |
| --- | --- |
| Work Orders list, scope, sort, search, filters | Card tabs (0a pilot, untouched) |
| Scan / Stock: gate and scanning | Mass Stage, History, Undo walkthrough |
| Hub Home and My Work Orders tabs | Dashboard, Timesheets, Leaderboards, Graphs, Report (later batches) |
| Tools Custody tab, check-in | Inventory, checkout flow, Correct Count (batch 3) |
| Find Item: search, Load All, scan | Edit item, notes, barcodes, Correct Count (office, batch 3) |

Keys never change once chosen. Roles: Tech, TL (Team Lead = `supervisor`), OA (`techfm_oa`), Admin, Owner.

## 3. Scripts

"Next" order follows file order (0a §5.4). Missing-target skipping handles roles; only wording differences are listed under **Role**.

### 3.1 work-orders (extends the 0a file)

New script goes FIRST in the file, with no `here`, so it plays when no card tab matches.

**`work-orders.list.find`** — "Finding a work order" · for everyone · `open`: none · `here`: none (fallback).

| Step points at | Wording | Role |
| --- | --- | --- |
| `#work-orders-scope` | My Work Orders shows the jobs you are on. All Work Orders shows every job. | |
| `#work-orders-sort` | Sort by scheduled date, newest or oldest first. | |
| `#work-orders-search` | Type a number, location or task to narrow the list. | |
| `#work-orders-filters-btn` | Advanced search adds filters: status, service type, priority, Team Lead, community and scheduled date. | Technician filter appears only where the page shows it |
| `#wo-export-btn` | Exports every work order that matches your filters, not only the ones on screen. | OA+ only (hidden otherwise, skipped) |
| first sample card | Each card is one job. Tap its header to open it. | |

### 3.2 transaction (two scripts)

**`transaction.scan.pick`** — "Picking a work order" · for everyone · `open`: none · `here`: `#wo-gate-cards-section:not([hidden])`.

| Step points at | Wording | Role |
| --- | --- | --- |
| `#wo-gate h2` | Pick the job you are scanning for. Only imported work orders appear; nothing typed here creates one. | |
| `#wo-gate-search-card` | Type a work order number to filter the cards. | TL+ only (hidden for Tech, skipped) |
| first card in `#wo-gate-cards` | Tap a card to start a scanning batch on that job. | Tech: "These are the jobs assigned to you. Tap one to start scanning." |

**`transaction.scan.scanning`** — "Scanning items" · for everyone · `open`: tap the In-Progress sample card · `here`: `#scango-active:not([hidden])`.

| Step points at | Wording | Role |
| --- | --- | --- |
| `#scango-wo-bar` | Your scans go to this job. Tap Change work order to pick another. | |
| `#scango-direction-fixed` | Everything you scan is taken out of stock and charged to this job. | Skipped if the direction toggle is showing |
| `#scango-advanced-toggle` | Reveals Add Stock and Take Out Stock, and browsing all items in manual entry. | TL+ only |
| `#scango-quantity` | Set the quantity before you scan. The default is 1. | |
| `#txn-scan-section .scan-toolbar` | Scan Barcode starts the camera and Upload Photo reads a picture. Each scan is saved to the work order automatically. | |
| `#scango-quickmode-toggle` | Quick mode saves a take-out scan at once, with no confirm box. Team Lead and above get an Undo on each logged line. | Tech: drop second sentence |
| `#txn-manual-section` | When a scan will not read, search by name or barcode here. It saves the same way a scan does. | Skipped while hidden |

### 3.3 user-hub (two scripts; other tabs belong to later batches)

**`user-hub.home`** — "Home" · for everyone · `open`: `#hub-tab-home` · `here`: `#hub-tab-home[aria-selected="true"]`.

| Step points at | Wording | Role |
| --- | --- | --- |
| `.hub-punch` | Punch in when your shift starts and punch out when it ends. Today's time shows here. | |
| `[data-action="hub-punch-in-shop"]` | Use this when you are in the shop and not on a work order. Shop time is paid and excluded from leaderboards. | Skipped when already punched in |
| `.hub-home-week-punches` | Open this to see this week's punches. Edit fixes one; Add punch records a missed one. | |
| `#hub-clock-mount` | Track starts your clock on the top job waiting for you and Stop ends it. A clock left running past 12 hours is closed automatically and marked auto-stopped. | Owner: "The Owner does not run a job clock." (only if the widget renders) |
| `.hub-tile-grid` | Jobs assigned to you, jobs in progress, and jobs ready to complete. | |

**`user-hub.work-orders`** — "My Work Orders" · for everyone · `open`: `#hub-tab-work-orders` · `here`: `#hub-tab-work-orders[aria-selected="true"]`.

| Step points at | Wording | Role |
| --- | --- | --- |
| `.hub-wo-list` | The jobs you are on, as the same cards the Work Orders page uses. | OA+: "Every live work order, up to ten cards." |
| first sample card | Tap a card to open that job on the Work Orders page. | |
| `[data-action="hub-view-all-work-orders"]` | View all opens the full Work Orders page. | |

### 3.4 tools

**`tools.custody.checkin`** — "Checking a tool in" · for everyone · `open`: none for Tech/TL (pinned to their own card); for OA+ the agent finds the clicks that pick the sample person · `here`: `.sub-nav-btn[data-feature="custody"].active`.

| Step points at | Wording | Role |
| --- | --- | --- |
| `.sub-nav` | Custody shows what a person is holding. Inventory and Scan are the other tabs. | |
| `#tool-user-picker` | Search for a person to see the tools they hold. | OA+ only |
| `#tool-user-card` | Name, role and how many tool records this person has out. | |
| `#tool-user-holdings` | Each row is a tool, with its barcode and the quantity out. | |
| first `.tool-checkin-btn` | Check In opens a short form. The amount starts at what is still out, and the work order is optional. | |
| `#tool-checkout-controls` | TechFM OA and above can also check a tool out to this person, by search or scan. | OA+ only |

### 3.5 saved-items (two scripts)

**`saved-items.find.search`** — "Finding an item" · for everyone · `open`: `#items-load-all-btn` · `here`: `.sub-nav-btn[data-feature="find"].active`.

| Step points at | Wording | Role |
| --- | --- | --- |
| `.sub-nav` | Find searches the catalogue. Scan looks an item up by its barcode. | |
| `#items-search` | Type a name or barcode, then tap Search. Nothing shows until you ask. | |
| `#items-load-all-btn` | Load All Items lists everything. It is a button so a phone is not made to draw thousands of rows. | |
| `#items-table` | Each row is one item, with its location so someone can go get it. Price and product link show only for TechFM OA and above. | |
| first row's action buttons | Edit, notes and Correct Count are office tasks and have their own tutorial. | Absent for Tech, skipped |

**`saved-items.scan.scan`** — "Scanning to find an item" · for everyone · `open`: `.sub-nav-btn[data-feature="scan"]` · `here`: `.sub-nav-btn[data-feature="scan"].active`.

| Step points at | Wording | Role |
| --- | --- | --- |
| `#items-scan-section .scan-toolbar` | Scan Barcode starts the camera and Upload Photo reads a picture of a barcode. The item it matches is shown to you. | |

## 4. Sample data

Negative ids; made-up names in the style of the existing sample file. `sample(user)` returns exact strings; an agent reads the page's loader and lists every GET it issues, because a key must match the real path and query to the character.

| Page | GET paths the sample must answer | Made-up records |
| --- | --- | --- |
| work-orders | `GET /work-orders/` as issued by the default load (scope mine, sort); `GET /work-orders/filter-options` | Reuse pilot orders -1 (In-Progress, viewer on crew) and -2 (Created); add -3 Assigned. One community, two service types |
| transaction | `GET /work-orders/` with `assigned_to_id=<viewer>` for a Tech, without it for others (`sample(user)` picks); `GET /items/` | -11 and -12 In-Progress, viewer assigned; -13 Assigned (never tapped: a tap would ask to start it). Three items, ids -21 to -23, with barcodes and quantities. `open` taps -11 |
| user-hub | `GET /hub`, `GET /attendance/me`, the My Work Orders list (`mine=true&limit=10` Tech/TL, `limit=10` otherwise), plus whatever else `userHub.js` fetches on load | Viewer not punched in; `startable` = [-1]; counts 2 / 1 / 0; one earlier punch this week; nothing running (clock off state) |
| tools | `GET /tools/`; `GET /users/` for the roles whose loader calls it | Two tools (ids -31, -32), one with custody for the viewer and one for a made-up person "Pat Sample" (id -41) |
| saved-items | `GET /items/` (Load All; no query is typed) | Four items, ids -21 to -24, with barcode, location, quantity; price and link filled, so OA+ sees them |

Each agent reads the viewer from `sample(user)`, never hard-codes a role.

## 5. Anchors to add

All ids/classes above were read from the real markup and exist, except as noted. The orchestrator adds the missing ones and updates the id census.

| Page | Exists | Missing or to confirm |
| --- | --- | --- |
| work-orders | all listed ids; card is `details.wo-card[data-id]` | none |
| transaction | `#wo-gate`, `#wo-gate-cards`, `#scango-*`, `.scan-toolbar`, `#txn-manual-section` | Stable class on a gate card (agent reports what the markup gives; else orchestrator adds `.wo-gate-card`) |
| user-hub | `.hub-punch`, `.hub-home-week-punches`, `#hub-clock-mount`, `.hub-tile-grid`, `.hub-wo-list`, both `data-action` buttons | Tutorial button at the end of `#hub-tabs`: the page has no `h2` title, so 0a §5.5 needs a Hub exception |
| tools | `.sub-nav`, `#tool-user-*`, `.tool-checkin-btn`, `#tool-checkout-controls` | none |
| saved-items | `.sub-nav`, `#items-*` | Action buttons cell of an items row: no stable class seen. Orchestrator adds one if the agent confirms |

## 6. Cannot be shown on sample data

| Page | Left out |
| --- | --- |
| transaction | Live camera and aim box; the batch log and summary (empty until a real scan); the red re-count warning; confirm dialogs (pop-ups are described only) |
| user-hub | The punch editor; a running clock (needs a start, which writes) |
| tools | Scan Tool to Check Out and its camera; the Check In form itself |
| saved-items | Live camera; edit, notes, barcodes and count pop-ups |

## 7. Agent table

Every agent also reads 0a §5.2/§5.3/§5.6, `tips.js`, and the existing pilot `work-orders.js` and `.sample.js` as the worked example.

| Page | Files owned (write only these) | Must read | Reports back |
| --- | --- | --- | --- |
| work-orders | `tutorials/work-orders.js` (edit: add script first), `tutorials/work-orders.sample.js` (edit: add -3, list keys) | `pages/work-orders.html`, `views/workOrders.js`, `workOrderList.js` | Exact list GET strings; any anchor not found |
| transaction | `tutorials/transaction.js`, `tutorials/transaction.sample.js` | `pages/transaction.html`, `views/transactions.js`, `scan.js` | Gate-card selector; whether a resumed batch skips the gate; Tech vs TL gate GETs |
| user-hub | `tutorials/user-hub.js`, `tutorials/user-hub.sample.js` | `pages/user-hub.html`, `views/userHub.js`, `hubHome.js`, `hubClock.js`, `hubTechnician.js`, `hubPicker.js` | Every GET on load; Owner clock rendering; phone-picker finding |
| tools | `tutorials/tools.js`, `tutorials/tools.sample.js` | `pages/tools.html`, `views/tools.js`, `toolReturn.js` | Clicks that select the sample person for OA+; whether `GET /users/` is called per role |
| saved-items | `tutorials/saved-items.js`, `tutorials/saved-items.sample.js` | `pages/saved-items.html`, `views/items.js`, `subnav.js` | Row action-cell selector; table columns for Tech vs OA |

## 8. Tests

The 0a guard test covers all: targets exist for some role, each script is visible to every role that opens the page, house-rule limits, negative ids, `textFor` roles. Extra: none. Two checks the orchestrator runs by hand once: the Hub scripts on a phone width, and the Technician run of `transaction.scan.scanning` (no leaked batch state after End).

## 9. Calls made by me, for the user to check

- Nine scripts in five pages; Scan splits into pick and scanning, Find Item into find and scan.
- Work Orders list script is first in the file and has no `here`, so it plays whenever no card tab is current.
- Sample tap for Scan / Stock uses an In-Progress order, so no start-confirm or write occurs.
- On a phone the Hub tab row sits behind the picker toggle; the My Work Orders `open` may need `#hub-picker-toggle` first. The agent reports; the orchestrator decides the fix.
- Wording tables above, including the Tech-only shortened Quick mode text.
