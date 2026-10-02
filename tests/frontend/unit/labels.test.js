// static/labels.js: the label print page's size, barcode and text sliders.

import { describe, expect, it } from "vitest";

const sizeVar = (name) => document.documentElement.style.getPropertyValue(`--${name}`);
const slider = (name) => document.querySelector(`[data-var="${name}"]`);

function renderPage() {
  document.body.innerHTML = `
    <form class="toolbar">
      <label>Width <input type="range" data-var="w" min="1" max="7.5" step="0.05" value="2.5"><output></output></label>
      <label>Height <input type="range" data-var="h" min="1" max="10" step="0.05" value="3"><output></output></label>
      <label>Barcode <input type="range" data-var="b" min="10" max="80" step="1" value="30"><output></output></label>
      <label>Text <input type="range" data-var="f" min="50" max="400" step="5" value="100"><output></output></label>
    </form>
    <div class="sheet"><div class="label"></div></div>`;
}

// jsdom has no layout, so the label reports overflow per `overflowing()`.
function stubOverflow(overflowing) {
  const label = document.querySelector(".label");
  Object.defineProperty(label, "clientHeight", { value: 100 });
  Object.defineProperty(label, "scrollHeight", { get: () => (overflowing() ? 120 : 100) });
}

const loadScript = () => import("../../../backend/static/labels.js");

function move(name, value) {
  slider(name).value = value;
  slider(name).dispatchEvent(new Event("input"));
}

describe("label sliders", () => {
  it("resize the labels as they move and remember the size", async () => {
    renderPage();
    await loadScript();

    move("w", "2");

    expect(sizeVar("w")).toBe("2");
    expect(slider("w").nextElementSibling.textContent).toBe('2"');
    expect(localStorage.getItem("labels.w")).toBe("2");
  });

  it("restore a saved size, clamped to the slider's range", async () => {
    localStorage.setItem("labels.w", "99");
    localStorage.setItem("labels.h", "4.5");
    renderPage();

    await loadScript();

    expect(sizeVar("w")).toBe("7.5");
    expect(sizeVar("h")).toBe("4.5");
  });

  it.each([
    ["f", "300", 150, "150", "150%"],
    ["b", "70", 42, "42", "42%"],
  ])("snap %s back to the largest value that still fits", async (name, tried, fits, snapped, shown) => {
    renderPage();
    stubOverflow(() => Number(sizeVar(name)) > fits);
    await loadScript();

    move(name, tried);

    expect(sizeVar(name)).toBe(snapped);
    expect(slider(name).nextElementSibling.textContent).toBe(shown);
  });

  it("shrink the text when a smaller label no longer holds it", async () => {
    renderPage();
    // Text fits while it is at most 50x the label width.
    stubOverflow(() => Number(sizeVar("f")) > 50 * Number(sizeVar("w")));
    await loadScript();

    move("w", "1.5");

    expect(sizeVar("w")).toBe("1.5");
    expect(sizeVar("f")).toBe("75");

    move("f", "90"); // grows from the shrunk 75, so it snaps again
    expect(sizeVar("f")).toBe("75");
  });

  it("shrink saved text that the shown labels cannot hold", async () => {
    localStorage.setItem("labels.f", "400");
    renderPage();
    stubOverflow(() => Number(sizeVar("f")) > 120);

    await loadScript();

    expect(sizeVar("f")).toBe("120");
  });
});
