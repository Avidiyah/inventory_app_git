"""Move SMR material entries from the half-gallon Bio item to the pint item
(user 2026-11-16). Quantities kept, stock untouched; the linked History
transaction moves with each entry. Dry run unless --apply.

Usage: PGURL=... python scripts/smr_bio_swap.py [--apply]
Undo:  PGURL=... python scripts/smr_bio_swap.py --undo <json>
"""
import json
import os
import sys
from datetime import datetime

import psycopg

HALF = "9cd0aa11-eda7-49a7-a9cd-a5df759ebb5b"  # $30 Bio Cleaner (Half Gallon) Bye, Bye - Sam
PINT = "aafd3802-7c5e-46c7-8688-a91d69a4f670"  # Bio Cleaner (One Pint)

conn = psycopg.connect(os.environ["PGURL"], connect_timeout=15)
cur = conn.cursor()


def stock():
    cur.execute("select id::text, quantity from items where id in (%s, %s)", (HALF, PINT))
    return dict(cur.fetchall())


if "--undo" in sys.argv:
    saved = json.load(open(sys.argv[sys.argv.index("--undo") + 1]))
    cur.execute("update work_order_items set item_id = %s where id = any(%s::uuid[])", (HALF, saved["entries"]))
    cur.execute("update transactions set item_id = %s where id = any(%s::uuid[])", (HALF, saved["transactions"]))
    conn.commit()
    print("undone:", len(saved["entries"]), "entries,", len(saved["transactions"]), "transactions")
    sys.exit()

cur.execute("""
  select wi.id::text, wi.transaction_id::text, w.number, wi.quantity, coalesce(wi.billable_quantity, wi.quantity)
  from work_order_items wi join work_orders w on w.id = wi.work_order_id
  where w.smr_imported_at is not null and wi.item_id = %s order by w.number""", (HALF,))
rows = cur.fetchall()
cur.execute("""select count(*) from work_order_items a join work_order_items b on a.work_order_id = b.work_order_id
  join work_orders w on w.id = a.work_order_id
  where w.smr_imported_at is not null and a.item_id = %s and b.item_id = %s""", (HALF, PINT))
clashes = cur.fetchone()[0]
cur.execute("select id::text, price from items where id in (%s, %s)", (HALF, PINT))
price = dict(cur.fetchall())
billed = sum(r[4] for r in rows)
print(f"entries: {len(rows)} on {len({r[2] for r in rows})} orders; qty {sum(r[3] for r in rows)}; clashes {clashes}")
print(f"bill at item price: ${billed * price[HALF]:.2f} -> ${billed * price[PINT]:.2f}")
before = stock()
print("stock before:", before)
if clashes or "--apply" not in sys.argv:
    print("dry run" if not clashes else "STOP: an order holds both items")
    sys.exit()

entries = [r[0] for r in rows]
txns = [r[1] for r in rows if r[1]]
path = f"smr_bio_swap_{datetime.now():%Y%m%d_%H%M%S}.json"
json.dump({"entries": entries, "transactions": txns}, open(path, "w"))
cur.execute("update work_order_items set item_id = %s where id = any(%s::uuid[])", (PINT, entries))
cur.execute("update transactions set item_id = %s where id = any(%s::uuid[])", (PINT, txns))
cur.execute("""select count(*) from work_order_items wi join work_orders w on w.id = wi.work_order_id
  where w.smr_imported_at is not null and wi.item_id = %s""", (HALF,))
left = cur.fetchone()[0]
assert left == 0 and stock() == before, "check failed, rolling back"
conn.commit()
print(f"moved {len(entries)} entries, {len(txns)} transactions; undo file {path}")
