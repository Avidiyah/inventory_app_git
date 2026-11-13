"""Paper reviewed: stage rule, plus `PUT /work-orders/smr/{id}/paper-reviewed` over real HTTP."""
from datetime import datetime, timezone
from types import SimpleNamespace

from app.database import get_db
from app.domain.work_orders_smr_lines import stage_for
from app.main import app
from tests.test_smr_ready import _client, _smr_order, _user

NOW = datetime(2026, 11, 13, tzinfo=timezone.utc)
DATED = SimpleNamespace(week=2)


def test_stamp_moves_a_billed_undated_order_to_needs_review():
    kw = dict(has_materials=True, billed=True)
    assert stage_for([], None, **kw) == "paper_review"
    assert stage_for([], None, paper_reviewed_at=NOW, **kw) == "needs_review"
    # not billed, or no materials: the stamp changes nothing
    assert stage_for([], None, has_materials=True, billed=False, paper_reviewed_at=NOW) == "other"
    assert stage_for([], None, has_materials=False, billed=True, paper_reviewed_at=NOW) == "no_material"


def _put(db, user, order_id, reviewed):
    try:
        with _client(db, user) as client:
            return client.put(f"/work-orders/smr/{order_id}/paper-reviewed", json={"reviewed": reviewed})
    finally:
        del app.dependency_overrides[get_db]


def test_gate_and_refusal(db):
    owner = _user(db, "owner")
    order = _smr_order(db, owner)  # no materials: not in paper review
    assert _put(db, _user(db), order.id, True).status_code == 403
    assert _put(db, _user(db, "admin"), order.id, True).status_code == 400
    assert _put(db, _user(db, "admin"), order.id, False).status_code == 200
