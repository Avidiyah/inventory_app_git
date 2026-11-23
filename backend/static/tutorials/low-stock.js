// Low Stock tutorial. Data only: the player is tutorial.js.

const CARD = "#low-stock-card-ffffffff-ffff-4fff-8fff-000000000051";

export const SCRIPTS = [
  {
    key: "low-stock.queue.reorder",
    title: "Reorder queue",
    open: [`${CARD} summary`],
    here: `${CARD}[open]`,    steps: [
      { target: "#low-stock-section > h2", title: "The queue",
        text: "Every item at or below its alert threshold, deepest below first." },
      { target: "#low-stock-tabs", title: "Tabs",
        text: "Tabs sort the queue by how recently each item moved, so what is both low and moving comes first." },
      { target: `${CARD} .low-stock-summary`, title: "The card",
        text: "What it is, how much is left, and how much was used in the last 7 days, including retroactive material." },
      { target: `${CARD} .low-stock-threshold`, title: "Warn at",
        text: ["Raise Warn at to be warned earlier.", "It takes effect on the next count that crosses it."] },
      { target: `${CARD} .low-stock-edit`, title: "Edit the item",
        text: "Fix the name, location, price, link, or extra barcodes here, then Save item." },
      { target: `${CARD} .low-stock-correction`, title: "Correct the count",
        text: ["Use this when the shelf count is wrong.", "The reason is required and is kept with the adjustment."] },
    ],
  },
];
