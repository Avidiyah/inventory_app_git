# Handoff: production snapshot on the dev server + Takeoff demo data (2026-11-25)

**Goal:** the owner sees Takeoff and the new work-order card working on real
production data, with mock takeoff data filled in.

**State:** Takeoff and the top bar are committed on local main
(046b135..0dbb1d0) and **not pushed**, so production has no takeoff tables.
The flagged-time work (6cf0cdb..f0d3d0e) is unpushed too.

## Facts

| Thing | Where |
|---|---|
| Local Postgres 18 | port 8801, role `inventory_user`, DB `inventory` (the dev and test DB; leave it alone) |
| Tools | `C:\Program Files\PostgreSQL\18\bin\{pg_dump,pg_restore,createdb,psql}.exe` |
| Newest local snapshot | `Desktop\SMR27 Reconciliation\prod_snapshots\prod_2026-11-16_before-descriptions.dump` (9 days old) |
| Production URL, for a fresh dump | `Desktop\DB URL.txt` (the db-copy entry is live). Never print it. |
| Server | `backend\venv\Scripts\python.exe -m uvicorn app.main:app --port 8124` from `backend/` |

## Plan

1. **Ask the owner:** take a fresh read-only `pg_dump -Fc` of production, or use the 11-16 snapshot? A fresh dump is the only way to see current orders. Get a yes before connecting to production.
2. **Restore into a new database**, `inventory_demo` on 8801 (`createdb`, then `pg_restore --no-owner --role=inventory_user`). Never restore over `inventory`: the test suite and local data live there.
3. **Migrate the copy:** `alembic upgrade head` with `DATABASE_URL` pointing at `inventory_demo`, set in the shell. Don't edit `backend/.env`: it also holds the VAPID key, so never truncate it.
4. **Defuse the copy before the server touches it** (production rows reach real people and services):
   - `DELETE FROM push_subscriptions;` stops dev sends from buzzing the crew's phones.
   - `DELETE FROM netfacilities_cloud_sessions;` removes stored sessions that work like passwords.
   - `DELETE FROM sessions;`
5. **Sign-in:** production password hashes are unknown. Run `scripts/create_owner.py` against the copy. The owner types the password; nobody puts it in chat.
6. **Mock data script:** `backend/scripts/demo_takeoff_seed.py`. It takes `--database-url`, refuses to run when the database name isn't `inventory_demo`, and tags every row it writes so `--undo` removes them. Write rows through `services.takeoff` (`add_line`, `set_purchase`) so the business rules hold. Cover:
   - 6–10 open orders on two or three real service types (WMR first), 3–6 lines each.
   - One item planned on two service types (shared shortfall).
   - One item short, with a partial purchase on the way ("Order N more" plus an editable On the way).
   - One item covered by stock, and one covered by a purchase ("Ordered").
   - One item with no price ("—"), and one decimal quantity (2.5).
   - One completed order with lines (need excluded, read-only card).
   - One service type typed two ways ("WMR" and "wmr") so they merge into one group.
7. **Run the server on the copy:** set `DATABASE_URL` for `inventory_demo` in the shell, then start uvicorn on 8124. Hand the owner the checklist from the 2026-11-25 Takeoff session: card, Takeoff section, Takeoff page, tutorials.
8. **Afterwards:** stop the server. Drop `inventory_demo` only when the owner says so.

## Don'ts

- No writes to production. The dump is read-only, and only with the owner's yes.
- No push: pushing main deploys.
- Don't commit dumps or URLs. The seed script may be committed; ask first.
