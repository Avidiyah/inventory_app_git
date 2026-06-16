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
import "./views/itemEditor.js";
import "./views/correction.js";
import "./views/items.js";
import "./views/users.js";
import "./views/history.js";
import "./views/transactions.js";
import "./views/scan.js";
import "./views/massStage.js";
import "./views/auth.js";

// --- Named imports for bootstrap calls ---------------------------
import { setOnDeletedSelectedItem } from "./views/items.js";
import { closeTransactionForm, setOnTransactionSaved, setScanResetter, setScanAutostarter } from "./views/transactions.js";
import { resetScan, autoStartTxnScan } from "./views/scan.js";
import { initAuth } from "./views/auth.js";

// Cross-view wiring: deleting the selected item from the Entry
// page must also dismiss the transaction form on the Transaction
// page (otherwise it would point at a now-missing row).
setOnDeletedSelectedItem(closeTransactionForm);

// After a completed manual stock/dispense, reset the scan UI so the next
// scan starts clean. Injected here (rather than imported by
// transactions.js) to keep the view dependency one-way: scan -> transactions.
setOnTransactionSaved(resetScan);

// Let the scan-and-go flow stop the live camera + clear the scan UI when
// the operator changes the work order. Same one-way-dependency reasoning.
setScanResetter(resetScan);

// Auto-start the camera when a work order batch begins (only if camera
// permission is already granted -- never prompts). Same one-way dependency.
setScanAutostarter(autoStartTxnScan);

// --- Auth gate ---------------------------------------------------
// `initAuth` checks /auth/me and then either shows the login screen or
// reveals the app and runs the role-appropriate initial loads. All
// data loading now happens behind a valid session.
initAuth();
