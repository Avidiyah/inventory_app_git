// Tutorial registry: page name -> { scripts, sample }. Edited by the
// orchestrator only; each page's two files are data (see tutorial.js).
import { SCRIPTS as workOrders } from "./work-orders.js";
import { sample as workOrdersSample } from "./work-orders.sample.js";

export const TUTORIALS = {
  "work-orders": { scripts: workOrders, sample: workOrdersSample },
};
