"""Port the rehearsal copy's final state onto another database (user 2026-11-11: "copy the final state").

  source  the rehearsal copy (what the user worked on locally)
  base    the production snapshot the rehearsal copy was restored from
  target  where the changes go (a restored snapshot for the dry run, then production)

SMR labor tables are replaced with the source's rows. Everything else is a three-way merge: what the source changed
since the base is applied to the target (new rows inserted, changed columns set where the target still holds the
base value, stock counts moved by the difference). Tables the local server touched on its own are left alone.
Anything the target holds that the copy would overwrite is listed; --apply refuses to run past it without --accept.

One transaction. Dry run (rollback) unless --apply.
  python scripts/smr_port_state.py --target @file-holding-the-url [--apply] [--accept]"""
import argparse, pathlib, re, sys
from collections import Counter
import psycopg
from psycopg.rows import dict_row
from psycopg.types.json import Jsonb

LOCAL = "postgresql://rehearsal:rehearsal@localhost:8802/"
REPLACE = ("smr_workers", "smr_labor_lines", "smr_line_edits", "smr_correction_blocks")        # insert order
INSERT = ("items", "transactions", "work_order_items", "user_requests")                         # insert order (foreign keys)
MERGE = ("items", "work_orders", "user_requests")
LOCAL_ONLY = {"sessions", "alembic_version", "attendance_punches", "work_order_labor", "work_order_labor_sessions"}
DELTA = {("items", "quantity")}                     # moved by the difference, so the target's own stock movements stay
SOFT = {"updated_at"}                               # never a conflict: the target keeps its own value if it moved
INVOICE_KEY = "invoice, vendor, work_date, week, hours, worker"
RUN = re.compile(r" run [0-9a-f]{12}$")


def connect(url):
    con = psycopg.connect(url, row_factory=dict_row)
    con.execute("set time zone 'UTC'")
    return con


def columns(con, table):
    return [r["column_name"] for r in con.execute(
        "select column_name from information_schema.columns where table_schema = 'public' and table_name = %s "
        "order by ordinal_position", (table,))]


def tables(con):
    return {r["table_name"] for r in con.execute(
        "select table_name from information_schema.tables where table_schema = 'public' and table_type = 'BASE TABLE'")}


def rows(con, table):
    return {r["id"]: r for r in con.execute(f"select * from {table}")}


def digest(con, table, cols):
    row = f"md5(row({', '.join(cols)})::text)"
    r = con.execute(f"select count(*) n, md5(coalesce(string_agg({row}, '' order by {row}), '')) h from {table}").fetchone()
    return r["n"], r["h"]


def copy_rows(src, dst, table, cols, ids=None):
    """Stream rows source -> target with COPY; `ids` limits to those primary keys."""
    where = "" if ids is None else " where id = any(%s)"
    c = ", ".join(cols)
    with src.cursor().copy(f"copy (select {c} from {table}{where}) to stdout", None if ids is None else (list(ids),)) as out, \
            dst.cursor().copy(f"copy {table} ({c}) from stdin") as into:
        for chunk in out:
            into.write(chunk)


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--source", default=LOCAL + "inventory")
    ap.add_argument("--base", default=LOCAL + "baseline_1109")
    ap.add_argument("--target", required=True, help="URL, or @path of a file holding it")
    ap.add_argument("--apply", action="store_true")
    ap.add_argument("--accept", action="store_true", help="overwrite what the target alone holds (listed in the report)")
    a = ap.parse_args()
    url = pathlib.Path(a.target[1:]).read_text(encoding="utf-8").strip() if a.target.startswith("@") else a.target
    S, B, T = connect(a.source), connect(a.base), connect(url)
    info = T.info
    print(f"target: {info.host}:{info.port}/{info.dbname}   mode: {'APPLY' if a.apply else 'dry run (rolled back)'}")
    ver = lambda con: con.execute("select version_num from alembic_version").fetchone()["version_num"]
    if ver(S) != ver(T):
        sys.exit(f"schema differs: source {ver(S)}, target {ver(T)}. Deploy the migration first.")
    overwrites, conflicts = [], []

    # ---- 0. nothing the source changed may fall outside the plan
    handled = set(REPLACE) | set(INSERT) | set(MERGE) | LOCAL_ONLY | {"smr_vendor_invoices"}
    for t in sorted(tables(S) - handled):
        shared = [c for c in columns(S, t) if c in columns(B, t)]
        if t not in tables(B) or digest(S, t, shared) != digest(B, t, shared):
            sys.exit(f"table {t} changed on the source and is not in the port plan")

    # ---- 1. what the target alone holds in the tables being replaced
    stems = lambda con: Counter(RUN.sub("", r["reason"] or "(no reason)") for r in con.execute("select reason from smr_line_edits"))
    ts, ss = stems(T), stems(S)
    for stem in sorted(set(ts) - set(ss)):
        overwrites.append(f"line edits on the target only: {ts[stem]} x '{stem[:90]}'")
    # hand edits (no run tag) the target holds and the source does not: a stem match alone misses a reused reason
    sids = [r["id"] for r in S.execute("select id from smr_line_edits")]
    for r in T.execute("""select o.number, e.field, e.new_value, e.reason, e.edited_at from smr_line_edits e
                          join smr_labor_lines l on l.id = e.line_id join work_orders o on o.id = l.work_order_id
                          where e.id <> all(%s) and coalesce(e.reason, '') !~ ' run [0-9a-f]{12}$' order by e.edited_at""", (sids,)):
        overwrites.append(f"hand edit on the target only: {r['number']} {r['field']} -> {r['new_value']!r} "
                          f"({r['reason']}, {r['edited_at']:%m/%d %H:%M})")
    lost = T.execute("""select count(*) n from smr_correction_blocks t where pasted_at is not null and not exists
                        (select 1 from unnest(%s::uuid[]) s(id) where s.id = t.id)""",
                     ([r["id"] for r in S.execute("select id from smr_correction_blocks where pasted_at is not null")],)).fetchone()["n"]
    if lost:
        overwrites.append(f"{lost} correction block(s) marked pasted on the target only")
    tw = {(r["display_name"], r["vendor"]) for r in T.execute("select display_name, vendor from smr_workers")}
    sw = {(r["display_name"], r["vendor"]) for r in S.execute("select display_name, vendor from smr_workers")}
    if tw - sw:
        overwrites.append(f"workers on the target only: {sorted(tw - sw)}")
    need = {r["reading_id"] for r in S.execute("select distinct reading_id from smr_labor_lines where reading_id is not null")}
    have = {r["id"] for r in T.execute("select id from smr_paper_readings")}
    if need - have:
        sys.exit(f"{len(need - have)} paper reading(s) the source lines point at are missing on the target")
    extra = T.execute("select count(*) n from smr_paper_readings where id <> all(%s)",
                      ([r["id"] for r in S.execute("select id from smr_paper_readings")],)).fetchone()["n"]
    if extra:
        overwrites.append(f"{extra} paper reading(s) on the target only: their lines would be dropped")
    inv = lambda con: Counter(tuple(r.values()) for r in con.execute(f"select {INVOICE_KEY} from smr_vendor_invoices"))
    it, is_ = inv(T), inv(S)
    if it != is_:
        overwrites.append(f"vendor invoices differ: {sum((it - is_).values())} row(s) on the target only, "
                          f"{sum((is_ - it).values())} on the source only (invoices are replaced too)")

    # ---- 2. replace the SMR labor tables
    for t in reversed(REPLACE):
        T.execute(f"delete from {t}")
    if it != is_:
        T.execute("delete from smr_vendor_invoices")
        copy_rows(S, T, "smr_vendor_invoices", columns(S, "smr_vendor_invoices"))
    for t in REPLACE:
        copy_rows(S, T, t, columns(S, t))
        if digest(S, t, columns(S, t)) != digest(T, t, columns(S, t)):
            sys.exit(f"{t}: target does not equal the source after the copy")
        print(f"replaced {t}: {digest(T, t, ['id'])[0]} rows")

    # ---- 3. three-way merge of everything else the source changed
    for t in INSERT:
        sb, ss_ = rows(B, t), rows(S, t)
        if sb.keys() - ss_.keys():
            sys.exit(f"{t}: {len(sb.keys() - ss_.keys())} row(s) deleted on the source; not handled")
        new = ss_.keys() - sb.keys()
        there = {r["id"] for r in T.execute(f"select id from {t} where id = any(%s)", (list(new),))}
        if new - there:
            copy_rows(S, T, t, columns(S, t), new - there)
        landed = T.execute(f"select count(*) n from {t} where id = any(%s)", (list(new),)).fetchone()["n"]
        assert landed == len(new), f"{t}: {len(new) - landed} new source row(s) not on the target"
        print(f"inserted {t}: {len(new - there)} rows" + (f" ({len(there)} already on the target)" if there else ""))
    for t in MERGE:
        sb, ss_, st = rows(B, t), rows(S, t), rows(T, t)
        done = Counter()
        for k in sb.keys() & ss_.keys():
            changed = [c for c in ss_[k] if ss_[k][c] != sb[k].get(c)]
            if not changed:
                continue
            if k not in st:
                conflicts.append(f"{t} {k}: changed on the source, gone from the target"); continue
            sets = {}
            for c in changed:
                old, new, cur = sb[k].get(c), ss_[k][c], st[k][c]
                if (t, c) in DELTA:
                    sets[c] = cur + (new - old)
                elif cur == new or (c in SOFT and cur != old):
                    continue
                elif cur == old or (old is None and not cur):
                    sets[c] = new
                else:
                    conflicts.append(f"{t} {st[k].get('number') or st[k].get('name') or k}.{c}: base {str(old)[:40]!r}, "
                                     f"source {str(new)[:40]!r}, target {str(cur)[:40]!r}")
            hard = [c for c in sets if c not in SOFT]
            if hard:
                vals = [Jsonb(v) if isinstance(v, (dict, list)) else v for v in sets.values()]
                T.execute(f"update {t} set {', '.join(f'{c} = %s' for c in sets)} where id = %s", (*vals, k))
                done.update(hard)
        print(f"merged {t}: {dict(done)}")

    # ---- 4. checks, then commit or roll back
    hours = lambda con: con.execute("select coalesce(sum(headcount * hours_each), 0) h, count(*) n from smr_labor_lines "
                                    "where status = 'charged'").fetchone()
    hs, ht = hours(S), hours(T)
    assert (hs["h"], hs["n"]) == (ht["h"], ht["n"]), f"charged hours differ: source {hs}, target {ht}"
    d = lambda con: con.execute("select count(*) n from work_orders where coalesce(smr_description, '') <> ''").fetchone()["n"]
    print(f"charged: {ht['n']} lines / {ht['h']:g} h (source {hs['h']:g} h); descriptions on target {d(T)} (source {d(S)})")
    for title, items in (("OVERWRITTEN ON THE TARGET", overwrites), ("CONFLICTS (left as the target has them)", conflicts)):
        print(f"\n{title}: {len(items)}")
        for x in items[:40]:
            print("  -", x)
    if a.apply and overwrites and not a.accept:
        T.rollback(); sys.exit("\nnot applied: the target holds changes the copy would overwrite; rerun with --accept to go ahead")
    if a.apply:
        T.commit(); print("\nAPPLIED")
    else:
        T.rollback(); print("\ndry run: rolled back, nothing written")


if __name__ == "__main__":
    main()
