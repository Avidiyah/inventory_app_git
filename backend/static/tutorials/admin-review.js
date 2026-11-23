// Admin Review tutorial. Data only: the player is tutorial.js.

const CARD = "#review-card-ffffffff-ffff-4fff-8fff-000000000061";

export const SCRIPTS = [
  {
    key: "admin-review.queue.review",
    title: "Billing review",
    here: "#admin-review-receipt-section:not([hidden])",
    open: [CARD],
    steps: [
      { target: "#admin-review-list", title: "The queue",
        text: ["Work orders waiting for final billing review.", "A tile that says Needs price has unpriced material."] },
      { target: CARD, title: "A tile", text: "Tap a tile to build its receipt." },
      { target: "#admin-review-receipt-output", title: "The receipt",
        text: ["The billing document, laid out for the client's 41-character text box.",
          "Copy it out as-is; changing the spacing breaks it at the other end."] },
      { target: "#admin-review-netfacilities-btn", title: "NetFacilities",
        text: "Opens NetFacilities so you can paste the receipt in." },
      { target: "#admin-review-reopen-btn", title: "Return to In-Progress",
        text: "Return to In-Progress sends the order back for corrections and keeps it live." },
      { target: "#admin-review-close-btn", title: "Close",
        text: ["Close finishes it.", "A closed work order leaves the active lists."] },
    ],
  },
];
