# Open Work — every named improvement not yet implemented

**This file is an index, not an owner.** Each item's full write-up — rationale,
file/line references, decision record — lives in the doc named in its row. This
page exists so the answer to *"what's actually left?"* is one file rather than
three, and so nothing open can hide inside an archive.

Last reconciled: **2026-08-10**, after IMP-033 (UX #19) shipped. Nothing below
has been started or scheduled.

> **Keep this in sync when an item ships, is logged, or changes tier.** It is the
> one file here that duplicates information by design, which is exactly the kind
> of file that rots. If it disagrees with the owning doc, the owning doc wins.

---

## The state of things

**Nothing is scheduled.** Tier 1 of the hardening checklist is empty; every item
from the original audit is shipped, a standing note with a trigger, or ruled out
of scope. The 10 items below are real, but none is queued and none has a date.

**#19 was promoted to IMP-033 and shipped on 2026-08-10**, which is the worked
example of how a Tier 3 observation becomes work: it goes into
`docs/improvement-tracker.md` first.

**Do not invent work to fill the queue.** The last three items questioned before
being built — C2, B3, X3 — all described symptoms that were **not occurring**,
and all three got dramatically cheaper for being checked against data first. C2
went from half a day to five minutes; X3 went from a frontend rewrite to a
backend-only ceiling. Ask what the number actually is before building what an
item describes.

---

## 1. Requested features

Owner: **`docs/improvement-tracker.md`**. User-requested behavior, not
framework work.

| ID | Area | What | Status |
|---|---|---|---|
| **IMP-004** | Mass Stage | Collapsible *New Mass Stage* card, collapsed by default; drop the redundant Unit # field; work-order-number-first search flow; group work orders under Communities by Location | Open — flagged *very low priority* since 2026-08-03 |

IMP-001–003, IMP-005–032 and IMP-033 are all Done.

---

## 2. Hardening — standing notes

Owner: **`docs/api-hardening-checklist.md`** → *Tier 2*. None of these is
scheduled work. Each is a real property of the system with a **named trigger**
that would promote it; they are written down so the trigger is recognized when
it arrives rather than rediscovered.

| ID | Class | What | Trigger |
|---|---|---|---|
| **N3** | N | `entrypoint.sh` runs `alembic upgrade head` on every cold start — safe on one instance, races on two. **B3's rate-limit counters are per-process and now sit on this list too** | adding a second instance |
| **N4** | N | SPA served from the API process: blanket `no-cache`, 13 HTML fragments re-read from disk per `/` request, no CDN, no content hashing | introducing a CDN — *deferred by design*, it solves the real blank-page failure |
| **N6** | N | `services/work_orders.py` is 2,008 lines / 59 functions, ~4× the next-largest service | **none — this is a boundary rule, not a refactor request.** New rule-shaped logic belongs behind `domain/work_orders.py` |
| **C2** | C→A | Tool-custody N+1: `list_tools` runs `_custody_query` per tool | the Tools page feels slow, or the tool count grows. Its risky half already shipped, so what remains is now provably invisible |
| **N7** | N | `pyzbar` wraps native `zbar`; on Windows it fails as a missing `libiconv.dll` — an error naming neither the package nor the cause — and takes the app down at **import** time | new dev machine, or a runtime/base-image change |
| **N8** | N | `/docs` and `/redoc` are CSP-broken wherever enabled: assets come from `cdn.jsdelivr.net`, `default-src 'self'` blocks them. Both have rendered blank everywhere since A4 | someone actually wants a working API explorer |

---

## 3. UX observations — never re-audited

Owner: **`docs/ux-review.md`** → *Tier 3*. These are July 2026 findings that
were never promoted or dismissed. The doc itself says they "have not been
re-audited as current priorities." Numbers are the original review's; they are
**not** renumbered, for the same reason hardening IDs are not.

| # | What | Files |
|---|---|---|
| **21** | Supervisor+ *Add Stock* is one toggle deep, behind *Manual entry & stock options*. Flagged to **confirm the tradeoff is intended**, not to change it | `pages/transaction.html`, `views/transactions.js` |
| **23** | No hardware (keyboard-wedge) scanner support. A Bluetooth laser scanner types barcode + Enter — faster and more reliable in warehouse lighting than camera decode — but those keystrokes go nowhere unless an input happens to be focused | `views/scan.js`, `views/transactions.js` |
| **24** | No low-stock signal until a dispense is rejected. Mass Stage already computes *short by N*; Find Item never surfaces it, so the first warning is a refusal on the floor | `views/items.js`, `pages/saved-items.html` |

Characteristics worth knowing before choosing between these, stated without a
recommendation — **the pick is the owner's**:

- **#21 is not an implementation item.** It asks the owner to confirm a
  deliberate tradeoff, so it can be closed with a yes or a no.
- **#23 is additive** — a keystroke accumulator feeding the existing
  `resolveBarcode` path, not a rewrite of the camera flow.
- **#23 and #24 both rest on an assumption worth testing first**, per the
  C2/B3/X3 pattern in *The state of things* above: does the crew actually have
  or want scanners, and is
  anyone being surprised by empty stock?

---

## Ruled out — recorded so they are not re-proposed

| ID | Why it is closed |
|---|---|
| **X2** — move work-order sorting into SQL | **Not safely possible.** `schedule_date` is deliberately raw text; the Python parser catches invalid calendar dates that Postgres `make_date` *raises* on. Replicating it needs PL/pgSQL or a generated column — both schema changes. Superseded by A6, which captured the available win with no behavior change |
| **X3** — paginate the unbounded collections | Promoted 2026-08-10 and **shipped the same day as a safety ceiling rather than pagination**, because the symptom was not occurring and two of the endpoints back client-side search. See the archive |

Also see `docs/api-hardening-checklist.md` → *Verified as non-issues* for
things that were audited and found not to be problems at all (Pydantic v2
migration debt, `BackgroundTasks` durability, API versioning, and others). Those
are not listed here because they are not work.

---

## Where the full record lives

| Doc | Holds |
|---|---|
| `docs/improvement-tracker.md` | every requested feature, open and done |
| `docs/api-hardening-checklist.md` | the live hardening queue, Tier 2 notes, out-of-scope items, verified non-issues |
| `docs/api-hardening-archive.md` | every **shipped** hardening item, with its decision record and verification evidence |
| `docs/ux-review.md` | the open Tier 3 UX findings |
| `docs/ux-review-archive.md` | the **completed** July 2026 UX items and their validation evidence |
| `docs/current-state.md` | current behavior and contracts — **the only authority**; if it conflicts with code, trust the code |
| `docs/endpoint-map.md` | all 72 endpoints traced DB↔view, request/response contracts, error catalog |
| `docs/handoff.md` | the live session hand-off — where work stands, and the menu of open items (the next one is **not** pre-selected) |
| `docs/project-summary.md` | what the app is, and the documentation map |
