"""Flip every line excluded as "read, not charged (weekly reports)" to charged
(user ruling 2026-11-06: paper hours bill where read; week overruns show on
the gap graph instead). Each edit goes through the service, so a history
row carries the run tag.  `--undo <tag>` puts those lines back.

Run from backend/:  venv\Scripts\python.exe <this file> [--undo "<tag>"]
"""
import sys, uuid
sys.path.insert(0, ".")
from decimal import Decimal
from app.database import SessionLocal
from app.domain.work_orders_smr_lines import GROUND_NOT_CHARGED_REPORTS
from app.models import SmrLaborLine, SmrLineEdit, User
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
            status="excluded", exclusion_ground=GROUND_NOT_CHARGED_REPORTS, reason=f"undo {tag}"))
    print(f"undone {len(rows)} lines / {hours(rows)} h")
    sys.exit()

tag = f"re-charged: paper hours bill where read (user 2026-11-06) run {uuid.uuid4().hex[:12]}"
rows = db.query(SmrLaborLine).filter(
    SmrLaborLine.status == "excluded", SmrLaborLine.exclusion_ground == GROUND_NOT_CHARGED_REPORTS).all()
print(f"before: {len(rows)} lines / {hours(rows)} h excluded under the weekly-reports ground")
for r in rows:
    svc.edit_line(db, line_id=r.id, user=owner, payload=SmrLineEditIn(status="charged", exclusion_ground=None, reason=tag))
left = db.query(SmrLaborLine).filter(SmrLaborLine.exclusion_ground == GROUND_NOT_CHARGED_REPORTS).count()
print(f"after: {left} left on that ground; charged {len(rows)} lines / {hours(rows)} h")
print(f"tag: {tag}")
