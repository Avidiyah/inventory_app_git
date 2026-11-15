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

// skip: plain HTML fixtures. An element marked data-keep is skipped.
const html = (s) => {
  const wrap = document.createElement("div");
  wrap.innerHTML = s;
  return wrap.childNodes;
};
const keep = (oldEl) => oldEl.hasAttribute("data-keep");

test("a skipped element keeps its attributes, children and field values", () => {
  morphInto(box, html(`<div id="k" class="old" data-keep><span>old</span><input value="x"></div>`));
  const k = el("k");
  const input = k.querySelector("input");
  input.value = "typed";
  morphInto(box, html(`<div id="k" class="new"><b>new</b><input value="y"></div>`), { skip: keep });
  expect(el("k")).toBe(k);
  expect(k.className).toBe("old");
  expect(k.hasAttribute("data-keep")).toBe(true);
  expect(k.querySelector("span").textContent).toBe("old");
  expect(k.querySelector("b")).toBeNull();
  expect(k.querySelector("input")).toBe(input);
  expect(input.value).toBe("typed");
  expect(input.getAttribute("value")).toBe("x");
});

test("siblings of a skipped element still update", () => {
  morphInto(box, html(`<p id="s1">a</p><div id="k" data-keep>old</div><p id="s2">b</p>`));
  morphInto(box, html(`<p id="s1">A</p><div id="k">new</div><p id="s2">B</p><p id="s3">C</p>`), { skip: keep });
  expect([...box.children].map((n) => n.textContent)).toEqual(["A", "old", "B", "C"]);
});

test("a skipped element absent from the new tree is still removed", () => {
  morphInto(box, html(`<div id="k" data-keep>old</div><p id="s1">a</p>`));
  morphInto(box, html(`<p id="s1">a</p>`), { skip: keep });
  expect(el("k")).toBeNull();
  expect(box.children).toHaveLength(1);
});

test("a skipped element with an id is never paired with a different id", () => {
  morphInto(box, html(`<div id="a" data-keep>A</div><div id="b">B</div><div id="c">C</div>`));
  const a = el("a");
  const seen = [];
  morphInto(box, html(`<div id="c">C2</div><div id="x">X</div><div id="a">A2</div>`), {
    skip: (oldEl, newEl) => {
      if (oldEl.hasAttribute("data-keep")) seen.push([oldEl.id, newEl.id]);
      return keep(oldEl);
    },
  });
  expect(el("a")).toBe(a);
  expect(a.textContent).toBe("A");
  expect(box.querySelectorAll("#a")).toHaveLength(1);
  expect(seen.every(([o, n]) => o === n)).toBe(true);
  expect([...box.children].map((n) => n.id)).toEqual(["c", "x", "a"]);
  expect(el("b")).toBeNull();
});

test("skip is not called for text nodes", () => {
  morphInto(box, html(`text<p id="s1">a</p>more`));
  const skip = (oldEl) => {
    if (oldEl.nodeType !== 1) throw new Error("skip called for a non-element");
    return false;
  };
  expect(() => morphInto(box, html(`TEXT<p id="s1">b</p>MORE`), { skip })).not.toThrow();
  expect(box.textContent).toBe("TEXTbMORE");
});

test("skip receives the new element it was paired with", () => {
  morphInto(box, html(`<div id="k" data-keep>old</div>`));
  let paired = null;
  morphInto(box, html(`<div id="k" class="fresh">new</div>`), {
    skip: (oldEl, newEl) => {
      if (oldEl.id === "k") paired = newEl;
      return true;
    },
  });
  expect(paired?.className).toBe("fresh");
  expect(paired?.textContent).toBe("new");
});

test("with no skip, behaviour is unchanged", () => {
  morphInto(box, html(`<div id="k" class="old" data-keep>old</div>`));
  const k = el("k");
  morphInto(box, html(`<div id="k" class="new">new</div>`));
  expect(el("k")).toBe(k);
  expect(k.className).toBe("new");
  expect(k.hasAttribute("data-keep")).toBe(false);
  expect(k.textContent).toBe("new");
});
