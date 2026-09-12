// The Tools page mount fixture.
//
// Nothing on this page loads at import: `loadTools()` is the entry, and main.js
// calls it on page activation. So `mountTools` only wires the two list
// endpoints off its arguments and leaves the fetching to the test --
// `openTools()` is the shorthand for "mounted and loaded".

import { http, HttpResponse } from "msw";
import { userEvent } from "@testing-library/user-event";
import { server } from "./handlers.js";
import { startRecording, stopRecording, requests, requestFor, clearRequests } from "./requests.js";
import { importView, mountView } from "./shell.js";
import { setTestUser } from "./session.js";
import { restoreMediaStubs, stubPermissions, stubUserMedia } from "./media.js";
import { restoreBrowserStubs, stubScrollIntoView } from "./browserStubs.js";
import { user as userFactory } from "./factories.js";

// Getters, not nodes: every mount replaces `document.documentElement`, so a
// captured node would be a corpse from the previous test.
const byId = (id) => () => document.getElementById(id);

export const el = {
  page: byId("tools-page"),
  // Custody: the picker, its results, and the selected user's card.
  picker: byId("tool-user-picker"), userSearch: byId("tool-user-search"),
  userResults: byId("tool-user-results"), custodyMessage: byId("tool-custody-message"),
  userCard: byId("tool-user-card"), userName: byId("tool-user-name"),
  userMeta: byId("tool-user-meta"), userStatus: byId("tool-user-status"),
  custodyCount: byId("tool-user-custody-count"), holdings: byId("tool-user-holdings"),
  // Checkout controls (the tool search that opens the checkout editor).
  checkoutControls: byId("tool-checkout-controls"), checkoutSearch: byId("tool-checkout-search"),
  checkoutResults: byId("tool-checkout-results"), checkoutScanBtn: byId("tool-checkout-scan-btn"),
  checkoutPickerMessage: byId("tool-checkout-picker-message"),
  // toolCheckout.js
  checkoutSection: byId("tool-checkout-section"), checkoutSelected: byId("tool-checkout-selected"),
  checkoutUserSummary: byId("tool-checkout-user-summary"), checkoutQuantity: byId("tool-checkout-quantity"),
  checkoutWorkOrder: byId("tool-checkout-work-order"), checkoutSaveBtn: byId("tool-checkout-save-btn"),
  checkoutCancelBtn: byId("tool-checkout-cancel-btn"), checkoutMessage: byId("tool-checkout-message"),
  // toolReturn.js
  returnSection: byId("tool-return-section"), returnSelected: byId("tool-return-selected"),
  returnUserSummary: byId("tool-return-user-summary"), returnQuantity: byId("tool-return-quantity"),
  returnWorkOrder: byId("tool-return-work-order"), returnSaveBtn: byId("tool-return-save-btn"),
  returnCancelBtn: byId("tool-return-cancel-btn"), returnMessage: byId("tool-return-message"),
  // Inventory
  theadRow: byId("tools-thead-row"), tbody: byId("tools-tbody"),
  search: byId("tools-search"), message: byId("tools-message"),
  editorSection: byId("tool-editor-section"), editorSelected: byId("tool-editor-selected"),
  editorBarcode: byId("tool-editor-barcode"), editorName: byId("tool-editor-name"),
  editorSaveBtn: byId("tool-editor-save-btn"), editorCancelBtn: byId("tool-editor-cancel-btn"),
  editorMessage: byId("tool-editor-message"),
  correctionSection: byId("tool-correction-section"), correctionSelected: byId("tool-correction-selected"),
  correctionCurrent: byId("tool-correction-current"), correctionQuantity: byId("tool-correction-new-quantity"),
  correctionReason: byId("tool-correction-reason"), correctionSaveBtn: byId("tool-correction-save-btn"),
  correctionCancelBtn: byId("tool-correction-cancel-btn"), correctionMessage: byId("tool-correction-message"),
  // Add Tool (the Tool tab of the create-item page)
  createBtn: byId("create-tool-btn"), createMessage: byId("create-tool-message"),
  toolBarcode: byId("tool-barcode"), toolName: byId("tool-name"), toolQuantity: byId("tool-quantity"),
  toolScanToggle: byId("tool-scan-toggle-btn"), toolScanControls: byId("tool-scan-controls"),
  toolScanInput: byId("tool-scan-input"), toolScanMessage: byId("tool-scan-message"),
  toolScanChooser: byId("tool-scan-chooser"),
  // The page's own contextual scanner
  scanInput: byId("tools-scan-input"), scanMessage: byId("tools-scan-message"),
  scanChooser: byId("tools-scan-chooser"), scanHeading: byId("tools-scan-heading"),
  scanHint: byId("tools-scan-hint"),
  subNavBtn: (feature) => document.querySelector(`#tools-page .sub-nav-btn[data-feature="${feature}"]`),
};

export const rows = () => Array.from(el.tbody().querySelectorAll("tr"));
export const headers = () => Array.from(el.theadRow().querySelectorAll("th")).map((th) => th.textContent);
export const actionSelect = (rowIndex = 0) => rows()[rowIndex]?.querySelector("select.row-actions-select") ?? null;
export const userOptions = () => Array.from(el.userResults().querySelectorAll(".tool-user-option"));
export const checkoutOptions = () => Array.from(el.checkoutResults().querySelectorAll("[data-checkout-tool-id]"));
export const holdingRows = () => Array.from(el.holdings().querySelectorAll(".tool-holding-row"));
export const checkinBtn = (index = 0) => holdingRows()[index]?.querySelector(".tool-checkin-btn") ?? null;
export const activeFeature = () => el.page().dataset.activeFeature;

// --- request recording -----------------------------------------------------
export { requests, requestFor, clearRequests };

// --- the shared confirm modal (dom.js) -------------------------------------
export { answerConfirm } from "./dialogs.js";

// --- answers ----------------------------------------------------------------
// `/tools/:barcode` is the lookup both scanners use; a different path from
// `/tools/`, so it never collides with the list handler `mountTools` installs.
export function answerToolLookup(barcode, toolOrStatus) {
  server.use(http.get(`/tools/${encodeURIComponent(barcode)}`, () =>
    typeof toolOrStatus === "number"
      ? HttpResponse.json({ detail: "Tool not found" }, { status: toolOrStatus })
      : HttpResponse.json(toolOrStatus)));
}

export function answerDecode(barcodes) {
  server.use(http.post("/barcodes/decode", () =>
    HttpResponse.json({ barcodes: barcodes.map((text) => ({ text, format: "CODE_128" })) })));
}

// --- upload -----------------------------------------------------------------
export async function upload(inputEl, name = "label.png") {
  const file = new File([new Uint8Array([0x89])], name, { type: "image/png" });
  await userEvent.setup().upload(inputEl, file);
}

// --- flows shared by the custody files --------------------------------------
// Choosing a user is the setup for nearly every custody assertion: focus the
// search box to list everyone, then click the option carrying that id.
export async function chooseUser(user, userInstance = null) {
  const ue = userInstance ?? userEvent.setup();
  await ue.click(el.userSearch());
  const option = el.userResults().querySelector(`[data-user-id="${user.id}"]`);
  if (!option) throw new Error(`no picker option for user ${user.id}`);
  await ue.click(option);
  return ue;
}

// --- mount ------------------------------------------------------------------
// `currentUser` overrides go onto the signed-in user the `user()` factory
// builds -- `loadTools` hands that object straight to the custody card for a
// supervisor/technician, so a test asserting the card's date copy needs to
// choose its `created_at`.
export async function mountTools({
  role = "admin", tools = [], users = null, handlers = [], currentUser = {},
} = {}) {
  // `handlers` go FIRST: MSW takes the first matching handler within one
  // `use()` call, so a test's own `/tools/` override must precede the default.
  server.use(
    ...handlers,
    http.get("/tools/", () => HttpResponse.json(tools)),
    http.get("/users/", () => HttpResponse.json(users ?? [])),
  );
  stubUserMedia();
  stubPermissions("prompt");
  // toolCheckout.js, toolReturn.js, the tool editor and the user picker's
  // keyboard navigation all call scrollIntoView unguarded; jsdom implements no
  // layout, so without this the call throws inside a listener and surfaces as
  // an unhandled rejection.
  const scrollIntoView = stubScrollIntoView();
  const me = await setTestUser({ role, ...currentUser });
  startRecording();
  // tools.js cannot be the entry point of its own module graph: it reaches
  // nav.js through scan.js -> transactions.js, and nav.js reads tools.js's
  // `toolsScanner` const while tools.js is still evaluating. production/main.js
  // enters at nav.js first, so the fixture primes the graph the same way --
  // the same shape helpers/items.js uses for the same cycle.
  await mountView("views/nav.js");
  const mod = await importView("views/tools.js");
  clearRequests();
  return { mod, currentUser: me, scrollIntoView };
}

// Mounted AND loaded, with the load's own two requests cleared -- the entry for
// every test asserting what happens after the page is populated. A test that
// asserts the load itself calls `mountTools` and then `mod.loadTools()`.
export async function openTools(options = {}) {
  const mounted = await mountTools(options);
  await mounted.mod.loadTools();
  clearRequests();
  return mounted;
}

export function restoreTools() {
  stopRecording();
  restoreMediaStubs();
  restoreBrowserStubs();
}
