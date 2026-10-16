"""The Admin's audited punch writes (spec D2, §1, §9).

A soft-deleted punch is gone for every purpose except the audit trail: the
partial unique index must not count it, and no read may return it.
"""
import os, sys, uuid
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timedelta, timezone

import pytest

from app.domain.errors import (NoChangeError, PunchNotFoundError,
                               PunchOverlapError, PunchTimeInvalidError)
from app.models import AttendancePunch, AttendancePunchEdit, User
from app.services import attendance as attendance_service
from app.services import auth as auth_service


def _seed_user(db, role="technician"):
    user = User(username=f"u-{uuid.uuid4().hex[:10]}",
                password_hash=auth_service.hash_password("hunter2"), role=role)
    db.add(user); db.flush()
    return user


def test_a_soft_deleted_open_punch_does_not_block_a_new_punch_in(db):
    # The partial unique index is the reason this is a real risk: if it still
    # counted the deleted row, the insert would raise IntegrityError and the
    # person could never clock in again.
    user = _seed_user(db)
    now = datetime.now(timezone.utc)
    stale = AttendancePunch(id=uuid.uuid4(), user_id=user.id,
                            started_at=now - timedelta(hours=30),
                            start_source="manual", deleted_at=now)
    db.add(stale); db.commit()

    punch = attendance_service.punch_in(db, user=user, now=now)

    assert punch.ended_at is None
    assert attendance_service.open_punch_for(db, user.id).id == punch.id


# `_punch` pins clock hours on `now`'s date, so a real clock read before
# 17:00 UTC would put those hours in the future and trip validation.
_NOW = datetime(2026, 9, 15, 20, tzinfo=timezone.utc)


def _punch(db, user, *, start_h, end_h, now, needs_review=False):
    punch = AttendancePunch(
        id=uuid.uuid4(), user_id=user.id,
        started_at=now.replace(hour=start_h, minute=0, second=0, microsecond=0),
        ended_at=now.replace(hour=end_h, minute=0, second=0, microsecond=0),
        start_source="manual", end_source="manual", needs_review=needs_review)
    db.add(punch); db.flush()
    return punch


def test_add_writes_the_punch_and_one_created_audit_row(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = datetime.now(timezone.utc)
    db.commit()

    punch = attendance_service.admin_add_punch(
        db, actor=admin, user_id=tech.id,
        started_at=now - timedelta(hours=4), ended_at=now - timedelta(hours=1),
        reason="forgot to clock in", now=now)

    rows = db.query(AttendancePunchEdit).filter_by(punch_id=punch.id).all()
    assert punch.end_source == "admin_edit"
    assert [r.field for r in rows] == ["created"]
    assert rows[0].edited_by_id == admin.id
    assert rows[0].old_value is None and rows[0].reason == "forgot to clock in"


def test_edit_writes_one_row_per_changed_field_and_clears_needs_review(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = _NOW
    punch = _punch(db, tech, start_h=8, end_h=15, now=now, needs_review=True)
    db.commit()
    new_end = punch.ended_at - timedelta(hours=1)

    attendance_service.admin_edit_punch(
        db, actor=admin, punch_id=punch.id, ended_at=new_end, now=now)

    fields = sorted(r.field for r in
                    db.query(AttendancePunchEdit).filter_by(punch_id=punch.id).all())
    assert fields == ["ended_at", "needs_review"]
    assert punch.needs_review is False and punch.end_source == "admin_edit"


def test_clearing_the_flag_alone_is_a_legal_edit(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = _NOW
    punch = _punch(db, tech, start_h=8, end_h=15, now=now, needs_review=True)
    db.commit()

    attendance_service.admin_edit_punch(
        db, actor=admin, punch_id=punch.id, needs_review=False, now=now)

    assert punch.needs_review is False
    assert punch.ended_at == now.replace(hour=15, minute=0, second=0, microsecond=0)


def test_an_edit_that_changes_nothing_is_refused(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = _NOW
    punch = _punch(db, tech, start_h=8, end_h=15, now=now)
    db.commit()
    with pytest.raises(NoChangeError):
        attendance_service.admin_edit_punch(db, actor=admin, punch_id=punch.id, now=now)


def test_an_edit_overlapping_another_punch_names_the_conflict(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = _NOW
    morning = _punch(db, tech, start_h=8, end_h=11, now=now)
    afternoon = _punch(db, tech, start_h=13, end_h=17, now=now)
    db.commit()
    with pytest.raises(PunchOverlapError) as caught:
        attendance_service.admin_edit_punch(
            db, actor=admin, punch_id=afternoon.id,
            started_at=morning.ended_at - timedelta(minutes=30), now=now)
    assert caught.value.punch_id == morning.id


def test_a_punch_may_not_be_reopened(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = _NOW
    punch = _punch(db, tech, start_h=8, end_h=15, now=now)
    db.commit()
    with pytest.raises(PunchTimeInvalidError):
        attendance_service.admin_edit_punch(
            db, actor=admin, punch_id=punch.id,
            started_at=punch.started_at + timedelta(hours=8), now=now)


def test_delete_is_soft_keeps_the_audit_and_hides_the_row(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = _NOW
    punch = _punch(db, tech, start_h=8, end_h=15, now=now)
    db.commit()

    attendance_service.admin_delete_punch(
        db, actor=admin, punch_id=punch.id, reason="duplicate", now=now)

    rows = db.query(AttendancePunchEdit).filter_by(punch_id=punch.id).all()
    assert [r.field for r in rows] == ["deleted"]
    assert rows[0].new_value is None and rows[0].old_value.startswith("20")
    assert punch.deleted_at is not None
    assert attendance_service.live_punches(db).filter_by(id=punch.id).first() is None


def test_a_deleted_punch_cannot_be_edited(db):
    admin, tech = _seed_user(db, "admin"), _seed_user(db)
    now = _NOW
    punch = _punch(db, tech, start_h=8, end_h=15, now=now)
    db.commit()
    attendance_service.admin_delete_punch(db, actor=admin, punch_id=punch.id, now=now)
    with pytest.raises(PunchNotFoundError):
        attendance_service.admin_edit_punch(
            db, actor=admin, punch_id=punch.id, needs_review=False, now=now)


# --- A worker's own time (2026-10-16 self-edit) --------------------------
# _NOW is Tue 2026-09-15; its Central week starts Mon 2026-09-14.

def _punch_at(db, user, start, end, *, needs_review=False):
    punch = AttendancePunch(id=uuid.uuid4(), user_id=user.id, started_at=start,
                            ended_at=end, start_source="manual",
                            end_source="manual", needs_review=needs_review)
    db.add(punch); db.flush()
    return punch


_TUE_9 = datetime(2026, 9, 15, 14, tzinfo=timezone.utc)      # 09:00 CDT
_LAST_FRI_9 = datetime(2026, 9, 11, 14, tzinfo=timezone.utc)  # previous week


def test_worker_adds_edits_deletes_own_open_week_punch(db):
    from app.domain.attendance import END_SOURCE_SELF_EDIT
    tech = _seed_user(db); db.commit()

    added = attendance_service.admin_add_punch(
        db, actor=tech, user_id=tech.id, started_at=_TUE_9,
        ended_at=_TUE_9 + timedelta(hours=2), now=_NOW)
    assert added.end_source == END_SOURCE_SELF_EDIT
    attendance_service.admin_edit_punch(
        db, actor=tech, punch_id=added.id,
        ended_at=_TUE_9 + timedelta(hours=3), now=_NOW)
    assert added.end_source == END_SOURCE_SELF_EDIT
    attendance_service.admin_delete_punch(db, actor=tech, punch_id=added.id, now=_NOW)

    rows = db.query(AttendancePunchEdit).filter_by(punch_id=added.id).all()
    assert sorted(r.field for r in rows) == ["created", "deleted", "ended_at"]
    assert {r.edited_by_id for r in rows} == {tech.id}


def test_worker_cannot_touch_another_persons_punch(db):
    from app.domain.errors import TimeEditForbiddenError
    tech, peer = _seed_user(db), _seed_user(db)
    punch = _punch_at(db, peer, _TUE_9, _TUE_9 + timedelta(hours=2)); db.commit()

    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_edit_punch(
            db, actor=tech, punch_id=punch.id,
            ended_at=_TUE_9 + timedelta(hours=3), now=_NOW)
    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_delete_punch(db, actor=tech, punch_id=punch.id, now=_NOW)
    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_add_punch(
            db, actor=tech, user_id=peer.id, started_at=_TUE_9 + timedelta(hours=4),
            ended_at=_TUE_9 + timedelta(hours=5), now=_NOW)


def test_self_edit_cannot_touch_a_closed_week(db):
    from app.domain.errors import TimeEditForbiddenError
    tech = _seed_user(db)
    punch = _punch_at(db, tech, _LAST_FRI_9, _LAST_FRI_9 + timedelta(hours=2)); db.commit()

    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_edit_punch(
            db, actor=tech, punch_id=punch.id,
            ended_at=_LAST_FRI_9 + timedelta(hours=3), now=_NOW)
    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_delete_punch(db, actor=tech, punch_id=punch.id, now=_NOW)
    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_add_punch(
            db, actor=tech, user_id=tech.id, started_at=_LAST_FRI_9 + timedelta(hours=4),
            ended_at=_LAST_FRI_9 + timedelta(hours=5), now=_NOW)


def test_self_edit_cannot_move_a_punch_into_a_closed_week(db):
    from app.domain.errors import TimeEditForbiddenError
    tech = _seed_user(db)
    start = datetime(2026, 9, 14, 5, 30, tzinfo=timezone.utc)   # Mon 00:30 CDT
    punch = _punch_at(db, tech, start, start + timedelta(hours=1)); db.commit()
    sunday = datetime(2026, 9, 14, 4, 30, tzinfo=timezone.utc)  # Sun 23:30 CDT

    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_edit_punch(
            db, actor=tech, punch_id=punch.id, started_at=sunday, now=_NOW)
    db.refresh(punch)
    assert punch.started_at == start


def test_self_edit_cannot_look_right_or_waive_lunch(db):
    from app.domain.errors import TimeEditForbiddenError
    tech = _seed_user(db)
    punch = _punch_at(db, tech, _TUE_9, _TUE_9 + timedelta(hours=8),
                      needs_review=True); db.commit()

    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_edit_punch(
            db, actor=tech, punch_id=punch.id, needs_review=False, now=_NOW)
    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_edit_punch(
            db, actor=tech, punch_id=punch.id, lunch_waived=True, now=_NOW)
    db.refresh(punch)
    assert punch.needs_review is True and punch.lunch_waived is False


def test_self_edit_cannot_look_right_by_resending_the_same_time(db):
    from app.domain.errors import TimeEditForbiddenError
    tech = _seed_user(db)
    punch = _punch_at(db, tech, _TUE_9, _TUE_9 + timedelta(hours=8),
                      needs_review=True); db.commit()

    with pytest.raises(TimeEditForbiddenError):
        attendance_service.admin_edit_punch(
            db, actor=tech, punch_id=punch.id, started_at=_TUE_9,
            needs_review=False, now=_NOW)
    db.refresh(punch)
    assert punch.needs_review is True


def test_self_fix_clears_needs_review(db):
    tech = _seed_user(db)
    punch = _punch_at(db, tech, _TUE_9, _TUE_9 + timedelta(hours=8),
                      needs_review=True); db.commit()

    attendance_service.admin_edit_punch(
        db, actor=tech, punch_id=punch.id,
        ended_at=_TUE_9 + timedelta(hours=6), now=_NOW)

    assert punch.needs_review is False
    fields = [r.field for r in db.query(AttendancePunchEdit).filter_by(punch_id=punch.id)]
    assert "needs_review" in fields
