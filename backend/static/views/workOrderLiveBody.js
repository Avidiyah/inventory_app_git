// Work Orders: the live card body.
//
// Layer: above workOrderCardHtml.js. A socket-driven update patches an open
// card body in place and leaves alone whatever the user has typed, picked or
// opened. The patcher pairs elements by id; the builders give every element
// it may keep an id (bodyLiveCensus.test.js holds them to that).

// Entry rows whose fields act together: kept or updated as one unit.
export const LIVE_FORMS = ".wo-add-item, .wo-add-labor";
// Server rows (a material line, a labor entry or an SMR line).
export const LIVE_ROWS = ".wo-item, .wo-labor-entry";
// A field that saves the moment it changes, so it always follows the server.
export const SAVES_ON_CHANGE = ".wo-mode-select";
