"""Name the generic vendor-crew lines from the invoices (user 2026-11-06):
each unnamed Green Choice / XXL line takes the invoiced name with the most
unused hours in its week. BT invoices carry classes, so BT stays generic.
Writes carry a run tag; `--undo <tag>` reverses the run.

Run from backend/:
  venv\\Scripts\\python.exe scripts\\smr_fill_invoice_names.py [--dry-run]
  venv\\Scripts\\python.exe scripts\\smr_fill_invoice_names.py --undo "<tag>"
Set DATABASE_URL in the environment to aim at another database.
"""
import sys, uuid
sys.path.insert(0, ".")
from collections import Counter
from app.database import SessionLocal
from app.models import User
from app.services import work_orders_smr_weekly as weekly

db = SessionLocal()
owner = db.query(User).filter(User.role == "owner").first()

if len(sys.argv) > 2 and sys.argv[1] == "--undo":
    print(f"undone {weekly.undo_invoice_names(db, user=owner, tag=sys.argv[2])} lines")
    sys.exit()

dry = "--dry-run" in sys.argv
tag = f"named from the invoice (user 2026-11-06) run {uuid.uuid4().hex[:12]}"
result = weekly.fill_invoice_names(db, user=owner, tag=tag, dry_run=dry)
by = Counter()
for _, week, name, hours in result["named"]:
    by[(week, name)] += hours
print(f"named {len(result['named'])} units / {sum(h for *_, h in result['named'])} h "
      f"on {len({wo for wo, *_ in result['named']})} orders")
for (week, name), hours in sorted(by.items()):
    print(f"  week {week}  {name:28} {hours} h")
print(f"left unnamed (no name with room): {len(result['left'])} lines / {sum(h for *_, h in result['left'])} h")
for wo, week, vendor, hours in result["left"][:40]:
    print(f"  {wo} week {week} {vendor} {hours} h")
print("dry run: nothing written" if dry else f"tag: {tag}")
