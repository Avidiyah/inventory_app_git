# Work order prior-work guardrail — design

Date: 2026-10-14 · Status: awaiting approval · Implement after the self-assignment work lands (same files: `start_labor_session`, crew lock, work order card).

## Problem
A second worker arrives at a work order someone already worked, repeats the assessment, and files material the first worker already requested. The notes say what was done; nobody reads them before charging.

## Behavior
- A work order has **prior work** when another user (not the caller) has any labor session, labor entry, or material line on it. Notes and crew membership do not count. No age cutoff.
- The caller's own prior work never triggers the gate (re-start after lunch / auto-hold).
- When prior work exists and the caller has not yet charged: banner "Someone has been here — check the notes before charging" (names + last activity), Notes section auto-expanded, **Begin Charging disabled until the caller taps "I've read the notes"**. Notes are already readable by everyone; unchanged.
- Empty notes: banner still shows, no gate (nothing to read).
- Scope: the Begin Charging path (`POST /{id}/tracking/start`). Technicians cannot add material or requests without it (crew lock). Supervisors+ adding material directly are not gated.

## Server
- `prior_work` on work order detail: `{by: [full_name], last_at}` or `null`, computed for the viewer (excludes own rows). Single query, no migration.
- `tracking/start` accepts `notes_acknowledged: bool` (default false). If prior work (by others) exists, notes are non-empty, and the flag is false → 409 `prior_work_unacknowledged` with the `prior_work` payload. Idempotent re-start on a row the caller already runs is exempt.
- The client attests; the server decides whether the gate applies. No per-user "opened" table.

## Client
- Banner + acknowledge button in `workOrderCardHtml.js` / `workOrderStatusActions.js`; the start call sends `notes_acknowledged` once acknowledged. A 409 re-renders the banner (covers a race where someone else charged after load).
- Copy lives next to the existing crew-lock hint.

## Tests
- Domain/service: prior-work computation (own vs others, each source, empty). Gate: 409 without flag, success with, exempt when own/idempotent/empty notes.
- Router: real TestClient on `tracking/start` (409 shape, ack path).
- Frontend: banner shown/hidden, button disabled until acknowledged.

## Out of scope
Per-user read receipts, hard-blocking supervisors, notification to the first worker.
