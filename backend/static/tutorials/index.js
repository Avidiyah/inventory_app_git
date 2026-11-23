// Tutorial registry: page name -> { scripts, sample }. Edited by the
// orchestrator only; each page's two files are data (see tutorial.js).
import { SCRIPTS as workOrders } from "./work-orders.js";
import { sample as workOrdersSample } from "./work-orders.sample.js";
import { SCRIPTS as transaction } from "./transaction.js";
import { sample as transactionSample } from "./transaction.sample.js";
import { SCRIPTS as userHub } from "./user-hub.js";
import { sample as userHubSample } from "./user-hub.sample.js";
import { SCRIPTS as tools } from "./tools.js";
import { sample as toolsSample } from "./tools.sample.js";
import { SCRIPTS as savedItems } from "./saved-items.js";
import { sample as savedItemsSample } from "./saved-items.sample.js";
import { SCRIPTS as massStage } from "./mass-stage.js";
import { sample as massStageSample } from "./mass-stage.sample.js";
import { SCRIPTS as history } from "./history.js";
import { sample as historySample } from "./history.sample.js";
import { SCRIPTS as savedUsers } from "./saved-users.js";
import { sample as savedUsersSample } from "./saved-users.sample.js";
import { SCRIPTS as userRequests } from "./user-requests.js";
import { sample as userRequestsSample } from "./user-requests.sample.js";
import { SCRIPTS as createItem } from "./create-item.js";
import { sample as createItemSample } from "./create-item.sample.js";
import { SCRIPTS as lowStock } from "./low-stock.js";
import { sample as lowStockSample } from "./low-stock.sample.js";
import { SCRIPTS as adminReview } from "./admin-review.js";
import { sample as adminReviewSample } from "./admin-review.sample.js";
import { SCRIPTS as starter } from "./starter.js";
import { SCRIPTS as integrations } from "./integrations.js";
import { sample as integrationsSample } from "./integrations.sample.js";

export const TUTORIALS = {
  "work-orders": { scripts: workOrders, sample: workOrdersSample },
  "transaction": { scripts: transaction, sample: transactionSample },
  "user-hub": { scripts: userHub, sample: userHubSample },
  "tools": { scripts: tools, sample: toolsSample },
  "saved-items": { scripts: savedItems, sample: savedItemsSample },
  "mass-stage": { scripts: massStage, sample: massStageSample },
  "history": { scripts: history, sample: historySample },
  "saved-users": { scripts: savedUsers, sample: savedUsersSample },
  "user-requests": { scripts: userRequests, sample: userRequestsSample },
  "create-item": { scripts: createItem, sample: createItemSample },
  "low-stock": { scripts: lowStock, sample: lowStockSample },
  "admin-review": { scripts: adminReview, sample: adminReviewSample },
  "integrations": { scripts: integrations, sample: integrationsSample },
  "starter": { scripts: starter },
};
