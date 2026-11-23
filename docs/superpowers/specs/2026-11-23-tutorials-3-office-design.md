# Tutorials 3 — office work (TechFM OA and above)

> **Rule added by the user 2026-11-23 (overrides anything below):** every box shows ONE simple sentence. A step that needs more is written as a list of sentences (`text: ["...", "..."]`, at most 3, each at most 120 characters) and the player gives each sentence its own tap on the same lit section. Wording tables that hold two sentences in one step are split at the sentence boundary, never merged into a longer sentence. Use plain words a new hire would use; one idea per sentence. See 0a spec 5.2 and 5.4.

Date: 2026-11-23 · Status: awaiting approval · Budget: ≤ 2,400 words (largest batch)

Refers to `2026-11-23-tutorials-0a-player-design.md` ("0a") by section number; nothing in it is restated.

## 1. Intent

Seven pages of office work get tutorials, written as data only: format 0a 5.2, sample data 0a 5.3, house rules 0a 5.2 (≤ 8 steps, ≤ 2 sentences, ≤ 240 characters, plain words, every sentence traceable to `tips.js` or `current-state.md`). No player code. Pop-ups are described, never opened. English only.

## 2. Scope and non-goals

| In | Out |
| --- | --- |
| 16 scripts on seven pages (section 3) | SMR imports on Integrations, SMR Admin Review (never built: SMR is finished) |
| Sample files for each page | Custody check-in, Find Item search (batch 1) |
| Anchors the orchestrator adds (section 5) | The `?` bubbles, which stay as they are |
| | Anything needing a file, the camera, or the cloud sign-in window (section 6) |

Keys follow `<page>.<area>.<script>`. Selectors below are what exists today; the builder confirms each against the markup.

## 3. Scripts

Role rule used throughout: a step whose target is absent for the viewer is skipped (0a 5.2). Page access: create-item, user-requests, low-stock, admin-review, integrations are TechFM OA+ only (`PAGE_ACCESS`), so every viewer sees every step unless noted. saved-items and tools are open to every role; see call C1.

### 3.1 create-item (OA+)

**`create-item.add.item`** — "Add Item". For: anyone adding a catalogue item. `open`: `.sub-nav-btn[data-feature="item"]`. `here`: `.sub-nav-btn[data-feature="item"].active`.

| Step points at | Wording |
| --- | --- |
| `#barcode` | The label number workers will scan. Type it in, or use Scan beside it. |
| `#item-scan-toggle-btn` | Scan opens the camera on this device so you can read the label instead of typing it. |
| `#name` | The name workers will see in search results. |
| `#location` | Where the item physically sits, as workers would describe it. It shows on search results so nobody has to ask. |
| `#quantity` | How many are on the shelf now. A wrong count is fixed later with Correct Count, never by re-adding. |
| `#price` | Optional here, but material with no price cannot bill. Using it unpriced on a work order raises a missing-price request. |
| `#product-link` | Where the item is bought. With the price, it is what closes a missing-price request. |
| `#create-item-btn` | Save Item adds it to the catalogue. Nothing is saved until you tap it. |

**`create-item.add.tool`** — "Add Tool". `open`: `.sub-nav-btn[data-feature="tool"]`. `here`: `.sub-nav-btn[data-feature="tool"].active`.

| Step points at | Wording |
| --- | --- |
| `#tool-barcode` | The label used to find this tool for checkout, return, and inventory. It must be unique among active tools. |
| `#tool-scan-toggle-btn` | Scan opens the camera so you can read the label instead of typing it. |
| `#tool-name` | The name people will see when they pick this tool. |
| `#tool-quantity` | Use 1 for a single serialized tool. Use a higher count for an unserialized batch tracked as a pool. |
| `#create-tool-btn` | Save Tool adds it to Tool Inventory. Archiving a tool later frees its barcode for reuse. |

### 3.2 saved-items (office parts)

All four scripts follow the Search script (batch 1) in file order. Reached from the Find tab's row Actions menu, which exists only for Team Lead+ (Notes) and OA+ (the rest).

**`saved-items.find.edit-item`** — "Edit Item". For: TechFM OA+. `open`: `#items-load-all-btn`, `[data-menu][data-id="-11"] .menu-trigger`, `[data-menu][data-id="-11"] [data-value="edit"]`. `here`: `#item-editor-section:not([hidden])`.

| Step points at | Wording |
| --- | --- |
| `#item-editor-selected` | Shows which item you are changing. Nothing changes until you tap Save Changes. |
| `#item-editor-barcode` | The label number workers scan. |
| `#item-editor-location` | Where the item sits, as workers would describe it. |
| `#item-editor-barcodes-rows` | Extra codes on the packaging that should scan to this same item. Use them when a vendor changes a label. |
| `#item-editor-price` | Material with no price cannot bill. |
| `#item-editor-product-link` | Where it is bought. Price and link together close a missing-price request. |
| `#item-editor-save-btn` | Saves the changes. Cancel leaves the item as it was. |

**`saved-items.find.notes`** — "Item notes". For: Team Lead and above. `open`: as above with `[data-value="notes"]`. `here`: `#notes-editor-section:not([hidden])`.

| Step points at | Wording |
| --- | --- |
| `#notes-rows` | Each note has a unique name and a stored type: text, number, or true/false. |
| `#notes-add-row-btn` | Adds another note row. Pick the right type so later displays and edits stay consistent. |
| `#notes-save-btn` | Saves all the notes on this item. Cancel closes the editor without saving. |

**`saved-items.find.correct-count`** — "Correct Count". For: TechFM OA+. `open`: as above with `[data-value="correct"]`. `here`: `#correction-section:not([hidden])`.

| Step points at | Wording |
| --- | --- |
| `#correction-section > h2` | Use this when the shelf count is wrong, not to record usage. Taking material out for a job is a Take Out Stock transaction. |
| `#correction-current` | The count the app holds now. |
| `#correction-new-quantity` | Type what is really on the shelf. The app records the difference as an adjustment that bills nothing. |
| `#correction-reason` | Required. It shows in Transaction History, so write what you would want to read six months from now. |
| `#correction-save-btn` | Saves the corrected count. |

**`saved-items.scan.add-barcode`** — "Add Barcode to an Item". For: TechFM OA+. The panel opens only from a scan that finds nothing (`openAddBarcode`), so it cannot be opened on sample data (call C2). The script lives on the Scan tab and describes it. `open`: `.sub-nav-btn[data-feature="scan"]`. `here`: `.sub-nav-btn[data-feature="scan"].active`.

| Step points at | Wording |
| --- | --- |
| `#items-scan-section > h2` | Scan a label to jump to its item. |
| `.scan-toolbar` in `#items-scan-section` | If the scan finds nothing, an Add Barcode panel opens. Search the item by name and the scanned code is attached to it. |
| `#items-scan-add-barcode-hint` (anchor A3) | Use this when you know the item is in the catalogue. It saves creating a duplicate item. |

### 3.3 user-requests (OA+)

One script per tab. `open`: `#user-requests-tabs [data-request-type="<type>"]`, then for material, catalogue and price a first card is targeted by its id (`#ureq-card--41`). `here`: `#user-requests-tabs [data-request-type="<type>"][aria-selected="true"]`. All four share the first two steps' form.

**`user-requests.requests.material`** — "Material requests". For: whoever keeps the shelves stocked.

| Step points at | Wording |
| --- | --- |
| `#user-requests-tabs` | Four kinds of request, one tab each. The number is how many are open. |
| `#user-requests-status` | Open is what needs you. Stocked and Resolved are the past. |
| `#ureq-card--41 .user-request-details` | A crew asked staff to stock this item. It shows the work order, how many, and what is on hand now. |
| `#ureq-card--41 .user-request-stock` | Use this when the shelf really has the item but the count says otherwise. It notifies the crew without recording a stock transaction. |
| `#ureq-card--41 .user-request-action` | Mark resolved closes the request. It does not change stock. |
| `#ureq-card--41 .user-request-edit-open` | Edit fixes the request's details. |

**`user-requests.requests.catalogue`** — "Catalogue requests". For: whoever adds new items.

| Step points at | Wording |
| --- | --- |
| `#ureq-card--42 .user-request-details` | Someone reported material that has no catalogue row. It shows what was searched, how many, and the work order. |
| `#ureq-card--42 .user-request-fulfill-open` | Fulfil adds the item and logs it retroactively on its work order. Matching requests start checked so one fix can close them together. |
| `#ureq-card--42 .user-request-close-open` | Close without fulfilling needs a reason. You can reopen it from Resolved. |
| `#ureq-card--42 .user-request-edit-open` | Edit fixes the request's details. |

**`user-requests.requests.recount`** — "Stock recounts". For: whoever counts shelves.

| Step points at | Wording |
| --- | --- |
| `#ureq-card--43 .user-request-details` | A dispense came up short. It shows the count before, what was dispensed, and the shortage. |
| `#ureq-card--43 .user-request-count-input` | Type the count you found on the shelf. |
| `#ureq-card--43 .user-request-count-reason` | Saving writes an inventory adjustment with this reason. |
| `#ureq-card--43 .user-request-action` | Mark resolved only closes the request. It does not change stock. |

**`user-requests.requests.price`** — "Missing price / link". For: whoever prices material.

| Step points at | Wording |
| --- | --- |
| `#ureq-card--44 .user-request-details` | Material was used on a work order with no price. Unpriced material cannot bill. |
| `#ureq-card--44 .user-request-price-input` | Enter the price. |
| `#ureq-card--44 .user-request-link-input` | Enter where it is bought. The request stays open until both a price and a link exist. |
| `#ureq-card--44 .user-request-price-save` | Saves both and closes the request. |
| `#ureq-card--44 .user-request-action` | Remove closes it without pricing. |

### 3.4 low-stock (OA+)

**`low-stock.queue.reorder`** — "Reorder queue". `open`: `#low-stock-card--51 summary`. `here`: none (single script).

| Step points at | Wording |
| --- | --- |
| `#low-stock-section > h2` | Every item at or below its alert threshold, deepest below first. |
| `#low-stock-tabs` | Tabs sort the queue by how recently each item moved, so what is both low and moving comes first. |
| `#low-stock-card--51 .low-stock-summary` | What it is, how much is left, and how much was used in the last 7 days, including retroactive material. |
| `#low-stock-card--51 .low-stock-threshold` | Raise Warn at to be warned earlier. It takes effect on the next count that crosses it. |
| `#low-stock-card--51 .low-stock-edit` | Fix the name, location, price, link, or extra barcodes here, then Save item. |
| `#low-stock-card--51 .low-stock-correction` | Use this when the shelf count is wrong. The reason is required and is kept with the adjustment. |

### 3.5 admin-review (OA+)

**`admin-review.queue.review`** — "Billing review". `open`: `#review-card--61`. `here`: none. The Admin Review queue holds orders an Admin sent to Review; a TechFM OA works it but cannot send an order here.

| Step points at | Wording |
| --- | --- |
| `#admin-review-list` | Work orders waiting for final billing review. A tile that says Needs price has unpriced material. |
| `#review-card--61` | Tap a tile to build its receipt. |
| `#admin-review-receipt-output` | The billing document, laid out for the client's 41-character text box. Copy it out as-is; changing the spacing breaks it at the other end. |
| `#admin-review-netfacilities-btn` | Opens NetFacilities so you can paste the receipt in. |
| `#admin-review-reopen-btn` | Return to In-Progress sends the order back for corrections and keeps it live. |
| `#admin-review-close-btn` | Close finishes it. A closed work order leaves the active lists. |

The Missing prices pop-up (shown on a tile that Needs price) is described in step 1 only.

### 3.6 integrations (OA+)

Owner also sees four SMR buttons; they are not pointed at, so the script reads the same for all. `open`: none.

**`integrations.netfacilities.import`** — "Import work orders".

| Step points at | Wording |
| --- | --- |
| `#wo-netfacilities-status` | Shows where the NetFacilities sign-in stands. |
| `#wo-netfacilities-cloud-sign-in-btn` | Opens a cloud sign-in window from any device. Export the work-order CSV there, then Import downloaded CSV brings it in. |
| `#wo-netfacilities-enrich-btn` | Fills in Task/Symptom and Priority from the same session. |
| `#wo-import-btn` | Import from CSV still takes any file you already have. |

**`integrations.netfacilities.export`** — "Export for the client".

| Step points at | Wording |
| --- | --- |
| `#wo-export-scope` | Picks which work orders go out, by status. |
| `#wo-export-client-btn` | For Client exports the billing sheet with totals and receipts, for the orders picked beside it. |

### 3.7 tools

**`tools.inventory.lookup`** — "Tool Inventory". For: every role. `open`: `.sub-nav-btn[data-feature="inventory"]`. `here`: `.sub-nav-btn[data-feature="inventory"].active`. Technician and Team Lead have no Actions column, so that step and its last sentence vanish; no `textFor` needed.

| Step points at | Wording |
| --- | --- |
| `#tools-search` | Find a tool by name or barcode. |
| `#tools-table` | On Hand is what is on the shelf. Checked Out names who holds the rest. |
| `[data-menu][data-id="-71"]` | Edit changes the name or barcode. Correct Count fixes a miscount or adds units to a bulk tool, with a reason. Archive frees the barcode. |

**`tools.custody.checkout`** — "Check out a tool". For: TechFM OA+ only (call C1). `open`: `.sub-nav-btn[data-feature="custody"]`, `#tool-user-search`, `.tool-user-option[data-user-id="-21"]`, `#tool-checkout-search`, `[data-checkout-tool-id="-71"]`. `here`: `#tool-checkout-section:not([hidden])`.

| Step points at | Wording |
| --- | --- |
| `#tool-user-picker` | Pick the person first. Their card shows what they hold. |
| `#tool-checkout-controls` | Search by tool name or barcode, or scan the tool label. |
| `#tool-checkout-quantity` | How many are going out. |
| `#tool-checkout-work-order` | Optional. It records which job the tool went out on; leave it blank for general shop use. |
| `#tool-checkout-save-btn` | Check Out records it against that person. |

## 4. Sample data

All ids negative; names made up in the pilot's style.

| Page | GET paths answered | Records |
| --- | --- | --- |
| create-item | none (confirm the loader makes none; else `{}`) | none |
| saved-items | `GET /items/` | Three items, ids -11..-13, one with notes `{"Size":"3 in","Pack":100}`, one with an extra barcode, one unpriced; `price`, `product_link`, `barcodes`, `low_stock_threshold` present. `sample(user)` returns them as the viewer's role is allowed to see them |
| user-requests | `GET /user-requests/counts`; `GET /user-requests/?status=open&type=material_request`, `…catalogue_request`, `…inventory_recount`, `…missing_item_price` | One open card per type, ids -41..-44, each with `request_type`, `status:"open"`, `message`, `details`, item and work-order fields the card builder reads; one catalogue card with a work order number. Counts 1 each |
| low-stock | `GET /items/low-stock` | Three rows, ids -51..-53, each with `last_dispensed_at` computed from now so one lands in each tab (last 24 h, 2–7 days, never) |
| admin-review | `GET /work-orders/?status=review`; `GET /work-orders/-61`; `GET /work-orders/-62` | Two Review orders; -61 fully priced with material and labor, -62 with `has_unpriced_items:true`. Detail shape as the 0a pilot's In-Progress order with status review |
| integrations | `GET /integrations/netfacilities/cloud/session` | `{available:true, has_saved_session:true, status:{state:"idle"}}` so Log in and Import Tasks and Priority both show |
| tools | `GET /tools/`; `GET /users/` | Three tools, ids -71..-73 (one with a `custody` entry, one a bulk count); three active users, -21..-23, so the picker has a list |

## 5. Anchors to add (orchestrator)

Most targets already exist as ids or scoped classes. Only these are missing or ambiguous.

| # | Page | Add | Why |
| --- | --- | --- | --- |
| A1 | create-item | nothing | All fields have ids |
| A2 | user-requests | `id="user-requests-export-link"` on the Export for print link | Only gap; tabs, status select and cards (`#ureq-card-<id>` plus part classes) already exist |
| A3 | saved-items | A `<p id="items-scan-add-barcode-hint" class="hint">` in the Scan section holding the no-match sentence; the last step of 3.2 then targets it | `#items-scan-chooser` is `hidden` until a scan runs, and a hidden target is skipped |
| A4 | low-stock | nothing | Cards (`#low-stock-card-<id>`), tabs and the scoped classes exist |
| A5 | admin-review | none | Tile `#review-card-<id>`, receipt and buttons have ids |
| A6 | integrations | none | Every button has an id |
| A7 | tools | none; row menu found by `[data-menu][data-id]` | |

In short: A2 (one id) and A3 (one hint paragraph) are the only edits; the id census gains both. The builder adds any further id it finds missing and reports it.

## 6. What a tutorial cannot show

| Page | Cannot show | Handling |
| --- | --- | --- |
| create-item, saved-items, tools | Camera scanning, Upload Photo | Scan buttons are pointed at and described only; `open` never clicks a scan toggle |
| saved-items | Add Barcode panel (opens only from a scan) | Described from the Scan tab (3.2) |
| integrations | The cloud sign-in window, file pickers, the downloaded CSV | The buttons are described; `open` never clicks them. "Import downloaded CSV" and "Close NetFacilities" appear only in a sentence, since they show only mid-session |
| admin-review | Open NetFacilities window, Missing prices pop-up | Described |
| user-requests | Fulfil and Close forms, Edit panels (inline panels the buttons open) | Described, not opened |

## 7. Agent table

One agent per page; each writes only its two files and reads only what is listed. Each reports file paths, selectors it could not find, sample paths the loader requested that the sample did not list, and questions.

| Page | Owns (`backend/static/tutorials/`) | Must read | Reports |
| --- | --- | --- | --- |
| create-item | `create-item.js`, `create-item.sample.js` | `pages/create-item.html`, `views/items.js`, `itemEditor.js`, tips `item.*`, `tool.*` | Confirms the loader makes no GET |
| saved-items | `saved-items.js`, `saved-items.sample.js` (extends batch 1's file) | `pages/saved-items.html`, `views/items.js`, `itemEditor.js`, `notes.js`, `addBarcode.js`, tips `item.*` | Whether Scan-tab `open` starts the camera |
| user-requests | `user-requests.js`, `user-requests.sample.js` | `pages/user-requests.html`, `views/userRequests*.js`, tips `requests.*` | Exact fields the card builder reads |
| low-stock | `low-stock.js`, `low-stock.sample.js` | `pages/low-stock.html`, `views/lowStock.js`, `lowStockCard.js` | Whether the `<details>` stays open through a live refresh |
| admin-review | `admin-review.js`, `admin-review.sample.js` | `pages/admin-review.html`, `views/adminReview.js`, `adminReviewReceipt.js`, `workOrderPresenters.js`, tips `review.*` | Minimum detail fields the receipt needs |
| integrations | `integrations.js`, `integrations.sample.js`  | `pages/integrations.html`, `views/workOrderIntegrations.js`, tips `integrations.netfacilities` | Every GET the page fires on load |
| tools | `tools.js`, `tools.sample.js` (extends batch 1's file) | `pages/tools.html`, `views/tools.js`, `toolCheckout.js`, tips `tools.*` | Whether the checkout form hides the user card |

## 8. Tests

The guard test (0a 6) covers everything here: targets exist for some role, house-rule limits, `textFor` keys, negative ids. Extra: if C1 is accepted, the guard reads `minRole` and checks each script has a visible step for every role at or above it, instead of every role that can open the page. Nothing else.

## 9. Calls made by Claude, for the user to check

- **C1 (needs a decision).** On saved-items and tools, Technician and Team Lead can open the page but never see the office controls, so 0a's rule "a visible step for each role that can open the page" would fail for Edit Item, Correct Count, Add Barcode, and Check out a tool. I propose an optional `minRole` on a script (data only): the guard checks from that role up, and the player offers "Next:" only to people at or above it. This is a small 0a-plan change.
- **C2.** Add Barcode is described from the Scan tab because its panel cannot be opened without a camera scan.
- Integrations is described for TechFM OA+ (as `PAGE_ACCESS` has it), though a comment in `pages/integrations.html` still says Admin+.
- Integrations is split into Import and Export; Admin Review and Low Stock are one script each.
- Stock recounts, catalogue and price scripts stop at describing Fulfil, Close and Edit rather than opening them.
- All wording above, as a table for the user's one review of the batch.
