"""SMR27: put names on un-named XXL / Green Choice / BT charged lines (user 2026-11-11).

Each un-named charged line (worker_id empty, any headcount) is poured onto people on that vendor's
weekly roster, in 0.5 h steps, never past a person's room:
  room = weekly cap - hours already named on charged lines that week
  cap  = invoice hours per person (Green Choice, XXL: smr_vendor_invoices) or crew-sheet hours
         per person (BT: its invoices bill by class, so TimeSheets/crew_sheets.csv gives the names)
  dated lines also keep each person at or under 12 h that day
People already on the order come first; a crew line of N people x H h picks N different people
while any have room. Hours nobody has room for in their own week (week-placed lines only) move to the
nearest week where that vendor's people have room, never before the order's schedule week; anything
still unplaced stays un-named. Order totals never change (checked before the commit).

Dry run unless --apply. Apply creates missing roster people (smr_workers), writes history rows tagged
with the run, all in one transaction. `--undo "<tag>"` restores every changed field, removes the lines
and the workers the run created.

Run from backend/:
  venv\\Scripts\\python.exe scripts\\smr_name_crews.py <crew_sheets.csv> [plan.csv] [--apply]
  venv\\Scripts\\python.exe scripts\\smr_name_crews.py --undo "<tag>"
  venv\\Scripts\\python.exe scripts\\smr_name_crews.py selfcheck
"""
import csv, hashlib, re, sys, uuid
sys.path.insert(0, ".")
from collections import defaultdict
from datetime import date, datetime, timezone
from decimal import Decimal, ROUND_FLOOR
from types import SimpleNamespace as NS

HALF, DAY_LIMIT = Decimal("0.5"), Decimal(12)
VENDORS = ("Green Choice", "XXL Construction", "BT Restoration")
INVOICE_NAME = {"Marco Blanco": "Marcos Blanco"}  # GC invoice spelling, as smr_line_quality.unname
PAPER_NAME = {"Michael": "Maikel Sanz", "Gabriel": "Gabriel Colina"}
CREW_SHA = "09d42d6729cbb2ee"  # sha256 prefix of the BT crew sheets this plan was reviewed against
FIELDS = ("reading_id", "work_date", "date_basis", "week", "vendor", "worker_id", "alias_on_paper", "headcount",
          "hours_each", "kind", "reason_code", "status", "exclusion_ground", "note")


def got_total(got):
    return sum(got.values(), Decimal(0))


def floor_half(x):
    return (x * 2).to_integral_value(rounding=ROUND_FLOOR) / 2


def schedule_week(text):
    """Week of a work order's schedule_date (a text column, mixed formats); 1 when blank or unreadable."""
    from app.domain.work_orders_smr_lines import week_of
    for fmt in ("%m/%d/%Y", "%Y-%m-%d"):
        try:
            return max(1, week_of(datetime.strptime(str(text).strip()[:10], fmt).date()))
        except ValueError:
            pass
    return 1


def plan_line(line, room, day, roster, on_order):
    """Pour one line onto people. Mutates room[(week, vendor, person)] and day[(person, date)].
    Returns ({person: hours}, leftover hours)."""
    people = roster.get((line.week, line.vendor), [])

    def cap(p):
        c = room.get((line.week, line.vendor, p), Decimal(0))
        if line.date:
            c = min(c, DAY_LIMIT - day.get((p, line.date), Decimal(0)))
        return floor_half(c)

    out, used = defaultdict(Decimal), set()
    for _ in range(line.headcount):
        want = Decimal(line.each)
        while want > 0:
            cands = [p for p in people if cap(p) > 0]
            if not cands:
                break
            p = min(cands, key=lambda p: (p in used, p not in on_order, -cap(p), p))
            take = min(want, cap(p))
            room[(line.week, line.vendor, p)] -= take
            if line.date:
                day[(p, line.date)] = day.get((p, line.date), Decimal(0)) + take
            out[p] += take
            used.add(p)
            want -= take
    return dict(out), line.headcount * Decimal(line.each) - got_total(out)


def selfcheck():
    L = lambda **k: NS(**({"week": 1, "vendor": "Green Choice", "headcount": 1, "each": Decimal(4), "date": None} | k))
    room = {(1, "Green Choice", "Ann"): Decimal(3), (1, "Green Choice", "Bo"): Decimal("2.5")}
    day, roster = {}, {(1, "Green Choice"): ["Ann", "Bo"]}
    # 4 h: on-order person first, then the one with room.
    assert plan_line(L(), room, day, roster, {"Bo"}) == ({"Bo": Decimal("2.5"), "Ann": Decimal("1.5")}, Decimal(0))
    # Crew of 2 x 3 h: two different people, 3 h each.
    room = {(1, "Green Choice", "Ann"): Decimal(3), (1, "Green Choice", "Bo"): Decimal(3)}
    assert plan_line(L(headcount=2, each=Decimal(3)), room, {}, roster, set()) == ({"Ann": 3, "Bo": 3}, Decimal(0))
    # 12 h day: Ann is nearly full on 06/01, so Bo takes the rest.
    room = {(1, "Green Choice", "Ann"): Decimal(20), (1, "Green Choice", "Bo"): Decimal(20)}
    day = {("Ann", date(2026, 6, 1)): Decimal("11.5")}
    r, left = plan_line(L(each=Decimal(6), date=date(2026, 6, 1)), room, day, roster, {"Ann"})
    assert r == {"Ann": Decimal("0.5"), "Bo": Decimal("5.5")} and left == 0, r
    # Nobody has room -> leftover.
    assert plan_line(L(each=Decimal(2)), {}, {}, roster, set()) == ({}, Decimal(2))
    assert schedule_week("") == 1 and schedule_week("7/23/2026") == schedule_week("2026-07-23") > 1
    print("selfcheck ok")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not sys.argv[1:] or "selfcheck" in args:
        return selfcheck()
    from sqlalchemy.orm import selectinload
    from app.database import SessionLocal
    from app.models import User
    from app.models_smr import SmrLaborLine, SmrLineEdit, SmrVendorInvoice, SmrWorker
    from app.domain.work_orders_smr_lines import GROUND_REMOVED, WEEK_BASES, validate_line_state, week_of
    from app.services.work_orders_smr_lines import _text, history, line_json

    db = SessionLocal()
    owner = db.query(User).filter(User.role == "owner").first()
    now = datetime.now(timezone.utc)

    def validate(state):
        validate_line_state(**{k: state[k] for k in ("status", "work_date", "date_basis", "exclusion_ground", "headcount",
                                                     "hours_each", "vendor", "kind", "reason_code", "week")})

    def change(line, changes, tag):
        state = {f: getattr(line, f) for f in FIELDS} | changes
        validate(state)
        for field, value in changes.items():
            if getattr(line, field) != value:
                history(db, line=line, actor=owner, field=field, old=_text(getattr(line, field)), new=_text(value),
                        reason=tag, now=now)
                setattr(line, field, value)
        line.updated_at, line.updated_by_id = now, owner.id

    def create(like, changes, tag):
        state = {f: getattr(like, f) for f in FIELDS} | changes
        validate(state)
        row = SmrLaborLine(id=uuid.uuid4(), work_order_id=like.work_order_id, import_key=None, created_at=now,
                           created_by_id=owner.id, updated_at=now, updated_by_id=owner.id, **state)
        db.add(row)
        db.flush()
        history(db, line=row, actor=owner, field="created", old=None, new=line_json(row), reason=tag, now=now)
        return row

    if "--undo" in flags:
        tag = args[0]
        edits = db.query(SmrLineEdit).filter(SmrLineEdit.reason == tag).order_by(SmrLineEdit.edited_at.desc()).all()
        if not edits:
            sys.exit(f"no edits carry the tag {tag!r}; nothing written")
        by_line = {l.id: l for l in db.query(SmrLaborLine).filter(SmrLaborLine.id.in_({e.line_id for e in edits}))}
        old = defaultdict(dict)
        for e in edits:  # newest first, so the earliest old value wins
            old[e.line_id][e.field] = e.old_value
        parse = {"work_date": date.fromisoformat, "hours_each": Decimal, "headcount": int, "week": int,
                 "reading_id": uuid.UUID, "worker_id": uuid.UUID}
        undo = f"undo {tag}"
        for line_id, fields in old.items():
            line = by_line[line_id]
            if "created" in fields:
                change(line, {"status": "excluded", "exclusion_ground": GROUND_REMOVED, "worker_id": None}, undo)
                continue
            change(line, {f: (parse.get(f, str)(v) if v is not None else None) for f, v in fields.items()}, undo)
        db.flush()
        made = {e.edited_at for e in edits}  # the run's workers carry its timestamp as created_at
        gone = 0
        for w in db.query(SmrWorker).filter(SmrWorker.created_at.in_(made)):
            if not db.query(SmrLaborLine.id).filter(SmrLaborLine.worker_id == w.id).first():
                db.delete(w)
                gone += 1
        db.commit()
        return print(f"undo: {len(old)} lines restored, {gone} workers removed")

    sheets = args[0]
    out_csv = args[1] if len(args) > 1 else None
    sha = hashlib.sha256(open(sheets, "rb").read()).hexdigest()[:16]
    if "--apply" in flags and sha != CREW_SHA:
        sys.exit(f"{sheets}: sha256 {sha}, expected {CREW_SHA} (crew sheets changed?); nothing written")
    workers = db.query(SmrWorker).all()
    canon = {}  # any spelling -> display_name
    for w in workers:
        for a in [w.display_name, *(w.aliases or [])]:
            canon.setdefault(a.strip().lower(), w.display_name)
    for a, b in PAPER_NAME.items():
        canon[a.lower()] = b  # "Gabriel" / "Michael" on paper are Gabriel Colina / Maikel Sanz
    known = {(w.display_name, w.vendor): w for w in workers}

    def who(name):
        name = re.sub(r"\s*\((?:REG|OT)\)$", "", name or "").strip()
        name = INVOICE_NAME.get(name, name)
        return canon.get(name.lower(), name)

    cap = defaultdict(Decimal)  # (week, vendor, person)
    for v in db.query(SmrVendorInvoice).filter(SmrVendorInvoice.vendor.in_(VENDORS[:2])):
        if v.worker:
            cap[(v.week, v.vendor, who(v.worker))] += Decimal(v.hours)
    for r in csv.DictReader(open(sheets, newline="", encoding="utf-8-sig")):
        if r["file"].startswith("BT") and r["hours"]:
            wk = week_of(date.fromisoformat(r["date"]))
            if wk:
                cap[(wk, "BT Restoration", who(r["name"]))] += Decimal(r["hours"])

    lines = (db.query(SmrLaborLine).options(selectinload(SmrLaborLine.work_order), selectinload(SmrLaborLine.worker))
             .filter(SmrLaborLine.status == "charged", SmrLaborLine.vendor.in_(VENDORS)).all())
    lines = [l for l in lines if l.exclusion_ground != GROUND_REMOVED and (l.week or 0) in range(1, 8)]
    room, day, on_order = dict(cap), {}, defaultdict(set)
    for l in lines:
        if l.worker_id:
            p, hrs = who(l.worker.display_name), l.headcount * Decimal(l.hours_each)
            room[(l.week, l.vendor, p)] = room.get((l.week, l.vendor, p), Decimal(0)) - hrs
            on_order[(l.work_order_id, l.vendor)].add(p)
            if l.work_date:
                day[(p, l.work_date)] = day.get((p, l.work_date), Decimal(0)) + hrs
    roster = defaultdict(list)
    for (wk, v, p) in cap:
        roster[(wk, v)].append(p)  # people with no smr_workers row yet are created on apply
    needed = {(p, v) for (_, v, p) in cap}
    missing = sorted(p for p, v in needed if (p, v) not in known)

    todo = sorted((l for l in lines if not l.worker_id),
                  key=lambda l: (l.week, l.vendor, l.work_date is None, l.work_order.number, str(l.id)))
    plan, stat, stuck = {}, defaultdict(lambda: defaultdict(Decimal)), []
    for l in todo:
        line = NS(week=l.week, vendor=l.vendor, headcount=l.headcount, each=Decimal(l.hours_each), date=l.work_date)
        got, left = plan_line(line, room, day, roster, on_order[(l.work_order_id, l.vendor)])
        plan[l.id] = [(p, x, None) for p, x in got.items()]
        on_order[(l.work_order_id, l.vendor)] |= set(got)
        if left:
            stuck.append((l, left))
        s = stat[l.vendor]
        s["lines"] += 1
        s["hours"] += l.headcount * Decimal(l.hours_each)
        s["named"] += l.headcount * Decimal(l.hours_each) - left
        s["left"] += left
    # Second pass (user 2026-11-11): hours no one has room for in their own week move to the nearest
    # other week where that vendor's people have room; week-placed lines only, never before the
    # order's schedule week. Paper-dated lines stay put (and stay un-named when full).
    for l, left in stuck:
        if l.work_date is None and l.date_basis in WEEK_BASES:
            lo = schedule_week(l.work_order.schedule_date)
            for w in sorted((w for w in range(lo, 8) if w != l.week), key=lambda w: (abs(w - l.week), w)):
                if not left:
                    break
                line = NS(week=w, vendor=l.vendor, headcount=1, each=left, date=None)
                got, left = plan_line(line, room, day, roster, on_order[(l.work_order_id, l.vendor)])
                plan[l.id] += [(p, x, w) for p, x in got.items()]
                on_order[(l.work_order_id, l.vendor)] |= set(got)
                stat[l.vendor]["moved"] += got_total(got)
                stat[l.vendor]["left"] -= got_total(got)
                stat[l.vendor]["named"] += got_total(got)
        if left:
            plan[l.id].append((None, left, None))

    print(f"crew sheets sha256 {sha}; roster people with no smr_workers row (apply creates them): {missing or 'none'}")
    print(f"{'vendor':18}{'lines':>7}{'hours':>9}{'named':>9}{'moved':>9}{'left':>9}")
    for v in VENDORS:
        s = stat[v]
        print(f"{v:18}{int(s['lines']):>7}{s['hours']:>9}{s['named']:>9}{s['moved']:>9}{s['left']:>9}")
    if out_csv:
        by_id = {l.id: l for l in todo}
        with open(out_csv, "w", newline="", encoding="utf-8-sig") as f:
            w = csv.writer(f)
            w.writerow(["wo", "line_id", "week", "vendor", "work_date", "person", "hours", "to_week"])
            for lid, pieces in plan.items():
                l = by_id[lid]
                for p, x, to in pieces:
                    w.writerow([l.work_order.number, lid, l.week, l.vendor, l.work_date or "", p or "", x, to or ""])
        print(f"plan: {out_csv} (blank person = left un-named)")

    if "--apply" not in flags:
        db.rollback()
        return print("dry run: nothing written (add --apply)")

    tag = f"name crews (user 2026-11-11) run {uuid.uuid4().hex[:12]}"
    before = defaultdict(Decimal)
    for l in lines:
        before[l.work_order_id] += l.headcount * Decimal(l.hours_each)
    for p, v in sorted(needed):  # one smr_workers row per missing roster person
        if (p, v) not in known:
            known[(p, v)] = SmrWorker(id=uuid.uuid4(), display_name=p, vendor=v, aliases=[], created_at=now)
            db.add(known[(p, v)])
    db.flush()
    for l in todo:
        first = True
        for p, x, to in plan[l.id]:
            note = l.note
            if p:
                note = f"{note or ''} | named from {l.vendor} crew (user 2026-11-11)".lstrip(" |")
            if to:
                note = f"{note or ''} | {x} h moved Week {l.week} -> {to}: over what individuals account for".lstrip(" |")
            ch = {"worker_id": known[(p, l.vendor)].id if p else None, "alias_on_paper": None if p else l.alias_on_paper,
                  "headcount": 1, "hours_each": x, "week": to or l.week, "note": note}
            if first:
                change(l, ch, tag)
                first = False
            else:
                create(l, ch, tag)
    db.flush()
    after = defaultdict(Decimal)
    for l in db.query(SmrLaborLine).filter(SmrLaborLine.status == "charged", SmrLaborLine.vendor.in_(VENDORS),
                                           SmrLaborLine.work_order_id.in_(list(before))):
        if l.week in range(1, 8) and l.exclusion_ground != GROUND_REMOVED:
            after[l.work_order_id] += l.headcount * Decimal(l.hours_each)
    bad = [o for o in before if before[o] != after[o]]
    if bad:
        db.rollback()
        sys.exit(f"order totals changed on {len(bad)} orders; rolled back, nothing written")
    db.commit()
    print(f"applied. tag: {tag}")


if __name__ == "__main__":
    main()
