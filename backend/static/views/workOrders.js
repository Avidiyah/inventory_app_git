// View: Work Orders page — public surface.
//
// The implementation lives in workOrderList.js and its siblings. This file is
// the name the other nine views import, and it exists so that split can happen
// without touching any of them. Siblings that need the list must import
// workOrderList.js directly: importing this barrel from inside the group would
// create a cycle.
export {
  loadWorkOrders,
  focusWorkOrder,
  focusWorkOrderNumber,
  soloNumberFromPath,
  workOrderCardClass,
  comboHtml,
  loadIntegrationsPage,
  mountWorkOrderList,
  openWorkOrdersByNumberSearch,
  openWorkOrdersFilteredByStatus,
  openWorkOrdersFilteredByDistribution,
} from "./workOrderList.js";
