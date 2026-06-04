"""Unit tests for password hashing (pure, no DB).

These exercise `app.services.auth.hash_password` / `verify_password`
directly. Importing the module pulls in `app.models`, which is fine;
nothing here touches the database.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services import auth


def test_hash_round_trip():
    h = auth.hash_password("hunter2")
    assert auth.verify_password("hunter2", h) is True


def test_wrong_password_rejected():
    h = auth.hash_password("hunter2")
    assert auth.verify_password("Hunter2", h) is False  # case-sensitive
    assert auth.verify_password("nope", h) is False


def test_salt_makes_hashes_unique():
    assert auth.hash_password("same") != auth.hash_password("same")


def test_hash_is_self_describing_scrypt():
    h = auth.hash_password("abcd")
    assert h.startswith("scrypt$")
    assert len(h.split("$")) == 6


def test_malformed_hash_fails_closed():
    assert auth.verify_password("anything", "not-a-real-hash") is False
    assert auth.verify_password("anything", "") is False
