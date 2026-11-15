// morphInto: patch a container in place, leave `open` to the user, flag what
// changed. Plain <details id> fixtures; no app modules.

import { beforeEach, expect, test } from "vitest";
import { morphInto } from "../../../backend/static/morph.js";

let box;
beforeEach(() => {
  document.body.innerHTML = `<div id="box"></div>`;
  box = document.getElementById("box");
});

// "g1:a,b g2:c" -> two groups of rows. A trailing "+" opens the group; a row
// written "a=text" carries that text.
function nodes(spec) {
  const wrap = document.createElement("div");
  wrap.innerHTML = spec.split(" ").map((part) => {
    const [head, rows = ""] = part.split(":");
    const open = head.endsWith("+");
    const rowHtml = rows.split(",").filter(Boolean).map((row) => {
      const [id, text = id] = row.split("=");
      return `<details class="row" id="${id}"><summary>${text}</summary><input></details>`;
    }).join("");
    return `<details class="group" id="${head.replace("+", "")}"${open ? " open" : ""}>` +
      `<summary>${head}</summary>${rowHtml}</details>`;
  }).join("");
  return wrap.childNodes;
}
const el = (id) => document.getElementById(id);
const flagged = () => [...box.querySelectorAll(".just-changed")].map((n) => n.id);
const FLASH = { flashSelector: ".row", flashKey: (n) => n.querySelector("summary").textContent };

test("open belongs to the user; a new details keeps what its builder gave it", () => {
  morphInto(box, nodes("g1+:a g2:b"));
  el("g1").open = false;
  el("g2").open = true;
  el("a").open = true;
  morphInto(box, nodes("g1+:a g2:b g3+:c"));
  expect([el("g1").open, el("g2").open, el("a").open, el("g3").open]).toEqual([false, true, true, true]);
});

test("matched elements keep identity, move between parents, and unmatched ones come and go", () => {
  morphInto(box, nodes("g1:a,b g2:c"));
  const a = el("a");
  morphInto(box, nodes("g1:b g2:a,d"));
  expect(el("a")).toBe(a);
  expect(a.parentElement.id).toBe("g2");
  expect(el("c")).toBeNull();
  expect(el("d").parentElement.id).toBe("g2");
});

test("does not overwrite the focused input's value", () => {
  morphInto(box, nodes("g1+:a"));
  const input = el("a").querySelector("input");
  el("a").open = true;
  input.focus();
  input.value = "half-typed";
  morphInto(box, nodes("g1+:a=changed"));
  expect(input.value).toBe("half-typed");
  expect(document.activeElement).toBe(input);
});

test("flags new and changed elements only, and never on a first draw", () => {
  morphInto(box, nodes("g1:a,b"), FLASH);
  expect(flagged()).toEqual([]);
  morphInto(box, nodes("g1:a,b=edited,c"), FLASH);
  expect(flagged()).toEqual(["b", "c"]);
});

test("a second morph clears the first one's flags; animationend clears its own", () => {
  morphInto(box, nodes("g1:a,b"), FLASH);
  morphInto(box, nodes("g1:a=x,b"), FLASH);
  morphInto(box, nodes("g1:a=x,b=y"), FLASH);
  expect(flagged()).toEqual(["b"]);
  el("b").dispatchEvent(new Event("animationend", { bubbles: true }));
  expect(flagged()).toEqual([]);
});

test("with no flashSelector, adds no class", () => {
  morphInto(box, nodes("g1:a"));
  morphInto(box, nodes("g1:a=x,b"));
  expect(flagged()).toEqual([]);
});
