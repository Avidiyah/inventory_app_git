"""Schema-level tests for the SMR27 audit columns (spec
docs/superpowers/specs/2026-10-23-smr-audit-workflow-design.md): the two
work-order columns and the nullable labor technician that represents an
anonymous Skilled Technician line."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone

from app.models import User, WorkOrder, WorkOrderLabor


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
