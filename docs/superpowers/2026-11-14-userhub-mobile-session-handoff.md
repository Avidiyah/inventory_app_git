# Session handoff — User Hub phone redesign (2026-11-14)

## State
- Branch `codex/userhub-mobile-layout` (PR #17, one pushed commit `c66c8f7`). Everything below is **uncommitted, untested, unpushed**. User said "no testing until I say so."
- Not mine, do not stage: `backend/static/views/smrWeeklyHours.js` (modified), `backend/tests/e2e/test_mobile_overflow.py` and `.ruv-swarm/` (untracked). Stage explicit paths only.
- PR #17 CI is red on main-inherited failures (2418941 added `apiSetSmrPaperReviewed` without `endpointTable.js` / `endpoint-map.md` / memprobe rows; `test_smr_tile_orders` gained a per-order query). Not caused by the PR.
- Preview: host server on 127.0.0.1:8124 serves this checkout (page shell builds at startup: restart after editing `user-hub.html`). Login `owner` / `owner1`.
- Vitest only starts from a PowerShell session with `C:\Users\…` in capital C.

## Built this session (all ≤600px; desktop unchanged)
- **Section picker** replaces the scrolling tab row (card + icon tiles, "Navigate your profile"). `user-hub.html`, `userHub.js`, `styles.css`.
- **Dashboard**: 7 grouped cards, pill counts, proportion bar. `hubAdmin.js`, `hubTechnician.js`.
- **Timesheets, Leaderboards, Work Orders, Graphs, Report**: one builder each (merged CSS at the end of `styles.css`).
- **Home**: the three count tiles sit in one row; label and number colored by status (lifted hues: assigned `#F87171`, in progress `--wo-status-in-progress`, ready `#A78BFA`).

## Known gaps
- Graphs: "Assigned" legend row renders as a solid red bar; a 100%-one-status community (Commons) has no ring; service-type/priority split cards and the "updated" hint are hidden on phone; phone block duplicates desktop cards.
- Work Orders tab: no card header, building not bold, disclosure triangle shows (needs `workOrderCardHtml.js` change; shared with the full page).
- Timesheets: Export CSV sits above the week card; Leaderboards: "?" icon alone on a line.
- Likely test breakage (not run): hubAttendance day/roster, Leaderboards empty-state text, hubReport cells/empty text, Graphs card counts, hubAdmin pipeline markup.

## Design rules learned
- Never require horizontal scrolling (memory `feedback-no-horizontal-scroll`).
- Work-order **location is the primary heading; the WO number is a serial** (search key), shown small.

## Next session: write the spec (no code yet)
Detailed spec of how work orders — the card and the Work Orders page — present information consistently (hierarchy: location → status/priority/overdue → number; what the user actually reads vs looks up). Candidate previews to pick from: `scratchpad\wo-variants.png` (A location-first chips below; B status stripe compact rows; C separate cards, number as footer). Recommendation: A for lists, with the spec applied to the full page's card and detail view. Then plan, then build, then run the tests and fix the breakage above; commit and push only on go-ahead (pushing main deploys).
