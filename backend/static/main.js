// Frontend composition root.
//
// Layer: app entry. The single ES module loaded by `index.html`
// (via `<script type="module" src="/static/main.js">`). Two jobs:
//
// 1. Side-effect-import every view module so each one's
//    DOM-event wiring (`addEventListener`, button handlers) runs
//    exactly once at startup.
// 2. Wire the cross-view callbacks that would otherwise create
//    import cycles -- in particular, the items view needs to
//    close the transaction form when the selected item is
//    deleted, but importing `transactions` from `items` would
//    pull the transaction module's DOM wiring into the Entry
//    page lifecycle. Injecting `closeTransactionForm` here keeps
//    the dependency one-way.
// 3. Trigger the initial data loads and page state.
//
// No business logic lives in this file; it should never grow
// beyond imports and a handful of bootstrap calls.

// --- Side-effect imports (register DOM handlers) -----------------
import "./views/nav.js";
import "./views/notes.js";
import "./views/items.js";
import "./views/users.js";
import "./views/history.js";

// --- Named imports for bootstrap calls ---------------------------
import { showPage } from "./views/nav.js";
import { loadItems, setOnDeletedSelectedItem } from "./views/items.js";
import { loadUsers } from "./views/users.js";
import { setHistoryTab } from "./views/history.js";
import { closeTransactionForm } from "./views/transactions.js";

// Cross-view wiring: deleting the selected item from the Entry
// page must also dismiss the transaction form on the Transaction
// page (otherwise it would point at a now-missing row).
setOnDeletedSelectedItem(closeTransactionForm);

// --- Initial state -----------------------------------------------
showPage("create-item");
setHistoryTab("all");
loadItems();
loadUsers();
