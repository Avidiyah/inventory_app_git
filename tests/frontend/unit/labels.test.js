// static/labels.js: the label print page's size sliders.

import { describe, expect, it } from "vitest";

async function mountPage() {
  document.body.innerHTML = `
    <form class="toolbar">
      <label>Width <input type="range" data-var="w" min="1" max="7.5" step="0.05" value="2.5"><output></output></label>
      <label>Height <input type="range" data-var="h" min="1" max="10" step="0.05" value="3"><output></output></label>
    </form>`;
  await import("../../../backend/static/labels.js");
}

const sizeVar = (name) => document.documentElement.style.getPropertyValue(`--${name}`);
const slider = (name) => document.querySelector(`[data-var="${name}"]`);

describe("label size sliders", () => {
  it("resize the labels as they move and remember the size", async () => {
    await mountPage();

    slider("w").value = "2";
    slider("w").dispatchEvent(new Event("input"));

    expect(sizeVar("w")).toBe("2");
    expect(slider("w").nextElementSibling.textContent).toBe('2"');
    expect(localStorage.getItem("labels.w")).toBe("2");
  });

  it("restore a saved size, clamped to the slider's range", async () => {
    localStorage.setItem("labels.w", "99");
    localStorage.setItem("labels.h", "4.5");

    await mountPage();

    expect(sizeVar("w")).toBe("7.5");
    expect(sizeVar("h")).toBe("4.5");
  });
});
