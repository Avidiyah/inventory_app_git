// View: Work Orders page — public surface.
//
// The implementation lives in workOrderList.js and its siblings. This file is
// the name the other nine views import, and it exists so that split can happen
// without touching any of them. Siblings that need the list must import
// workOrderList.js directly: importing this barrel from inside the group would
// create a cycle.

// Registers the card's delegated listeners as a side effect. Not optional:
// without it every button on a work-order card is inert.
import "./workOrderActions.js";

export {
  loadWorkOrders,
  focusWorkOrder,
  loadIntegrationsPage,
  mountWorkOrderList,
  openWorkOrdersByNumberSearch,
  openWorkOrdersFilteredByStatus,
  openWorkOrdersFilteredByDistribution,
} from "./workOrderList.js";
export { workOrderCardClass } from "./workOrderPresenters.js";
export { comboHtml } from "./workOrderCardHtml.js";
export { focusWorkOrderNumber, soloNumberFromPath } from "./workOrderRouting.js";
