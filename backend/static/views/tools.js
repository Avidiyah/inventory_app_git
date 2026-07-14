// View: tools list, Add Tool form, and the Tools page (Find/Scan/Edit).
//
// Layer: views. Owns two physically separate DOM regions:
//
// 1. The "Add Tool" card on the Add Item page (`create-item.html`) --
//    mirrors `items.js`'s create-item form binding, just for a different
//    section on the same page.
// 2. The Tools page itself (`tools.html`): the table (with each tool's
//    on-hand count and current custody breakdown), search filtering, row
//    actions (Checkout / Edit / Archive for Admin+, Return for any role
//    that currently holds the tool), and the Tools-page scanner.
//
// Checkout and Return each have their own contextual sub-flow module
// (`toolCheckout.js` / `toolReturn.js`, mirroring `correction.js`'s
// open/close/save shape); the Edit Tool sub-flow is small enough to live
// here alongside the table it belongs to.

import { getTools, setTools, getRole, getUsers, getCurrentUser } from "../state.js";
import {
  apiListTools,
  apiCreateTool,
  apiUpdateTool,
  apiDeleteTool,
  apiGetToolByBarcode,
} from "../api.js";
import { escapeHtml, friendlyError } from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";
import { roleAtLeast } from "../roles.js";
import { mountScanner } from "./scan.js";
import { initSubNav } from "./subnav.js";
import { openToolCheckout, closeToolCheckout, setOnSaved as setOnCheckoutSaved } from "./toolCheckout.js";
import {
  openToolReturn,
  closeToolReturn,
  getReturningToolId,
  setOnSaved as setOnReturnSaved,
} from "./toolReturn.js";
import {
  openToolCorrection,
  closeToolCorrection,
  getCorrectingToolId,
  setOnSaved as setOnCorrectionSaved,
} from "./toolCorrection.js";

// --- Add Tool form (elements live on the Add Item page) ----------------

const createToolBtn = document.getElementById("create-tool-btn");
const createToolMessage = document.getElementById("create-tool-message");
const toolBarcodeInput = document.getElementById("tool-barcode");
const toolNameInput = document.getElementById("tool-name");
const toolQuantityInput = document.getElementById("tool-quantity");

createToolBtn.addEventListener("click", async () => {
  const barcode = toolBarcodeInput.value.trim();
  const name = toolNameInput.value.trim();
  const quantity = toolQuantityInput.value;
  setMessage(createToolMessage, "", "");

  if (!barcode || !name) {
    setMessage(createToolMessage, "Enter a barcode and a tool name.", "error");
    return;
  }

  try {
    await apiCreateTool({
      barcode,
      name,
      quantity: quantity === "" ? 1 : parseFloat(quantity),
    });
    setMessage(createToolMessage, "Tool saved.", "success");
    toolBarcodeInput.value = "";
    toolNameInput.value = "";
    toolQuantityInput.value = "1";
  } catch (err) {
    setMessage(createToolMessage, friendlyError(err, "Could not save the tool. Try again."), "error");
  }
});

// --- Tools page table ---------------------------------------------------

const toolsTheadRow = document.getElementById("tools-thead-row");
const toolsTbody = document.getElementById("tools-tbody");
const toolsSearch = document.getElementById("tools-search");
const toolsMessage = document.getElementById("tools-message");

export async function loadTools() {
  toolsTbody.innerHTML = `<tr><td colspan="5" class="hint">Loading…</td></tr>`;
  try {
    const tools = await apiListTools();
    setTools(tools);
    renderTools();
  } catch (error) {
    toolsTbody.innerHTML =
      `<tr><td colspan="5" class="error">${escapeHtml(friendlyError(error, "Could not load tools. Try again."))}</td></tr>`;
  }
}

function custodyCell(tool) {
  if (!tool.custody || tool.custody.length === 0) return "—";
  return tool.custody
    .map(c => `${escapeHtml(c.username)}: ${escapeHtml(c.quantity)}`)
    .join("<br>");
}

function currentUserCustody(tool) {
  const me = getCurrentUser();
  if (!me || !tool.custody) return null;
  return tool.custody.find(c => c.user_id === me.id) || null;
}

function actionsCell(tool) {
  const canAdmin = roleAtLeast(getRole(), "admin");
  const options = [];
  if (canAdmin) {
    options.push(`<option value="checkout">Check Out</option>`);
  }
  if (currentUserCustody(tool)) {
    options.push(`<option value="return">Return</option>`);
  }
  if (canAdmin) {
    options.push(`<option value="edit">Edit</option>`);
    options.push(`<option value="correct">Correct Count</option>`);
    options.push(`<option value="delete">Archive</option>`);
  }
  if (options.length === 0) return "";
  const ariaLabel = `Actions for ${tool.name}`;
  return `<label class="sr-only" for="tool-row-actions-${tool.id}">${escapeHtml(ariaLabel)}</label>
     <select id="tool-row-actions-${tool.id}" class="row-actions-select" data-id="${tool.id}" aria-label="${escapeHtml(ariaLabel)}">
       <option value="" disabled selected>Actions</option>
       ${options.join("")}
     </select>`;
}

export function renderTools() {
  const term = toolsSearch.value.trim().toLowerCase();
  const all = getTools();
  const tools = term
    ? all.filter(tool =>
        tool.name.toLowerCase().includes(term) ||
        tool.barcode.toLowerCase().includes(term))
    : all;

  toolsTheadRow.innerHTML = `
    <th>Barcode</th>
    <th>Name</th>
    <th>On Hand</th>
    <th>Checked Out</th>
    <th>Actions</th>
  `;

  toolsTbody.innerHTML = "";
  if (tools.length === 0) {
    const row = document.createElement("tr");
    const text = term ? "No tools match that search." : "No tools yet.";
    row.innerHTML = `<td colspan="5">${escapeHtml(text)}</td>`;
    toolsTbody.appendChild(row);
    return;
  }

  tools.forEach(tool => {
    const row = document.createElement("tr");
    row.innerHTML = `
      <td data-label="Barcode">${escapeHtml(tool.barcode)}</td>
      <td data-primary>${escapeHtml(tool.name)}</td>
      <td data-label="On Hand"><strong>${escapeHtml(tool.quantity)}</strong></td>
      <td data-label="Checked Out">${custodyCell(tool)}</td>
      <td data-label="Actions">${actionsCell(tool)}</td>
    `;
    toolsTbody.appendChild(row);
  });
}

toolsSearch.addEventListener("input", renderTools);

setOnCheckoutSaved(loadTools);
setOnReturnSaved(loadTools);
setOnCorrectionSaved(loadTools);

toolsTbody.addEventListener("change", async (event) => {
  const target = event.target;
  if (!target.classList.contains("row-actions-select")) return;

  const action = target.value;
  const toolId = target.dataset.id;
  target.value = "";

  if (!action || !toolId) return;
  const tool = getTools().find(t => t.id === toolId);
  if (!tool) return;

  if (action === "checkout") {
    // Admin+ only (gated by actionsCell); assigned-to picker uses the
    // full users cache since Admin always has it loaded.
    openToolCheckout(tool, getUsers());
    return;
  }

  if (action === "return") {
    const custody = currentUserCustody(tool);
    // Supervisor+ can pick any holder (their users cache is loaded);
    // a Technician only ever sees themselves here (actionsCell already
    // restricts the option to a tool they hold), so toolReturn.js falls
    // back to the current user when the picker is empty.
    const canPickAnyUser = roleAtLeast(getRole(), "supervisor");
    openToolReturn(tool, canPickAnyUser ? getUsers() : [], custody);
    return;
  }

  if (action === "edit") {
    openToolEditor(tool);
    return;
  }

  if (action === "correct") {
    openToolCorrection(tool);
    return;
  }

  if (action === "delete") {
    setMessage(toolsMessage, "", "");
    if (!(await confirmDialog(`Archive "${tool.name}"? It will be hidden from lookup and lists, but its history is kept.`))) return;
    try {
      await apiDeleteTool(toolId);
      if (getEditingToolId() === toolId) closeToolEditor();
      if (getReturningToolId() === toolId) closeToolReturn();
      if (getCorrectingToolId() === toolId) closeToolCorrection();
      setMessage(toolsMessage, `Archived "${tool.name}".`, "success");
      loadTools();
    } catch (err) {
      setMessage(toolsMessage, friendlyError(err, "Could not archive the tool. Try again."), "error");
    }
  }
});

// --- Edit Tool sub-flow ---------------------------------------------------

const toolEditorSection = document.getElementById("tool-editor-section");
const toolEditorSelected = document.getElementById("tool-editor-selected");
const toolEditorBarcode = document.getElementById("tool-editor-barcode");
const toolEditorName = document.getElementById("tool-editor-name");
const toolEditorSaveBtn = document.getElementById("tool-editor-save-btn");
const toolEditorCancelBtn = document.getElementById("tool-editor-cancel-btn");
const toolEditorMessage = document.getElementById("tool-editor-message");

let editingToolId = null;

function getEditingToolId() {
  return editingToolId;
}

function openToolEditor(tool) {
  editingToolId = tool.id;
  toolEditorSelected.textContent = `Editing: ${tool.name} (${tool.barcode})`;
  toolEditorBarcode.value = tool.barcode;
  toolEditorName.value = tool.name;
  setMessage(toolEditorMessage, "", "");
  toolEditorSection.hidden = false;
  toolEditorSection.scrollIntoView({ behavior: "smooth", block: "start" });
}

function closeToolEditor() {
  editingToolId = null;
  toolEditorSection.hidden = true;
  setMessage(toolEditorMessage, "", "");
}

toolEditorCancelBtn.addEventListener("click", closeToolEditor);

toolEditorSaveBtn.addEventListener("click", async () => {
  if (!editingToolId) return;
  const barcode = toolEditorBarcode.value.trim();
  const name = toolEditorName.value.trim();
  setMessage(toolEditorMessage, "", "");

  if (!barcode || !name) {
    setMessage(toolEditorMessage, "Barcode and name are required.", "error");
    return;
  }

  try {
    await apiUpdateTool(editingToolId, { barcode, name });
    setMessage(toolEditorMessage, "Tool updated.", "success");
    loadTools();
    setTimeout(closeToolEditor, 1000);
  } catch (err) {
    setMessage(toolEditorMessage, friendlyError(err, "Could not save the tool. Try again."), "error");
  }
});

// --- Tools-page scanner ---------------------------------------------------

const toolsScanInput = document.getElementById("tools-scan-input");
const toolsScanMessage = document.getElementById("tools-scan-message");
const toolsScanChooser = document.getElementById("tools-scan-chooser");

let toolsSubNav = null;

export const toolsScanner = mountScanner({
  inputEl: toolsScanInput,
  messageEl: toolsScanMessage,
  chooserEl: toolsScanChooser,
  allowCreate: false, // Add Tool only lives on the Add Item page.
  lookupFn: apiGetToolByBarcode,
  notFoundLabel: "tool",
  onItemFound: (tool) => {
    if (toolsSubNav) toolsSubNav.showFeature("find");
    toolsSearch.value = tool.barcode;
    renderTools();
    const row = toolsTbody.querySelector("tr");
    if (row && typeof row.scrollIntoView === "function") {
      row.scrollIntoView({ behavior: "smooth", block: "center" });
    }
  },
  liveEls: {
    videoEl: document.getElementById("tools-scan-video"),
    scanBtn: document.getElementById("tools-scan-scan-btn"),
    uploadBtn: document.getElementById("tools-scan-upload-btn"),
    torchBtn: document.getElementById("tools-scan-torch-btn"),
    aimboxEl: document.getElementById("tools-scan-aimbox"),
  },
});

toolsSubNav = initSubNav(document.getElementById("tools-page"), {
  onShow(feature, prev) {
    if (prev === "scan" && feature !== "scan") toolsScanner.stopLive();
    if (feature === "scan") toolsScanner.refreshPermissionState();
    if (prev && prev !== feature) {
      closeToolEditor();
      closeToolCheckout();
      closeToolReturn();
      closeToolCorrection();
    }
  },
});
