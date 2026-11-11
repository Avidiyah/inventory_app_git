"""SMR27: fill the work description (work_orders.smr_description) from the reviewed CSV
(user 2026-11-11: descriptions are pre-filled, there is no suggestion box).

CSV columns used: wo, status, description. Rows with status "load" are written; "hold" and
"waiting" rows are left alone. Only an empty description is filled, so text a person saved
is never overwritten. --undo blanks a description only where it still equals the CSV text.

Dry run unless --apply. A correction block prints the description the next time it is generated.
Run from backend/:  venv\\Scripts\\python.exe scripts\\smr_descriptions.py <csv> [--undo] [--apply]
"""
import csv, sys
sys.path.insert(0, ".")


def plan(rows, current, undo=False):
    """rows: CSV dicts. current: {wo: saved description or None}. Returns ({wo: text or None}, {why skipped: count})."""
    writes, skipped = {}, {}

    def skip(why):
        skipped[why] = skipped.get(why, 0) + 1

    for r in rows:
        wo, text = r["wo"].strip(), r["description"].strip()
        saved = (current.get(wo) or "").strip()
        if r["status"].strip() != "load" or not text:
            skip("not marked load")
        elif wo not in current:
            skip("order not in this database")
        elif undo:
            if saved == text:
                writes[wo] = None
            else:
                skip("edited since the load, kept" if saved else "blank already")
        elif saved:
            skip("already has this text" if saved == text else "has a description a person saved, kept")
        else:
            writes[wo] = text
    return writes, skipped


def selfcheck():
    rows = [dict(wo="1", status="load", description="A"), dict(wo="2", status="load", description="B"),
            dict(wo="3", status="hold", description="C"), dict(wo="4", status="load", description="D"),
            dict(wo="5", status="waiting", description="")]
    current = {"1": None, "2": "typed by a person", "3": None, "5": None}
    assert plan(rows, current) == ({"1": "A"}, {"has a description a person saved, kept": 1, "not marked load": 2,
                                               "order not in this database": 1})
    loaded = {"1": "A", "2": "typed by a person", "3": None, "5": None}
    assert plan(rows, loaded)[0] == {}                                   # a second load writes nothing
    assert plan(rows, loaded, undo=True)[0] == {"1": None}               # undo only what the load wrote
    assert plan(rows, loaded | {"1": "A, then edited"}, undo=True)[0] == {}  # an edited description is kept
    print("selfcheck ok")


def main():
    args = [a for a in sys.argv[1:] if not a.startswith("--")]
    flags = {a for a in sys.argv[1:] if a.startswith("--")}
    if not args or args[0] == "selfcheck":
        return selfcheck()
    from app.database import SessionLocal, engine
    from app.models import WorkOrder

    print(f"database: {engine.url.host}:{engine.url.port}/{engine.url.database}")
    if "--apply" in flags and engine.url.host not in ("localhost", "127.0.0.1") and "--not-local" not in flags:
        sys.exit("not a local database; add --not-local to write there. nothing written")
    rows = list(csv.DictReader(open(args[0], newline="", encoding="utf-8-sig")))
    db = SessionLocal()
    found = db.query(WorkOrder.number, WorkOrder.smr_description).filter(
        WorkOrder.number.in_([r["wo"].strip() for r in rows])).all()
    numbers = [number for number, _ in found]
    assert len(numbers) == len(set(numbers)), "an order number appears twice in this database"
    writes, skipped = plan(rows, dict(found), undo="--undo" in flags)
    print(f"{'blank' if '--undo' in flags else 'fill'}: {len(writes)} descriptions")
    for why, count in sorted(skipped.items()):
        print(f"  skipped {count}: {why}")
    if "--apply" not in flags:
        return print("dry run: nothing written (add --apply)")
    for wo, text in writes.items():
        db.query(WorkOrder).filter(WorkOrder.number == wo).update({"smr_description": text})
    db.commit()
    print("written")


if __name__ == "__main__":
    main()
