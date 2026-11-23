// Find Item tutorials (batch 1: Find, Scan; batch 3: office parts). Data only: the player is tutorial.js.

const ID = "ffffffff-ffff-4fff-8fff-000000000011";
// Load All paints a skeleton at once; the Quantity cell exists only once real rows land, so the
// player waits for it. `#items-count` shows with the rows, so a loaded table skips that click.
const LOAD = ["#items-load-all-btn", '#items-tbody td[data-label="Quantity"]', "#items-count"];
const ROW_MENU = `[data-menu][data-id="${ID}"] .menu-trigger`;
const PICK = (value) => `[data-menu][data-id="${ID}"] [data-value="${value}"]`;
const SCAN_TAB = '.sub-nav-btn[data-feature="scan"]';
const SCAN_BOX = "#items-scan-section .scan-toolbar";

export const SCRIPTS = [
  {
    key: "saved-items.find.search",
    title: "Finding an item",
    here: '.sub-nav-btn[data-feature="find"].active',
    open: LOAD,
    steps: [
      { target: ".sub-nav", title: "Find and Scan",
        text: ["Find searches the catalogue.", "Scan looks an item up by its barcode."] },
      { target: "#items-search", title: "Search",
        text: ["Type a name or barcode, then tap Search.", "Nothing shows until you ask."] },
      { target: "#items-load-all-btn", title: "Load All",
        text: ["Load All Items lists everything.", "It is a button so a phone is not made to draw thousands of rows."] },
      { target: "#items-table", title: "The list",
        text: ["Each row is one item, with its location so someone can go get it.",
          "Price and product link show only for TechFM OA and above."] },
      { target: '#items-table td[data-label="Actions"]', title: "Row actions",
        text: "Edit, notes and Correct Count are office tasks and have their own tutorial." },
    ],
  },
  {
    key: "saved-items.scan.scan",
    title: "Scanning to find an item",
    here: '.sub-nav-btn[data-feature="scan"].active',
    open: [SCAN_TAB],
    steps: [
      { target: SCAN_BOX, title: "Scan",
        text: ["Scan Barcode starts the camera and Upload Photo reads a picture of a barcode.",
          "The item it matches is shown to you."] },
    ],
  },
  {
    key: "saved-items.find.edit-item",
    title: "Edit Item",
    minRole: "techfm_oa",
    here: "#item-editor-section:not([hidden])",
    open: ["#items-load-all-btn", ROW_MENU, PICK("edit")],
    steps: [
      { target: "#item-editor-selected", title: "Which item",
        text: ["Shows which item you are changing.", "Nothing changes until you tap Save Changes."] },
      { target: "#item-editor-barcode", title: "Barcode", text: "The label number workers scan." },
      { target: "#item-editor-location", title: "Location", text: "Where the item sits, as workers would describe it." },
      { target: "#item-editor-barcodes-rows", title: "Extra barcodes",
        text: ["Extra codes on the packaging that should scan to this same item.", "Use them when a vendor changes a label."] },
      { target: "#item-editor-price", title: "Price", text: "Material with no price cannot bill." },
      { target: "#item-editor-product-link", title: "Product link",
        text: ["Where it is bought.", "Price and link together close a missing-price request."] },
      { target: "#item-editor-save-btn", title: "Save", text: ["Saves the changes.", "Cancel leaves the item as it was."] },
    ],
  },
  {
    key: "saved-items.find.notes",
    title: "Item notes",
    minRole: "supervisor",
    here: "#notes-editor-section:not([hidden])",
    open: ["#items-load-all-btn", ROW_MENU, PICK("notes")],
    steps: [
      { target: "#notes-rows", title: "Notes",
        text: "Each note has a unique name and a stored type: text, number, or true/false." },
      { target: "#notes-add-row-btn", title: "Add a note",
        text: ["Adds another note row.", "Pick the right type so later displays and edits stay consistent."] },
      { target: "#notes-save-btn", title: "Save",
        text: ["Saves all the notes on this item.", "Cancel closes the editor without saving."] },
    ],
  },
  {
    key: "saved-items.find.correct-count",
    title: "Correct Count",
    minRole: "techfm_oa",
    here: "#correction-section:not([hidden])",
    open: ["#items-load-all-btn", ROW_MENU, PICK("correct")],
    steps: [
      { target: "#correction-section > h2", title: "When to use it",
        text: ["Use this when the shelf count is wrong, not to record usage.",
          "Taking material out for a job is a Take Out Stock transaction."] },
      { target: "#correction-current", title: "Current count", text: "The count the app holds now." },
      { target: "#correction-new-quantity", title: "New count",
        text: ["Type what is really on the shelf.", "The app records the difference as an adjustment that bills nothing."] },
      { target: "#correction-reason", title: "Reason",
        text: ["Required.", "It shows in Transaction History, so write what you would want to read six months from now."] },
      { target: "#correction-save-btn", title: "Save", text: "Saves the corrected count." },
    ],
  },
  {
    key: "saved-items.scan.add-barcode",
    title: "Add Barcode to an Item",
    minRole: "techfm_oa",
    here: '.sub-nav-btn[data-feature="scan"].active',
    open: [SCAN_TAB],
    steps: [
      { target: "#items-scan-section > h2", title: "Scan", text: "Scan a label to jump to its item." },
      { target: SCAN_BOX, title: "No match",
        text: ["If the scan finds nothing, an Add Barcode panel opens.",
          "Search the item by name and the scanned code is attached to it."] },
      { target: "#items-scan-add-barcode-hint", title: "When to use it",
        text: ["Use this when you know the item is in the catalogue.", "It saves creating a duplicate item."] },
    ],
  },
];
