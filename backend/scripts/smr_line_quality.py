"""SMR labor-line quality fixes (review 2026-11-09, user rulings that day).

  report     person-days over 12 h, readings off their tie (read only)
  overhead   at most 0.5 h each of assessment / audit / staging per order;
             the extra splits off as an excluded line, ground "overhead counted once"
  days       a line whose note gives hours per day ("8.5 h on 06/23 + 8.5 h on 06/24")
             becomes one line per day
  crew       nameless 1-person lines over 12 h whose paper gives a crew's hours:
             reason crew_size_not_given (the block prints "<vendor> crew")
  cleanup    the 0.5 h per-order clean-up lines: kind clean-up, reason cleanup_spread,
             vendor Green Choice in Weeks 1-2, BT Restoration from Week 3
  allocate   <csv>: SMR27 post-audit allocation lines (import_allocations.csv), one charged
             line per row, basis "week placement (post-audit allocation)"; reruns skip known keys
  changes    <csv>: the post-audit line changes (import_line_changes.csv): un-exclude,
             set vendor, move week (shrink the line, twin in the new week)
  selfcheck  asserts on the overhead rule, no database writes

Each fix is a dry run unless --apply is given. Writes carry history rows with
the run tag, all in one transaction (smr_charge_undated_likely.py pattern);
`--undo "<tag>"` restores every field the run changed and removes the lines it created.

Run from backend/:  venv\\Scripts\\python.exe scripts\\smr_line_quality.py <fix> [--apply]
"""
import os, re, sys, uuid
sys.path.insert(0, ".")
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal
from types import SimpleNamespace as NS

from app.domain.work_orders_smr_lines import (
    GROUND_OVERHEAD_ONCE, GROUND_REMOVED, check_tie, kinds_of, validate_line_state, week_of,
)

DAY_LIMIT = Decimal(12)  # user 2026-11-09: more than this on one date for one person is "impossible"
HALF = Decimal("0.5")
DEFAULT_VENDOR = {"assessment": "Belfor", "audit": "XXL Construction", "staging": "XXL Construction"}
# sha256 prefixes of the frozen post-audit files (levelling rebuild 2026-11-10); a rebuild changes these.
FROZEN = {"import_allocations.csv": "cc0d80dba55cbf74", "import_line_changes.csv": "e6a9ec75ac325ac5"}
FIELDS = ("reading_id","work_date", "date_basis", "week", "vendor", "worker_id", "alias_on_paper", "headcount",
          "hours_each", "kind", "reason_code", "status", "exclusion_ground", "note")


def _printing(line):
    return line.reading.printing_no if line.reading is not None else 99


def overhead_plan(lines):
    """For one order's charged lines: [(line, keep_kinds, keep_hours)] for each overhead
    line that changes. keep_kinds empty = exclude the whole line. Dated lines win over
    week placements, then the usual vendor (assessment Belfor, audit/staging XXL), then
    the earlier printing."""
    oh = [l for l in lines if l.status == "charged" and set(kinds_of(l.kind)) & set(DEFAULT_VENDOR)]
    oh.sort(key=lambda l: (l.work_date is None, l.vendor != DEFAULT_VENDOR.get(kinds_of(l.kind)[0]),
                           _printing(l), str(l.id)))
    covered, plan = set(), []
    for l in oh:
        toks = kinds_of(l.kind)
        if l.headcount != 1 or not set(toks) <= set(DEFAULT_VENDOR):
            plan.append((l, None, None))  # not a plain overhead line: left alone, listed
            continue
        new = [t for t in toks if t not in covered]
        keep = min(Decimal(l.hours_each), HALF * len(new))
        if new != toks or keep != Decimal(l.hours_each):
            plan.append((l, new, keep))
        covered |= set(new)
    return plan


def selfcheck():
    def L(kind, h, vendor="Belfor", day=date(2026, 7, 1), printing=1, i=0):
        return NS(id=i, kind=kind, hours_each=Decimal(h), vendor=vendor, work_date=day, headcount=1,
                  status="charged", reading=NS(printing_no=printing))
    # Belfor + XXL audit on one paper: XXL keeps the audit, Belfor's goes.
    a, b, x = L("assessment", "0.5", i=1), L("audit", "0.5", i=2), L("audit", "0.5", "XXL Construction", i=3)
    assert [(p[0].id, p[1], p[2]) for p in overhead_plan([a, b, x])] == [(2, [], Decimal(0))]
    # A package on two printings: the dated one stays, the week placement goes.
    p1 = [L(k, "0.5", v, None, 1, i) for i, (k, v) in enumerate(DEFAULT_VENDOR.items(), 10)]
    p2 = [L(k, "0.5", v, date(2026, 6, 22), 2, i) for i, (k, v) in enumerate(DEFAULT_VENDOR.items(), 20)]
    assert sorted(p[0].id for p in overhead_plan(p1 + p2)) == [10, 11, 12]
    # "three assessment lines" on one 1.5 h line keeps 0.5 h; a 1 h assessment + staging line is fine.
    assert [(p[1], p[2]) for p in overhead_plan([L("assessment", "1.5")])] == [(["assessment"], HALF)]
    assert overhead_plan([L("assessment, staging", "1.0")]) == []
    # A combined line whose assessment is already covered keeps only its audit.
    assert [(p[0].id, p[1], p[2]) for p in overhead_plan([a, L("assessment, audit", "0.5", i=5)])] == [(5, ["audit"], HALF)]
    print("selfcheck ok")


def main():
    args = sys.argv[1:]
    if not args or args[0] == "selfcheck":
        return selfcheck()
    from sqlalchemy.orm import selectinload
    from app.database import SessionLocal
    from app.models import SmrLaborLine, SmrLineEdit, SmrPaperReading, User, WorkOrder
    from app.services.work_orders_smr_lines import _text, history, line_json

    db = SessionLocal()
    owner = db.query(User).filter(User.role == "owner").first()
    now = datetime.now(timezone.utc)
    apply_ = "--apply" in args
    lines = (db.query(SmrLaborLine)
             .options(selectinload(SmrLaborLine.work_order), selectinload(SmrLaborLine.reading),
                      selectinload(SmrLaborLine.worker)).all())
    live = [l for l in lines if l.exclusion_ground != GROUND_REMOVED]

    def h(rows):
        return sum((Decimal(r.headcount) * Decimal(r.hours_each) for r in rows), Decimal(0))

    def validate(state):
        validate_line_state(status=state["status"], work_date=state["work_date"], date_basis=state["date_basis"],
                            exclusion_ground=state["exclusion_ground"], headcount=state["headcount"],
                            hours_each=state["hours_each"], vendor=state["vendor"], kind=state["kind"],
                            reason_code=state["reason_code"], week=state["week"])

    def change(line, changes, tag):
        state = {f: getattr(line, f) for f in FIELDS} | changes
        validate(state)
        for field, value in changes.items():
            if getattr(line, field) != value:
                history(db, line=line, actor=owner, field=field, old=_text(getattr(line, field)), new=_text(value),
                        reason=tag, now=now)
                setattr(line, field, value)
        line.updated_at, line.updated_by_id = now, owner.id

    def create(like, changes, tag, import_key=None):
        state = {f: getattr(like, f) for f in FIELDS} | changes
        validate(state)
        row = SmrLaborLine(id=uuid.uuid4(), work_order_id=like.work_order_id, import_key=import_key, created_at=now,
                           created_by_id=owner.id, updated_at=now, updated_by_id=owner.id, **state)
        db.add(row)
        db.flush()
        history(db, line=row, actor=owner, field="created", old=None, new=line_json(row), reason=tag, now=now)
        return row

    def finish(tag, summary):
        print(summary)
        if apply_:
            db.commit()
            print(f"applied. tag: {tag}")
        else:
            db.rollback()
            print("dry run: nothing written (add --apply)")

    def tag_for(what):
        return f"{what} (user 2026-11-09) run {uuid.uuid4().hex[:12]}"

    fix = args[0]
    if fix == "--undo":
        tag = args[1]
        edits = (db.query(SmrLineEdit).filter(SmrLineEdit.reason == tag).order_by(SmrLineEdit.edited_at.desc()).all())
        by_line = {l.id: l for l in lines}
        old = defaultdict(dict)
        for e in edits:  # newest first, so the earliest old value wins
            old[e.line_id][e.field] = e.old_value
        undo = f"undo {tag}"
        parse = {"work_date": date.fromisoformat, "hours_each": Decimal, "headcount": int, "week": int,
                 "reading_id": uuid.UUID, "worker_id": uuid.UUID}
        for line_id, fields in old.items():
            line = by_line[line_id]
            if "created" in fields:
                change(line, {"status": "excluded", "exclusion_ground": GROUND_REMOVED}, undo)
                line.import_key = None  # frees an allocation key so a rerun can recreate the line
                continue
            change(line, {f: (parse.get(f, str)(v) if v is not None else None) for f, v in fields.items()}, undo)
        apply_ = True
        return finish(undo, f"undo: {len(old)} lines restored")

    if fix == "report":
        day = defaultdict(list)
        for l in live:
            if l.status == "charged" and l.worker_id and l.work_date:
                day[(l.worker.display_name, l.work_date)].append(l)
        over = sorted(((k, v) for k, v in day.items() if h(v) > DAY_LIMIT), key=lambda kv: -h(kv[1]))
        print(f"person-days over {DAY_LIMIT} h: {len(over)}")
        for (name, d), rows in over:
            parts = ", ".join(f"{r.work_order.number} p{_printing(r)} {r.hours_each}" for r in rows)
            print(f"  {name:28} {d:%m/%d}  {h(rows):>5} h  [{parts}]")
        by_reading = defaultdict(list)
        for l in live:
            if l.reading_id:
                by_reading[l.reading_id].append(l)
        print("readings off their tie:")
        for r in db.query(SmrPaperReading).options(selectinload(SmrPaperReading.work_order)).all():
            fail = check_tie({"reading_id": r.id, "wo": r.work_order.number, "printing_no": r.printing_no,
                              "work_date": r.work_date, "hours_as_read": r.hours_as_read},
                             [{f: getattr(l, f) for f in ("status", "exclusion_ground", "work_date", "headcount", "hours_each")}
                              for l in by_reading[r.id]])
            if fail:
                edited = {e.reason for l in by_reading[r.id] for e in l.edits if e.field != "created"}
                print(f"  WO {fail.wo} p{fail.printing_no}: read {fail.expected} h, lines {fail.found} h; "
                      f"edits: {sorted(edited) or 'none since import'}")
        return

    by_order = defaultdict(list)
    for l in live:
        by_order[l.work_order_id].append(l)

    if fix == "overhead":
        tag, out, skipped = tag_for("overhead counted once"), Decimal(0), []
        for order_lines in by_order.values():
            for line, kinds, keep in overhead_plan(order_lines):
                if kinds is None:
                    skipped.append(line)
                    continue
                gone = [t for t in kinds_of(line.kind) if t not in kinds]
                excess = Decimal(line.hours_each) - keep
                print(f"  {line.work_order.number} p{_printing(line)} {line.vendor:16} {line.kind:28} {line.hours_each} h "
                      f"-> {', '.join(kinds) or 'excluded'} {keep} h")
                if not kinds:
                    change(line, {"status": "excluded", "exclusion_ground": GROUND_OVERHEAD_ONCE}, tag)
                    out += excess
                    continue
                change(line, {"kind": ", ".join(kinds), "hours_each": keep}, tag)
                if excess:
                    if "on the clock" in (line.note or ""):
                        # User 2026-11-09 (23278441): clock time keyed under an overhead label is field work.
                        create(line, {"kind": "field", "hours_each": excess, "reason_code": "as_read"}, tag)
                        continue
                    create(line, {"kind": ", ".join(gone or kinds), "hours_each": excess, "status": "excluded",
                                  "exclusion_ground": GROUND_OVERHEAD_ONCE}, tag)
                    out += excess
        for line in skipped:
            print(f"  left alone (not plain overhead): {line.work_order.number} {line.kind} x{line.headcount} {line.hours_each} h")
        return finish(tag, f"overhead: {out} h moved to excluded")

    if fix == "days":
        tag, n = tag_for("split per paper day"), 0
        pat = re.compile(r"(\d+(?:\.\d)?) h on (\d\d)/(\d\d)")
        for line in live:
            parts = pat.findall(line.note or "")
            if line.status != "charged" or len({(m, d) for _, m, d in parts}) < 2:
                continue
            days = [(Decimal(x), date(2026, int(m), int(d))) for x, m, d in parts]
            if sum(x for x, _ in days) != Decimal(line.hours_each) or line.work_date not in {d for _, d in days}:
                print(f"  not split (hours or date do not match the note): {line.work_order.number} {line.note}")
                continue
            print(f"  {line.work_order.number} {line.note}")
            first, *rest = days
            change(line, {"hours_each": first[0], "work_date": first[1], "week": week_of(first[1])}, tag)
            for x, d in rest:
                create(line, {"hours_each": x, "work_date": d, "week": week_of(d)}, tag)
            n += 1
        return finish(tag, f"days: {n} lines split")

    if fix == "crew":
        tag, rows = tag_for("crew size not on paper"), []
        for line in live:
            if (line.status == "charged" and line.worker_id is None and line.headcount == 1 and line.kind == "field"
                    and Decimal(line.hours_each) > DAY_LIMIT and line.reason_code != "crew_size_not_given"
                    and f"{line.vendor} {Decimal(line.hours_each).normalize():f} h (one individual"
                    not in (line.reading.raw_note if line.reading else "")):
                print(f"  {line.work_order.number} {line.vendor:16} {line.hours_each} h  {line.note}")
                change(line, {"reason_code": "crew_size_not_given"}, tag)
                rows.append(line)
        return finish(tag, f"crew: {len(rows)} lines / {h(rows)} h")

    if fix == "reasons":
        # One reason per order for its as_read lines: overhead lines say so; field lines take the
        # note's stated cause when it gives one, else the direction of the change vs the estimate.
        # Writes a draft CSV (biggest ratio first) for the user to check before --apply.
        tag, out, n = tag_for("reason from the reading notes"), [], 0
        crew = re.compile(r"crews?( members)? (billed|added|captured|counted|charged) as (individuals|one)"
                          r"|(charged|billed) as one (individual|person)", re.I)
        for order_lines in by_order.values():
            charged = [l for l in order_lines if l.status == "charged"]
            if not charged:
                continue
            order = charged[0].work_order
            target = Decimal(order.smr_target["hours"]) if order.smr_target else None
            total = h(charged)
            # The field hours carry the finding; overhead and clean-up lines carry their own codes.
            fieldw = [l for l in charged if l.kind == "field"]
            field = h(fieldw)
            notes = " | ".join(sorted({l.reading.raw_note for l in order_lines if l.reading and l.reading.raw_note}))
            arith = re.search(r"[^.;]{0,30}arithmetic[^.;]{0,30}", notes, re.I)
            hit = None
            if target is None:
                code = "as_read"
            elif total < target:
                code, hit = ("arithmetic", arith) if arith else ("over_billed", None)
            elif field <= target:
                code = "accurate"  # the paper's field hours fit the bill; any increase is overhead / clean-up
            elif crew.search(notes):
                code, hit = "crew_as_one", crew.search(notes)
            elif arith:
                code, hit = "arithmetic", arith
            else:
                code = "hours_on_paper_above_billed"
            # User 2026-11-09: a generic increase whose billed hours are about one person's share of
            # the crew reads as "crew billed as one person". Crew size = distinct named workers plus
            # unnamed headcount; lines whose crew size the paper never gave make the size unknown.
            # ponytail: one share over the whole order, not per day; per-day test if the auditor asks.
            size_known = not any(l.reason_code == "crew_size_not_given" for l in fieldw)
            size = len({l.worker_id for l in fieldw if l.worker_id}) + sum(l.headcount for l in fieldw if not l.worker_id)
            if code == "hours_on_paper_above_billed" and size_known and size >= 2 and target <= field / size + HALF:
                code, evidence = "crew_as_one", f"billed {target} h <= {field} h / crew of {size} + 0.5"
            else:
                evidence = hit.group(0).strip() if hit else ""
            todo = [l for l in charged if l.reason_code == "as_read"]
            for l in todo:
                change(l, {"reason_code": code if l.kind in ("field", "clean-up") else "overhead_added"}, tag)
            n += len(todo)
            out.append({"wo": order.number, "billed_h": target, "charged_h": total, "field_h": field,
                        "ratio": round(total / target, 2) if target else "", "field_reason": code,
                        "lines_set": len(todo), "evidence": evidence, "notes": notes[:600]})
        out.sort(key=lambda r: -(r["ratio"] or 0))
        import csv
        path = os.environ.get("REASON_CSV", r"C:\Users\mcclu\Desktop\SMR27 Reconciliation\reason_draft.csv")
        try:
            with open(path, "w", newline="", encoding="utf-8-sig") as f:
                w = csv.DictWriter(f, fieldnames=list(out[0]))
                w.writeheader()
                w.writerows(out)
        except PermissionError:
            print("draft CSV is open in Excel: not rewritten")
        counts = defaultdict(int)
        for r in out:
            counts[r["field_reason"]] += 1
        print("orders by field reason:", dict(counts), f"\ndraft: {path}")
        return finish(tag, f"reasons: {n} lines on {len(out)} orders")

    if fix == "spill":
        # User 2026-11-09: a named person's hours past 12 on one date spill into the next day,
        # and on again if that day fills. The last lines of the day move (higher order number,
        # later printing); a line straddling the limit splits. The note records the move.
        from datetime import timedelta
        tag, moved = tag_for("spilled past the 12 h day"), []
        days = defaultdict(list)
        for l in live:
            if l.status == "charged" and l.worker_id and l.work_date:
                days[(l.worker_id, l.work_date)].append(l)
        for worker_id in sorted({k[0] for k in days if h(days[k]) > DAY_LIMIT}, key=str):
            d = min(k[1] for k in days if k[0] == worker_id and h(days[k]) > DAY_LIMIT)
            while True:  # each day settles before the next, so spilled-in hours are counted where they land
                while h(days[(worker_id, d)]) > DAY_LIMIT:
                    excess = h(days[(worker_id, d)]) - DAY_LIMIT
                    nxt = d + timedelta(days=1)
                    line = max(days[(worker_id, d)], key=lambda l: (l.work_order.number, _printing(l), str(l.id)))
                    take = min(excess, Decimal(line.hours_each))
                    note = f"{line.note or ''} | {take} h spilled from {d:%m/%d} (12 h day)".lstrip(" |")
                    print(f"  {line.worker.display_name:26} {line.work_order.number} {d:%m/%d} -> {nxt:%m/%d} {take} h"
                          + ("  WEEK CHANGES" if week_of(nxt) != week_of(d) else ""))
                    days[(worker_id, d)].remove(line)
                    if take == Decimal(line.hours_each):
                        change(line, {"work_date": nxt, "week": week_of(nxt), "note": note}, tag)
                        days[(worker_id, nxt)].append(line)
                    else:
                        change(line, {"hours_each": Decimal(line.hours_each) - take}, tag)
                        days[(worker_id, d)].append(line)
                        days[(worker_id, nxt)].append(
                            create(line, {"hours_each": take, "work_date": nxt, "week": week_of(nxt), "note": note}, tag))
                    moved.append((d, nxt, take))
                later = [k[1] for k in days if k[0] == worker_id and k[1] > d and h(days[k]) > DAY_LIMIT]
                if not later:
                    break
                d = min(later)
        return finish(tag, f"spill: {len(moved)} moves, {sum(t for *_, t in moved)} h; "
                           f"week changes on {sum(week_of(a) != week_of(b) for a, b, _ in moved)}")

    if fix in ("allocate", "changes"):
        import csv, hashlib
        path = args[1]
        name, digest = os.path.basename(path), hashlib.sha256(open(path, "rb").read()).hexdigest()[:16]
        if FROZEN.get(name) != digest:
            sys.exit(f"{name}: sha256 {digest}, expected {FROZEN.get(name)} (frozen file changed?); nothing written")
        rows = list(csv.DictReader(open(path, newline="", encoding="utf-8-sig")))

    if fix == "allocate":
        from app.domain.work_orders_smr_lines import ALLOCATION_BASIS
        from app.services import work_orders as wos
        tag = tag_for(f"post-audit allocation {FROZEN[name]}")
        orders = {n: wos.find_by_number(db, n) for n in sorted({r["wo"] for r in rows})}
        bad = [n for n, o in orders.items() if o is None or o.smr_imported_at is None]
        if bad:
            sys.exit(f"not SMR orders in the app: {', '.join(bad)}; nothing written")
        known = {k for (k,) in db.query(SmrLaborLine.import_key).filter(SmrLaborLine.import_key.like("alloc %"))}
        made, skipped = [], 0
        for r in rows:
            key = f"alloc {r['wo']} W{r['week']} {r['vendor']} {r['source']}"
            if key in known:
                skipped += 1
                continue
            state = dict.fromkeys(FIELDS) | {
                "date_basis": ALLOCATION_BASIS, "week": int(r["week"]), "vendor": r["vendor"], "headcount": 1,
                "hours_each": Decimal(r["hours"]), "kind": r["kind"], "reason_code": r["reason_code"],
                "status": "charged", "note": f"{r['source']} ({r['evidence_class']}): {r['note']}"}
            made.append(create(NS(work_order_id=orders[r["wo"]].id, **state), {}, tag, import_key=key))
        return finish(tag, f"allocate: {len(made)} lines / {h(made)} h on {len({l.work_order_id for l in made})} orders; "
                           f"{skipped} already in")

    if fix == "changes":
        from app.domain.work_orders_smr_lines import WEEK_BASES
        tag, by_id, done = tag_for(f"post-audit line changes {FROZEN[name]}"), {str(l.id): l for l in live}, defaultdict(Decimal)
        for r in rows:
            line, what, x = by_id.get(r["line_id"]), r["change"], Decimal(r["hours"])
            if line is None or line.work_order.number != r["wo"]:
                sys.exit(f"line {r['line_id']} (WO {r['wo']}) not found; nothing written")
            if what == "un-exclude":
                assert line.exclusion_ground == "awaiting invoice (GC, Week 7)" and h([line]) == x, r
                change(line, {"status": "charged", "exclusion_ground": None}, tag)
            elif what == "set vendor":
                assert line.vendor == "Unknown" and line.status == "charged" and h([line]) == x, r
                change(line, {"vendor": r["vendor"]}, tag)
            elif what == "move week":
                assert (line.headcount == 1 and line.work_date is None and line.date_basis in WEEK_BASES
                        and line.week == int(r["week"]) and line.worker and line.worker.display_name == r["worker"]
                        and x <= Decimal(line.hours_each)), r
                note = f"{line.note or ''} | {x} h moved Week {r['week']} -> {r['to_week']}: {r['why']}".lstrip(" |")
                if x == Decimal(line.hours_each):
                    change(line, {"week": int(r["to_week"]), "note": note}, tag)
                else:
                    change(line, {"hours_each": Decimal(line.hours_each) - x}, tag)
                    create(line, {"hours_each": x, "week": int(r["to_week"]), "note": note}, tag)
            else:
                sys.exit(f"unknown change {what!r}; nothing written")
            done[what] += x
        return finish(tag, "changes: " + ", ".join(f"{k} {v} h" for k, v in done.items()))

    if fix == "cleanup":
        tag, rows = tag_for("clean-up labelled"), []
        for line in live:
            if line.vendor == "Unknown" and (line.note or "").startswith("clean-up 0.5 h per order"):
                vendor = "Green Choice" if (line.week or 0) <= 2 else "BT Restoration"
                change(line, {"kind": "clean-up", "reason_code": "cleanup_spread", "vendor": vendor}, tag)
                rows.append(line)
        weeks = defaultdict(Decimal)
        for r in rows:
            weeks[(r.week, r.vendor)] += Decimal(r.hours_each)
        for (w, v), x in sorted(weeks.items(), key=lambda kv: (kv[0][0] or 0, kv[0][1])):
            print(f"  week {w} {v:16} {x} h")
        return finish(tag, f"cleanup: {len(rows)} lines / {h(rows)} h")

    sys.exit(f"unknown fix: {fix}")


if __name__ == "__main__":
    main()
