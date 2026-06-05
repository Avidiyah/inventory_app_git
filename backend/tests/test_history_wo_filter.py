"""Tests for the work-order LIKE-pattern builder used by
`app.services.history.list_history`.

Pure helper, no DB -- consistent with the rest of this suite. The
helper is the single source of truth for:

- "no filter" cases (None / empty / whitespace-only),
- case-sensitive substring matching (`%value%`),
- escaping the two SQL LIKE wildcards (`%`, `_`) and the escape
  character itself (`\\`) so a literal `%` in the user input doesn't
  silently widen the match.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from app.services.history import _build_wo_like_pattern


def test_none_returns_no_filter():
    assert _build_wo_like_pattern(None) is None


def test_empty_string_returns_no_filter():
    assert _build_wo_like_pattern("") is None


def test_whitespace_only_returns_no_filter():
    assert _build_wo_like_pattern("   ") is None
    assert _build_wo_like_pattern("\t\n") is None


def test_plain_value_wraps_in_substring_pattern():
    pattern, escape_char = _build_wo_like_pattern("WO123")
    assert pattern == "%WO123%"
    assert escape_char == "\\"


def test_value_is_trimmed():
    pattern, _ = _build_wo_like_pattern("  WO123  ")
    assert pattern == "%WO123%"


def test_percent_in_input_is_escaped():
    # User typed "50%" -- must match literal percent, not "anything".
    pattern, escape_char = _build_wo_like_pattern("50%")
    assert pattern == "%50\\%%"
    assert escape_char == "\\"


def test_underscore_in_input_is_escaped():
    pattern, _ = _build_wo_like_pattern("WO_42")
    assert pattern == "%WO\\_42%"


def test_backslash_in_input_is_escaped_first():
    # Escape the escape character before the wildcards, otherwise we
    # would double-escape any backslash introduced by the wildcard pass.
    pattern, _ = _build_wo_like_pattern("a\\b")
    assert pattern == "%a\\\\b%"


def test_combined_wildcards_and_backslash():
    pattern, _ = _build_wo_like_pattern("a\\b%c_d")
    # Backslash escaped first -> a\\b%c_d ; then % -> a\\b\%c_d ;
    # then _ -> a\\b\%c\_d ; then wrap.
    assert pattern == "%a\\\\b\\%c\\_d%"
