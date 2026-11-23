import { describe, expect, it, vi } from "vitest";
import { bootApp } from "../helpers/app.js";

const DOT = "How this page works, you have not finished it yet";
const btn = () => document.querySelector("#work-orders-page .tut-btn");
const dotted = () => btn().classList.contains("tut-btn-dot");

// main.js installs the buttons and dots from this registry.
const FIXTURE = { "work-orders": { scripts: [
  { key: "work-orders.a", title: "A", steps: [] },
  { key: "work-orders.b", title: "B", minRole: "supervisor", steps: [] },
] } };

async function boot(role = "technician") {
  vi.doMock("../../../backend/static/tutorials/index.js", () => ({ TUTORIALS: FIXTURE }));
  const app = await bootApp({ role, page: "work-orders" });
  const dots = await import("../../../backend/static/tutorialDots.js");
  const tp = await import("../../../backend/static/tutorialProgress.js");
  const state = await import("../../../backend/static/state.js");
  tp.clearProgress(); // empty cache, repaints
  return { ...app, dots, tp, state };
}

describe("red dot", () => {
  it("shows while a relevant script is unfinished, and clears when it is done", async () => {
    const { tp } = await boot();
    expect(dotted()).toBe(true);
    expect(btn().getAttribute("aria-label")).toBe(DOT);
    expect(btn().title).toBe(DOT);
    tp.mark("work-orders.a", "seen");
    expect(dotted()).toBe(true); // seen is not finished
    tp.mark("work-orders.a", "completed");
    expect(dotted()).toBe(false); // b is for Team Lead and above
    expect(btn().hasAttribute("aria-label")).toBe(false);
    expect(btn().hasAttribute("title")).toBe(false);
  });

  it("a role change plus repaint recomputes", async () => {
    const { tp, dots, state, currentUser } = await boot();
    tp.mark("work-orders.a", "completed");
    expect(dotted()).toBe(false);
    state.setCurrentUser({ ...currentUser, role: "supervisor" });
    dots.repaintDots();
    expect(dotted()).toBe(true);
    tp.mark("work-orders.b", "completed");
    expect(dotted()).toBe(false);
  });

  it("nobody signed in shows no dot", async () => {
    const { dots, state } = await boot();
    state.setCurrentUser(null);
    dots.repaintDots();
    expect(dotted()).toBe(false);
  });
});
