"""`services.work_orders_smr_lines` (spec 2026-11-04): every write on a
paper-correction line leaves a history row with a reason, removal is soft,
dating an undated line charges it, workers merge with history, blocks
version and go stale, and the Hours table reads lines only."""

from __future__ import annotations

import json
import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest

from app.domain import work_orders as wo
from app.domain.errors import WorkOrderNotFoundError, WorkOrderStateError
from app.models import SmrLaborLine, SmrLineEdit, User
from app.schemas.work_orders_smr_lines import SmrLineEditIn, SmrLineIn, SmrReadingEditIn, SmrReadingIn, SmrWorkerIn
from app.services import auth
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service
from app.services import work_orders_smr_lines as svc


def _user(db, role="admin"):
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", first_name="Pat", last_name=role.title(),
                password_hash=auth.hash_password("x"), role=role)
    db.add(user)
    db.flush()
    return user


def _smr_order(db, owner):
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    sheet = ("WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
             f"{number},c,SMR27 - Belfor,05/15/2026,05/21/2026,a,Closed,\"B:1,U 1,x\"\r\n").encode()
    smr_service.import_smr(db, csv_bytes=sheet, user=owner)
    return wos.find_by_number(db, number)


def _line_in(**overrides):
    fields = dict(vendor="Belfor", hours_each=Decimal("2.0"), reason_code="accurate",
                  work_date=date(2026, 6, 20), reason="keyed from the paper")
    fields.update(overrides)
    return SmrLineIn(**fields)


def _edits(db, line_id):
    return db.query(SmrLineEdit).filter(SmrLineEdit.line_id == line_id).order_by(SmrLineEdit.edited_at).all()


# --- readings ------------------------------------------------------------

def test_add_reading_and_refuse_a_second_of_the_same_printing(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    reading = svc.add_reading(db, work_order_id=order.id,
                              payload=SmrReadingIn(printing_no=1, work_date=date(2026, 6, 20), hours_as_read=Decimal("3.5"),
                                                   raw_note=" paper names Pat 3.5 h "), user=admin)
    assert (reading.printing_no, reading.hours_as_read, reading.raw_note) == (1, Decimal("3.5"), "paper names Pat 3.5 h")
    assert "app" in reading.source
    with pytest.raises(WorkOrderStateError, match="rinting 1"):
        svc.add_reading(db, work_order_id=order.id, payload=SmrReadingIn(printing_no=1), user=admin)


def test_edit_reading_changes_fields_refuses_a_taken_printing_and_a_no_op(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    first = svc.add_reading(db, work_order_id=order.id, payload=SmrReadingIn(printing_no=1, raw_note="x"), user=admin)
    second = svc.add_reading(db, work_order_id=order.id, payload=SmrReadingIn(printing_no=2), user=admin)

    out = svc.edit_reading(db, reading_id=first.id, user=admin, payload=SmrReadingEditIn(
        work_date=date(2026, 6, 20), hours_as_read=Decimal("2.5"), raw_note="  Pat 2.5 h  "))
    assert (out.work_date, out.hours_as_read, out.raw_note) == (date(2026, 6, 20), Decimal("2.5"), "Pat 2.5 h")
    assert out.source.endswith("edited in the app by " + admin.full_name)
    assert out.printing_no == 1

    with pytest.raises(WorkOrderStateError):
        svc.edit_reading(db, reading_id=first.id, user=admin, payload=SmrReadingEditIn(printing_no=2))
    with pytest.raises(WorkOrderStateError):
        svc.edit_reading(db, reading_id=second.id, user=admin, payload=SmrReadingEditIn(printing_no=None))
    with pytest.raises(WorkOrderStateError):  # no-op
        svc.edit_reading(db, reading_id=first.id, user=admin, payload=SmrReadingEditIn(raw_note="Pat 2.5 h"))
    with pytest.raises(WorkOrderNotFoundError):
        svc.edit_reading(db, reading_id=uuid.uuid4(), user=admin, payload=SmrReadingEditIn(raw_note="y"))


def test_dating_a_reading_dates_and_charges_its_undated_lines_only(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    reading = svc.add_reading(db, work_order_id=order.id, payload=SmrReadingIn(printing_no=1), user=admin)
    other = svc.add_reading(db, work_order_id=order.id, payload=SmrReadingIn(printing_no=2), user=admin)
    waiting = svc.add_line(db, work_order_id=order.id, user=admin, payload=_line_in(
        reading_id=reading.id, work_date=None, status="excluded", exclusion_ground="undated"))
    placed = svc.add_line(db, work_order_id=order.id, user=admin, payload=_line_in(
        reading_id=reading.id, work_date=None, date_basis="Week 1 placement (crew sheets, Supplement)"))
    elsewhere = svc.add_line(db, work_order_id=order.id, user=admin, payload=_line_in(
        reading_id=other.id, work_date=None, status="excluded", exclusion_ground="undated"))

    svc.edit_reading(db, reading_id=reading.id, user=admin, payload=SmrReadingEditIn(work_date=date(2026, 6, 27)))

    db.expire_all()
    dated = db.get(SmrLaborLine, waiting.id)
    assert (dated.work_date, dated.week, dated.status, dated.exclusion_ground) == (date(2026, 6, 27), 5, "charged", None)
    assert _edits(db, waiting.id)[-1].reason == "dated with printing 1"
    assert db.get(SmrLaborLine, placed.id).work_date is None and db.get(SmrLaborLine, placed.id).week == 1
    assert db.get(SmrLaborLine, elsewhere.id).work_date is None


def test_writes_refuse_a_live_order_and_an_unknown_one(db):
    admin = _user(db)
    live = wos.get_or_create_work_order(db, number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=admin.id)
    with pytest.raises(WorkOrderStateError, match="SMR"):
        svc.add_reading(db, work_order_id=live.id, payload=SmrReadingIn(printing_no=1), user=admin)
    with pytest.raises(WorkOrderStateError, match="SMR"):
        svc.add_line(db, work_order_id=live.id, payload=_line_in(), user=admin)
    with pytest.raises(WorkOrderNotFoundError):
        svc.generate_block(db, work_order_id=uuid.uuid4(), user=admin)


# --- lines ---------------------------------------------------------------

def test_add_line_writes_the_line_and_one_created_row_carrying_the_reason(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    line = svc.add_line(db, work_order_id=order.id, payload=_line_in(headcount=2, kind="assessment,audit"), user=admin)
    assert (line.hours, line.week, line.kind, line.status) == (Decimal("4.0"), 4, "assessment, audit", "charged")
    edits = _edits(db, line.id)
    assert [(e.field, e.reason, e.edited_by_id) for e in edits] == [("created", "keyed from the paper", admin.id)]
    assert json.loads(edits[0].new_value)["vendor"] == "Belfor" and edits[0].old_value is None
    assert line.history[0].field == "created"


def test_add_line_refuses_a_blank_reason_a_bad_state_and_a_foreign_reading(db):
    admin = _user(db)
    order, other = _smr_order(db, admin), _smr_order(db, admin)
    with pytest.raises(WorkOrderStateError, match="reason"):
        svc.add_line(db, work_order_id=order.id, payload=_line_in(reason="  "), user=admin)
    with pytest.raises(WorkOrderStateError, match="work date"):
        svc.add_line(db, work_order_id=order.id, payload=_line_in(work_date=None), user=admin)
    foreign = svc.add_reading(db, work_order_id=other.id, payload=SmrReadingIn(printing_no=1), user=admin)
    with pytest.raises(WorkOrderStateError, match="reading"):
        svc.add_line(db, work_order_id=order.id, payload=_line_in(reading_id=foreign.id), user=admin)
    assert wos.find_by_number(db, order.number).smr_lines == []


def test_edit_line_writes_one_history_row_per_changed_field(db):
    admin, editor = _user(db), _user(db, "owner")
    order = _smr_order(db, admin)
    line = svc.add_line(db, work_order_id=order.id, payload=_line_in(), user=admin)
    edited = svc.edit_line(db, line_id=line.id, payload=SmrLineEditIn(hours_each=Decimal("3.5"), note="re-read", reason="re-read the paper"),
                           user=editor)
    assert (edited.hours_each, edited.note, edited.hours) == (Decimal("3.5"), "re-read", Decimal("3.5"))
    rows = [(e.field, e.old_value, e.new_value, e.reason) for e in _edits(db, line.id)[1:]]
    assert sorted(rows) == [("hours_each", "2.0", "3.5", "re-read the paper"), ("note", None, "re-read", "re-read the paper")]
    assert edited.history[-1].edited_by_name == "Pat Owner"


def test_edit_line_refuses_a_no_op_and_a_blank_reason(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    line = svc.add_line(db, work_order_id=order.id, payload=_line_in(), user=admin)
    with pytest.raises(WorkOrderStateError, match="reason"):
        svc.edit_line(db, line_id=line.id, payload=SmrLineEditIn(note="x", reason=""), user=admin)
    with pytest.raises(WorkOrderStateError, match="othing"):
        svc.edit_line(db, line_id=line.id, payload=SmrLineEditIn(reason="why"), user=admin)
    with pytest.raises(WorkOrderStateError, match="othing"):
        svc.edit_line(db, line_id=line.id, payload=SmrLineEditIn(hours_each=Decimal("2.0"), reason="same"), user=admin)
    assert len(_edits(db, line.id)) == 1


def test_dating_an_undated_line_charges_it_with_history(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    undated = svc.add_line(db, work_order_id=order.id,
                           payload=_line_in(work_date=None, status="excluded", exclusion_ground="undated"), user=admin)
    dated = svc.edit_line(db, line_id=undated.id, payload=SmrLineEditIn(work_date=date(2026, 6, 3), reason="date found on the sheet"),
                          user=admin)
    assert (dated.status, dated.exclusion_ground, dated.week) == ("charged", None, 2)
    assert {e.field for e in _edits(db, undated.id)[1:]} == {"work_date", "status", "exclusion_ground"}


def test_removing_a_line_is_soft_and_writes_one_deleted_row(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    line = svc.add_line(db, work_order_id=order.id, payload=_line_in(), user=admin)
    removed = svc.edit_line(db, line_id=line.id, payload=SmrLineEditIn(status="excluded", exclusion_ground="removed", reason="double keyed"),
                            user=admin)
    assert (removed.status, removed.exclusion_ground) == ("excluded", "removed")
    rows = _edits(db, line.id)[1:]
    assert [(e.field, e.new_value, e.reason) for e in rows] == [("deleted", None, "double keyed")]
    assert json.loads(rows[0].old_value)["status"] == "charged"
    assert [l.id for l in wos.find_by_number(db, order.number).smr_lines] == [line.id]


# --- workers -------------------------------------------------------------

def test_search_workers_by_name_or_alias_and_skip_archived(db):
    trint = svc.add_worker(db, payload=SmrWorkerIn(display_name="Trinton Smith", vendor="XXL Construction", alias="Trint"))
    gone = svc.add_worker(db, payload=SmrWorkerIn(display_name=f"Gone {uuid.uuid4().hex[:6]}", vendor="Belfor"))
    svc.merge_workers(db, worker_id=gone.id, into_id=trint.id, reason="same person", user=_user(db, "owner"))
    assert trint.id in {w.id for w in svc.search_workers(db, "TRINT")}
    assert trint.id in {w.id for w in svc.search_workers(db, "smith")}
    assert trint.id not in {w.id for w in svc.search_workers(db, "nobody-by-this-name")}
    assert gone.id not in {w.id for w in svc.search_workers(db, "")}


def test_add_worker_appends_an_alias_to_the_existing_name_and_vendor(db):
    name = f"Rye {uuid.uuid4().hex[:6]}"
    first = svc.add_worker(db, payload=SmrWorkerIn(display_name=name, vendor="Green Choice"))
    again = svc.add_worker(db, payload=SmrWorkerIn(display_name=name, vendor="Green Choice", alias="Ryeguy"))
    third = svc.add_worker(db, payload=SmrWorkerIn(display_name=name, vendor="Green Choice", alias="Ryeguy"))
    assert first.id == again.id == third.id and third.aliases == ["Ryeguy"]
    with pytest.raises(WorkOrderStateError, match="vendor"):
        svc.add_worker(db, payload=SmrWorkerIn(display_name="X", vendor="Acme"))


def test_merge_workers_repoints_lines_with_history_and_archives_the_duplicate(db):
    admin, owner = _user(db), _user(db, "owner")
    order = _smr_order(db, admin)
    keep = svc.add_worker(db, payload=SmrWorkerIn(display_name=f"Chris Romero {uuid.uuid4().hex[:4]}", vendor="XXL Construction"))
    dup = svc.add_worker(db, payload=SmrWorkerIn(display_name=f"Romero {uuid.uuid4().hex[:4]}", vendor="XXL Construction", alias="C.R."))
    line = svc.add_line(db, work_order_id=order.id, payload=_line_in(vendor="XXL Construction", worker_id=dup.id), user=admin)

    merged = svc.merge_workers(db, worker_id=dup.id, into_id=keep.id, reason="same person", user=owner)

    assert merged.id == keep.id and dup.display_name in merged.aliases and "C.R." in merged.aliases
    reloaded = wos.find_by_number(db, order.number).smr_lines[0]
    assert reloaded.worker_id == keep.id
    assert [(e.field, e.old_value, e.new_value) for e in _edits(db, line.id)[1:]] == [("worker_id", str(dup.id), str(keep.id))]
    found = {w.id for w in svc.search_workers(db, dup.display_name)}  # the folded alias still finds the keeper
    assert keep.id in found and dup.id not in found
    with pytest.raises(WorkOrderStateError, match="orker"):
        svc.add_line(db, work_order_id=order.id, payload=_line_in(vendor="XXL Construction", worker_id=dup.id), user=admin)
    with pytest.raises(WorkOrderStateError, match="vendor"):
        svc.add_line(db, work_order_id=order.id, payload=_line_in(vendor="Belfor", worker_id=keep.id), user=admin)


# --- blocks --------------------------------------------------------------

def test_generate_block_versions_and_goes_stale_when_lines_change(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    assert svc.latest_block(order) is None
    line = svc.add_line(db, work_order_id=order.id, payload=_line_in(), user=admin)

    first = svc.generate_block(db, work_order_id=order.id, user=admin)
    today = datetime.now(timezone.utc).astimezone(wo.NOTE_TIMEZONE).strftime("%m/%d/%y")
    assert first.version == 1 and first.stale is False and first.generated_by_name == "Pat Admin"
    assert first.text.startswith("SMR27 LABOR CORRECTION v1") and today in first.text.split("\n")[0]
    assert "06/20 Belfor" in first.text and "2.0 h" in first.text
    assert svc.latest_block(wos.find_by_number(db, order.number)).stale is False

    svc.edit_line(db, line_id=line.id, payload=SmrLineEditIn(hours_each=Decimal("1.0"), reason="re-read"), user=admin)
    assert svc.latest_block(wos.find_by_number(db, order.number)).stale is True

    second = svc.generate_block(db, work_order_id=order.id, user=admin)
    assert second.version == 2 and second.stale is False
    assert svc.latest_block(wos.find_by_number(db, order.number), include_price=False).text is None


def test_mark_pasted_stamps_once(db):
    admin, other = _user(db), _user(db, "owner")
    order = _smr_order(db, admin)
    svc.add_line(db, work_order_id=order.id, payload=_line_in(), user=admin)
    block = svc.generate_block(db, work_order_id=order.id, user=admin)

    pasted = svc.mark_pasted(db, block_id=block.id, user=admin)
    again = svc.mark_pasted(db, block_id=block.id, user=other)

    assert pasted.pasted_at is not None and pasted.pasted_by_name == "Pat Admin"
    assert (again.pasted_at, again.pasted_by_name) == (pasted.pasted_at, "Pat Admin")
    with pytest.raises(WorkOrderNotFoundError):
        svc.mark_pasted(db, block_id=uuid.uuid4(), user=admin)


# --- hours ---------------------------------------------------------------

def test_a_keyed_name_links_a_known_worker_or_alias_and_stays_unlinked_otherwise(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    name = f"Trinton {uuid.uuid4().hex[:6]}"
    worker = svc.add_worker(db, payload=SmrWorkerIn(display_name=name, vendor="XXL Construction"))
    svc.add_worker(db, payload=SmrWorkerIn(display_name=name, vendor="XXL Construction", alias="T. Smith"))

    by_name = svc.add_line(db, work_order_id=order.id,
                           payload=_line_in(vendor="XXL Construction", alias_on_paper=name.upper()), user=admin)
    by_alias = svc.add_line(db, work_order_id=order.id,
                            payload=_line_in(vendor="XXL Construction", alias_on_paper="t. smith"), user=admin)
    other_vendor = svc.add_line(db, work_order_id=order.id,
                                payload=_line_in(vendor="Belfor", alias_on_paper=name), user=admin)
    unknown = svc.add_line(db, work_order_id=order.id,
                           payload=_line_in(vendor="XXL Construction", alias_on_paper="Nobody Known"), user=admin)
    assert (by_name.worker_id, by_alias.worker_id) == (worker.id, worker.id)
    assert other_vendor.worker_id is None and unknown.worker_id is None

    # Re-keying the name on an edit re-links; a name that matches nothing unlinks.
    edited = svc.edit_line(db, line_id=unknown.id, payload=SmrLineEditIn(alias_on_paper="T. Smith", reason="misread"), user=admin)
    assert edited.worker_id == worker.id
    edited = svc.edit_line(db, line_id=edited.id, payload=SmrLineEditIn(alias_on_paper="Nobody", reason="misread"), user=admin)
    assert edited.worker_id is None

    # The hours table groups an unlinked keyed name under that name.
    cells = {(r.group, r.name, r.vendor) for r in svc.hours_table(db).rows}
    assert ("worker", "Nobody", "XXL Construction") in cells
    assert ("worker", name, "XXL Construction") in cells


def test_hours_table_groups_worker_and_vendor_by_week_from_lines_only(db):
    admin = _user(db)
    order = _smr_order(db, admin)
    wos.add_work_order_labor(db, order.id, user=admin, technician_id=None, minutes=600)  # legacy, never in the table
    name = f"Jesus {uuid.uuid4().hex[:6]}"
    worker = svc.add_worker(db, payload=SmrWorkerIn(display_name=name, vendor="XXL Construction"))
    svc.add_line(db, work_order_id=order.id, payload=_line_in(vendor="XXL Construction", worker_id=worker.id), user=admin)
    svc.add_line(db, work_order_id=order.id,
                 payload=_line_in(vendor="XXL Construction", worker_id=worker.id, work_date=date(2026, 6, 27), hours_each=Decimal("3.0")),
                 user=admin)
    svc.add_line(db, work_order_id=order.id,
                 payload=_line_in(vendor="Green Choice", headcount=4, hours_each=Decimal("1.5"), work_date=None,
                                  status="excluded", exclusion_ground="undated"), user=admin)

    table = svc.hours_table(db)

    cells = {(r.group, r.name, r.vendor, r.week): (r.charged_hours, r.excluded_hours, r.lines) for r in table.rows}
    assert cells[("worker", name, "XXL Construction", 4)] == (Decimal("2.0"), Decimal(0), 1)
    assert cells[("worker", name, "XXL Construction", 5)] == (Decimal("3.0"), Decimal(0), 1)
    assert cells[("worker", "Skilled Technician", "Green Choice", None)][1] >= Decimal("6.0")
    assert cells[("vendor", "XXL Construction", "XXL Construction", 5)][0] >= Decimal("3.0")
    assert {4, 5, None} <= set(table.weeks) and table.weeks[-1] is None
    assert next(r for r in table.rows if r.week == 5).week_label == "Week 5"
    assert table.charged_hours >= Decimal("5.0") and table.excluded_hours >= Decimal("6.0")

    csv_text = svc.hours_csv(db).decode("utf-8")
    assert csv_text.splitlines()[0] == "group,name,vendor,week,week_label,charged_hours,excluded_hours,lines"
    assert f"worker,{name},XXL Construction,5,Week 5,3.0,0,1" in csv_text
