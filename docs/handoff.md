# Session Hand-off

Last updated: 2026-08-09, after the api-hardening-checklist restructure. B2
(DB-aware health check) shipped earlier the same day; the auth-hardening piece
(X1 + C3) shipped earlier still and was owner-validated.

This file is the **live** hand-off: where the work stands and what to pick up
next. It is not a history. For durable behavior and contracts start with
`docs/current-state.md`; for the framework/operational backlog see
`docs/api-hardening-checklist.md`; for user-requested features see
`docs/improvement-tracker.md`.

The July 2026 UX effort that used to live in this file is fully preserved in
`docs/ux-review.md` (its `## Completed` section carries the per-item detail and
validation notes). Nothing was lost by rewriting this file — only the
superseded status narrative went.

---

## Where things stand

**Just shipped (2026-08-09): auth hardening — checklist X1 + C3.**

Four defects closed, all in `docs/api-hardening-checklist.md` under
*Shipped by lifting the no-schema-change rule* with full verification evidence:

1. Session tokens are hashed at rest (`sessions.token` → `token_hash`, SHA-256).
2. Every session has a 12h absolute `expires_at` (was NULL by default, forever).
3. Password reset revokes sessions, like archive and role change already did.
4. Login is throttled — exponential backoff on (username, IP), 429 +
   `Retry-After`.

Verified: 514 backend tests, Alembic `fbc4e6a8d0f2` at head with a clean
down/up round-trip, 72 OpenAPI operations unchanged, 32 JS files syntax-clean,
and an owner browser pass across all seven manual checks.

**State of the tree:** the work is on `main` and **uncommitted**, deliberately.
The owner's standing direction as of 2026-08-09: *nothing gets committed until
everything in the docs roadmaps up to this point is implemented*, across however
many sessions that takes. So expect a large uncommitted diff and do not treat it
as unfinished business or offer to commit it. Verify what is actually present
with `git diff` rather than trusting this file.

**Deployment note that still matters:** the migration drops and recreates
`sessions`, so **the first cold start on the new image signs every user out.**
That is intended (it is what clears the accumulated plaintext credentials), but
it should land when no crew is mid-shift. If this has not been deployed yet,
that decision is still open.

---

## Also shipped 2026-08-09: B2 — the health check no longer lies

`GET /healthz` runs `SELECT 1` and returns `{"status": "ok"}` or 503
`Database unavailable.`; `render.yaml` now points `healthCheckPath` there
instead of at `/`. Full detail and verification evidence in
`docs/api-hardening-checklist.md` → Class B.

**Deployment consequence, and it is the intended one:** a deploy that cannot
reach Postgres now *fails* rather than going green. Nothing about the running
app changes for any user — this is deploy-gate behavior only.

Four calls were made deliberately rather than defaulted, in case they come back
up: `SELECT 1` only (no Alembic-head or table check — those would fail during a
legitimate migration); in the OpenAPI schema, so the operation count is a
documented 72 → 73 rather than a hidden route; path `/healthz`; and
`healthCheckPath` repointed in the same batch rather than deferred.

## Also shipped 2026-08-09: the hardening checklist is now priority-ordered

`docs/api-hardening-checklist.md` was restructured. It was grouped by
**observability class** (A/B/C/N/X) with the running order buried in a
"Suggested next order" paragraph at the bottom. It is now grouped by **when to
do it**, and the class survives as a per-item tag — because the class says what
*shipping* an item costs, which is a different question from *when* to ship it.

Documentation-only change. No code was touched.

**Shape now:** Tier 0 (deadline-driven) → Tier 1 (do next, in order) → Tier 2
(standing notes with named triggers) → Not in scope → Shipped → Verified as
non-issues. Item IDs are unchanged and still stable; the rank is the heading
number, the ID is the identity. Shipped items (A1–A6, B2, X1, C3) moved to a
**Shipped** section at the bottom with every verification-evidence table intact
— deliberately kept rather than deleted, so the queue at the top is purely
actionable without losing the record.

**The ordering is explicit now**, with four stated criteria: irreversible loss
first, then items that make other items safe to ship, then unauthenticated over
authenticated exposure, then cheaper-first on a tie.

Three ordering changes were made and owner-approved this session:

1. **N5 moved to #1**, alone in Tier 0. It was previously noted as "running in
   parallel". It is the only item whose failure mode is *data loss* rather than
   degradation, and the only one with an external clock.
2. **B1 before C1** — half the effort, and it closes a live hole rather than
   guarding a future endpoint.
3. **C4 before C2** — 15 minutes vs. half a day, and C4 is the last item
   exposing anything to an unauthenticated caller.

Every open item was re-verified against the working tree during the
restructure and all still hold. One correction landed: **C1's line numbers had
drifted ~7 lines** (279/315/365/563/630 → 286/322/372/570/636). That drift is
itself evidence for C1 — an in-body gate has no stable anchor.

---

## Shipped this session: N5, N2 (and N7 incidentally)

**N5 is closed** (2026-08-09). `inventory-db` was upgraded off the free plan, so
the 90-day expiry clock is gone — there is no date to log, because the deadline
was removed rather than met. Point-in-time recovery now covers any moment in the
**last three days**, which is stronger than the periodic dump the item asked
for: it covers partial corruption and bad migrations, not just loss of the
instance. Two caveats recorded in the checklist: the window is a recovery floor
rather than an archive (anything found more than three days late is outside it),
and PITR is a *recovery* path, not a deploy gate — it does not reduce N2's
priority. The web service is still deliberately on the free plan; that is
latency, not data loss.

**Tier 0 is now empty.** Nothing left on the list has an external clock.

**N2 (CI) shipped 2026-08-09.** `.github/workflows/ci.yml` runs three jobs —
`backend` (postgres:16 service, migrations, full suite on Python 3.12),
`static` (`node --check`, compile, single Alembic head, migration round-trip,
`pip-audit`), and `deploy` (gated on `needs: [backend, static]`, pushes to
`main` only, firing a Render hook). `render.yaml` is now `autoDeploy: false`,
so that hook is the only path to production. **523 passed in CI**, matching
local exactly.

The thing it nearly shipped with: `conftest.py` *skipped* DB-backed tests when
Postgres was unreachable, and **244 of 425 test functions take the `db`
fixture** — so a placeholder `DATABASE_URL` would have reported success over
43% of the suite. `tests/_db_availability.py` now raises instead of skipping
under `CI=true`, with local behavior unchanged.

**N7 closed incidentally**: installing `libzbar0` in CI is the first time the
`pyzbar` native dependency has been handled outside a container, which was its
named trigger.

**Read the two failure drills under N2 in the checklist before running another
one.** The guard drill passed. The deploy-gate drill was done wrong — `if:
always()` overrides `needs`, so it fired a real deploy of `main` (healthy, and
already-verified code, but unintended). The generalizable lesson: a drill that
requires weakening the condition under test is not a drill of that condition.

## Next up: B4, then N1

**B4 is new, and N2 found it.** The `pip-audit` gate's first run reported **23
known CVEs across two packages**: `pillow==12.2.0` (fix 12.3.0) and
`starlette==1.2.1` (fix 1.3.1). It ranks ahead of N1 on exposure: Pillow parses
**attacker-supplied image data** (`routers/barcodes.py:45` →
`services/barcodes.py:79-85`, before `pyzbar` sees it), reachable by any
authenticated user with the upload endpoint. **B1 does not cover this** — a size
cap bounds volume, not malformed content. Class B rather than A because a minor
bump of the image decoder and the ASGI layer is not provably invisible; check
A3's `httpx2==2.9.1` pin still resolves against Starlette 1.3. When it ships,
drop `continue-on-error: true` from the *Dependency audit* step.

**Then N1 (structured logging).** `backend/app/` contains **no logging
whatsoever** — not one `import logging`, logger call, or `print()` (re-verified
2026-08-09, 0 matches). Two things sharpen that: `login_attempts` is
deliberately transient (swept at 24h, deleted on successful login) so it cannot
answer "who was trying to get in", and `/healthz` now discards the driver's
exception on purpose — correct, because it is unauthenticated, but it means a
real database outage currently produces **no** diagnosable artifact anywhere in
the system. Logging that swallowed exception server-side is the direct follow-on
to B2.

Full Tier 1 order after that: **B1 → C1 → C4 → C2 → B3.**

---

## The session workflow

This is the sequence the owner runs a working session by. Follow it in order;
each step's output is the next step's input.

1. **Read all current documentation first.** All seven files under `docs/`, not
   just the one that looks relevant. The routing between them is in
   `docs/project-summary.md` → *Documentation map*, and the split matters:
   hardening ≠ improvement-tracker, and `current-state.md` is the only contract
   authority.
2. **Review the relevant code** — and prefer the code graph over opening files.
   See *MCP tooling* below.
3. **Plan, and stop.** Present the plan and wait. Surface the forks that are
   genuinely the owner's call — security/permission boundaries, anything with a
   visible one-time cost, anything that breaks a cross-reference — rather than
   defaulting them silently.
4. **Execute** only after an explicit go-ahead.
5. **Update documentation in the same turn as the work.** Never defer it to
   "later in the session"; the specific routing is in *Working rhythm* below.
6. **Write the session hand-off** — this file — and sync Obsidian before
   closing.

Steps 1 and 5 are the ones that have actually been skipped before, and both
times it cost a later session real time. This file was found stale once because
step 5 was deferred past a context boundary and never happened.

## MCP tooling

Two servers are wanted for this project. **Verify what is actually connected at
the start of each session rather than assuming** — the set has already differed
from expectations once.

**Graphify** — use it for code review *before* reading source. It answers
"where is this symbol", "who calls this", "what breaks if I change this", and
"what does this file depend on" from a promoted code graph, which is far cheaper
than opening files and more complete than grep for structural questions. Start
with `list_repositories`, then pass the id (`Avidiyah/inventory_app_git`) to the
query tools. It also has `recall` / `remember` for durable per-repo notes.

> **Check the index commit before trusting a structural answer.** As of
> 2026-08-09 the graph is at `d715545` (2,512 nodes / 5,790 edges), which
> *predates* the uncommitted X1/C3/B2 work. Its view of `sessions` is therefore
> the pre-hash schema, and the never-expiring-session defect it appears to show
> is the one X1 already fixed. Structural questions about untouched areas are
> reliable; anything near auth, sessions, or `/healthz` must be confirmed
> against the working tree. Because nothing is committed by design, this drift
> will keep widening — treat the graph as a map of the last commit, not of the
> tree.

**Obsidian** — the retrieval path for documentation held outside the repo.

> **It was NOT connected on 2026-08-09.** The vault was updated through direct
> filesystem writes instead, which works and is a fine fallback. Vault root:
> `C:\Users\mcclu\Desktop\Obsidian\John_Vault`, and this project's folder is
> `4. Notes\Repository-Docs\inventory-app-git`.

What lives in that folder, and what it is for:

| Path | What it is |
|---|---|
| `reviews/api-hardening-checklist.md` | **Mirror** of the repo checklist. Not authoritative — edit the repo copy, then re-sync. |
| `reviews/Gap Audit.md` | The FastAPI-specific exposure audit the checklist was built from. |
| `sessions/session-log.md` | Structured per-session log: `## <ISO timestamp>` then `### Summary` / `### Changed Files` / `### Decisions / Context Updates` / `### Follow-ups`. |
| `README.md` | Repo context plus a second, shorter append-log in the same four-section format. |

Two cautions learned on 2026-08-09. The vault mirror had drifted **two shipping
sessions** behind the repo before anyone noticed, which is why it now carries a
provenance header saying which direction sync flows. And the session log had a
matching gap — the 08-07 and 08-09 sessions were never written — now closed by a
clearly-labelled backfill entry. **Append to the log in the same session as the
work**, for the same reason step 5 above exists.

Note that `app-grade-2026-08-06.md`, referenced from the checklist's header as
the grading pass it extends, is **not present** in `reviews/` — only
`Gap Audit.md` is. Either it was renamed or it lives elsewhere in the vault. Not
chased down; flagged so the next session does not assume the citation resolves.

---

## Working rhythm on this project

Carried forward because it still holds:

- **The user picks the next item.** Phrasing decides the mode:
  - "pick" / "explain" / "come up with a plan" → analysis only that turn. Wait
    for an explicit separate go-ahead ("proceed", "begin implementation")
    before editing code.
  - "Do number N" → implement directly (still read the code thoroughly first;
    just don't pause for a separate explain-only turn).
- **Raise permission and trust-boundary forks before implementing.** Don't pick
  a default silently on a security-relevant call. The auth work had two such
  forks — hash-in-place vs. truncate, and backoff vs. account lockout — and
  both changed the design materially once surfaced.
- **Check whether a decision has already been made.** The auth plan initially
  proposed re-adding an idle timeout; migration `c7e9a1b3d5f8` showed one had
  been deliberately *removed* in June 2026. Read the migration history before
  proposing to reintroduce something.
- **Do not start the dev/preview server automatically** — the owner validates in
  the browser manually. Backend tests, syntax checks, and direct
  router/service calls are fair game and expected.
- **Nothing gets committed until the owner explicitly asks.** Work batches up,
  then lands on `main` in one go.
- After shipping an item, update its tracking doc in the same turn:
  hardening items → `docs/api-hardening-checklist.md` (tick it, record inline
  verification evidence, then **move the whole entry down to `## Shipped`** so
  the priority queue at the top stays purely actionable); feature requests →
  `docs/improvement-tracker.md`. Behavior changes also go into
  `docs/current-state.md`.
- When priority changes, **do not renumber item IDs.** `B1`/`C1`/`N1` are
  referenced across docs and past sessions. Move the entry; the heading number
  is the rank, the ID is the identity.

## On trusting this file

Verify status against `git diff` / `git log` directly rather than trusting any
summary here, including this one. This file was found stale once before — the
code and `docs/ux-review.md` had been updated in a stretch of a session that
fell out of context, and this file had not. If something here claims work
happened that isn't in the diff, it didn't happen; if the diff shows something
this file doesn't mention, trust the diff and update this file.
