"""Charge every undated paper line to its order's most likely labor week
(user ruling 2026-11-06: the week matters, the day does not). The week per
order comes from the reconciliation's likely_weeks.csv (building's dated
paper per week, close week a ceiling). Each line becomes a charged week
placement; every edit goes through the service, so a history row carries
the run tag.  `--undo <tag>` puts those lines back to excluded / undated.

Run from backend/:
  venv\\Scripts\\python.exe scripts\\smr_charge_undated_likely.py <likely_weeks.csv> [--dry-run]
  venv\\Scripts\\python.exe scripts\\smr_charge_undated_likely.py --undo "<tag>"
Set DATABASE_URL in the environment to aim at another database.
"""
import csv, sys, uuid
sys.path.insert(0, ".")
from collections import Counter
from decimal import Decimal
from app.database import SessionLocal
from app.domain.work_orders_smr_lines import DATE_BASIS_PAPER, GROUND_UNDATED, WEEK_PLACEMENT_BASIS
from app.models import SmrLaborLine, SmrLineEdit, User, WorkOrder
from app.schemas.work_orders_smr_lines import SmrLineEditIn
from app.services import work_orders_smr_lines as svc

db = SessionLocal()
owner = db.query(User).filter(User.role == "owner").first()

def hours(rows):
    return sum((Decimal(r.headcount) * Decimal(r.hours_each) for r in rows), Decimal(0))

if len(sys.argv) > 2 and sys.argv[1] == "--undo":
    tag = sys.argv[2]
    ids = {e.line_id for e in db.query(SmrLineEdit).filter(SmrLineEdit.reason == tag, SmrLineEdit.field == "status")}
    rows = db.query(SmrLaborLine).filter(SmrLaborLine.id.in_(ids), SmrLaborLine.status == "charged").all()
    for r in rows:
        svc.edit_line(db, line_id=r.id, user=owner, payload=SmrLineEditIn(
            status="excluded", exclusion_ground=GROUND_UNDATED, date_basis=DATE_BASIS_PAPER, week=None, reason=f"undo {tag}"))
    print(f"undone {len(rows)} lines / {hours(rows)} h")
    sys.exit()

path, dry = sys.argv[1], "--dry-run" in sys.argv
likely = {r["wo"]: int(r["week"]) for r in csv.DictReader(open(path, newline="", encoding="utf-8"))}
rows = (
    db.query(SmrLaborLine).join(WorkOrder)
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
    svc.edit_line(db, line_id=r.id, user=owner, payload=SmrLineEditIn(
        status="charged", exclusion_ground=None, date_basis=WEEK_PLACEMENT_BASIS, week=w, reason=tag))
left = db.query(SmrLaborLine).filter(SmrLaborLine.exclusion_ground == GROUND_UNDATED).count()
print(f"after: {left} undated lines left; charged {len(todo)} lines / {hours([r for r, _ in todo])} h")
print(f"tag: {tag}")
