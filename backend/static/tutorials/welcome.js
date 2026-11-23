// The one-time welcome tour. Data only; standalone (no page, no sample).
// Step 1 is targetless (a centred box): the user's four sentences, one per tap.
// Step 2 waits for the person's own tap on the Hub's Tutorials tab (on a phone
// it lights the section picker first); the steps after it run on that tab.
// views/welcome.js decides when it is due and what follows.

export const SCRIPTS = [
  {
    key: "welcome",
    title: "Welcome",
    minRole: "technician",
    steps: [
      {
        title: "Welcome",
        text: [
          "Welcome to TechFM.",
          "TechFM is Technological Facilities Maintenance: our app for work orders, stock, tools and time.",
          "Each page has its own tutorial available at the top of the page.",
          "They are also in the Tutorials section, which we're about to navigate to first.",
        ],
      },
      {
        waitTap: "#hub-tab-tutorials",
        via: "#hub-picker-toggle",
        viaText: "Tap here to open the list of sections.",
        title: "Tutorials",
        text: "Tap Tutorials, where everything that teaches you the app is kept.",
      },
      {
        target: '[data-tut-sub="todo"]',
        title: "Your to-do list",
        text: ["Tutorials you have not finished are listed under To do.", "Tap one to start it."],
      },
      {
        target: '[data-tut-sub="completed"]',
        title: "Completed",
        text: ["Finished ones move to Completed.", "You can run them again any time."],
      },
      {
        target: "#user-hub-page .tut-btn",
        title: "On every page",
        text: ["Each page has this button by its title.", "It explains the page you are on."],
      },
    ],
  },
];
