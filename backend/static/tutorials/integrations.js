// Integrations page tutorials. Data only: the player is tutorial.js.

export const SCRIPTS = [
  {
    key: "integrations.netfacilities.import",
    title: "Import work orders",
    steps: [
      { target: "#wo-netfacilities-status", title: "Sign-in status",
        text: "Shows where the NetFacilities sign-in stands." },
      { target: "#wo-netfacilities-cloud-sign-in-btn", title: "Log in",
        text: ["Opens a cloud sign-in window from any device.",
          "Export the work-order CSV there, then Import downloaded CSV brings it in."] },
      { target: "#wo-netfacilities-enrich-btn", title: "Tasks and Priority",
        text: "Fills in Task/Symptom and Priority from the same session." },
      { target: "#wo-import-btn", title: "Import from CSV",
        text: "Import from CSV still takes any file you already have." },
    ],
  },
  {
    key: "integrations.netfacilities.export",
    title: "Export for the client",
    steps: [
      { target: "#wo-export-scope", title: "Which orders",
        text: "Picks which work orders go out, by status." },
      { target: "#wo-export-client-btn", title: "For Client",
        text: "For Client exports the billing sheet with totals and receipts, for the orders picked beside it." },
    ],
  },
];
