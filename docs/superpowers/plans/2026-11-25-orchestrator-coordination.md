# Two orchestrators, one checkout — coordination protocol (2026-11-25)

Two orchestrator sessions run at the same time in this checkout, each with its
own Sonnet subagents:

| Tag | Plan |
|---|---|
| `[takeoff]` | `docs/superpowers/plans/2026-11-25-takeoff-and-top-bar.md` |
| `[flagged]` | `docs/superpowers/plans/2026-11-25-flagged-time-step-through.md` |

Both plans link here; this file wins where they disagree on coordination.

## 1. Find each other

- At start, at every wave/task boundary and before every commit: run
  `ListAgents`, then read the ledger (§3).
- First contact: `SendMessage` to each listed peer session
  `"[tag] HELLO — running <plan path>; protocol: docs/superpowers/plans/2026-11-25-orchestrator-coordination.md"`.
  The peer replies `"[tag] HELLO"`. Session names are labels, not identity:
  the plan path in the HELLO is the identity.
- Peer not listed (closed, other machine): the ledger alone governs; say so in
  your report to the owner.

## 2. Who owns what

Each plan's lane table lists its **exclusive** files; the other orchestrator and
its subagents never write them. Files both plans touch are **shared** and
change only under a claim:

| Shared file | `[takeoff]` change | `[flagged]` change |
|---|---|---|
| `backend/static/api.js` | new takeoff wrappers after `apiAddWorkOrderItem`; one param on it | swap the hub attendance review wrapper |
| `tests/frontend/helpers/endpointTable.js` | new takeoff rows | swap one row |
| `backend/static/styles.css` | append `/* Work-order top bar */`, `/* Takeoff section */`, `/* Takeoff page */` blocks at EOF | append the flagged-time block at EOF |
| `backend/scripts/memprobe_routes.py` | five takeoff routes | replace the bulk-review route |
| `backend/tests/test_route_role_gates.py`, `test_realtime_emit.py`, `test_memprobe.py` | takeoff entries | new session-review entries, if needed |
| `docs/current-state.md` | takeoff + top bar sections | attendance review lines |
| the git index (commits) | — | — |

Any other file you find you need that the other plan lists as its own: stop,
`SendMessage` the owner orchestrator, and let them make the change.

## 3. Claims

Ledger: `.git/orchestration/claims.md` (inside `.git`, so it is never
committed; create the folder if missing). One line per event:
`<ISO time> [tag] CLAIM|RELEASE <path>`.

To change a shared file:
1. Read the ledger. If the path's last line is a peer CLAIM, do other work
   and wait for its RELEASE message; never sleep-poll.
2. Append `CLAIM`, send `"[tag] CLAIM <path>"`.
3. Re-read the file, make the smallest edit at your anchor (§2): append or
   insert one hunk; never reformat, reorder or "tidy" the other plan's lines.
4. Commit that path at once (§4), append `RELEASE`, send `"[tag] RELEASE <path>"`.

A claim lasts minutes (edit + commit), never a whole task. The peer replies
`ACK` to each CLAIM; no reply is not a veto, the ledger is the lock.

## 4. Commits

- Commit only by pathspec: `git commit -m "<msg>" -- <path> [<path>...]`. It
  commits those paths alone, whatever the other session has staged.
- `index.lock exists`: wait and retry; never delete the lock.
- Never `git add -A`, `git stash`, `git reset`, `git checkout -- <path>`,
  `git restore` on a file you don't own, or amend a commit you didn't make.
- Neither orchestrator pushes. Each sends `"[tag] READY TO PUSH"` to the peer
  and reports to the owner; the owner decides (pushing `main` deploys).

## 5. Subagents

- Subagents don't message other sessions. Each brief lists: the lane's own
  files, the peer plan's files (forbidden), and the shared files (§2:
  forbidden to the subagent; the orchestrator makes those edits under a
  claim, or reports the needed change).
- Subagents never commit; the orchestrator commits after review.

## 6. Tests and the database

- Backend tests are safe to overlap: the `db` fixture rolls back each test.
- `[takeoff]` sends `"[takeoff] HEADS-UP alembic upgrade/downgrade"` before
  touching the local schema (DDL takes brief locks).
- A failure in a file the peer owns: send `"[tag] FAILING <test> — <first error line>"`
  to the peer; don't fix it. Full-suite runs (each plan's last task) happen
  after sending `"[tag] HEADS-UP full suite"`; failures caused by the peer's
  in-progress work go back to the peer, not into your fixes.
- `[flagged]`'s `styles.css` note ("another session's uncommitted edits"):
  any uncommitted `styles.css` hunk that neither plan wrote is the owner's.
  Leave it unstaged and ask the owner.

## 7. Message vocabulary

`HELLO`, `CLAIM <path>`, `ACK`, `RELEASE <path>`, `DONE <task>`,
`HEADS-UP <what>`, `FAILING <test> — <line>`, `BLOCKED <reason>`,
`READY TO PUSH`. One line each, prefixed with the tag. Send `DONE` at each
task end so the peer knows when shared anchors moved.
