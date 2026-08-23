// Shared skeleton-loader markup for in-flight, DB-backed views.
//
// Layer: shared helper (same tier as format.js / dom.js). Pure functions in,
// HTML strings out -- no DOM access and no state, matching how every view in
// this app builds `innerHTML` directly.
//
// These replace the app's old `<p class="hint">Loading…</p>` /
// `<td class="hint">Loading…</td>` placeholders. Callers keep their own
// busy-state machinery (request-id guards, disabled buttons, error paths)
// exactly as it was -- only the in-flight markup changes.
//
// Screen readers: the visible "Loading…" text these replace was announced,
// so every block carries an .sr-only "Loading…" and marks the decorative
// bars aria-hidden. Callers get that for free and must not add their own.
//
// See docs/superpowers/specs/2026-08-23-skeleton-loaders-design.md.

// Bar widths ride on `.skel-w-NN` classes, NOT an inline `style="width:…"`.
// The app's CSP has no `style-src`, so it falls back to `default-src 'self'`
// and the browser silently drops style attributes parsed out of markup --
// the same trap `views/hubTechnician.js` documents. This module stays a pure
// string builder (no DOM, so no CSSOM escape hatch), so a class ladder is the
// fix. `styles.css` defines 25%–95% in steps of 5.
const WIDTH_STEP = 5;
const WIDTH_MIN = 25;
const WIDTH_MAX = 95;

// Deterministic width cycle for body lines. Deterministic rather than random
// (spec §3) so a repeated card still looks organic but two renders of the
// same view are pixel-identical -- manual visual checks stay reproducible.
// Values sit on the ladder already, so the default path never rounds.
const BODY_WIDTHS = [90, 80, 85, 65, 95, 70];

const SR_LOADING = `<span class="sr-only">Loading…</span>`;

function bodyWidth(index) {
  return BODY_WIDTHS[index % BODY_WIDTHS.length];
}

// Snap a caller-supplied CSS width ("70%") onto the class ladder. Callers
// keep passing percentage strings -- this is what makes the fix invisible to
// the ~12 existing call sites. Anything that isn't a percentage (e.g. "auto")
// returns null so the caller falls back to the deterministic cycle.
function snapWidth(cssWidth) {
  const match = /^\s*([\d.]+)%\s*$/.exec(String(cssWidth));
  if (!match) return null;
  const pct = Number(match[1]);
  if (!Number.isFinite(pct)) return null;
  const snapped = Math.round(pct / WIDTH_STEP) * WIDTH_STEP;
  return Math.min(WIDTH_MAX, Math.max(WIDTH_MIN, snapped));
}

function line(width, extraClass = "") {
  const classes = ["skel-line", `skel-w-${width}`];
  if (extraClass) classes.push(extraClass);
  return `<span class="${classes.join(" ")}" aria-hidden="true"></span>`;
}

// `rowCount` skeleton table rows of `colCount` cells each. `widths` is an
// optional array (same length as colCount) of CSS percentage widths, so a view
// can keep its narrow columns narrow instead of every cell getting a
// full-width bar. Values are snapped to the nearest 5% class (see snapWidth);
// a non-percentage entry falls back to the deterministic cycle.
export function skeletonTableRows(colCount, rowCount = 5, { widths = null } = {}) {
  const cells = [];
  for (let row = 0; row < rowCount; row += 1) {
    const tds = [];
    for (let col = 0; col < colCount; col += 1) {
      const asked = widths && widths[col] ? snapWidth(widths[col]) : null;
      const width = asked === null ? bodyWidth(row + col) : asked;
      // The sr-only text rides in the first cell of the first row only --
      // one announcement per loading region, not one per bar.
      const sr = row === 0 && col === 0 ? SR_LOADING : "";
      tds.push(`<td>${sr}${line(width)}</td>`);
    }
    cells.push(`<tr class="skel-row">${tds.join("")}</tr>`);
  }
  return cells.join("");
}

// One card-shaped block: an optional wider/taller header bar over `lines`
// body bars of varying width.
export function skeletonCard({ lines = 3, hasHeader = true } = {}) {
  const head = hasHeader ? line(40, "skel-line--head") : "";
  const body = [];
  for (let i = 0; i < lines; i += 1) body.push(line(bodyWidth(i)));
  return `<div class="skel-card">${SR_LOADING}${head}${body.join("")}</div>`;
}

// `itemCount` stacked two-line groups (title bar + shorter subtitle bar), for
// list-style panels that are neither tables nor cards.
export function skeletonList(itemCount = 4) {
  const items = [];
  for (let i = 0; i < itemCount; i += 1) {
    const sr = i === 0 ? SR_LOADING : "";
    items.push(
      `<div class="skel-list-item">${sr}` +
      line(bodyWidth(i)) +
      line(bodyWidth(i + 3), "skel-line--sub") +
      `</div>`
    );
  }
  return items.join("");
}
