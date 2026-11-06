"""Charge every undated paper line to its order's most likely labor week
(user ruling 2026-11-06: the week matters, the day does not). The week per
order comes from the reconciliation's likely_weeks.csv (building's dated
paper per week, close week a ceiling). Each line becomes a charged week
placement with the same history rows a service edit writes (one per field,
carrying the run tag), in ONE transaction -- the per-line service path took
seconds a line against Render.  `--undo <tag>` puts those lines back.

Run from backend/:
  venv\\Scripts\\python.exe scripts\\smr_charge_undated_likely.py <likely_weeks.csv> [--dry-run]
  venv\\Scripts\\python.exe scripts\\smr_charge_undated_likely.py --undo "<tag>"
Set DATABASE_URL in the environment to aim at another database.
"""
import csv, sys, uuid
sys.path.insert(0, ".")
from collections import Counter
from datetime import datetime, timezone
from decimal import Decimal
from sqlalchemy.orm import selectinload
from app.database import SessionLocal
from app.domain.work_orders_smr_lines import DATE_BASIS_PAPER, GROUND_UNDATED, WEEK_PLACEMENT_BASIS, validate_line_state
from app.models import SmrLaborLine, SmrLineEdit, User, WorkOrder
from app.services.work_orders_smr_lines import _text, history

db = SessionLocal()
owner = db.query(User).filter(User.role == "owner").first()
now = datetime.now(timezone.utc)

def hours(rows):
    return sum((Decimal(r.headcount) * Decimal(r.hours_each) for r in rows), Decimal(0))

def apply(line, changes, reason):
    """Set each changed field with a history row, as edit_line does; no commit."""
    for field, value in changes.items():
        if getattr(line, field) != value:
            history(db, line=line, actor=owner, field=field, old=_text(getattr(line, field)), new=_text(value), reason=reason, now=now)
            setattr(line, field, value)
    line.updated_at, line.updated_by_id = now, owner.id

if len(sys.argv) > 2 and sys.argv[1] == "--undo":
    tag = sys.argv[2]
    ids = {e.line_id for e in db.query(SmrLineEdit).filter(SmrLineEdit.reason == tag, SmrLineEdit.field == "status")}
    rows = db.query(SmrLaborLine).filter(SmrLaborLine.id.in_(ids), SmrLaborLine.status == "charged").all()
    for r in rows:
        apply(r, {"status": "excluded", "exclusion_ground": GROUND_UNDATED, "date_basis": DATE_BASIS_PAPER, "week": None}, f"undo {tag}")
    db.commit()
    print(f"undone {len(rows)} lines / {hours(rows)} h")
    sys.exit()

path, dry = sys.argv[1], "--dry-run" in sys.argv
likely = {r["wo"]: int(r["week"]) for r in csv.DictReader(open(path, newline="", encoding="utf-8"))}
rows = (
    db.query(SmrLaborLine).options(selectinload(SmrLaborLine.work_order))
    .filter(SmrLaborLine.status == "excluded", SmrLaborLine.exclusion_ground == GROUND_UNDATED).all()
)
todo = [(r, likely[r.work_order.number]) for r in rows if r.work_order.number in likely]
skipped = [r for r in rows if r.work_order.number not in likely]
print(f"undated: {len(rows)} lines / {hours(rows)} h; with a likely week: {len(todo)} lines / {hours([r for r, _ in todo])} h; "
      f"no likely week (left alone): {len(skipped)} lines / {hours(skipped)} h on {sorted({r.work_order.number for r in skipped})}")
by = Counter()
for r, w in todo:
    by[(w, r.vendor)] += Decimal(r.headcount) * Decimal(r.hours_each)
for (w, v), h in sorted(by.items()):
    print(f"  week {w}  {v:18} {h} h")
if dry:
    print("dry run: nothing written")
    sys.exit()

tag = f"charged to likely week (user 2026-11-06) run {uuid.uuid4().hex[:12]}"
for r, w in todo:
    validate_line_state(status="charged", work_date=r.work_date, date_basis=WEEK_PLACEMENT_BASIS, exclusion_ground=None,
                        headcount=r.headcount, hours_each=r.hours_each, vendor=r.vendor, kind=r.kind,
                        reason_code=r.reason_code, week=w)
    apply(r, {"status": "charged", "exclusion_ground": None, "date_basis": WEEK_PLACEMENT_BASIS, "week": w}, tag)
db.commit()
left = db.query(SmrLaborLine).filter(SmrLaborLine.exclusion_ground == GROUND_UNDATED, SmrLaborLine.status == "excluded").count()
print(f"after: {left} undated lines left; charged {len(todo)} lines / {hours([r for r, _ in todo])} h")
print(f"tag: {tag}")
