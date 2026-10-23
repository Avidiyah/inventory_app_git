"""`GET /work-orders/smr` tiles (spec 2026-10-23 D7/D8): before / after /
delta per order computed from the frozen baseline, archived orders included,
edited ones first."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from decimal import Decimal

from app.domain import roles
from app.domain import work_orders as wo
from app.models import Item, User
from app.services import auth
from app.services import work_orders as wos
from app.services import work_orders_smr as smr_service


def _user(db, role=roles.ROLE_OWNER):
    user = User(username=f"u-{uuid.uuid4().hex[:8]}", password_hash=auth.hash_password("x"), role=role)
    db.add(user)
    db.flush()
    return user


def _sheet(numbers):
    head = "WORK ORDER,CREATOR,SERVICE TYPE,SCHEDULE DATE,COMPLETION DATE,ASSIGNED TO,FILED STATUS,LOCATION\r\n"
    rows = "".join(f"{n},c,SMR27 - Belfor,05/15/2026,05/21/2026,a,Closed,\"B:1,U 1,x\"\r\n" for n in numbers)
    return (head + rows).encode()


def test_smr_tiles_before_after_delta(db):
    owner = _user(db)
    numbers = [f"SMR-{uuid.uuid4().hex[:8]}" for _ in range(2)]
    smr_service.import_smr(db, csv_bytes=_sheet(numbers), user=owner)
    edited = wos.find_by_number(db, numbers[1])
    wos.add_work_order_labor(db, edited.id, user=owner, technician_id=None, minutes=45)

    page = smr_service.list_smr_tiles(db)

    mine = {t.number: t for t in page.tiles if t.number in numbers}
    assert mine[numbers[1]].edited is True and mine[numbers[0]].edited is False
    assert mine[numbers[1]].delta.skilled_minutes == 45
    assert mine[numbers[1]].delta.labor_total == wo.labor_charge(45)
    assert mine[numbers[1]].after.labor_total == wo.labor_charge(45)
    assert mine[numbers[1]].before.total == Decimal("0.00")
    assert mine[numbers[0]].delta.total == Decimal(0)
    assert page.tiles.index(mine[numbers[1]]) < page.tiles.index(mine[numbers[0]])
    assert page.counts.orders >= 2 and page.counts.edited >= 1
    assert page.delta.labor_total >= wo.labor_charge(45)
    assert page.imported_at is not None


def test_smr_tiles_include_archived(db):
    owner = _user(db)
    number = f"SMR-{uuid.uuid4().hex[:8]}"
    smr_service.import_smr(db, csv_bytes=_sheet([number]), user=owner)
    order = wos.find_by_number(db, number)
    wos.archive_work_order(db, order.id, user=owner)

    page = smr_service.list_smr_tiles(db)

    tile = next(t for t in page.tiles if t.number == number)
    assert tile.archived_at is not None
    assert page.counts.archived >= 1
