# Session Hand-off

Last updated: 2026-08-09, after **N2 (CI) shipped and merged to `main`**. N5
closed the same day (paid Postgres). Earlier that day: the checklist
restructure, B2 (DB-aware health check), and X1 + C3 (auth hardening,
owner-validated).

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

**Just shipped (2026-08-09): N2 — CI, merged to `main` at `d14627b`.**

`.github/workflows/ci.yml` now runs on every push and PR: `backend` (postgres:16
service, migrations, full suite on Python 3.12), `static` (`node --check`,
compile, single Alembic head, migration round-trip, `pip-audit`), and `deploy`
(gated on `needs: [backend, static]`, `main` pushes only, firing a Render hook
from the `RENDER_DEPLOY_HOOK_URL` secret). `render.yaml` is `autoDeploy: false`,
so that hook is the only path to production. **523 passed in CI.**

Full detail and verification evidence in `docs/api-hardening-checklist.md` →
*Shipped* → N2, including an honest record of a drill that went wrong.

**Two things N2 produced that were not on anyone's list:**

- **B4 — found by `pip-audit`'s first run, and closed the same day.** 23 known
  CVEs in `pillow` and `starlette`; Pillow parses attacker-supplied image data
  on the barcode upload path. The gate justified itself before it was even
  merged, then the finding was fixed and the gate armed. See *Shipped 2026-08-09:
  B4* below.
- **N7 closed incidentally.** Installing `libzbar0` in CI is the first time the
  `pyzbar` native dependency has been handled outside a container.

### State of the tree — this changed, read it

**Everything is committed and merged. `main` is clean and in sync with
`origin/main`.** The previous standing direction — *nothing gets committed until
the roadmaps are done*, which this file carried for several sessions — **is no
longer in force.** It ended with N2, because CI cannot be built or verified
without pushing commits and opening a PR. Normal commit-per-change flow now
applies, and `main` is protected by the gate rather than by holding work back.

Do not look for a large uncommitted diff. If `git status` is dirty, that is real
work in progress, not the old deliberate posture.

**The session-table migration has been deployed.** `fbc4e6a8d0f2` drops and
recreates `sessions`, so every user was signed out when it landed. That was
always the intent (it is what clears the accumulated plaintext credentials) and
it has now happened — do not treat it as still-pending, and do not schedule it
again.

**Docs-only pushes no longer deploy** (decided and shipped 2026-08-09). The
`deploy` job now classifies the push before firing the hook.

`paths-ignore` — the fix this was originally logged as — **does not work here.**
It is a workflow-level *trigger* filter, so it would have skipped `backend` and
`static` too, landing docs commits on `main` having run no checks at all. There
is no job-level `paths-ignore`.

What shipped instead is an **allowlist of what actually ships**: `render.yaml`
sets `rootDir: backend`, so the image is built from `backend/` alone and nothing
else in the repo can reach production. The hook fires only when `backend/**` or
`render.yaml` changed. An allowlist was chosen over a blocklist of doc paths
because a blocklist rots — the next new top-level directory would silently start
deploying again.

Every unclassifiable case (new branch, force push, grafted history, empty diff)
**falls through to deploying**. That direction is deliberate: a redundant deploy
is noise, while a skipped real change is a silent production stall.

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

## Also shipped 2026-08-09: N5 — the database deadline is gone

**N5 is closed.** `inventory-db` was upgraded off the free plan, so
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

## The one thing to read before drilling anything

N2 included two deliberate failure drills — breaking a gate on purpose to prove
it actually fails. **One of them was designed wrong and caused a real
production deploy.**

To let the `deploy` job run on a pull request, its condition was temporarily
changed to `if: always()`. That was the error: **`always()` overrides `needs`**,
meaning "run regardless of whether the dependencies succeeded" — the exact
opposite of the property being tested. The run was cancelled, but `deploy` had
already fired the hook. It deployed `main` (already-verified code) and came up
healthy, so there was no damage, but nothing about the gate was proven.

**The generalizable lesson, which is why this is in the live hand-off rather
than buried in the checklist: a drill that requires weakening the condition
under test is not a drill of that condition.** The guard drill in the same batch
was designed correctly — it overrode `DATABASE_URL` at the *step* level, leaving
migrations working and isolating the failure to the thing being tested — and it
passed.

Consequence for the deploy gate: its **green path is confirmed** (the merge to
`main` ran both jobs, then deployed). Its **red path — a failing build being
blocked — has never been observed**, and is deliberately left to be verified for
free on the first real red build. Do not invent a drill for it.

## Shipped 2026-08-09: B4 — the CVE baseline is clean and the gate is armed

`pillow` 12.2.0 → **12.3.0** and `starlette` 1.2.1 → **1.3.1**, closing all 23
CVEs `pip-audit` found on its first run. **523 passed**, OpenAPI still 73,
Alembic head untouched. `pip-audit` is now **blocking** — `continue-on-error`
is gone from the *Dependency audit* step, so a new advisory goes red.

Two risks this item carried both evaporated, and the reasons are worth keeping:
`fastapi==0.136.3` declares `starlette>=0.46.0` with **no upper bound**, so
there was never a pin to fight; and A3's `httpx2==2.9.1` worry is moot because
**no test imports `TestClient`** (0 matches). Minimum fixing versions were used
rather than latest — Starlette is already at 1.6.0 upstream, and three extra
minors buy no additional CVE coverage.

Full detail in `docs/api-hardening-checklist.md` → *Shipped* → B4.

## Next up: N1

**N1 (structured logging).** `backend/app/` contains **no logging
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
6. **Write the session hand-off** — this file — and append to the Obsidian
   session log before closing. The `docs/` → vault *mirror* no longer needs
   doing by hand; a `Stop` hook syncs it (see *MCP tooling*). The session log
   still does.

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

> **Re-indexed and current as of 2026-08-09.** The graph is at `cf7dec2` —
> `main`'s tip — with 2,664 nodes / 6,083 edges. It now covers X1/C3, B2, and
> N2, so the previous standing caveat (graph at `d715545`, pre-hash `sessions`
> schema, "confirm anything near auth against the working tree") **no longer
> applies** and has been removed rather than left to mislead.
>
> The habit that produced that caveat is still right, though: check
> `graph_stats` → `commitSha` against `git rev-parse HEAD` before trusting a
> structural answer. It is one call, and it tells you whether the map matches
> the territory.

**Obsidian** — the retrieval path for documentation held outside the repo.
Vault root: `C:\Users\mcclu\Desktop\Obsidian\John_Vault`; this project's folder
is `4. Notes\Repository-Docs\inventory-app-git`.

> **Fixed 2026-08-09. Do not re-diagnose this.** The `obsidian` MCP server is
> `@modelcontextprotocol/server-filesystem` and *is* connected — but it was
> reporting the **repo** as its only allowed directory even though
> `~/.claude.json` correctly pointed it at the vault. That is not a
> misconfiguration: the server supports the MCP **roots** protocol, and
> `dist/index.js:578` *replaces* its command-line directories with the client's
> roots at initialization. Claude Code declares the workspace as its roots, so
> the vault argument was discarded every session.
>
> The fix was to make the vault a workspace directory —
> `permissions.additionalDirectories` in `~/.claude/settings.json` (user scope,
> so it is not committed and works from any project). Both directories are now
> allowed, and it took effect live via `roots/list_changed` without a restart.
> Editing the server's `args` would never have worked.

What lives in that folder, and what it is for:

| Path | What it is |
|---|---|
| `reviews/*.md` | **Generated mirrors of all seven `docs/*.md` files.** Not authoritative and not hand-edited — see below. |
| `reviews/Gap Audit.md` | The FastAPI-specific exposure audit the checklist was built from. Vault-native, *not* a mirror; the sync never touches it. |
| `sessions/session-log.md` | Structured per-session log: `## <ISO timestamp>` then `### Summary` / `### Changed Files` / `### Decisions / Context Updates` / `### Follow-ups`. |
| `README.md` | Repo context plus a second, shorter append-log in the same four-section format. |

### The mirror is automated now — do not sync it by hand

`scripts/sync-obsidian.ps1` generates every `reviews/*.md` mirror from `docs/`,
and a **`Stop` hook** in `.claude/settings.local.json` runs it when a turn ends.
Staleness is now structural rather than a thing to remember.

Three properties worth knowing before touching it:

- **It is idempotent, by hash.** Each mirror's header carries
  `<!-- sync-source-sha256: … -->` of the repo file it came from. A file is
  rewritten only when that hash changes, so the hook is a no-op on most turns
  and the vault's own git history stays quiet. This is why running it on every
  turn is safe.
- **It generates rather than copies**, because the mirrors carry vault-only
  additions a copy would destroy: Obsidian frontmatter matching the vault's
  existing taxonomy (`status: stable`, `type: reference`), and per-file
  wikilinks such as the checklist's `[[Gap Audit]]` back-reference. Those live
  in the `$related` map at the top of the script — add to it there, never in the
  vault.
- **`-Check` reports staleness without writing** and exits 1 if anything is
  behind. That is the form to use from CI or a pre-commit hook if this is ever
  wanted as a gate.

The vault path defaults inside the script and is overridable with
`INVENTORY_VAULT_DOCS`, so the committed hook config does not hard-code one
machine's layout.

**Still manual: `sessions/session-log.md` and `README.md`.** Those are append-only
narrative, not mirrors, and nothing generates them. The log had a real gap once —
08-07 and 08-09 were never written, closed later by a labelled backfill.
**Append to it in the same session as the work**, for the same reason step 5
above exists.

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
- **Commit rhythm changed with N2 (2026-08-09).** The old rule — *nothing gets
  committed until the owner explicitly asks*, work batching up and landing on
  `main` in one go — **no longer applies.** CI cannot be built or verified
  without pushing, so the batch landed and normal per-change commits resumed.
  `main` is now protected by the deploy gate rather than by withholding work.
  Still ask before **merging to `main`**, because that is what deploys.
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
