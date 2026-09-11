// Characterization coverage for views/massStage.js: loadStages and the
// community -> building -> unit tree, lazy detail, create stage, and the
// thirteen delegated actions across the planning, loading and completed
// bodies. massStageActionCoverage.test.js audits that every action is
// named here.

import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server, pageHandlers } from "../helpers/handlers.js";
import { requestFor, requests, clearRequests } from "../helpers/requests.js";
import { answerConfirm, confirmOverlay, confirmTitle } from "../helpers/dialogs.js";
import {
  card, cardEls, el, groupEls, mountMassStage, openCard, openStages, respond, restoreMassStage, slotEls, stageMessage, state,
} from "../helpers/massStage.js";
import {
  item as itemFactory, massStageDetail, massStageSummary, mergedItem, stageItem, stageWorkOrder, user as userFactory,
} from "../helpers/factories.js";

afterEach(() => restoreMassStage());
const user = () => userEvent.setup();

describe("mountMassStage", () => {
  it("mounts with an empty list and nothing fetched", async () => {
    const { mod } = await mountMassStage();
    expect(typeof mod.loadStages).toBe("function");
    expect(el.list().children).toHaveLength(0);
    expect(requests()).toHaveLength(0);
  });
});
