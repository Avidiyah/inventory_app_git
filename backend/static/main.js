// Frontend composition root.
//
// Layer: app entry. The single ES module loaded by `index.html`
// (via `<script type="module" src="/static/main.js">`). Two jobs:
//
// 1. Side-effect-import every view module so each one's
//    DOM-event wiring (`addEventListener`, button handlers) runs
//    exactly once at startup.
// 2. Wire the cross-view callbacks that would otherwise create
//    import cycles -- in particular, the scan view needs to reset
//    itself when the scan-and-go batch changes, but importing
//    `scan` from `transactions` would pull the scanner's DOM
//    wiring into the transaction module. Injecting the callbacks
//    here keeps the dependency one-way.
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
import { setScanResetter, setScanAutostarter } from "./views/transactions.js";
import { resetScan, autoStartTxnScan } from "./views/scan.js";
import { initAuth } from "./views/auth.js";

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
