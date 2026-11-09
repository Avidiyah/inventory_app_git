"""Load the paper of SMR orders the bulk import refused because the number
already existed as a plain work order ("Not SMR orders: ..."). Production's
import ran without them (run ce433a212267 = the approved 0dc2a170e862 files
minus six orders); user 2026-11-09: load them.

Each order is marked SMR the way the import marks an order it creates
(`smr_imported_at`, `smr_baseline`, `smr_target` from its Breakdown row, the
SMR service type when it has none), then the app's own `import_paper` runs on
just that order's rows of the full files. Undated lines then go through
`smr_charge_undated_likely.py` with likely_weeks.csv cut to these orders.

Run from backend/:
  venv\\Scripts\\python.exe scripts\\smr_load_skipped_orders.py <Deliverable Batch dir> <wo> [<wo> ...] --apply
DATABASE_URL in the environment picks the database; the host prints first.
"""
import csv, io, sys
sys.path.insert(0, ".")
from datetime import datetime, timezone
from pathlib import Path

from app.database import SessionLocal
from app.domain import work_orders_smr as smr
from app.models import User
from app.services import work_orders as wos
from app.services.work_orders_smr_import import _parse, import_paper

args = [a for a in sys.argv[1:] if a != "--apply"]
if "--apply" not in sys.argv or len(args) < 2:
    sys.exit(__doc__)
folder, numbers = Path(args[0]), set(args[1:])


def only(name: str) -> bytes:
    """The file's header and the rows of `numbers`, as CSV bytes."""
    rows = list(csv.DictReader(io.StringIO((folder / name).read_bytes().decode("utf-8-sig"))))
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=list(rows[0]), lineterminator="\n")
    writer.writeheader()
    writer.writerows(r for r in rows if r["wo"] in numbers)
    return out.getvalue().encode("utf-8")


db = SessionLocal()
print("database:", db.get_bind().url.host, db.get_bind().url.database)
owner = db.query(User).filter(User.role == "owner").first()
readings, lines = only("paper_readings.full.csv"), only("paper_lines.full.csv")
_, _, breakdown = _parse(readings, lines, (folder / "breakdown.csv").read_bytes())

now = datetime.now(timezone.utc)
for number in sorted(numbers):
    order = wos.find_by_number(db, number)
    if order is None or order.smr_imported_at is not None or number not in breakdown:
        sys.exit(f"{number}: expected an existing non-SMR order with a Breakdown row; nothing written")
    order.smr_imported_at = now
    order.service_type = order.service_type or smr.SMR_SERVICE_TYPE
    order.smr_baseline = smr.snapshot(order, taken_at=now, source_row={
        "WORK ORDER": number, "SERVICE TYPE": smr.SMR_SERVICE_TYPE,
        "CREATOR": "marked SMR 2026-11-09: the bulk import refused it (existed as a plain order)"})
    order.smr_target = smr.target_record(breakdown[number], imported_at=now)
    print(f"  {number}: marked SMR, target {order.smr_target['hours']} h")
db.commit()

result = import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)
print(f"imported {result.readings} readings, {result.lines} lines; charged {result.charged_hours} h, "
      f"excluded {result.excluded_hours} h; {result.run_id}")
cut = folder / "likely_weeks.skipped_orders.csv"
rows = [r for r in csv.DictReader(open(folder / "likely_weeks.csv", newline="", encoding="utf-8")) if r["wo"] in numbers]
with open(cut, "w", newline="", encoding="utf-8") as f:
    writer = csv.DictWriter(f, fieldnames=list(rows[0]) if rows else ["wo", "week"])
    writer.writeheader()
    writer.writerows(rows)
print(f"likely weeks for these orders: {len(rows)} -> {cut}")
