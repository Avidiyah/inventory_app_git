// The page-shell fixture.
//
// Composes the REAL document the server serves and injects it into jsdom, so
// view modules -- which capture element ids at import time -- wire against
// production markup. Rename an id in a fragment and the tests that use it go
// red, instead of a control silently going dead in production.

import { readFileSync } from "node:fs";
import { fileURLToPath, pathToFileURL } from "node:url";
import { dirname, join } from "node:path";

// `fileURLToPath(new URL(...))` does not work here: under the jsdom
// environment the global `URL` is jsdom's, and node rejects that object as
// not-a-file-URL. Converting the string form first keeps it all in node.
const HELPERS_DIR = dirname(fileURLToPath(import.meta.url));
const REPO_ROOT = join(HELPERS_DIR, "..", "..", "..");
const STATIC_DIR = join(REPO_ROOT, "backend", "static");
const MAIN_PY = join(REPO_ROOT, "backend", "app", "main.py");

// Source of truth is main.py, read at test time. A hardcoded copy of the
// fragment order here would drift from what production assembles, which is
// exactly the failure this fixture exists to prevent.
export function shellParts() {
  const source = readFileSync(MAIN_PY, "utf8");
  const match = source.match(/^SHELL_PARTS\s*=\s*\(([\s\S]*?)^\)/m);
  if (!match) {
    throw new Error(
      `SHELL_PARTS tuple not found in ${MAIN_PY}. If it was renamed or ` +
      `reformatted, update this parser -- do not hardcode the list.`,
    );
  }
  const parts = [...match[1].matchAll(/"([^"]+\.html)"/g)].map((m) => m[1]);
  if (!parts.length) throw new Error("SHELL_PARTS matched but yielded no fragments");
  return parts;
}

// The assembled string is the same for every mount in a worker, and reading
// main.py plus fourteen fragments on each one is pure repeat I/O. Cached at
// module scope; the DOMParser pass below still runs per test, so each test
// gets its own fresh DOM. Invalidate by restarting the run -- a test that
// edits a fragment on disk is not a thing this suite does.
let assembled = null;

export function assembleShell() {
  if (assembled !== null) return assembled;
  const html = shellParts()
    .map((part) => readFileSync(join(STATIC_DIR, part), "utf8"))
    .join("");
  // shell-tail.html carries two: the ZXing UMD vendor tag and the main.js
  // module tag. Neither may run -- main.js boots every view against a DOM
  // the test has not arranged yet.
  assembled = html.replace(/<script\b[\s\S]*?<\/script>/gi, "");
  return assembled;
}

// Listeners a view hangs on `document` at import outlive the shell they were
// written for: `mountShell` swaps `documentElement`, but `document` is one
// object per file, and each test re-imports the view (setup.js resets the
// registry), so without this the previous tests' delegated handlers fire
// beside the current one against a DOM they never saw. `catalogueRequest.js`
// and `workOrderRequests.js` delegate off `document`; the latter's send
// handler re-finds a message element the first stacked handler has already
// renamed (dom.js `setMessage` overwrites className), and rejects on null.
//
// Only registrations made WHILE `importView` evaluates a module are tracked
// and dropped at the next mount. Runtime registrations stay: dom.js removes
// its own dialog keydown listener, and user-event installs its value-tracking
// listeners on `document` once per document and would not reinstall them
// (dropping those turned a cleared filter into "70017001") (P7d).
const documentListeners = [];
let capturing = false;
const nativeAddEventListener = document.addEventListener.bind(document);
document.addEventListener = (type, listener, options) => {
  if (capturing) documentListeners.push([type, listener, options]);
  nativeAddEventListener(type, listener, options);
};

function dropDocumentListeners() {
  documentListeners.splice(0).forEach(([type, listener, options]) =>
    document.removeEventListener(type, listener, options));
}

export function mountShell() {
  dropDocumentListeners();
  const parsed = new DOMParser().parseFromString(assembleShell(), "text/html");
  document.replaceChild(
    document.importNode(parsed.documentElement, true),
    document.documentElement,
  );
}

// Import a view module against the shell that is already in the document.
//
// Separate from `mountView` for the one case that needs two imports against a
// single shell: a module whose own import graph is cyclic and therefore cannot
// be the entry point (see `helpers/items.js`). Mounting twice would replace
// `document.documentElement` and leave the first module's captured elements
// detached, so the shell is mounted once and each module imported in turn.
export async function importView(modulePath) {
  // A bare Windows path ("C:\...") is not a resolvable module specifier, so
  // the absolute path is handed to import() as a file:// URL.
  capturing = true;
  try {
    return await import(/* @vite-ignore */ pathToFileURL(join(STATIC_DIR, modulePath)).href);
  } finally {
    capturing = false;
  }
}

// The only supported way to load a view module.
//
// Order is not optional: the module's top-level getElementById calls run at
// import time, so importing before mounting captures nulls and every
// assertion afterwards is testing a corpse.
export async function mountView(modulePath) {
  mountShell();
  return importView(modulePath);
}
