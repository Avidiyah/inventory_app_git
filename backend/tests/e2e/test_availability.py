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
