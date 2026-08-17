// View: Add Tool form plus the user-first Tools page.
//
// Custody is the default feature: TechFM OA and above search active users,
// while Supervisor/Technician opens their own card. Checkout starts from that
// card by tool search or contextual scan; check-in starts from one of the
// selected user's current holdings. Inventory retains lookup and TechFM OA+
// maintenance.

import { getTools, setTools, getRole, getCurrentUser } from "../state.js";
import {
  apiListTools,
  apiListUsers,
  apiCreateTool,
  apiUpdateTool,
  apiDeleteTool,
  apiGetToolByBarcode,
} from "../api.js";
import { escapeHtml, friendlyError, formatUserName, filterRanked } from "../format.js";
import { setMessage, confirmDialog } from "../dom.js";
import { roleAtLeast, roleLabel } from "../roles.js";
import { mountScanner } from "./scan.js";
import { initSubNav } from "./subnav.js";
import {
  openToolCheckout,
  closeToolCheckout,
  setOnSaved as setOnCheckoutSaved,
} from "./toolCheckout.js";
import {
  openToolReturn,
  closeToolReturn,
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

// --- User-first custody state -------------------------------------------

const toolsPage = document.getElementById("tools-page");
const userPicker = document.getElementById("tool-user-picker");
const userSearch = document.getElementById("tool-user-search");
const userResults = document.getElementById("tool-user-results");
const custodyMessage = document.getElementById("tool-custody-message");
const userCard = document.getElementById("tool-user-card");
const userName = document.getElementById("tool-user-name");
const userMeta = document.getElementById("tool-user-meta");
const userStatus = document.getElementById("tool-user-status");
const custodyCount = document.getElementById("tool-user-custody-count");
const holdingsEl = document.getElementById("tool-user-holdings");
const checkoutControls = document.getElementById("tool-checkout-controls");
const checkoutToolSearch = document.getElementById("tool-checkout-search");
const checkoutToolResults = document.getElementById("tool-checkout-results");
const checkoutScanBtn = document.getElementById("tool-checkout-scan-btn");
const checkoutPickerMessage = document.getElementById("tool-checkout-picker-message");

let custodyUsers = [];
let selectedUserId = null;
let activeUserResultIndex = -1;
let visibleUserIds = [];
let scanPurpose = "lookup";
let checkoutScanUserId = null;
let toolsSubNav = null;

function canManageCustody() {
  return roleAtLeast(getRole(), "techfm_oa");
}

function selectedUser() {
  return custodyUsers.find((user) => user.id === selectedUserId) || null;
}

function formattedCreatedAt(value) {
  if (!value) return "Created date unavailable";
  const date = new Date(value);
  return Number.isNaN(date.getTime()) ? "Created date unavailable" : "Created " + date.toLocaleString();
}

function holdingsForUser(userId) {
  return getTools().flatMap((tool) => {
    const custody = (tool.custody || []).find((entry) => entry.user_id === userId);
    return custody ? [{ tool, custody }] : [];
  });
}

function hideUserResults() {
  activeUserResultIndex = -1;
  visibleUserIds = [];
  userResults.innerHTML = "";
  userResults.hidden = true;
  userSearch.setAttribute("aria-expanded", "false");
  userSearch.removeAttribute("aria-activedescendant");
}

function clearCheckoutPicker() {
  checkoutToolSearch.value = "";
  checkoutToolResults.innerHTML = "";
  checkoutToolResults.hidden = true;
  setMessage(checkoutPickerMessage, "", "");
}

function clearSelectedUser() {
  selectedUserId = null;
  userCard.hidden = true;
  holdingsEl.innerHTML = "";
  clearCheckoutPicker();
  closeToolCheckout();
  closeToolReturn();
}

function renderUserCard() {
  const user = selectedUser();
  if (!user) {
    userCard.hidden = true;
    return;
  }

  const holdings = holdingsForUser(user.id);
  userName.textContent = formatUserName(user);
  userMeta.textContent = roleLabel(user.role) + " · " + formattedCreatedAt(user.created_at);
  userStatus.textContent = "Active";
  custodyCount.textContent =
    holdings.length === 1
      ? "1 tool record currently checked out"
      : holdings.length + " tool records currently checked out";

  if (holdings.length === 0) {
    holdingsEl.innerHTML = '<p class="tool-empty-state">No tools currently checked out.</p>';
  } else {
    holdingsEl.innerHTML = holdings
      .map(({ tool, custody }) =>
        '<div class="tool-holding-row">' +
          '<div class="tool-holding-detail">' +
            '<strong>' + escapeHtml(tool.name) + '</strong>' +
            '<span>Barcode: ' + escapeHtml(tool.barcode) + '</span>' +
            '<span>Checked out: ' + escapeHtml(custody.quantity) + '</span>' +
          '</div>' +
          '<button type="button" class="tool-checkin-btn secondary-btn" data-tool-id="' +
            escapeHtml(tool.id) + '">Check In</button>' +
        '</div>'
      )
      .join("");
  }

  checkoutControls.hidden = !canManageCustody();
  userCard.hidden = false;
}

function chooseUser(user) {
  selectedUserId = user.id;
  userSearch.value = formatUserName(user);
  hideUserResults();
  clearCheckoutPicker();
  closeToolCheckout();
  closeToolReturn();
  setMessage(custodyMessage, "", "");
  renderUserCard();
  userCard.focus();
}

function matchingUsers() {
  // Normalized like every other search box, so `O'Brien` is reachable by
  // typing `obrien`. An empty query still matches everyone -- `filterRanked`
  // treats a query with no tokens as "no criteria", and every entry ranks
  // equally, so the original order survives.
  const query = userSearch.value.trim();
  return filterRanked(custodyUsers, (user) => [formatUserName(user)], query)
    .slice(0, 8);
}

function setActiveUserOption(index) {
  const options = Array.from(userResults.querySelectorAll(".tool-user-option"));
  if (options.length === 0) {
    activeUserResultIndex = -1;
    userSearch.removeAttribute("aria-activedescendant");
    return;
  }
  activeUserResultIndex = (index + options.length) % options.length;
  options.forEach((option, optionIndex) => {
    const isActive = optionIndex === activeUserResultIndex;
    option.classList.toggle("is-active", isActive);
    option.setAttribute("aria-selected", String(isActive));
  });
  const active = options[activeUserResultIndex];
  userSearch.setAttribute("aria-activedescendant", active.id);
  active.scrollIntoView({ block: "nearest" });
}

function renderUserResults() {
  const matches = matchingUsers();
  visibleUserIds = matches.map((user) => user.id);
  activeUserResultIndex = -1;
  userSearch.removeAttribute("aria-activedescendant");

  if (matches.length === 0) {
    userResults.innerHTML = '<p class="hint">No matching active users.</p>';
  } else {
    userResults.innerHTML = matches
      .map((user) =>
        '<button type="button" id="tool-user-option-' + escapeHtml(user.id) +
          '" class="manual-item-card tool-user-option" role="option" aria-selected="false" data-user-id="' +
          escapeHtml(user.id) + '">' +
          '<span class="manual-item-name">' + escapeHtml(formatUserName(user)) + '</span>' +
          '<span class="manual-item-meta"><span>' + escapeHtml(roleLabel(user.role)) + '</span></span>' +
        '</button>'
      )
      .join("");
  }
  userResults.hidden = false;
  userSearch.setAttribute("aria-expanded", "true");
}

userSearch.addEventListener("focus", renderUserResults);

userSearch.addEventListener("input", () => {
  const current = selectedUser();
  if (current && userSearch.value !== formatUserName(current)) clearSelectedUser();
  renderUserResults();
});

userSearch.addEventListener("keydown", (event) => {
  if (event.key === "Escape") {
    hideUserResults();
    return;
  }
  if (event.key !== "ArrowDown" && event.key !== "ArrowUp" && event.key !== "Enter") return;
  if (userResults.hidden) renderUserResults();

  if (event.key === "ArrowDown") {
    event.preventDefault();
    setActiveUserOption(activeUserResultIndex + 1);
  } else if (event.key === "ArrowUp") {
    event.preventDefault();
    setActiveUserOption(activeUserResultIndex - 1);
  } else if (event.key === "Enter" && activeUserResultIndex >= 0) {
    event.preventDefault();
    const user = custodyUsers.find((candidate) => candidate.id === visibleUserIds[activeUserResultIndex]);
    if (user) chooseUser(user);
  }
});

userResults.addEventListener("click", (event) => {
  const option = event.target.closest("[data-user-id]");
  if (!option) return;
  const user = custodyUsers.find((candidate) => candidate.id === option.dataset.userId);
  if (user) chooseUser(user);
});

document.addEventListener("click", (event) => {
  if (!userPicker.contains(event.target)) hideUserResults();
  if (!checkoutControls.contains(event.target)) checkoutToolResults.hidden = true;
});

holdingsEl.addEventListener("click", (event) => {
  const button = event.target.closest(".tool-checkin-btn");
  if (!button) return;
  const user = selectedUser();
  const tool = getTools().find((candidate) => candidate.id === button.dataset.toolId);
  const custody = tool && (tool.custody || []).find((entry) => entry.user_id === selectedUserId);
  if (!user || !tool || !custody) return;
  closeToolCheckout();
  openToolReturn(tool, user, custody);
});

// --- Checkout tool search ------------------------------------------------

function availableCheckoutTools() {
  const query = checkoutToolSearch.value.trim();
  const available = getTools().filter((tool) => Number(tool.quantity) > 0);
  return filterRanked(
    available,
    (tool) => [tool.name, tool.barcode],
    query,
    (left, right) => left.name.localeCompare(right.name)
  ).slice(0, 8);
}

function renderCheckoutToolResults() {
  const tools = availableCheckoutTools();
  if (tools.length === 0) {
    checkoutToolResults.innerHTML =
      '<p class="hint">' +
      (checkoutToolSearch.value.trim() ? "No available tools match that search." : "No tools are currently available.") +
      '</p>';
  } else {
    checkoutToolResults.innerHTML = tools
      .map((tool) =>
        '<button type="button" class="manual-item-card" data-checkout-tool-id="' +
          escapeHtml(tool.id) + '">' +
          '<span class="manual-item-name">' + escapeHtml(tool.name) + '</span>' +
          '<span class="manual-item-meta">' +
            '<span>Barcode: ' + escapeHtml(tool.barcode) + '</span>' +
            '<span>On hand: ' + escapeHtml(tool.quantity) + '</span>' +
          '</span>' +
        '</button>'
      )
      .join("");
  }
  checkoutToolResults.hidden = false;
}

checkoutToolSearch.addEventListener("focus", renderCheckoutToolResults);
checkoutToolSearch.addEventListener("input", () => {
  closeToolCheckout();
  renderCheckoutToolResults();
});
checkoutToolSearch.addEventListener("keydown", (event) => {
  if (event.key === "Escape") checkoutToolResults.hidden = true;
  if (event.key === "Enter") {
    const first = checkoutToolResults.querySelector("[data-checkout-tool-id]");
    if (first) {
      event.preventDefault();
      first.click();
    }
  }
});

checkoutToolResults.addEventListener("click", (event) => {
  const option = event.target.closest("[data-checkout-tool-id]");
  if (!option) return;
  const user = selectedUser();
  const tool = getTools().find((candidate) => candidate.id === option.dataset.checkoutToolId);
  if (!user || !tool || Number(tool.quantity) <= 0) return;
  checkoutToolSearch.value = tool.name;
  checkoutToolResults.hidden = true;
  closeToolReturn();
  openToolCheckout(tool, user);
});

// --- Inventory table -----------------------------------------------------

const toolsTheadRow = document.getElementById("tools-thead-row");
const toolsTbody = document.getElementById("tools-tbody");
const toolsSearch = document.getElementById("tools-search");
const toolsMessage = document.getElementById("tools-message");

function custodyCell(tool) {
  if (!tool.custody || tool.custody.length === 0) return "—";
  return tool.custody
    .map((entry) => escapeHtml(entry.user_name) + ": " + escapeHtml(entry.quantity))
    .join("<br>");
}

function actionsCell(tool) {
  if (!canManageCustody()) return "";
  const ariaLabel = "Actions for " + tool.name;
  return '<label class="sr-only" for="tool-row-actions-' + escapeHtml(tool.id) + '">' +
      escapeHtml(ariaLabel) + '</label>' +
    '<select id="tool-row-actions-' + escapeHtml(tool.id) +
      '" class="row-actions-select" data-id="' + escapeHtml(tool.id) +
      '" aria-label="' + escapeHtml(ariaLabel) + '">' +
      '<option value="" disabled selected>Actions</option>' +
      '<option value="edit">Edit</option>' +
      '<option value="correct">Correct Count</option>' +
      '<option value="delete">Archive</option>' +
    '</select>';
}

export function renderTools() {
  const term = toolsSearch.value.trim();
  const all = getTools();
  const filtered = term
    ? filterRanked(all, (tool) => [tool.name, tool.barcode], term)
    : all;
  const showActions = canManageCustody();
  const columnCount = showActions ? 5 : 4;

  toolsTheadRow.innerHTML =
    "<th>Barcode</th><th>Name</th><th>On Hand</th><th>Checked Out</th>" +
    (showActions ? "<th>Actions</th>" : "");
  toolsTbody.innerHTML = "";

  if (filtered.length === 0) {
    const row = document.createElement("tr");
    row.innerHTML = '<td colspan="' + columnCount + '">' +
      escapeHtml(term ? "No tools match that search." : "No tools yet.") + '</td>';
    toolsTbody.appendChild(row);
    return;
  }

  filtered.forEach((tool) => {
    const row = document.createElement("tr");
    row.innerHTML =
      '<td data-label="Barcode">' + escapeHtml(tool.barcode) + '</td>' +
      '<td data-primary>' + escapeHtml(tool.name) + '</td>' +
      '<td data-label="On Hand"><strong>' + escapeHtml(tool.quantity) + '</strong></td>' +
      '<td data-label="Checked Out">' + custodyCell(tool) + '</td>' +
      (showActions ? '<td data-label="Actions">' + actionsCell(tool) + '</td>' : "");
    toolsTbody.appendChild(row);
  });
}

toolsSearch.addEventListener("input", renderTools);

async function refreshTools() {
  try {
    const tools = await apiListTools();
    setTools(tools);
    renderTools();
    renderUserCard();
    return true;
  } catch (error) {
    const message = friendlyError(error, "The change was saved, but tool data could not be refreshed.");
    setMessage(toolsMessage, message, "error");
    setMessage(custodyMessage, message, "error");
    return false;
  }
}

setOnCheckoutSaved(refreshTools);
setOnReturnSaved(refreshTools);
setOnCorrectionSaved(refreshTools);

toolsTbody.addEventListener("change", async (event) => {
  const target = event.target;
  if (!target.classList.contains("row-actions-select")) return;

  const action = target.value;
  const toolId = target.dataset.id;
  target.value = "";
  if (!action || !toolId) return;

  const tool = getTools().find((candidate) => candidate.id === toolId);
  if (!tool) return;

  if (action === "edit") {
    openToolEditor(tool);
    return;
  }
  if (action === "correct") {
    openToolCorrection(tool);
    return;
  }
  if (action !== "delete") return;

  setMessage(toolsMessage, "", "");
  if (!(await confirmDialog('Archive "' + tool.name + '"? Its history will be kept.'))) return;
  try {
    await apiDeleteTool(toolId);
    if (getEditingToolId() === toolId) closeToolEditor();
    if (getCorrectingToolId() === toolId) closeToolCorrection();
    setMessage(toolsMessage, 'Archived "' + tool.name + '".', "success");
    await refreshTools();
  } catch (err) {
    setMessage(toolsMessage, friendlyError(err, "Could not archive the tool. Try again."), "error");
  }
});

// --- Edit Tool sub-flow --------------------------------------------------

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
  toolEditorSelected.textContent = "Editing: " + tool.name + " (" + tool.barcode + ")";
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
    await refreshTools();
    setTimeout(closeToolEditor, 1000);
  } catch (err) {
    setMessage(toolEditorMessage, friendlyError(err, "Could not save the tool. Try again."), "error");
  }
});

// --- Contextual scanner --------------------------------------------------

const toolsScanInput = document.getElementById("tools-scan-input");
const toolsScanMessage = document.getElementById("tools-scan-message");
const toolsScanChooser = document.getElementById("tools-scan-chooser");
const toolsScanHeading = document.getElementById("tools-scan-heading");
const toolsScanHint = document.getElementById("tools-scan-hint");
const scanNavButton = toolsPage.querySelector('.sub-nav-btn[data-feature="scan"]');

function setLookupScanContext() {
  scanPurpose = "lookup";
  checkoutScanUserId = null;
  toolsScanHeading.textContent = "Scan Tool Inventory";
  toolsScanHint.textContent = "Scan a tool's barcode to find it in Inventory.";
}

function setCheckoutScanContext(user) {
  scanPurpose = "checkout";
  checkoutScanUserId = user.id;
  toolsScanHeading.textContent = "Scan Tool for Checkout";
  toolsScanHint.textContent = "Scan a tool to check out to " + formatUserName(user) + ". You will confirm the quantity before saving.";
}

export const toolsScanner = mountScanner({
  inputEl: toolsScanInput,
  messageEl: toolsScanMessage,
  chooserEl: toolsScanChooser,
  allowCreate: false,
  lookupFn: apiGetToolByBarcode,
  notFoundLabel: "tool",
  onItemFound: (tool) => {
    if (scanPurpose === "checkout") {
      const user = custodyUsers.find((candidate) => candidate.id === checkoutScanUserId);
      if (!canManageCustody() || !user) {
        setMessage(toolsScanMessage, "Select an active user before scanning for checkout.", "error");
        return;
      }
      if (Number(tool.quantity) <= 0) {
        setMessage(toolsScanMessage, tool.name + " has no units on hand.", "error");
        return;
      }
      setLookupScanContext();
      toolsSubNav.showFeature("custody");
      closeToolReturn();
      openToolCheckout(tool, user);
      return;
    }

    toolsSubNav.showFeature("inventory");
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

checkoutScanBtn.addEventListener("click", () => {
  const user = selectedUser();
  if (!canManageCustody() || !user) {
    setMessage(checkoutPickerMessage, "Select an active user first.", "error");
    return;
  }
  closeToolCheckout();
  closeToolReturn();
  setCheckoutScanContext(user);
  toolsScanner.reset();
  toolsSubNav.showFeature("scan");
  toolsScanner.refreshPermissionState();
});

scanNavButton.addEventListener("click", () => {
  setLookupScanContext();
  toolsScanner.reset();
  toolsScanner.refreshPermissionState();
});

toolsSubNav = initSubNav(toolsPage, {
  onShow(feature, previous) {
    if (previous === "scan" && feature !== "scan") {
      toolsScanner.stopLive();
      setLookupScanContext();
    }
    if (feature === "scan") toolsScanner.refreshPermissionState();
    if (feature !== "custody") {
      closeToolCheckout();
      closeToolReturn();
      checkoutToolResults.hidden = true;
    }
    if (feature !== "inventory") {
      closeToolEditor();
      closeToolCorrection();
    }
  },
});

// --- Page load / auth reset ---------------------------------------------

export async function loadTools() {
  toolsTbody.innerHTML = '<tr><td colspan="5" class="hint">Loading…</td></tr>';
  setMessage(toolsMessage, "", "");
  setMessage(custodyMessage, "Loading tool custody…", "");

  const adminPlus = canManageCustody();
  let toolsLoadFailed = false;
  userPicker.hidden = !adminPlus;
  const currentUser = getCurrentUser();
  const results = await Promise.allSettled([
    apiListTools(),
    adminPlus ? apiListUsers() : Promise.resolve(currentUser ? [currentUser] : []),
  ]);

  if (results[0].status === "fulfilled") {
    setTools(results[0].value);
    renderTools();
  } else {
    toolsLoadFailed = true;
    setTools([]);
    const message = friendlyError(results[0].reason, "Could not load tools. Try again.");
    toolsTbody.innerHTML = '<tr><td colspan="5" class="error">' + escapeHtml(message) + '</td></tr>';
    setMessage(custodyMessage, message, "error");
  }

  if (results[1].status === "fulfilled") {
    custodyUsers = results[1].value
      .filter((user) => !user.archived_at)
      .sort((left, right) => formatUserName(left).localeCompare(formatUserName(right)));
    if (adminPlus) {
      if (selectedUserId && !custodyUsers.some((user) => user.id === selectedUserId)) {
        clearSelectedUser();
      }
      if (!toolsLoadFailed) {
        setMessage(custodyMessage, selectedUserId ? "" : "Search for a user to view tool custody.", "");
      }
    } else if (custodyUsers.length > 0) {
      selectedUserId = custodyUsers[0].id;
      if (!toolsLoadFailed) setMessage(custodyMessage, "", "");
    }
    renderUserCard();
  } else {
    custodyUsers = [];
    clearSelectedUser();
    setMessage(custodyMessage, friendlyError(results[1].reason, "Could not load active users. Try again."), "error");
  }
}

export function resetToolsView() {
  custodyUsers = [];
  selectedUserId = null;
  setTools([]);
  userSearch.value = "";
  toolsSearch.value = "";
  hideUserResults();
  clearSelectedUser();
  closeToolEditor();
  closeToolCorrection();
  setLookupScanContext();
  toolsScanner.reset();
  if (toolsSubNav) toolsSubNav.showFeature("custody");
  setMessage(custodyMessage, "", "");
  setMessage(toolsMessage, "", "");
}
