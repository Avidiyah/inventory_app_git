"""The daily report's four status buckets and the distribution built on them.

Layer: services (pure -- no session, no clock). Split out of
`work_order_report.py` so that module stays under the 500-line rule, and so
the workbook renderer can import the bucket table without dragging the
section queries along.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md
(§2, E1-E3, E8).

**One table, consumed everywhere (E2).** `REPORT_BUCKETS` is the only place
the seven lifecycle statuses collapse to the four states an Admin acts on.
The aggregator and both renderers read it; the import-time check below turns
an eighth status into a startup failure instead of a slice that silently
vanishes from every pie.

**Closed is not a status (§2.1).** Every stored status is live; a closed work
order is an archived row. So `bucket_of` maps live statuses only, and
`row_bucket` decides Closed from `archived_at` before it looks at status.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Optional, Protocol

from app.domain import work_orders as wo

BUCKET_ACCEPTED = "accepted"
BUCKET_IN_PROGRESS = "in_progress"
BUCKET_READY_TO_CLOSE = "ready_to_close"
BUCKET_CLOSED = "closed"


@dataclass(frozen=True)
class Bucket:
    key: str
    label: str
    statuses: tuple[str, ...]


# Lifecycle order: every legend, every table header, and every pie's
# clockwise order from 12 o'clock. Never alphabetical, never largest-first --
# a small-multiple grid whose slice order shifts per card cannot be read (§2).
REPORT_BUCKETS: tuple[Bucket, ...] = (
    Bucket(BUCKET_ACCEPTED, "Accepted", (wo.STATUS_CREATED,)),
    Bucket(
        BUCKET_IN_PROGRESS,
        "In progress",
        (wo.STATUS_ASSIGNED, wo.STATUS_IN_PROGRESS, wo.STATUS_ON_HOLD),
    ),
    Bucket(
        BUCKET_READY_TO_CLOSE,
        "Ready to close",
        (wo.STATUS_READY_TO_COMPLETE, wo.STATUS_COMPLETED, wo.STATUS_REVIEW),
    ),
    # Decided by `archived_at`, not by status -- see `row_bucket`.
    Bucket(BUCKET_CLOSED, "Closed", ()),
)

BUCKET_KEYS: tuple[str, ...] = tuple(bucket.key for bucket in REPORT_BUCKETS)
BUCKET_LABELS: dict[str, str] = {bucket.key: bucket.label for bucket in REPORT_BUCKETS}

_STATUS_TO_BUCKET: dict[str, str] = {
    status: bucket.key for bucket in REPORT_BUCKETS for status in bucket.statuses
}

# The loud failure (E2): a status the table does not place, or places twice,
# stops the app at import rather than at the Admin's next download.
if set(_STATUS_TO_BUCKET) != set(wo.ALL_STATUSES) or sum(
    len(bucket.statuses) for bucket in REPORT_BUCKETS
) != len(wo.ALL_STATUSES):
    raise RuntimeError(
        "REPORT_BUCKETS must place every work-order status exactly once; "
        f"buckets cover {sorted(_STATUS_TO_BUCKET)}, "
        f"statuses are {sorted(wo.ALL_STATUSES)}"
    )


def bucket_of(status: str) -> str:
    """The bucket key for a *live* status. Raises on anything else."""
    try:
        return _STATUS_TO_BUCKET[status]
    except KeyError:
        raise ValueError(f"No report bucket for work-order status {status!r}") from None


class RowLike(Protocol):
    """What `distribution` reads. `ReportRow` satisfies it; so does any
    object with these five attributes."""

    status: str
    community: Optional[str]
    location: Optional[str]
    service_type: Optional[str]
    archived_at: Optional[object]


def row_bucket(row: RowLike) -> str:
    """Closed if the row is archived, else by status."""
    return BUCKET_CLOSED if row.archived_at is not None else bucket_of(row.status)


def empty_counts() -> dict[str, int]:
    return {key: 0 for key in BUCKET_KEYS}


@dataclass(frozen=True)
class ServiceTypeDistribution:
    key: str
    label: str
    total: int
    counts: dict[str, int]


@dataclass(frozen=True)
class CommunityDistribution:
    """One group's four-bucket counts plus the same counts re-cut by service
    type. Also used for the company as a whole (`key == COMPANY_KEY`)."""

    key: str
    label: str
    total: int
    counts: dict[str, int]
    service_types: list[ServiceTypeDistribution]


@dataclass(frozen=True)
class ReportDistribution:
    company: CommunityDistribution
    communities: list[CommunityDistribution]


COMPANY_KEY = "company"
COMPANY_LABEL = "Company"

OTHER_KEY = "__other__"
OTHER_LABEL = "Other"
GRID_SIZE = 9


def distribution(rows: Iterable[RowLike]) -> ReportDistribution:
    """Company x community x service type x bucket counts over `rows`.

    A pure function of the rows the report already fetched (E1): the pies and
    the Work Orders sheet cannot disagree because they are the same list.

    A row naming two communities is counted in both -- `community_memberships`
    is membership, not a tag -- so community totals do not sum to the company
    total. Service-type labels are chosen company-wide (smallest spelling by
    code point, as `services/hub.py` does) so one grouping key reads the same
    on every sheet."""
    groups: dict[str, dict[str, dict[str, int]]] = {
        key: {} for key in (COMPANY_KEY, *wo.ALL_COMMUNITY_FILTERS)
    }
    labels: dict[str, str] = {}
    for row in rows:
        bucket = row_bucket(row)
        service_key, service_label = wo.normalize_service_type(row.service_type)
        if service_key not in labels or service_label < labels[service_key]:
            labels[service_key] = service_label
        memberships = wo.community_memberships(row.community, row.location)
        for key in (COMPANY_KEY, *memberships):
            groups[key].setdefault(service_key, empty_counts())[bucket] += 1

    def build(key: str, label: str) -> CommunityDistribution:
        service_types = [
            ServiceTypeDistribution(
                key=service_key,
                label=labels[service_key],
                total=sum(counts.values()),
                counts=counts,
            )
            for service_key, counts in groups[key].items()
        ]
        service_types.sort(key=lambda entry: (-entry.total, entry.label.casefold()))
        counts = empty_counts()
        for entry in service_types:
            for bucket_key, count in entry.counts.items():
                counts[bucket_key] += count
        return CommunityDistribution(
            key=key,
            label=label,
            total=sum(counts.values()),
            counts=counts,
            service_types=service_types,
        )

    return ReportDistribution(
        company=build(COMPANY_KEY, COMPANY_LABEL),
        communities=[
            build(key, wo.COMMUNITY_LABELS[key]) for key in wo.ALL_COMMUNITY_FILTERS
        ],
    )


def grid_of(
    service_types: list[ServiceTypeDistribution],
) -> tuple[list[ServiceTypeDistribution], int]:
    """The small-multiple grid (E8): every service type when nine or fewer
    fit, otherwise the top eight plus an `Other` roll-up of the rest.

    Returns the cards and how many service types `Other` folded in (0 when it
    did not bite), so the sheet can say so rather than truncate silently."""
    if len(service_types) <= GRID_SIZE:
        return list(service_types), 0
    shown = service_types[: GRID_SIZE - 1]
    rest = service_types[GRID_SIZE - 1 :]
    counts = empty_counts()
    for entry in rest:
        for key, count in entry.counts.items():
            counts[key] += count
    other = ServiceTypeDistribution(
        key=OTHER_KEY, label=OTHER_LABEL, total=sum(counts.values()), counts=counts
    )
    return [*shown, other], len(rest)


def communities_of(row: RowLike) -> tuple[str, ...]:
    """The communities a row belongs to, as labels, in `ALL_COMMUNITY_FILTERS`
    order (E14).

    Membership, not the raw `community` column: that column is NULL on every
    imported row, and the location text is what the Graphs tab, the Work
    Orders filter, and `distribution` above already parse. Never empty --
    Academics is the fallback."""
    return tuple(
        wo.COMMUNITY_LABELS[key]
        for key in wo.community_memberships(row.community, row.location)
    )


def primary_community(row: RowLike) -> str:
    """The one community a row is attributed to when a figure must sum (E14):
    its first membership. Every row has exactly one, so dollars grouped by it
    are never counted twice."""
    return communities_of(row)[0]
