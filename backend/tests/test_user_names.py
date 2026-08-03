"""Human-name validation, persistence, and legacy remediation."""

import os
import sys
import uuid

import pytest
from fastapi import HTTPException
from pydantic import ValidationError

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.domain import roles
from app.domain.errors import (
    DuplicateUsernameError,
    InvalidCredentialsError,
    InvalidUserNameError,
    InvalidUsernameError,
)
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


def test_name_update_accepts_and_trims_an_optional_username():
    # Omitted entirely -> the login name is left alone.
    assert UserNameUpdate(first_name="Jamie", last_name="Rivera").username is None
    payload = UserNameUpdate(
        first_name="Jamie",
        last_name="Rivera",
        username="  field-tech  ",
    )
    assert payload.username == "field-tech"
    with pytest.raises(ValidationError):
        UserNameUpdate(first_name="Jamie", last_name="Rivera", username="   ")


def test_update_name_changes_the_login_username(db):
    user = _create_user(db, roles.ROLE_TECHNICIAN)
    original = user.username
    new_username = f"u-{uuid.uuid4().hex[:10]}"

    updated = users_service.update_name(
        db,
        user.id,
        first_name="Jamie",
        last_name="Rivera",
        username=new_username,
    )
    assert updated.username == new_username

    # The new name is the one that authenticates; the old one is free again.
    assert auth.authenticate(db, username=new_username, password="hunter2").id == user.id
    with pytest.raises(InvalidCredentialsError):
        auth.authenticate(db, username=original, password="hunter2")


def test_update_name_leaves_username_alone_when_omitted(db):
    user = _create_user(db, roles.ROLE_TECHNICIAN)
    original = user.username

    updated = users_service.update_name(
        db, user.id, first_name="Jamie", last_name="Rivera"
    )
    assert updated.username == original


def test_username_change_rejects_a_duplicate(db):
    taken = _create_user(db, roles.ROLE_TECHNICIAN)
    user = _create_user(db, roles.ROLE_TECHNICIAN)

    with pytest.raises(DuplicateUsernameError):
        users_service.update_name(
            db,
            user.id,
            first_name="Jamie",
            last_name="Rivera",
            username=taken.username,
        )

    # The rollback leaves the account usable under its original name.
    db.refresh(user)
    assert auth.authenticate(db, username=user.username, password="hunter2").id == user.id


def test_username_change_rejects_blank(db):
    user = _create_user(db, roles.ROLE_TECHNICIAN)

    with pytest.raises(InvalidUsernameError):
        users_service.update_name(
            db, user.id, first_name="Jamie", last_name="Rivera", username="   "
        )


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
