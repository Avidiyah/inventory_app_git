"""The request-scoped crossing buffer.

Two things are worth pinning: that what gets buffered is plain values
(anything lazy would raise `DetachedInstanceError` in the background task
that eventually reads it), and that the buffer is per-context, so one
request's crossings can never be delivered on another's response.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import contextvars
import uuid
from decimal import Decimal
from types import SimpleNamespace

import pytest

from app.services import low_stock


@pytest.fixture(autouse=True)
def _clean_buffer():
    """Drain before and after so a leaked entry fails its own test rather
    than the next one."""
    low_stock.drain()
    yield
    low_stock.drain()


def _item(quantity="5", threshold=6, name="Blue Tape"):
    return SimpleNamespace(
        id=uuid.uuid4(),
        name=name,
        quantity=Decimal(quantity),
        low_stock_threshold=threshold,
    )


def test_a_crossing_is_buffered_with_pushes_true():
    item = _item(quantity="5")
    low_stock.record(item, quantity_before=Decimal("7"))
    crossings = low_stock.drain()
    assert len(crossings) == 1
    assert crossings[0].pushes is True
    assert crossings[0].name == "Blue Tape"
    assert crossings[0].item_id == item.id


def test_an_already_low_item_buffers_nothing():
    """Membership did not change, so there is neither a push to send nor a
    page to invalidate. This is the noise case the whole edge rule exists
    for."""
    item = _item(quantity="4")
    low_stock.record(item, quantity_before=Decimal("5"))
    assert low_stock.drain() == []


def test_leaving_the_low_set_is_buffered_with_pushes_false():
    item = _item(quantity="9")
    low_stock.record(item, quantity_before=Decimal("2"))
    crossings = low_stock.drain()
    assert len(crossings) == 1
    assert crossings[0].pushes is False


def test_a_write_that_changes_nothing_relevant_buffers_nothing():
    item = _item(quantity="9")
    low_stock.record(item, quantity_before=Decimal("10"))
    assert low_stock.drain() == []


def test_quantity_is_buffered_as_a_display_string():
    """`Decimal("5.000")` on a lock screen reads as a bug. The background
    task receives text, already formatted, because it cannot format
    anything itself without the session."""
    item = _item(quantity="5.000")
    low_stock.record(item, quantity_before=Decimal("7"))
    assert low_stock.drain()[0].quantity == "5"


def test_a_threshold_raise_crosses_without_stock_moving():
    item = _item(quantity="10", threshold=20)
    low_stock.record(item, quantity_before=Decimal("10"), threshold_before=6)
    crossings = low_stock.drain()
    assert len(crossings) == 1
    assert crossings[0].pushes is True


def test_draining_empties_the_buffer():
    low_stock.record(_item(quantity="5"), quantity_before=Decimal("7"))
    assert len(low_stock.drain()) == 1
    assert low_stock.drain() == []


def test_the_buffer_does_not_leak_between_contexts():
    """A copied context is what each request (and each threadpool call
    into a sync handler) actually runs in. Recording inside one must be
    invisible outside it."""
    def _record_in_here():
        low_stock.record(_item(quantity="5"), quantity_before=Decimal("7"))
        return len(low_stock.drain())

    assert contextvars.copy_context().run(_record_in_here) == 1
    assert low_stock.drain() == []


def test_the_buffer_is_bounded():
    """A non-HTTP caller (a script, a job) never drains. The cap stops an
    unbounded list rather than pretending that case cannot happen."""
    for _ in range(low_stock.MAX_BUFFERED_CROSSINGS + 10):
        low_stock.record(_item(quantity="5"), quantity_before=Decimal("7"))
    assert len(low_stock.drain()) == low_stock.MAX_BUFFERED_CROSSINGS
