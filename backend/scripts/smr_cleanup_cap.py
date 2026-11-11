"""SMR27: cap clean-up hours per order and re-place what comes off (user 2026-11-11).

Input: a per-order CSV (wo, cleanup_keep_h, prep_add_h, scope_h, eligible) built by the reconciliation
(Desktop/SMR27 Reconciliation, "clean-up cap plan <date>.csv"). For each order:
  1. clean-up lines are cut down to cleanup_keep_h (Green Choice lines first, the weekly-report line last);
  2. an order kept above what it has (large BG job) takes clean-up hours from the cut hours;
  3. prep_add_h is taken as material preparation, from the order's own cut hours first;
  4. what is left goes as field work to eligible orders worked that week, lowest hours-to-scope first,
     never past scope_h;
  5. the rest is unplaced: it leaves the charge (ground "removed", note "unplaced: clean-up cap").
Hours never leave their week, vendor or person, so no invoice or personal cap can be exceeded
(checked before the commit).

`limit <limits.csv>` (wo, limit_h): an order above its limit loses placed field hours (post-audit allocation
lines with no paper reading) down to it, weakest evidence first; they are unplaced the same way (note
"unplaced: small-task limit").

`add <adds.csv>` (wo, kind, reason_code, hours, vendor, weeks, note): puts hours back on an order from the
unplaced pool of that vendor in the weeks listed (space-separated, first choice first).

`respread <targets.csv>` (wo, week, vendor, target_h): the crew-sheet-location hours each order should carry from
that vendor in that week. Orders above their target give, orders below take; the total of each week and vendor
must already equal what is charged, so nothing is unplaced.

Dry run unless --apply. Writes history rows with the run tag in one transaction; undo with
  venv\\Scripts\\python.exe scripts\\smr_line_quality.py --undo "<tag>"

Run from backend/:  venv\\Scripts\\python.exe scripts\\smr_cleanup_cap.py [limit|add|respread] <csv> [unplaced.csv] [--apply]
`--label=<name>` names the run in its tag (add: "rule adds", "ceiling raise" for the 2026-11-11 ceiling_adds.py CSVs).
"""
import csv, sys, uuid
sys.path.insert(0, ".")
from collections import defaultdict
from datetime import datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from types import SimpleNamespace as NS

BT, CLEAN, PREP, FIELD = "BT Restoration", "clean-up", "material preparation", "field"
FIELDS = ("reading_id", "work_date", "date_basis", "week", "vendor", "worker_id", "alias_on_paper", "headcount",
          "hours_each", "kind", "reason_code", "status", "exclusion_ground", "note")
REASON = {CLEAN: "invoice_backed", PREP: "estimated_rule", FIELD: "invoice_backed"}
NOTE = {
    CLEAN: "clean-up (Invoice-backed): general labor, invoiced, on no paper; large BG job or BT on the paper "
           "(clean-up cap, user 2026-11-11)",
    PREP: "material prep (Estimated (rule)): general labor, invoiced, on no paper; countertop 3 h, drywall or plywood "
          "sheet 1 h, OSB half sheet 0.5 h, flooring 1 h per 20 sq ft, trim piece 0.25 h, cove base 0.5 h, "
          "paint masking 1 h (clean-up cap, user 2026-11-11)",
    FIELD: "general labor (Invoice-backed): invoiced, on no paper; re-placed from clean-up as field work inside "
           "the order's scope (clean-up cap, user 2026-11-11)",
}


WEAKEST_FIRST = ("estimated_add", "invoice_backed", "crew_sheet_location", "same_crew_week")


def limit_plan(lines, limits):
    """limits: {wo: hours the order may carry}. Placed field hours (no paper reading) above the limit come off,
    weakest evidence first: estimated, invoice-backed, crew-sheet location, same crew and week."""
    by_wo, moves = defaultdict(list), []
    for l in lines:
        by_wo[l.wo].append(l)
    rank = lambda l: (WEAKEST_FIRST.index(l.reason) if l.reason in WEAKEST_FIRST else len(WEAKEST_FIRST), -l.hours, str(l.id))
    for wo, limit in sorted(limits.items()):
        over = sum((l.hours for l in by_wo[wo]), Decimal(0)) - limit
        for l in sorted((l for l in by_wo[wo] if l.kind == FIELD and not l.paper), key=rank):
            if over <= 0:
                break
            moves.append((l, min(l.hours, over), None, None))
            over -= moves[-1][1]
    return moves


UNPLACED = "| unplaced:"


def pick(cands, need):
    """Take `need` hours from candidates (each with .hours) in order: ([(candidate, hours)], hours still missing)."""
    out = []
    for c in cands:
        if need <= 0:
            break
        out.append((c, min(c.hours, need)))
        need -= out[-1][1]
    return out, need


def respread_plan(have, target):
    """have: {(wo, week, vendor): [(line id, hours)]}, target: {(wo, week, vendor): hours}. Returns [(line id, hours,
    wo taking them)]: an order above its target gives its largest lines first and the order furthest below takes
    first, inside the same week and vendor, so few lines move."""
    moves = []
    for cell in sorted({k[1:] for k in target}):
        keys = sorted(k for k in set(have) | set(target) if k[1:] == cell)
        held = {k: sum((h for _i, h in have.get(k, [])), Decimal(0)) for k in keys}
        assert sum(held.values()) == sum(target.get(k, Decimal(0)) for k in keys), f"targets do not total what is charged in {cell}"
        give = []
        for k in keys:
            over = held[k] - target.get(k, Decimal(0))
            for i, h in sorted(have.get(k, []), key=lambda x: (-x[1], str(x[0]))):
                if over <= 0:
                    break
                give.append([i, min(h, over)])
                over -= give[-1][1]
        give.sort(key=lambda g: (-g[1], str(g[0])))
        for need, k in sorted(((target.get(k, Decimal(0)) - held[k], k) for k in keys), reverse=True):
            for g in give:
                if need <= 0:
                    break
                x = min(g[1], need)
                if x > 0:
                    g[1] -= x
                    need -= x
                    moves.append((g[0], x, k[0]))
    return moves


def floor_half(x):
    return (Decimal(x) * 2).to_integral_value(rounding=ROUND_FLOOR) / 2


def plan(lines, orders):
    """lines: charged lines (id, wo, week, vendor, kind, reason, hours); orders: {wo: NS(keep, prep, scope, eligible)}.
    Returns ([(line, hours, destination wo or None, kind or None)], {(wo, kind): hours no cut hour could fund},
    room still open inside scope on eligible orders)."""
    by_wo, total, weeks = defaultdict(list), defaultdict(Decimal), defaultdict(set)
    for l in lines:
        by_wo[l.wo].append(l)
        total[l.wo] += l.hours
        weeks[l.wo].add(l.week)
    pool, own, clean = defaultdict(list), defaultdict(list), defaultdict(Decimal)
    for wo in sorted(by_wo):
        cu = [l for l in by_wo[wo] if l.kind == CLEAN]
        clean[wo] = sum((l.hours for l in cu), Decimal(0))
        over = clean[wo] - orders[wo].keep if wo in orders else Decimal(0)
        for l in sorted(cu, key=lambda l: (l.vendor == BT, l.reason == "cleanup_spread", -l.hours, str(l.id))):
            if over <= 0:
                break
            piece = [l, min(l.hours, over)]
            over -= piece[1]
            total[wo] -= piece[1]
            pool[(l.week, l.vendor)].append(piece)
            own[wo].append(piece)
    moves, unmet = [], {}

    def take(pieces, need, wo, kind):
        for p in pieces:
            x = min(p[1], need)
            if x > 0:
                p[1] -= x
                need -= x
                total[wo] += x
                moves.append((p[0], x, wo, kind))
        return need

    def fund(wo, need, kind, first=()):
        need = take(first, need, wo, kind)
        for w in sorted(weeks[wo], key=lambda w: -sum(p[1] for p in pool[(w, BT)])):  # fullest week the order was worked in
            need = take(pool[(w, BT)], need, wo, kind)
        if need:
            unmet[(wo, kind)] = need

    for wo in sorted(orders):
        if wo in by_wo and orders[wo].keep > clean[wo]:
            fund(wo, orders[wo].keep - clean[wo], CLEAN)
    for wo in sorted(orders):
        if wo in by_wo and orders[wo].prep > 0:
            fund(wo, orders[wo].prep, PREP, [p for p in own[wo] if p[0].vendor == BT])
    cands = [wo for wo in by_wo if wo in orders and orders[wo].eligible and orders[wo].scope]
    for wo in sorted(cands, key=lambda wo: (total[wo] / orders[wo].scope, wo)):
        room = floor_half(orders[wo].scope - total[wo])
        for key in sorted((k for k in pool if k[0] in weeks[wo]), key=lambda k: (-sum(p[1] for p in pool[k]), k)):
            if room <= 0:
                break
            room = take(pool[key], room, wo, FIELD)  # fullest week first, so tight weeks keep hours for their own orders
    for pieces in pool.values():
        moves += [(p[0], p[1], None, None) for p in pieces if p[1] > 0]
    room = sum((max(floor_half(orders[wo].scope - total[wo]), Decimal(0)) for wo in cands), Decimal(0))
    return moves, unmet, room


def selfcheck():
    D = Decimal
    L = lambda i, wo, kind, h, week=3, vendor=BT, reason="invoice_backed": NS(id=i, wo=wo, week=week, vendor=vendor,
                                                                              kind=kind, reason=reason, hours=D(h),
                                                                              paper=False)
    O = lambda keep, prep=0, scope=None, eligible=True: NS(keep=D(keep), prep=D(prep), scope=scope and D(scope), eligible=eligible)
    lines = [L(1, "A", CLEAN, 3), L(2, "A", CLEAN, "0.5", reason="cleanup_spread"), L(3, "A", FIELD, 4),
             L(4, "B", CLEAN, 2), L(5, "B", FIELD, 5), L(6, "C", CLEAN, "0.5"), L(7, "C", FIELD, 3),
             L(8, "D", CLEAN, 2, week=4), L(9, "D", FIELD, 1, week=4), L(10, "E", CLEAN, "0.5", week=1, vendor="Green Choice")]
    orders = {"A": O(1, scope=6), "B": O(0, prep=1, scope=6), "C": O(4, scope=3), "D": O(0, eligible=False), "E": O(0, scope=9)}
    moves, unmet, _room = plan(lines, orders)
    got = defaultdict(D)
    for line, x, wo, kind in moves:
        got[(line.id, wo, kind)] += x
    # A keeps its weekly-report 0.5 h + 0.5 h; C (large BG) is raised 3.5 h first; B's prep comes from B's own line;
    # A then has room for 0 h of the pool (it is empty); D's Week 4 hours have no eligible order: unplaced;
    # E's Green Choice 0.5 h goes back on E as field (room under scope).
    assert got == {(1, "C", CLEAN): D("2.5"), (4, "C", CLEAN): D(1), (4, "B", PREP): D(1), (8, None, None): D(2),
                   (10, "E", FIELD): D("0.5")}, dict(got)
    assert not unmet and floor_half("1.75") == D("1.5")
    lines2 = [L(1, "A", CLEAN, 6), L(2, "A", FIELD, 1), L(3, "B", FIELD, 2)]
    moves, unmet, room = plan(lines2, {"A": O(0, scope=3), "B": O(0, prep=9, scope=20)})
    # B wants 9 h of prep, 6 h exist; nothing is left for field.
    assert sum(x for _line, x, _wo, kind in moves if kind == PREP) == 6 and unmet == {("B", PREP): D(3)} and room == 2 + 12
    # limit: 8.5 h on the order, 6 h allowed: the estimate goes first, then part of the crew-sheet hours; paper stays.
    lines3 = [L(1, "A", FIELD, 2), L(2, "A", FIELD, 1, reason="estimated_add"), L(3, "A", FIELD, 3, reason="crew_sheet_location"),
              L(4, "A", FIELD, 2, reason="same_crew_week"), L(5, "A", CLEAN, "0.5")]
    lines3[0].paper = True
    assert [(l.id, x) for l, x, *_ in limit_plan(lines3, {"A": D(6)})] == [(2, D(1)), (3, D("1.5"))]
    assert limit_plan(lines3, {"A": D(9)}) == []
    # add: 5 h wanted from lines of 3 h and 4 h: all of the first, 2 h of the second; 9 h wanted leaves 2 h short.
    a, b = NS(hours=D(3)), NS(hours=D(4))
    assert pick([a, b], D(5)) == ([(a, D(3)), (b, D(2))], D(0)) and pick([a, b], D(9))[1] == D(2)
    # respread: A holds 10 h (lines of 7 and 3) against a target of 2; B takes 6 and C 2. The 7 h line gives first,
    # to the order furthest below; the other week is left alone.
    k = lambda wo, week=3: (wo, week, "Green Choice")
    have = {k("A"): [(1, D(7)), (2, D(3))], k("B"): [(3, D(1))], k("A", 4): [(4, D(5))]}
    got = respread_plan(have, {k("A"): D(2), k("B"): D(7), k("C"): D(2), k("A", 4): D(5)})
    assert got == [(1, D(6), "B"), (1, D(1), "C"), (2, D(1), "C")], got
    print("selfcheck ok")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args or args[0] == "selfcheck":
        return selfcheck()
    from sqlalchemy.orm import selectinload
    from app.database import SessionLocal, engine
    from app.models import User, WorkOrder
    from app.models_smr import SmrLaborLine, SmrLineEdit
    from app.domain.work_orders_smr_lines import ALLOCATION_BASIS, GROUND_REMOVED, validate_line_state
    from app.services.work_orders_smr_lines import _text, history, line_json

    print(f"database: {engine.url.host}:{engine.url.port}/{engine.url.database}")
    if "--apply" in flags and engine.url.host not in ("localhost", "127.0.0.1") and "--not-local" not in flags:
        sys.exit("not a local database; add --not-local to write there. nothing written")
    what = {"limit": "small-task limit", "add": "workload add", "respread": "wider spread"}.get(args[0], "clean-up cap")
    args = args[1:] if args[0] in ("limit", "add", "respread") else args
    table = list(csv.DictReader(open(args[0], newline="", encoding="utf-8-sig")))
    db = SessionLocal()
    owner = db.query(User).filter(User.role == "owner").first()
    now = datetime.now(timezone.utc)
    label = next((f[8:] for f in flags if f.startswith("--label=")), what)  # names the run in the tag; the mode is still `what`
    tag = f"{label} (user 2026-11-11) run {uuid.uuid4().hex[:12]}"

    def validate(state):
        validate_line_state(**{k: state[k] for k in ("status", "work_date", "date_basis", "exclusion_ground", "headcount",
                                                     "hours_each", "vendor", "kind", "reason_code", "week")})

    def change(line, changes):
        validate({f: getattr(line, f) for f in FIELDS} | changes)
        for field, value in changes.items():
            if getattr(line, field) != value:
                history(db, line=line, actor=owner, field=field, old=_text(getattr(line, field)), new=_text(value),
                        reason=tag, now=now)
                setattr(line, field, value)
        line.updated_at, line.updated_by_id = now, owner.id

    def create(like, work_order_id, changes):
        state = {f: getattr(like, f) for f in FIELDS} | changes
        validate(state)
        row = SmrLaborLine(id=uuid.uuid4(), work_order_id=work_order_id, import_key=None, created_at=now,
                           created_by_id=owner.id, updated_at=now, updated_by_id=owner.id, **state)
        db.add(row)
        db.flush()
        history(db, line=row, actor=owner, field="created", old=None, new=line_json(row), reason=tag, now=now)

    def week_totals():
        out = defaultdict(Decimal)
        for l in db.query(SmrLaborLine).filter(SmrLaborLine.status == "charged"):
            out[(l.week, l.vendor, l.worker_id)] += l.headcount * Decimal(l.hours_each)
        return out

    if what == "workload add":
        # Each row takes its hours from the unplaced pool (removed lines noted "unplaced: ...") of that vendor in the
        # weeks given, in that order, so the hours keep their week, vendor and person.
        # Only lines unplaced by a run that still stands: an undone run leaves its removed twins behind, note and all.
        reasons = {r for (r,) in db.query(SmrLineEdit.reason).filter(SmrLineEdit.reason.like("%(user 2026-11-11) run %")).distinct()}
        live = {r for r in reasons if not r.startswith("undo ") and f"undo {r}" not in reasons}
        ids = {i for (i,) in db.query(SmrLineEdit.line_id).filter(SmrLineEdit.reason.in_(live)).distinct()}
        pool = [l for l in db.query(SmrLaborLine).filter(SmrLaborLine.exclusion_ground == GROUND_REMOVED,
                                                         SmrLaborLine.note.like(f"%{UNPLACED}%(user 2026-11-11)"))
                if l.id in ids]
        print(f"unplaced pool: {sum(Decimal(l.hours_each) for l in pool)} h on {len(pool)} lines, from {len(live)} standing runs")
        target = {o.number: o.id for o in db.query(WorkOrder).filter(WorkOrder.number.in_({r["wo"] for r in table}))}
        before, took = week_totals(), defaultdict(Decimal)
        for r in table:
            weeks = [int(w) for w in r["weeks"].split()]
            cands = sorted((l for l in pool if l.vendor == r["vendor"] and l.week in weeks and UNPLACED in (l.note or "")),
                           key=lambda l: (weeks.index(l.week), -Decimal(l.hours_each), str(l.id)))
            picked, short = pick([NS(line=l, hours=Decimal(l.hours_each)) for l in cands], Decimal(r["hours"]))
            print(f"{r['wo']} {r['kind']:20} {r['vendor']:16} {Decimal(r['hours']) - short} of {r['hours']} h, weeks {weeks}")
            if short:
                db.rollback()
                sys.exit("not enough unplaced hours for that row; nothing written")
            for p, x in picked:
                l = p.line
                named = f" | named from {l.vendor} crew (user 2026-11-11)" if " | named from" in (l.note or "") else ""
                create(l, target[r["wo"]], {"status": "charged", "exclusion_ground": None, "hours_each": x, "kind": r["kind"],
                                            "reason_code": r["reason_code"], "reading_id": None,
                                            "date_basis": ALLOCATION_BASIS, "note": r["note"] + named})
                took[(l.week, l.vendor, l.worker_id)] += x
                if x == Decimal(l.hours_each):
                    change(l, {"note": l.note.replace(UNPLACED, "| re-placed:")})
                else:
                    change(l, {"hours_each": Decimal(l.hours_each) - x})
        db.flush()
        after = week_totals()
        if any(before[k] + took[k] != after[k] for k in set(before) | set(after)):
            db.rollback()
            sys.exit("hours changed outside the cells they were taken from; rolled back, nothing written")
        if "--apply" not in flags:
            db.rollback()
            return print("dry run: nothing written (add --apply)")
        db.commit()
        return print(f"applied. tag: {tag}")
    if what == "wider spread":
        target = {(r["wo"], int(r["week"]), r["vendor"]): Decimal(r["target_h"]) for r in table}
        cells = {k[1:] for k in target}
        src = [l for l in db.query(SmrLaborLine).options(selectinload(SmrLaborLine.work_order))
               .filter(SmrLaborLine.status == "charged", SmrLaborLine.reason_code == "crew_sheet_location")
               if (l.week, l.vendor) in cells]
        assert all(l.headcount == 1 for l in src), "a crew line (headcount above 1): not handled"
        by_id, have = {l.id: l for l in src}, defaultdict(list)
        for l in src:
            have[(l.work_order.number, l.week, l.vendor)].append((l.id, Decimal(l.hours_each)))
        stray = sorted(k[0] for k in have if k not in target)
        if stray:
            sys.exit(f"orders with these hours missing from the targets: {', '.join(stray)}; nothing written")
        order_id = {o.number: o.id for o in db.query(WorkOrder).filter(WorkOrder.number.in_({k[0] for k in target}))}
        moves = respread_plan(have, target)
        gave, took, parts = defaultdict(Decimal), defaultdict(Decimal), defaultdict(list)
        for line_id, x, wo in moves:
            gave[by_id[line_id].work_order.number] += x
            took[wo] += x
            parts[line_id].append((x, wo))
        print(f"{sum(gave.values())} h move off {len(gave)} orders onto {len(took)} orders, {len(moves)} new lines; "
              f"largest gift {max(took.values(), default=0)} h, largest cut {max(gave.values(), default=0)} h")
        before = week_totals()
        for line_id, ps in parts.items():
            l = l0 = by_id[line_id]
            cut = (l.note or "").find(" | named from")
            base, named = ((l.note or "")[:cut], (l.note or "")[cut:]) if cut >= 0 else (l.note or "", "")
            for x, wo in ps:
                create(l0, order_id[wo], {"hours_each": x, "reading_id": None, "date_basis": ALLOCATION_BASIS,
                                          "note": f"{base} | spread over every open order in the communities the crew sheets name (user 2026-11-11){named}"})
            kept = Decimal(l.hours_each) - sum((x for x, _wo in ps), Decimal(0))
            change(l, {"hours_each": kept} if kept > 0 else
                   {"status": "excluded", "exclusion_ground": GROUND_REMOVED, "note": f"{l.note or ''} | re-placed: {what} (user 2026-11-11)"})
        db.flush()
        after = week_totals()
        if any(before[k] != after[k] for k in set(before) | set(after)):
            db.rollback()
            sys.exit("hours moved between weeks, vendors or people; rolled back, nothing written")
        if "--apply" not in flags:
            db.rollback()
            return print("dry run: nothing written (add --apply)")
        db.commit()
        return print(f"applied. tag: {tag}")
    rows = (db.query(SmrLaborLine).options(selectinload(SmrLaborLine.work_order), selectinload(SmrLaborLine.worker))
            .filter(SmrLaborLine.status == "charged").all())
    if what == "clean-up cap":
        rows = [l for l in rows if (l.week or 0) in range(1, 8)]
    by_id = {l.id: l for l in rows}
    order_id = {l.work_order.number: l.work_order_id for l in rows}
    lines = [NS(id=l.id, wo=l.work_order.number, week=l.week, vendor=l.vendor, kind=l.kind, reason=l.reason_code,
                hours=l.headcount * Decimal(l.hours_each),
                paper=l.reading_id is not None or l.date_basis != ALLOCATION_BASIS)  # placed = a post-audit allocation
             for l in rows]
    if what == "clean-up cap":
        orders = {r["wo"]: NS(keep=Decimal(r["cleanup_keep_h"]), prep=Decimal(r["prep_add_h"] or 0),
                              scope=Decimal(r["scope_h"]) if r["scope_h"] else None, eligible=r["eligible"] == "1") for r in table}
        stray = sorted({l.wo for l in lines if l.kind == CLEAN and l.wo not in orders})
        if stray:
            sys.exit(f"orders with clean-up lines missing from the plan: {', '.join(stray)}; nothing written")
        moves, unmet, room = plan(lines, orders)
    else:
        moves, unmet, room = limit_plan(lines, {r["wo"]: Decimal(r["limit_h"]) for r in table}), {}, None
    assert all(by_id[l.id].headcount == 1 for l, *_ in moves), "a crew line (headcount above 1): not handled"

    stat = defaultdict(lambda: defaultdict(Decimal))
    for line, x, wo, kind in moves:
        stat[(line.week, line.vendor)][kind or "unplaced"] += x
    cols = (CLEAN, PREP, FIELD, "unplaced")
    print(f"{'week vendor':24}" + "".join(f"{c[:14]:>16}" for c in cols))
    for key in sorted(stat):
        print(f"{key[0]} {key[1]:22}" + "".join(f"{stat[key][c]:>16}" for c in cols))
    print(f"{'total':24}" + "".join(f"{sum(s[c] for s in stat.values()):>16}" for c in cols))
    if room is not None:
        print(f"room still open inside scope on eligible orders (no cut hours in their weeks): {room} h")
    print(f"lines touched: {len({l.id for l, *_ in moves})}; orders losing hours: {len({l.wo for l, _x, wo, _k in moves if wo is None})}")
    for (wo, kind), x in sorted(unmet.items()):
        print(f"  not funded (no cut hours in the order's weeks): {wo} {kind} {x} h")
    if len(args) > 1:
        with open(args[1], "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["from_wo", "week", "vendor", "person", "hours"])
            for line, x, wo, kind in moves:
                if wo is None:
                    src = by_id[line.id]
                    w.writerow([line.wo, line.week, line.vendor, src.worker.display_name if src.worker else "", x])
        print(f"unplaced hours listed in {args[1]}")
    if "--apply" not in flags:
        db.rollback()
        return print("dry run: nothing written (add --apply)")

    before = week_totals()
    parts = defaultdict(list)
    for line, x, wo, kind in moves:
        parts[line.id].append((x, wo, kind))
    for line_id, ps in parts.items():
        src = by_id[line_id]
        named = (src.note or "")[(src.note or "").find(" | named from"):] if " | named from" in (src.note or "") else ""
        unplaced = sum((x for x, wo, _ in ps if wo is None), Decimal(0))
        kept = Decimal(src.hours_each) - sum((x for x, *_ in ps), Decimal(0))
        for x, wo, kind in ps:
            if wo is not None:
                create(src, order_id[wo], {"hours_each": x, "kind": kind, "reason_code": REASON[kind], "reading_id": None,
                                           "date_basis": ALLOCATION_BASIS, "note": NOTE[kind] + named})
        gone = {"status": "excluded", "exclusion_ground": GROUND_REMOVED,
                "note": f"{src.note or ''} | {'unplaced' if unplaced else 're-placed'}: {what} (user 2026-11-11)"}
        if kept > 0:
            if unplaced:
                create(src, src.work_order_id, {"hours_each": unplaced} | gone)
            change(src, {"hours_each": kept})
        else:
            change(src, ({"hours_each": unplaced} if unplaced else {}) | gone)
    db.flush()
    after, lost = week_totals(), defaultdict(Decimal)
    for line, x, wo, _ in moves:
        if wo is None:
            lost[(line.week, line.vendor, by_id[line.id].worker_id)] += x
    bad = [k for k in set(before) | set(after) if before[k] - lost[k] != after[k]]
    if bad:
        db.rollback()
        sys.exit(f"hours moved between weeks, vendors or people in {len(bad)} cells; rolled back, nothing written")
    db.commit()
    print(f"applied. tag: {tag}")


if __name__ == "__main__":
    main()
