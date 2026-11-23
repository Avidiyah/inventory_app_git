// History tutorials. Data only: the player is tutorial.js.

const TABS = "#history-tabs";

export const SCRIPTS = [
  {
    key: "history.log.all",
    title: "All Transactions",
    here: `${TABS} .sub-nav-btn[data-feature="all"].active`,
    steps: [
      { target: "#history-wo-row", title: "Work order filter",
        text: ["Type a work order number to see only its transactions; archived work orders still match.",
          "If it names an archived one, you are offered a restore."] },
      { target: "#history-date-row", title: "Date range",
        text: ["Pick From and To dates, or leave one blank for an open range.", "The To date counts in full."] },
      { target: TABS, title: "Three views",
        text: ["Switch between all transactions, one item, or one user.", "The filters above apply in every view."] },
      { target: "#history-table", title: "The table",
        text: ["Newest first.",
          "Type says added, taken out or correction, and WO / Reason shows the work order or the correction reason."] },
      { target: "#history-table thead .admin-col", title: "Charge",
        text: ["Charge shows the base value and the marked-up value.",
          "A work-order row shows a dash, because it bills through its work-order line."] },
      { target: ".void-txn-btn", title: "Void",
        text: ["Void undoes a mistaken transaction: it reverses the effect on the on-hand count and removes the row from history.",
          "You confirm first."] },
      { target: "#history-pricing-btn", title: "Pricing list",
        text: ["Pricing list builds a plain-text list of every priced row matching your filters, with a total.",
          "It fits the client's 41-character box, so paste it as-is."] },
      { target: "#history-pagination", title: "Pages",
        text: ["Ten rows to a page.", "Prev and Next move through the matches."] },
    ],
  },
  {
    key: "history.log.by-item",
    title: "By Item",
    here: `${TABS} .sub-nav-btn[data-feature="item"].active`,
    open: [`${TABS} [data-feature="item"]`],
    steps: [
      { target: "#history-item-search", title: "Pick an item",
        text: "Search by name or barcode, then pick the item to list its transactions." },
      { target: "#history-wo-row", title: "Same filters", text: "The work order and date filters apply here too." },
    ],
  },
  {
    key: "history.log.by-user",
    title: "By User",
    here: `${TABS} .sub-nav-btn[data-feature="user"].active`,
    open: [`${TABS} [data-feature="user"]`],
    steps: [
      { target: "#history-user-select", title: "Pick a person",
        text: ["Pick a person to list their transactions.", "Archived users can still be picked."] },
      { target: "#history-date-row", title: "Same filters", text: "The work order and date filters apply here too." },
    ],
  },
];
