"""`services.work_orders_smr_import.import_paper` (spec 2026-11-04, Import):
every row parsed and tie-checked before the first write, one commit or
nothing, idempotent by `(order, printing)` and `line_id`, changed rows
refused and named, the eight reviewed orders the app never had created
from their Breakdown row, the paper-check mark set once."""

from __future__ import annotations

import csv
import io
import uuid
from decimal import Decimal

import pytest

from app.domain import roles
from app.domain.errors import WorkOrderStateError
from app.domain import work_orders_smr_lines as lines_rules
from app.models import SmrLaborLine, SmrLineEdit, SmrPaperReading, SmrWorker, User
from app.services import auth
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service
from app.services import work_orders_smr_import as smr_import
from app.services.work_orders_smr_import import import_paper

READING_COLUMNS = ["reading_id", "wo", "printing_no", "work_date", "hours_as_read", "raw_note", "reviewer", "csv_row"]
LINE_COLUMNS = ["line_id", "reading_id", "wo", "work_date", "date_basis", "week", "vendor", "worker", "alias_on_paper",
                "headcount", "hours_each", "kind", "status", "exclusion_ground", "reason_code", "note"]
BREAKDOWN_COLUMNS = ["WO#", "Unit#", "Closed Date", "Labor Type", "BELFOR HRS", "Add HRS", "Duplicate HRS", "Hours",
                     "Labor $", "OT Hours", "OT $", "Total Material Cost", "Total L&M", ""]


def _csv(columns, rows):
    out = io.StringIO()
    writer = csv.DictWriter(out, fieldnames=columns, lineterminator="\r\n")
    writer.writeheader()
    for row in rows:
        writer.writerow({column: row.get(column, "") for column in columns})
    return out.getvalue().encode("utf-8")


def _user(db, role=roles.ROLE_OWNER):
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", first_name="Pat", last_name="Owner",
                password_hash=auth.hash_password("x"), role=role)
    db.add(user)
    db.flush()
    return user


def _smr_numbers(db, owner, count):
    numbers = [f"SMR-{uuid.uuid4().hex[:8]}" for _ in range(count)]
    head = "WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
    rows = "".join(f"{n},c,SMR27 - Belfor,05/15/2026,05/21/2026,a,Closed,\"B:1,U 1,x\"\r\n" for n in numbers)
    smr_service.import_smr(db, csv_bytes=(head + rows).encode(), user=owner)
    return numbers


def _reading(reading_id, wo, printing=1, work_date="06/20/2026", hours="6.0", note="paper names Pat 6 h", csv_row="7"):
    return {"reading_id": reading_id, "wo": wo, "printing_no": str(printing), "work_date": work_date,
            "hours_as_read": hours, "raw_note": note, "reviewer": "JM", "csv_row": csv_row}


def _line(line_id, reading_id, wo, hours="6.0", **overrides):
    row = {"line_id": line_id, "reading_id": reading_id, "wo": wo, "work_date": "06/20/2026", "date_basis": "paper",
           "vendor": "XXL Construction", "worker": "Trinton Smith", "alias_on_paper": "Trint", "headcount": "1",
           "hours_each": hours, "kind": "field", "status": "charged", "exclusion_ground": "", "reason_code": "",
           "note": "paper names Trint 6 h"}
    row.update(overrides)
    return row


def _files(numbers):
    a, b = numbers
    readings = [_reading("R1", a), _reading("R2", a, printing=2, work_date="", hours="", note="re-print, nothing new"),
                _reading("R3", b, hours="7.5")]
    lines = [
        _line("L1", "R1", a),
        _line("L2", "R3", b, hours="3.0", worker="", alias_on_paper="", vendor="Green Choice", headcount="2",
              reason_code="crew_as_one"),
        _line("L3", "R3", b, hours="1.5", worker="", vendor="Green Choice", work_date="", status="excluded",
              exclusion_ground="undated", date_basis=""),
        _line("L4", "R3", b, hours="0.5", vendor="Belfor", worker="", kind="assessment", reason_code="overhead_added"),
    ]
    return _csv(READING_COLUMNS, readings), _csv(LINE_COLUMNS, lines)


def _state(db, numbers):
    orders = [wos.find_by_number(db, n) for n in numbers]
    ids = [o.id for o in orders]
    return (
        db.query(SmrPaperReading).filter(SmrPaperReading.work_order_id.in_(ids)).count(),
        db.query(SmrLaborLine).filter(SmrLaborLine.work_order_id.in_(ids)).count(),
    )


def test_import_writes_readings_lines_workers_history_and_the_paper_check(db):
    owner = _user(db)
    numbers = _smr_numbers(db, owner, 2)
    readings, lines = _files(numbers)

    result = import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)

    assert (result.orders, result.readings, result.lines, result.workers_created) == (2, 3, 4, 1)
    assert (result.charged_hours, result.excluded_hours) == (Decimal("12.5"), Decimal("1.5"))
    assert result.created_orders == [] and result.run_id.startswith("import ")
    assert _state(db, numbers) == (3, 4)
    a, b = (wos.find_by_number(db, n) for n in numbers)
    assert [r.printing_no for r in a.smr_readings] == [1, 2] and a.smr_readings[0].source.startswith("paper_review.csv row 7, import ")
    trint = next(l for l in a.smr_lines if l.worker is not None)
    assert (trint.worker.display_name, trint.worker.aliases, trint.worker.vendor) == ("Trinton Smith", ["Trint"], "XXL Construction")
    assert trint.reason_code == "as_read" and trint.import_key == "L1" and trint.week == 4
    undated = next(l for l in b.smr_lines if l.status == "excluded")
    assert (undated.exclusion_ground, undated.date_basis, undated.week) == ("undated", "paper", None)
    edits = db.query(SmrLineEdit).filter(SmrLineEdit.line_id.in_([l.id for l in a.smr_lines + b.smr_lines])).all()
    assert len(edits) == 4 and {e.field for e in edits} == {"created"} and {e.reason for e in edits} == {result.run_id}
    assert a.smr_paper_checked_at is not None and a.smr_paper_checked_by_id == owner.id


def test_a_tie_mismatch_aborts_with_nothing_written(db):
    owner = _user(db)
    numbers = _smr_numbers(db, owner, 2)
    readings, _ = _files(numbers)
    lines = _csv(LINE_COLUMNS, [_line("L1", "R1", numbers[0], hours="4.5")])
    before = db.query(SmrWorker).count()

    with pytest.raises(WorkOrderStateError, match=r"Reading R1 \(WO SMR-.*printing 1\): lines total 4.5 h, paper read 6.0 h"):
        import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)

    assert _state(db, numbers) == (0, 0) and db.query(SmrWorker).count() == before
    assert wos.find_by_number(db, numbers[0]).smr_paper_checked_at is None


def test_a_rerun_of_the_same_files_writes_nothing(db):
    owner = _user(db)
    numbers = _smr_numbers(db, owner, 2)
    readings, lines = _files(numbers)
    first = import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)

    again = import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)

    assert (again.readings, again.lines, again.workers_created) == (0, 0, 0)
    assert (again.skipped_readings, again.skipped_lines, again.orders) == (3, 4, 2)
    assert again.run_id == first.run_id and _state(db, numbers) == (3, 4)


def test_a_changed_row_for_an_imported_key_is_refused_and_named(db):
    owner = _user(db)
    numbers = _smr_numbers(db, owner, 2)
    readings, lines = _files(numbers)
    import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)
    a, b = numbers
    changed_lines = _csv(LINE_COLUMNS, [
        _line("L1", "R1", a, hours="5.0"),  # L1 moved to 5.0 h
        _line("L5", "R1", a, hours="1.0", vendor="Belfor", worker=""),  # a new line keeps R1 tied
        _line("L2", "R3", b, hours="3.0", worker="", alias_on_paper="", vendor="Green Choice", headcount="2", reason_code="crew_as_one"),
        _line("L3", "R3", b, hours="1.5", worker="", vendor="Green Choice", work_date="", status="excluded", exclusion_ground="undated"),
        _line("L4", "R3", b, hours="0.5", vendor="Belfor", worker="", kind="assessment", reason_code="overhead_added"),
    ])

    with pytest.raises(WorkOrderStateError, match="Already imported with different values.*line L1"):
        import_paper(db, readings_bytes=readings, lines_bytes=changed_lines, user=owner)

    assert _state(db, numbers) == (3, 4)


def test_a_week_placement_line_imports_with_its_week_and_a_moved_week_is_refused(db):
    # Decision 13 generalised (user 2026-11-06): the weekly-report hours hang
    # on a reading with no hours (the tie check skips it) and carry `week`.
    owner = _user(db)
    a = _smr_numbers(db, owner, 1)[0]
    readings = _csv(READING_COLUMNS, [
        _reading("R1", a),
        _reading("R9", a, printing=9, work_date="", hours="", note="weekly reports: 0.5 h clean-up"),
    ])
    columns = LINE_COLUMNS + ["week"]
    placed = _line("L7", "R9", a, hours="0.5", vendor="Belfor", worker="", alias_on_paper="", work_date="",
                   date_basis=lines_rules.WEEK_PLACEMENT_BASIS, week="3")
    lines = _csv(columns, [_line("L1", "R1", a), placed])

    result = import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)

    assert (result.readings, result.lines, result.charged_hours) == (2, 2, Decimal("6.5"))
    stored = db.query(SmrLaborLine).filter(SmrLaborLine.import_key == "L7").one()
    assert (stored.work_date, stored.week, stored.status) == (None, 3, "charged")

    moved = _csv(columns, [_line("L1", "R1", a), {**placed, "week": "4"}])
    with pytest.raises(WorkOrderStateError, match="Already imported with different values.*line L7"):
        import_paper(db, readings_bytes=readings, lines_bytes=moved, user=owner)


def test_reviewed_orders_the_app_never_had_are_created_from_the_breakdown(db):
    owner = _user(db)
    (known,) = _smr_numbers(db, owner, 1)
    missing = f"SMR-{uuid.uuid4().hex[:8]}"
    readings = _csv(READING_COLUMNS, [_reading("R1", known), _reading("R2", missing, hours="2.0", csv_row="9")])
    lines = _csv(LINE_COLUMNS, [_line("L1", "R1", known), _line("L2", "R2", missing, hours="2.0", vendor="Belfor", worker="")])

    with pytest.raises(WorkOrderStateError, match=f"Not in the app.*{missing}"):
        import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)
    assert wos.find_by_number(db, missing) is None

    breakdown = _csv(BREAKDOWN_COLUMNS, [
        {"WO#": missing, "Unit#": "Young Hall 108", "Closed Date": "05/21/2026", "Labor Type": "SL", "Hours": "1.5",
         "Labor $": "$93.75", "OT $": "0", "Total Material Cost": "$9.38", "Total L&M": "$103.13"},
        {"WO#": "", "Hours": "4455.5"},
    ])
    result = import_paper(db, readings_bytes=readings, lines_bytes=lines, breakdown_bytes=breakdown, user=owner)

    assert result.created_orders == [missing] and (result.orders, result.readings, result.lines) == (2, 2, 2)
    created = wos.find_by_number(db, missing)
    assert created.smr_imported_at is not None and created.service_type == "SMR27 - Belfor"
    assert created.unit_number == "Young Hall 108" and created.smr_target["hours"] == "1.5"
    assert created.smr_target["materials_total"] == "9.38" and created.smr_baseline["totals"]["labor_total"] == "0.00"
    assert created.smr_baseline["source_row"]["CREATOR"] == "created by paper import"
    assert created.smr_readings[0].source.endswith("; created by paper import")
    assert created.smr_paper_checked_at is not None

    ghost = f"SMR-{uuid.uuid4().hex[:8]}"
    with pytest.raises(WorkOrderStateError, match=f"Not in the app or the Breakdown upload: {ghost}"):
        import_paper(
            db, readings_bytes=_csv(READING_COLUMNS, [_reading("R9", ghost, hours="")]),
            lines_bytes=_csv(LINE_COLUMNS, []), breakdown_bytes=breakdown, user=owner,
        )


def test_a_failure_after_creating_a_missing_order_leaves_it_importable(db, monkeypatch):
    # `get_or_create_work_order` commits on its own, so the created shell
    # outlives a failure later in the run. It must carry its SMR mark, or
    # every rerun refuses the number as a live non-SMR order.
    owner = _user(db)
    missing = f"SMR-{uuid.uuid4().hex[:8]}"
    readings = _csv(READING_COLUMNS, [_reading("R2", missing, hours="2.0")])
    lines = _csv(LINE_COLUMNS, [_line("L2", "R2", missing, hours="2.0", vendor="Belfor", worker="")])
    breakdown = _csv(BREAKDOWN_COLUMNS, [{"WO#": missing, "Unit#": "Young Hall 108", "Hours": "1.5", "Labor $": "$93.75",
                                          "Total Material Cost": "$9.38", "Total L&M": "$103.13"}])

    def hiccup(*args, **kwargs):
        raise RuntimeError("database hiccup after the orders were created")

    monkeypatch.setattr(smr_import, "history", hiccup)
    with pytest.raises(RuntimeError):
        import_paper(db, readings_bytes=readings, lines_bytes=lines, breakdown_bytes=breakdown, user=owner)
    db.rollback()  # what the request's session does on an error
    monkeypatch.undo()

    created = wos.find_by_number(db, missing)
    assert created is not None and created.smr_imported_at is not None and created.smr_target["hours"] == "1.5"
    result = import_paper(db, readings_bytes=readings, lines_bytes=lines, breakdown_bytes=breakdown, user=owner)
    assert (result.orders, result.readings, result.lines, result.created_orders) == (1, 1, 1, [])


def test_a_live_non_smr_order_and_an_orphan_line_abort(db):
    owner = _user(db)
    live = wos.get_or_create_work_order(db, number=f"WO-{uuid.uuid4().hex[:8]}", created_by_id=owner.id)
    with pytest.raises(WorkOrderStateError, match=f"Not SMR orders: {live.number}"):
        import_paper(db, readings_bytes=_csv(READING_COLUMNS, [_reading("R1", live.number, hours="")]),
                     lines_bytes=_csv(LINE_COLUMNS, []), user=owner)
    (number,) = _smr_numbers(db, owner, 1)
    with pytest.raises(WorkOrderStateError, match="Line L1: reading R9 is not in the readings file"):
        import_paper(db, readings_bytes=_csv(READING_COLUMNS, [_reading("R1", number)]),
                     lines_bytes=_csv(LINE_COLUMNS, [_line("L1", "R9", number)]), user=owner)


def test_the_paper_check_mark_is_set_once(db):
    owner, checker = _user(db), _user(db, roles.ROLE_TECHNICIAN)
    numbers = _smr_numbers(db, owner, 2)
    marked = wos.find_by_number(db, numbers[0])
    smr_service.set_paper_check(db, work_order_id=marked.id, checked=True, user=checker)
    when = marked.smr_paper_checked_at
    readings, lines = _files(numbers)

    import_paper(db, readings_bytes=readings, lines_bytes=lines, user=owner)

    db.refresh(marked)
    assert (marked.smr_paper_checked_at, marked.smr_paper_checked_by_id) == (when, checker.id)
    assert wos.find_by_number(db, numbers[1]).smr_paper_checked_by_id == owner.id
