// Standalone tutorials (welcome tour): targetless centred step, no sample and no
// closing showPage, onEnd("done" | "ended"), Hub tab restore, picker left alone
// by overlay taps. Player basics live in tutorial.test.js.
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { importView, mountView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
import { restoreBrowserStubs, stubScrollIntoView } from "../helpers/browserStubs.js";

let tut, showPage;
const overlay = () => document.querySelector(".tut-overlay");
const box = () => document.querySelector(".tut-box");
const text = () => document.querySelector(".tut-text").textContent;
const count = () => document.querySelector(".tut-count").textContent;
const act = (name) => document.querySelector(`[data-tut-act="${name}"]`);
const tap = () => overlay().click();
const byId = (id) => document.getElementById(id);
const toggle = () => byId("hub-picker-toggle");

const welcome = (extra = {}) => ({ key: "welcome", title: "Welcome", steps: [
  { title: "Welcome", text: ["Hello.", "Again."] },
  { target: "#sa", title: "Tabs", text: "Tabs." },
  { target: "#nope", title: "Gone", text: "Gone." },
  { target: "#sb", title: "Last", text: "Last." }], ...extra });

const install = (script) => {
  showPage = vi.fn();
  tut.installTutorials({ getActivePage: () => "user-hub", showPage,
    tutorials: { welcome: { scripts: [script], standalone: true } } });
};

beforeEach(async () => {
  server.use(http.put("/tutorials/progress/:key", () => new HttpResponse(null, { status: 204 })));
  tut = await mountView("tutorial.js");
  await importView("views/hubPicker.js");
  stubScrollIntoView();
  document.body.insertAdjacentHTML("beforeend", '<div id="sa">A</div><div id="sb">B</div>');
  await setTestUser({ role: "technician" });
  // The Hub's own tab switching is userHub.js's; a stand-in that moves `.active`.
  for (const tab of document.querySelectorAll(".hub-tab")) {
    tab.addEventListener("click", () => {
      document.querySelectorAll(".hub-tab").forEach((t) => t.classList.toggle("active", t === tab));
      toggle().setAttribute("aria-expanded", "false");
    });
  }
});
afterEach(() => { tut.endTutorial({ restore: false }); restoreBrowserStubs(); });

describe("targetless step", () => {
  it("centres the box with nothing lit, two-tap rule and counter unchanged, missing target still skips", () => {
    tut.runSteps(welcome(), "technician");
    expect(overlay().classList.contains("tut-targetless")).toBe(true);
    expect(document.querySelector(".tut-spot").style.width).toBe("0px");
    expect(count()).toBe("1 of 3");
    expect(text()).toBe("Hello.");
    tap();
    expect(text()).toBe("Again.");
    tap();
    expect(box().hidden).toBe(true);
    tap();
    expect(count()).toBe("2 of 3");
    expect(overlay().classList.contains("tut-targetless")).toBe(false);
    tap(); tap();
    expect(document.querySelector(".tut-title").textContent).toBe("Last");
  });
});

describe("standalone run", () => {
  it("sets no responder, never calls showPage, onEnd('done') on Done", async () => {
    install(welcome());
    const api = await import("../../../backend/static/api.js");
    server.use(http.get("/work-orders/", () => HttpResponse.json(["server"])));
    const onEnd = vi.fn();
    const started = tut.startTutorial("welcome", "welcome", { onEnd });
    await vi.waitFor(() => expect(box()).not.toBeNull());
    await expect(api.apiListWorkOrders()).resolves.toEqual(["server"]);
    for (let i = 0; i < 6; i += 1) tap();
    act("done").click();
    await started;
    expect(onEnd).toHaveBeenCalledExactlyOnceWith("done");
    expect(showPage).not.toHaveBeenCalled();
    expect(overlay()).toBeNull();
  });

  it.each([
    ["End", () => act("end").click()],
    ["Esc", () => document.dispatchEvent(new KeyboardEvent("keydown", { key: "Escape", bubbles: true }))],
    ["leaving the page", () => tut.endTutorial({ restore: false })],
  ])("onEnd('ended') on %s", async (_n, stop) => {
    install(welcome());
    const onEnd = vi.fn();
    const started = tut.startTutorial("welcome", "welcome", { onEnd });
    await vi.waitFor(() => expect(box()).not.toBeNull());
    stop();
    await started;
    expect(onEnd).toHaveBeenCalledExactlyOnceWith("ended");
    expect(showPage).not.toHaveBeenCalled();
  });

  it("calls onEnd('ended') even when nothing could start, and with no onEnd all is as before", async () => {
    install(welcome({ steps: [{ target: "#nope", text: "x" }] }));
    const onEnd = vi.fn();
    await tut.startTutorial("welcome", "welcome", { onEnd });
    expect(onEnd).toHaveBeenCalledExactlyOnceWith("ended");
    await expect(tut.startTutorial("welcome", "welcome")).resolves.toBeUndefined();
  });

  it("restores the Hub tab it began on; an already-active tab still ends with the picker collapsed", async () => {
    install(welcome({ open: ["#hub-tab-tutorials"], here: "#hub-tab-tutorials.active" }));
    expect(byId("hub-tab-home").classList.contains("active")).toBe(true);
    const started = tut.startTutorial("welcome", "welcome");
    await vi.waitFor(() => expect(box()).not.toBeNull());
    expect(byId("hub-tab-tutorials").classList.contains("active")).toBe(true);
    act("end").click();
    await started;
    expect(byId("hub-tab-home").classList.contains("active")).toBe(true);
    expect(byId("hub-tab-tutorials").classList.contains("active")).toBe(false);

    install(welcome());
    toggle().click();
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    const again = tut.startTutorial("welcome", "welcome");
    await vi.waitFor(() => expect(box()).not.toBeNull());
    act("end").click();
    await again;
    expect(toggle().getAttribute("aria-expanded")).toBe("false");
  });

  it("an open click already satisfied (aria-expanded true) is skipped, not toggled shut", async () => {
    install(welcome({ open: ["#hub-picker-toggle"], here: "#hub-picker.open" }));
    toggle().click();
    const started = tut.startTutorial("welcome", "welcome");
    await vi.waitFor(() => expect(box()).not.toBeNull());
    expect(toggle().getAttribute("aria-expanded")).toBe("true");
    act("end").click();
    await started;
  });

  it("a tap on the overlay does not collapse the open phone picker", async () => {
    install(welcome());
    toggle().click();
    const started = tut.startTutorial("welcome", "welcome");
    await vi.waitFor(() => expect(box()).not.toBeNull());
    tap();
    expect(byId("hub-picker").classList.contains("open")).toBe(true);
    act("end").click();
    await started;
  });
});
