import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";
import { http, HttpResponse } from "msw";
import { server } from "../helpers/handlers.js";
import { importView, mountView } from "../helpers/shell.js";
import { stubClientRects } from "../helpers/starterWalk.js";
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

describe("wait steps", () => {
  let wait, t1, t2, other, seen;
  const spot = () => document.querySelector(".tut-spot");
  const clickAt = (el) => {
    const r = el.getBoundingClientRect();
    overlay().dispatchEvent(new MouseEvent("click", { bubbles: true, cancelable: true,
      clientX: r.left + r.width / 2, clientY: r.top + r.height / 2 }));
  };
  const W = () => ({ key: "demo.wait", title: "W", steps: [
    { waitTap: "#t2", via: "#t1", viaText: "Open it.", text: "Tap two." },
    { target: "#b", title: "After", text: "After." },
    { target: "#c", title: "Last", text: "Last." }] });

  beforeEach(async () => {
    vi.useFakeTimers();
    stubClientRects();
    wait = await importView("tutorialWait.js");
    document.getElementById("host").insertAdjacentHTML("beforeend",
      '<button id="t1" type="button">t1</button><button id="t2" type="button">t2</button><button id="other" type="button">o</button>');
    [t1, t2, other] = ["t1", "t2", "other"].map((id) => document.getElementById(id));
    const mine = (seen = []);
    document.addEventListener("click", (e) => mine.push(e.target));
  });
  // runSteps alone never sets `running`, so endTutorial would be a no-op: Esc
  // finishes the run, which silences this instance's document listeners.
  afterEach(() => { key("Escape"); tut.endTutorial({ restore: false }); vi.useRealTimers(); });

  it("keeps the box up, no pill, and the first tap does not hide it", () => {
    tut.runSteps(W(), "owner");
    expect(text()).toBe("Tap two.");
    expect(box().hidden).toBe(false);
    expect(pill().hidden).toBe(true);
    tap();
    expect(box().hidden).toBe(false);
    expect(count()).toBe("1 of 3");
  });

  it("forwards a tap inside the lit rectangle once; outside does nothing", () => {
    const spy = vi.fn();
    t2.addEventListener("click", spy);
    tut.runSteps(W(), "owner");
    clickAt(other);
    expect(spy).not.toHaveBeenCalled();
    expect(seen).toEqual([]);
    expect(count()).toBe("1 of 3");
    clickAt(t2);
    expect(spy).toHaveBeenCalledOnce();
    expect(seen).toEqual([t2]); // the overlay tap itself never reached document
  });

  it.each(["Enter", "ArrowRight"])("%s acts as the lit tap", (k) => {
    const spy = vi.fn();
    t2.addEventListener("click", spy);
    tut.runSteps(W(), "owner");
    key(k);
    expect(spy).toHaveBeenCalledOnce();
  });

  it("blocks every other key, and keyup of Enter and Space, so a focused button never fires", () => {
    const onOther = vi.fn();
    other.addEventListener("click", onOther);
    other.addEventListener("keydown", onOther);
    other.addEventListener("keyup", onOther);
    tut.runSteps(W(), "owner");
    other.focus();
    for (const [type, k] of [["keydown", "x"], ["keydown", " "], ["keyup", "Enter"], ["keyup", " "]]) {
      const e = new KeyboardEvent(type, { key: k, bubbles: true, cancelable: true });
      other.dispatchEvent(e);
      expect(e.defaultPrevented).toBe(true);
    }
    expect(onOther).not.toHaveBeenCalled();
  });

  it("lights via while waitTap has no box, forwards to via, then lights waitTap", () => {
    let open = false;
    t2.getClientRects = () => (open ? [{}] : []);
    t1.addEventListener("click", () => { open = true; });
    const spy2 = vi.fn();
    t2.addEventListener("click", spy2);
    tut.runSteps(W(), "owner");
    expect(text()).toBe("Open it.");
    expect(spot().style.top).toBe(`${t1.getBoundingClientRect().top - 6}px`);
    clickAt(t1);
    expect(spy2).not.toHaveBeenCalled();
    vi.advanceTimersByTime(50);
    expect(text()).toBe("Tap two.");
    expect(spot().style.top).toBe(`${t2.getBoundingClientRect().top - 6}px`);
    clickAt(t2);
    expect(spy2).toHaveBeenCalledOnce();
  });

  it("C1: a role-hidden waitTap skips it and the steps up to the next wait", () => {
    const s = { key: "demo.c1", title: "C", steps: [
      { target: "#a", text: "A." }, { waitTap: "#e", text: "Hidden." },
      { target: "#b", text: "B." }, { target: "#c", text: "C." },
      { waitTap: "#t1", text: "One." }, { target: "#under", text: "U." }] };
    expect(tut.visibleSteps(s, "owner").map((v) => v.step.target ?? v.step.waitTap))
      .toEqual(["#a", "#t1", "#under"]);
  });

  it("C1: a role-visible waitTap with no box anywhere ends quietly after 3 s", async () => {
    t2.getClientRects = () => [];
    const noVia = W();
    delete noVia.steps[0].via;
    const done = tut.runSteps(noVia, "owner");
    vi.advanceTimersByTime(2900);
    expect(overlay()).not.toBeNull();
    vi.advanceTimersByTime(200);
    await expect(done).resolves.toEqual({ result: "end" });
    expect((await import("../../../backend/static/tutorialProgress.js")).isDone("demo.wait")).toBe(false);
  });

  it("Esc and End end without completing; no Back on the first step after a wait", async () => {
    const tp = await import("../../../backend/static/tutorialProgress.js");
    let done = tut.runSteps(W(), "owner");
    key("Escape");
    await expect(done).resolves.toEqual({ result: "end" });
    done = tut.runSteps(W(), "owner");
    act("end").click();
    await expect(done).resolves.toEqual({ result: "end" });
    expect(tp.isDone("demo.wait")).toBe(false);

    tut.runSteps(W(), "owner");
    clickAt(t2);
    vi.advanceTimersByTime(50);
    expect(text()).toBe("After.");
    expect(act("back")).toBeNull();
    tap(); tap();
    expect(text()).toBe("Last.");
    expect(act("back")).not.toBeNull();
  });

  it("a text list and a textFor list give one sentence per tap", () => {
    tut.runSteps({ key: "demo.l", title: "L", steps: [
      { target: "#a", text: "X.", textFor: { owner: ["One.", "Two."] } },
      { target: "#b", text: ["P.", "Q."] }] }, "owner");
    expect(text()).toBe("One.");
    tap();
    expect(text()).toBe("Two.");
    tap(); tap();
    expect(text()).toBe("P.");
    tap();
    expect(text()).toBe("Q.");
  });

  it("expectNav is set by a forwarded page tap and clears when the next step shows", () => {
    tut.runSteps(W(), "owner");
    expect(wait.isExpectingNav()).toBe(false);
    clickAt(t2);
    expect(wait.isExpectingNav()).toBe(true);
    vi.advanceTimersByTime(50);
    expect(text()).toBe("After.");
    expect(wait.isExpectingNav()).toBe(false);
  });

  it("no next target within 3 s ends quietly, expectNav cleared, never completed", async () => {
    const tp = await import("../../../backend/static/tutorialProgress.js");
    const done = tut.runSteps({ key: "demo.gone", title: "G", steps: [
      { waitTap: "#t2", text: "Tap." }, { target: "#zz", text: "Never." }] }, "owner");
    clickAt(t2);
    expect(wait.isExpectingNav()).toBe(true);
    vi.advanceTimersByTime(3100);
    await expect(done).resolves.toEqual({ result: "end" });
    expect(wait.isExpectingNav()).toBe(false);
    expect(tp.isDone("demo.gone")).toBe(false);
  });

  it("endTutorial from nav is ignored while expecting", () => {
    tut.runSteps(W(), "owner");
    clickAt(t2);
    tut.endTutorial({ restore: false, fromNav: true });
    expect(overlay()).not.toBeNull();
  });
});

describe("starter entry (no sample)", () => {
  beforeEach(async () => { await setTestUser({ role: "technician" }); });

  it("sets no responder, skips showPage, refusals and the restore", async () => {
    const api = await import("../../../backend/static/api.js");
    const { confirmOverlay } = await import("../helpers/dialogs.js");
    const showPage = vi.fn();
    document.getElementById("host").insertAdjacentHTML("afterbegin",
      '<section id="demo-page"><h2>D</h2><textarea id="note"></textarea><div data-tutorial-busy></div></section>');
    document.getElementById("note").value = "typed words";
    tut.installTutorials({ getActivePage: () => "demo", showPage,
      tutorials: { demo: { scripts: [{ key: "demo.s", title: "S", sample: false, steps: [{ target: "#a", text: "A." }] }] } } });
    server.use(http.get("/work-orders/", () => HttpResponse.json(["server"])));
    const started = tut.startTutorial("demo", "demo.s");
    await vi.waitFor(() => expect(text()).toBe("A."));
    expect(confirmOverlay().hidden).toBe(true);
    await expect(api.apiListWorkOrders()).resolves.toEqual(["server"]);
    act("done").click();
    await started;
    expect(showPage).not.toHaveBeenCalled();
    expect(document.getElementById("note").value).toBe("typed words");
  });
});
