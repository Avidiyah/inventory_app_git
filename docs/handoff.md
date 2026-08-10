# Session Hand-off

Last updated: **2026-08-10**, end of the session that shipped **B3** (every
route rate limited at 60 requests/second per caller) and then **X3** (every list
endpoint bounded at 5,000 rows). **Tier 1 is empty and nothing is queued.**

**B3 is closed** — pushed, deployed, and owner-validated in the browser.
**X3 is committed and not pushed**, and it is the only outstanding thing.

X3 is worth reading about before touching anything list-shaped: it was logged as
*paginate the collection endpoints* and shipped as a **safety ceiling with no
frontend work**, because measuring first showed the symptom was not occurring
and that two of the endpoints back client-side search rather than list views.

The session before shipped **C1** (every static role gate in
`routers/work_orders.py` is declarative), **C4** (FastAPI's docs endpoints are
closed in production), and **C2's ordering half** (tool custody sorted by name),
then demoted the rest of C2 to Tier 2. All three are pushed and live.

The same day, the database rollback/cutover closed — caused by importing 800+
work orders that did not belong to the company, requiring the first production
Postgres rollback. The Render Blueprint moved from `inventory-db` to
`inventory-db-copy` in `22164bb`, and the copy's plan and PITR window were
re-verified in the dashboard afterwards, so N5's guarantees hold on the live
target. Earlier the same day, N1 (structured logging) and B1 (upload size caps)
were committed, pushed to production, and verified. The session before implemented N1 and closed B4's two loose
ends; the one before that shipped **B4** (the CVE baseline), scoped the **deploy
gate** so docs pushes stop deploying, and fixed **Obsidian vault access** plus
automated the docs mirror. Earlier: N2 (CI), N5 (paid Postgres), B2 (DB-aware
health check), X1 + C3 (auth hardening), and the checklist restructure.

This file is the **live** hand-off: where the work stands and what to pick up
next. It is not a history, and it is not the backlog.

**For "what is left to do", read `docs/open-work.md`** — one index of every
named improvement not yet implemented, across all three backlogs. For durable
behavior and contracts start with `docs/current-state.md`. The full routing
table is in `docs/project-summary.md` → *Documentation map*.

**The docs were de-cluttered on 2026-08-10.** Shipped history moved out of the
hardening checklist and the UX review into `docs/api-hardening-archive.md` and
`docs/ux-review-archive.md` — it had reached 79% and 84% of those files
respectively, with the open queue underneath it. Nothing was deleted or edited
in the move, and **no item ID changed**.

---

## Start here

> **Database rollback/cutover is closed.** Owner confirmed on 2026-08-10 that
> the production database was successfully rolled back after an import of 800+
> wrong-company work orders. The earlier live service mismatch was fixed by
> applying the Render environment/Blueprint binding to `inventory-db-copy`; no
> further rollback copy is needed for this incident.
>
> **The copy's settings were verified in the dashboard on 2026-08-10** and match
> what N5 closed on: plan `basic-256mb` (1 GB storage), PITR up to 3 days,
> binding confirmed and intended to stay. No follow-up remains on the database.
>
> Historical diagnostic note, retained because it explains the failure mode:
> the CI deploy hook proved only that the container restarted. Render's
> `fromDatabase` reference updates on Blueprint sync. Public `/healthz` proves
> only database reachability; Admin `/db-test` reports PostgreSQL logical
> names, not the Render resource display name.

> **X3 shipped and is the one thing not yet pushed.** Every list endpoint is
> capped at **5,000 rows** (`MAX_LIST_ROWS`), truncation reported as
> `event=list.truncated`. `GET /items/search-index` was deleted outright.
> **659 passed**, OpenAPI **73 → 72**, no migration, **no frontend file
> changed**.
>
> **It was logged as pagination and deliberately is not pagination.** Asking
> what the row counts actually were — hundreds — plus finding that `/items/`
> and `/users/` back *client-side* search in Scan/Stock manual entry, History
> and Mass Stage, turned the largest change in this project's recent history
> into one with zero frontend work. **That is now three items in a row (C2, B3,
> X3) where the checklist figure came from reading code rather than from data.**
>
> **The ceiling's real product is the log line.** If `event=list.truncated`
> never appears, nothing needs doing. When it does, it names which list
> overflowed, so pagination gets scoped by evidence instead of all six at once.
>
> **B3 is shipped, pushed, deployed and validated.** Every non-exempt path is
> capped at 60 requests/second per caller, returning 429 + `Retry-After: 1`.
> **632 passed** at the time, OpenAPI 73, no migration.
>
> `11a0b42` + `1c094de` went out in CI run **31421105913** — all three jobs
> green, `==> Deployable changes present.`, hook `dep-d9t1rke7bikc73afrm00`.
> `GET /healthz` returned 200 afterwards.
>
> **The owner's browser pass came back clean on 2026-08-10 and B3 is closed.**
> Ordinary field work does not approach the cap — which was the only real risk
> this change carried.
>
> **What that pass does and does not prove, because the two halves rest on
> different evidence.** It proves the limiter does not **misfire**. It does not
> prove it **fires**, since nothing in ordinary use should ever reach 60/s;
> that half rests on the 47 local tests, 16 of which drive the real ASGI stack
> and assert the 429, its `Retry-After`, the exemptions, and the middleware
> ordering. Read the two together rather than treating the browser pass as
> end-to-end proof of the whole feature.
>
> **Two direct probes of the live service returned no 429 and were deliberately
> not escalated.** 65 sequential requests, then 150 at 50-way concurrency, both
> to a non-exempt 404 path. Two explanations that cannot be separated from
> outside: the requests may never have landed 60-within-one-second (each curl is
> a fresh TCP+TLS handshake to a free-tier service), or the probe may have hit
> the old container. Separating them meant load-testing production for a signal
> the browser pass gives for free. **Do not re-run this probe** — it was
> considered and dropped on purpose.
>
> **What the probe did establish is worth keeping:** it took deliberate 50-way
> concurrency to even have a chance of reaching the cap. Sequential real-world
> request patterns cannot approach 60/s. That is the gap the number was chosen
> to sit in, now observed rather than assumed.
>
> **The cap was the owner's call, not a measured one, and that is worth knowing
> before anyone tunes it.** The plan of record was to pull real volume from N1's
> `event=request` lines first and possibly demote B3 to a Tier 2 note; the owner
> specified 60/s per user, API routes only, before that ran. So the number is a
> policy decision. Anyone changing it is changing a choice, not correcting an
> estimate. The measurement was never done and the analyzer script written for
> it was scratch-only — if the question comes back, it has to be rebuilt.
>
> **One measurement did land and it changed the design.** `/` and `/static/*`
> go through the same middleware chain as the API, and a cold SPA load is ~35
> requests fired nearly at once. A *global* 60/s would therefore have been
> tripped by two people refreshing at a shift change, serving a 429 for a
> JavaScript module — the blank page this app has history with. Hence per
> caller, and hence `/`, `/static/*` and `/healthz` exempt: neither counted nor
> refused.
>
> **C1 and C4 are both shipped, deployed, and verified. C2's ordering half
> shipped after them and C2 itself was demoted.**
>
> C1 (`b314d06` + `eb7f4a2`) went out on its own; the owner ran all eight
> browser checks against the deployed service and every one passed, including
> the Supervisor-level `lookup` check that would have caught a wrong minimum.
>
> C4 (`9388ed8`) went out with three doc commits in run **31415331711** —
> `583 passed in 21.42s`, `==> Deployable changes present.`, hook
> `dep-d9t0rl8n74is739jo6ig`. Confirmed on the live service: `/openapi.json`,
> `/docs`, `/redoc`, and `/docs/oauth2-redirect` all return **404**, while
> `/healthz` and `/` still return 200. **The public schema is closed.**
>
> **A dashboard deploy earlier the same day rebuilt production from `eb7f4a2`
> with no CI run behind it** — 33 minutes after run `31402048099`. Healthy and
> harmless, but it disproves a claim this repo carried: see *CI is not the only
> path to production* below.
>
> `2cb99c9` (C2's ordering half) **was pushed** and is live. An earlier revision
> of this file said it was outstanding; that was stale by the time it was read.

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
| `9388ed8` | **C4** — the docs endpoints are closed in production (pushed, deployed) |
| `e11b8b0` | the correction that a dashboard deploy bypasses CI |
| `b9c3b94` | `inventory-db-copy` re-verified — N5's guarantees hold on the live target |
| `2cb99c9` | **C2's ordering half** — tool custody sorted by name (pushed) |
| `775f1a2` | the hand-off rewrite that queued B3 (pushed) |
| `11a0b42` | **B3** — 60 req/s per caller on every non-exempt route (pushed, deployed) |
| `1c094de` | B3's own hash recorded in this file (pushed) |

**Tier 1 emptied and was then refilled by the owner with X3.** C1, C4, C2's
ordering half and B3 have all shipped; the rest of C2 was demoted to Tier 2
after its symptom turned out not to be occurring. **Nothing left on the list
exposes anything to an unauthenticated caller** — C4 was the last one.

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

**Ahead of `origin/main` by X3's commits; everything through B3 is pushed and
deployed.** Expect an `[ahead]` marker and an otherwise clean tree.

**X3 touches `backend/**`, so its push deploys.** Two properties make it worth
its own push and its own browser pass rather than riding along with anything:

- it changes **six list endpoints at once**, which is every list in the app; and
- it **removes a route** (`/items/search-index`), taking OpenAPI 73 → 72. That
  is the only route removal in this whole run.

**What to look at once it deploys.** Every list should be indistinguishable from
today — that is the entire claim, since the ceiling sits far above any real
data. Worth clicking: Find Item *Load All Items*, Scan/Stock manual item search,
the History item filter, Mass Stage, Tools, Users, and Work Orders *Show all*.
If any list comes back **short or empty**, that is the regression to look for,
and `event=list.truncated` in the logs would confirm it immediately.

B3 was the highest-blast-radius change before it: it sits on **every** route in
the app, in middleware, ahead of routing. It went out on its own push
accordingly, and **its browser validation passed with nothing open.** Ordinary
use is unaffected, as designed.

**The failure mode to recognize if it ever appears later.** A 429 on a static
asset would render as a blank or half-styled page rather than as an error
message. That should be impossible — `/`, `/static/*` and `/healthz` are exempt
and there is a test firing 200 consecutive requests at each to prove it — but it
is the symptom to connect back to this change, because nothing about a blank
page says "rate limit". Likewise, a `Too many requests. Please slow down.`
banner during ordinary work would mean the cap is mistuned for real field
behaviour, and the fix is the **number**, not the exemption list.

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

What it cost was small and is now closed: production served C1's role
annotations in a public `/openapi.json` for roughly two and a half hours,
between C1's deploy and C4's. Reconnaissance-grade, and shut by
`dep-d9t0rl8n74is739jo6ig`.

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

**Superseded for current production targeting — and re-verified on the new
target, so nothing reopens.** On 2026-08-10 `render.yaml` was changed to point
`inventory-app` at the existing Render Postgres instance `inventory-db-copy`.
The evidence in this N5 section belonged to the original `inventory-db`, so the
copy was checked in the dashboard rather than assumed equivalent: plan
**`basic-256mb`** (1 GB storage), **PITR up to 3 days**, binding confirmed and
intended to stay. Same guarantees, active target. **This follow-up is closed.**

One figure that had never been written down anywhere: **1 GB of storage.** Not a
near-term concern, and structurally rather than by estimate — the app persists
no binary data at all, so growth is rows only. It is still a hard ceiling with
no monitoring, and `render.yaml` no longer declares the database, so nothing in
the repo would notice it being approached. Detail in the checklist's N5 entry.

**Tier 0 is now empty.** Nothing left on the list has an external clock.

## CI is not the only path to production

`render.yaml` claimed it was, and that claim was disproved in use on
2026-08-10. **A Manual Deploy or Blueprint sync from the Render dashboard
rebuilds the configured branch tip and runs nothing** — no suite, no
`pip-audit`, no Alembic head check. `autoDeploy: false` closes the
push-triggered path; it does not close the dashboard.

Observed: a full rebuild started at **15:42:51Z** with the last CI run
(`31402048099`) at **15:09:18Z**. The deploy was healthy and harmless, because
the branch tip `eb7f4a2` had already passed CI when it was pushed.

**The hazard is the case where those two diverge.** A dashboard deploy while
`main` carries unpushed local work ships the *last pushed* commit, not what is
in the working tree — so it can silently roll production backwards past work
that was never pushed. That is exactly the shape of this session's state: C4 has
been committed locally for some time while production runs `eb7f4a2`.

Not a defect to fix — the dashboard is a necessary escape hatch, and the DB
cutover needed it. Recorded so nobody re-derives it, and so the N2 evidence
(*"the hook is the only path to production"*) is read with this qualifier
attached.

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

Full detail in `docs/api-hardening-archive.md` → B4.

## Shipped 2026-08-09: N1 — the app can be diagnosed now

`backend/app/` went from **zero** logging of any kind to logfmt on stdout with a
request id on every request and `user_id` on every authenticated one. New module
`app/logging_config.py`; call sites in `main.py` (middleware + `/healthz`),
`auth_deps.py`, and `routers/auth.py`. **548 passed** (523 + 25 new), OpenAPI
still 73, Alembic head untouched. Full decision record and the evidence table in
`docs/api-hardening-archive.md` → N1.

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
evidence table in `docs/api-hardening-archive.md` → B1.

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

## Shipped 2026-08-10: C1 — the role gates are declarative

The five in-body 403 gates in `routers/work_orders.py` are now
`Depends(require_min_role(...))`. Roles are unchanged and the response body is
byte-identical (`auth_deps.py:73` raises the same detail string the inline
versions raised). **575 passed**, OpenAPI still 73, Alembic head untouched, zero
files under `backend/static/`. Full decision record and evidence table in
`docs/api-hardening-archive.md` → C1.

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
of the tree* for why that mattered and what it briefly cost.

## Shipped 2026-08-10: C4 — the docs endpoints are closed in production

`main._doc_urls(production=)` returns `None` for `docs_url` / `redoc_url` /
`openapi_url` when `COOKIE_SECURE` is true, which **un-mounts** the routes
rather than gating them — production returns a plain 404 for all four
(`/docs/oauth2-redirect` is derived from `docs_url` and goes with it).
`render.yaml` needed no change; it already sets `COOKIE_SECURE: "true"`. **583
passed**. Full record in `docs/api-hardening-archive.md` → C4.

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

## Shipped 2026-08-10: C2's ordering half — and C2 itself was demoted

`_custody_query` (`services/tools.py`) ended at `.having(net > 0)` with **no
`ORDER BY`**, so the order of holders within a tool was whatever Postgres
returned. That is a user-visible list on the Tools page with an unspecified
order — stable in practice, guaranteed by nothing, and free to change after a
vacuum or a plan change. It now orders by first name, last name, then
`assigned_to_id`. **585 passed.**

Three things worth carrying forward:

- **The tiebreaker is load-bearing.** Full names are *not* unique in this system
  (`docs/current-state.md` → `users`), so name alone would leave two same-named
  holders undefined relative to each other. `assigned_to_id` closes that, and
  `test_custody_order_is_deterministic_for_duplicate_full_names` pins it by
  asserting two reads agree rather than asserting which twin wins.
- **Splitting the item is what made it cheap.** C2 was one "~half day, Class C,
  one-time visible reshuffle" item. It was really two changes with completely
  different economics: a five-minute correctness fix that carried *all* the
  visible risk, and a half-day optimisation that carried none. Doing the small
  half first means the big half is now provably invisible — a consolidated
  all-tools query returns the same order as the per-tool one. Worth looking for
  this shape in other items: the expensive part and the risky part are not
  always the same part.
- **The symptom was never occurring.** The owner confirmed the Tools page is
  accurate and performing as expected. The item's "200 tools = 201 queries" came
  from reading the code, not from the data. Asking what the number actually was,
  rather than implementing against the write-up, is what turned a half-day item
  into a five-minute one.

**C2 is now a Tier 2 standing note**, trigger: the Tools page feels slow, or the
tool count grows enough to matter.

## Shipped 2026-08-10: B3 — every route is rate limited

New `rate_limit` middleware in `main.py` caps **every non-exempt path at 60
requests/second per caller**, returning 429 with `Retry-After: 1`. Pure policy in
`domain/rate_limit.py`, in-memory counters in `services/rate_limit.py`, three
test files (`test_rate_limit.py`, `test_rate_limit_service.py`,
`test_rate_limit_middleware.py`). **632 passed** (585 + 47), OpenAPI still 73,
Alembic head untouched, no migration. Full record in
`docs/api-hardening-archive.md` → B3.

Five things worth carrying forward:

- **The cap is a policy decision, not a measured one, and the file should not
  pretend otherwise.** The plan of record — written in this file the session
  before — was to pull real volume from N1's `event=request` lines first, and to
  treat "demote B3 to a Tier 2 note" as a legitimate outcome. The owner
  specified 60/s per user, API routes only, before that measurement ran. Nothing
  wrong happened; it is the owner's call to make. But it means the number has no
  field data behind it, and **the honest thing for the next session to know is
  that tuning it is changing a choice, not correcting an estimate.**
- **The measurement that *did* happen is the one that shaped the design.**
  Driving the ASGI stack showed `/` and `/static/*` emit `event=request` lines
  through the same middleware chain as the API, and that a cold SPA load is ~35
  requests fired nearly at once. That killed the global-cap reading of the
  instruction: two people refreshing at a shift change is ~70, so a global 60/s
  would have served a 429 for a JavaScript module. Worth generalizing — *the
  instruction was ambiguous in a way that only showed up once something was
  measured.* "60/s for all users" reads as obviously clear until you know what a
  page load costs.
- **It also corrects this file's own instruction from last session.** The note
  saying "Render's log search over `event=request` will answer it" is wrong as
  written: that search counts asset fetches, so it overstates API volume by ~35
  per refresh. Any future volume question has to filter to API paths first.
- **Exempt means neither counted nor refused, and both halves are load-bearing.**
  Not counted, so page loads cannot spend the budget. *Not refused*, so an
  over-limit caller can still load the SPA that fixes it — otherwise a client
  that ran away once would be locked out of the page needed to recover — and so
  a busy caller cannot fail an unrelated deploy through `healthCheckPath`.
- **Keying had a constraint that only appears when you try to write it.**
  Middleware runs *before* route dependencies resolve, so `get_current_user` has
  not run and there is no user id to key on. The session cookie is the only
  identity available that early. If a future item wants per-*user* limiting
  rather than per-session, that is not a parameter change — it needs the limit
  moved out of middleware into a dependency, with all the per-route wiring that
  implies.

**Pushed, deployed** (`dep-d9t1rke7bikc73afrm00`), **and owner-validated in the
browser on 2026-08-10.** **B3 is closed.** See *Start here* for the one nuance
worth carrying: the browser pass proves the limiter does not misfire, while the
local suite is what proves it fires.

## Shipped 2026-08-10: X3 — every list endpoint is bounded

Six list endpoints returned their whole table. All are now capped at
**`MAX_LIST_ROWS = 5000`** with truncation reported as an N1 line. New pure
policy in `domain/list_limits.py`, applied through `services/_list_cap.py`.
`GET /items/search-index` was **deleted** outright. **659 passed** (632 + 27),
OpenAPI **73 → 72**, Alembic head untouched, **no frontend file changed**. Full
record in `docs/api-hardening-archive.md` → X3.

**The item asked for pagination. Pagination is deliberately not what shipped**,
and that is the whole story of this one.

Five things worth carrying forward:

- **Asking what the number actually was turned this from the largest change in
  the project's recent history into a no-frontend one.** The owner confirmed
  production holds *hundreds* of rows. That is the third time in three items —
  C2's "200 tools = 201 queries", B3's request volume, now X3's unbounded
  lists — that a checklist figure came from reading code rather than from data.
  **The pattern is now strong enough to treat as a rule: before building what
  an item describes, ask what the number actually is.**
- **Exploring found something the item did not know about itself.** `/items/`
  and `/users/` are not merely list views — they are bulk reference-data loads
  backing *client-side* search. `transactions.js:140` (Scan/Stock manual entry)
  and `history.js:387` each fetch every item once per session and filter
  locally on each keystroke; `massStage.js`, `workOrders.js` and `tools.js` do
  the same. Paginating them would have rewritten core field workflow. **A list
  endpoint's consumers are not always list views — check before assuming a
  page contract is a backend change.**
- **The ceiling's real product is the log line, not the cap.**
  `event=list.truncated list=<name> cap=5000` is the trigger that says
  pagination is finally needed, and it names *which* list overflowed — so that
  work gets scoped by evidence instead of doing all six at once. If it never
  appears, nothing needs doing. That is why exactly `MAX_LIST_ROWS` is *not*
  treated as truncation, and why a caller's own smaller `limit` is not either:
  a signal that cries wolf is a signal people learn to ignore.
- **`GET /work-orders/` could not be made uniform, and the reason is X2.** Its
  ordering is decided in Python because `schedule_date` is raw text, so the
  ceiling bounds the *response*, not the query. Its omitted-`limit` call also
  stopped taking a separate uncapped branch and now runs A6's
  rank-then-hydrate path universally — same rows, same order, strictly less
  loading. That branch switch is the one behavioral risk in the change and it
  is pinned by its own test.
- **Deleting beat capping for `/items/search-index`.** Zero callers anywhere;
  it returned every live item name and barcode to any signed-in user and served
  nothing. Route, schema, service function and test assertions all went. **The
  cheapest fix for an unbounded endpoint is not having one** — worth checking
  for on any future item of this shape.

**Not yet pushed, deployed, or browser-validated.** See *State of the tree*.

## Next up: nothing is queued

**Tier 1 is empty again.** Every item on the original audit is now shipped, a
Tier 2 standing note with a named trigger, or ruled out of scope.

**Do not invent an item to fill it.** The last two items questioned before being
built — C2 and X3 — both described symptoms that were not occurring, and both
got dramatically cheaper for having been checked against data first. The honest
options, in order:

1. **Finish X3.** It is committed, unpushed, and unvalidated. Push, deploy, and
   confirm the browser pass below before starting anything new.
2. **Re-read Tier 2 for a trigger that has fired.** `C2` (Tools page feels
   slow), `N4` (a CDN is introduced), `N8` (someone wants a working API
   explorer), `N3` (a second instance — note B3's per-process rate-limit
   counters are already on its list), `N6` (boundary rule, no trigger).
3. **Ask the owner what actually hurts.** The list is a code audit and has
   never been the only source of work. `IMP-004` (the Mass Stage redesign)
   remains the one open requested improvement.

---

## The session workflow

This is the sequence the owner runs a working session by. Follow it in order;
each step's output is the next step's input.

1. **Read all current documentation first.** Every file under `docs/`, not
   just the one that looks relevant — though the two archives
   (`api-hardening-archive.md`, `ux-review-archive.md`) are reference-on-demand
   rather than required reading, and `open-work.md` is the fastest way in. The routing between them is in
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

> **It re-indexes on push to `main`, and as of 2026-08-10 it is behind again.**
> `graph_stats` → `commitSha 22164bb`, five commits back: the graph predates
> C1, C4 and C2's ordering half, so its view of `routers/work_orders.py` still
> shows the in-body 403 gates C1 removed. Check `commitSha` against
> `git rev-parse HEAD` every session; it is one call, and the failure mode is
> silent. **Check the Graphify account's plan and usage first** — that was the
> cause last time and nothing in this repo can fix it.
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
| `reviews/*.md` | **Generated mirrors of every `docs/*.md` file.** Not authoritative and not hand-edited — see below. |
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
