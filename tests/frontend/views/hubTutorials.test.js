import { afterEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { el, openHub, restoreHub, stopClock } from "../helpers/hub.js";
import { requests } from "../helpers/requests.js";

afterEach(() => {
  stopClock();
  restoreHub();
  vi.doUnmock("../../../backend/static/tutorials/index.js");
  vi.doUnmock("../../../backend/static/tutorial.js");
});

const FIXTURE = {
  "work-orders": { scripts: [
    { key: "work-orders.a", title: "Notes", steps: [] },
    { key: "work-orders.b", title: "Materials", minRole: "supervisor", steps: [] },
  ] },
  history: { scripts: [{ key: "history.a", title: "Filters", steps: [] }] },
  "admin-review": { scripts: [{ key: "admin-review.a", title: "Review", steps: [] }] },
};
const putProgress = () => http.put("/tutorials/progress/:key", () => HttpResponse.json({}));

async function open(role = "technician") {
  vi.doMock("../../../backend/static/tutorials/index.js", () => ({ TUTORIALS: FIXTURE }));
  const startTutorial = vi.fn();
  vi.doMock("../../../backend/static/tutorial.js", async (orig) => ({ ...(await orig()), startTutorial }));
  const app = await openHub({ role, handlers: [putProgress()] });
  const tp = await import("../../../backend/static/tutorialProgress.js");
  tp.clearProgress();
  return { ...app, tp, startTutorial };
}
const show = async (tab = "tutorials") => {
  el.tab(tab).click();
  await vi.advanceTimersByTimeAsync(10);
};
const panel = () => el.panel("tutorials");
const sub = (id) => panel().querySelector(`[data-tut-sub="${id}"]`);
const entries = () => [...panel().querySelectorAll(".hub-tut-entry")];

describe("Hub Tutorials tab", () => {
  it.each(["technician", "supervisor", "techfm_oa", "admin", "owner"])(
    "shows for %s and the picker reads Tutorials", async (role) => {
      await open(role);
      expect(el.tab("tutorials").hidden).toBe(false);
      await show();
      expect(el.panel("tutorials").hidden).toBe(false);
      expect(document.getElementById("hub-picker-label").textContent).toBe("Tutorials");
    });

  it("To do groups by page with audience labels; counts equal list lengths", async () => {
    await open("supervisor");
    await show();
    expect(sub("todo").textContent).toBe("To do (3)");
    expect(sub("completed").textContent).toBe("Completed (0)");
    expect(entries()).toHaveLength(3);
    const groups = [...panel().querySelectorAll(".hub-tut-page")].map((g) => g.textContent);
    expect(groups).toEqual(["Work Orders", "History"]);
    const wo = panel().querySelector('[data-tut-key="work-orders.b"]');
    expect(wo.textContent).toContain("Team Lead and above");
    expect(panel().querySelector('[data-tut-key="work-orders.a"]').textContent).toContain("Everyone");
  });

  it("pages the role cannot open never appear", async () => {
    await open("technician");
    await show();
    expect(entries().map((e) => e.dataset.tutKey)).toEqual(["work-orders.a"]);
  });

  it("seen-not-finished says Started; finished moves to Completed with Replay", async () => {
    const { tp } = await open();
    await show();
    tp.mark("work-orders.a", "seen");
    expect(entries()[0].textContent).toContain("Started");
    tp.mark("work-orders.a", "completed");
    expect(panel().textContent).toContain("You have finished every tutorial.");
    sub("completed").click();
    expect(entries()).toHaveLength(1);
    expect(entries()[0].textContent).toContain("Replay");
    expect(sub("todo").textContent).toBe("To do (0)");
    expect(sub("completed").textContent).toBe("Completed (1)");
  });

  it("empty Completed reads Nothing finished yet.", async () => {
    await open();
    await show();
    sub("completed").click();
    expect(panel().textContent).toContain("Nothing finished yet.");
  });

  it("a tap opens the page then plays that script; replay sends no PUT", async () => {
    const { tp, startTutorial } = await open();
    tp.mark("work-orders.a", "completed");
    await show();
    sub("completed").click();
    const before = requests().filter((r) => r.method === "PUT").length;
    entries()[0].click();
    expect(startTutorial).toHaveBeenCalledWith("work-orders", "work-orders.a");
    expect(document.getElementById("work-orders-page").classList.contains("active")).toBe(true);
    expect(requests().filter((r) => r.method === "PUT")).toHaveLength(before);
  });

  it("each entry is one button, none nested", async () => {
    await open("supervisor");
    await show();
    for (const e of entries()) {
      expect(e.tagName).toBe("BUTTON");
      expect(e.querySelector("button")).toBeNull();
    }
  });

  it("the open panel repaints on a progress change", async () => {
    const { tp } = await open();
    await show();
    expect(entries()).toHaveLength(1);
    tp.mark("work-orders.a", "completed");
    expect(entries()).toHaveLength(0);
  });
});

describe("Tutorials tab red dot", () => {
  const dotted = () => el.tab("tutorials").classList.contains("hub-tab-dot");
  const LABEL = "Tutorials, you have not finished them all yet";

  it("shows while any relevant script is unfinished, with a label and title", async () => {
    const { tp } = await open();
    tp.clearProgress();
    expect(dotted()).toBe(true);
    expect(el.tab("tutorials").getAttribute("aria-label")).toBe(LABEL);
    expect(el.tab("tutorials").title).toBe(LABEL);
    tp.mark("work-orders.a", "seen");
    expect(dotted()).toBe(true);
    tp.mark("work-orders.a", "completed");
    expect(dotted()).toBe(false);
    expect(el.tab("tutorials").hasAttribute("aria-label")).toBe(false);
    expect(el.tab("tutorials").hasAttribute("title")).toBe(false);
  });

  it("scripts the role cannot see do not hold it", async () => {
    const { tp } = await open("technician");
    tp.mark("work-orders.a", "completed");
    expect(dotted()).toBe(false);
  });
});
