// Work-order card tutorials. Data only: the player is tutorial.js.

const OPEN_CARD = 'details.wo-card[data-number="SAMPLE-1"] [data-peek-open]';

export const SCRIPTS = [
  {
    key: "work-orders.card.details",
    title: "Details",
    open: [OPEN_CARD],
    steps: [
      { target: "details.wo-solo > summary.wo-summary", title: "The card",
        text: ["One card per job.", "The colour is the status: yellow means In-Progress."] },
      { target: "#wo-sec-tabs", title: "Tabs",
        text: ["Everything about the job sits under these tabs.", "The numbers show how much is logged so far."] },
      { target: "#wo-sec-details .wo-details", title: "Details",
        text: "Where the job is, what was asked for, and who is on the crew." },
      { target: "#wo-act-start-tracking-wo", title: "Begin Charging",
        text: ["This starts your clock on this job and puts you on the crew.", "Tap Stop Charging when you stop."] },
      { target: ".wo-more-btn", title: "More", text: "Less common actions live behind this button." },
    ],
  },
  {
    key: "work-orders.card.notes",
    title: "Notes",
    here: '.wo-solo .wo-tab[data-wo-tab="notes"][aria-selected="true"]',
    open: [OPEN_CARD, '.wo-tab[data-wo-tab="notes"]'],
    steps: [
      { target: "#wo-sec-notes .wo-notes-log", title: "Notes", text: "Read what the last person left before you start." },
      { target: "#wo-notes-input", title: "Add your own", text: ["Write what you did and what is left.", "Then tap Save note."] },
    ],
  },
  {
    key: "work-orders.card.materials",
    title: "Materials",
    here: '.wo-solo .wo-tab[data-wo-tab="materials"][aria-selected="true"]',
    open: [OPEN_CARD, '.wo-tab[data-wo-tab="materials"]'],
    steps: [
      { target: "#wo-sec-materials .wo-items", title: "Materials", text: "Every item used on this job so far." },
      { target: "#wo-add-item", title: "Add an item",
        text: ["Search for the item by name or barcode.", "Then enter how many you used."] },
      { target: "#wo-mode-select", title: "New entries",
        text: ["Dispense takes the item out of stock.", "Retroactive records paper usage without touching stock."] },
    ],
  },
  {
    key: "work-orders.card.labor",
    title: "Labor",
    here: '.wo-solo .wo-tab[data-wo-tab="labor"][aria-selected="true"]',
    open: [OPEN_CARD, '.wo-tab[data-wo-tab="labor"]'],
    steps: [
      { target: "#wo-sec-labor .wo-labor-list", title: "Labor", text: "Hours charged to this job, person by person." },
      { target: "#wo-add-labor", title: "Add hours", text: "Key hours in by hand for anyone on the crew.",
        textFor: { technician: "Add or fix your own hours by hand this week." } },
    ],
  },
];
