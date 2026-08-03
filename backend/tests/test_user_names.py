"""Human-name validation, persistence, and legacy remediation."""

import os
import sys
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import roles
from app.domain.errors import InvalidUserNameError
from app.models import User
from app.schemas.users import UserCreate, UserNameUpdate, UserResponse
from app.routers.users import update_user_name as update_user_name_route
from app.services import auth
from app.services import users as users_service


def test_user_create_trims_required_names():
    payload = UserCreate(
        username="  field-tech  ",
        first_name="  Jamie  ",
        last_name="  Rivera  ",
        password="hunter2",
        role=roles.ROLE_TECHNICIAN,
    )

    assert payload.username == "field-tech"
    assert payload.first_name == "Jamie"
    assert payload.last_name == "Rivera"


@pytest.mark.parametrize("field", ["first_name", "last_name"])
def test_user_create_rejects_blank_names(field):
    values = {
        "username": "field-tech",
        "first_name": "Jamie",
        "last_name": "Rivera",
        "password": "hunter2",
        "role": roles.ROLE_TECHNICIAN,
    }
    values[field] = "   "
    with pytest.raises(ValidationError):
        UserCreate(**values)


def test_name_update_requires_both_names():
    with pytest.raises(ValidationError):
        UserNameUpdate(first_name="Jamie", last_name=" ")


def test_legacy_full_name_uses_neutral_placeholder():
    user = User(username="private-login", first_name=None, last_name=None)
    assert user.full_name == "Name unavailable"


def test_create_and_update_user_names(db):
    user = users_service.create_user(
        db,
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name="Jamie",
        last_name="Rivera",
        password_hash=auth.hash_password("hunter2"),
        role=roles.ROLE_TECHNICIAN,
    )
    assert user.full_name == "Jamie Rivera"

    updated = users_service.update_name(
        db,
        user.id,
        first_name="Jordan",
        last_name="Lee",
    )
    response = UserResponse.model_validate(updated)
    assert response.first_name == "Jordan"
    assert response.last_name == "Lee"
    assert response.full_name == "Jordan Lee"


def test_service_strips_names_and_rejects_blank_parts(db):
    user = users_service.create_user(
        db,
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name="  Jamie ",
        last_name=" Rivera  ",
        password_hash=auth.hash_password("hunter2"),
        role=roles.ROLE_TECHNICIAN,
    )
    assert user.first_name == "Jamie"
    assert user.last_name == "Rivera"

    with pytest.raises(InvalidUserNameError):
        users_service.update_name(
            db,
            user.id,
            first_name="   ",
            last_name="Smith",
        )


def _create_user(db, role):
    return users_service.create_user(
        db,
        username=f"u-{uuid.uuid4().hex[:10]}",
        first_name="Existing",
        last_name="User",
        password_hash=auth.hash_password("hunter2"),
        role=role,
    )


def test_user_can_update_own_name(db):
    user = _create_user(db, roles.ROLE_TECHNICIAN)
    updated = update_user_name_route(
        user.id,
        UserNameUpdate(first_name="Self", last_name="Service"),
        actor=user,
        db=db,
    )
    assert updated.full_name == "Self Service"


def test_manager_can_update_subordinate_name_but_peer_cannot(db):
    owner = _create_user(db, roles.ROLE_OWNER)
    first_tech = _create_user(db, roles.ROLE_TECHNICIAN)
    second_tech = _create_user(db, roles.ROLE_TECHNICIAN)

    updated = update_user_name_route(
        first_tech.id,
        UserNameUpdate(first_name="Managed", last_name="Technician"),
        actor=owner,
        db=db,
    )
    assert updated.full_name == "Managed Technician"

    with pytest.raises(HTTPException) as exc:
        update_user_name_route(
            first_tech.id,
            UserNameUpdate(first_name="Peer", last_name="Edit"),
            actor=second_tech,
            db=db,
        )
    assert exc.value.status_code == 403
