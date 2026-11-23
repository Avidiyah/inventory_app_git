// views/hubPatch.js: the one patch path every hub tab paints through (W7
// rules 1, 2, 8).

import { beforeEach, describe, expect, it } from "vitest";
import { importView } from "../helpers/shell.js";

let patchHub;
let mount;

beforeEach(async () => {
  ({ patchHub } = await importView("views/hubPatch.js"));
  mount = document.createElement("div");
  document.body.replaceChildren(mount);
});

const FLASH = { flashSelector: ".row[id]" };

describe("patchHub", () => {
  it("keeps a focused input's value", () => {
    patchHub(mount, `<input id="f" value="a">`);
    const input = mount.querySelector("#f");
    input.focus();
    input.value = "typed";
    patchHub(mount, `<input id="f" value="b">`);
    expect(mount.querySelector("#f")).toBe(input);
    expect(input.value).toBe("typed");
  });

  it("keeps a dirty field", () => {
    patchHub(mount, `<input id="f" value="a"><button id="b">x</button>`);
    mount.querySelector("#f").value = "typed";
    mount.querySelector("#b").focus();
    patchHub(mount, `<input id="f" value="server"><button id="b">x</button>`);
    expect(mount.querySelector("#f").value).toBe("typed");
  });

  it("leaves a .punch-editor subtree untouched", () => {
    patchHub(mount, `<div class="host"></div>`);
    const editor = document.createElement("div");
    editor.className = "punch-editor";
    editor.textContent = "editing";
    mount.querySelector(".host").appendChild(editor);
    patchHub(mount, `<div class="host"><div class="punch-editor">fresh</div></div>`);
    expect(mount.querySelector(".punch-editor")).toBe(editor);
    expect(editor.textContent).toBe("editing");
  });

  it("leaves an element matching skipSelector untouched", () => {
    patchHub(mount, `<div id="slot"></div>`);
    const kept = document.createElement("p");
    mount.querySelector("#slot").appendChild(kept);
    patchHub(mount, `<div id="slot"></div>`, { skipSelector: "#slot" });
    expect(mount.querySelector("#slot p")).toBe(kept);
  });

  it("keeps an open details open", () => {
    patchHub(mount, `<details id="d"><summary>s</summary>body</details>`);
    mount.querySelector("#d").open = true;
    patchHub(mount, `<details id="d"><summary>s</summary>body 2</details>`);
    expect(mount.querySelector("#d").open).toBe(true);
  });

  it("flags a changed [id] element with just-changed", () => {
    patchHub(mount, `<p class="row" id="r1">1</p><p class="row" id="r2">2</p>`, FLASH);
    patchHub(mount, `<p class="row" id="r1">1</p><p class="row" id="r2">3</p>`, FLASH);
    expect(mount.querySelector("#r1").classList.contains("just-changed")).toBe(false);
    expect(mount.querySelector("#r2").classList.contains("just-changed")).toBe(true);
  });

  it("a first draw over a skeleton flags nothing", () => {
    mount.innerHTML = `<div class="skel-grid"></div>`;
    patchHub(mount, `<p class="row" id="r1">1</p>`, FLASH);
    expect(mount.querySelector(".just-changed")).toBeNull();
  });

  it("an unchanged repaint flags nothing", () => {
    patchHub(mount, `<p class="row" id="r1">1</p>`, FLASH);
    patchHub(mount, `<p class="row" id="r1">1</p>`, FLASH);
    expect(mount.querySelector(".just-changed")).toBeNull();
  });
});

describe("patchHub glow", () => {
  it("a second repaint before the glow ends keeps it", () => {
    patchHub(mount, `<p class="row" id="r1">1</p>`, FLASH);
    patchHub(mount, `<p class="row" id="r1">2</p>`, FLASH);
    patchHub(mount, `<p class="row" id="r1">2</p>`, FLASH);
    expect(mount.querySelector("#r1").classList.contains("just-changed")).toBe(true);
  });
});
