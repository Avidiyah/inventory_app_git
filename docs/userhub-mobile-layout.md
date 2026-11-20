# UserHub mobile layout

Session: 2026-11-14

At viewport widths up to 600px, Home presents attendance and work-order tracking as separate, labeled cards. Attendance includes the weekly punch disclosure, with full-width punch actions and status beside today's total. The work-order card shows the order number, community, and building/unit details (or location fallback) above a short **Track work order** button. Counts use two columns, including the existing Ready to complete tile.

The mobile Home heading appears only while Home is selected. Active attendance uses **Shop time** or **Shift time** according to the punch type; active work-order tracking keeps its elapsed timer and Stop action. Tabs can scroll horizontally. Wider screens retain the existing layout and detailed tracking button label. The shop-time explanation is shortened at all widths.

Implementation is in `backend/static/pages/user-hub.html`, `backend/static/views/hubHome.js`, `backend/static/views/hubClock.js`, and `backend/static/styles.css`. Attendance and tracking APIs, time calculations, refresh behavior, and punch editing remain unchanged. Work-order details are escaped and associated with the tracking button through `aria-describedby`.

## Verification

- Focused Vitest suites for `hubHome`, `hubClock`, and `userHub`: 71 tests passed. Clock coverage includes escaped mobile details and the retained desktop label.
- Chromium fixture using the real shell, view modules, and stylesheet with simulated payloads: idle, active, empty, and attendance-error states checked at 320, 360, 390, 600, 601, and 1280px; no page overflow. Long work-order text also checked at mobile widths.
- Browser checks use fixture data; they are not a production backend end-to-end test.

## Project-memory gap

Checked-in attendance/Home specs supplied context. This note records the implementation and verification for later reconciliation into `4. Notes/Repository-Docs/inventory-app-git`; it does not replace the canonical project memory.
