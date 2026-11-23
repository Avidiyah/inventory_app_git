// Tools page tutorials (batch 1 check-in, batch 3 lookup and checkout). Data only: the player is tutorial.js.

const P = "ffffffff-ffff-4fff-8fff-";

export const SCRIPTS = [
  {
    key: "tools.custody.checkin",
    title: "Checking a tool in",
    here: '.sub-nav-btn[data-feature="custody"].active',
    // Technician and Team Lead are pinned to their own card, so the first two
    // clicks are optional. The last entry only stops the player from treating
    // the already-visible tabs as "card shown" before the person is picked.
    open: [
      "?#tool-user-picker:not([hidden]) #tool-user-search",
      `?.tool-user-option[data-user-id="${P}000000000041"]`,
      "?#tool-user-card:not([hidden])",
    ],
    steps: [
      { target: ".sub-nav", title: "Tabs",
        text: ["Custody shows what a person is holding.", "Inventory and Scan are the other tabs."] },
      { target: "#tool-user-picker", title: "Pick a person", text: "Search for a person to see the tools they hold." },
      { target: "#tool-user-card", title: "The person", text: "Name, role and how many tool records this person has out." },
      { target: "#tool-user-holdings", title: "Holdings", text: "Each row is a tool, with its barcode and the quantity out." },
      { target: ".tool-checkin-btn", title: "Check In",
        text: ["Check In opens a short form.", "The amount starts at what is still out, and the work order is optional."] },
      { target: "#tool-checkout-controls", title: "Check out",
        text: "TechFM OA and above can also check a tool out to this person, by search or scan." },
    ],
  },
  {
    key: "tools.inventory.lookup",
    title: "Tool Inventory",
    here: '.sub-nav-btn[data-feature="inventory"].active',
    open: ['.sub-nav-btn[data-feature="inventory"]'],
    steps: [
      { target: "#tools-search", title: "Search", text: "Find a tool by name or barcode." },
      { target: "#tools-table", title: "The list",
        text: ["On Hand is what is on the shelf.", "Checked Out names who holds the rest."] },
      { target: `[data-menu][data-id="${P}000000000071"]`, title: "Actions",
        text: ["Edit changes the name or barcode.", "Correct Count fixes a miscount or adds units to a bulk tool, with a reason.",
          "Archive frees the barcode."] },
    ],
  },
  {
    key: "tools.custody.checkout",
    title: "Check out a tool",
    minRole: "techfm_oa",
    here: "#tool-checkout-section:not([hidden])",
    // The last entry is the checkout form itself, for the same reason as above.
    open: [
      '.sub-nav-btn[data-feature="custody"]',
      "#tool-user-search",
      `.tool-user-option[data-user-id="${P}000000000021"]`,
      "#tool-checkout-search",
      `[data-checkout-tool-id="${P}000000000071"]`,
      "#tool-checkout-section:not([hidden])",
    ],
    steps: [
      { target: "#tool-user-picker", title: "The person", text: ["Pick the person first.", "Their card shows what they hold."] },
      { target: "#tool-checkout-controls", title: "Find the tool", text: "Search by tool name or barcode, or scan the tool label." },
      { target: "#tool-checkout-quantity", title: "Quantity", text: "How many are going out." },
      { target: "#tool-checkout-work-order", title: "Work order",
        text: ["Optional.", "It records which job the tool went out on; leave it blank for general shop use."] },
      { target: "#tool-checkout-save-btn", title: "Check Out", text: "Check Out records it against that person." },
    ],
  },
];
