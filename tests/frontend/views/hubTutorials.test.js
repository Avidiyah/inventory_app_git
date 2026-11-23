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

const STARTER = { starter: { scripts: [
  { key: "starter.menu", title: "Using the menu", minRole: "technician", sample: false, steps: [] },
  { key: "starter.field", title: "Field", minRole: "technician", sample: false, steps: [] },
  { key: "starter.people", title: "People", minRole: "supervisor", sample: false, steps: [] },
] } };

async function open(role = "technician", fixture = FIXTURE) {
  vi.doMock("../../../backend/static/tutorials/index.js", () => ({ TUTORIALS: fixture }));
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

describe("Starter sub-tab", () => {
  const WITH = { ...FIXTURE, ...STARTER };
  const keys = () => entries().map((e) => e.dataset.tutKey);

  it("has To do, Completed, Starter in order, opens on To do", async () => {
    await open("supervisor", WITH);
    await show();
    expect([...panel().querySelectorAll("[data-tut-sub]")].map((b) => b.dataset.tutSub)).toEqual(["todo", "completed", "starter"]);
    expect(sub("todo").classList.contains("active")).toBe(true);
  });

  it("lists only relevant starters in order with New / Started / Done and Replay", async () => {
    const { tp } = await open("technician", WITH);
    await show();
    sub("starter").click();
    expect(keys()).toEqual(["starter.menu", "starter.field"]);
    expect(entries()[0].textContent).toContain("New");
    tp.mark("starter.menu", "seen");
    expect(entries()[0].textContent).toContain("Started");
    tp.mark("starter.menu", "completed");
    expect(entries()[0].textContent).toContain("Done");
    expect(entries()[0].textContent).toContain("Replay");
  });

  it("the count is the unfinished number and its span is absent at 0", async () => {
    const { tp } = await open("supervisor", WITH);
    await show();
    expect(sub("starter").textContent).toBe("Starter (3)");
    for (const k of ["starter.menu", "starter.field", "starter.people"]) tp.mark(k, "completed");
    expect(sub("starter").textContent).toBe("Starter");
    expect(sub("starter").querySelector(".hub-tut-count")).toBeNull();
  });

  it("starters also appear in To do (grouped Menu) and Completed", async () => {
    const { tp } = await open("technician", WITH);
    await show();
    expect([...panel().querySelectorAll(".hub-tut-page")].map((g) => g.textContent)).toContain("Menu");
    expect(keys()).toContain("starter.field");
    tp.mark("starter.field", "completed");
    sub("completed").click();
    expect(keys()).toEqual(["starter.field"]);
    expect(panel().querySelector(".hub-tut-page").textContent).toBe("Menu");
  });

  it("every-tutorial-finished needs the starters finished too; the dot counts them", async () => {
    const { tp } = await open("technician", WITH);
    await show();
    tp.mark("work-orders.a", "completed");
    expect(panel().textContent).not.toContain("You have finished every tutorial");
    expect(el.tab("tutorials").classList.contains("hub-tab-dot")).toBe(true);
    tp.mark("starter.menu", "completed");
    tp.mark("starter.field", "completed");
    expect(panel().textContent).toContain("You have finished every tutorial");
    expect(el.tab("tutorials").classList.contains("hub-tab-dot")).toBe(false);
  });

  it("a tap starts the starter and never shows a page; entries are single buttons", async () => {
    const { startTutorial } = await open("technician", WITH);
    await show();
    sub("starter").click();
    for (const e of entries()) expect(e.querySelector("button")).toBeNull();
    const before = document.querySelector(".page.active")?.id;
    entries()[1].click();
    expect(startTutorial).toHaveBeenCalledWith("starter", "starter.field");
    expect(document.querySelector(".page.active")?.id).toBe(before);
    expect(document.getElementById("starter-page")).toBeNull();
    expect(document.querySelector("[data-tut-page=starter]")).not.toBeNull();
    expect(document.querySelector(".nav-btn[data-page=starter]")).toBeNull();
  });

  it("setTutorialsSub opens the tab on that sub-tab", async () => {
    await open("technician", WITH);
    const hub = await import("../../../backend/static/views/hubTutorials.js");
    hub.setTutorialsSub("starter");
    await show();
    expect(sub("starter").classList.contains("active")).toBe(true);
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
