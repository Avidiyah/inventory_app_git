// GET /items/labels: the label sliders. labels.css sizes every label from
// --w / --h (inches), the barcode from --b (% of label height) and the text
// from --f (% on top of the label-size scaling); CSP drops inline styles,
// so they are set through CSSOM. The last values are remembered per
// browser.
//
// Growing the barcode or text past what a label can hold snaps that slider
// back to the largest value that fits; resizing a label shrinks the text
// the same way. Moving a slider down is never blocked.
const root = document.documentElement;
const UNIT = { w: '"', h: '"', b: "%", f: "%" };
const labels = document.getElementsByClassName("label");
const sliders = Object.fromEntries(
  [...document.querySelectorAll("input[data-var]")].map((s) => [s.dataset.var, s]),
);

// +1px tolerance: scrollHeight rounds, so an exact fit can read 1px over.
const overflows = () => [...labels].some((l) => l.scrollHeight > l.clientHeight + 1);

function apply(slider) {
  const name = slider.dataset.var;
  root.style.setProperty(`--${name}`, slider.value);
  slider.nextElementSibling.textContent = `${slider.value}${UNIT[name]}`;
  try { localStorage.setItem(`labels.${name}`, slider.value); } catch { /* storage blocked */ }
}

// Binary-search the largest step at or below the slider's value where no
// label overflows; the minimum if none does. Assumes bigger never fits better.
function fitDown(slider) {
  if (!slider || !overflows()) return;
  const min = Number(slider.min);
  const step = Number(slider.step);
  const at = (i) => { slider.value = String(min + i * step); apply(slider); };
  let lo = 0;
  let hi = Math.round((Number(slider.value) - min) / step) - 1;
  let best = 0;
  while (lo <= hi) {
    const mid = (lo + hi) >> 1;
    at(mid);
    if (overflows()) hi = mid - 1;
    else { best = mid; lo = mid + 1; }
  }
  at(best);
}

for (const slider of Object.values(sliders)) {
  try {
    const saved = localStorage.getItem(`labels.${slider.dataset.var}`);
    if (saved !== null) slider.value = saved; // a range input clamps to min/max
  } catch { /* storage blocked */ }
  apply(slider);
  slider.addEventListener("input", () => {
    const name = slider.dataset.var;
    // The applied CSS value, not a cached one: fitDown may have moved it.
    const grew = Number(slider.value) > Number(root.style.getPropertyValue(`--${name}`));
    apply(slider);
    if (name === "w" || name === "h") fitDown(sliders.f);
    else if (grew) fitDown(slider);
  });
}
fitDown(sliders.f); // saved text may be too big for the labels now shown
