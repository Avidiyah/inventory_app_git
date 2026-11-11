"""The paper-correction routes S6–S16 (spec 2026-11-04) over real HTTP, and
the work-order detail carrying readings, lines, legacy minutes and the
block. TestClient, never a direct handler call (this repo has been bitten
by FastAPI parsing a signature differently than a direct call does)."""

from __future__ import annotations

import csv
import io
import uuid
from datetime import date
from decimal import Decimal

from fastapi.testclient import TestClient

from app.database import get_db
from app.main import app
from app.models import User
from app.services import auth as auth_service
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service

READING_COLUMNS = ["reading_id", "wo", "printing_no", "work_date", "hours_as_read", "raw_note", "reviewer", "csv_row"]
LINE_COLUMNS = ["line_id", "reading_id", "wo", "work_date", "date_basis", "week", "vendor", "worker", "alias_on_paper",
                "headcount", "hours_each", "kind", "status", "exclusion_ground", "reason_code", "note"]


def _user(db, role="admin"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}", first_name="Pat", last_name=role.title(),
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user)
    db.flush()
    return user


def _smr_order(db, owner):
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    sheet = ("WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
             f"{number},c,SMR27 - Belfor,05/15/2026,05/21/2026,a,Closed,\"B:1,U 1,x\"\r\n").encode()
    smr_service.import_smr(db, csv_bytes=sheet, user=owner)
    return wos.find_by_number(db, number)


def _csv(columns, rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return out.getvalue().encode("utf-8")


class _Client:
    def __init__(self, db, user):
        self.db, self.user = db, user

    def __enter__(self):
        app.dependency_overrides[get_db] = lambda: self.db
        self.client = TestClient(app).__enter__()
        if self.user is not None:
            self.client.cookies.set("session", auth_service.create_session(self.db, self.user))
        return self.client

    def __exit__(self, *exc):
        self.client.__exit__(*exc)
        del app.dependency_overrides[get_db]


LINE = {"vendor": "Belfor", "hours_each": "2.0", "reason_code": "accurate", "work_date": "2026-06-20", "reason": "paper"}


def test_admin_adds_a_reading_and_a_line_and_the_detail_carries_them(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    wos.add_work_order_labor(db, order.id, user=admin, technician_id=None, minutes=30)
    with _Client(db, admin) as client:
        reading = client.post(f"/work-orders/smr/{order.id}/readings",
                              json={"printing_no": 1, "work_date": "2026-06-20", "hours_as_read": "2.0", "raw_note": "Pat 2 h"})
        assert reading.status_code == 200, reading.text
        line = client.post(f"/work-orders/smr/{order.id}/lines", json={**LINE, "reading_id": reading.json()["id"]})
        assert line.status_code == 200, line.text
        assert line.json()["hours"] == "2.0" and line.json()["history"][0]["field"] == "created"

        edited = client.patch(f"/work-orders/smr/readings/{reading.json()['id']}", json={"hours_as_read": "3.0", "raw_note": "Pat 3 h"})
        assert edited.status_code == 200 and edited.json()["hours_as_read"] == "3.0" and edited.json()["raw_note"] == "Pat 3 h"
        assert client.patch(f"/work-orders/smr/readings/{reading.json()['id']}", json={"raw_note": "Pat 3 h"}).status_code == 400
        assert client.patch(f"/work-orders/smr/readings/{uuid.uuid4()}", json={"raw_note": "x"}).status_code == 404

        detail = client.get(f"/work-orders/{order.id}").json()
        assert detail["labor_total"] == "125.00" and detail["smr_legacy_labor_minutes"] == 30
        assert [l["id"] for l in detail["smr_lines"]] == [line.json()["id"]]
        assert detail["smr_readings"][0]["id"] == reading.json()["id"] and detail["smr_block"] is None

        block = client.post(f"/work-orders/smr/{order.id}/block")
        assert block.status_code == 200 and block.json()["version"] == 1 and block.json()["stale"] is False
        pasted = client.post(f"/work-orders/smr/blocks/{block.json()['id']}/pasted")
        assert pasted.status_code == 200 and pasted.json()["pasted_by_name"] == "Pat Admin"
        assert client.get(f"/work-orders/{order.id}").json()["smr_block"]["pasted_at"] is not None

        tiles = client.get("/work-orders/smr", params={"has_lines": "true", "block_stale_or_unpasted": "true"}).json()
        assert order.number not in [t["number"] for t in tiles["tiles"]]
        assert order.number in [t["number"] for t in client.get("/work-orders/smr", params={"has_lines": "true"}).json()["tiles"]]

        # The work description (user 2026-11-10) is saved by Generate and printed in the block.
        described = client.post(f"/work-orders/smr/{order.id}/block", json={"description": " Patched drywall. "})
        assert "WORK DESCRIPTION\nPatched drywall.\n" in described.json()["text"]
        assert client.get(f"/work-orders/{order.id}").json()["smr_description"] == "Patched drywall."


def test_regenerate_all_and_its_undo_over_http(db):
    # User 2026-11-11: one button re-prices every block; Undo takes the run back.
    admin = _user(db)
    first, second = _smr_order(db, admin), _smr_order(db, admin)
    with _Client(db, admin) as client:
        for order in (first, second):
            assert client.post(f"/work-orders/smr/{order.id}/lines", json=LINE).status_code == 200
        run = client.post("/work-orders/smr/blocks/regenerate")
        assert run.status_code == 200 and run.json()["count"] >= 2, run.text
        assert client.get("/work-orders/smr").json()["regenerated_at"] is not None
        block = client.get(f"/work-orders/{first.id}").json()["smr_block"]
        assert block["version"] == 1 and block["pasted_at"] is None and "\nBelfor ST " in block["text"]

        undone = client.delete("/work-orders/smr/blocks/regenerate")
        assert undone.status_code == 200 and undone.json()["count"] == run.json()["count"]
        assert client.get(f"/work-orders/{first.id}").json()["smr_block"] is None
    with _Client(db, _user(db, "supervisor")) as client:
        assert client.post("/work-orders/smr/blocks/regenerate").status_code == 403
        assert client.delete("/work-orders/smr/blocks/regenerate").status_code == 403


def test_patch_edits_dates_and_soft_removes_with_domain_errors_as_400_and_404(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    with _Client(db, admin) as client:
        line = client.post(f"/work-orders/smr/{order.id}/lines",
                           json={**LINE, "work_date": None, "status": "excluded", "exclusion_ground": "undated"}).json()
        dated = client.patch(f"/work-orders/smr/lines/{line['id']}", json={"work_date": "2026-06-03", "reason": "date found"})
        assert dated.status_code == 200 and (dated.json()["status"], dated.json()["week"]) == ("charged", 2)

        blank = client.patch(f"/work-orders/smr/lines/{line['id']}", json={"note": "x", "reason": ""})
        assert blank.status_code == 400 and "reason" in blank.json()["detail"]
        missing = client.patch(f"/work-orders/smr/lines/{uuid.uuid4()}", json={"note": "x", "reason": "y"})
        assert missing.status_code == 404

        removed = client.patch(f"/work-orders/smr/lines/{line['id']}",
                               json={"status": "excluded", "exclusion_ground": "removed", "reason": "double keyed"})
        assert removed.status_code == 200 and removed.json()["exclusion_ground"] == "removed"
        assert [h["field"] for h in removed.json()["history"]][-1] == "deleted"


def test_workers_search_add_and_owner_only_merge(db):
    admin, owner, tech = _user(db), _user(db, "owner"), _user(db, "technician")
    name = f"Trinton {uuid.uuid4().hex[:6]}"
    with _Client(db, admin) as client:
        added = client.post("/work-orders/smr/workers", json={"display_name": name, "vendor": "XXL Construction", "alias": "Trint"})
        assert added.status_code == 200 and added.json()["aliases"] == ["Trint"]
        dup = client.post("/work-orders/smr/workers", json={"display_name": name + " dup", "vendor": "XXL Construction"}).json()
        found = client.get("/work-orders/smr/workers", params={"q": name[:12]}).json()
        assert {w["id"] for w in found} >= {added.json()["id"], dup["id"]}
        assert client.post(f"/work-orders/smr/workers/{dup['id']}/merge", json={"into_id": added.json()["id"], "reason": "same"}).status_code == 403
    with _Client(db, owner) as client:
        merged = client.post(f"/work-orders/smr/workers/{dup['id']}/merge", json={"into_id": added.json()["id"], "reason": "same"})
        assert merged.status_code == 200 and name + " dup" in merged.json()["aliases"]
    with _Client(db, tech) as client:
        assert client.get("/work-orders/smr/workers", params={"q": "x"}).status_code == 403
    with _Client(db, None) as client:
        assert client.get("/work-orders/smr/hours").status_code == 401


def test_owner_imports_the_paper_with_the_breakdown_and_reads_the_hours(db):
    owner = _user(db, "owner")
    known = _smr_order(db, owner)
    missing = f"SMR-{uuid.uuid4().hex[:8]}"
    readings = _csv(READING_COLUMNS, [
        {"reading_id": "R1", "wo": known.number, "printing_no": "1", "work_date": "06/20/2026", "hours_as_read": "2.0", "raw_note": "n"},
        {"reading_id": "R2", "wo": missing, "printing_no": "1", "work_date": "06/27/2026", "hours_as_read": "3.0", "raw_note": "n"},
    ])
    lines = _csv(LINE_COLUMNS, [
        {"line_id": "L1", "reading_id": "R1", "wo": known.number, "work_date": "06/20/2026", "vendor": "Belfor", "headcount": "1",
         "hours_each": "2.0", "kind": "field", "status": "charged"},
        {"line_id": "L2", "reading_id": "R2", "wo": missing, "work_date": "06/27/2026", "vendor": "Green Choice", "worker": "Rye",
         "headcount": "1", "hours_each": "3.0", "kind": "field", "status": "charged", "reason_code": "accurate"},
    ])
    breakdown = ("WO#,Unit#,Closed Date,Labor Type,BELFOR HRS,Add HRS,Duplicate HRS,Hours,Labor $,OT Hours,OT $,Total Material Cost,Total L&M,\r\n"
                 f"{missing},Young Hall 108,05/21/2026,SL,,,,1,62.50,,0,9.38,71.88,\r\n").encode()
    files = {"readings": ("paper_readings.csv", readings, "text/csv"), "lines": ("paper_lines.csv", lines, "text/csv"),
             "breakdown": ("breakdown.csv", breakdown, "text/csv")}
    with _Client(db, _user(db)) as client:
        assert client.post("/work-orders/smr/import-paper", files=files).status_code == 403
    with _Client(db, owner) as client:
        without = client.post("/work-orders/smr/import-paper", files={k: v for k, v in files.items() if k != "breakdown"})
        assert without.status_code == 400 and missing in without.json()["detail"]

        result = client.post("/work-orders/smr/import-paper", files=files)
        assert result.status_code == 200, result.text
        body = result.json()
        assert (body["orders"], body["readings"], body["lines"], body["workers_created"], body["created_orders"]) == (2, 2, 2, 1, [missing])
        assert body["charged_hours"] == "5.0"

        hours = client.get("/work-orders/smr/hours").json()
        assert any(r["group"] == "worker" and r["name"] == "Rye" and r["week"] == 5 and r["charged_hours"] == "3.0" for r in hours["rows"])
        csv_out = client.get("/work-orders/smr/hours.csv")
        assert csv_out.status_code == 200 and csv_out.headers["content-type"].startswith("text/csv")
        assert "Rye,Green Choice,5,Week 5,3.0,0,1" in csv_out.text
