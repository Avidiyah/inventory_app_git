// User Requests tutorials, one per tab. Data only: the player is tutorial.js.
// Every tab shows all four sample cards (the page does not filter the list on
// the client), so each script lights its own card by id.

const P = "ffffffff-ffff-4fff-8fff-";
const card = (n) => `#ureq-card-${P}0000000000${n}`;
const tab = (type) => `#user-requests-tabs [data-request-type="${type}"]`;
const here = (type) => `${tab(type)}[aria-selected="true"]`;

export const SCRIPTS = [
  {
    key: "user-requests.requests.material",
    title: "Material requests",
    here: here("material_request"),
    open: [tab("material_request")],
    steps: [
      { target: "#user-requests-tabs", title: "Tabs",
        text: ["Four kinds of request, one tab each.", "The number is how many are open."] },
      { target: "#user-requests-status", title: "Status",
        text: ["Open is what needs you.", "Stocked and Resolved are the past."] },
      { target: `${card(41)} .user-request-details`, title: "The request",
        text: ["A crew asked staff to stock this item.", "It shows the work order, how many, and what is on hand now."] },
      { target: `${card(41)} .user-request-stock`, title: "Mark stocked",
        text: ["Use this when the shelf really has the item but the count says otherwise.",
          "It notifies the crew without recording a stock transaction."] },
      { target: `${card(41)} .user-request-action`, title: "Mark resolved",
        text: ["Mark resolved closes the request.", "It does not change stock."] },
      { target: `${card(41)} .user-request-edit-open`, title: "Edit", text: "Edit fixes the request's details." },
    ],
  },
  {
    key: "user-requests.requests.catalogue",
    title: "Catalogue requests",
    here: here("catalogue_request"),
    open: [tab("catalogue_request")],
    steps: [
      { target: `${card(42)} .user-request-details`, title: "The request",
        text: ["Someone reported material that has no catalogue row.",
          "It shows what was searched, how many, and the work order."] },
      { target: `${card(42)} .user-request-fulfill-open`, title: "Fulfil",
        text: ["Fulfil adds the item and logs it retroactively on its work order.",
          "Matching requests start checked so one fix can close them together."] },
      { target: `${card(42)} .user-request-close-open`, title: "Close without fulfilling",
        text: ["Close without fulfilling needs a reason.", "You can reopen it from Resolved."] },
      { target: `${card(42)} .user-request-edit-open`, title: "Edit", text: "Edit fixes the request's details." },
    ],
  },
  {
    key: "user-requests.requests.recount",
    title: "Stock recounts",
    here: here("inventory_recount"),
    open: [tab("inventory_recount")],
    steps: [
      { target: `${card(43)} .user-request-details`, title: "The recount",
        text: ["A dispense came up short.", "It shows the count before, what was dispensed, and the shortage."] },
      { target: `${card(43)} .user-request-count-input`, title: "Your count", text: "Type the count you found on the shelf." },
      { target: `${card(43)} .user-request-count-reason`, title: "Reason",
        text: "Saving writes an inventory adjustment with this reason." },
      { target: `${card(43)} .user-request-action`, title: "Mark resolved",
        text: ["Mark resolved only closes the request.", "It does not change stock."] },
    ],
  },
  {
    key: "user-requests.requests.price",
    title: "Missing price / link",
    here: here("missing_item_price"),
    open: [tab("missing_item_price")],
    steps: [
      { target: `${card(44)} .user-request-details`, title: "The request",
        text: ["Material was used on a work order with no price.", "Unpriced material cannot bill."] },
      { target: `${card(44)} .user-request-price-input`, title: "Price", text: "Enter the price." },
      { target: `${card(44)} .user-request-link-input`, title: "Product link",
        text: ["Enter where it is bought.", "The request stays open until both a price and a link exist."] },
      { target: `${card(44)} .user-request-price-save`, title: "Save", text: "Saves both and closes the request." },
      { target: `${card(44)} .user-request-action`, title: "Remove", text: "Remove closes it without pricing." },
    ],
  },
];
