// View helper: the User Hub's phone section picker.
//
// Layer: views. One card shows the current section; opening it lists every
// section the viewer can see. Desktop never shows the toggle. Split out of
// userHub.js (W7) to keep that file under the line cap.

const sectionPicker = document.getElementById("hub-picker");
const sectionToggle = document.getElementById("hub-picker-toggle");

function setPickerOpen(open) {
  if (!sectionPicker || !sectionToggle) return;
  sectionPicker.classList.toggle("open", open);
  sectionToggle.setAttribute("aria-expanded", String(open));
}

export function syncSectionPicker(name) {
  if (!sectionPicker) return;
  sectionPicker.dataset.current = name;
  const btn = document.getElementById(`hub-tab-${name}`);
  document.getElementById("hub-picker-label").textContent = btn ? btn.textContent : name;
  setPickerOpen(false);
}

sectionToggle?.addEventListener("click", () => setPickerOpen(!sectionPicker.classList.contains("open")));
document.addEventListener("click", (e) => {
  if (sectionPicker?.classList.contains("open") && !sectionPicker.contains(e.target)) setPickerOpen(false);
});
document.addEventListener("keydown", (e) => {
  if (e.key === "Escape" && sectionPicker?.classList.contains("open")) {
    setPickerOpen(false);
    sectionToggle.focus();
  }
});

