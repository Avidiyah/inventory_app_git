"""Tests for pure Web Push policy.

Layer: pure unit (no DB, no HTTP, no pywebpush), matching the other `domain/`
test files.

Two disasters are guarded here.

`test_no_status_other_than_404_or_410_can_ever_delete_a_subscription` -- one
mistyped VAPID key makes every push service answer 401. Code that treats "any
4xx" as "this subscription is dead" would empty the entire table in a single
pass, and every user would have to opt in again on every device with nothing
explaining why.

`test_internal_and_metadata_addresses_are_rejected` -- `POST
/push/subscriptions` hands the server a URL and asks it to make a request. With
no allowlist that is a blind SSRF primitive pointed at Render's internal
network, and cloud metadata endpoints are the classic target.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import pytest

from app.domain.push import (
    PUSH_CONFIGURATION_ERROR,
    PUSH_DROP_SUBSCRIPTION,
    PUSH_OK,
    PUSH_PAYLOAD_TOO_LARGE,
    PUSH_RETRY,
    classify_push_response,
    is_allowed_push_endpoint,
)


# --------------------------------------------------------------------------
# Response classification
# --------------------------------------------------------------------------

@pytest.mark.parametrize("status", [200, 201, 202, 204])
def test_2xx_is_a_successful_delivery(status):
    assert classify_push_response(status) == PUSH_OK


@pytest.mark.parametrize("status", [404, 410])
def test_only_404_and_410_mean_the_subscription_is_gone(status):
    # 404: the push service does not recognise the endpoint.
    # 410 Gone: the subscription was explicitly revoked.
    # These are the ONLY statuses that say anything about the subscription.
    assert classify_push_response(status) == PUSH_DROP_SUBSCRIPTION


@pytest.mark.parametrize("status", [401, 403])
def test_auth_failures_are_our_problem_not_the_subscriptions(status):
    # Our VAPID JWT was rejected. Equally true of every other subscription in
    # the table, so it must never be read as a property of this one.
    assert classify_push_response(status) == PUSH_CONFIGURATION_ERROR


def test_413_is_reported_distinctly():
    assert classify_push_response(413) == PUSH_PAYLOAD_TOO_LARGE


@pytest.mark.parametrize("status", [429, 500, 502, 503, 504])
def test_throttling_and_server_errors_are_retryable(status):
    assert classify_push_response(status) == PUSH_RETRY


def test_an_unrecognised_4xx_is_never_retried_and_never_deletes():
    # Fail closed both ways: do not destroy data we have no evidence is bad,
    # and do not hammer a push service over an error that will not self-heal.
    assert classify_push_response(400) == PUSH_CONFIGURATION_ERROR
    assert classify_push_response(451) == PUSH_CONFIGURATION_ERROR


def test_no_status_other_than_404_or_410_can_ever_delete_a_subscription():
    for status in range(200, 600):
        if status in (404, 410):
            continue
        assert classify_push_response(status) != PUSH_DROP_SUBSCRIPTION, (
            f"status {status} must not delete a subscription"
        )


# --------------------------------------------------------------------------
# Endpoint allowlist (SSRF guard)
# --------------------------------------------------------------------------

@pytest.mark.parametrize("endpoint", [
    "https://fcm.googleapis.com/fcm/send/abc123",
    "https://fcm.googleapis.com/wp/abc123",
    "https://web.push.apple.com/QABC123",
    "https://updates.push.services.mozilla.com/wpush/v2/abc",
])
def test_real_push_service_endpoints_are_allowed(endpoint):
    assert is_allowed_push_endpoint(endpoint) is True


@pytest.mark.parametrize("endpoint", [
    "http://169.254.169.254/latest/meta-data/",
    "https://169.254.169.254/latest/meta-data/",
    "http://localhost:8124/db-test",
    "https://127.0.0.1/",
    "http://10.0.0.5/internal",
    "https://metadata.google.internal/computeMetadata/v1/",
])
def test_internal_and_metadata_addresses_are_rejected(endpoint):
    assert is_allowed_push_endpoint(endpoint) is False


@pytest.mark.parametrize("endpoint", [
    "https://evil.com/fcm.googleapis.com",
    "https://notfcm.googleapis.com/x",
    "https://fcm.googleapis.com.evil.com/x",
    "https://push.apple.com.attacker.net/x",
])
def test_lookalike_hosts_are_rejected(endpoint):
    # Suffix matching must require a literal dot boundary, or
    # `notfcm.googleapis.com` slips through.
    assert is_allowed_push_endpoint(endpoint) is False


def test_plain_http_is_rejected_even_for_an_allowed_host():
    assert is_allowed_push_endpoint("http://fcm.googleapis.com/fcm/send/x") is False


@pytest.mark.parametrize("endpoint", [
    "",
    "   ",
    "not-a-url",
    "ftp://fcm.googleapis.com/x",
    "https://user:pass@fcm.googleapis.com/x",
    "//fcm.googleapis.com/x",
])
def test_malformed_and_credentialed_urls_are_rejected(endpoint):
    assert is_allowed_push_endpoint(endpoint) is False
