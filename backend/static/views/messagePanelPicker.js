// View helpers for the message panel: DOM builders and the filterable
// people checklist shared by New group and Message many.
//
// Layer: views. Filtering hides rows and never unticks them, so a pick made
// before the filter changed is kept. User strings go through textContent.

export function h(tag, className, text) {
  const node = document.createElement(tag);
  if (className) node.className = className;
  if (text !== undefined && text !== null) node.textContent = text;
  return node;
}

export function button(className, text, onClick, label) {
  const node = h("button", className, text);
  node.type = "button";
  if (label) node.setAttribute("aria-label", label);
  node.addEventListener("click", onClick);
  return node;
}

// `text` as an array of nodes with the first match of `q` wrapped in <mark>.
export function marked(text, q) {
  const i = q ? text.toLowerCase().indexOf(q.toLowerCase()) : -1;
  if (i < 0) return [text];
  const hit = h("mark", "", text.slice(i, i + q.length));
  return [text.slice(0, i), hit, text.slice(i + q.length)];
}

// Live, client-side people filter: name only, case-insensitive, anywhere.
export const nameMatches = (name, q) => !q || String(name || "").toLowerCase().includes(q.toLowerCase());

export function filterField() {
  const field = h("input", "msg-field");
  field.type = "search";
  field.placeholder = "Search people";
  field.setAttribute("aria-label", "Search people");
  return field;
}

// A checklist of `people`. `tools` go above the scroll area, `list` inside it.
// `bulk` adds Select all / Deselect all, which act on the people shown.
export function pickList(people, { title, bulk = false, onChange = () => {} }) {
  const filter = filterField();
  const sec = h("div", "msg-sec", title);
  const boxes = people.map((p) => {
    const box = document.createElement("input");
    box.type = "checkbox";
    box.value = p.id;
    return box;
  });
  const names = people.map(() => h("span", ""));
  const rows = people.map((p, i) => {
    const label = h("label", "msg-pick");
    const text = h("span", "");
    text.append(names[i], " ", h("small", "", p.role_label || ""));
    label.append(boxes[i], text);
    return label;
  });
  const none = h("p", "msg-empty");
  const picked = () => boxes.filter((b) => b.checked).map((b) => b.value);

  const changed = () => {
    const n = picked().length;
    sec.textContent = n ? `${title} · ${n} picked` : title;
    onChange();
  };
  boxes.forEach((b) => b.addEventListener("change", changed));

  const applyFilter = () => {
    const q = filter.value.trim();
    let shown = 0;
    people.forEach((p, i) => {
      const hit = nameMatches(p.name, q);
      rows[i].hidden = !hit;
      names[i].replaceChildren(...marked(p.name, hit ? q : ""));
      if (hit) shown += 1;
    });
    none.textContent = `No one matches "${filter.value.trim()}".`;
    none.hidden = shown > 0;
  };
  filter.addEventListener("input", applyFilter);
  applyFilter();

  const tools = [filter];
  if (bulk) {
    const setShown = (on) => () => {
      rows.forEach((row, i) => { if (!row.hidden) boxes[i].checked = on; });
      changed();
    };
    const pair = h("div", "msg-row-btns");
    pair.append(button("msg-btn small", "Select all", setShown(true)),
      button("msg-btn small", "Deselect all", setShown(false)));
    tools.push(pair);
  }
  return { tools, list: [sec, ...rows, none], picked };
}
