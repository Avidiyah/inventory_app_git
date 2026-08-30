"""Tests for NetFacilities import reconciliation -- the auto-close sweep.

The import's row loop is covered by `test_work_order_import.py`. This file
covers what the import does *after* the loop: closing every live work order the
CSV did not list, reopening one it lists again, and the 24-hour undo.

The sweep is company-wide by design, which makes every count in here depend on
whatever else the database holds. `_reset_live` settles that once per test by
sweeping the ambient rows away first, so the assertions below can be exact
about the handful of work orders each test actually creates. DB-backed tests
skip if no database.
"""

import os
import sys
import uuid
from datetime import datetime, timedelta, timezone

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain import roles
from app.domain import work_orders as wo
from app.domain.errors import RoleManagementError
from app.models import User, WorkOrder, WorkOrderLaborSession
from app.services import auth
from app.services import work_orders as wos


def _seed_user(db, role, username=None, first_name=None, last_name=None):
    user = User(
        username=username or f"u-{uuid.uuid4().hex[:10]}",
        first_name=first_name,
        last_name=last_name,
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _num():
    return f"WO-{uuid.uuid4().hex[:8]}"


def _row(number, task="Fix couch"):
    return [number, "Commons: 8B", "Belfor", "", "SMR27", "7/29/2026", task]


def _csv(rows):
    """CSV bytes with the export header row + the given data rows."""
    lines = [",".join(wo.IMPORT_HEADERS)]
    for r in rows:
        cells = [f'"{c}"' if "," in c else c for c in r]
        lines.append(",".join(cells))
    return ("\r\n".join(lines) + "\r\n").encode("utf-8")


def _reset_live(db, admin):
    """Leave the database with no live sweepable work orders.

    One import whose CSV names a single throwaway number sweeps every live work
    order the local database already held; archiving that throwaway by hand
    then clears the last one *without* leaving a batch id behind. Every test
    below therefore starts from a known-empty live set and can assert exact
    counts, which is the only way `auto_closed` means anything.
    """
    number = _num()
    wos.import_work_orders(db, csv_bytes=_csv([_row(number)]), user=admin)
    throwaway = wos.find_by_number(db, number)
    wos.archive_work_order(db, throwaway.id, user=admin)
    # Undo the sweep's stamp on the ambient rows so pending-undo tests start
    # from nothing pending too.
    db.query(WorkOrder).filter(WorkOrder.auto_closed_at.is_not(None)).update(
        {
            WorkOrder.auto_closed_at: None,
            WorkOrder.auto_closed_batch_id: None,
        },
        synchronize_session=False,
    )
    db.commit()


def _live_numbers(db):
    return [
        number
        for (number,) in db.query(WorkOrder.number).filter(
            WorkOrder.archived_at.is_(None)
        )
    ]


def _covering_csv(db, extra_rows=()):
    """A CSV listing every currently live work order, plus `extra_rows`.

    The real NetFacilities export is the full list of what is open, and the
    sweep closes what the CSV omits. A test that wants to observe anything
    other than the sweep has to hand the import a complete export.
    """
    return _csv(
        [_row(number, task="") for number in _live_numbers(db)] + list(extra_rows)
    )


def _sweepable(db):
    """How many work orders a sweep against an unrelated CSV would close."""
    return (
        db.query(WorkOrder)
        .filter(WorkOrder.archived_at.is_(None), WorkOrder.legacy.is_not(True))
        .count()
    )


def _live(db, admin, number=None):
    """One live work order, created the only way work orders are created."""
    number = number or _num()
    wos.import_work_orders(
        db, csv_bytes=_covering_csv(db, [_row(number)]), user=admin
    )
    return wos.find_by_number(db, number)


def _running(db, work_order):
    return (
        db.query(WorkOrderLaborSession)
        .filter(
            WorkOrderLaborSession.work_order_id == work_order.id,
            WorkOrderLaborSession.ended_at.is_(None),
        )
        .count()
    )


def _sweep_away_everything(db, admin):
    """Run an import whose CSV names one unrelated number, closing the rest."""
    return wos.import_work_orders(db, csv_bytes=_csv([_row(_num())]), user=admin)


# --- the sweep -----------------------------------------------------------

def test_a_work_order_absent_from_the_csv_is_closed_and_stamped(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    absent = _live(db, admin)

    result = _sweep_away_everything(db, admin)

    db.refresh(absent)
    assert result["auto_closed"] == 1
    assert absent.archived_at is not None
    assert absent.auto_closed_batch_id is not None
    assert absent.auto_closed_at == absent.archived_at
    assert absent.notes.endswith(f"TechFM {wos.AUTO_CLOSE_NOTE}")


def test_a_work_order_the_csv_lists_is_left_alone(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    present = _live(db, admin)
    notes_before = present.notes

    result = wos.import_work_orders(db, csv_bytes=_covering_csv(db), user=admin)

    db.refresh(present)
    assert result["auto_closed"] == 0
    assert present.archived_at is None
    assert present.auto_closed_batch_id is None
    assert present.auto_closed_at is None
    assert present.notes == notes_before


def test_a_hand_archived_work_order_in_the_csv_is_neither_swept_nor_reopened(db):
    """Absence is the sweep's only signal, and a person's close is not it."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    work_order = _live(db, admin)
    wos.archive_work_order(db, work_order.id, user=admin)
    archived_at = work_order.archived_at

    result = wos.import_work_orders(
        db, csv_bytes=_csv([_row(work_order.number)]), user=admin
    )

    db.refresh(work_order)
    assert result["closed"] == 1
    assert result["reopened"] == 0
    assert result["auto_closed"] == 0
    assert work_order.archived_at == archived_at
    assert work_order.auto_closed_batch_id is None


def test_a_legacy_work_order_is_out_of_scope_not_absent(db):
    """Legacy rows predate NetFacilities and can never appear in an export.

    Sweeping them would close all of them on every single import, forever, and
    because the undo is time-limited there would be no way to make it stop.
    """
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    legacy = _live(db, admin)
    legacy.legacy = True
    db.commit()

    result = _sweep_away_everything(db, admin)

    db.refresh(legacy)
    assert result["auto_closed"] == 0
    assert legacy.archived_at is None
    assert legacy.auto_closed_batch_id is None


def test_a_header_only_csv_sweeps_nothing(db):
    """A valid header with zero data rows parses cleanly. Without the guard it
    would close every live work order in the system."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    live = _live(db, admin)

    result = wos.import_work_orders(db, csv_bytes=_csv([]), user=admin)

    db.refresh(live)
    assert result["auto_closed"] == 0
    assert live.archived_at is None


def test_a_csv_of_only_blank_numbers_sweeps_nothing(db):
    """Every row skipped means nothing was seen, which is the same empty case."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    live = _live(db, admin)

    result = wos.import_work_orders(db, csv_bytes=_csv([_row("   ")]), user=admin)

    db.refresh(live)
    assert result["skipped"] == 1
    assert result["auto_closed"] == 0
    assert live.archived_at is None


def test_the_sweep_stops_a_running_clock(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN, first_name="Ada", last_name="Nunez")
    _reset_live(db, admin)
    work_order = _live(db, admin)
    wos.update_work_order(
        db, work_order.id, user=admin, fields={"assigned_to_ids": [tech.id]}
    )
    wos.start_labor_session(db, work_order.id, user=tech)
    assert _running(db, work_order) == 1

    _sweep_away_everything(db, admin)

    db.refresh(work_order)
    assert work_order.archived_at is not None
    assert _running(db, work_order) == 0
    assert work_order.labor_entries


def test_auto_closed_matches_the_rows_actually_archived(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    _live(db, admin)
    _live(db, admin)
    assert _sweepable(db) == 2

    result = _sweep_away_everything(db, admin)

    assert result["auto_closed"] == 2
    # Only the one row that import's own CSV created is still live.
    assert _sweepable(db) == 1


def test_an_import_that_closes_nothing_leaves_no_batch_id_behind(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    _live(db, admin)

    result = wos.import_work_orders(db, csv_bytes=_covering_csv(db), user=admin)

    assert result["auto_closed"] == 0
    assert (
        db.query(WorkOrder)
        .filter(WorkOrder.auto_closed_batch_id.is_not(None))
        .count()
        == 0
    )


def test_one_sweep_shares_a_batch_id_and_the_next_gets_its_own(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    first = _live(db, admin)
    second = _live(db, admin)

    _sweep_away_everything(db, admin)
    db.refresh(first)
    db.refresh(second)
    assert first.auto_closed_batch_id == second.auto_closed_batch_id
    batch_one = first.auto_closed_batch_id

    later = _live(db, admin)
    _sweep_away_everything(db, admin)
    db.refresh(later)

    assert later.auto_closed_batch_id is not None
    assert later.auto_closed_batch_id != batch_one


# --- reopen on reappearance ----------------------------------------------

def test_a_swept_work_order_the_csv_lists_again_is_reopened(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    work_order = _live(db, admin)
    _sweep_away_everything(db, admin)
    db.refresh(work_order)
    assert work_order.archived_at is not None

    result = wos.import_work_orders(
        db, csv_bytes=_csv([_row(work_order.number, task="Back again")]), user=admin
    )

    db.refresh(work_order)
    assert work_order.archived_at is None
    assert work_order.auto_closed_batch_id is None
    assert work_order.auto_closed_at is None
    assert result["reopened"] == 1
    assert result["opened"] == 0
    assert result["created"] == 0
    assert result["closed"] == 0
    # Closed automatically, then how it came back -- the pair reads as a story.
    assert f"TechFM {wos.AUTO_CLOSE_NOTE}" in work_order.notes
    assert work_order.notes.endswith(f"TechFM {wos.AUTO_REOPEN_NOTE}")


def test_a_reopened_work_order_receives_the_csvs_fill_blanks_metadata(db):
    """It falls through to the ordinary live-row merge, so the CSV it came back
    in still fills what was blank."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    number = _num()
    wos.import_work_orders(
        db, csv_bytes=_csv([[number, "", "", "", "", "", ""]]), user=admin
    )
    work_order = wos.find_by_number(db, number)
    assert work_order.location is None
    _sweep_away_everything(db, admin)
    db.refresh(work_order)
    assert work_order.archived_at is not None

    wos.import_work_orders(
        db, csv_bytes=_csv([_row(number, task="Real task")]), user=admin
    )

    db.refresh(work_order)
    assert work_order.archived_at is None
    assert work_order.location == "Commons: 8B"
    assert work_order.description == "Real task"


def test_total_counts_a_reopened_row(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    work_order = _live(db, admin)
    _sweep_away_everything(db, admin)

    result = wos.import_work_orders(
        db, csv_bytes=_csv([_row(work_order.number)]), user=admin
    )

    assert result["reopened"] == 1
    assert result["total"] == 1


def test_a_session_the_sweep_stopped_stays_stopped_after_reopen(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN, first_name="Bo", last_name="Reyes")
    _reset_live(db, admin)
    work_order = _live(db, admin)
    wos.update_work_order(
        db, work_order.id, user=admin, fields={"assigned_to_ids": [tech.id]}
    )
    wos.start_labor_session(db, work_order.id, user=tech)
    _sweep_away_everything(db, admin)

    wos.import_work_orders(
        db, csv_bytes=_csv([_row(work_order.number)]), user=admin
    )

    db.refresh(work_order)
    assert work_order.archived_at is None
    assert _running(db, work_order) == 0


def test_a_restored_work_order_can_be_swept_again(db):
    """Design decision 6: it is still absent upstream, so re-closing it is the
    correct read. The remedy lives in NetFacilities, not in a hidden flag."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    work_order = _live(db, admin)
    _sweep_away_everything(db, admin)
    wos.undo_auto_close(db, user=admin)
    db.refresh(work_order)
    assert work_order.archived_at is None

    _sweep_away_everything(db, admin)

    db.refresh(work_order)
    assert work_order.archived_at is not None
    assert work_order.auto_closed_batch_id is not None


# --- the undo ------------------------------------------------------------

def test_undo_restores_every_sweep_in_the_window_across_two_batches(db):
    admin = _seed_user(db, roles.ROLE_ADMIN, first_name="Ada", last_name="Nunez")
    _reset_live(db, admin)
    first = _live(db, admin)
    _sweep_away_everything(db, admin)
    second = _live(db, admin)
    _sweep_away_everything(db, admin)
    db.refresh(first)
    db.refresh(second)
    assert first.auto_closed_batch_id != second.auto_closed_batch_id

    restored = wos.undo_auto_close(db, user=admin)

    db.refresh(first)
    db.refresh(second)
    # Both sweeps, plus the throwaway row each of them created and the next
    # sweep then closed.
    assert restored >= 2
    for row in (first, second):
        assert row.archived_at is None
        assert row.auto_closed_batch_id is None
        assert row.auto_closed_at is None
        assert row.notes.endswith("TechFM restored: auto-close undone by Ada Nunez.")


def test_undo_leaves_a_hand_archived_work_order_alone(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    by_hand = _live(db, admin)
    wos.archive_work_order(db, by_hand.id, user=admin)
    archived_at = by_hand.archived_at
    notes_before = by_hand.notes
    swept = _live(db, admin)
    _sweep_away_everything(db, admin)

    wos.undo_auto_close(db, user=admin)

    db.refresh(by_hand)
    db.refresh(swept)
    assert by_hand.archived_at == archived_at
    assert by_hand.notes == notes_before
    assert swept.archived_at is None


def test_undo_leaves_a_sweep_older_than_the_window_alone(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    stale = _live(db, admin)
    _sweep_away_everything(db, admin)
    db.refresh(stale)
    long_ago = datetime.now(timezone.utc) - timedelta(hours=25)
    stale.auto_closed_at = long_ago
    db.commit()

    restored = wos.undo_auto_close(db, user=admin)

    db.refresh(stale)
    assert stale.archived_at is not None
    assert stale.auto_closed_at == long_ago
    assert restored == 0


def test_undo_returns_the_true_count_when_a_row_was_restored_in_between(db):
    """The label an operator read a moment ago is a promise about the past."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    first = _live(db, admin)
    second = _live(db, admin)
    _sweep_away_everything(db, admin)
    assert wos.pending_auto_close(db, user=admin)["closed_count"] == 2
    wos.restore_work_order(db, first.id, user=admin)

    assert wos.undo_auto_close(db, user=admin) == 1

    db.refresh(second)
    assert second.archived_at is None


def test_undo_with_nothing_pending_is_zero_not_an_error(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)

    assert wos.undo_auto_close(db, user=admin) == 0


def test_undo_and_pending_refuse_below_techfm_oa(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    supervisor = _seed_user(db, roles.ROLE_SUPERVISOR)
    _reset_live(db, admin)

    with pytest.raises(RoleManagementError):
        wos.undo_auto_close(db, user=supervisor)
    with pytest.raises(RoleManagementError):
        wos.pending_auto_close(db, user=supervisor)


def test_pending_reports_both_batches_and_then_nothing(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    assert wos.pending_auto_close(db, user=admin) is None

    _live(db, admin)
    _sweep_away_everything(db, admin)
    _live(db, admin)
    _sweep_away_everything(db, admin)

    pending = wos.pending_auto_close(db, user=admin)
    assert pending["batch_count"] == 2
    assert pending["closed_count"] >= 2
    assert pending["oldest_ran_at"] <= pending["newest_ran_at"]

    wos.undo_auto_close(db, user=admin)
    assert wos.pending_auto_close(db, user=admin) is None


def test_pending_ignores_a_sweep_outside_the_window(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    _reset_live(db, admin)
    _live(db, admin)
    _sweep_away_everything(db, admin)
    db.query(WorkOrder).filter(WorkOrder.auto_closed_at.is_not(None)).update(
        {WorkOrder.auto_closed_at: datetime.now(timezone.utc) - timedelta(hours=25)},
        synchronize_session=False,
    )
    db.commit()

    assert wos.pending_auto_close(db, user=admin) is None


# --- restore_work_order --------------------------------------------------

def test_restoring_a_sweep_closed_row_clears_both_columns_and_says_who(db):
    admin = _seed_user(db, roles.ROLE_ADMIN, first_name="Bo", last_name="Reyes")
    _reset_live(db, admin)
    work_order = _live(db, admin)
    _sweep_away_everything(db, admin)

    wos.restore_work_order(db, work_order.id, user=admin)

    db.refresh(work_order)
    assert work_order.archived_at is None
    assert work_order.auto_closed_batch_id is None
    assert work_order.auto_closed_at is None
    assert work_order.notes.endswith("TechFM restored by Bo Reyes.")


def test_restoring_a_hand_archived_row_stays_silent(db):
    admin = _seed_user(db, roles.ROLE_ADMIN, first_name="Bo", last_name="Reyes")
    _reset_live(db, admin)
    work_order = _live(db, admin)
    wos.archive_work_order(db, work_order.id, user=admin)
    notes_before = work_order.notes

    wos.restore_work_order(db, work_order.id, user=admin)

    db.refresh(work_order)
    assert work_order.archived_at is None
    assert work_order.notes == notes_before
