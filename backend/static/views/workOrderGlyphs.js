// Work Orders: glyphs.
//
// Layer: leaf of the Work Orders module group -- imports nothing from it. The
// small inline SVGs that sit in front of a status pill, a priority or overdue
// tag, and the charging strip, so no state on the card is color alone. Sized
// and colored by `.wo-glyph` in styles.css (never a style= attribute -- CSP),
// drawn in currentColor so each one takes its pill's text color.

function svg(paths) {
  return `<svg class="wo-glyph" viewBox="0 0 16 16" aria-hidden="true" focusable="false">${paths}</svg>`;
}

const STROKE = `fill="none" stroke="currentColor" stroke-width="1.8" stroke-linecap="round" stroke-linejoin="round"`;

const STATUS_GLYPHS = {
  created: svg(`<circle cx="8" cy="8" r="5" ${STROKE}/>`),
  assigned: svg(`<circle cx="8" cy="5" r="2.6" fill="currentColor"/><path d="M3 14c0-3 2.2-5 5-5s5 2 5 5z" fill="currentColor"/>`),
  in_progress: svg(`<path d="M5 3l8 5-8 5z" fill="currentColor"/>`),
  on_hold: svg(`<rect x="4" y="3" width="3" height="10" rx="1" fill="currentColor"/><rect x="9" y="3" width="3" height="10" rx="1" fill="currentColor"/>`),
  ready_to_complete: svg(`<path d="M4 2h8M4 14h8M5 2c0 4 6 4 6 6s-6 2-6 6M11 2c0 4-6 4-6 6s6 2 6 6" ${STROKE}/>`),
  completed: svg(`<path d="M3 8.5l3.2 3.2L13 5" ${STROKE} stroke-width="2.2"/>`),
  review: svg(`<circle cx="7" cy="7" r="4" ${STROKE}/><path d="M10 10l3.5 3.5" ${STROKE} stroke-width="2.2"/>`),
};

// Filled triangle with the "!" cut out of it: the cut is stroked in the tag's
// own fill (`.wo-glyph-cut` in styles.css) so it reads as a hole.
export const WARNING_GLYPH = svg(
  `<path d="M8 2L1.5 13.5h13z" fill="currentColor"/><path class="wo-glyph-cut" d="M8 6.5v3.2M8 11.6v.1" fill="none" stroke-width="1.6" stroke-linecap="round"/>`
);

export const CLOCK_GLYPH = svg(`<circle cx="8" cy="8" r="5.5" ${STROKE}/><path d="M8 5v3.2l2.2 1.4" ${STROKE}/>`);

export const DOT_GLYPH = svg(`<circle cx="8" cy="8" r="4" fill="currentColor"/>`);

// "" for a status this map does not know, so a new lifecycle state renders as
// a plain labelled pill rather than a broken one.
export function statusGlyph(status) {
  return STATUS_GLYPHS[status] || "";
}
