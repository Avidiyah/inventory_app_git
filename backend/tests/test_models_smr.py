"""Schema-level tests for the SMR27 audit columns (spec
docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md): the two
work-order columns and the nullable labor technician that represents an
anonymous Skilled Technician line."""

from __future__ import annotations

import uuid
from datetime import date, datetime, timezone
from decimal import Decimal

import pytest
from sqlalchemy.exc import IntegrityError

from app.domain import work_orders_smr_lines as rules
from app.domain.work_orders_smr_lines import WEEK1_PLACEMENT_BASIS
from app.models import (
    SmrCorrectionBlock,
    SmrLaborLine,
    SmrLineEdit,
    SmrPaperReading,
    SmrWorker,
    User,
    WorkOrder,
    WorkOrderLabor,
)


def test_smr_columns_round_trip(db):
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", role="owner")
    db.add(user)
    db.flush()
    now = datetime.now(timezone.utc)
    order = WorkOrder(
        number=f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=user.id,
        smr_imported_at=now,
        smr_baseline={"a": 1},
        smr_target={"hours": "1.5"},
    )
    db.add(order)
    db.flush()
    db.add(WorkOrderLabor(work_order_id=order.id, technician_id=None, minutes=30))
    db.flush()
    db.expire_all()

    reloaded = db.query(WorkOrder).filter(WorkOrder.id == order.id).one()
    assert reloaded.smr_imported_at == now
    assert reloaded.smr_baseline == {"a": 1}
    assert reloaded.smr_target == {"hours": "1.5"}
    assert [e.technician_id for e in reloaded.labor_entries] == [None]
    assert reloaded.labor_entries[0].technician is None


def test_paper_check_survives_deleting_the_checker(db):
    """Spec 2026-10-27-smr-paper-check: the who nulls out, the when stays."""
    owner = User(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", role="owner")
    checker = User(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", role="technician")
    db.add_all([owner, checker])
    db.flush()
    now = datetime.now(timezone.utc)
    order = WorkOrder(
        number=f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=owner.id,
        smr_imported_at=now,
        smr_paper_checked_at=now,
        smr_paper_checked_by_id=checker.id,
    )
    db.add(order)
    db.flush()
    db.delete(checker)
    db.flush()
    db.expire_all()

    reloaded = db.query(WorkOrder).filter(WorkOrder.id == order.id).one()
    assert reloaded.smr_paper_checked_at == now
    assert reloaded.smr_paper_checked_by_id is None


# --- paper corrections (spec 2026-11-04) ------------------------------------

def _user(db, role="owner"):
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", password_hash="x", role=role)
    db.add(user)
    db.flush()
    return user


def _smr_order(db, owner):
    order = WorkOrder(number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=owner.id,
                      smr_imported_at=datetime.now(timezone.utc))
    db.add(order)
    db.flush()
    return order


def _line(order, **overrides):
    fields = dict(work_order_id=order.id, work_date=date(2026, 6, 20), vendor="Belfor", headcount=1,
                  hours_each=Decimal("1.5"), kind="field", reason_code="accurate", status="charged")
    fields.update(overrides)
    return SmrLaborLine(**fields)


def _refused(db, row):
    db.add(row)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()


def test_paper_correction_tables_round_trip(db):
    owner, linked = _user(db), _user(db, "technician")
    order = _smr_order(db, owner)
    worker = SmrWorker(display_name="Trinton Smith", vendor="XXL Construction", aliases=["Trint"], user_id=linked.id)
    db.add(worker)
    db.flush()
    reading = SmrPaperReading(work_order_id=order.id, printing_no=1, work_date=date(2026, 6, 20),
                              hours_as_read=Decimal("3.0"), raw_note="2 XXL x 1.5", reviewer="JM",
                              source="paper_review.csv row 12, import abc123", created_by_id=owner.id)
    db.add(reading)
    db.flush()
    line = _line(order, reading_id=reading.id, worker_id=worker.id, import_key=f"L-{uuid.uuid4().hex[:6]}",
                 week=4, kind="assessment, audit", headcount=2, created_by_id=owner.id)
    db.add(line)
    db.flush()
    db.add(SmrLineEdit(line_id=line.id, edited_by_id=owner.id, field="created", new_value="{}", reason="import abc123"))
    db.add(SmrCorrectionBlock(work_order_id=order.id, version=1, text="SMR27 LABOR CORRECTION v1",
                              generated_by_id=owner.id, lines_digest="d" * 64))
    db.flush()
    db.expire_all()

    reloaded = db.query(WorkOrder).filter(WorkOrder.id == order.id).one()
    assert [r.printing_no for r in reloaded.smr_readings] == [1]
    assert reloaded.smr_readings[0].hours_as_read == Decimal("3.0")
    only = reloaded.smr_lines[0]
    assert only.worker.display_name == "Trinton Smith" and only.worker.aliases == ["Trint"]
    assert only.worker.user_id == linked.id
    assert only.reading is reloaded.smr_readings[0]
    assert (only.kind, only.date_basis, only.week, only.headcount) == ("assessment, audit", "paper", 4, 2)
    assert [(e.field, e.reason) for e in only.edits] == [("created", "import abc123")]
    assert reloaded.smr_blocks[0].version == 1 and reloaded.smr_blocks[0].pasted_at is None


def test_a_charged_line_needs_a_date_unless_it_is_a_week1_placement(db):
    order = _smr_order(db, _user(db))
    _refused(db, _line(order, work_date=None))

    # Decision 13: the placement basis is the one exception, with week 1.
    order = _smr_order(db, _user(db))
    db.add(_line(order, work_date=None, date_basis=WEEK1_PLACEMENT_BASIS, week=1))
    db.flush()
    assert db.query(SmrLaborLine).filter(SmrLaborLine.work_order_id == order.id).one().week == 1


def test_a_week_placement_charges_with_its_week_and_no_date(db):
    # Decision 13 generalised (user 2026-11-06): the weekly-report basis
    # charges with a blank day as long as the line carries its week.
    order = _smr_order(db, _user(db))
    _refused(db, _line(order, work_date=None, date_basis=rules.WEEK_PLACEMENT_BASIS, week=None))

    order = _smr_order(db, _user(db))
    db.add(_line(order, work_date=None, date_basis=rules.WEEK_PLACEMENT_BASIS, week=3, hours_each=Decimal("0.5")))
    db.flush()
    assert db.query(SmrLaborLine).filter(SmrLaborLine.work_order_id == order.id).one().week == 3


def test_hours_off_the_half_hour_step_are_refused(db):
    _refused(db, _line(_smr_order(db, _user(db)), hours_each=Decimal("1.3")))


def test_an_excluded_line_needs_a_ground(db):
    _refused(db, _line(_smr_order(db, _user(db)), status="excluded", exclusion_ground=None))


def test_headcount_below_one_and_unknown_status_are_refused(db):
    _refused(db, _line(_smr_order(db, _user(db)), headcount=0))
    _refused(db, _line(_smr_order(db, _user(db)), status="pending"))


def test_one_reading_per_printing_per_order(db):
    order = _smr_order(db, _user(db))
    db.add(SmrPaperReading(work_order_id=order.id, printing_no=2, raw_note="a"))
    db.flush()
    _refused(db, SmrPaperReading(work_order_id=order.id, printing_no=2, raw_note="b"))


def test_deleting_a_linked_user_nulls_the_worker_link(db):
    linked = _user(db, "technician")
    worker = SmrWorker(display_name=f"W {uuid.uuid4().hex[:6]}", vendor="Belfor", user_id=linked.id)
    db.add(worker)
    db.flush()
    db.delete(linked)
    db.flush()
    db.expire_all()

    assert db.query(SmrWorker).filter(SmrWorker.id == worker.id).one().user_id is None


def test_an_editor_with_history_cannot_be_deleted(db):
    # Same as `attendance_punch_edits`: the who on a history row is a plain FK.
    owner, editor = _user(db), _user(db, "admin")
    line = _line(_smr_order(db, owner))
    db.add(line)
    db.flush()
    db.add(SmrLineEdit(line_id=line.id, edited_by_id=editor.id, field="note", old_value=None, new_value="x", reason="why"))
    db.flush()
    db.delete(editor)
    with pytest.raises(IntegrityError):
        db.flush()
    db.rollback()
