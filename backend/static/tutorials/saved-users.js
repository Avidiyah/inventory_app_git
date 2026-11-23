// Users page tutorials. Data only: the player is tutorial.js.
// Page floor is Team Lead, equal to every script's audience, so no minRole.

const TECH = '.user-profile-btn[data-id="ffffffff-ffff-4fff-8fff-000000250001"]';
const MENU = "#users-tbody tr:not(.archived-user) .menu-trigger";
const ARCHIVED_ROW = "#users-tbody tr.archived-user";

export const SCRIPTS = [
  {
    key: "saved-users.users.list",
    title: "Finding a person",
    open: [],
    steps: [
      { target: "#users-search", title: "Search",
        text: "Type part of a name or username to narrow the list." },
      { target: "#users-scope", title: "Active, Archived, Needs a fix",
        text: ["Active, Archived, or Needs a fix.", "Archived people cannot sign in but keep their history."] },
      { target: "#users-table", title: "The list",
        text: ["One row per person with their role.", "A name that is a link opens that person's week."] },
      { target: ".users-fix-count", title: "Needs a fix",
        text: ["This flag means the person has days this week that need a fix.", "Tap the name to see which."] },
      { target: "#users-tbody .action-menu", title: "Actions",
        text: ["Edit details, reset a password or archive from the Actions menu, for people you outrank.",
          "Archiving blocks sign-in but keeps their history."] },
    ],
  },
  {
    key: "saved-users.users.week",
    title: "A person's week",
    here: "#user-profile:not([hidden]) .user-profile",
    open: [TECH, ".user-profile-day > .user-profile-summary"],
    steps: [
      { target: ".user-profile-header", title: "Who",
        text: ["The person's name and role.", "Everything below is one week."] },
      { target: ".user-profile-toolbar", title: "Weeks",
        text: ["The arrows move between weeks.", "Back to users returns to the list."] },
      { target: ".user-profile-totals", title: "Week totals",
        text: ["Paid, charged to work orders, not charged, and work orders completed.",
          "Days marked with a warning need review and are left out."] },
      { target: ".user-profile-day", title: "Days",
        text: ["Each day shows a band (under 8h, 8–10h, over 10h) and how much paid time was charged.",
          "Tap a day to open it."] },
      { target: ".user-profile-day .hub-hours-edit", title: "Fix a punch",
        text: ["Under Punches, Edit fixes a punch's start or end time.", "+ Add punch records a missed one."] },
      { target: ".user-profile-wo-card", title: "Work orders",
        text: ["Work orders completed that day.", "Tap one to open its card."] },
      { target: ".day-tl-tag", title: "Tags",
        text: "Tags such as Self-edited show who changed a punch or entered hours: the person or an Admin." },
    ],
  },
  {
    key: "saved-users.add",
    title: "Add a user",
    here: "#users-add[open]",
    // The second selector is a field inside the form: the click is made only while it is hidden.
    open: ["#users-add > summary", "#user-first-name"],
    steps: [
      { target: "#users-add > summary", title: "Add user", text: "Tap + Add user to open the new-user form." },
      { target: "#user-first-name", title: "Name", text: "Type their first and last name." },
      { target: "#username", title: "Username", text: "Pick the username they will sign in with." },
      { target: "#user-role", title: "Role",
        text: ["Choose their role.", "You can only create roles below your own."],
        textFor: {
          owner: "Choose Admin, TechFM OA, Team Lead or Technician.",
          admin: "Choose TechFM OA, Team Lead or Technician.",
          techfm_oa: "Choose Team Lead or Technician.",
          supervisor: "You can only create Technicians.",
        } },
      { target: 'label[for="user-role"] .tip-btn', title: "Role help",
        text: "Tap the ? beside Role to see what each role can do." },
      { target: "#user-password", title: "Password", text: "Give them a first password of at least 4 characters." },
      { target: "#create-user-btn", title: "Create", text: "Tap Add User to create the account." },
    ],
  },
  {
    key: "saved-users.actions",
    title: "Reset or archive",
    // Back from a profile if one is showing; the table is the tab this script lives on.
    open: ["?.user-profile-back", "#users-table"],
    steps: [
      { target: "#users-scope", title: "Active and Archived",
        text: ["Active shows people who can sign in.", "Archived shows people who cannot."] },
      { target: MENU, title: "Actions menu",
        text: ["Each row has an Actions menu.", "It lists only what you may do to that person: you must outrank them."] },
      { target: MENU, title: "Edit Role",
        text: ["Edit Role changes someone's role.", "You can only pick roles below your own."],
        textFor: { supervisor: ["A Team Lead's menu has no Edit Role.",
          "Ask a TechFM OA or above to change someone's role."] } },
      { target: MENU, title: "Reset Password", text: "Reset Password sets a new password for someone you outrank." },
      { target: MENU, title: "Archive",
        text: ["Archive stops a person signing in but keeps their history.",
          "Anyone holding tools must return them first, or the confirmation can check them all in."] },
    ],
  },
  {
    key: "saved-users.restore",
    title: "Restore",
    here: '#users-scope [data-scope="archived"][aria-pressed="true"]',
    open: ['#users-scope [data-scope="archived"]'],
    steps: [
      { target: ARCHIVED_ROW, title: "Archived",
        text: "Archived people are marked (archived) and cannot sign in." },
      { target: ARCHIVED_ROW + " .menu-trigger", title: "Restore",
        text: "Restore brings an archived person back, with their history intact." },
    ],
  },
];
