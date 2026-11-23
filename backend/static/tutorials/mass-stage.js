// Mass Stage tutorials. Data only: the player is tutorial.js.

const MAPLE = '.community-group[data-community="Maple Court"] > .community-summary';
const CEDAR = '.community-group[data-community="Cedar Row"] > .community-summary';
const STAGE_1 = '.stage-card[data-stage-id="ffffffff-ffff-4fff-8fff-000000230001"]';
const STAGE_2 = '.stage-card[data-stage-id="ffffffff-ffff-4fff-8fff-000000230002"]';
const STAGE_3 = '.stage-card[data-stage-id="ffffffff-ffff-4fff-8fff-000000230003"]';
const ROOM = '.room-card[data-slot-id="ffffffff-ffff-4fff-8fff-000000230004"] > .room-summary';

export const SCRIPTS = [
  {
    key: "mass-stage.stage.new",
    title: "New stage",
    open: [],
    steps: [
      { target: "#mass-stage-create-section", title: "New stage",
        text: ["A stage plans truck loading around work orders that are already imported.",
          "It cannot create a work order."] },
      { target: "#mass-stage-community-select", title: "Community",
        text: "Pick the community, or add a new one, then enter the building number." },
      { target: "#mass-stage-create-btn", title: "Create",
        text: ["Create starts the stage.",
          "Only one active stage exists for each community and building."] },
      { target: "#mass-stage-list .community-summary", title: "Communities",
        text: ["Stages are grouped by community, then building.",
          "A Team Lead sees their own; TechFM OA and above see everyone's."] },
    ],
  },
  {
    key: "mass-stage.stage.plan",
    title: "Planning",
    here: ".stage-card[open] .ms-add-room",
    // The room summary is listed twice: the player skips the last open click once the
    // first step is visible, and the stage summary is visible as soon as the stage opens.
    open: [MAPLE, `${STAGE_1} > .stage-summary`, ROOM, ROOM],
    steps: [
      { target: ".stage-card[open] > .stage-summary", title: "Status",
        text: ["Each building shows its status: planning, loading or completed.",
          "The count shows units and items."] },
      { target: ".ms-add-room", title: "Add a work order",
        text: ["Type an imported work order number, an optional unit number and who is assigned, then tap Add work order.",
          "A number that was not imported is refused."] },
      { target: ".room-summary", title: "Units",
        text: ["Each unit is one work order.", "Open work order jumps to its card."] },
      { target: ".ms-add-item", title: "Add an item",
        text: "Search an item by name or barcode, enter the planned quantity and tap Add." },
      { target: '[data-action="save-stage"]', title: "Save",
        text: "Save Mass Stage moves the stage to loading and locks the plan." },
    ],
  },
  {
    key: "mass-stage.stage.load",
    title: "Load list",
    here: ".stage-card[open] .ms-merged-actions",
    open: [MAPLE, `${STAGE_2} > .stage-summary`],
    steps: [
      { target: `${STAGE_2} .ms-merged`, title: "Load list",
        text: ["The load list merges the same item across every unit.",
          "Planned is the requested total, Loaded is what is staged, Remaining is what is left to load."] },
      { target: `${STAGE_2} .ms-merged-actions`, title: "Staged and Return",
        text: ["Staged records what you loaded, which takes it out of stock.",
          "Return puts unused staged stock back into inventory."] },
      { target: `${STAGE_2} .ms-short`, title: "Short by",
        text: "Short by means the shelf holds fewer than the plan calls for." },
      { target: `${STAGE_2} .ms-rooms`, title: "Units",
        text: ["Units lists each work order in the stage.", "Open work order jumps to its card."] },
      { target: `${STAGE_2} [data-action="complete-stage"]`, title: "Mark Completed",
        text: "Mark Completed ends the stage and makes it read-only." },
      { target: `${STAGE_2} [data-action="delete-stage"]`, title: "Delete",
        text: ["Delete removes the stage.", "Items already loaded stay dispensed."] },
    ],
  },
  {
    key: "mass-stage.stage.again",
    title: "Stage Again",
    here: '.stage-card[open] [data-action="reuse-stage"]',
    open: [CEDAR, `${STAGE_3} > .stage-summary`],
    steps: [
      { target: ".ms-merged-stats-ro", title: "Read-only",
        text: ["A completed stage is read-only.", "Each item shows what was returned and consumed."] },
      { target: '[data-action="reuse-stage"]', title: "Stage again",
        text: ["Stage again starts a fresh stage for the same community and building.",
          "Its item lists start empty; nothing is copied."] },
    ],
  },
];
