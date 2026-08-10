# Session Hand-off

Last updated: **2026-08-10**, after owner confirmation that the database
rollback/cutover is successful and closed. The incident was caused by importing
800+ work orders that did not belong to the company, requiring the first
production Postgres rollback. Earlier the same day, **C1** (every static role
gate in `routers/work_orders.py` is declarative now) and **C4** (FastAPI's docs
endpoints are closed in production) were implemented on top of the
database-target cutover and committed together, **awaiting one push**. That
cutover — the Render Blueprint moving from `inventory-db` to `inventory-db-copy`
after the bad work-order import — landed in `22164bb` and **is pushed**. Earlier
the same day, N1 (structured logging) and B1 (upload size caps) were committed,
pushed to production, and verified. The session before implemented N1 and closed B4's two loose
ends; the one before that shipped **B4** (the CVE baseline), scoped the **deploy
gate** so docs pushes stop deploying, and fixed **Obsidian vault access** plus
automated the docs mirror. Earlier: N2 (CI), N5 (paid Postgres), B2 (DB-aware
health check), X1 + C3 (auth hardening), and the checklist restructure.

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

## Start here

> **Database rollback/cutover is closed.** Owner confirmed on 2026-08-10 that
> the production database was successfully rolled back after an import of 800+
> wrong-company work orders. The earlier live service mismatch was fixed by
> applying the Render environment/Blueprint binding to `inventory-db-copy`; no
> further rollback copy is needed for this incident.
>
> Historical diagnostic note, retained because it explains the failure mode:
> the CI deploy hook proved only that the container restarted. Render's
> `fromDatabase` reference updates on Blueprint sync. Public `/healthz` proves
> only database reachability; Admin `/db-test` reports PostgreSQL logical
> names, not the Render resource display name.

> **C1 is live and validated. C4 is committed but unpushed, and pushing it is
> the next action.**
>
> The batch did not hold: C1 (`b314d06` + `eb7f4a2`) was pushed on its own while
> C4 was still being written. CI run **31402048099** went green, the classifier
> logged `==> Deployable changes present.`, and the hook fired
> (`dep-d9suk4p42hec73bo2ov0`). **The owner ran all eight browser checks against
> the deployed service on 2026-08-10 and every one passed**, including the
> Supervisor-level `lookup` check that would have caught a wrong minimum. C1 is
> closed with nothing outstanding.
>
> **C4's three live checks cannot run yet** — `/openapi.json`, `/docs`, and
> `/redoc` returning 404 all require the push. Until then the live
> `/openapi.json` still answers with 113 KB. That is the current state, not a
> failure.
>
> **The consequence is small but real and currently open.** C1 added
> `responses={403: ...}` naming the role each gated route requires, and that
> lands in `/openapi.json` — which is public until C4 ships. So the live schema
> right now states, for eight routes, exactly which role is needed. That is
> reconnaissance, not a breach: no rows, no credentials, no bypass, every gate
> still enforced. But it is precisely the window the batching was supposed to
> avoid, and **pushing C4 (`9388ed8`) closes it.** 583 passed locally.

**N1 and B1 are shipped, pushed, green, and live in production.** Nothing is
waiting on a decision for those items.

| Commit | What |
|---|---|
| `62c32aa` | **B4** — `pillow` 12.3.0, `starlette` 1.3.1, `pip-audit` now blocking |
| `a99ad37` | the hand-off rewrite for the post-B4 state |
| `a6572e3` | **N1** — structured logging, request id per request |
| `5053ba2` | **B1** — 10 MB / 25 MB upload caps on the two upload routes |
| `45aa9ba` | B1's own hash recorded in this file |
| `e5cd587` | the **C4 decision** — close the docs endpoints in production |
| `22164bb` | the **database-target cutover** to `inventory-db-copy` (pushed) |
| `b314d06` | **C1** — the five in-body 403 gates are declarative (pushed, deployed) |
| `eb7f4a2` | C1's own hash recorded in this file (pushed) |
| `9388ed8` | **C4** — the docs endpoints are closed in production (**not pushed**) |

**Tier 1 now starts at C2** (~half day). Full order: **C2 → B3.** C1 and C4 are
done, and **nothing left on the list exposes anything to an unauthenticated
caller** — C4 was the last one, so the checklist's third ordering criterion has
stopped discriminating between the remaining items.

### B4's two loose ends are closed (2026-08-09, next session)

Both were open at the end of the B4 session and both have now been shut. Kept
here rather than deleted because the *first* one has a durable lesson attached.

1. **Production is confirmed healthy.** The owner supplied the URL —
   `https://inventory-app-gb1c.onrender.com` — and `GET /healthz` returned 200
   `{"status":"ok"}`. B4 is live and the database is reachable from the
   deployed service. The URL is now recorded in `docs/current-state.md` →
   *Runtime And Stack* → *Deployment*, with the caveat the owner attached: **it
   can change**, so the Render dashboard is the authority and that line is a
   convenience. The lesson worth keeping: B2 built a health check so a broken
   deploy would fail loudly, and it sat unusable for a session because nobody
   had written down where to point it.

2. **The barcode upload path is validated.** The owner clicked through it after
   the Pillow 12.2.0 → 12.3.0 bump and reports everything running as it should.
   B4's one plausible behavior surface is clear.

**Still incidentally true:** N7 closed when N2 installed `libzbar0` in CI — the
first time the `pyzbar` native dependency was handled outside a container.

### State of the tree

**`origin/main` is at `eb7f4a2` (C1, deployed). C4 (`9388ed8`) sits on top of
it, committed and unpushed. Expect `[ahead 1]`.**

C1 and C4 were *planned* as one push — both Class C, both small, both touching
what the API exposes and to whom — for one CI run, one deploy, and one
browser-validation pass. **That plan did not survive contact:** C1 was pushed on
its own mid-session, before C4 existed.

**The lesson is worth more than the batching was.** The intent lived only in
this file and in the session's head; nothing enforced it, and a perfectly
ordinary `git push` broke it without anyone deciding to. If a future pair of
items genuinely must ship together, the sequencing has to be a property of the
work — one branch, or one commit — not a note saying "don't push yet." A
plan that can be defeated by the most routine command in the workflow is not a
plan.

What it cost here was small and is described under *Start here*: production is
serving C1's role annotations in `/openapi.json` until C4 lands. Pushing C4 is
the fix.

Before the database-target cutover, the tree was clean, pushed, and in sync
with `origin/main`. N1 (`a6572e3`) and B1 (`5053ba2`) shipped together on
2026-08-10: CI run **31389720697** ran all three jobs green — Static checks,
Backend suite, and Deploy to Render — and the deployed service came back
healthy.

**Production verification, done on the live service rather than inferred:**

| Check | Result |
|---|---|
| `GET /healthz` | **200 `{"status":"ok"}`** — B2's real `SELECT 1`, so Postgres is reachable from the deployed container |
| `X-Request-ID` | **`fec6d5fa1d68`** — N1's middleware confirmed live in production, its first end-to-end proof |
| A4 security headers | CSP, `X-Frame-Options: DENY`, HSTS all present |

That HSTS header is worth noting for C4: it is emitted only when
`COOKIE_SECURE` is true, so this response is direct evidence that the flag is
actually set in production — which is what makes it usable as C4's
production signal rather than a second flag.

**One workflow point worth keeping.** The previous session left N1
*uncommitted* because pushing deploys, which conflated two different things.
Committing is local and free; pushing is the deploy. Separating them means work
cannot be lost or half-reviewed while still leaving the deploy a single
explicit decision.

The previous standing direction — *nothing gets committed until the roadmaps are
done*, which this file carried for several sessions — **is no longer in force.**
It ended with N2, because CI cannot be built or verified without pushing commits
and opening a PR. Normal commit-per-change flow now applies, and `main` is
protected by the gate rather than by holding work back.

So: a dirty `git status` here would be real work in progress, not the old
deliberate posture. Do not look for a large batched diff.

**The session-table migration has been deployed.** `fbc4e6a8d0f2` drops and
recreates `sessions`, so every user was signed out when it landed. That was
always the intent (it is what clears the accumulated plaintext credentials) and
it has now happened — do not treat it as still-pending, and do not schedule it
again.

**Docs-only pushes no longer deploy** (decided and shipped 2026-08-09). The
`deploy` job now classifies the push before firing the hook.

> **A green "Deploy to Render" job does not mean a deploy happened.** Read this
> before concluding the classifier has regressed. The job always runs — it is
> the *step* that is conditional — so a docs-only push shows three green jobs,
> identical at a glance to a push that deployed. The difference is only visible
> in the log: `==> Nothing under backend/ or render.yaml changed; skipping
> deploy.` followed by a `No deploy needed` step. Confirmed on run
> **31389939289** (2026-08-10, docs-only), which went fully green while leaving
> production untouched. `gh run view <id> --log` is how you tell them apart;
> the job list cannot.

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

> **Observed for real on 2026-08-10, having been theory until then.** An empty
> commit (`c06eb00`, pushed to nudge the Graphify indexer) hit the empty-diff
> branch: `No file changes in range; deploying.` — and it deployed. No damage:
> the tree at `c06eb00` is byte-identical to `80b0981`, so it redeployed
> already-verified code, and `/healthz` returned 200 afterwards. But it is a
> **production restart**, which on the free web tier means a cold start for the
> next caller.
>
> **So: never use `git commit --allow-empty` to trigger anything on this repo.**
> A trivial docs-only commit delivers the same push webhook and classifies as
> skip, leaving production untouched. The fall-through is correct behavior and
> should not be changed — it just makes the empty commit the one nudge to avoid.

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

**Superseded for current production targeting.** On 2026-08-10, `render.yaml`
was changed to point `inventory-app` at the existing Render Postgres instance
`inventory-db-copy`. The paid-plan/PITR evidence in this N5 section belongs to
the original `inventory-db`; verify the copy's plan and recovery settings in
Render before relying on the same operational guarantee for the active target.

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

**The counter-example, from later the same day.** The deploy-scoping change
(`c7ae670`) had both of its branches verified on *real pushes*, with nothing
modified to make either one fire: the docs/tooling push that carried it
classified as skip and left production untouched, and the next push (`62c32aa`,
which changed `backend/requirements.txt`) classified as deployable and fired the
hook. That is what a valid drill looks like — the condition under test was
exercised, not weakened. Note the asymmetry with the `always()` failure: there
the drill had to *change* the thing being tested in order to run at all, which
was the tell.

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

## Shipped 2026-08-09: N1 — the app can be diagnosed now

`backend/app/` went from **zero** logging of any kind to logfmt on stdout with a
request id on every request and `user_id` on every authenticated one. New module
`app/logging_config.py`; call sites in `main.py` (middleware + `/healthz`),
`auth_deps.py`, and `routers/auth.py`. **548 passed** (523 + 25 new), OpenAPI
still 73, Alembic head untouched. Full decision record and the evidence table in
`docs/api-hardening-checklist.md` → *Shipped* → N1.

Three things from it worth carrying forward:

- **A failed login logs the username only if the account exists.** Otherwise
  `user=unknown`. Logging the submitted string verbatim would put a password in
  the logs the first time someone types it into the username field. If a future
  item wants to see which invented usernames were probed, that is a deliberate
  reversal of a safety decision, not an oversight.
- **`bind_user` mutates a shared dict on purpose.** Starlette's
  `BaseHTTPMiddleware` runs the route in a separate anyio task holding a *copy*
  of the context, so a `ContextVar.set()` in a dependency never reaches the
  middleware. If someone "cleans that up" into a `.set()`, `user_id` silently
  disappears from the request line and nothing outside
  `test_bind_user_mutates_in_place_rather_than_rebinding` will notice.
- **Uvicorn's access log was deliberately left on.** Ours is richer; uvicorn's
  is the one that still works if our middleware breaks. Verified there is no
  double-print: uvicorn's `LOGGING_CONFIG` declares no `root` key and sets
  `propagate=False`.

**Verification drove the ASGI stack directly rather than booting a server.**
That pattern is reusable and respects the browser-validation rule — it proved
middleware ordering, the header, and the task-boundary behavior without a
running service.

## Shipped 2026-08-09: B1 — the two upload routes are capped

`routers/barcodes.py` and `routers/work_orders.py` no longer call
`file.file.read()`. Both go through `read_capped` in the new
`app/routers/_uploads.py`, at **10 MB** for the barcode image and **25 MB** for
the work-order CSV. **562 passed** (548 + 14 new), OpenAPI still 73, Alembic
head untouched, zero files under `backend/static/`. Full decision record and
evidence table in `docs/api-hardening-checklist.md` → *Shipped* → B1.

Three things worth carrying forward:

- **The item's own framing was half wrong, and the correction is the
  interesting part.** It said both routes read the upload "into memory
  unbounded". Starlette's multipart parser has already received the whole body
  and spooled it — to **disk** past 1 MB — before any handler runs. So receiving
  was memory-bounded already; the unbounded part was `.read()` with no argument
  materialising that spooled file as one `bytes` object for Pillow or the CSV
  parser. The cap closes that and **cannot** stop a large body being
  transmitted. If a future item wants that, it needs a `Content-Length` check in
  middleware — considered here and deliberately not done.
- **The size check is written twice and both halves are load-bearing.**
  `UploadFile.size` is exact and lets an oversized upload be refused without
  reading anything, but it is `None` for any `UploadFile` the multipart parser
  did not build. The bounded `read(limit + 1)` is the guard that cannot be
  bypassed. Deleting either one as redundant breaks a real case;
  `test_an_upload_with_no_declared_size_is_still_capped` is the tripwire.
- **The role gate runs before the size check on the import route**, so an
  unauthorised caller gets 403 and learns nothing about the cap. Pinned by
  `test_the_role_gate_still_runs_before_the_size_check`, because transposing two
  adjacent lines is a silent change.

**Owner browser validation passed 2026-08-10.** An ordinary barcode photo upload
and an ordinary work-order CSV import both behave as before against the deployed
service. **B1 is closed with nothing outstanding.**

## Shipped this session: C1 — the role gates are declarative

The five in-body 403 gates in `routers/work_orders.py` are now
`Depends(require_min_role(...))`. Roles are unchanged and the response body is
byte-identical (`auth_deps.py:73` raises the same detail string the inline
versions raised). **575 passed**, OpenAPI still 73, Alembic head untouched, zero
files under `backend/static/`. Full decision record and evidence table in
`docs/api-hardening-checklist.md` → *Shipped* → C1.

Four things worth carrying forward:

- **Moving a gate into a dependency does not document it.** The item argued the
  in-body gate was "invisible in the OpenAPI schema" — but FastAPI does not
  infer a 403 from a dependency merely capable of raising one, so a dependency
  is *equally* invisible. Half of what C1 argued for would not have shipped
  without the explicit `responses={403: ...}`, which now covers all eight gated
  routes in that module through one `_forbidden` helper.
- **A directly-called handler never resolves its dependencies**, so every test
  that proved a gate by calling the handler with a below-rank user silently
  stops testing it. Three did. Two of them would have kept *passing* against a
  different code path rather than failing — `test_import_route_requires_admin`
  and `test_route_rejects_below_admin` would have gone on asserting a 403 that
  the gate no longer produced. If a future item moves any other gate, look for
  this pattern first; it is the failure mode that does not announce itself.
- **The blast radius was found by running the suite, not by grep.** An initial
  search looked clean because its output had been truncated at a result limit,
  which produced a confident and wrong "exactly one test affected." Same class
  of error as the `gx_find` zero-match described under *MCP tooling*: a tool
  answered a narrower question than the one being asked.
- **`transactions.py:55` is a sixth in-body 403 and is correctly in-body.** It
  gates on `can_transact(role, payload.transaction_type)` — a stock and a
  dispense are the same route with different minimums, so it needs the parsed
  body and cannot be a static dependency. C1's own text claimed the in-body
  gates were "all in `routers/work_orders.py`"; that is now corrected in the
  checklist so nobody re-derives it.

**Pushed, deployed** (`dep-d9suk4p42hec73bo2ov0`), and **owner-validated in the
browser on 2026-08-10** — all eight checks passed against the live service.
**C1 is closed.** It shipped separately from C4 rather than with it; see *State
of the tree* for why that matters and what it cost.

## Shipped this session: C4 — the docs endpoints are closed in production

`main._doc_urls(production=)` returns `None` for `docs_url` / `redoc_url` /
`openapi_url` when `COOKIE_SECURE` is true, which **un-mounts** the routes
rather than gating them — production returns a plain 404 for all four
(`/docs/oauth2-redirect` is derived from `docs_url` and goes with it).
`render.yaml` needed no change; it already sets `COOKIE_SECURE: "true"`. **583
passed**. Full record in `docs/api-hardening-checklist.md` → *Shipped* → C4.

Three things worth carrying forward:

- **The item was wrong about two of its three routes, and measuring first is
  what caught it.** It treated all three as equally exposed. Driving the ASGI
  stack before changing anything showed `/docs` at 1,023 bytes and `/redoc` at
  905 — HTML shells whose only assets come from `cdn.jsdelivr.net`, which A4's
  `default-src 'self'` CSP blocks. Both have rendered blank *everywhere,
  local included*, since A4 shipped. The live exposure was `/openapi.json`
  alone, at **113,156 bytes**. Logged as **N8**.
- **So the item's stated cost was near zero.** "It removes URLs the owner may
  use directly" was the reason this needed a decision at all — and two of the
  three could not be used by anyone. Worth remembering the general shape:
  the cost side of a trade-off is as worth measuring as the benefit side.
- **Closing `/openapi.json` removes the route, not the schema.** `app.openapi()`
  still returns the full dict, so every "OpenAPI operations = 73" check and
  C1's `test_every_gated_work_order_route_documents_its_403` keep working.
  That was the one thing that could have made a 15-minute item expensive, and
  it is pinned by `test_the_schema_is_still_generated_when_the_route_is_closed`.

**There is deliberately no override env var.** Re-enabling the docs in
production takes an edit and a deploy. That friction is the feature — an
`ENABLE_DOCS` flag is exactly the kind of thing that gets switched on for an
afternoon and left on, and CI would not notice.

## Before anything else: push C4

C1 is already live. C4 (`9388ed8`) is committed, verified locally, and **not
pushed** — and it is what closes the public `/openapi.json`. Then:

1. Confirm the CI run is green — and remember that a green *Deploy to Render*
   job is not proof a deploy happened; read the log (see the note above). For
   C1's push the line to look for was `==> Deployable changes present.`
   followed by the hook's `{"deploy":{"id":...}}`.
2. Confirm `GET /healthz` returns 200 on the live service.
3. **Confirm C4 on the live URL**: `/openapi.json` should return **404**. That
   is the single clearest end-to-end proof of this change, it needs no login,
   and it is the one check that shows the window is shut.
4. Confirm `/docs` and `/redoc` also 404.
5. Load the SPA and click through two or three pages. C4 touches no application
   route, so the expected result is that nothing at all is different.

**C1 needs nothing further** — its eight-check pass was completed on the live
service on 2026-08-10. Only C4's four checks above remain, and all four depend
on the push.

## Next up: C2

**C2 (eliminate the tool-custody N+1, ~half day, Class C).** `routers/tools.py`
calls `_tool_response` per tool and each invocation runs a `GROUP BY` aggregate,
so an unbounded `list_tools` is 201 queries for 200 tools. Read the item before
starting: it is riskier than a pure optimisation because `_custody_query` has no
`ORDER BY`, so consolidating will very likely reshuffle the custody rows visible
on the Tools page. That is a one-time visible change, fine as a deliberate one
and not safe as a silent one.

Full Tier 1 order after that: **B3**, and that is the end of the tier.

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
   session log before closing. Then run `scripts/sync-obsidian.ps1 -Check` and
   sync if it reports anything stale: a `Stop` hook is supposed to do this, and
   on 2026-08-10 it did not (see *MCP tooling*). The session log is
   append-only narrative and is always manual.

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

> **It re-indexes on push to `main`, and as of 2026-08-10 it is current.**
> Check `graph_stats` → `commitSha` against `git rev-parse HEAD` every session
> anyway; it is one call, and the failure mode is silent.
>
> **The one time it went stale, the cause was a plan limit, not a bug.** The
> graph sat at `62c32aa` across six pushes on 2026-08-10 while reporting
> `status: ready` — the **free tier has an update cap**, and it had been hit.
> Upgrading the Graphify account cleared it: the next push produced build
> `6306ff13` at `c06eb00` with **2,829 nodes / 6,305 edges** (up from 2,667 /
> 6,085), and `_uploads.py` with its call edges is present. Nothing in this repo
> was ever the problem, and nothing in this repo could have fixed it.
>
> So if it is behind again, **check the account's plan and usage first** rather
> than re-diagnosing webhooks. There is no repository-level webhook (`gh api
> repos/…/hooks` is empty — indexing runs off a GitHub App installation), no
> reindex tool in the MCP surface, and the local `graphify` CLI cannot reach the
> hosted tenant (its full command list has no push/promote/login/sync/upload).
>
> **Uncommitted work is still invisible to it** — that is the case where map and
> territory genuinely differ, and no plan fixes it.

#### `gx_find` takes a term, not a sentence — this cost a wrong conclusion

Worth knowing before using the query tools, because it produced a confident
statement that was not supported.

`gx_find "read_capped upload size cap"` returns **0 matches**. `gx_find
"read_capped"` returns **1**, correctly locating `_uploads.py:86`. Both against
the *same current* graph. The multi-word phrase is not a natural-language query
here — it is matched as a term, and a term with spaces in it matches nothing.

That zero was cited during the staleness diagnosis as proof the graph lacked
B1. **It proved nothing**; it would have returned zero against a perfectly
current graph, as it now demonstrably does. The staleness itself was real, but
the evidence that actually established it was `commitSha` plus a `buildId` that
had not changed. Use `gx_find` with a bare symbol name, or `query_graph` /
`gx_find_seeds` for a real question in prose.

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

### The mirror is scripted — but do not trust the hook to have run

`scripts/sync-obsidian.ps1` generates every `reviews/*.md` mirror from `docs/`,
and a **`Stop` hook** in `.claude/settings.local.json` is meant to run it when a
turn ends. Do not hand-edit the mirrors; run the script.

> **Correction, 2026-08-10 — this file previously claimed "staleness is now
> structural rather than a thing to remember." That is false and was disproved
> the same session it was relied on.** `-Check` reported **all four** changed
> docs stale (`api-hardening-checklist.md`, `current-state.md`,
> `endpoint-map.md`, `handoff.md`) after a turn that edited them, so the hook
> had not fired. Running `scripts/sync-obsidian.ps1` directly fixed it
> immediately — **the script is fine; the hook is what is unreliable.**
>
> So the standing habit is: run `-Check` before closing a session. It is one
> call, it writes nothing, and it is the only thing that actually tells you.
> Treating the hook as a guarantee is what left the vault behind.

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
