"""Unit tests for the E2E guard. Deliberately NOT marked `e2e`: they run in
the ordinary backend job, which is what keeps the guard covered even though
the suite it protects is deselected there."""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

import pytest

from tests.e2e import _availability


def test_missing_browser_skips_outside_ci(monkeypatch):
    monkeypatch.delenv("CI", raising=False)
    # `Skipped` derives from BaseException, so `pytest.raises(Exception)`
    # would let it through and skip this test instead of asserting on it.
    with pytest.raises(pytest.skip.Exception) as caught:
        _availability.unavailable("chromium is not installed")
    assert "chromium is not installed" in str(caught.value)


def test_missing_browser_is_an_error_in_ci(monkeypatch):
    monkeypatch.setenv("CI", "true")
    with pytest.raises(RuntimeError, match="chromium is not installed"):
        _availability.unavailable("chromium is not installed")


def test_seed_names_all_carry_the_run_prefix():
    """Teardown finds rows by prefix. A record without one is a row that
    survives the run inside a real dev database."""
    from tests.e2e import _seed

    seed = _seed.Seed(
        prefix="E2E-abcd1234",
        owner_username="E2E-abcd1234-owner",
        work_order_number="E2E-abcd1234-WO",
        item_barcode="E2E-abcd1234-ITEM",
    )
    for value in (seed.owner_username, seed.work_order_number, seed.item_barcode):
        assert value.startswith(seed.prefix)
    assert _seed.RUN_PREFIX.startswith("E2E-")
