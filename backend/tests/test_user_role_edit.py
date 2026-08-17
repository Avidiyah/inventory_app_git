"""Role editing from the Users page (`PATCH /users/{id}/role`).

Two rules are under test. The route-level Admin+ gate is pinned in
`test_route_role_gates.py` (calling a handler directly skips FastAPI's
dependencies, so it cannot be observed here). What *is* observable here is
the handler's own pair of rank checks -- the actor must outrank both the
role the target holds and the role being assigned -- plus the service
behaviour: the role is persisted and the target's sessions are revoked so
their cached, role-shaped UI cannot outlive the change.
"""

import os
import sys
import uuid

import pytest
from fastapi import HTTPException

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import roles
from app.models import AuthSession
from app.routers.users import update_user_role as update_user_role_route
from app.schemas.users import UserRoleUpdate
from app.services import auth
from app.services import users as users_service


def _create_user(db, role):
    return users_service.create_user(
        db,
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name="Existing",
        last_name="User",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )


def test_role_payload_rejects_unknown_role():
    with pytest.raises(ValueError):
        UserRoleUpdate(role="superuser")


def test_admin_can_promote_and_demote_a_subordinate(db):
    admin = _create_user(db, roles.ROLE_ADMIN)
    target = _create_user(db, roles.ROLE_TECHNICIAN)

    promoted = update_user_role_route(
        target.id,
        UserRoleUpdate(role=roles.ROLE_SUPERVISOR),
        actor=admin,
        db=db,
    )
    assert promoted.role == roles.ROLE_SUPERVISOR

    demoted = update_user_role_route(
        target.id,
        UserRoleUpdate(role=roles.ROLE_TECHNICIAN),
        actor=admin,
        db=db,
    )
    assert demoted.role == roles.ROLE_TECHNICIAN


def test_admin_cannot_assign_own_rank_or_above(db):
    admin = _create_user(db, roles.ROLE_ADMIN)
    target = _create_user(db, roles.ROLE_TECHNICIAN)

    for role in (roles.ROLE_ADMIN, roles.ROLE_OWNER):
        with pytest.raises(HTTPException) as exc:
            update_user_role_route(
                target.id,
                UserRoleUpdate(role=role),
                actor=admin,
                db=db,
            )
        assert exc.value.status_code == 403

    db.refresh(target)
    assert target.role == roles.ROLE_TECHNICIAN


def test_actor_cannot_change_a_peer_or_their_own_role(db):
    admin = _create_user(db, roles.ROLE_ADMIN)
    peer = _create_user(db, roles.ROLE_ADMIN)

    for target_id in (peer.id, admin.id):
        with pytest.raises(HTTPException) as exc:
            update_user_role_route(
                target_id,
                UserRoleUpdate(role=roles.ROLE_TECHNICIAN),
                actor=admin,
                db=db,
            )
        assert exc.value.status_code == 403

    db.refresh(admin)
    db.refresh(peer)
    assert admin.role == roles.ROLE_ADMIN
    assert peer.role == roles.ROLE_ADMIN


def test_owner_is_never_re_rolled(db):
    owner = _create_user(db, roles.ROLE_OWNER)
    other_owner = _create_user(db, roles.ROLE_OWNER)

    with pytest.raises(HTTPException) as exc:
        update_user_role_route(
            other_owner.id,
            UserRoleUpdate(role=roles.ROLE_ADMIN),
            actor=owner,
            db=db,
        )
    assert exc.value.status_code == 403


def test_unknown_user_is_404(db):
    admin = _create_user(db, roles.ROLE_ADMIN)

    with pytest.raises(HTTPException) as exc:
        update_user_role_route(
            uuid.uuid4(),
            UserRoleUpdate(role=roles.ROLE_TECHNICIAN),
            actor=admin,
            db=db,
        )
    assert exc.value.status_code == 404


def test_role_change_revokes_the_target_sessions(db):
    target = _create_user(db, roles.ROLE_TECHNICIAN)
    token = auth.create_session(db, target, remember=False)
    assert auth.get_active_session_user(db, token) is not None

    users_service.update_role(db, target.id, role=roles.ROLE_SUPERVISOR)

    assert db.query(AuthSession).filter(AuthSession.user_id == target.id).count() == 0
    assert auth.get_active_session_user(db, token) is None
    assert users_service.get_user(db, target.id).role == roles.ROLE_SUPERVISOR


def test_techfm_oa_cannot_change_an_admin_or_owner_role(db):
    # The second of TechFM OA's two subtractions. `can_manage` is false at
    # equal rank and above, so an Admin, an Owner, and a TechFM OA peer are all
    # out of reach -- no special case implements this.
    actor = _create_user(db, roles.ROLE_TECHFM_OA)

    for target_role in (roles.ROLE_ADMIN, roles.ROLE_OWNER, roles.ROLE_TECHFM_OA):
        target = _create_user(db, target_role)
        with pytest.raises(HTTPException) as exc:
            update_user_role_route(
                target.id,
                UserRoleUpdate(role=roles.ROLE_SUPERVISOR),
                actor=actor,
                db=db,
            )
        assert exc.value.status_code == 403
        db.refresh(target)
        assert target.role == target_role


def test_techfm_oa_cannot_hand_out_admin_or_owner(db):
    # The other half of the rule: the actor must outrank the role being
    # *assigned*, not just the one the target holds.
    actor = _create_user(db, roles.ROLE_TECHFM_OA)
    target = _create_user(db, roles.ROLE_TECHNICIAN)

    for role in (roles.ROLE_ADMIN, roles.ROLE_OWNER, roles.ROLE_TECHFM_OA):
        with pytest.raises(HTTPException) as exc:
            update_user_role_route(
                target.id, UserRoleUpdate(role=role), actor=actor, db=db
            )
        assert exc.value.status_code == 403

    db.refresh(target)
    assert target.role == roles.ROLE_TECHNICIAN


def test_techfm_oa_can_re_role_subordinates(db):
    actor = _create_user(db, roles.ROLE_TECHFM_OA)
    target = _create_user(db, roles.ROLE_TECHNICIAN)

    promoted = update_user_role_route(
        target.id,
        UserRoleUpdate(role=roles.ROLE_SUPERVISOR),
        actor=actor,
        db=db,
    )
    assert promoted.role == roles.ROLE_SUPERVISOR


def test_admin_can_promote_a_supervisor_to_techfm_oa(db):
    # The counterpart to the rank choice: Admins must retain control of these
    # accounts, which is exactly what a shared Admin rank would have broken.
    admin = _create_user(db, roles.ROLE_ADMIN)
    target = _create_user(db, roles.ROLE_SUPERVISOR)

    promoted = update_user_role_route(
        target.id,
        UserRoleUpdate(role=roles.ROLE_TECHFM_OA),
        actor=admin,
        db=db,
    )
    assert promoted.role == roles.ROLE_TECHFM_OA
