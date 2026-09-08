"""The two stock edges a Material Request lives on.

Pure, like `test_low_stock_domain.py`: numbers in, bool out, no session.
The interesting cases are the boundaries -- exact zero and a negative
count (Scan / Stock records real usage past the recorded balance).
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from decimal import Decimal

import pytest

from app.domain import material_requests as policy


@pytest.mark.parametrize(
    "before,after",
    [("0", "1"), ("0", "0.5"), ("-3", "1"), ("-3", "0.01")],
)
def test_restocked_is_the_edge_from_nonpositive_to_positive(before, after):
    assert policy.restocked(Decimal(before), Decimal(after)) is True


@pytest.mark.parametrize(
    "before,after",
    [("1", "5"), ("0", "0"), ("-2", "0"), ("-2", "-1"), ("5", "0"), ("5", "4")],
)
def test_restocked_ignores_every_other_move(before, after):
    assert policy.restocked(Decimal(before), Decimal(after)) is False


@pytest.mark.parametrize(
    "before,after",
    [("1", "0"), ("5", "-2"), ("0.5", "0")],
)
def test_went_out_is_the_edge_from_positive_to_nonpositive(before, after):
    assert policy.went_out(Decimal(before), Decimal(after)) is True


@pytest.mark.parametrize(
    "before,after",
    [("0", "1"), ("0", "-1"), ("5", "3"), ("0", "0"), ("-1", "-2")],
)
def test_went_out_ignores_every_other_move(before, after):
    assert policy.went_out(Decimal(before), Decimal(after)) is False


def test_the_two_edges_never_both_fire():
    for before in ("-2", "0", "1"):
        for after in ("-2", "0", "1"):
            b, a = Decimal(before), Decimal(after)
            assert not (policy.restocked(b, a) and policy.went_out(b, a))


def test_the_vocabulary_is_shared_with_the_queue_service():
    from app.services import user_requests as request_service

    assert policy.REQUEST_MATERIAL == "material_request"
    assert policy.STATUS_STOCKED == "stocked"
    assert request_service.STATUS_STOCKED is policy.STATUS_STOCKED
    assert request_service.STATUS_OPEN is policy.STATUS_OPEN
    assert request_service.STATUS_RESOLVED is policy.STATUS_RESOLVED
    assert request_service.REQUEST_MATERIAL is policy.REQUEST_MATERIAL
    assert request_service.EDITABLE_DETAILS[policy.REQUEST_MATERIAL] == frozenset(
        {"quantity", "product_link", "note"}
    )
