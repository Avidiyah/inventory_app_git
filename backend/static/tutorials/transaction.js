// Transaction (scan-and-go) tutorials. Data only: the player is tutorial.js.

export const SCRIPTS = [
  {
    key: "transaction.scan.pick",
    title: "Picking a work order",
    here: "#wo-gate-cards-section:not([hidden])",
    steps: [
      { target: "#wo-gate h2", title: "Pick a job",
        text: ["Pick the job you are scanning for.", "Only imported work orders appear; nothing typed here creates one."] },
      { target: "#wo-gate-search-card", title: "Search", text: "Type a work order number to filter the cards." },
      { target: "#wo-gate-cards .wo-card", title: "Start a batch",
        text: "Tap a card to start a scanning batch on that job.",
        textFor: { technician: ["These are the jobs assigned to you.", "Tap one to start scanning."] } },
    ],
  },
  {
    key: "transaction.scan.scanning",
    title: "Scanning items",
    here: "#scango-active:not([hidden])",
    open: ['#wo-gate-cards .wo-card[data-wo-id="ffffffff-ffff-4fff-8fff-000000000011"]'],
    steps: [
      { target: "#scango-wo-bar", title: "Your job",
        text: ["Your scans go to this job.", "Tap Change work order to pick another."] },
      { target: "#scango-direction-fixed", title: "Taking out stock",
        text: "Everything you scan is taken out of stock and charged to this job." },
      { target: "#scango-advanced-toggle", title: "Stock options",
        text: "Reveals Add Stock and Take Out Stock, and browsing all items in manual entry." },
      { target: "#scango-quantity", title: "Quantity",
        text: ["Set the quantity before you scan.", "The default is 1."] },
      { target: "#txn-scan-section .scan-toolbar", title: "Scan",
        text: ["Scan Barcode starts the camera and Upload Photo reads a picture.",
          "Each scan is saved to the work order automatically."] },
      { target: "#scango-quickmode-toggle", title: "Quick mode",
        text: ["Quick mode saves a take-out scan at once, with no confirm box.",
          "Team Lead and above get an Undo on each logged line."],
        textFor: { technician: "Quick mode saves a take-out scan at once, with no confirm box." } },
      { target: "#txn-manual-section", title: "Manual entry",
        text: ["When a scan will not read, search by name or barcode here.", "It saves the same way a scan does."] },
    ],
  },
];
