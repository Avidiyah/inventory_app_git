"""Offline tests for NetFacilities cloud-session encryption at rest (D9)."""

from __future__ import annotations

import pytest
from cryptography.fernet import Fernet

from app.services import netfacilities_cloud_crypto as crypto


VALID_KEY = Fernet.generate_key().decode("ascii")


def test_encrypt_then_decrypt_round_trips(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", VALID_KEY)
    token = crypto.encrypt_storage_state('{"cookies": []}')
    assert crypto.decrypt_storage_state(token) == '{"cookies": []}'


def test_is_configured_true_with_valid_key(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", VALID_KEY)
    assert crypto.is_configured() is True


def test_is_configured_false_when_unset(monkeypatch):
    monkeypatch.delenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", raising=False)
    assert crypto.is_configured() is False


def test_encrypt_raises_when_key_missing(monkeypatch):
    monkeypatch.delenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", raising=False)
    with pytest.raises(crypto.NetFacilitiesCloudCryptoUnavailable):
        crypto.encrypt_storage_state("{}")


def test_encrypt_raises_when_key_malformed(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", "not-a-fernet-key")
    with pytest.raises(crypto.NetFacilitiesCloudCryptoUnavailable):
        crypto.encrypt_storage_state("{}")


def test_decrypt_raises_when_token_was_encrypted_with_a_different_key(monkeypatch):
    monkeypatch.setenv("NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY", VALID_KEY)
    token = crypto.encrypt_storage_state("{}")
    monkeypatch.setenv(
        "NETFACILITIES_CLOUD_SESSION_ENCRYPTION_KEY",
        Fernet.generate_key().decode("ascii"),
    )
    with pytest.raises(crypto.NetFacilitiesCloudCryptoUnavailable):
        crypto.decrypt_storage_state(token)
