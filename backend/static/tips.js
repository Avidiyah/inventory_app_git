// Field-help copy for the `?` bubbles. Keys are stable ids referenced from
// markup via `data-tip`; see docs/superpowers/specs/2026-08-23-tooltips-design.md.
//
// Layer: data only. No imports, no functions -- the whole body of field-help
// copy is meant to be read and edited as prose in one place (spec D1).
//
// `label` is the accessible name of the button ("Help: <label>"); `text` is the
// bubble body. Plain text only, 1-3 sentences, no markup and no links (D5) --
// both are escaped at render time.
//
// Key naming: `<area>.<thing>`, lowercase, dot-separated. The area prefix keeps
// the registry grouped by page when sorted, which is how it gets reviewed.
//
// A tip explains a rule you need once while learning. A rule you need every
// time you touch the control stays a visible `.hint` paragraph.
export const TIPS = {
  // --- Login (shell-head.html) ------------------------------------------
  "auth.shift-session": {
    label: "Stay signed in for this shift",
    text: "Every sign-in expires after 12 hours. Turn this on only to keep the session cookie when the browser closes; it does not extend the 12-hour limit.",
  },
  "auth.notifications": {
    label: "Enable notifications",
    text: "Allows this device to receive work-order alerts for the signed-in account. On iPhone and iPad, push works only when the app is installed to the Home Screen; logging out removes this device's subscription.",
  },

  // --- Transaction (pages/transaction.html) ------------------------------
  "txn.wo-gate": {
    label: "Selecting a work order",
    text: "Work orders are import-only. A number that has not been imported cannot be scanned into, and nothing you type here creates one. Pick one of the cards to start a scanning batch.",
  },
  "txn.quick-mode": {
    label: "Quick mode",
    text: "Quick mode commits a dispense scan immediately instead of showing the confirm dialog. Add Stock always keeps its confirm, because a mistake there is costlier to reverse. Supervisor and above get an Undo on each logged line; other roles do not.",
  },
  "txn.advanced": {
    label: "Manual entry and stock options",
    text: "Reveals the Add Stock / Take Out direction toggle and the browse-all-items mode of the manual entry panel. Without it you get the streamlined dispense-only flow.",
  },
  "txn.direction": {
    label: "Add Stock and Take Out Stock",
    text: "Add Stock puts material back on the shelf. Take Out Stock removes it and charges it to the work order you selected.",
  },

  // --- Add Item / Tool (pages/create-item.html) --------------------------
  "item.barcode": {
    label: "Barcode",
    text: "The label number workers will scan. Scan it with the camera or type it in; an item can pick up more codes later from Find Item.",
  },
  "item.location": {
    label: "Location",
    text: "Where the item physically sits, as workers would describe it. It shows on search results so somebody can go get it without asking.",
  },
  "item.price": {
    label: "Price",
    text: "Optional here, but material with no price cannot bill. Using an unpriced item on a work order raises a missing-price request in the User Requests queue, which stays open until a price and a product link both exist.",
  },
  "item.product-link": {
    label: "Product Link",
    text: "Where the item is bought, for reordering and for checking the price. It is half of what closes a missing-price request; the other half is the price.",
  },
  "tool.quantity": {
    label: "Tool quantity",
    text: "Use 1 for a single serialized tool. Use a higher count for an unserialized batch that is tracked as a pool rather than as individual tools.",
  },
  "tool.barcode": {
    label: "Tool barcode",
    text: "The label used to find this tool for checkout, return, and inventory. It must be unique among active tools; archiving a tool frees its barcode for reuse.",
  },

  // --- Find Item (pages/saved-items.html) --------------------------------
  "item.load-all": {
    label: "Search and Load All Items",
    text: "Nothing shows until you ask for it: Search filters the full catalogue by name or barcode, Load All lists everything. This is deliberate, so a phone is not made to render thousands of rows to answer one question.",
  },
  "item.extra-barcodes": {
    label: "Additional barcodes",
    text: "Extra codes on the packaging that should scan to this same item. Use these when a vendor changes a label or a case and an inner unit carry different codes.",
  },
  "item.correct-count": {
    label: "Correct Count",
    text: "Use this when the shelf count is wrong, not to record usage. Taking material out for a job is a Take Out Stock transaction; a correction is an adjustment that bills nothing.",
  },
  "item.correct-reason": {
    label: "Correction reason",
    text: "The reason is stored on the adjustment and shows in Transaction History, so somebody reading the count change later knows why it happened. Write what you would want to read six months from now.",
  },
  "item.add-barcode": {
    label: "Add Barcode to an Item",
    text: "Attaches a code you just scanned to an item that already exists, instead of creating a duplicate item. Use it when a scan finds nothing but you know the item is in the catalogue.",
  },
  "item.notes": {
    label: "Item notes",
    text: "Each note has a unique name and a stored type: text, number, or true/false. Choosing the right type keeps later displays and edits consistent.",
  },

  // --- Tools (pages/tools.html) ------------------------------------------
  "tools.custody-vs-inventory": {
    label: "Custody and Inventory tabs",
    text: "Custody is user-first: pick a person and see what they are holding, then check tools out or in. Inventory is tool-first: look a tool up, edit it, or correct its count.",
  },
  "tools.checkout-wo": {
    label: "Work Order on checkout",
    text: "Optional. It records which job the tool went out on, so custody can be read alongside the work order. Leave it blank for general shop use.",
  },
  "tools.return-wo": {
    label: "Work Order on check-in",
    text: "Optional, and it does not have to match the checkout. It records the job the tool came back from.",
  },
  "tools.correct-reason": {
    label: "Tool correction reason",
    text: "Corrections fix a miscount or add units to a bulk tool. The reason is kept with the adjustment so the count change is explainable later.",
  },

  // --- Work Orders (pages/work-orders.html) ------------------------------
  "wo.status": {
    label: "Status",
    text: "The lifecycle runs Created, Assigned, In-Progress, Ready to Complete, Completed, Review, with On-Hold as the pause state meaning nobody is on the clock. Ready to Complete is a technician saying the job is done and waiting on a supervisor; Completed is the supervisor agreeing and is what the billing queue reads; Review is the final admin billing check.",
  },
  "wo.priority-vs-level": {
    label: "Priority and Priority level",
    text: "Priority is the category imported from NetFacilities. Priority level is TechFM's own High/Medium triage layered on top of it. They are separate fields and they filter independently.",
  },
  "wo.community": {
    label: "Community",
    text: "Derived from the imported location rather than typed, so it stays consistent across imports. A row whose location matches no named community falls under Academics, including rows with a blank location.",
  },
  "wo.scheduled-date": {
    label: "Scheduled date",
    text: "Matches the imported scheduled date exactly, not a range. Rows whose imported date is blank or unreadable sort last and will not match any date you pick here.",
  },
  "wo.export": {
    label: "Export filtered CSV",
    text: "Exports every work order matching the filters above, not just the ones shown on screen. The file re-imports cleanly, so it doubles as a way to bulk-correct rows and load them back.",
  },
  "wo.routing": {
    label: "Assigned technicians",
    text: "The routed Supervisor oversees the order. More than one technician can be assigned. Technicians must be assigned to track time; Supervisors and higher roles may also work and record time on any order they can see.",
  },
  "wo.entry-mode": {
    label: "New material entry mode",
    text: "Dispense records new material as stock-moving usage. Retroactive adds a paper-sheet entry to the work order without changing on-hand stock; the mode applies only to entries added after the selection changes.",
  },
  "wo.auto-stopped": {
    label: "Auto-stopped labor",
    text: "A clock found running past 12 hours is closed at the 12-hour cap and marked as an estimate. Review the entry before billing it.",
  },

  // --- Billing (shared History / Work Orders editor) --------------------
  "billing.quantity": {
    label: "Billable quantity",
    text: "This changes the invoice only; it never puts material back in stock. Zero keeps the line but charges nothing, while a blank value or the full recorded quantity clears the override and bills all units.",
  },

  // --- History (pages/history.html) --------------------------------------
  "history.wo-filter": {
    label: "Filter by Work Order",
    text: "Filters on the work-order number stored on each row, so a work order's history survives the work order being archived. If the number you type names an archived work order, Supervisor and above are offered a restore.",
  },
  "history.date-range": {
    label: "Date range",
    text: "Either side may be left blank for an open range. The To date is included in full, so a row logged late that day still matches.",
  },
  "history.pricing-list": {
    label: "Pricing list",
    text: "Builds a plain-text list of every priced row matching the current filters, not just the visible page, with a total. It is formatted to fit the client's 41-character text box, so paste it in as-is.",
  },
  "history.charge-col": {
    label: "Charge column",
    text: "Shows the base line value and the marked-up value for ad-hoc rows. A work-order row shows a dash instead, because that material bills through its work-order line rather than here.",
  },

  // --- Admin Review (pages/admin-review.html) ----------------------------
  "review.receipt": {
    label: "Work Order Receipt",
    text: "The billing document for the work order, laid out to fit the client's 41-character text box. Copy it out as-is; changing the spacing breaks it at the other end.",
  },
  "review.reopen-vs-close": {
    label: "Return to In-Progress and Close",
    text: "Return to In-Progress sends the work order back for corrections and keeps it live. Close finishes it, and a closed work order leaves the active lists.",
  },

  // --- User Requests (pages/user-requests.html) --------------------------
  "requests.types": {
    label: "Request types",
    text: "Recount requests flag stock that came up short. Missing price requests collect a price and product link for unpriced material used on a work order. Item requests report material a user searched for and could not find; fulfilling one adds it to the catalogue and logs it back onto the work order it came from.",
  },
  "requests.recount": {
    label: "Correcting a recount request",
    text: "Saving a corrected count writes an inventory adjustment with this reason. Mark resolved only closes the request; it does not change stock.",
  },
  "requests.siblings": {
    label: "Closing matching item requests",
    text: "Matching item requests start checked because one catalogue fix can close them together. Each selected request with a live work order adds its own quantity there; closed or absent work orders receive no line, and unchecked requests stay open.",
  },

  // --- Mass Stage (pages/mass-stage.html) --------------------------------
  "stage.new": {
    label: "New Mass Stage",
    text: "A stage plans truck loading around work orders that are already imported. It cannot create a work order, and only one active stage exists per community and building at a time.",
  },
  "stage.load-list": {
    label: "Mass Stage load list",
    text: "The load list merges the same item across every unit. Planned is the requested total, Loaded is what has been staged, Remaining is the planned quantity not yet loaded, and Return records unused staged stock back into inventory.",
  },

  // --- Add User (pages/create-user.html) ---------------------------------
  "user.role": {
    label: "Role",
    text: "Technicians scan and work assigned jobs; Supervisors run the board and approve finished work. TechFM OA handles imports, exports, and the request queues, and Admin and Owner add billing review and full account management. You can only create roles at or below your own.",
  },
  "user.lifecycle": {
    label: "User lifecycle",
    text: "Archiving blocks sign-in but keeps the user's history and allows restoration later. A user holding tools must return them first, or the archive confirmation can check them all in.",
  },

  // --- User Hub (pages/user-hub.html) ------------------------------------
  "hub.clock": {
    label: "Time clock",
    text: "Starting work on a work order opens your clock, and stopping it closes it. A session left running past twelve hours is closed automatically at the twelve-hour mark and flagged auto-stopped, so review those before they bill.",
  },
  "hub.graphs": {
    label: "Graphs",
    text: "The donuts are a shape, not a readout. The exact counts sit in the legend beside each one, and clicking a slice opens the matching work orders. Pick a community first, then split it by service type or priority.",
  },
  "hub.priorities": {
    label: "Hub priorities",
    text: "Technicians see high-priority work assigned to them. Supervisors see high-priority live work orders routed to them, and TechFM OA and above see company-wide counts. The main count includes the unassigned subset shown beside it.",
  },
  "hub.crew": {
    label: "My crew",
    text: "Crew membership is derived from live work orders routed to you, not from a permanent team list. A person appears after a work order is assigned under your supervision.",
  },
  "hub.timesheets": {
    label: "Timesheets",
    text: "Each day includes tracked sessions plus manual adjustments. Supervisors see their routed crew; TechFM OA and above see every live Supervisor and Technician account. Open a day cell to see the tracked/adjustment split and any estimate flags.",
  },
  "hub.attention": {
    label: "Needs attention",
    text: "Long session starts at 8 hours and approaching cap at 11. Idle means assigned work with no recorded time at 10:00 a.m. Central. Stale means an In-Progress or On-Hold order has no session activity recorded, or its last activity was at least three days ago.",
  },
  "hub.clock-attention": {
    label: "On the clock now",
    text: "Long session starts at 8 hours and approaching cap at 11. A clock found running past 12 hours is auto-stopped at the cap and should be reviewed as an estimate.",
  },
  "hub.exceptions": {
    label: "Hub exceptions",
    text: "Counts open recount, missing-price, and item requests, plus the Admin Review queue. A live In-Progress or On-Hold order is stale when no session activity is recorded, or its last activity was at least three days ago.",
  },
  "hub.billing-week": {
    label: "Hub billing periods",
    text: "Material and labor dollars use receipt billing for work orders completed in the current Central-time week. Average completion time and the daily sparkline use the trailing 14 Central days, so they do not share the dollar totals' date window.",
  },

  // --- Integrations (pages/integrations.html) ----------------------------
  "integrations.netfacilities": {
    label: "NetFacilities import and export",
    text: "Log in to NetFacilities opens a cloud sign-in window from any device. Export the work-order CSV there; Import downloaded CSV brings it in, then Import Tasks and Priority fills in Task/Symptom and Priority from the same session. Import from CSV still accepts any file you already have. For Client exports the billing sheet with totals and receipts, scoped by the dropdown beside it.",
  },
};
