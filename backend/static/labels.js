// GET /items/labels: the label-size sliders. labels.css sizes every label
// (and scales its text) from the unitless inch values --w / --h; CSP drops
// inline styles, so they are set through CSSOM. The last size is
// remembered per browser.
const root = document.documentElement;

for (const slider of document.querySelectorAll("input[data-var]")) {
  const key = `labels.${slider.dataset.var}`;
  const apply = () => {
    root.style.setProperty(`--${slider.dataset.var}`, slider.value);
    slider.nextElementSibling.textContent = `${slider.value}"`;
    try { localStorage.setItem(key, slider.value); } catch { /* storage blocked */ }
  };
  try {
    const saved = localStorage.getItem(key);
    if (saved !== null) slider.value = saved; // a range input clamps to min/max
  } catch { /* storage blocked */ }
  apply();
  slider.addEventListener("input", apply);
}
