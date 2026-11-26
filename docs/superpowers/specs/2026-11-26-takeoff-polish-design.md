# Takeoff page polish

**Intent:** the owner likes the Takeoff page; it should match the styling and
details of the other pages.

## Approaches

| Option | Trade-off |
|---|---|
| **A. Polish the table (picked), plus a card per service type** | Keeps column comparison; items stay table rows |
| B. A tap-to-open card per item, like Low Stock | Closer match, but ordering takes an extra tap and columns are harder to compare |
| C. B plus "To order" / "Ordered" tabs | Adds behaviour |

## Changes

| Part | Change |
|---|---|
| Service types | Each is its own raised card (nested panel, border, rounded corners, shadow). Name and planned total form the header. Always open (builder's proposal) |
| Column headings | Same style as other tables: no all-caps or letter spacing |
| Work orders link | "Show work orders" becomes a small "▸ 3 work orders" toggle; "▾" when open. Same list |
| Order control | "Order N more" gets an outlined button so it reads as tappable. "Ordered" and "Covered by stock" keep the tick, with no outline |
| Loading | Skeleton from `skeleton.js` on a load with nothing on screen. The reload after a save keeps the rows in place |

## Constraints and non-goals

- Front end only: `views/takeoff.js`, `styles.css`, and `takeoff.test.js` where text changes.
- Phone keeps the stacked rows inside each service card. No sideways scrolling.
- No change to numbers, ordering behaviour, sorting, or the work-order card's Takeoff section.
- No per-item cards, tabs or collapsing service cards.
