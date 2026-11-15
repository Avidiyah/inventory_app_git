"""W3 Task 1: the flush listener stamps who changed each protected field.

Stamps feed the save-time conflict message ("Maria changed Priority to P2
12 seconds ago"). They are written by one listener (`app/field_stamps.py`),
so every writer -- the edit form, CSV import, tracking, History voids --
leaves one without remembering to.
"""

import uuid
from datetime import datetime, timedelta, timezone
from decimal import Decimal

from fastapi.testclient import TestClient
from sqlalchemy import text

from app.database import get_db
from app.domain import roles
from app.domain import work_orders as wo
from app.main import app
from app.models import Item, User, WorkOrderFieldStamp, WorkOrderItem, WorkOrderLabor
from app.services import auth as auth_service
from app.services import work_orders as wos
from app.services.transactions import void_transaction


def _user(db, role, first="Maria", last="Lopez"):
    user = User(
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name=first,
        last_name=last,
        password_hash=auth_service.hash_password("hunter2"),
        role=role,
    )
    db.add(user)
    db.flush()
    return user


def _wo(db, creator, *, technician=None):
    return wos.get_or_create_work_order(
        db,
        number=f"WO-{uuid.uuid4().hex[:8]}",
        created_by_id=creator.id,
        assigned_to_id=technician.id if technician else None,
    )


def _item(db):
    item = Item(
        barcode=f"BC-{uuid.uuid4().hex[:10]}",
        name="Wire Nut",
        quantity=Decimal("50"),
        location="Bay 2",
        price=Decimal("1.00"),
    )
    db.add(item)
    db.flush()
    return item


def _stamp(db, work_order_id, field):
    return (
        db.query(WorkOrderFieldStamp)
        .filter_by(work_order_id=work_order_id, field=field)
        .one_or_none()
    )


def test_changing_priority_stamps_it_with_the_actor(db):
    admin = _user(db, roles.ROLE_ADMIN)
    w = _wo(db, admin)
    db.info["actor_id"] = admin.id
    wos.update_work_order(db, w.id, user=admin, fields={"priority": "P2"})

    stamp = _stamp(db, w.id, "priority")
    assert stamp is not None
    assert stamp.changed_by_id == admin.id
    assert datetime.now(timezone.utc) - stamp.changed_at < timedelta(seconds=5)


def test_resaving_an_unchanged_value_writes_no_stamp(db):
    admin = _user(db, roles.ROLE_ADMIN)
    w = _wo(db, admin)
    db.execute(text("UPDATE work_orders SET priority = 'P1' WHERE id = :id"), {"id": w.id})
    db.info["actor_id"] = admin.id
    wos.update_work_order(db, w.id, user=admin, fields={"priority": "P1"})
    assert _stamp(db, w.id, "priority") is None


def test_a_second_change_moves_the_stamp_to_the_new_actor(db):
    admin = _user(db, roles.ROLE_ADMIN)
    other = _user(db, roles.ROLE_ADMIN, first="Sam", last="Ortiz")
    w = _wo(db, admin)
    db.info["actor_id"] = admin.id
    wos.update_work_order(db, w.id, user=admin, fields={"priority": "P2"})
    db.info["actor_id"] = other.id
    wos.update_work_order(db, w.id, user=other, fields={"priority": "P3"})
    db.expire_all()
    assert _stamp(db, w.id, "priority").changed_by_id == other.id


def test_crew_change_stamps_assigned_to_ids(db):
    admin = _user(db, roles.ROLE_ADMIN)
    tech = _user(db, roles.ROLE_TECHNICIAN, first="Tia", last="Ng")
    w = _wo(db, admin)
    db.info["actor_id"] = admin.id
    wos.update_work_order(db, w.id, user=admin, fields={"assigned_to_ids": [tech.id]})
    stamp = _stamp(db, w.id, "assigned_to_ids")
    assert stamp is not None and stamp.changed_by_id == admin.id


def test_a_new_work_order_gets_no_stamps(db):
    admin = _user(db, roles.ROLE_ADMIN)
    tech = _user(db, roles.ROLE_TECHNICIAN)
    db.info["actor_id"] = admin.id
    w = _wo(db, admin, technician=tech)
    assert db.query(WorkOrderFieldStamp).filter_by(work_order_id=w.id).count() == 0


def test_csv_import_update_stamps_changed_fields(db):
    admin = _user(db, roles.ROLE_ADMIN)
    number = f"WO-{uuid.uuid4().hex[:8]}"

    def csv(task):
        header = ",".join(wo.IMPORT_HEADERS)
        row = ",".join([number, "Commons: 8B", "Belfor", "", "SMR27", "7/29/2026", task])
        return f"{header}\r\n{row}\r\n".encode("utf-8")

    db.info["actor_id"] = admin.id
    wos.import_work_orders(db, csv_bytes=csv("   "), user=admin)
    w = wos.find_by_number(db, number)
    assert _stamp(db, w.id, "description") is None
    wos.import_work_orders(db, csv_bytes=csv("Fix couch"), user=admin)
    stamp = _stamp(db, w.id, "description")
    assert stamp is not None and stamp.changed_by_id == admin.id


def test_auto_hold_on_last_stop_stamps_status(db):
    sup = _user(db, roles.ROLE_SUPERVISOR)
    tech = _user(db, roles.ROLE_TECHNICIAN)
    w = _wo(db, sup, technician=tech)
    db.info["actor_id"] = tech.id
    wos.start_labor_session(db, w.id, user=tech)
    db.execute(text("DELETE FROM work_order_field_stamps WHERE work_order_id = :id"), {"id": w.id})
    wos.stop_labor_session(db, w.id, user=tech)
    db.refresh(w)
    assert w.status == "on_hold"
    stamp = _stamp(db, w.id, "status")
    assert stamp is not None and stamp.changed_by_id == tech.id


def test_history_void_sets_line_updated_by(db):
    sup = _user(db, roles.ROLE_SUPERVISOR)
    tech = _user(db, roles.ROLE_TECHNICIAN)
    item = _item(db)
    w = _wo(db, sup, technician=tech)
    db.info["actor_id"] = tech.id
    line = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(4))
    line_id = line.id
    second = wos.add_work_order_item(db, w.id, user=tech, item_id=item.id, quantity=Decimal(2))
    db.info["actor_id"] = sup.id
    void_transaction(db, transaction_id=second.transaction_id, user_id=sup.id)
    db.expire_all()
    line = db.get(WorkOrderItem, line_id)
    assert line is not None
    assert line.updated_by_id == sup.id


def test_quantity_edit_sets_line_updated_by(db):
    sup = _user(db, roles.ROLE_SUPERVISOR)
    item = _item(db)
    w = _wo(db, sup)
    db.info["actor_id"] = sup.id
    line = wos.add_work_order_item(db, w.id, user=sup, item_id=item.id, quantity=Decimal(4))
    other = _user(db, roles.ROLE_SUPERVISOR, first="Sam", last="Ortiz")
    db.info["actor_id"] = other.id
    wos.update_work_order_item(db, w.id, line.id, user=other, quantity=Decimal(3))
    assert db.get(WorkOrderItem, line.id).updated_by_id == other.id


def test_labor_edit_sets_updated_by(db):
    admin = _user(db, roles.ROLE_ADMIN)
    tech = _user(db, roles.ROLE_TECHNICIAN)
    w = _wo(db, admin, technician=tech)
    db.info["actor_id"] = admin.id
    entry = wos.add_work_order_labor(db, w.id, user=admin, technician_id=tech.id, minutes=60)
    other = _user(db, roles.ROLE_ADMIN, first="Sam", last="Ortiz")
    db.info["actor_id"] = other.id
    wos.update_work_order_labor(db, w.id, entry.id, user=other, minutes=95)
    assert db.get(WorkOrderLabor, entry.id).updated_by_id == other.id


def test_no_actor_stamps_with_null(db):
    admin = _user(db, roles.ROLE_ADMIN)
    w = _wo(db, admin)
    db.info.pop("actor_id", None)
    wos.update_work_order(db, w.id, user=admin, fields={"priority": "P2"})
    stamp = _stamp(db, w.id, "priority")
    assert stamp is not None and stamp.changed_by_id is None


def test_http_patch_records_the_signed_in_user(db):
    admin = _user(db, roles.ROLE_ADMIN)
    w = _wo(db, admin)
    db.info.pop("actor_id", None)
    token = auth_service.create_session(db, admin)
    app.dependency_overrides[get_db] = lambda: db
    try:
        with TestClient(app) as client:
            client.cookies.set("session", token)
            response = client.patch(f"/work-orders/{w.id}", json={"priority": "P2"})
    finally:
        del app.dependency_overrides[get_db]
    assert response.status_code == 200, response.text
    assert _stamp(db, w.id, "priority").changed_by_id == admin.id
