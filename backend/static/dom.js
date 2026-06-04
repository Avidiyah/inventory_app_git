// Foundation: small DOM helpers shared by views.
//
// Layer: foundation. Lives below the views so any number of them
// can write status messages or read note-editor inputs without
// duplicating selectors.

// Set a status message and CSS class on an arbitrary element.
// Passing an empty `text` clears the line; an empty `type` removes
// any styling so the element returns to a neutral state.
export function setMessage(element, text, type) {
  element.textContent = text || "";
  element.className = type || "";
}

// The notes editor builds rows containing a single `.note-value`
// input. Reading the raw string is centralised here so the editor
// view does not have to know the internal markup.
export function getNoteValueRaw(wrapper) {
  const el = wrapper.querySelector(".note-value");
  return el ? el.value : "";
}
