"""Witness sign-off on a work order (spec 2026-09-30): migration, service,
and router tests. Router tests go through a real `TestClient`, never a
direct handler call (see `test_work_orders_router.py` for why)."""

import base64
import importlib.util
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import uuid
from datetime import datetime, timezone
from pathlib import Path

import pytest
from alembic.migration import MigrationContext
from alembic.operations import Operations
from sqlalchemy import delete, text

from app.domain import roles
from app.domain.errors import (
    WorkOrderAlreadySignedError,
    WorkOrderNotFoundError,
    WorkOrderSignatureError,
)
from app.models import User, WorkOrder, WorkOrderSignature
from app.services import auth as auth_service
from app.services import work_order_signature as signature_service
from app.services import work_orders as wos

PNG = b"\x89PNG\r\n\x1a\n" + b"\x00" * 16
PNG_URL = "data:image/png;base64," + base64.b64encode(PNG).decode()


def _seed_user(db, role, first="Sam", last="Signer"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
        first_name=first,
        last_name=last,
    )
    db.add(user)
    db.flush()
    return user


def _work_order(db, admin, tech):
    return wos.get_or_create_work_order(
        db,
        number=f"WO-SIG-{uuid.uuid4().hex[:8]}",
        created_by_id=admin.id,
        assigned_to_id=tech.id,
    )


def _save(db, work_order_id, user, **overrides):
    payload = dict(
        image_data_url=PNG_URL, witness_name="Pat Doe", witness_phone="(555) 555-1234"
    )
    payload.update(overrides)
    return signature_service.save_signature(db, work_order_id, user=user, **payload)


def _rows(db, work_order_id):
    return (
        db.query(WorkOrderSignature)
        .filter_by(work_order_id=work_order_id)
        .count()
    )


# --------------------------------------------------------------------------
# migration
# --------------------------------------------------------------------------


def _load_migration():
    path = (
        Path(__file__).resolve().parents[1]
        / "alembic" / "versions"
        / "a7c3e9f1b2d4_add_work_order_signatures.py"
    )
    spec = importlib.util.spec_from_file_location("sig_rev", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_migration_drops_and_recreates_the_table(db):
    module = _load_migration()
    ctx = MigrationContext.configure(db.connection())
    exists = lambda: db.execute(text("SELECT to_regclass('work_order_signatures')")).scalar()
    assert exists() is not None  # dev DB is at head
    with Operations.context(ctx):
        module.downgrade()
    assert exists() is None
    with Operations.context(ctx):
        module.upgrade()
    assert exists() is not None


# --------------------------------------------------------------------------
# service
# --------------------------------------------------------------------------


def test_save_inserts_one_row_and_a_note_line(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN, "Tia", "Tech")
    work_order = _work_order(db, admin, tech)

    result = _save(db, work_order.id, tech)

    row = db.query(WorkOrderSignature).filter_by(work_order_id=work_order.id).one()
    assert row.witness_name == "Pat Doe"
    assert row.witness_phone == "5555551234"
    assert row.image_png == PNG
    assert row.captured_by_id == tech.id
    assert row.captured_at.tzinfo is not None
    assert result.notes.endswith("Tia Tech captured witness sign-off from Pat Doe")


def test_second_save_conflicts(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _work_order(db, admin, tech)
    _save(db, work_order.id, tech)

    with pytest.raises(WorkOrderAlreadySignedError):
        _save(db, work_order.id, admin)
    assert _rows(db, work_order.id) == 1


def test_concurrent_insert_maps_to_conflict(db, monkeypatch):
    """Two devices saving at once: the pre-check misses, the unique constraint
    fires, and the loser still gets the conflict error rather than a raw
    IntegrityError."""
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _work_order(db, admin, tech)
    db.add(WorkOrderSignature(
        work_order_id=work_order.id, image_png=PNG, witness_name="First",
        witness_phone="5555550000", captured_by_id=admin.id,
        captured_at=datetime.now(timezone.utc),
    ))
    db.commit()
    monkeypatch.setattr(signature_service, "_already_signed", lambda *a: False)

    with pytest.raises(WorkOrderAlreadySignedError):
        _save(db, work_order.id, tech)
    assert _rows(db, work_order.id) == 1
    assert db.query(WorkOrderSignature).one().witness_name == "First"


def test_save_on_invisible_work_order_is_not_found(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    stranger = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _work_order(db, admin, tech)

    with pytest.raises(WorkOrderNotFoundError):
        _save(db, work_order.id, stranger)
    assert _rows(db, work_order.id) == 0


@pytest.mark.parametrize("bad", [
    {"image_data_url": "data:image/jpeg;base64," + base64.b64encode(PNG).decode()},
    {"image_data_url": "data:image/png;base64,"
     + base64.b64encode(PNG + b"\x00" * (256 * 1024)).decode()},
    {"witness_name": "   "},
    {"witness_phone": "555-1234"},
], ids=["non-png", "oversize", "blank-name", "short-phone"])
def test_bad_payloads_rejected_and_nothing_written(db, bad):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _work_order(db, admin, tech)
    notes_before = work_order.notes

    with pytest.raises(WorkOrderSignatureError):
        _save(db, work_order.id, tech, **bad)
    assert _rows(db, work_order.id) == 0
    db.refresh(work_order)
    assert work_order.notes == notes_before


def test_clear_deletes_row_and_appends_note(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    sup = _seed_user(db, roles.ROLE_SUPERVISOR, "Sue", "Super")
    work_order = _work_order(db, admin, tech)
    _save(db, work_order.id, tech)

    result = signature_service.clear_signature(db, work_order.id, user=sup)

    assert _rows(db, work_order.id) == 0
    assert result.notes.endswith("Sue Super cleared the witness sign-off")
    assert "captured witness sign-off from Pat Doe" in result.notes


def test_clear_when_unsigned_is_not_found(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _work_order(db, admin, tech)

    with pytest.raises(WorkOrderNotFoundError):
        signature_service.clear_signature(db, work_order.id, user=admin)


def test_archive_and_restore_keep_the_row(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _work_order(db, admin, tech)
    _save(db, work_order.id, tech)

    wos.archive_work_order(db, work_order.id, user=admin)
    assert _rows(db, work_order.id) == 1
    wos.restore_work_order(db, work_order.id, user=admin)
    assert _rows(db, work_order.id) == 1


def test_work_order_delete_cascades(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _work_order(db, admin, tech)
    _save(db, work_order.id, tech)
    wid = work_order.id

    # Core delete bypasses ORM cascades, so this proves the DB's ON DELETE CASCADE.
    db.execute(delete(WorkOrder).where(WorkOrder.id == wid))
    db.commit()
    assert _rows(db, wid) == 0


def test_get_png_returns_bytes_and_404s_when_unsigned(db):
    admin = _seed_user(db, roles.ROLE_ADMIN)
    tech = _seed_user(db, roles.ROLE_TECHNICIAN)
    work_order = _work_order(db, admin, tech)

    with pytest.raises(WorkOrderNotFoundError):
        signature_service.get_signature_png(db, work_order.id, user=tech)
    _save(db, work_order.id, tech)
    assert signature_service.get_signature_png(db, work_order.id, user=tech) == PNG
