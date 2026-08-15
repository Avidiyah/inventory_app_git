"""Tests for VAPID keypair generation.

Layer: unit (no DB, no HTTP client), matching `test_health_check.py`.

These assert interoperability, not cryptography. The failure they guard against
is quiet and expensive: a keypair that looks fine, is accepted by our own code,
and is then rejected by every browser -- because the public half was serialized
in the wrong form. Browsers need the raw uncompressed P-256 point (65 bytes,
leading 0x04), not DER, not PEM, not a compressed point. Nothing else in this
repo would notice the difference until a real device silently failed to
subscribe.
"""

import base64
import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from scripts.generate_vapid_keys import generate_vapid_keypair


def _b64url_decode(value: str) -> bytes:
    # Restore the padding that the URL-safe, unpadded encoding strips.
    return base64.urlsafe_b64decode(value + "=" * (-len(value) % 4))


def test_the_public_key_is_a_raw_uncompressed_p256_point():
    _private, public = generate_vapid_keypair()
    raw = _b64url_decode(public)

    # 1 marker byte + 32-byte X + 32-byte Y -- exactly what
    # `pushManager.subscribe({applicationServerKey})` requires.
    assert len(raw) == 65
    assert raw[0] == 0x04


def test_both_halves_are_url_safe_base64_without_padding():
    private, public = generate_vapid_keypair()

    for value in (private, public):
        assert "=" not in value
        assert "+" not in value
        assert "/" not in value


def test_each_call_produces_a_different_keypair():
    first_private, first_public = generate_vapid_keypair()
    second_private, second_public = generate_vapid_keypair()

    assert first_private != second_private
    assert first_public != second_public


def test_the_private_key_loads_in_the_library_that_will_sign_with_it():
    # The round-trip that matters: our serialization must be readable by the
    # exact code path `pywebpush` uses to sign, or every send fails at runtime
    # with a key that passed every test above.
    from py_vapid import Vapid02

    private, _public = generate_vapid_keypair()
    vapid = Vapid02.from_string(private)

    headers = vapid.sign({
        "aud": "https://fcm.googleapis.com",
        "sub": "mailto:ops@example.com",
    })

    authorization = headers["Authorization"]
    assert isinstance(authorization, str) and authorization
    # A JWT: header.payload.signature. Asserted structurally rather than by
    # prefix, which differs between the VAPID drafts the library supports.
    assert authorization.count(".") == 2
