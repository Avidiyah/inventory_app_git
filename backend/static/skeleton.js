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

// Deterministic width cycle for body lines. Deterministic rather than random
// (spec §3) so a repeated card still looks organic but two renders of the
// same view are pixel-identical -- manual visual checks stay reproducible.
const BODY_WIDTHS = ["92%", "78%", "85%", "66%", "95%", "72%"];

const SR_LOADING = `<span class="sr-only">Loading…</span>`;

function bodyWidth(index) {
  return BODY_WIDTHS[index % BODY_WIDTHS.length];
}

function line(width, extraClass = "") {
  const cls = extraClass ? `skel-line ${extraClass}` : "skel-line";
  return `<span class="${cls}" style="width: ${width}" aria-hidden="true"></span>`;
}

// `rowCount` skeleton table rows of `colCount` cells each. `widths` is an
// optional array (same length as colCount) of CSS widths, so a view can keep
// its narrow columns narrow instead of every cell getting a full-width bar.
export function skeletonTableRows(colCount, rowCount = 5, { widths = null } = {}) {
  const cells = [];
  for (let row = 0; row < rowCount; row += 1) {
    const tds = [];
    for (let col = 0; col < colCount; col += 1) {
      const width = widths && widths[col] ? widths[col] : bodyWidth(row + col);
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
  const head = hasHeader ? line("42%", "skel-line--head") : "";
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
