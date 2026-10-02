// GET /items/labels: the label sliders and label selection. labels.css
// sizes each label from --w / --h (inches), its barcode from --b (% of
// label height) and its text from --f (% on top of the label-size
// scaling); CSP drops inline styles, so they are set through CSSOM.
//
// Sliders act on the selected labels (click or Space/Enter toggles one;
// "Select all" toggles every one). With none or all selected they act on
// the whole page: set on <html>, clearing single-label tweaks, and
// remembered per browser. A partial selection's tweaks are per label and
// not remembered -- the labels shown change with the location.
//
// Growing the barcode or text past what a label can hold snaps that slider
// back to the largest value that fits; resizing a label shrinks the text
// the same way. Moving a slider down is never blocked.
const root = document.documentElement;
const UNIT = { w: '"', h: '"', b: "%", f: "%" };
const labels = [...document.getElementsByClassName("label")];
const sliders = Object.fromEntries(
  [...document.querySelectorAll("input[data-var]")].map((s) => [s.dataset.var, s]),
);
const selectAll = document.getElementById("select-all");

const selected = () => labels.filter((l) => l.classList.contains("selected"));
// The labels a slider acts on, or null for the whole page.
function scope() {
  const picked = selected();
  return picked.length && picked.length < labels.length ? picked : null;
}
// A label's own tweak, else the page-wide value.
const valueOf = (label, name) =>
  label?.style.getPropertyValue(`--${name}`) || root.style.getPropertyValue(`--${name}`);

// +1px tolerance: scrollHeight rounds, so an exact fit can read 1px over.
const overflows = (some) => some.some((l) => l.scrollHeight > l.clientHeight + 1);

function show(slider) {
  slider.nextElementSibling.textContent = `${slider.value}${UNIT[slider.dataset.var]}`;
}

function apply(slider, some) {
  const prop = `--${slider.dataset.var}`;
  show(slider);
  if (some) {
    for (const l of some) l.style.setProperty(prop, slider.value);
    return;
  }
  root.style.setProperty(prop, slider.value);
  for (const l of labels) l.style.removeProperty(prop);
  try { localStorage.setItem(`labels.${slider.dataset.var}`, slider.value); } catch { /* storage blocked */ }
}

// Binary-search the largest step at or below the slider's value where none
// of the acted-on labels overflows; the minimum if none does. Assumes
// bigger never fits better.
function fitDown(slider, some) {
  if (!slider || !overflows(some || labels)) return;
  const min = Number(slider.min);
  const step = Number(slider.step);
  const at = (i) => { slider.value = String(min + i * step); apply(slider, some); };
  let lo = 0;
  let hi = Math.round((Number(slider.value) - min) / step) - 1;
  let best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    at(mid);
    if (overflows(some || labels)) hi = mid - 1;
    else { best = mid; lo = mid + 1; }
  }
  at(best);
}

// Point the sliders at the first acted-on label's values and the checkbox
// at the selection.
function syncControls() {
  const first = scope()?.[0];
  for (const s of Object.values(sliders)) {
    s.value = valueOf(first, s.dataset.var);
    show(s);
  }
  const count = selected().length;
  selectAll.checked = count > 0 && count === labels.length;
  selectAll.indeterminate = count > 0 && count < labels.length;
}

function select(label, on) {
  label.classList.toggle("selected", on);
  label.setAttribute("aria-checked", String(on));
}

for (const slider of Object.values(sliders)) {
  try {
    const saved = localStorage.getItem(`labels.${slider.dataset.var}`);
    if (saved !== null) slider.value = saved; // a range input clamps to min/max
  } catch { /* storage blocked */ }
  apply(slider, null);
  slider.addEventListener("input", () => {
    const some = scope();
    const name = slider.dataset.var;
    // The applied value, not a cached one: fitDown may have moved it.
    const grew = Number(slider.value) > Number(valueOf(some?.[0], name));
    apply(slider, some);
    if (name === "w" || name === "h") fitDown(sliders.f, some);
    else if (grew) fitDown(slider, some);
  });
}

for (const label of labels) {
  const toggle = () => { select(label, !label.classList.contains("selected")); syncControls(); };
  label.addEventListener("click", toggle);
  label.addEventListener("keydown", (event) => {
    if (event.key !== " " && event.key !== "Enter") return;
    event.preventDefault();
    toggle();
  });
}

selectAll.addEventListener("change", () => {
  for (const label of labels) select(label, selectAll.checked);
  syncControls();
});

fitDown(sliders.f, null); // saved text may be too big for the labels now shown
