import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { mountView } from "../helpers/shell.js";
import { setTestUser } from "../helpers/session.js";
import { restoreBrowserStubs, stubScrollIntoView } from "../helpers/browserStubs.js";
import { dismissMessageDialog } from "../helpers/workOrders.js";

let tut;
const box = () => document.querySelector(".tut-box");
const pill = () => document.querySelector(".tut-pill");
const overlay = () => document.querySelector(".tut-overlay");
const text = () => document.querySelector(".tut-text").textContent;
const count = () => document.querySelector(".tut-count").textContent;
const act = (name) => document.querySelector(`[data-tut-act="${name}"]`);
const tap = () => overlay().click();
const key = (k) => document.dispatchEvent(new KeyboardEvent("keydown", { key: k, bubbles: true }));

beforeEach(async () => {
  server.use(http.put("/tutorials/progress/:key", () => new HttpResponse(null, { status: 204 })));
  tut = await mountView("tutorial.js");
  stubScrollIntoView();
  document.body.insertAdjacentHTML("beforeend", `
    <div id="host">
      <div id="a">A</div><div id="b">B</div><div id="c">C</div>
      <details id="closed"><summary id="sum">S</summary><div id="d">D</div></details>
      <div hidden><div id="e">E</div></div>
      <button id="under" type="button">under</button>
    </div>`);
});
afterEach(() => {
  tut.endTutorial({ restore: false });
  restoreBrowserStubs();
});

const three = {
  key: "demo.x", title: "X",
  steps: [
    { target: "#a", title: "One", text: "First." },
    { target: "#b", title: "Two", text: ["Second.", "Second more."] },
    { target: "#c", title: "Three", text: "Third.", textFor: { supervisor: "Lead third." } },
  ],
};

describe("runSteps", () => {
  it("first tap hides the box behind a pill, second moves on", async () => {
    tut.runSteps(three, "technician");
    expect(text()).toBe("First.");
    expect(count()).toBe("1 of 3");
    tap();
    expect(box().hidden).toBe(true);
    expect(pill().hidden).toBe(false);
    expect(pill().textContent).toBe("Tap anywhere for the next step");
    tap();
    expect(box().hidden).toBe(false);
    expect(document.querySelector(".tut-title").textContent).toBe("Two");
    expect(count()).toBe("2 of 3");
  });

  it("gives each sentence of a step its own tap", async () => {
    tut.runSteps(three, "technician");
    tap(); tap();
    expect(text()).toBe("Second.");
    tap();
    expect(text()).toBe("Second more.");
    expect(box().hidden).toBe(false);
    tap();
    expect(box().hidden).toBe(true);
  });

  it("offers Back after step 1, and End removes everything", async () => {
    const done = tut.runSteps(three, "technician");
    expect(act("back")).toBeNull();
    tap(); tap();
    act("back").click();
    expect(count()).toBe("1 of 3");
    act("end").click();
    await expect(done).resolves.toEqual({ result: "end" });
  });

  it("Esc ends; Enter and ArrowRight tap", async () => {
    const done = tut.runSteps(three, "technician");
    document.body.focus();
    key("ArrowRight");
    expect(box().hidden).toBe(true);
    key("Enter");
    expect(count()).toBe("2 of 3");
    key("Escape");
    await expect(done).resolves.toEqual({ result: "end" });
  });

  it("skips missing, [hidden] and closed-details targets, keeps an open-details one", () => {
    const s = { key: "demo.y", title: "Y", steps: ["#zz", "#e", "#d", "#sum", "#a"].map((t) => ({ target: t, text: t })) };
    expect(tut.visibleSteps(s, "technician").map((v) => v.step.target)).toEqual(["#sum", "#a"]);
    document.getElementById("closed").open = true;
    expect(tut.visibleSteps(s, "technician").map((v) => v.step.target)).toEqual(["#d", "#sum", "#a"]);
  });

  it("uses textFor for the named role only", async () => {
    tut.runSteps(three, "supervisor");
    tap(); tap(); tap(); tap(); tap();
    expect(text()).toBe("Lead third.");
    tut.endTutorial({ restore: false });
    expect(tut.sentences(three.steps[2], "technician")).toEqual(["Third."]);
  });

  it("shows text literally", () => {
    tut.runSteps({ key: "demo.z", title: "Z", steps: [{ target: "#a", text: "<b>x</b>" }] }, "owner");
    expect(text()).toBe("<b>x</b>");
  });

  it("last step stays up with Done", async () => {
    const done = tut.runSteps({ key: "demo.z", title: "Z", steps: [{ target: "#a", text: "Only." }] }, "owner");
    tap();
    expect(box().hidden).toBe(false);
    act("done").click();
    await expect(done).resolves.toEqual({ result: "done" });
  });

  it("never lets a tap reach the page beneath", () => {
    const spy = vi.fn();
    document.getElementById("under").addEventListener("click", spy);
    document.addEventListener("click", spy);
    tut.runSteps(three, "technician");
    tap();
    expect(spy).not.toHaveBeenCalled();
  });
});

describe("placeBox", () => {
  const vp = { width: 400, height: 800 };
  it("goes below, then above, then pins to the bottom, always on screen", () => {
    expect(tut.placeBox({ left: 10, top: 100, bottom: 150, width: 50 }, { width: 300, height: 100 }, vp).mode).toBe("below");
    expect(tut.placeBox({ left: 10, top: 600, bottom: 750, width: 50 }, { width: 300, height: 100 }, vp).mode).toBe("above");
    const pinned = tut.placeBox({ left: 0, top: 50, bottom: 760, width: 400 }, { width: 300, height: 100 }, vp);
    expect(pinned.mode).toBe("bottom");
    const wide = tut.placeBox({ left: 390, top: 0, bottom: 10, width: 10 }, { width: 900, height: 50 }, vp);
    expect(wide.left).toBeGreaterThanOrEqual(0);
    expect(wide.left + Math.min(900, vp.width - 24)).toBeLessThanOrEqual(vp.width);
  });
});

describe("session", () => {
  let showPage;
  const demo = () => ({
    sample: () => ({ "GET /work-orders/": [1] }),
    scripts: [
      { key: "demo.one", title: "One", here: "#a", steps: [{ target: "#a", text: "One." }] },
      { key: "demo.two", title: "Two", here: "#b", open: ["#tab2"], steps: [{ target: "#t2", text: "Two." }] },
    ],
  });
  const install = (tutorials = { demo: demo() }) => {
    showPage = vi.fn();
    document.getElementById("host").insertAdjacentHTML("afterbegin", '<section id="demo-page"><h2>Demo</h2></section>');
    tut.installTutorials({ getActivePage: () => "demo", showPage, tutorials });
  };

  beforeEach(async () => { await setTestUser({ role: "technician" }); });

  it("start sets sample mode and reloads once; End clears it and reloads again", async () => {
    install();
    const api = await import("../../../backend/static/api.js");
    server.use(http.get("/hub", () => HttpResponse.json(["real"])));
    const started = tut.startTutorial("demo", "demo.one");
    await vi.waitFor(() => expect(box()).not.toBeNull());
    expect(showPage).toHaveBeenCalledTimes(1);
    await expect(api.apiListWorkOrders({ status: "x" })).resolves.toEqual([1]);
    await expect(api.apiGetHub()).resolves.toEqual(["real"]);
    act("done").click();
    await started;
    expect(showPage).toHaveBeenCalledTimes(2);
    expect(overlay()).toBeNull();
    server.use(http.get("/work-orders/", () => HttpResponse.json(["server"])));
    await expect(api.apiListWorkOrders()).resolves.toEqual(["server"]);
  });

  it("restore:false ends without reloading; ending when idle does nothing", async () => {
    install();
    tut.endTutorial();
    expect(showPage).not.toHaveBeenCalled();
    tut.startTutorial("demo", "demo.one");
    await vi.waitFor(() => expect(box()).not.toBeNull());
    tut.endTutorial({ restore: false });
    expect(showPage).toHaveBeenCalledTimes(1);
    expect(overlay()).toBeNull();
  });

  it("plays the last script whose `here` matches, else the first", () => {
    const { scripts } = demo();
    expect(tut.pickScript(scripts).key).toBe("demo.two");
    document.getElementById("b").remove();
    expect(tut.pickScript(scripts).key).toBe("demo.one");
    document.getElementById("a").remove();
    expect(tut.pickScript(scripts).key).toBe("demo.one");
  });

  it("open: skips a click whose result is visible; clicks and waits otherwise; fails quietly", async () => {
    const host = document.getElementById("host");
    host.insertAdjacentHTML("beforeend", '<button id="o1">o1</button><div id="o2" hidden>o2</div><div id="tgt" hidden>t</div>');
    const o1 = document.getElementById("o1");
    const clicks = vi.fn(() => { document.getElementById("o2").hidden = false; });
    o1.addEventListener("click", clicks);
    const o2 = document.getElementById("o2");
    o2.addEventListener("click", () => { document.getElementById("tgt").hidden = false; });
    const s = { key: "demo.o", title: "O", open: ["#o1", "#o2"], steps: [{ target: "#tgt", text: "t" }] };
    await expect(tut.runOpen(s, "owner")).resolves.toBe(true);
    expect(clicks).toHaveBeenCalledTimes(1);
    await expect(tut.runOpen(s, "owner")).resolves.toBe(true);
    expect(clicks).toHaveBeenCalledTimes(1);

    vi.useFakeTimers();
    const never = tut.runOpen({ key: "demo.n", title: "N", open: ["#nope"], steps: [{ target: "#zz", text: "z" }] }, "owner");
    await vi.advanceTimersByTimeAsync(7000);
    await expect(never).resolves.toBe(false);
    vi.useRealTimers();
  });

  it("open: an optional absent selector is skipped at once; focus comes before click", async () => {
    const host = document.getElementById("host");
    host.insertAdjacentHTML("beforeend", '<input id="f1"><div id="tg" hidden>t</div>');
    const order = [];
    const f1 = document.getElementById("f1");
    f1.addEventListener("focus", () => order.push("focus"));
    f1.addEventListener("click", () => { order.push("click"); document.getElementById("tg").hidden = false; });
    const s = { key: "demo.q", title: "Q", open: ["?#absent", "#f1"], steps: [{ target: "#tg", text: "t" }] };
    await expect(tut.runOpen(s, "owner")).resolves.toBe(true);
    expect(order).toEqual(["focus", "click"]);
  });

  it("offers Next only when a later script's tab exists; Next runs it without a reload", async () => {
    const d = demo();
    d.scripts[1].here = "#t2:not([hidden])"; // `here` = its tab is selected; not yet
    install({ demo: d });
    const host = document.getElementById("host");
    host.insertAdjacentHTML("beforeend", '<button id="tab2">tab</button><div id="t2" hidden>t2</div>');
    document.getElementById("tab2").addEventListener("click", () => { document.getElementById("t2").hidden = false; });
    const started = tut.startTutorial("demo", "demo.one");
    await vi.waitFor(() => expect(act("next")).not.toBeNull());
    expect(act("next").textContent).toBe("Next: Two");
    act("next").click();
    await vi.waitFor(() => expect(text()).toBe("Two."));
    expect(showPage).toHaveBeenCalledTimes(1);
    expect(act("next")).toBeNull();
    act("done").click();
    await started;
  });

  it("no visible step ends quietly and restores", async () => {
    vi.useFakeTimers();
    install({ demo: { sample: () => ({}), scripts: [{ key: "demo.none", title: "N", steps: [{ target: "#zz", text: "z" }] }] } });
    const started = tut.startTutorial("demo");
    await vi.advanceTimersByTimeAsync(7000);
    await started;
    vi.useRealTimers();
    expect(overlay()).toBeNull();
    expect(showPage).toHaveBeenCalledTimes(2);
  });

  it("refuses to start over unsaved text and says why", async () => {
    install();
    const api = await import("../../../backend/static/api.js");
    const page = document.getElementById("demo-page");
    page.insertAdjacentHTML("beforeend", "<textarea id=\"note\"></textarea>");
    document.getElementById("note").value = "unsaved words";
    await tut.startTutorial("demo");
    expect(await dismissMessageDialog()).toMatch(/Finish or save what you typed/);
    expect(overlay()).toBeNull();
    expect(showPage).not.toHaveBeenCalled();
    expect(document.getElementById("note").value).toBe("unsaved words");
    server.use(http.get("/work-orders/", () => HttpResponse.json(["server"])));
    await expect(api.apiListWorkOrders()).resolves.toEqual(["server"]);
  });

  it("starting closes an open tip", async () => {
    install();
    const { installTooltips } = await import("../../../backend/static/tooltip.js");
    installTooltips();
    document.getElementById("host").insertAdjacentHTML("beforeend", '<button class="tip-btn" data-tip="wo.status">?</button>');
    document.querySelector('[data-tip="wo.status"]').click();
    expect(document.getElementById("tip-bubble").hidden).toBe(false);
    tut.startTutorial("demo", "demo.one");
    expect(document.getElementById("tip-bubble").hidden).toBe(true);
  });

  it("ending fires tutorial:end", async () => {
    install();
    const spy = vi.fn();
    document.addEventListener("tutorial:end", spy);
    tut.startTutorial("demo", "demo.one");
    await vi.waitFor(() => expect(box()).not.toBeNull());
    tut.endTutorial({ restore: false });
    expect(spy).toHaveBeenCalledOnce();
  });
});

describe("page button", () => {
  const tutorials = { demo: { scripts: [] } };
  it("goes in a [data-tutorial-slot] when the page has one, even with an h2", () => {
    document.getElementById("host").insertAdjacentHTML("afterbegin",
      '<section id="demo-page"><div data-tutorial-slot></div><h2>Home</h2></section>');
    tut.installTutorials({ getActivePage: () => "demo", showPage: vi.fn(), tutorials });
    expect(document.querySelector("[data-tutorial-slot] .tut-btn")).not.toBeNull();
  });
  it("else ends the first h2, once", () => {
    document.getElementById("host").insertAdjacentHTML("afterbegin",
      '<section id="demo-page"><h2>Demo <button class="tip-btn">?</button></h2><h2>Other</h2></section>');
    const d = { getActivePage: () => "demo", showPage: vi.fn(), tutorials };
    tut.installTutorials(d);
    tut.installTutorials(d);
    const btns = document.querySelectorAll("#demo-page .tut-btn");
    expect(btns).toHaveLength(1);
    expect(btns[0].previousElementSibling.className).toBe("tip-btn");
    expect(btns[0].textContent).toBe("How this page works");
  });
});

describe("minRole and Next", () => {
  it("skips a later script above the person's role", () => {
    document.getElementById("host").insertAdjacentHTML("beforeend", '<button id="tb">b</button><button id="tc">c</button>');
    const a = { key: "demo.a", title: "A", steps: [{ target: "#a", text: "A." }] };
    const b = { key: "demo.b", title: "B", minRole: "supervisor", open: ["#tb"], steps: [{ target: "#b", text: "B." }] };
    const c = { key: "demo.c", title: "C", open: ["#tc"], steps: [{ target: "#c", text: "C." }] };
    tut.runSteps(a, "technician", { scripts: [a, b] });
    expect(act("next")).toBeNull();
    tut.endTutorial({ restore: false });
    act("done")?.click();
    tut.runSteps(a, "technician", { scripts: [a, b, c] });
    expect(act("next").textContent).toBe("Next: C");
    act("done").click();
    tut.runSteps(a, "supervisor", { scripts: [a, b, c] });
    expect(act("next").textContent).toBe("Next: B");
    act("done").click();
  });
});

describe("progress recording", () => {
  let tp;
  beforeEach(async () => { tp = await import("../../../backend/static/tutorialProgress.js"); });
  const two = { key: "demo.p", title: "P", steps: [
    { target: "#a", text: "A." }, { target: "#b", text: "B." }, { target: "#d", text: "Hidden." }] };

  it("marks seen on entry and completed on the last visible step, not before", () => {
    tut.runSteps(two, "technician");
    expect(tp.hasSeen("demo.p")).toBe(true);
    expect(tp.isDone("demo.p")).toBe(false);
    tap();
    tap();
    expect(count()).toBe("2 of 2"); // #d is skipped, so #b is the last
    expect(tp.isDone("demo.p")).toBe(true);
  });

  it("End early never completes", () => {
    tut.runSteps(two, "technician");
    act("end").click();
    expect(tp.hasSeen("demo.p")).toBe(true);
    expect(tp.isDone("demo.p")).toBe(false);
  });

  it("a Next jump marks the next script seen", async () => {
    document.getElementById("host").insertAdjacentHTML("beforeend", '<button id="tn">n</button>');
    const a = { key: "demo.a", title: "A", steps: [{ target: "#a", text: "A." }] };
    const b = { key: "demo.b", title: "B", open: ["#tn"], steps: [{ target: "#b", text: "B." }] };
    const out = tut.runSteps(a, "technician", { scripts: [a, b] });
    expect(tp.isDone("demo.a")).toBe(true);
    act("next").click();
    expect((await out).script).toBe(b);
    tut.runSteps(b, "technician");
    expect(tp.hasSeen("demo.b")).toBe(true);
    act("done").click();
  });
});

describe("startTutorial by key", () => {
  const mk = (extra = {}) => ({ scripts: [
    { key: "demo.a", title: "A", here: "#a", steps: [{ target: "#a", text: "A." }] },
    { key: "demo.b", title: "B", steps: [{ target: "#b", text: "B." }] },
  ], ...extra });
  const install = (tutorials, showPage = vi.fn()) => {
    tut.installTutorials({ getActivePage: () => "demo", showPage, tutorials });
    return showPage;
  };
  beforeEach(async () => { await setTestUser({ role: "technician" }); });

  const playing = async (page, key) => {
    install({ [page]: mk() });
    const started = tut.startTutorial(page, key);
    await vi.waitFor(() => expect(box()).not.toBeNull());
    return async () => { tut.endTutorial({ restore: false }); await started; };
  };

  it("a key overrides `here`", async () => {
    const stop = await playing("demo", "demo.b");
    expect(text()).toBe("B.");
    await stop();
  });

  it("no key keeps the here rule", async () => {
    const stop = await playing("demo");
    expect(text()).toBe("A.");
    await stop();
  });

  it("an unknown key falls back to the here rule", async () => {
    const stop = await playing("demo", "demo.nope");
    expect(text()).toBe("A.");
    await stop();
  });

  it("an entry with no sample (a starter) never calls showPage", async () => {
    const showPage = install({ starter: mk() });
    const started = tut.startTutorial("starter", "demo.b");
    await vi.waitFor(() => expect(text()).toBe("B."));
    act("done").click();
    await started;
    expect(showPage).not.toHaveBeenCalled();
  });

  it("pickScript skips a script above the person's role", () => {
    const scripts = [
      { key: "x.a", here: "#a", steps: [] },
      { key: "x.b", here: "#b", minRole: "techfm_oa", steps: [] },
    ];
    expect(tut.pickScript(scripts, "technician").key).toBe("x.a");
    expect(tut.pickScript(scripts, "admin").key).toBe("x.b");
  });
});
