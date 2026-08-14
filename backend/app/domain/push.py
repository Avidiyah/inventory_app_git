"""Pure Web Push policy -- no I/O, no pywebpush, no SQLAlchemy.

Layer: domain, alongside `domain/realtime.py`. Everything here is a decision
that can be made without talking to anything, which is what makes it testable
without a database or a network.

Both functions guard a specific disaster rather than merely tidying logic, and
each docstring names the one it guards.
"""

from urllib.parse import urlsplit

__all__ = [
    "PUSH_OK",
    "PUSH_DROP_SUBSCRIPTION",
    "PUSH_CONFIGURATION_ERROR",
    "PUSH_PAYLOAD_TOO_LARGE",
    "PUSH_RETRY",
    "ALLOWED_PUSH_HOSTS",
    "classify_push_response",
    "is_allowed_push_endpoint",
]

# --- response classification -------------------------------------------

# Delivered. The push service has accepted responsibility for the message.
PUSH_OK = "ok"

# This subscription is dead. Delete the row -- do not disable it, do not retry.
# Reached by 404 and 410 and by nothing else, ever.
PUSH_DROP_SUBSCRIPTION = "drop_subscription"

# We are misconfigured. True of every message, not of one subscription.
# Never deletes anything; should alert.
PUSH_CONFIGURATION_ERROR = "configuration_error"

# We sent something too big. Split out from the generic configuration error so
# it is distinguishable in logs at a glance.
PUSH_PAYLOAD_TOO_LARGE = "payload_too_large"

# Transient. Back off and try again within a bounded budget.
PUSH_RETRY = "retry"


def classify_push_response(status_code: int) -> str:
    """What a push service's HTTP status means for the subscription.

    The split that matters is inside the 4xx range, and it is the opposite of
    the intuitive reading. `404` and `410` are statements about the
    *subscription*: the endpoint is unknown or explicitly revoked, so the row
    is worthless. `401` and `403` are statements about *us*: our VAPID JWT was
    rejected, which is equally true for every other row in the table.

    Collapsing those cases into "any 4xx means delete" empties the subscription
    table on the first key misconfiguration, and every user would have to opt
    in again on every device with nothing explaining why.
    `tests/test_push_domain.py` asserts exhaustively that no status outside
    {404, 410} reaches the delete branch.

    Order is significant: specific statuses are matched before the generic 4xx
    fallback.
    """
    if 200 <= status_code < 300:
        return PUSH_OK
    if status_code in (404, 410):
        return PUSH_DROP_SUBSCRIPTION
    if status_code in (401, 403):
        return PUSH_CONFIGURATION_ERROR
    if status_code == 413:
        return PUSH_PAYLOAD_TOO_LARGE
    if status_code == 429:
        return PUSH_RETRY
    if 400 <= status_code < 500:
        # Unrecognised client error. Fail closed both ways: no evidence the
        # subscription is bad, and a 4xx will not fix itself on retry.
        return PUSH_CONFIGURATION_ERROR
    return PUSH_RETRY


# --- endpoint allowlist -------------------------------------------------

# Registration hands the server a URL and later asks it to POST there. Without
# this allowlist that is a blind SSRF primitive inside the hosting provider's
# network. These are the only hosts a browser can legitimately produce.
ALLOWED_PUSH_HOSTS: tuple[str, ...] = (
    "fcm.googleapis.com",          # Chrome, Edge
    "push.apple.com",              # Safari (web.push.apple.com and friends)
    "push.services.mozilla.com",   # Firefox
)


def is_allowed_push_endpoint(endpoint: str) -> bool:
    """Whether `endpoint` is a URL we are willing to send a push request to.

    Deliberately an allowlist rather than a denylist of private ranges. A
    denylist has to anticipate every internal address, every DNS rebinding
    trick, and every IPv6 spelling; an allowlist only has to name the three
    push services that exist. A new browser is then a reviewable one-line
    change to the tuple above rather than a silent hole.

    Suffix matching requires a literal dot boundary, so `notfcm.googleapis.com`
    and `fcm.googleapis.com.evil.com` are both rejected. HTTPS is mandatory,
    and embedded credentials are refused outright -- a browser never produces
    them, so their presence means the value did not come from one.
    """
    if not endpoint or not endpoint.strip():
        return False

    try:
        parsed = urlsplit(endpoint.strip())
        # Both of these parse `netloc`, so they share the try: a malformed
        # authority raises here rather than returning something misleading.
        if parsed.username is not None or parsed.password is not None:
            return False
        host = parsed.hostname
    except ValueError:
        return False

    if parsed.scheme != "https":
        return False
    if not host:
        return False

    host = host.lower()
    return any(
        host == allowed or host.endswith("." + allowed)
        for allowed in ALLOWED_PUSH_HOSTS
    )
