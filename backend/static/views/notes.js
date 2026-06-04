// View: notes editor (modal-style panel on the Entry page).
//
// Layer: views. Owns the JSONB notes editor that opens when the
// user clicks "Edit Notes" on an item row. Three exported pieces:
//
// - `renderNotesSummary(notes)` -> HTML string used by `items.js`
//   inside the notes cell. Kept here so the rendering rules live
//   next to the editor's input rules.
// - `openNotesEditor(itemId, itemName)` populates and reveals the
//   editor for an item; `closeNotesEditor()` hides it.
// - `setOnSaved(fn)` lets the items view register a callback so
//   the table is refreshed after a successful save.
//
// The editor renders one input per note key. Type select
// (string/number/boolean) drives `renderNoteValueInput`, which
// swaps the value control. Backend whitelist (str/int/float/bool)
// is mirrored here intentionally -- the client UX requires the
// type metadata that the JSONB blob does not preserve.

import { getItems, getEditingNotesItemId, setEditingNotesItemId } from "../state.js";
import { apiUpdateNotes } from "../api.js";
import { escapeHtml, formatNoteValue, detectNoteType, formatError } from "../format.js";
import { setMessage, getNoteValueRaw } from "../dom.js";

const notesEditorSection = document.getElementById("notes-editor-section");
const notesEditorSelected = document.getElementById("notes-editor-selected");
const notesRows = document.getElementById("notes-rows");
const notesAddRowBtn = document.getElementById("notes-add-row-btn");
const notesSaveBtn = document.getElementById("notes-save-btn");
const notesCancelBtn = document.getElementById("notes-cancel-btn");
const notesMessage = document.getElementById("notes-message");

let onSavedCallback = null;

export function setOnSaved(fn) {
  onSavedCallback = fn;
}

export function renderNotesSummary(notes) {
  if (!notes || typeof notes !== "object" || Object.keys(notes).length === 0) {
    return '<span class="empty">—</span>';
  }
  return Object.entries(notes)
    .map(([k, v]) => `${escapeHtml(k)}: ${escapeHtml(formatNoteValue(v))}`)
    .join(", ");
}

export function openNotesEditor(itemId, itemName) {
  const item = getItems().find(i => i.id === itemId);
  if (!item) return;

  setEditingNotesItemId(itemId);
  notesEditorSelected.textContent = `Editing notes for: ${itemName}`;
  setMessage(notesMessage, "", "");
  notesRows.innerHTML = "";

  const entries = Object.entries(item.notes || {});
  if (entries.length === 0) {
    addNoteRow();
  } else {
    entries.forEach(([k, v]) => addNoteRow(k, detectNoteType(v), v));
  }

  notesEditorSection.hidden = false;
  notesEditorSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

export function closeNotesEditor() {
  setEditingNotesItemId(null);
  notesEditorSection.hidden = true;
  notesRows.innerHTML = "";
  setMessage(notesMessage, "", "");
}

function addNoteRow(key = "", type = "string", value = "") {
  const row = document.createElement("div");
  row.className = "note-row";
  row.innerHTML = `
    <input type="text" class="note-key" placeholder="Key" value="${escapeHtml(key)}">
    <select class="note-type">
      <option value="string">String</option>
      <option value="number">Number</option>
      <option value="boolean">Boolean</option>
    </select>
    <span class="note-value-wrapper"></span>
    <button type="button" class="note-remove-btn" title="Remove">×</button>
  `;
  const typeSelect = row.querySelector(".note-type");
  typeSelect.value = type;
  const valueWrapper = row.querySelector(".note-value-wrapper");
  renderNoteValueInput(valueWrapper, type, value);

  typeSelect.addEventListener("change", () => {
    renderNoteValueInput(valueWrapper, typeSelect.value, getNoteValueRaw(valueWrapper));
  });

  row.querySelector(".note-remove-btn").addEventListener("click", () => row.remove());

  notesRows.appendChild(row);
}

function renderNoteValueInput(wrapper, type, currentValue) {
  wrapper.innerHTML = "";
  if (type === "boolean") {
    const sel = document.createElement("select");
    sel.className = "note-value";
    sel.innerHTML = '<option value="true">true</option><option value="false">false</option>';
    sel.value = (currentValue === true || currentValue === "true") ? "true" : "false";
    wrapper.appendChild(sel);
  } else if (type === "number") {
    const input = document.createElement("input");
    input.type = "number";
    input.step = "any";
    input.className = "note-value";
    input.placeholder = "Number";
    input.value = (currentValue === "" || currentValue === null || currentValue === undefined) ? "" : currentValue;
    wrapper.appendChild(input);
  } else {
    const input = document.createElement("input");
    input.type = "text";
    input.className = "note-value";
    input.placeholder = "Value";
    input.value = (currentValue === null || currentValue === undefined) ? "" : String(currentValue);
    wrapper.appendChild(input);
  }
}

notesAddRowBtn.addEventListener("click", () => addNoteRow());
notesCancelBtn.addEventListener("click", closeNotesEditor);

notesSaveBtn.addEventListener("click", async () => {
  setMessage(notesMessage, "", "");

  const editingId = getEditingNotesItemId();
  if (!editingId) {
    setMessage(notesMessage, "No item selected.", "error");
    return;
  }

  const rows = notesRows.querySelectorAll(".note-row");
  const collected = {};
  const seenKeys = new Set();

  for (const row of rows) {
    const key = row.querySelector(".note-key").value.trim();
    if (!key) continue;
    if (seenKeys.has(key)) {
      setMessage(notesMessage, `Duplicate key: "${key}".`, "error");
      return;
    }
    seenKeys.add(key);

    const type = row.querySelector(".note-type").value;
    const rawValue = getNoteValueRaw(row.querySelector(".note-value-wrapper"));

    if (type === "number") {
      if (rawValue === "") {
        setMessage(notesMessage, `Value for "${key}" is required.`, "error");
        return;
      }
      const num = Number(rawValue);
      if (!Number.isFinite(num)) {
        setMessage(notesMessage, `Invalid number for "${key}".`, "error");
        return;
      }
      collected[key] = num;
    } else if (type === "boolean") {
      collected[key] = rawValue === "true";
    } else {
      collected[key] = rawValue;
    }
  }

  try {
    await apiUpdateNotes(editingId, collected);
    setMessage(notesMessage, "Notes saved.", "success");
    if (onSavedCallback) await onSavedCallback();
    setTimeout(closeNotesEditor, 1000);
  } catch (err) {
    if (err && err.status !== undefined) {
      setMessage(notesMessage, formatError(err.detail, "Failed to save notes."), "error");
    } else {
      setMessage(notesMessage, "Could not connect to the server.", "error");
    }
  }
});
