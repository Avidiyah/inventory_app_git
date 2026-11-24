// Starter tutorials: menu tours. Data only. Each wait step lights one real menu
// button and waits for the person's tap; the overview step then describes the
// page that opened. No sample data, no page of their own (docs spec 5).

const wait = (page, group, groupName, label, extra = {}) => ({
  waitTap: `.nav-btn[data-page="${page}"]`,
  // Phone/narrow mode (html.nav-mobile): the menu opens from #nav-title; group toggles are headings there.
  via: `html.nav-mobile #nav-title,[data-nav-group="${group}"] .nav-group-toggle`,
  viaText: `Tap here to open the ${groupName} menu.`,
  text: `Now tap ${label}.`,
  ...extra,
});
const look = (page, text) => ({ target: `#${page}-page`, text });

export const SCRIPTS = [
  {
    key: "starter.menu",
    title: "Using the menu",
    sample: false,
    minRole: "technician",
    steps: [
      {
        target: "#main-nav",
        text: ["This bar at the top is the menu.", "Each button opens one page of the app."],
        textFor: {
          supervisor: ["This bar at the top is the menu.", "The buttons are grouped under names like Inventory and Field."],
          techfm_oa: ["This bar at the top is the menu.", "The buttons are grouped under names like Inventory and Field."],
          admin: ["This bar at the top is the menu.", "The buttons are grouped under names like Inventory and Field."],
          owner: ["This bar at the top is the menu.", "The buttons are grouped under names like Inventory and Field."],
        },
      },
      wait("saved-items", "inventory", "Inventory", "Find Item", { text: "Tap Find Item to try it." }),
      { target: "#main-nav", text: "The button for the page you are on stays marked." },
      { target: "#auth-user-indicator", text: ["Your name takes you back to your Hub.", "Log Out is at the bottom of the Hub's Home tab."] },
    ],
  },
  {
    key: "starter.inventory",
    title: "Inventory",
    sample: false,
    minRole: "technician",
    steps: [
      wait("create-item", "inventory", "Inventory", "Add Item", { text: "Tap Add Item to begin." }),
      look("create-item", ["Add Item puts a new item or tool in the catalogue.", "You enter its name, barcode, location and price."]),
      wait("saved-items", "inventory", "Inventory", "Find Item", {
        textFor: { technician: "Tap Find Item to begin.", supervisor: "Tap Find Item to begin." },
      }),
      look("saved-items", [
        "Find Item searches the catalogue by name or barcode.",
        "Open an item to see its count and where it sits.",
        "Nothing shows until you search or tap Load All.",
      ]),
      wait("tools", "inventory", "Inventory", "Tools"),
      look("tools", [
        "Tools tracks who is holding each shop tool.",
        "Custody shows a person's tools; Inventory looks up one tool.",
        "Anyone can check a tool back in.",
      ]),
    ],
  },
  {
    key: "starter.field",
    title: "Field",
    sample: false,
    minRole: "technician",
    steps: [
      wait("transaction", "field", "Field", "Scan / Stock", { text: "Tap Scan / Stock to begin." }),
      look("transaction", [
        "Scan / Stock is where you scan material you use on a job.",
        "First pick the work order, then scan each item.",
        "Team Lead and above can also put stock back.",
      ]),
      wait("work-orders", "field", "Field", "Work Orders"),
      look("work-orders", [
        "Work Orders lists the jobs, each as a card coloured by its status.",
        "Tap a card to see its notes, materials and labor.",
        "Work orders are imported, so you cannot create one here.",
      ]),
      wait("mass-stage", "field", "Field", "Mass Stage"),
      look("mass-stage", [
        "Mass Stage plans loading a truck for several jobs at once.",
        "Each plan is for one community and building.",
        "Its load list shows what is planned, loaded and left.",
      ]),
    ],
  },
  {
    key: "starter.people",
    title: "People",
    sample: false,
    minRole: "supervisor",
    steps: [
      wait("saved-users", "people", "People", "Users", { text: "Tap Users to begin." }),
      look("saved-users", [
        "Users lists everyone who has an account.",
        "You can add a person or archive an account, for roles below yours.",
        "Archiving blocks sign-in but keeps their history.",
      ]),
    ],
  },
  {
    key: "starter.review",
    title: "Review",
    sample: false,
    minRole: "supervisor",
    steps: [
      wait("low-stock", "review", "Review", "Low Stock", { text: "Tap Low Stock to begin." }),
      look("low-stock", ["Low Stock lists the items that are running low.", "You can change the level where an item counts as low."]),
      wait("user-requests", "review", "Review", "User Requests"),
      look("user-requests", [
        "User Requests collects what crews ask the office for.",
        "That means material to stock, new items, recounts and missing prices.",
      ]),
      wait("admin-review", "review", "Review", "Admin Review"),
      look("admin-review", [
        "Admin Review is the last billing check on a finished job.",
        "From here a job is closed, or sent back to In-Progress.",
      ]),
      wait("history", "review", "Review", "History", { textFor: { supervisor: "Tap History to begin." } }),
      look("history", [
        "History lists every stock transaction.",
        "Filter it by work order number or by date.",
        "Pricing List makes a text list of priced rows to paste elsewhere.",
      ]),
    ],
  },
];
