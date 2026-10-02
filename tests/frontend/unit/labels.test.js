// static/labels.js: the label print page's sliders and label selection.

import { describe, expect, it } from "vitest";

const sizeVar = (name) => document.documentElement.style.getPropertyValue(`--${name}`);
const slider = (name) => document.querySelector(`[data-var="${name}"]`);
const label = (i) => document.querySelectorAll(".label")[i];
const ownVar = (i, name) => label(i).style.getPropertyValue(`--${name}`);
const selectAll = () => document.getElementById("select-all");

function renderPage() {
  const box = '<div class="label" tabindex="0" role="checkbox" aria-checked="false"></div>';
  document.body.innerHTML = `
    <form class="toolbar">
      <label><input type="checkbox" id="select-all"> Select all</label>
      <label>Width <input type="range" data-var="w" min="1" max="7.5" step="0.05" value="2.5"><output></output></label>
      <label>Height <input type="range" data-var="h" min="1" max="10" step="0.05" value="3"><output></output></label>
      <label>Barcode <input type="range" data-var="b" min="10" max="80" step="1" value="30"><output></output></label>
      <label>Text <input type="range" data-var="f" min="50" max="400" step="5" value="100"><output></output></label>
    </form>
    <div class="sheet">${box.repeat(3)}</div>`;
}

// jsdom has no layout, so label `i` reports overflow per `overflowing()`.
function stubOverflow(overflowing, i = 0) {
  Object.defineProperty(label(i), "clientHeight", { value: 100 });
  Object.defineProperty(label(i), "scrollHeight", { get: () => (overflowing() ? 120 : 100) });
}

function toggleAll(checked) {
  selectAll().checked = checked;
  selectAll().dispatchEvent(new Event("change"));
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

describe("label selection", () => {
  it("narrows the sliders to the clicked label, unremembered", async () => {
    renderPage();
    await loadScript();

    label(0).click();
    move("w", "2");

    expect(label(0).classList.contains("selected")).toBe(true);
    expect(label(0).getAttribute("aria-checked")).toBe("true");
    expect(ownVar(0, "w")).toBe("2");
    expect(ownVar(1, "w")).toBe("");
    expect(sizeVar("w")).toBe("2.5");
    expect(localStorage.getItem("labels.w")).toBe("2.5");
  });

  it("toggles from the keyboard", async () => {
    renderPage();
    await loadScript();

    label(1).dispatchEvent(new KeyboardEvent("keydown", { key: " ", bubbles: true }));

    expect(label(1).classList.contains("selected")).toBe(true);
  });

  it("selects and clears every label from the checkbox, showing a partial selection", async () => {
    renderPage();
    await loadScript();

    toggleAll(true);
    expect([0, 1, 2].every((i) => label(i).classList.contains("selected"))).toBe(true);

    label(2).click();
    expect(selectAll().checked).toBe(false);
    expect(selectAll().indeterminate).toBe(true);

    toggleAll(false);
    expect([0, 1, 2].some((i) => label(i).classList.contains("selected"))).toBe(false);
    expect(selectAll().indeterminate).toBe(false);
  });

  it("moves every label, clearing single-label tweaks, while all are selected", async () => {
    renderPage();
    await loadScript();
    label(0).click();
    move("w", "2");

    toggleAll(true);
    move("w", "3");

    expect(sizeVar("w")).toBe("3");
    expect(ownVar(0, "w")).toBe("");
    expect(localStorage.getItem("labels.w")).toBe("3");
  });

  it("shows the selected label's own values on the sliders", async () => {
    renderPage();
    await loadScript();
    label(1).click();
    move("f", "150");

    label(1).click(); // deselect: back to the page-wide values
    expect(slider("f").value).toBe("100");

    label(1).click();
    expect(slider("f").value).toBe("150");
    expect(slider("f").nextElementSibling.textContent).toBe("150%");
  });

  it("checks only the selected labels for overflow", async () => {
    renderPage();
    stubOverflow(() => true, 1); // label 1 can never fit
    stubOverflow(() => Number(ownVar(0, "f") || sizeVar("f")) > 200, 0);
    await loadScript();

    label(0).click();
    move("f", "300");

    expect(ownVar(0, "f")).toBe("200");
  });
});
