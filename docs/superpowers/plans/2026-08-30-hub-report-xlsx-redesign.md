# Hub Report Excel Redesign Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:executing-plans to implement this plan task-by-task (this repo's CLAUDE.md forbids subagents unless the user says otherwise, so subagent-driven-development needs an explicit go-ahead). Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Rebuild the `GET /hub/report/export` workbook as a designed `Report` overview, one four-slice-pie sheet per community, a readable deduped `Work Orders` sheet with Notes in column C, and the byte-identical re-importable `Data` sheet moved last.

**Architecture:** A new pure module (`work_order_report_buckets.py`) owns the four-bucket table and the company × community × service-type distribution, computed over the one E1 population (`all_rows` = live rows + rows closed this week) that `daily_report` now fetches uncapped. A new theme module (`_xlsx_theme.py`) owns fonts, palette, formats, tables, and chart construction/placement. `work_order_report_xlsx.py` is rewritten as sheet composition only and stays a pure function of `DailyReport`.

**Tech Stack:** Python 3 / FastAPI / SQLAlchemy 2 (existing), `openpyxl==3.1.5` (pinned, existing), pytest. Postgres on port 8801 for the DB-backed tests (`.env` holds `DATABASE_URL`).

**Spec:** `docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md` (E-numbers). Parents: `2026-08-30-hub-report-xlsx-export-design.md` (X-numbers), `2026-08-30-work-order-daily-report-design.md` (R-numbers).

## Global Constraints

- All code lives under `backend/`; run every command from `C:\Users\mcclu\Desktop\inventory_app_git\backend` with `venv/Scripts/python`.
- Keep every file under 500 lines (CLAUDE.md). If `work_order_report_xlsx.py` would cross it, moving `_report_sheet` and `_community_sheet` into `app/services/work_order_report_xlsx_charts.py` is pre-approved; nothing else moves.
- `report_xlsx` stays a pure function of `DailyReport` — no queries, no clock below `daily_report` (E13 / X3).
- `Data` sheet stays cell-for-cell equal to `report_csv` output, money-as-text included (E10 / X5). Do not touch `export_row`, `report_csv`, `report_filename`, or the route URL / Admin floor (§5).
- Bucket order everywhere is `Accepted, In progress, Ready to close, Closed` — never alphabetical, never largest-first (§2).
- Bucket palette (hex, no `#`): Accepted `9CA3AF`, In progress `D97706`, Ready to close `6D28D9`, Closed `15803D`. Brand red `C8102E` is never a slice (§4.0).
- Fonts: `Aptos Narrow` body 10; title 18 bold `C8102E`; subtitle 9 italic `5A5C60`; section 11 bold `1C1D20` with 1pt `D8D9DB` bottom rule; table header 10 bold white on `1C1D20` (§4.0).
- Number formats: counts `#,##0`, money `$#,##0.00` over `Decimal`, percent `0.0%` over real fractions, dates `yyyy-mm-dd hh:mm` (§4.0).
- Tab colors: `Report` `C8102E`; communities `5A5C60`; `Work Orders` `1C1D20`; `Data` `B7B9BC` (§4.0).
- Gridlines off on every sheet except `Data`; no merged cells; no conditional formatting, sparklines, slicers, macros, or doughnuts (§3 "not taken").
- Every chart sets `visible_cells_only = False` and reads the hidden `Chart Data` sheet (E7). Never render a pie whose total is 0 (§4.2).
- openpyxl cannot write tz-aware datetimes — convert to UTC and strip `tzinfo` before writing.
- Commit after each task with a plain `git commit` — **no `Co-Authored-By` trailer** (CLAUDE.md; `.claude/settings.json` has no `attribution.commit`). Do **not** push: pushing `main` deploys production; that is the user's call.
- Before the first edit: `git fetch origin && git status -sb` — local `main` often lags `origin/main`; if it does, stop and tell the user before editing.
- Work on `main` directly — no worktree, no feature branch (nine worktrees already exist; every change lands on `main` by the end). The spec and this plan are committed first, as their own `docs(specs)` commit, before Task 0's first code edit.
- Community, wherever the workbook names one, is `community_memberships(community, location)` (E14): the membership list (`communities_of`) for the `Work Orders` COMMUNITIES column, the primary (`primary_community`, first in `ALL_COMMUNITY_FILTERS` order) wherever money sums. Never the raw `community` column — it is NULL on every imported row.
- The nine service-type cards carry **no legend** (E15); the community status pie is the shared key.
- The `db`-backed tests run against a developer Postgres that may hold real rows: scope every count assertion to rows the test created. `test_cascade_deletes_with_user` failing on the dev DB is a known environmental failure, not a regression.

## Decisions this plan makes where the spec was silent or self-inconsistent

Read these before starting; they are deliberate and each is cited where it applies.

| # | Decision | Why |
|---|---|---|
| P1 | `distribution` is a **pure function over `all_rows`** (the E4 fetch), not a second columns-only query (E3's wording). | E4 already loads every live row with eager loads; a second query would double the work and open a window for the pies and the `Work Orders` sheet to disagree. E1 ("every pie, every table, and the Work Orders sheet count the same set") is satisfied by construction. Same numbers, one fetch, testable without a database. |
| P2 | Buckets + distribution live in a **new module `app/services/work_order_report_buckets.py`**, imported by both `work_order_report.py` and the renderer. | `work_order_report.py` is 324 lines; adding ~180 would break the 500-line rule. |
| P3 | Charts are **placed by cell range (`TwoCellAnchor`)**, not by centimetres. | The spec's 7.5 cm cards on an 11-character column pitch overlap the next anchor (3 × 11 chars ≈ 6 cm). A two-cell anchor fills exactly the cells named regardless of font metrics, which is what "column widths are fixed so the grid lines up" actually requires. Verified against openpyxl 3.1.5: `chart.anchor = TwoCellAnchor(...)` then `sheet.add_chart(chart)` writes `<twoCellAnchor>`. |
| P4 | Community sheet exact-value block sits at **F6:H10** (spec: E5:G9); the community pie fills **A6:D20**. | The pie ends at column D; E is one column of air. Block header aligns with the pie's top row. |
| P5 | **Eight** visible sheets + hidden `Chart Data` physically second-to-last, `Data` physically last. | The spec's "nine visible" counted the hidden sheet. Putting `Data` last in `sheetnames` keeps "Data is last" a one-line assertion. |
| P6 | `table_of` writes a styled header but **no Excel Table when there are zero data rows**. | Excel flags a header-only table as a file needing repair. The empty state line sits under the header instead. |
| P7 | The service-type grid shows **all** service types when there are ≤ 9; `Other` appears only when there are > 9 (top 8 + Other). | Folding a single service type into "Other" when nine fit is a lossless-but-silly card. |
| P8 | `Report`'s "By community" table sits at a **fixed** row 58. | Dollars are grouped by primary community (E14 / P9), so the dollars block is at most five rows (42–48) plus a one-line footnote; the chart beside it ends at row 56. Nothing can push row 58. |
| P9 | Dollars are grouped by **primary community** (`primary_community(row)`: first of `community_memberships(community, location)` in `ALL_COMMUNITY_FILTERS` order, Academics fallback), and the `Work Orders` sheet's column F is **COMMUNITIES** (`communities_of(row)`, `; `-joined). Never the raw `community` column. | Spec E14. The raw column is NULL on every NetFacilities-imported row (697 of 697 in the dev copy), so grouping by it yields one `(no community)` bar and a blank column. Primary attribution counts each row exactly once, which was the real concern — memberships double-count, money must not. |
| P10 | `ReportRow` gains `notes: Optional[str] = None` and `material_lines: int = 0`. | The `Work Orders` sheet needs both; neither was on the dataclass. Defaults keep every existing constructor call valid and neither reaches the JSON (`HubReportRow` does not declare them). |
| P11 | "Semibold" → `bold=True`. | openpyxl `Font` has no weight axis. |
| P12 | Slice-2 label is **"In progress"** — confirmed 2026-08-30 (spec §8, resolved). | One string in `REPORT_BUCKETS`, plus the test literals that quote it. |
| P13 | `STATUS_LABELS` (all seven) is defined once in `work_order_report.py`, copied from `static/views/hubReport.js`. | The spec wants "the page's own labels"; `services/hub.py::_GRAPH_STATUS_LABELS` is private and spells them differently ("In-Progress"). |
| P14 | The nine grid cards are built with `legend=None`; the community status pie above keeps `legend="r"`. | Spec E15. Nine identical four-entry legends on 7.5 × 6 cm cards are noise and cost a quarter of each card's height; E9 is carried by the detail table. A zip-level test counts `<legend>` parts. |
| P15 | `daily_report` always fetches `all_rows` and computes `distribution`, so the JSON page pays for the workbook's population. Accepted; Task 8 times it. No `include_rows` flag unless the timing says so. | Spec E16. One payload that cannot disagree with itself; same order of cost as the capped `closing` fetch. |
| P16 | Task 8 renders **two** sample workbooks: one from the developer database and one from a synthetic showcase payload built with the test fixtures. | The dev copy has no archived rows (0 of 697) and 91% of its live rows are `created`: on its own it never shows a Closed slice, a Closed series on Activity, or a non-zero Dollars chart, and every pie is mostly gray. Signing off on that alone is signing off on a design never seen working. |

## File structure

| File | Responsibility |
|---|---|
| **Create** `backend/app/services/work_order_report_buckets.py` | `REPORT_BUCKETS`, `bucket_of`, `row_bucket`, the three distribution dataclasses, `distribution(rows)`, `grid_of(service_types)`, `communities_of(row)`, `primary_community(row)`. Pure. |
| **Create** `backend/tests/test_work_order_report_buckets.py` | Pure tests for the above. |
| **Modify** `backend/app/services/work_order_report.py` | `STATUS_LABELS`; `ReportRow.notes` / `.material_lines`; `DailyReport.distribution` / `.all_rows`; `_live_rows`; `reading_order`; `daily_report` composes them. |
| **Modify** `backend/tests/test_work_order_report.py` | DB-backed tests for the E1 population and reading order. |
| **Create** `backend/app/services/_xlsx_theme.py` | Palette, fonts, formats, `setup_sheet`, `title_block`, `section`, `kpi`, `header_row`, `write_rows`, `table_of`, `empty_state`, `note`, `notes_row_height`, `pie_of`, `column_chart_of`, `place`. Pure. |
| **Create** `backend/tests/test_xlsx_theme.py` | Zip-level and unit tests for the theme helpers. |
| **Rewrite** `backend/app/services/work_order_report_xlsx.py` | `report_xlsx`, `report_xlsx_filename`, `XLSX_MEDIA_TYPE`, `SHEET_NAMES`, `_ChartData`, `_report_sheet`, `_community_sheet`, `_work_orders_sheet`, `_data_sheet`, `_community_money`, `_pie`, `_bucket_rows`, `_population_caveat`. |
| **Rewrite** `backend/tests/test_work_order_report_xlsx.py` | Payload fixtures + per-sheet tests + zip-level chart tests. |
| **Modify** `backend/app/routers/hub.py:252-270` | Docstring only. |
| **Modify** `backend/tests/test_hub_router.py:270-284` | Expected `sheetnames`. |
| **Modify** `docs/endpoint-map.md:1258-1261` | The workbook description. |

---

### Task 0: Sync check

**Files:** none.

- [ ] **Step 1: Confirm local main is current**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git && git fetch origin && git status -sb && git log --oneline -1 origin/main
```

Expected: `## main...origin/main` with no `[behind N]`. If behind, stop and report — do not edit.

- [ ] **Step 2: Baseline the existing suites**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git/backend && venv/Scripts/python -m pytest tests/test_work_order_report_xlsx.py tests/test_work_order_report.py tests/test_hub_router.py -q
```

Expected: all pass (xlsx: 10 passed). DB tests skip if Postgres is down — bring it up before Task 2.

---

### Task 1: The bucket table and the distribution (pure)

**Files:**
- Create: `backend/app/services/work_order_report_buckets.py`
- Test: `backend/tests/test_work_order_report_buckets.py`

**Interfaces:**
- Consumes: `app.domain.work_orders` — `ALL_STATUSES`, `STATUS_*`, `ALL_COMMUNITY_FILTERS`, `COMMUNITY_LABELS`, `community_memberships(community, location)`, `normalize_service_type(value) -> (key, label)`.
- Produces (later tasks rely on these exact names):
  - `BUCKET_ACCEPTED = "accepted"`, `BUCKET_IN_PROGRESS = "in_progress"`, `BUCKET_READY_TO_CLOSE = "ready_to_close"`, `BUCKET_CLOSED = "closed"`
  - `REPORT_BUCKETS: tuple[Bucket, ...]`, `BUCKET_KEYS: tuple[str, ...]`, `BUCKET_LABELS: dict[str, str]`
  - `bucket_of(status: str) -> str` (raises `ValueError`), `row_bucket(row) -> str`, `empty_counts() -> dict[str, int]`
  - `ServiceTypeDistribution(key, label, total, counts)`, `CommunityDistribution(key, label, total, counts, service_types)`, `ReportDistribution(company, communities)`
  - `COMPANY_KEY = "company"`, `OTHER_KEY = "__other__"`, `OTHER_LABEL = "Other"`, `GRID_SIZE = 9`
  - `distribution(rows) -> ReportDistribution`, `grid_of(service_types) -> tuple[list[ServiceTypeDistribution], int]`
  - `communities_of(row) -> tuple[str, ...]`, `primary_community(row) -> str` (E14)

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_work_order_report_buckets.py`:

```python
"""The four-bucket table and the distribution built on it.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md
(§2, E1-E3, E8).

Pure: no `db` fixture. Rows are `SimpleNamespace`s carrying only the five
attributes `distribution` reads, which is also the point -- the aggregate
must not depend on anything a `ReportRow` does not already carry.
"""

import os
import sys

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from app.domain import work_orders as wo
from app.services import work_order_report_buckets as buckets

CLOSED_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)


def _row(
    *,
    status=wo.STATUS_CREATED,
    community=None,
    location=None,
    service_type="Plumbing",
    archived=False,
):
    return SimpleNamespace(
        status=status,
        community=community,
        location=location,
        service_type=service_type,
        archived_at=CLOSED_AT if archived else None,
    )


def _community(result, key):
    return next(entry for entry in result.communities if entry.key == key)


# --- the table (E2) ---------------------------------------------------------


def test_every_status_lands_in_exactly_one_live_bucket():
    placed = [buckets.bucket_of(status) for status in wo.ALL_STATUSES]

    assert placed == [
        "accepted",
        "in_progress",
        "in_progress",
        "in_progress",
        "ready_to_close",
        "ready_to_close",
        "ready_to_close",
    ]
    assert buckets.BUCKET_CLOSED not in placed


def test_bucket_order_and_labels_are_lifecycle_order():
    assert buckets.BUCKET_KEYS == ("accepted", "in_progress", "ready_to_close", "closed")
    assert [bucket.label for bucket in buckets.REPORT_BUCKETS] == [
        "Accepted",
        "In progress",
        "Ready to close",
        "Closed",
    ]
    assert buckets.BUCKET_LABELS["ready_to_close"] == "Ready to close"


def test_unknown_status_fails_loudly():
    with pytest.raises(ValueError, match="cancelled"):
        buckets.bucket_of("cancelled")


def test_an_archived_row_is_closed_whatever_its_status():
    assert buckets.row_bucket(_row(status=wo.STATUS_REVIEW, archived=True)) == "closed"
    assert buckets.row_bucket(_row(status=wo.STATUS_REVIEW)) == "ready_to_close"


def test_empty_counts_is_zero_filled_in_bucket_order():
    assert list(buckets.empty_counts().items()) == [
        ("accepted", 0),
        ("in_progress", 0),
        ("ready_to_close", 0),
        ("closed", 0),
    ]


# --- community attribution (E14) -------------------------------------------


def test_communities_of_is_the_membership_labels_in_filter_order():
    assert buckets.communities_of(_row(community="Scholars")) == ("Scholars",)
    # Filter order, not text order: Scholars precedes Commons however the
    # location phrases it.
    assert buckets.communities_of(
        _row(location="Commons annex / Scholars 3")
    ) == ("Scholars", "Commons")
    # Nothing named: the Academics fallback, never an empty tuple.
    assert buckets.communities_of(_row()) == ("Academics",)


def test_primary_community_is_the_first_membership():
    assert buckets.primary_community(_row(location="Commons annex / Scholars 3")) == "Scholars"
    assert buckets.primary_community(_row(community="Young Hall")) == "Young Hall"
    assert buckets.primary_community(_row()) == "Academics"


# --- the distribution (E1, E3, §2.1) ---------------------------------------


def test_a_multi_community_row_is_counted_in_both():
    rows = [
        _row(community="Scholars", location="Scholars 3 / Commons annex"),
        _row(community="Centennial", status=wo.STATUS_ASSIGNED),
        _row(community="Centennial", status=wo.STATUS_REVIEW, archived=True, service_type="HVAC"),
        _row(community="Centennial", status=wo.STATUS_CREATED),
    ]

    result = buckets.distribution(rows)

    assert _community(result, "scholars").total == 1
    assert _community(result, "commons").total == 1
    assert _community(result, "centennial").counts == {
        "accepted": 1,
        "in_progress": 1,
        "ready_to_close": 0,
        "closed": 1,
    }
    assert result.company.total == 4
    # Deliberately not 4: memberships, not tags (§2.1). A future "fix" that
    # makes these sum trips this line.
    assert sum(entry.total for entry in result.communities) == 5


def test_every_group_sums_to_its_total():
    rows = [
        _row(community="Commons", status=status)
        for status in wo.ALL_STATUSES
    ] + [_row(community="Commons", status=wo.STATUS_COMPLETED, archived=True)]

    result = buckets.distribution(rows)

    for group in (result.company, *result.communities):
        assert sum(group.counts.values()) == group.total
        for service_type in group.service_types:
            assert sum(service_type.counts.values()) == service_type.total
    assert _community(result, "commons").counts == {
        "accepted": 1,
        "in_progress": 3,
        "ready_to_close": 3,
        "closed": 1,
    }


def test_blank_service_type_is_unspecified_and_a_closed_row_leaves_the_live_buckets():
    rows = [_row(community="Commons", service_type="  ", status=wo.STATUS_COMPLETED, archived=True)]

    commons = _community(buckets.distribution(rows), "commons")

    assert [(s.label, s.total, s.counts["closed"]) for s in commons.service_types] == [
        ("Unspecified", 1, 1)
    ]
    assert commons.counts["ready_to_close"] == 0


def test_service_type_labels_are_shared_company_wide_and_sorted_by_total_then_label():
    rows = [
        _row(community="Commons", service_type="hvac"),
        _row(community="Scholars", service_type="HVAC"),
        _row(community="Scholars", service_type="HVAC"),
        _row(community="Scholars", service_type="Doors"),
        _row(community="Scholars", service_type="appliances"),
    ]

    result = buckets.distribution(rows)

    # `HVAC` < `hvac` by code point, chosen once for every sheet.
    assert [s.label for s in _community(result, "commons").service_types] == ["HVAC"]
    assert [s.label for s in _community(result, "scholars").service_types] == [
        "HVAC",
        "appliances",
        "Doors",
    ]


def test_no_rows_still_produces_every_community_in_fixed_order():
    result = buckets.distribution([])

    assert [entry.key for entry in result.communities] == list(wo.ALL_COMMUNITY_FILTERS)
    assert [entry.label for entry in result.communities] == [
        "Scholars",
        "Centennial",
        "Commons",
        "Young Hall",
        "Academics",
    ]
    assert result.company.key == buckets.COMPANY_KEY
    assert result.company.total == 0
    assert result.company.service_types == []


# --- the grid (E8) ----------------------------------------------------------


def _entry(label, total):
    return buckets.ServiceTypeDistribution(
        key=label.lower(),
        label=label,
        total=total,
        counts={"accepted": total, "in_progress": 0, "ready_to_close": 0, "closed": 0},
    )


def test_grid_shows_everything_when_nine_or_fewer():
    nine = [_entry(f"T{index}", 20 - index) for index in range(9)]

    assert buckets.grid_of(nine) == (nine, 0)


def test_grid_folds_the_tail_into_other_past_nine():
    eleven = [_entry(f"T{index}", 20 - index) for index in range(11)]

    cards, folded = buckets.grid_of(eleven)

    assert folded == 3
    assert [card.label for card in cards] == [f"T{index}" for index in range(8)] + ["Other"]
    assert cards[-1].key == buckets.OTHER_KEY
    assert cards[-1].total == sum(entry.total for entry in eleven[8:])
    assert cards[-1].counts["accepted"] == cards[-1].total
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report_buckets.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'app.services.work_order_report_buckets'`.

- [ ] **Step 3: Write the module**

Create `backend/app/services/work_order_report_buckets.py`:

```python
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
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report_buckets.py -q
```

Expected: `14 passed`.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git && git add backend/app/services/work_order_report_buckets.py backend/tests/test_work_order_report_buckets.py && git commit -m "feat(hub-report): four-bucket table and community x service-type distribution

The seven lifecycle statuses collapse to Accepted / In progress / Ready to
close / Closed in one table (REPORT_BUCKETS); an import-time check makes an
unplaced status a startup failure. distribution() is a pure function over
report rows so the workbook's pies and its row sheet count the same set.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md"
```

---

### Task 2: The E1 population on `DailyReport`

**Files:**
- Modify: `backend/app/services/work_order_report.py` (imports; `ReportRow`; `DailyReport`; `_row`; new `_live_rows`, `reading_order`; `daily_report`)
- Test: `backend/tests/test_work_order_report.py` (append)

**Interfaces:**
- Consumes: Task 1 — `BUCKET_KEYS`, `ReportDistribution`, `distribution`, `row_bucket`.
- Produces:
  - `STATUS_LABELS: dict[str, str]` — all seven statuses, page spelling.
  - `ReportRow.notes: Optional[str]`, `ReportRow.material_lines: int`.
  - `DailyReport.distribution: ReportDistribution`, `DailyReport.all_rows: list[ReportRow]` (already sorted by `reading_order`).
  - `reading_order(row: ReportRow) -> tuple` — public so the xlsx test fixture can sort its hand-built rows the same way.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_work_order_report.py` (after the CSV tests; the file already imports `labor_day`, `wo`, `work_order_report`, `timedelta`, and defines `_work_order` / `_central_noon`):

```python


# --- the E1 population (xlsx redesign spec §2.1, E1, E4) -------------------


def test_all_rows_is_live_plus_closed_this_week_and_nothing_else(db):
    now = _central_noon(2026, 8, 26)
    week_start_at, _ = labor_day.day_bounds(
        labor_day.central_date_of(_central_noon(2026, 8, 24))
    )
    live = _work_order(db, status=wo.STATUS_IN_PROGRESS)
    closed_this_week = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=week_start_at + timedelta(hours=1)
    )
    closed_last_week = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=week_start_at - timedelta(hours=1)
    )

    payload = work_order_report.daily_report(db, now=now)
    numbers = [row.number for row in payload.all_rows]

    assert live.number in numbers
    assert closed_this_week.number in numbers
    assert closed_last_week.number not in numbers
    assert len(numbers) == len(set(numbers))


def test_all_rows_reads_closed_first_then_the_live_buckets_in_reverse_lifecycle(db):
    now = _central_noon(2026, 8, 26)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    older_close = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=1)
    )
    newer_close = _work_order(
        db, status=wo.STATUS_COMPLETED, archived_at=day_start + timedelta(hours=2)
    )
    accepted = _work_order(db, status=wo.STATUS_CREATED)
    working = _work_order(db, status=wo.STATUS_ON_HOLD)
    ready = _work_order(db, status=wo.STATUS_REVIEW)
    mine = {r.number for r in (older_close, newer_close, accepted, working, ready)}

    payload = work_order_report.daily_report(db, now=now)
    ordered = [row.number for row in payload.all_rows if row.number in mine]

    assert ordered == [
        newer_close.number,
        older_close.number,
        ready.number,
        working.number,
        accepted.number,
    ]


def test_distribution_is_built_over_all_rows_and_rows_carry_notes(db):
    now = _central_noon(2026, 8, 26)
    day_start, _ = labor_day.day_bounds(labor_day.central_date_of(now))
    order = _work_order(
        db,
        status=wo.STATUS_COMPLETED,
        archived_at=day_start + timedelta(hours=1),
        notes="call first",
        community="Commons",
    )

    payload = work_order_report.daily_report(db, now=now)
    row = next(r for r in payload.all_rows if r.number == order.number)

    # Company Closed is closed_week by another name: same window, same rows.
    assert payload.distribution.company.counts["closed"] == payload.sections.closed_week.count
    assert payload.distribution.company.total == len(payload.all_rows)
    assert row.notes == "call first"
    assert row.material_lines == 0


def test_status_labels_cover_every_status_in_the_pages_spelling():
    assert [work_order_report.STATUS_LABELS[s] for s in wo.ALL_STATUSES] == [
        "Created",
        "Assigned",
        "In progress",
        "On hold",
        "Ready to complete",
        "Completed",
        "Review",
    ]


def test_reading_order_is_a_pure_sort_key():
    from datetime import datetime, timezone
    from decimal import Decimal
    from uuid import uuid4

    def row(number, status, archived_at=None):
        return work_order_report.ReportRow(
            work_order_id=uuid4(), number=number, status=status, community=None,
            location=None, building_number=None, unit_number=None, service_type=None,
            priority=None, supervisor_name=None, technician_names=[],
            materials_total=Decimal("0"), labor_minutes=0, labor_total=Decimal("0"),
            total=Decimal("0"), created_at=None, completed_at=None,
            archived_at=archived_at, auto_closed=False, legacy=False,
        )

    stamp = datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc)
    rows = [
        row("B-accepted", wo.STATUS_CREATED),
        row("A-accepted", wo.STATUS_CREATED),
        row("closed-older", wo.STATUS_REVIEW, stamp),
        row("closed-newer", wo.STATUS_COMPLETED, stamp + timedelta(hours=1)),
        row("working", wo.STATUS_ASSIGNED),
        row("ready", wo.STATUS_READY_TO_COMPLETE),
    ]

    assert [r.number for r in sorted(rows, key=work_order_report.reading_order)] == [
        "closed-newer",
        "closed-older",
        "ready",
        "working",
        "A-accepted",
        "B-accepted",
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report.py -q -k "all_rows or distribution_is_built or status_labels or reading_order"
```

Expected: 5 failures — `AttributeError: 'DailyReport' object has no attribute 'all_rows'`, `module has no attribute 'STATUS_LABELS'`, `no attribute 'reading_order'`.

- [ ] **Step 3: Edit `work_order_report.py` — imports and `STATUS_LABELS`**

Replace the import block's last line and add the labels. Change:

```python
from app.services._list_cap import capped
from app.services.work_orders import export_row, work_order_totals
```

to:

```python
from app.services._list_cap import capped
from app.services.work_order_report_buckets import (
    BUCKET_KEYS,
    ReportDistribution,
    distribution,
    row_bucket,
)
from app.services.work_orders import export_row, work_order_totals
```

Then, directly after the `CSV_SECTION_HEADER = "SECTION"` line, add:

```python

# The page's own labels (`static/views/hubReport.js` STATUS_LABELS), so the
# workbook's STATUS column and the screen name a status the same way.
STATUS_LABELS: dict[str, str] = {
    wo.STATUS_CREATED: "Created",
    wo.STATUS_ASSIGNED: "Assigned",
    wo.STATUS_IN_PROGRESS: "In progress",
    wo.STATUS_ON_HOLD: "On hold",
    wo.STATUS_READY_TO_COMPLETE: "Ready to complete",
    wo.STATUS_COMPLETED: "Completed",
    wo.STATUS_REVIEW: "Review",
}
```

- [ ] **Step 4: Edit `ReportRow` and `_row`**

In `ReportRow`, change the tail of the field list from:

```python
    auto_closed: bool
    legacy: bool
    export_cells: list = field(default_factory=list)
```

to:

```python
    auto_closed: bool
    legacy: bool
    # Read by the workbook's Work Orders sheet (redesign E5); absent from
    # `schemas.hub.HubReportRow`, so neither reaches the JSON.
    notes: Optional[str] = None
    material_lines: int = 0
    export_cells: list = field(default_factory=list)
```

In `_row`, change:

```python
        auto_closed=_auto_closed(work_order),
        legacy=bool(work_order.legacy),
        export_cells=export_row(work_order),
```

to:

```python
        auto_closed=_auto_closed(work_order),
        legacy=bool(work_order.legacy),
        notes=work_order.notes,
        material_lines=len(work_order.items),
        export_cells=export_row(work_order),
```

- [ ] **Step 5: Edit `DailyReport`**

Change:

```python
@dataclass(frozen=True)
class DailyReport:
    generated_at: datetime
    day: date
    week: ReportWeek
    sections: ReportSections
```

to:

```python
@dataclass(frozen=True)
class DailyReport:
    generated_at: datetime
    day: date
    week: ReportWeek
    sections: ReportSections
    # The workbook's population (redesign E1): every live row plus every row
    # closed this week, in `reading_order`, and the four-bucket distribution
    # computed over exactly that list. Neither reaches the JSON response.
    distribution: ReportDistribution
    all_rows: list[ReportRow]
```

- [ ] **Step 6: Add `_live_rows` and `reading_order`**

Insert directly before `def daily_report(`:

```python
def _live_rows(db: Session) -> list[ReportRow]:
    """Every non-archived work order, uncapped (redesign E4).

    The workbook's Work Orders sheet is a downloadable record; one that
    silently omitted rows while looking complete would be a record-keeping
    problem, not a performance one -- the reasoning that already exempts the
    `closed_*` and `new_*` sections from the cap. The on-screen `closing` list
    keeps its cap; the file does not."""
    records = _base_query(db).filter(WorkOrder.archived_at.is_(None)).all()
    return [_row(record) for record in records]


# Reading order for `all_rows` (redesign §4.3): Closed first, then the live
# buckets in reverse lifecycle order -- what came off the plate this week,
# then what is nearest to coming off it.
_BUCKET_RANK: dict[str, int] = {
    key: rank for rank, key in enumerate(reversed(BUCKET_KEYS))
}


def reading_order(row: ReportRow) -> tuple:
    """Sort key: bucket rank, then most recent close first, then number."""
    closed_at = (
        -labor_day.as_utc(row.archived_at).timestamp()
        if row.archived_at is not None
        else 0.0
    )
    return (_BUCKET_RANK[row_bucket(row)], closed_at, row.number)


```

- [ ] **Step 7: Compose them in `daily_report`**

Replace the `return DailyReport(...)` statement at the end of `daily_report` with:

```python
    closed_week = _closed_section(db, start=week_start_at, end=now)
    # The one population (E1): everything live right now, plus everything
    # closed this week. Disjoint by construction -- a row is archived or it is
    # not -- so this is a union, not a merge, and it needs no dedup.
    all_rows = sorted([*_live_rows(db), *closed_week.rows], key=reading_order)
    return DailyReport(
        generated_at=now,
        day=today,
        week=ReportWeek(start=week_start, end=week_end),
        sections=ReportSections(
            closed_today=_closed_section(db, start=day_start, end=day_end),
            closed_week=closed_week,
            closing=_closing_section(db),
            new_today=_new_section(db, start=day_start, end=day_end),
            new_week=_new_section(db, start=week_start_at, end=now),
        ),
        distribution=distribution(all_rows),
        all_rows=all_rows,
    )
```

Also update the module docstring's first load-bearing paragraph: change `**One payload, two renderers.**` to `**One payload, three renderers.**` and append the sentence `The Excel workbook (`work_order_report_xlsx.py`) renders the same payload plus its `distribution` / `all_rows`, computed here for the same reason.`

- [ ] **Step 8: Run the tests to verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report.py tests/test_work_order_report_buckets.py -q
```

Expected: all pass. The existing xlsx tests will now **fail** (`DailyReport.__init__() missing 2 required keyword-only arguments`) — that is expected until Task 4; do not patch them here.

- [ ] **Step 9: Check the line count**

```bash
wc -l app/services/work_order_report.py
```

Expected: under 400.

- [ ] **Step 10: Commit**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git && git add backend/app/services/work_order_report.py backend/tests/test_work_order_report.py && git commit -m "feat(hub-report): DailyReport carries the workbook's population and distribution

all_rows is every live work order plus every row closed this week, uncapped
and in reading order (closed newest-first, then ready / in progress /
accepted); distribution is the four-bucket aggregate over that same list.
ReportRow gains notes and material_lines for the Work Orders sheet.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md"
```

---

### Task 3: The theme module

**Files:**
- Create: `backend/app/services/_xlsx_theme.py`
- Test: `backend/tests/test_xlsx_theme.py`

**Interfaces:**
- Consumes: openpyxl only.
- Produces (exact names the renderer uses):
  - Colors: `BRAND_RED`, `INK`, `MUTED`, `RULE`, `TAB_GRAY`, `WHITE`, `BUCKET_COLORS: dict[str, str]`, `SERIES_COLORS`
  - Fonts/styles: `font(**overrides) -> Font`, `BODY`, `TITLE`, `SUBTITLE`, `SECTION`, `HEADER`, `KPI_LABEL`, `KPI_VALUE`, `HEADER_FILL`, `SECTION_RULE`, `KPI_RULE`, `TOP`, `TOP_WRAPPED`
  - Formats: `COUNT`, `MONEY`, `PERCENT`, `DATE`
  - `NOTES_WIDTH = 60`, `NOTES_MAX_LINES = 4`, `LINE_POINTS = 13.5`
  - `setup_sheet(sheet, *, tab_color, freeze="A5", gridlines=False, print_title_rows=None)`
  - `set_widths(sheet, widths: dict[str, float])`
  - `title_block(sheet, title, lines)`
  - `section(sheet, row, text, *, span=6)`
  - `note(sheet, row, text, *, column=1)`, `empty_state(sheet, row, text, *, column=1)`
  - `kpi(sheet, row, column, label, value)`
  - `header_row(sheet, row, headers, *, column=1)`
  - `write_rows(sheet, row, rows, *, column=1, formats=None, alignment=None) -> int` (last row written; `row - 1` if none)
  - `table_of(sheet, *, name, row, headers, rows, column=1, formats=None, alignment=None) -> int`
  - `notes_row_height(text) -> Optional[float]`
  - `pie_of(source, *, title, header_row, last_row, colors, legend="r", percent_labels=True) -> PieChart`
  - `column_chart_of(source, *, title, header_row, last_row, series_columns=(2, 3), stacked=False, y_title=None) -> BarChart`
  - `place(sheet, chart, cells: str)` — `cells` is an inclusive A1 range like `"B24:D36"`.

- [ ] **Step 1: Write the failing tests**

Create `backend/tests/test_xlsx_theme.py`:

```python
"""The workbook's house style helpers (redesign spec §4.0, E12).

openpyxl cannot read back charts it wrote, so chart assertions go through
`zipfile` over the saved bytes -- the same witness the renderer tests use.
"""

import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import openpyxl
from openpyxl import Workbook

from app.services import _xlsx_theme as theme


def _saved(workbook):
    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def _part(data, name):
    with zipfile.ZipFile(io.BytesIO(data)) as archive:
        return archive.read(name).decode()


def _pie_workbook(**kwargs):
    workbook = Workbook()
    sheet = workbook.active
    source = workbook.create_sheet("Chart Data")
    source.append(["Bucket", "Count"])
    for label, count in (("Accepted", 3), ("In progress", 2), ("Ready to close", 1), ("Closed", 4)):
        source.append([label, count])
    chart = theme.pie_of(
        source,
        title="Status",
        header_row=1,
        last_row=5,
        colors=["9CA3AF", "D97706", "6D28D9", "15803D"],
        **kwargs,
    )
    theme.place(sheet, chart, "B24:D36")
    return workbook


def test_pie_is_fixed_order_fixed_color_and_plots_hidden_cells():
    xml = _part(_saved(_pie_workbook()), "xl/charts/chart1.xml")

    assert 'plotVisOnly val="0"' in xml
    assert 'firstSliceAng val="0"' in xml
    assert xml.count("<dPt>") == 4
    assert xml.index("9CA3AF") < xml.index("D97706") < xml.index("6D28D9") < xml.index("15803D")
    assert 'showPercent val="1"' in xml
    assert 'legendPos val="r"' in xml


def test_pie_can_drop_labels_and_move_the_legend():
    xml = _part(_saved(_pie_workbook(legend="b", percent_labels=False)), "xl/charts/chart1.xml")

    assert 'showPercent val="1"' not in xml
    assert 'legendPos val="b"' in xml


def test_place_fills_exactly_the_named_cells():
    xml = _part(_saved(_pie_workbook()), "xl/drawings/drawing1.xml")

    assert "<twoCellAnchor>" in xml
    assert "<from><col>1</col><colOff>0</colOff><row>23</row>" in xml
    assert "<to><col>4</col><colOff>0</colOff><row>36</row>" in xml


def test_column_chart_uses_brand_then_neutral_and_can_stack():
    workbook = Workbook()
    sheet = workbook.active
    source = workbook.create_sheet("Chart Data")
    source.append(["Community", "Labor", "Materials"])
    source.append(["North", 100, 20])
    chart = theme.column_chart_of(
        source, title="Dollars", header_row=1, last_row=2, stacked=True, y_title="Dollars"
    )
    theme.place(sheet, chart, "G42:M56")

    xml = _part(_saved(workbook), "xl/charts/chart1.xml")

    assert 'grouping val="stacked"' in xml
    assert 'overlap val="100"' in xml
    assert xml.index(theme.BRAND_RED) < xml.index(theme.MUTED)
    assert 'plotVisOnly val="0"' in xml


def test_table_of_writes_a_banded_table_only_when_there_are_rows():
    workbook = Workbook()
    with_rows = workbook.active
    last = theme.table_of(
        with_rows, name="WorkOrders", row=5, headers=("A", "B"), rows=[[1, 2], [3, 4]],
        formats={1: theme.COUNT},
    )
    without = workbook.create_sheet("Empty")
    empty_last = theme.table_of(without, name="Nothing", row=5, headers=("A", "B"), rows=[])

    assert last == 7
    assert empty_last == 5  # the header row is the last row written
    assert [t.displayName for t in with_rows.tables.values()] == ["WorkOrders"]
    assert list(with_rows.tables.values())[0].ref == "A5:B7"
    assert with_rows["B6"].number_format == theme.COUNT
    assert with_rows["A5"].font.bold and with_rows["A5"].font.color.rgb.endswith(theme.WHITE)
    assert without.tables == {}
    assert without["A5"].value == "A"


def test_setup_sheet_applies_the_shared_furniture():
    workbook = Workbook()
    sheet = workbook.active
    theme.setup_sheet(sheet, tab_color=theme.BRAND_RED, freeze="D6", print_title_rows="5:5")

    reloaded = openpyxl.load_workbook(io.BytesIO(_saved(workbook))).active

    assert reloaded.sheet_properties.tabColor.rgb.endswith(theme.BRAND_RED)
    assert reloaded.sheet_view.showGridLines is False
    assert reloaded.freeze_panes == "D6"
    assert reloaded.page_setup.orientation == "landscape"
    assert reloaded.page_setup.fitToWidth == 1
    assert reloaded.sheet_properties.pageSetUpPr.fitToPage is True
    assert reloaded.page_margins.left == 0.5
    assert reloaded.print_title_rows == "$5:$5"  # openpyxl absolutises on reload


def test_setup_sheet_can_leave_gridlines_on_for_the_data_sheet():
    workbook = Workbook()
    theme.setup_sheet(workbook.active, tab_color=theme.TAB_GRAY, freeze="A2", gridlines=True)

    reloaded = openpyxl.load_workbook(io.BytesIO(_saved(workbook))).active

    assert reloaded.sheet_view.showGridLines is not False


def test_title_block_section_and_kpi_styles():
    workbook = Workbook()
    sheet = workbook.active
    theme.title_block(sheet, "Scholars", ["Weekly status", "caveat"])
    theme.section(sheet, 5, "Status", span=3)
    theme.kpi(sheet, 6, 2, "Accepted", 12)

    assert sheet["A1"].font.size == 18 and sheet["A1"].font.color.rgb.endswith(theme.BRAND_RED)
    assert sheet["A2"].font.italic and sheet["A2"].font.size == 9
    assert sheet["A5"].font.bold and sheet["C5"].border.bottom.style == "thin"
    assert sheet["D5"].border.bottom.style is None
    assert sheet["B6"].value == "Accepted" and sheet["B7"].value == 12
    assert sheet["B7"].border.bottom.color.rgb.endswith(theme.BRAND_RED)
    assert sheet["B7"].number_format == theme.COUNT


def test_notes_row_height_caps_at_four_lines():
    assert theme.notes_row_height(None) is None
    assert theme.notes_row_height("short") is None
    assert theme.notes_row_height("one\ntwo") == 27.0
    assert theme.notes_row_height("x" * 200) == 54.0
    assert theme.notes_row_height("\n".join(["line"] * 10)) == 54.0
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_xlsx_theme.py -q
```

Expected: collection error — `ModuleNotFoundError: No module named 'app.services._xlsx_theme'`.

- [ ] **Step 3: Write the module**

Create `backend/app/services/_xlsx_theme.py`:

```python
"""House style for the daily report workbook (redesign spec §4.0, E12).

Layer: services (pure -- openpyxl objects in, openpyxl objects out). Fonts,
fills, number formats, the bucket palette, table and chart construction, so
`work_order_report_xlsx.py` is sheet composition and nothing else.

Two things about this module are load-bearing:

**Charts are placed by cell range, not by centimetres.** openpyxl's default
one-cell anchor sizes a chart in absolute units, so a grid of pies lines up
only if column widths happen to match the font's pixel metrics -- which
change with whatever font Excel substitutes. `place()` uses a two-cell anchor
instead: the chart fills exactly the cells named, whatever the widths.

**Slice colors are set per data point, in bucket order, on every pie.** Excel
would otherwise assign its theme's accent sequence and Accepted would be a
different color on every sheet. `pie_of` takes the colors explicitly so the
palette below is the only place they exist.
"""

from __future__ import annotations

import math
from typing import Optional, Sequence

from openpyxl.chart import BarChart, PieChart, Reference
from openpyxl.chart.label import DataLabelList
from openpyxl.chart.series import DataPoint
from openpyxl.chart.shapes import GraphicalProperties
from openpyxl.drawing.spreadsheet_drawing import AnchorMarker, TwoCellAnchor
from openpyxl.styles import Alignment, Border, Font, PatternFill, Side
from openpyxl.utils import range_boundaries
from openpyxl.worksheet.table import Table, TableStyleInfo
from openpyxl.worksheet.worksheet import Worksheet

# --- palette (§4.0) ---------------------------------------------------------

BRAND_RED = "C8102E"  # titles and the KPI rule: the brand, never a slice
INK = "1C1D20"
MUTED = "5A5C60"
RULE = "D8D9DB"
TAB_GRAY = "B7B9BC"
WHITE = "FFFFFF"

# Bucket key -> fill. Traceable to the `--wo-status-*` tokens the Graphs tab
# uses, darkened where the token was tuned for a dark canvas and would wash
# out on white paper.
BUCKET_COLORS: dict[str, str] = {
    "accepted": "9CA3AF",  # --wo-status-created #D1D5DB, darkened
    "in_progress": "D97706",  # --wo-status-in-progress #FACC15, darkened
    "ready_to_close": "6D28D9",  # --wo-status-ready-to-complete, as-is
    "closed": "15803D",  # --wo-status-review, as-is
}

# The two-series treatment for the Activity and Dollars charts. Not the
# bucket palette: those are not bucket charts and must not borrow it (§4.1).
SERIES_COLORS: tuple[str, str] = (BRAND_RED, MUTED)

# --- type (§4.0) ------------------------------------------------------------

FONT_NAME = "Aptos Narrow"  # Excel falls back to Calibri where it is missing


def font(**overrides) -> Font:
    return Font(**{"name": FONT_NAME, "size": 10, **overrides})


BODY = font()
TITLE = font(size=18, bold=True, color=BRAND_RED)
SUBTITLE = font(size=9, italic=True, color=MUTED)
SECTION = font(size=11, bold=True, color=INK)
HEADER = font(bold=True, color=WHITE)
KPI_LABEL = font(size=9, color=MUTED)
KPI_VALUE = font(size=20, bold=True, color=INK)

HEADER_FILL = PatternFill("solid", fgColor=INK)
SECTION_RULE = Border(bottom=Side(style="thin", color=RULE))
KPI_RULE = Border(bottom=Side(style="medium", color=BRAND_RED))
TOP = Alignment(vertical="top")
TOP_WRAPPED = Alignment(vertical="top", wrap_text=True)

COUNT = "#,##0"
MONEY = "$#,##0.00"
PERCENT = "0.0%"
DATE = "yyyy-mm-dd hh:mm"

TABLE_STYLE = TableStyleInfo(name="TableStyleLight1", showRowStripes=True)

# The Notes column (§4.3): 60 characters wide, wrapped, at most four lines
# tall. 13.5pt is one line of 10pt text with Excel's default leading.
NOTES_WIDTH = 60
NOTES_MAX_LINES = 4
LINE_POINTS = 13.5


# --- sheet furniture --------------------------------------------------------


def setup_sheet(
    sheet: Worksheet,
    *,
    tab_color: str,
    freeze: Optional[str] = "A5",
    gridlines: bool = False,
    print_title_rows: Optional[str] = None,
) -> None:
    """Tab color, gridlines, freeze panes, and the print setup every sheet
    shares: landscape, one page wide, half-inch margins."""
    sheet.sheet_properties.tabColor = tab_color
    sheet.sheet_view.showGridLines = gridlines
    sheet.freeze_panes = freeze
    sheet.page_setup.orientation = "landscape"
    sheet.page_setup.fitToWidth = 1
    sheet.page_setup.fitToHeight = 0
    sheet.sheet_properties.pageSetUpPr.fitToPage = True
    for side in ("left", "right", "top", "bottom"):
        setattr(sheet.page_margins, side, 0.5)
    if print_title_rows:
        sheet.print_title_rows = print_title_rows


def set_widths(sheet: Worksheet, widths: dict[str, float]) -> None:
    for column, width in widths.items():
        sheet.column_dimensions[column].width = width


def title_block(sheet: Worksheet, title: str, lines: Sequence[str]) -> None:
    """Rows 1-4: the title, then up to three subtitle / caveat lines."""
    sheet.cell(row=1, column=1, value=title).font = TITLE
    for offset, line in enumerate(lines, start=2):
        sheet.cell(row=offset, column=1, value=line).font = SUBTITLE


def section(sheet: Worksheet, row: int, text: str, *, span: int = 6) -> None:
    """A section heading with a 1pt rule under it across `span` columns."""
    sheet.cell(row=row, column=1, value=text).font = SECTION
    for column in range(1, span + 1):
        sheet.cell(row=row, column=column).border = SECTION_RULE


def note(sheet: Worksheet, row: int, text: str, *, column: int = 1) -> None:
    sheet.cell(row=row, column=column, value=text).font = SUBTITLE


def empty_state(sheet: Worksheet, row: int, text: str, *, column: int = 1) -> None:
    sheet.cell(row=row, column=column, value=text).font = font(italic=True, color=MUTED)


def kpi(sheet: Worksheet, row: int, column: int, label: str, value) -> None:
    """One KPI tile: label above value, brand-red rule under the value."""
    sheet.cell(row=row, column=column, value=label).font = KPI_LABEL
    cell = sheet.cell(row=row + 1, column=column, value=value)
    cell.font = KPI_VALUE
    cell.number_format = COUNT
    cell.border = KPI_RULE


def header_row(
    sheet: Worksheet, row: int, headers: Sequence[str], *, column: int = 1
) -> None:
    """White-on-ink header cells: plain blocks and Excel Table headers alike
    (the table style leaves explicit fills alone)."""
    for offset, header in enumerate(headers):
        cell = sheet.cell(row=row, column=column + offset, value=header)
        cell.font = HEADER
        cell.fill = HEADER_FILL


def write_rows(
    sheet: Worksheet,
    row: int,
    rows: Sequence[Sequence],
    *,
    column: int = 1,
    formats: Optional[dict[int, str]] = None,
    alignment: Optional[Alignment] = None,
) -> int:
    """Write `rows` from `row` down. `formats` maps a 0-based column offset to
    a number format. Returns the last row written (`row - 1` if none)."""
    formats = formats or {}
    for index, values in enumerate(rows):
        for offset, value in enumerate(values):
            cell = sheet.cell(row=row + index, column=column + offset, value=value)
            cell.font = BODY
            if offset in formats:
                cell.number_format = formats[offset]
            if alignment is not None:
                cell.alignment = alignment
    return row + len(rows) - 1


def table_of(
    sheet: Worksheet,
    *,
    name: str,
    row: int,
    headers: Sequence[str],
    rows: Sequence[Sequence],
    column: int = 1,
    formats: Optional[dict[int, str]] = None,
    alignment: Optional[Alignment] = None,
) -> int:
    """A banded Excel Table with autofilter, header at `row`. Returns the last
    row written.

    With no data rows the header is still written but no Table is created:
    Excel treats a header-only table as a file to repair. `name` must be
    unique in the workbook and contain no spaces."""
    header_row(sheet, row, headers, column=column)
    last = write_rows(
        sheet, row + 1, rows, column=column, formats=formats, alignment=alignment
    )
    if rows:
        first_letter = sheet.cell(row=row, column=column).column_letter
        last_letter = sheet.cell(row=row, column=column + len(headers) - 1).column_letter
        table = Table(displayName=name, ref=f"{first_letter}{row}:{last_letter}{last}")
        table.tableStyleInfo = TABLE_STYLE
        sheet.add_table(table)
    return last


def notes_row_height(text: Optional[str]) -> Optional[float]:
    """Row height for a wrapped Notes cell: one line per `NOTES_WIDTH`
    characters, capped at `NOTES_MAX_LINES`. `None` means leave the default."""
    if not text:
        return None
    lines = sum(
        max(1, math.ceil(len(part) / NOTES_WIDTH)) for part in text.splitlines()
    )
    if lines <= 1:
        return None
    return min(lines, NOTES_MAX_LINES) * LINE_POINTS


# --- charts -----------------------------------------------------------------


def pie_of(
    source: Worksheet,
    *,
    title: str,
    header_row: int,
    last_row: int,
    colors: Sequence[str],
    legend: Optional[str] = "r",
    percent_labels: bool = True,
) -> PieChart:
    """A pie over a two-column block on `source`: labels in column A, counts
    in column B, `header_row` holding the series title.

    `colors` are applied per data point in row order -- pass the bucket
    palette in bucket order. `firstSliceAng = 0` keeps the first slice at 12
    o'clock; `visible_cells_only = False` lets Excel plot a block that lives
    on a hidden sheet (E7)."""
    chart = PieChart()
    chart.title = title
    chart.firstSliceAng = 0
    chart.visible_cells_only = False
    chart.add_data(
        Reference(source, min_col=2, min_row=header_row, max_row=last_row),
        titles_from_data=True,
    )
    chart.set_categories(
        Reference(source, min_col=1, min_row=header_row + 1, max_row=last_row)
    )
    series = chart.series[0]
    for index, color in enumerate(colors):
        point = DataPoint(idx=index)
        point.graphicalProperties = GraphicalProperties(solidFill=color)
        series.dPt.append(point)
    if percent_labels:
        chart.dataLabels = DataLabelList()
        chart.dataLabels.showPercent = True
        chart.dataLabels.showVal = False
        chart.dataLabels.showCatName = False
        chart.dataLabels.showSerName = False
        chart.dataLabels.showLeaderLines = False
    if legend is None:
        chart.legend = None
    else:
        chart.legend.position = legend
    return chart


def column_chart_of(
    source: Worksheet,
    *,
    title: str,
    header_row: int,
    last_row: int,
    series_columns: tuple[int, int] = (2, 3),
    stacked: bool = False,
    y_title: Optional[str] = None,
) -> BarChart:
    """A vertical column chart over a block on `source`: categories in column
    A, one series per column in `series_columns`, titles from `header_row`.
    Brand red then neutral -- never the bucket palette."""
    chart = BarChart()
    chart.type = "col"
    chart.title = title
    chart.visible_cells_only = False
    if stacked:
        chart.grouping = "stacked"
        chart.overlap = 100
    if y_title:
        chart.y_axis.title = y_title
    first, last = series_columns
    chart.add_data(
        Reference(
            source, min_col=first, max_col=last, min_row=header_row, max_row=last_row
        ),
        titles_from_data=True,
    )
    chart.set_categories(
        Reference(source, min_col=1, min_row=header_row + 1, max_row=last_row)
    )
    for series, color in zip(chart.series, SERIES_COLORS):
        series.graphicalProperties = GraphicalProperties(solidFill=color)
    return chart


def place(sheet: Worksheet, chart, cells: str) -> None:
    """Anchor `chart` so it fills exactly `cells` -- an inclusive A1 range such
    as `"B24:D36"` -- whatever the column widths and row heights are."""
    min_col, min_row, max_col, max_row = range_boundaries(cells)
    chart.anchor = TwoCellAnchor(
        _from=AnchorMarker(col=min_col - 1, row=min_row - 1),
        to=AnchorMarker(col=max_col, row=max_row),
    )
    sheet.add_chart(chart)
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_xlsx_theme.py -q
```

Expected: `9 passed`. If `test_setup_sheet_applies_the_shared_furniture` fails on `showGridLines is False`, check that openpyxl round-trips it as `False` (it writes `showGridLines="0"`); if it reads back as `None` on reload, assert on the raw sheet XML instead (`'showGridLines="0"' in _part(data, "xl/worksheets/sheet1.xml")`).

- [ ] **Step 5: Commit**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git && git add backend/app/services/_xlsx_theme.py backend/tests/test_xlsx_theme.py && git commit -m "feat(hub-report): house-style module for the report workbook

Palette, fonts, number formats, banded tables, and chart builders in one
place so the workbook renderer is sheet composition only. Charts are placed
by cell range (two-cell anchor) so the small-multiple grid lines up whatever
font Excel substitutes; pie slices are colored per data point in bucket
order so Accepted is the same gray on every sheet.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md"
```

---

### Task 4: Workbook skeleton, `Chart Data`, `Data`, and the `Work Orders` sheet

**Files:**
- Rewrite: `backend/app/services/work_order_report_xlsx.py`
- Rewrite: `backend/tests/test_work_order_report_xlsx.py`

**Interfaces:**
- Consumes: Task 1 (`BUCKET_KEYS`, `BUCKET_LABELS`, `BUCKET_CLOSED`, `row_bucket`, `grid_of`), Task 2 (`STATUS_LABELS`, `reading_order`, `DailyReport.all_rows` / `.distribution`, `ReportRow.notes` / `.material_lines`), Task 3 (everything under `theme.`).
- Produces: `XLSX_MEDIA_TYPE` (unchanged), `SHEET_NAMES`, `CHART_DATA_SHEET = "Chart Data"`, `WORK_ORDER_HEADERS`, `WORK_ORDERS_HEADER_ROW = 5`, `report_xlsx(payload) -> bytes`, `report_xlsx_filename(payload) -> str`; `_ChartData.block(name, header, rows) -> (header_row, last_row)`; `_report_sheet` / `_community_sheet` write **title blocks only** here (Tasks 5 and 6 add their bodies below row 4 — the title blocks written here are final).

- [ ] **Step 1: Rewrite the test file's fixtures and the tests this task satisfies**

Replace `backend/tests/test_work_order_report_xlsx.py` in full with:

```python
"""The daily report's Excel render.

`report_xlsx` is a pure function of a `DailyReport` (spec X3 / E13), so these
tests hand-build frozen payloads instead of touching the database -- no `db`
fixture, no dev-Postgres fencing. Charts cannot be read back through openpyxl,
so they are asserted over the saved bytes with `zipfile`.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md
"""

import csv
import io
import os
import sys
import zipfile

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from datetime import date, datetime, timezone
from decimal import Decimal
from uuid import uuid4

import openpyxl
import pytest

from app.domain import work_orders as wo
from app.services import work_order_report as report
from app.services import work_order_report_buckets as buckets
from app.services import work_order_report_xlsx as xlsx

CLOSED_AT = datetime(2026, 8, 25, 15, 30, tzinfo=timezone.utc)


def _row(
    *,
    number="WO-1",
    status=wo.STATUS_CREATED,
    community=None,
    location="Bldg A",
    service_type=None,
    labor_total="0.00",
    materials_total="0.00",
    archived=False,
    notes=None,
    priority=None,
):
    """A `ReportRow` whose `export_cells` are shaped like `export_row`'s: 26
    values, three of them genuine ints, money as fixed-point strings. Live by
    default; `archived=True` makes it a row closed this week."""
    labor = Decimal(labor_total)
    materials = Decimal(materials_total)
    archived_at = CLOSED_AT if archived else None
    cells = [
        number,
        location or "",
        "",
        "",
        service_type or "",
        "",
        "Leaky faucet",
        status,
        "Tech One; Tech Two",
        "Sue",
        community or "",
        "3",
        "12",
        "manual",
        2,
        f"{materials:.2f}",
        60,
        60,
        f"{labor:.2f}",
        f"{materials + labor:.2f}",
        notes or "",
        "2026-08-25 14:00",
        "2026-08-25 15:00",
        "2026-08-25 15:00",
        "2026-08-25 15:30" if archived else "",
    ]
    assert len(cells) == len(wo.EXPORT_HEADERS)
    return report.ReportRow(
        work_order_id=uuid4(),
        number=number,
        status=status,
        community=community,
        location=location,
        building_number="3",
        unit_number="12",
        service_type=service_type,
        priority=priority,
        supervisor_name="Sue",
        technician_names=["Tech One", "Tech Two"],
        materials_total=materials,
        labor_minutes=60,
        labor_total=labor,
        total=materials + labor,
        created_at=datetime(2026, 8, 25, 14, 0, tzinfo=timezone.utc),
        completed_at=datetime(2026, 8, 25, 15, 0, tzinfo=timezone.utc),
        archived_at=archived_at,
        auto_closed=False,
        legacy=False,
        notes=notes,
        material_lines=2,
        export_cells=cells,
    )


def _payload(
    *,
    live=(),
    closed_today=(),
    closed_week=(),
    closing=(),
    new_today=(),
    new_week=(),
    auto_closed_today=0,
    by_status=None,
    closing_count=None,
    truncated=False,
):
    """The E1 population is `live` + `closed_week`; the sections are passed
    separately, exactly as `daily_report` composes them."""
    closing_rows = list(closing)
    all_rows = sorted([*live, *closed_week], key=report.reading_order)
    return report.DailyReport(
        generated_at=datetime(2026, 8, 25, 22, 30, tzinfo=timezone.utc),
        day=date(2026, 8, 25),
        week=report.ReportWeek(start=date(2026, 8, 24), end=date(2026, 8, 30)),
        sections=report.ReportSections(
            closed_today=report.ClosedSection(
                count=len(closed_today),
                auto_closed_count=auto_closed_today,
                rows=list(closed_today),
            ),
            closed_week=report.ClosedSection(
                count=len(closed_week), auto_closed_count=0, rows=list(closed_week)
            ),
            closing=report.ClosingSection(
                count=(closing_count if closing_count is not None else len(closing_rows)),
                by_status=(by_status if by_status is not None else {}),
                truncated=truncated,
                rows=closing_rows,
            ),
            new_today=report.NewSection(count=len(new_today), rows=list(new_today)),
            new_week=report.NewSection(count=len(new_week), rows=list(new_week)),
        ),
        distribution=buckets.distribution(all_rows),
        all_rows=all_rows,
    )


def _scholars_payload():
    """Scholars only: 3 accepted Plumbing, 1 on-hold HVAC, 1 review Plumbing
    (live) plus 2 Plumbing closed this week. Every other community empty."""
    live = [
        _row(number="WO-1", community="Scholars", service_type="Plumbing"),
        _row(number="WO-2", community="Scholars", service_type="Plumbing"),
        _row(
            number="WO-3",
            community="Scholars",
            service_type="Plumbing",
            notes="Tenant home after 5.\nCall first.",
        ),
        _row(
            number="WO-4",
            community="Scholars",
            service_type="HVAC",
            status=wo.STATUS_ON_HOLD,
        ),
        _row(
            number="WO-5",
            community="Scholars",
            service_type="Plumbing",
            status=wo.STATUS_REVIEW,
        ),
    ]
    closed = [
        _row(
            number="WO-6",
            community="Scholars",
            service_type="Plumbing",
            status=wo.STATUS_COMPLETED,
            archived=True,
            labor_total="100.00",
            materials_total="25.00",
        ),
        _row(
            number="WO-7",
            community="Scholars",
            service_type="Plumbing",
            status=wo.STATUS_REVIEW,
            archived=True,
        ),
    ]
    return _payload(
        live=live,
        closed_today=closed[:1],
        closed_week=closed,
        closing=[live[4]],
        by_status={wo.STATUS_REVIEW: 1},
        new_today=[live[0]],
        new_week=live[:2],
    )


def _workbook(payload):
    return openpyxl.load_workbook(io.BytesIO(xlsx.report_xlsx(payload)))


def _cells(sheet):
    """Every cell value as a grid, `None` intact."""
    return [[cell.value for cell in row] for row in sheet.iter_rows()]


def _column(sheet, column, first, last):
    return [sheet.cell(row=row, column=column).value for row in range(first, last + 1)]


def _chart_parts(payload):
    with zipfile.ZipFile(io.BytesIO(xlsx.report_xlsx(payload))) as archive:
        return {
            name: archive.read(name).decode()
            for name in archive.namelist()
            if name.startswith("xl/charts/chart") and name.endswith(".xml")
        }


# --- workbook shape (E6, E7, E10) ------------------------------------------


def test_sheets_are_the_eight_visible_plus_hidden_chart_data_with_data_last():
    workbook = _workbook(_payload())

    assert workbook.sheetnames == [
        "Report",
        "Scholars",
        "Centennial",
        "Commons",
        "Young Hall",
        "Academics",
        "Work Orders",
        "Chart Data",
        "Data",
    ]
    assert workbook.sheetnames == list(xlsx.SHEET_NAMES)
    assert workbook["Chart Data"].sheet_state == "hidden"
    assert all(
        workbook[name].sheet_state == "visible"
        for name in workbook.sheetnames
        if name != "Chart Data"
    )
    assert workbook.active.title == "Report"


def test_tab_colors_and_gridlines_follow_the_house_style():
    workbook = _workbook(_payload())

    assert workbook["Report"].sheet_properties.tabColor.rgb.endswith("C8102E")
    assert workbook["Commons"].sheet_properties.tabColor.rgb.endswith("5A5C60")
    assert workbook["Work Orders"].sheet_properties.tabColor.rgb.endswith("1C1D20")
    assert workbook["Data"].sheet_properties.tabColor.rgb.endswith("B7B9BC")
    assert workbook["Report"].sheet_view.showGridLines is False
    assert workbook["Data"].sheet_view.showGridLines is not False


def test_filename_is_the_covered_day():
    assert xlsx.report_xlsx_filename(_payload()) == "wo-report_2026-08-25.xlsx"


# --- Data (X5, E10) ---------------------------------------------------------


def test_data_sheet_matches_report_csv():
    """The load-bearing pin (X5): the Data sheet is `report_csv`, cell for
    cell, so save-as-CSV from Excel still round-trips through the importer."""
    closed = _row(
        number="WO-1",
        community="North",
        service_type="Plumbing",
        status=wo.STATUS_COMPLETED,
        archived=True,
    )
    closing = _row(number="WO-3", status=wo.STATUS_REVIEW)
    new = _row(number="WO-4")
    payload = _payload(
        live=[closing, new],
        closed_today=[closed],
        closed_week=[
            closed,
            _row(number="WO-2", service_type="HVAC", status=wo.STATUS_COMPLETED, archived=True),
        ],
        closing=[closing],
        new_today=[new],
        new_week=[new],
        by_status={wo.STATUS_REVIEW: 1},
    )

    expected = list(csv.reader(io.StringIO(report.report_csv(payload))))
    actual = [
        ["" if value is None else str(value) for value in row]
        for row in _cells(_workbook(payload)["Data"])
    ]

    assert actual == expected


def test_data_sheet_header_is_the_section_prefixed_export_headers():
    sheet = _workbook(_payload())["Data"]

    assert tuple(cell.value for cell in sheet[1]) == (
        report.CSV_SECTION_HEADER,
    ) + wo.EXPORT_HEADERS
    assert sheet.freeze_panes == "A2"


# --- Work Orders (E4, E5, §4.3) ---------------------------------------------


def test_work_orders_header_has_notes_in_column_c_and_freezes_at_d6():
    sheet = _workbook(_scholars_payload())["Work Orders"]

    assert [cell.value for cell in sheet[5]][:21] == [
        "WORK ORDER",
        "LOCATION",
        "NOTES",
        "BUCKET",
        "STATUS",
        "COMMUNITIES",
        "SERVICE TYPE",
        "PRIORITY",
        "BUILDING",
        "UNIT",
        "SUPERVISOR",
        "TECHNICIANS",
        "MATERIAL LINES",
        "MATERIALS TOTAL",
        "LABOR MINUTES",
        "LABOR TOTAL",
        "TOTAL",
        "CREATED AT",
        "COMPLETED AT",
        "CLOSED AT",
        "SECTIONS",
    ]
    assert sheet["C5"].value == "NOTES"
    assert sheet.column_dimensions["C"].width == 60
    assert sheet.freeze_panes == "D6"
    assert sheet.print_title_rows == "$5:$5"


def test_work_orders_is_the_deduped_population_in_reading_order():
    sheet = _workbook(_scholars_payload())["Work Orders"]

    numbers = _column(sheet, 1, 6, 12)
    assert numbers == ["WO-6", "WO-7", "WO-5", "WO-4", "WO-1", "WO-2", "WO-3"]
    assert len(numbers) == len(set(numbers)) == 7
    assert sheet.cell(row=13, column=1).value is None
    assert [t.ref for t in sheet.tables.values()] == ["A5:U12"]


def test_work_orders_columns_carry_bucket_status_sections_and_real_numbers():
    sheet = _workbook(_scholars_payload())["Work Orders"]
    closed = [cell.value for cell in sheet[6]]
    accepted = [cell.value for cell in sheet[10]]
    ready = [cell.value for cell in sheet[8]]

    assert closed[0] == "WO-6"
    assert closed[3] == "Closed" and closed[4] == "Completed"
    assert closed[12] == 2
    assert closed[13] == Decimal("25.00") and sheet["N6"].number_format == "$#,##0.00"
    assert closed[15] == Decimal("100.00") and closed[16] == Decimal("125.00")
    assert closed[17] == datetime(2026, 8, 25, 14, 0) and sheet["R6"].number_format == "yyyy-mm-dd hh:mm"
    assert closed[19] == datetime(2026, 8, 25, 15, 30)
    assert closed[20] == "closed_today; closed_week"
    assert accepted[3] == "Accepted" and accepted[4] == "Created"
    assert accepted[19] is None
    assert accepted[20] == "new_today; new_week"
    assert ready[3] == "Ready to close" and ready[4] == "Review" and ready[20] == "closing"


def test_work_orders_communities_column_lists_every_membership():
    payload = _payload(
        live=[
            _row(number="WO-1", location="Scholars 3 / Commons annex"),
            _row(number="WO-2", community="Young Hall"),
            _row(number="WO-3"),
        ]
    )
    sheet = _workbook(payload)["Work Orders"]

    assert sheet["F5"].value == "COMMUNITIES"
    assert sheet.column_dimensions["F"].width == 22
    # Memberships, not the raw column (E14): two names for a two-community
    # location, Academics for a location naming none -- never blank.
    assert _column(sheet, 6, 6, 8) == ["Scholars; Commons", "Young Hall", "Academics"]


def test_work_orders_notes_wrap_top_aligned_with_a_capped_row_height():
    sheet = _workbook(_scholars_payload())["Work Orders"]

    note_cell = sheet["C12"]
    assert note_cell.value == "Tenant home after 5.\nCall first."
    assert note_cell.alignment.wrap_text is True
    assert note_cell.alignment.vertical == "top"
    assert sheet.row_dimensions[12].height == 27.0
    assert sheet.row_dimensions[6].height is None


def test_empty_population_renders_a_header_and_an_empty_state_without_a_table():
    sheet = _workbook(_payload())["Work Orders"]

    assert sheet["C5"].value == "NOTES"
    assert sheet["A6"].value == "No live or recently closed work orders."
    assert sheet.tables == {}
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report_xlsx.py -q
```

Expected: failures — `module 'app.services.work_order_report_xlsx' has no attribute 'SHEET_NAMES'` and `KeyError: 'Worksheet Work Orders does not exist.'` (the current module still builds `Summary` + `Data`).

- [ ] **Step 3: Rewrite the renderer module**

Replace `backend/app/services/work_order_report_xlsx.py` in full with:

```python
"""The Admin daily report as an Excel workbook.

Layer: services. The third renderer of `work_order_report.daily_report`'s
payload, beside the JSON route and `report_csv` -- a pure function of that
payload, no queries and no clock, so the file and the screen cannot disagree
(parent spec R9 / X3, redesign E13). Styling lives in `_xlsx_theme.py` (E12);
this module is sheet composition only.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md

Sheet order is the reading order: `Report`, one sheet per community, `Work
Orders`, then the machine sheets -- hidden `Chart Data`, and `Data` last.

Three things about this module are load-bearing:

**openpyxl discards charts across a load/save cycle.** So there is no
committed `.xlsx` template -- the workbook is built in code, and the charts
cannot be read back in tests: `tests/test_work_order_report_xlsx.py` asserts
them over the saved bytes with `zipfile`.

**Every chart reads the hidden `Chart Data` sheet (E7)**, one labelled block
per chart written by cursor, with `visible_cells_only = False` so Excel plots
it. The designed sheets carry the same numbers as styled tables, from the
same payload -- never as chart sources.

**`Data` is `report_csv`, cell for cell (E10 / X5)**, money-as-text included,
so save-as-CSV from Excel still round-trips through `parse_import_row`.
"""

from __future__ import annotations

import io
from datetime import datetime, timezone
from decimal import Decimal
from typing import Optional
from uuid import UUID

from openpyxl import Workbook
from openpyxl.utils import get_column_letter, range_boundaries
from openpyxl.worksheet.worksheet import Worksheet

from app.domain import labor_day
from app.domain import work_orders as wo
from app.services import _xlsx_theme as theme
from app.services.work_order_report import (
    CLOSING_STATUSES,
    CSV_SECTION_HEADER,
    SECTION_ORDER,
    STATUS_LABELS,
    DailyReport,
    ReportRow,
)
from app.services.work_order_report_buckets import (
    BUCKET_CLOSED,
    BUCKET_KEYS,
    BUCKET_LABELS,
    CommunityDistribution,
    communities_of,
    grid_of,
    primary_community,
    row_bucket,
)

XLSX_MEDIA_TYPE = (
    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"
)

CHART_DATA_SHEET = "Chart Data"

# Physical order. Excel opens on the first; `Chart Data` is hidden, so the
# tab strip shows eight and ends on `Data` (E6, plan P5).
SHEET_NAMES: tuple[str, ...] = (
    "Report",
    *(wo.COMMUNITY_LABELS[key] for key in wo.ALL_COMMUNITY_FILTERS),
    "Work Orders",
    CHART_DATA_SHEET,
    "Data",
)

PLACEHOLDER = "(none)"
EMPTY_STATE = "No live or recently closed work orders."
EMPTY_COMMUNITY_STATE = "No live or recently closed work orders in this community."

BUCKET_COLOR_ORDER = [theme.BUCKET_COLORS[key] for key in BUCKET_KEYS]


def report_xlsx(payload: DailyReport) -> bytes:
    workbook = Workbook()
    report_sheet = workbook.active
    report_sheet.title = "Report"
    community_sheets = {
        key: workbook.create_sheet(wo.COMMUNITY_LABELS[key])
        for key in wo.ALL_COMMUNITY_FILTERS
    }
    work_orders_sheet = workbook.create_sheet("Work Orders")
    chart_data = _ChartData(workbook.create_sheet(CHART_DATA_SHEET))
    chart_data.sheet.sheet_state = "hidden"
    data_sheet = workbook.create_sheet("Data")

    _report_sheet(report_sheet, payload, chart_data)
    for community in payload.distribution.communities:
        _community_sheet(community_sheets[community.key], payload, community, chart_data)
    _work_orders_sheet(work_orders_sheet, payload)
    _data_sheet(data_sheet, payload)

    buffer = io.BytesIO()
    workbook.save(buffer)
    return buffer.getvalue()


def report_xlsx_filename(payload: DailyReport) -> str:
    """Named for the period it covers, not the moment of export -- the same
    timesheet convention `report_filename` follows (user-hub-design.md D14)."""
    return f"wo-report_{payload.day.isoformat()}.xlsx"


# --------------------------------------------------------------------------
# Shared pieces
# --------------------------------------------------------------------------


class _ChartData:
    """Cursor over the hidden source sheet: one named block per chart (E7).

    Each block is a one-cell name, a header row, then its rows, then a blank
    row -- so a person who unhides the sheet can find what a chart reads."""

    def __init__(self, sheet: Worksheet) -> None:
        self.sheet = sheet
        self.row = 1

    def block(self, name: str, header: list, rows: list[list]) -> tuple[int, int]:
        """Write the block; return `(header_row, last_row)` for a `Reference`."""
        self.sheet.cell(row=self.row, column=1, value=name)
        header_row = self.row + 1
        for offset, value in enumerate(header, start=1):
            self.sheet.cell(row=header_row, column=offset, value=value)
        for index, values in enumerate(rows, start=1):
            for offset, value in enumerate(values, start=1):
                self.sheet.cell(row=header_row + index, column=offset, value=value)
        last_row = header_row + len(rows)
        self.row = last_row + 2
        return header_row, last_row


def _population_caveat(payload: DailyReport) -> str:
    """§2.1, on every designed sheet: what the population is, and why the
    community totals do not sum to the company total."""
    generated = payload.generated_at.astimezone(labor_day.CENTRAL)
    week = payload.week
    return (
        f"Live work orders as of {generated:%Y-%m-%d %H:%M} Central, plus work "
        f"orders closed {week.start.isoformat()} – {week.end.isoformat()}. A work "
        "order named in two communities is counted in both; community totals do "
        "not sum to the company total."
    )


def _bucket_rows(group: CommunityDistribution) -> list[list]:
    """Label / count / share, in bucket order. Shares are real fractions."""
    return [
        [
            BUCKET_LABELS[key],
            group.counts[key],
            (group.counts[key] / group.total) if group.total else 0,
        ]
        for key in BUCKET_KEYS
    ]


def _pie(
    sheet: Worksheet,
    chart_data: _ChartData,
    *,
    name: str,
    title: str,
    group,
    cells: str,
    legend: Optional[str],
    percent_labels: bool,
    empty_text: str = EMPTY_STATE,
) -> None:
    """A bucket pie for `group` (anything with `.total` and `.counts`) filling
    `cells`, or the empty-state line at the range's top-left when there is
    nothing to plot -- a pie with no area is a rendering bug, not a data point
    (§4.2)."""
    min_col, min_row, _, _ = range_boundaries(cells)
    if group.total == 0:
        theme.empty_state(sheet, min_row, empty_text, column=min_col)
        return
    header_row, last_row = chart_data.block(
        name,
        ["Bucket", "Count"],
        [[BUCKET_LABELS[key], group.counts[key]] for key in BUCKET_KEYS],
    )
    chart = theme.pie_of(
        chart_data.sheet,
        title=title,
        header_row=header_row,
        last_row=last_row,
        colors=BUCKET_COLOR_ORDER,
        legend=legend,
        percent_labels=percent_labels,
    )
    theme.place(sheet, chart, cells)


# --------------------------------------------------------------------------
# Report  (body added in Task 5)
# --------------------------------------------------------------------------


def _report_sheet(sheet: Worksheet, payload: DailyReport, chart_data: _ChartData) -> None:
    theme.setup_sheet(sheet, tab_color=theme.BRAND_RED)
    week = payload.week
    generated = payload.generated_at.astimezone(labor_day.CENTRAL)
    theme.title_block(
        sheet,
        "Weekly Work Order Report",
        [
            f"{payload.day.strftime('%a, %b %d, %Y')} · week of "
            f"{week.start.isoformat()} – {week.end.isoformat()} (week to date)",
            f"Generated {generated.strftime('%Y-%m-%d %H:%M')} Central",
            _population_caveat(payload),
        ],
    )


# --------------------------------------------------------------------------
# Community sheets  (body added in Task 6)
# --------------------------------------------------------------------------


def _community_sheet(
    sheet: Worksheet,
    payload: DailyReport,
    community: CommunityDistribution,
    chart_data: _ChartData,
) -> None:
    theme.setup_sheet(sheet, tab_color=theme.MUTED)
    theme.title_block(
        sheet,
        community.label,
        [
            f"Weekly status · {community.total:,} work orders",
            _population_caveat(payload),
        ],
    )


# --------------------------------------------------------------------------
# Work Orders
# --------------------------------------------------------------------------

WORK_ORDERS_HEADER_ROW = 5

WORK_ORDER_HEADERS: tuple[str, ...] = (
    "WORK ORDER",
    "LOCATION",
    "NOTES",
    "BUCKET",
    "STATUS",
    "COMMUNITIES",
    "SERVICE TYPE",
    "PRIORITY",
    "BUILDING",
    "UNIT",
    "SUPERVISOR",
    "TECHNICIANS",
    "MATERIAL LINES",
    "MATERIALS TOTAL",
    "LABOR MINUTES",
    "LABOR TOTAL",
    "TOTAL",
    "CREATED AT",
    "COMPLETED AT",
    "CLOSED AT",
    "SECTIONS",
)

WORK_ORDER_WIDTHS: tuple[int, ...] = (
    14, 34, theme.NOTES_WIDTH, 14, 16, 22, 18, 12, 10, 10, 18, 24, 12, 14, 12, 14, 14, 18, 18, 18, 20,
)

# 0-based column offset -> number format.
WORK_ORDER_FORMATS: dict[int, str] = {
    12: theme.COUNT,
    13: theme.MONEY,
    14: theme.COUNT,
    15: theme.MONEY,
    16: theme.MONEY,
    17: theme.DATE,
    18: theme.DATE,
    19: theme.DATE,
}


def _excel_utc(value: Optional[datetime]) -> Optional[datetime]:
    """UTC, naive: openpyxl refuses tz-aware datetimes. UTC on purpose -- the
    same seam `export_row` writes (§5); the covered period is in the title."""
    if value is None:
        return None
    return labor_day.as_utc(value).astimezone(timezone.utc).replace(tzinfo=None)


def _sections_of(payload: DailyReport) -> dict[UUID, list[str]]:
    """Which report sections each work order appeared in, in SECTION_ORDER --
    the `Data` sheet's SECTION filter folded into one deduped row."""
    seen: dict[UUID, list[str]] = {}
    for key in SECTION_ORDER:
        for row in getattr(payload.sections, key).rows:
            seen.setdefault(row.work_order_id, []).append(key)
    return seen


def _work_order_cells(row: ReportRow, sections: dict[UUID, list[str]]) -> list:
    return [
        row.number,
        row.location,
        row.notes,
        BUCKET_LABELS[row_bucket(row)],
        STATUS_LABELS.get(row.status, row.status),
        "; ".join(communities_of(row)),
        row.service_type,
        row.priority,
        row.building_number,
        row.unit_number,
        row.supervisor_name,
        "; ".join(row.technician_names),
        row.material_lines,
        row.materials_total,
        row.labor_minutes,
        row.labor_total,
        row.total,
        _excel_utc(row.created_at),
        _excel_utc(row.completed_at),
        _excel_utc(row.archived_at),
        "; ".join(sections.get(row.work_order_id, [])),
    ]


def _work_orders_sheet(sheet: Worksheet, payload: DailyReport) -> None:
    """One row per work order over the E1 population, deduped, in reading
    order (§4.3). Money is numeric here -- this sheet is for reading and
    pivoting, and it is not the re-import path."""
    theme.setup_sheet(
        sheet,
        tab_color=theme.INK,
        freeze=f"D{WORK_ORDERS_HEADER_ROW + 1}",
        print_title_rows=f"{WORK_ORDERS_HEADER_ROW}:{WORK_ORDERS_HEADER_ROW}",
    )
    theme.set_widths(
        sheet,
        {get_column_letter(index): width for index, width in enumerate(WORK_ORDER_WIDTHS, start=1)},
    )
    week = payload.week
    theme.title_block(
        sheet,
        "Work Orders",
        [
            f"{len(payload.all_rows):,} work orders · live now plus closed "
            f"{week.start.isoformat()} – {week.end.isoformat()}",
            "One row per work order. Timestamps are UTC; the covered period is "
            "in the line above and in the filename.",
        ],
    )

    sections = _sections_of(payload)
    rows = [_work_order_cells(row, sections) for row in payload.all_rows]
    theme.table_of(
        sheet,
        name="WorkOrders",
        row=WORK_ORDERS_HEADER_ROW,
        headers=WORK_ORDER_HEADERS,
        rows=rows,
        formats=WORK_ORDER_FORMATS,
        alignment=theme.TOP,
    )
    first = WORK_ORDERS_HEADER_ROW + 1
    for index, row in enumerate(payload.all_rows, start=first):
        sheet.cell(row=index, column=3).alignment = theme.TOP_WRAPPED
        height = theme.notes_row_height(row.notes)
        if height is not None:
            sheet.row_dimensions[index].height = height
    if not rows:
        theme.empty_state(sheet, first, EMPTY_STATE)


# --------------------------------------------------------------------------
# Data
# --------------------------------------------------------------------------


def _data_sheet(sheet: Worksheet, payload: DailyReport) -> None:
    """`report_csv` as cells: same header, same section order, same values.

    Deliberately not coerced to numbers. The money columns stay the strings
    `export_row` produced, so Excel shows its "number stored as text" hint on
    them -- that is the price of the CSV being byte-identical, and the charts
    are immune because they read `Chart Data` instead."""
    theme.setup_sheet(sheet, tab_color=theme.TAB_GRAY, freeze="A2", gridlines=True)
    sheet.append([CSV_SECTION_HEADER, *wo.EXPORT_HEADERS])
    for cell in sheet[1]:
        cell.font = theme.font(bold=True)
    for key in SECTION_ORDER:
        # All five sections, so a row appears under both `closed_today` and
        # `closed_week` -- the CSV's filter-on-SECTION property, preserved.
        for row in getattr(payload.sections, key).rows:
            sheet.append([key, *row.export_cells])
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report_xlsx.py -q
```

Expected: `13 passed`. (`CLOSING_STATUSES`, `BUCKET_CLOSED`, `Decimal`, `grid_of`, `PLACEHOLDER`, `primary_community` are imported/defined now but first used in Tasks 5–6; a linter warning about unused names is acceptable until then.)

- [ ] **Step 5: Confirm the workbook opens cleanly from an empty payload**

```bash
venv/Scripts/python -c "
import io, openpyxl, sys
sys.path.insert(0, '.')
from tests.test_work_order_report_xlsx import _payload
from app.services import work_order_report_xlsx as x
wb = openpyxl.load_workbook(io.BytesIO(x.report_xlsx(_payload())))
print(wb.sheetnames, wb['Work Orders']['A6'].value)
"
```

Expected: the nine names and `No live or recently closed work orders.`

- [ ] **Step 6: Commit**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git && git add backend/app/services/work_order_report_xlsx.py backend/tests/test_work_order_report_xlsx.py && git commit -m "feat(hub-report): rebuild the workbook skeleton with a readable Work Orders sheet

Report, five community sheets, Work Orders, hidden Chart Data, then Data
last. Work Orders is one deduped row per work order over the live-plus-
closed-this-week population, Notes in column C, numeric money, UTC
timestamps, and a SECTIONS column folding the Data sheet's filter into one
row. Report and community sheets carry their title blocks; bodies follow.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md"
```

---

### Task 5: The `Report` sheet

**Files:**
- Modify: `backend/app/services/work_order_report_xlsx.py` (the `_report_sheet` section)
- Modify: `backend/tests/test_work_order_report_xlsx.py` (append)

**Interfaces:**
- Consumes: `_pie`, `_bucket_rows`, `_ChartData.block`, `theme.*`, `payload.distribution.company`, `payload.sections.*`, `CLOSING_STATUSES`, `STATUS_LABELS`.
- Produces: `KPI_ROW = 6`, `STATUS_ROW = 10`, `ACTIVITY_ROW = 26`, `DOLLARS_ROW = 42`, `BY_COMMUNITY_ROW = 58`, `CHART_ROWS = 15`, `DOLLARS_FOOTNOTE`, `_community_money(rows) -> list[tuple[str, Decimal, Decimal]]`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_work_order_report_xlsx.py`:

```python


# --- Report (§4.1, E11) -----------------------------------------------------


def test_report_title_block_names_the_day_week_and_population():
    sheet = _workbook(_scholars_payload())["Report"]

    assert sheet["A1"].value == "Weekly Work Order Report"
    assert sheet["A2"].value == "Tue, Aug 25, 2026 · week of 2026-08-24 – 2026-08-30 (week to date)"
    assert sheet["A3"].value == "Generated 2026-08-25 17:30 Central"
    assert sheet["A4"].value.startswith("Live work orders as of 2026-08-25 17:30 Central, plus work orders closed 2026-08-24 – 2026-08-30.")
    assert "counted in both" in sheet["A4"].value
    assert sheet.freeze_panes == "A5"


def test_report_kpi_strip_is_open_then_the_three_live_buckets_then_closed():
    sheet = _workbook(_scholars_payload())["Report"]

    assert [cell.value for cell in sheet[xlsx.KPI_ROW]][:5] == [
        "Open work orders",
        "Accepted",
        "In progress",
        "Ready to close",
        "Closed this week",
    ]
    assert [cell.value for cell in sheet[xlsx.KPI_ROW + 1]][:5] == [5, 3, 1, 1, 2]
    assert sheet.cell(row=xlsx.KPI_ROW + 1, column=1).border.bottom.color.rgb.endswith("C8102E")


def test_report_company_status_block_has_counts_and_real_shares():
    sheet = _workbook(_scholars_payload())["Report"]

    assert sheet.cell(row=xlsx.STATUS_ROW, column=1).value == "Company status"
    assert [cell.value for cell in sheet[xlsx.STATUS_ROW + 1]][:3] == ["Bucket", "Count", "Share"]
    rows = [
        [sheet.cell(row=row, column=col).value for col in (1, 2, 3)]
        for row in range(xlsx.STATUS_ROW + 2, xlsx.STATUS_ROW + 6)
    ]
    assert [row[:2] for row in rows] == [
        ["Accepted", 3],
        ["In progress", 1],
        ["Ready to close", 1],
        ["Closed", 2],
    ]
    assert [row[2] for row in rows] == pytest.approx([3 / 7, 1 / 7, 1 / 7, 2 / 7])
    assert sheet.cell(row=xlsx.STATUS_ROW + 2, column=3).number_format == "0.0%"


def test_report_activity_block_matches_the_payload_counts():
    sheet = _workbook(_scholars_payload())["Report"]

    assert sheet.cell(row=xlsx.ACTIVITY_ROW, column=1).value == "Activity"
    # The corner cell is written as None: openpyxl reloads "" as None anyway.
    assert [cell.value for cell in sheet[xlsx.ACTIVITY_ROW + 1]][:3] == [None, "Today", "Week to date"]
    assert [
        [sheet.cell(row=row, column=col).value for col in (1, 2, 3)]
        for row in (xlsx.ACTIVITY_ROW + 2, xlsx.ACTIVITY_ROW + 3)
    ] == [["Closed", 1, 2], ["New", 1, 2]]
    assert sheet.cell(row=xlsx.ACTIVITY_ROW + 4, column=1).value is None


def test_report_activity_block_notes_auto_closed_work_orders():
    payload = _payload(
        closed_today=[_row(status=wo.STATUS_COMPLETED, archived=True)],
        auto_closed_today=1,
    )
    sheet = _workbook(payload)["Report"]

    assert sheet.cell(row=xlsx.ACTIVITY_ROW + 4, column=1).value == (
        "Closed today includes (1 in NetFacilities); this week (0 in NetFacilities)"
    )


def test_report_dollars_block_is_by_primary_community_and_counts_each_row_once():
    week = [
        _row(number="WO-1", community="Centennial", status=wo.STATUS_COMPLETED, archived=True,
             labor_total="100.00", materials_total="10.00"),
        # Named in two communities: attributed to Scholars (first in filter
        # order) and counted once (E14).
        _row(number="WO-2", location="Commons annex / Scholars 3", status=wo.STATUS_COMPLETED,
             archived=True, labor_total="5.00", materials_total="0.00"),
        _row(number="WO-3", community="Centennial", status=wo.STATUS_COMPLETED, archived=True,
             labor_total="50.00", materials_total="20.00"),
        # Nothing named: Academics, never "(no community)".
        _row(number="WO-4", status=wo.STATUS_COMPLETED, archived=True,
             labor_total="1.00", materials_total="0.00"),
    ]

    assert xlsx._community_money(week) == [
        ("Centennial", Decimal("150.00"), Decimal("30.00")),
        ("Scholars", Decimal("5.00"), Decimal("0.00")),
        ("Academics", Decimal("1.00"), Decimal("0.00")),
    ]

    sheet = _workbook(_payload(closed_week=week))["Report"]
    assert sheet.cell(row=xlsx.DOLLARS_ROW, column=1).value == "Dollars closed this week"
    assert [cell.value for cell in sheet[xlsx.DOLLARS_ROW + 1]][:4] == ["Community", "Labor", "Materials", "Total"]
    assert [cell.value for cell in sheet[xlsx.DOLLARS_ROW + 2]][:4] == [
        "Centennial", Decimal("150.00"), Decimal("30.00"), Decimal("180.00"),
    ]
    assert sheet.cell(row=xlsx.DOLLARS_ROW + 2, column=2).number_format == "$#,##0.00"
    # Three money rows (44-46), footnote on the next row (E14).
    assert sheet.cell(row=xlsx.DOLLARS_ROW + 5, column=1).value == xlsx.DOLLARS_FOOTNOTE
    assert xlsx.DOLLARS_FOOTNOTE == "Dollars count a work order under its first community."


def test_report_by_community_table_and_the_ready_to_close_footnote():
    sheet = _workbook(_scholars_payload())["Report"]
    grid = _cells(sheet)
    top = next(index for index, row in enumerate(grid, start=1) if row and row[0] == "By community")

    assert top == xlsx.BY_COMMUNITY_ROW  # fixed (P8): the dollars block is bounded by E14
    assert grid[top][:6] == ["Community", "Accepted", "In progress", "Ready to close", "Closed", "Total"]
    assert grid[top + 1][:6] == ["Scholars", 3, 1, 1, 2, 7]
    assert grid[top + 5][:6] == ["Academics", 0, 0, 0, 0, 0]
    assert [t.displayName for t in sheet.tables.values()] == ["ByCommunity"]
    footnotes = [row[0] for row in grid[top + 6 : top + 9] if row and row[0]]
    assert footnotes[0] == "Ready to close = 0 ready to complete, 0 completed, 1 review."
    assert "counted in both" in footnotes[1]


def test_report_with_nothing_to_plot_shows_the_empty_state_instead_of_a_zero_pie():
    sheet = _workbook(_payload())["Report"]

    assert sheet.cell(row=xlsx.STATUS_ROW, column=7).value == "No live or recently closed work orders."
    assert [cell.value for cell in sheet[xlsx.KPI_ROW + 1]][:5] == [0, 0, 0, 0, 0]
    assert [cell.value for cell in sheet[xlsx.DOLLARS_ROW + 2]][:4] == [
        "(none)", Decimal("0.00"), Decimal("0.00"), Decimal("0.00"),
    ]
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report_xlsx.py -q -k report_
```

Expected: 8 failures — `module has no attribute 'KPI_ROW'` etc.

- [ ] **Step 3: Replace the `_report_sheet` section of the renderer**

Replace the block from the `# Report  (body added in Task 5)` banner through the end of the `_report_sheet` function with:

```python
# --------------------------------------------------------------------------
# Report
# --------------------------------------------------------------------------

REPORT_WIDTHS = {"A": 28, "B": 14, "C": 14, "D": 14, "E": 14, "F": 3}

# Fixed rows (§4.1). Every block is fixed-height: dollars are grouped by
# primary community (E14), so that block is at most five rows plus a
# footnote, and "By community" sits at BY_COMMUNITY_ROW (P8).
KPI_ROW = 6
STATUS_ROW = 10
ACTIVITY_ROW = 26
DOLLARS_ROW = 42
BY_COMMUNITY_ROW = 58

# Charts fill G:M beside the A:E blocks, 15 rows tall (about 8 cm).
CHART_ROWS = 15

# Under the dollars block (E14): primary attribution, stated on the sheet.
DOLLARS_FOOTNOTE = "Dollars count a work order under its first community."


def _chart_cells(top: int) -> str:
    return f"G{top}:M{top + CHART_ROWS - 1}"


def _community_money(
    rows: list[ReportRow],
) -> list[tuple[str, Decimal, Decimal]]:
    """Labor and materials dollars per primary community, biggest combined
    first (E14).

    `primary_community` -- a row's first membership -- rather than the raw
    `community` column (NULL on every imported row) or the full membership
    list (a row named in two communities must not have its dollars counted
    twice). Decimals throughout -- openpyxl writes them natively, and the
    report's money is never a float anywhere else either."""
    totals: dict[str, list[Decimal]] = {}
    for row in rows:
        key = primary_community(row)
        bucket = totals.setdefault(key, [Decimal("0.00"), Decimal("0.00")])
        bucket[0] += row.labor_total
        bucket[1] += row.materials_total
    return sorted(
        ((name, labor, materials) for name, (labor, materials) in totals.items()),
        key=lambda entry: (-(entry[1] + entry[2]), entry[0]),
    )


def _report_sheet(sheet: Worksheet, payload: DailyReport, chart_data: _ChartData) -> None:
    theme.setup_sheet(sheet, tab_color=theme.BRAND_RED)
    theme.set_widths(sheet, REPORT_WIDTHS)
    week = payload.week
    generated = payload.generated_at.astimezone(labor_day.CENTRAL)
    theme.title_block(
        sheet,
        "Weekly Work Order Report",
        [
            f"{payload.day.strftime('%a, %b %d, %Y')} · week of "
            f"{week.start.isoformat()} – {week.end.isoformat()} (week to date)",
            f"Generated {generated.strftime('%Y-%m-%d %H:%M')} Central",
            _population_caveat(payload),
        ],
    )
    company = payload.distribution.company
    sections = payload.sections

    # KPI strip. "Open" is the three live buckets; Closed is the week's
    # output -- the deleted pipeline chart's numbers, restated (§4.1).
    open_count = company.total - company.counts[BUCKET_CLOSED]
    tiles = [
        ("Open work orders", open_count),
        (BUCKET_LABELS["accepted"], company.counts["accepted"]),
        (BUCKET_LABELS["in_progress"], company.counts["in_progress"]),
        (BUCKET_LABELS["ready_to_close"], company.counts["ready_to_close"]),
        ("Closed this week", company.counts[BUCKET_CLOSED]),
    ]
    for column, (label, value) in enumerate(tiles, start=1):
        theme.kpi(sheet, KPI_ROW, column, label, value)

    # Company status: the four-slice pie beside its exact-value block (E9).
    theme.section(sheet, STATUS_ROW, "Company status")
    theme.header_row(sheet, STATUS_ROW + 1, ("Bucket", "Count", "Share"))
    theme.write_rows(
        sheet,
        STATUS_ROW + 2,
        _bucket_rows(company),
        formats={1: theme.COUNT, 2: theme.PERCENT},
    )
    _pie(
        sheet,
        chart_data,
        name="company",
        title="Company status",
        group=company,
        cells=_chart_cells(STATUS_ROW),
        legend="r",
        percent_labels=True,
    )

    # Activity: section counts, never row tallies -- `closing` can be capped
    # and the page follows the same rule (X8).
    theme.section(sheet, ACTIVITY_ROW, "Activity")
    activity = [
        ["Closed", sections.closed_today.count, sections.closed_week.count],
        ["New", sections.new_today.count, sections.new_week.count],
    ]
    theme.header_row(sheet, ACTIVITY_ROW + 1, (None, "Today", "Week to date"))
    theme.write_rows(
        sheet, ACTIVITY_ROW + 2, activity, formats={1: theme.COUNT, 2: theme.COUNT}
    )
    auto_today = sections.closed_today.auto_closed_count
    auto_week = sections.closed_week.auto_closed_count
    if auto_today or auto_week:
        # The page's own phrasing (R10), so the file reads like the screen.
        theme.note(
            sheet,
            ACTIVITY_ROW + 4,
            f"Closed today includes ({auto_today} in NetFacilities); "
            f"this week ({auto_week} in NetFacilities)",
        )
    header_row, last_row = chart_data.block("activity", [None, "Today", "Week to date"], activity)
    theme.place(
        sheet,
        theme.column_chart_of(
            chart_data.sheet,
            title="Activity",
            header_row=header_row,
            last_row=last_row,
            y_title="Work orders",
        ),
        _chart_cells(ACTIVITY_ROW),
    )

    # Dollars closed this week, stacked labor over materials (X11).
    theme.section(sheet, DOLLARS_ROW, "Dollars closed this week")
    money = _community_money(sections.closed_week.rows) or [
        (PLACEHOLDER, Decimal("0.00"), Decimal("0.00"))
    ]
    theme.header_row(sheet, DOLLARS_ROW + 1, ("Community", "Labor", "Materials", "Total"))
    dollars_last = theme.write_rows(
        sheet,
        DOLLARS_ROW + 2,
        [[name, labor, materials, labor + materials] for name, labor, materials in money],
        formats={1: theme.MONEY, 2: theme.MONEY, 3: theme.MONEY},
    )
    theme.note(sheet, dollars_last + 1, DOLLARS_FOOTNOTE)
    header_row, last_row = chart_data.block(
        "dollars",
        ["Community", "Labor", "Materials"],
        [[name, labor, materials] for name, labor, materials in money],
    )
    theme.place(
        sheet,
        theme.column_chart_of(
            chart_data.sheet,
            title="Dollars closed this week",
            header_row=header_row,
            last_row=last_row,
            stacked=True,
            y_title="Dollars",
        ),
        _chart_cells(DOLLARS_ROW),
    )

    # By community: the four buckets per community, then the Ready-to-close
    # three-status split as a footnote (E11) and the memberships caveat.
    # Fixed row (P8): the dollars block above is bounded by E14.
    top = BY_COMMUNITY_ROW
    theme.section(sheet, top, "By community")
    last = theme.table_of(
        sheet,
        name="ByCommunity",
        row=top + 1,
        headers=("Community", *BUCKET_LABELS.values(), "Total"),
        rows=[
            [entry.label, *(entry.counts[key] for key in BUCKET_KEYS), entry.total]
            for entry in payload.distribution.communities
        ],
        formats={offset: theme.COUNT for offset in range(1, 6)},
    )
    by_status = sections.closing.by_status
    split = ", ".join(
        f"{by_status.get(status, 0):,} {STATUS_LABELS[status].lower()}"
        for status in CLOSING_STATUSES
    )
    theme.note(sheet, last + 2, f"Ready to close = {split}.")
    theme.note(
        sheet,
        last + 3,
        "A work order named in two communities is counted in both; community "
        "rows do not sum to the company figures above.",
    )
```

- [ ] **Step 4: Run the tests to verify they pass**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report_xlsx.py -q
```

Expected: `21 passed`.

- [ ] **Step 5: Commit**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git && git add backend/app/services/work_order_report_xlsx.py backend/tests/test_work_order_report_xlsx.py && git commit -m "feat(hub-report): designed Report overview with KPI strip, company pie, activity, dollars

Five KPI tiles over the four-bucket company pie with its exact-value
block, the Activity and Dollars column charts in the brand-red / neutral
treatment, and a By-community table with the Ready-to-close three-status
split as a footnote. The old Summary sheet's pipeline and service-type
charts are gone: they are the Ready-to-close slice and the per-community
grid now.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md"
```

---

### Task 6: The community sheets and the zip-level chart tests

**Files:**
- Modify: `backend/app/services/work_order_report_xlsx.py` (the `_community_sheet` section)
- Modify: `backend/tests/test_work_order_report_xlsx.py` (append)

**Interfaces:**
- Consumes: `_pie`, `_bucket_rows`, `grid_of`, `theme.*`, `CommunityDistribution`.
- Produces: `COMMUNITY_WIDTHS`, `COMMUNITY_PIE_CELLS = "A6:D20"`, `COMMUNITY_BLOCK_COLUMN = 6`, `GRID_SECTION_ROW = 22`, `GRID_CELLS` (nine inclusive ranges, row-major), `DETAIL_ROW = 64`.

- [ ] **Step 1: Write the failing tests**

Append to `backend/tests/test_work_order_report_xlsx.py`:

```python


# --- community sheets (§4.2, E6, E8, E9) ------------------------------------


def test_community_sheet_title_pie_block_and_detail_table():
    sheet = _workbook(_scholars_payload())["Scholars"]

    assert sheet["A1"].value == "Scholars"
    assert sheet["A2"].value == "Weekly status · 7 work orders"
    assert "counted in both" in sheet["A3"].value
    assert sheet["A5"].value == "Status"
    assert sheet.column_dimensions["A"].width == 22
    assert all(sheet.column_dimensions[letter].width == 11 for letter in "BCDEFGHIJ")

    # Exact-value block beside the pie (E9): F6 header, F7:H10 buckets.
    assert [cell.value for cell in sheet[6]][5:8] == ["Bucket", "Count", "Share"]
    assert [
        [sheet.cell(row=row, column=col).value for col in (6, 7)] for row in range(7, 11)
    ] == [["Accepted", 3], ["In progress", 1], ["Ready to close", 1], ["Closed", 2]]
    assert sheet["H7"].value == pytest.approx(3 / 7)

    assert sheet["A22"].value == "By service type"
    assert sheet["A23"].value is None
    assert sheet["A64"].value == "Service type detail"
    assert [cell.value for cell in sheet[65]][:6] == [
        "Service type", "Accepted", "In progress", "Ready to close", "Closed", "Total",
    ]
    assert [cell.value for cell in sheet[66]][:6] == ["Plumbing", 3, 0, 1, 2, 6]
    assert [cell.value for cell in sheet[67]][:6] == ["HVAC", 0, 1, 0, 0, 1]
    assert [(t.displayName, t.ref) for t in sheet.tables.values()] == [
        ("ServiceTypes_scholars", "A65:F67")
    ]


def test_empty_community_renders_the_empty_state_and_nothing_else():
    sheet = _workbook(_scholars_payload())["Centennial"]

    assert sheet["A2"].value == "Weekly status · 0 work orders"
    assert sheet["A5"].value == "No live or recently closed work orders in this community."
    assert sheet.max_row == 5
    assert sheet.tables == {}


def _eleven_service_types_in_commons():
    live = [
        _row(number=f"WO-{index}", community="Commons", service_type=f"Trade {index:02d}")
        for index in range(11)
    ] + [_row(number="WO-extra", community="Commons", service_type="Trade 00")]
    return _payload(live=live)


def test_grid_caps_at_nine_cards_and_says_so():
    sheet = _workbook(_eleven_service_types_in_commons())["Commons"]

    assert sheet["A23"].value == '"Other" combines 3 further service types.'
    # The detail table still lists every service type, so the cap costs no
    # information (E8).
    labels = _column(sheet, 1, 66, 76)
    assert labels[0] == "Trade 00" and len(labels) == 11 and "Other" not in labels
    assert sheet.cell(row=77, column=1).value is None


# --- charts, at the zip level (§7) ------------------------------------------


def test_chart_count_is_three_plus_one_per_community_plus_one_per_card():
    parts = _chart_parts(_scholars_payload())

    # Report: pie + activity + dollars. Scholars: pie + Plumbing + HVAC.
    assert len(parts) == 6
    assert all('plotVisOnly val="0"' in xml for xml in parts.values())


def test_every_pie_is_fixed_order_and_fixed_color():
    parts = _chart_parts(_scholars_payload())
    pies = [xml for xml in parts.values() if "<pieChart>" in xml]

    assert len(pies) == 3
    for xml in pies:
        assert 'firstSliceAng val="0"' in xml
        assert xml.index("9CA3AF") < xml.index("D97706") < xml.index("6D28D9") < xml.index("15803D")
        assert "C8102E" not in xml


def test_grid_cards_have_no_legend_but_every_other_chart_does():
    parts = _chart_parts(_scholars_payload())

    # Report pie + activity + dollars, plus the Scholars status pie: four
    # legends. The two Scholars cards (Plumbing, HVAC) carry none (E15).
    assert sum("<legend>" in xml for xml in parts.values()) == 4


def test_grid_cards_are_capped_at_nine_charts():
    parts = _chart_parts(_eleven_service_types_in_commons())

    # Report pie + activity + dollars, Commons pie, nine cards.
    assert len(parts) == 3 + 1 + 9


def test_empty_workbook_has_no_pies_and_every_community_is_an_empty_state():
    payload = _payload()
    workbook = _workbook(payload)
    parts = _chart_parts(payload)

    # Activity and Dollars always render; every pie is an empty state.
    assert len(parts) == 2
    assert not any("<pieChart>" in xml for xml in parts.values())
    for name in ("Scholars", "Centennial", "Commons", "Young Hall", "Academics"):
        assert workbook[name]["A5"].value == (
            "No live or recently closed work orders in this community."
        )


def test_chart_data_blocks_are_named_and_hidden():
    sheet = _workbook(_scholars_payload())["Chart Data"]
    names = [row[0] for row in _cells(sheet) if row and isinstance(row[0], str)]

    assert sheet.sheet_state == "hidden"
    assert names[:3] == ["company", "Bucket", "Accepted"]
    assert "activity" in names and "dollars" in names
    assert "scholars" in names and "scholars:plumbing" in names and "scholars:hvac" in names
```

- [ ] **Step 2: Run the tests to verify they fail**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report_xlsx.py -q -k "community or grid or chart or empty_workbook"
```

Expected: failures on `A5` (`None != "Status"`), table lists, and chart counts (`3 != 6`).

- [ ] **Step 3: Replace the `_community_sheet` section of the renderer**

Replace the block from the `# Community sheets  (body added in Task 6)` banner through the end of the `_community_sheet` function with:

```python
# --------------------------------------------------------------------------
# Community sheets
# --------------------------------------------------------------------------

# A = 22, B-J = 11 uniform, so the 3 x 3 grid below lines up (§4.2).
COMMUNITY_WIDTHS = {"A": 22, **{letter: 11 for letter in "BCDEFGHIJ"}}

COMMUNITY_PIE_CELLS = "A6:D20"
COMMUNITY_BLOCK_COLUMN = 6  # F6:H10 -- one column of air after the pie
GRID_SECTION_ROW = 22  # heading; the "Other" note sits on row 23
DETAIL_ROW = 64

# Nine cards, row-major: B/E/H, thirteen rows apart, each 12 rows tall.
GRID_CELLS: tuple[str, ...] = tuple(
    f"{first}{top}:{last}{top + 12}"
    for top in (24, 37, 50)
    for first, last in (("B", "D"), ("E", "G"), ("H", "J"))
)


def _community_sheet(
    sheet: Worksheet,
    payload: DailyReport,
    community: CommunityDistribution,
    chart_data: _ChartData,
) -> None:
    theme.setup_sheet(sheet, tab_color=theme.MUTED)
    theme.set_widths(sheet, COMMUNITY_WIDTHS)
    theme.title_block(
        sheet,
        community.label,
        [
            f"Weekly status · {community.total:,} work orders",
            _population_caveat(payload),
        ],
    )
    if community.total == 0:
        # No charts of zeros (§4.2): the line stands in for the whole body.
        theme.empty_state(sheet, 5, EMPTY_COMMUNITY_STATE)
        return

    theme.section(sheet, 5, "Status", span=10)
    _pie(
        sheet,
        chart_data,
        name=community.key,
        title=f"{community.label} · status",
        group=community,
        cells=COMMUNITY_PIE_CELLS,
        legend="r",
        percent_labels=True,
        empty_text=EMPTY_COMMUNITY_STATE,
    )
    theme.header_row(sheet, 6, ("Bucket", "Count", "Share"), column=COMMUNITY_BLOCK_COLUMN)
    theme.write_rows(
        sheet,
        7,
        _bucket_rows(community),
        column=COMMUNITY_BLOCK_COLUMN,
        formats={1: theme.COUNT, 2: theme.PERCENT},
    )

    theme.section(sheet, GRID_SECTION_ROW, "By service type", span=10)
    cards, folded = grid_of(community.service_types)
    if folded:
        theme.note(
            sheet,
            GRID_SECTION_ROW + 1,
            f'"Other" combines {folded} further service types.',
        )
    for card, cells in zip(cards, GRID_CELLS):
        _pie(
            sheet,
            chart_data,
            name=f"{community.key}:{card.key}",
            title=f"{card.label} · {card.total:,}",
            group=card,
            cells=cells,
            legend=None,  # E15: the status pie above is the shared key
            percent_labels=False,
        )

    theme.section(sheet, DETAIL_ROW, "Service type detail", span=10)
    theme.table_of(
        sheet,
        name=f"ServiceTypes_{community.key}",
        row=DETAIL_ROW + 1,
        headers=("Service type", *BUCKET_LABELS.values(), "Total"),
        rows=[
            [entry.label, *(entry.counts[key] for key in BUCKET_KEYS), entry.total]
            for entry in community.service_types
        ],
        formats={offset: theme.COUNT for offset in range(1, 6)},
    )
```

- [ ] **Step 4: Run the whole xlsx suite**

```bash
venv/Scripts/python -m pytest tests/test_work_order_report_xlsx.py tests/test_xlsx_theme.py tests/test_work_order_report_buckets.py -q
```

Expected: all pass (`31 passed` in the xlsx file).

- [ ] **Step 5: Check the line count**

```bash
wc -l app/services/work_order_report_xlsx.py app/services/_xlsx_theme.py
```

Expected: both under 500. If the renderer is over, apply the pre-approved split from Global Constraints (move `_report_sheet` + its constants + `_community_money`, and `_community_sheet` + its constants, into `app/services/work_order_report_xlsx_charts.py`; that module imports `_ChartData`, `_pie`, `_bucket_rows`, `_population_caveat`, `PLACEHOLDER`, `EMPTY_COMMUNITY_STATE` from the renderer, and the renderer imports the two sheet functions back lazily inside `report_xlsx` to avoid the cycle). Re-run Step 4 afterwards; tests reference `xlsx.KPI_ROW` etc., so re-export those names from the renderer.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git && git add backend/app/services/work_order_report_xlsx.py backend/tests/test_work_order_report_xlsx.py && git commit -m "feat(hub-report): one chart sheet per community with a service-type small-multiple grid

Each community sheet: the four-slice status pie with its exact-value
block, a 3 x 3 grid of service-type pies (top eight plus an Other roll-up
past nine, stated on the sheet), and an Excel Table listing every service
type. An empty community renders an empty-state line, never a zero pie.
Charts are asserted at the zip level: count, plotVisOnly=0, fixed slice
order and color.

Spec: docs/superpowers/specs/2026-08-30-hub-report-xlsx-redesign-design.md"
```

---

### Task 7: Router docstring, router test, endpoint map

**Files:**
- Modify: `backend/app/routers/hub.py:252-270`
- Modify: `backend/tests/test_hub_router.py:270-284`
- Modify: `docs/endpoint-map.md:1258-1261`

- [ ] **Step 1: Update the router test expectation**

In `backend/tests/test_hub_router.py`, `test_report_export_is_an_attachment_xlsx`, change:

```python
    assert workbook.sheetnames == ["Summary", "Data"]
```

to:

```python
    assert workbook.sheetnames == [
        "Report",
        "Scholars",
        "Centennial",
        "Commons",
        "Young Hall",
        "Academics",
        "Work Orders",
        "Chart Data",
        "Data",
    ]
    assert workbook["Chart Data"].sheet_state == "hidden"
    assert workbook["Work Orders"]["C5"].value == "NOTES"
```

- [ ] **Step 2: Run it to see it fail, then pass after the docstring edit is irrelevant to it**

```bash
venv/Scripts/python -m pytest tests/test_hub_router.py -q -k report_export
```

Expected: passes already (the renderer is done); if it fails on `sheetnames`, the renderer from Task 4 was not committed — stop and check `git status`.

- [ ] **Step 3: Update the route docstring**

In `backend/app/routers/hub.py`, replace the `export_hub_report` docstring:

```python
    """The same payload as an Excel workbook: a charted `Summary` sheet over a
    `Data` sheet that is the `SECTION`-prefixed CSV, cell for cell.

    Composed from `daily_report` rather than from its own query, so the file and
    the screen -- truncation included -- cannot disagree. `report_csv` is still
    the executable contract the `Data` sheet is tested against; restoring a CSV
    download is a one-line flip back to it."""
```

with:

```python
    """The same payload as an Excel workbook: a designed `Report` overview, one
    four-bucket chart sheet per community, a readable deduped `Work Orders`
    sheet, and -- last -- a `Data` sheet that is the `SECTION`-prefixed CSV,
    cell for cell.

    Composed from `daily_report` rather than from its own query, so the file and
    the screen cannot disagree. `report_csv` is still the executable contract
    the `Data` sheet is tested against; restoring a CSV download is a one-line
    flip back to it."""
```

- [ ] **Step 4: Update the endpoint map**

In `docs/endpoint-map.md`, replace:

```
`GET /hub/report/export` serializes the same payload as an `.xlsx` workbook: a
charted `Summary` sheet over a `Data` sheet that is the `SECTION`-prefixed CSV
cell for cell — header `SECTION` + the 26 `EXPORT_HEADERS` — so a save-as-CSV
from Excel still re-imports through `POST /work-orders/import`.
```

with:

```
`GET /hub/report/export` serializes the same payload as an `.xlsx` workbook
(`work_order_report_xlsx.report_xlsx`, styled by `_xlsx_theme`): a `Report`
overview (KPI strip, company four-bucket pie, activity, dollars, by-community
table), one chart sheet per community (status pie plus a 3×3 service-type
grid over the same four buckets — Accepted / In progress / Ready to close /
Closed, `work_order_report_buckets.REPORT_BUCKETS`), a deduped `Work Orders`
sheet (Notes in column C) over the live-plus-closed-this-week population
(`DailyReport.all_rows`, uncapped), and — last, after a hidden `Chart Data`
sheet — a `Data` sheet that is the `SECTION`-prefixed CSV cell for cell —
header `SECTION` + the 26 `EXPORT_HEADERS` — so a save-as-CSV from Excel still
re-imports through `POST /work-orders/import`. `distribution` and `all_rows`
are not in the JSON response.
```

- [ ] **Step 5: Run the full suite**

```bash
venv/Scripts/python -m pytest -q
```

Expected: all pass except the known environmental `test_cascade_deletes_with_user` if the dev DB holds cloud-session rows. Report the actual output.

- [ ] **Step 6: Commit**

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git && git add backend/app/routers/hub.py backend/tests/test_hub_router.py docs/endpoint-map.md && git commit -m "docs(hub-report): describe the redesigned workbook on the route and in the endpoint map"
```

(`docs/` mirrors to the Obsidian vault automatically — do not sync by hand.)

---

### Task 8: One-time visual check (manual, user-run)

**Files:** none committed. Output goes to the scratchpad.

The spec (§7) is explicit that chart *shape* is a one-time manual check because openpyxl cannot read charts back. The user validates manually; do not start the dev server.

- [ ] **Step 1: Generate two sample workbooks — the developer database and a synthetic showcase (P16)**

The dev copy has no archived rows and 91% of its live rows are `created`, so on its own it never shows a Closed slice, a Closed series on Activity, or a non-zero Dollars chart. The first file shows the real shape; the second shows the design working. `<scratchpad>` is this session's scratchpad directory.

```bash
cd /c/Users/mcclu/Desktop/inventory_app_git/backend && venv/Scripts/python - <<'EOF'
import time
from datetime import datetime, timezone

from app.database import SessionLocal
from app.domain import work_orders as wo
from app.services import work_order_report as r, work_order_report_xlsx as x
from tests.test_work_order_report_xlsx import _payload, _row

out = r"<scratchpad>"

# 1. The developer database, timed (E16 / P15).
db = SessionLocal()
started = time.perf_counter()
payload = r.daily_report(db, now=datetime.now(timezone.utc))
elapsed = time.perf_counter() - started
open(f"{out}/wo-report-dev.xlsx", "wb").write(x.report_xlsx(payload))
print(f"daily_report: {elapsed:.2f}s; {len(payload.all_rows)} rows;",
      [(c.label, c.total) for c in payload.distribution.communities])

# 2. The showcase: every slice, a two-community row, Commons over the
#    nine-card cap, Young Hall and Academics empty.
live = [
    _row(number="WO-01", community="Scholars", service_type="Plumbing"),
    _row(number="WO-02", community="Scholars", service_type="Plumbing", status=wo.STATUS_ASSIGNED),
    _row(number="WO-03", community="Scholars", service_type="HVAC", status=wo.STATUS_IN_PROGRESS,
         notes="Tenant home after 5.\nCall first.\nDog in unit."),
    _row(number="WO-04", community="Scholars", service_type="Electrical", status=wo.STATUS_ON_HOLD),
    _row(number="WO-05", community="Scholars", service_type="Plumbing", status=wo.STATUS_REVIEW),
    _row(number="WO-06", location="Scholars 3 / Commons annex", service_type="Doors",
         status=wo.STATUS_READY_TO_COMPLETE),
    _row(number="WO-07", community="Centennial", service_type="Windows"),
    _row(number="WO-08", community="Centennial", service_type="Windows", status=wo.STATUS_COMPLETED),
] + [
    _row(number=f"WO-{n}", community="Commons", service_type=f"Trade {n:02d}") for n in range(10, 21)
]
closed = [
    _row(number="WO-30", community="Scholars", service_type="Plumbing", status=wo.STATUS_COMPLETED,
         archived=True, labor_total="120.00", materials_total="35.50"),
    _row(number="WO-31", community="Centennial", service_type="HVAC", status=wo.STATUS_REVIEW,
         archived=True, labor_total="60.00"),
    _row(number="WO-32", location="Commons annex / Scholars 3", service_type="Doors",
         status=wo.STATUS_COMPLETED, archived=True, labor_total="40.00", materials_total="12.00"),
]
closing = [row for row in live if row.status in r.CLOSING_STATUSES]
showcase = _payload(
    live=live,
    closed_today=closed[:1],
    closed_week=closed,
    closing=closing,
    by_status={s: sum(1 for row in closing if row.status == s) for s in r.CLOSING_STATUSES},
    new_today=live[:2],
    new_week=live[:8],
)
open(f"{out}/wo-report-showcase.xlsx", "wb").write(x.report_xlsx(showcase))
print("showcase:", len(showcase.all_rows), "rows")
EOF
```

If `daily_report` takes more than about a second on the dev copy, say so in the hand-off: that is the E16 / P15 trigger for an `include_rows` switch on `daily_report`, to be decided then — not added now.

- [ ] **Step 2: Hand both paths to the user with this checklist**

Open `wo-report-dev.xlsx` in Excel and confirm:
1. Opens with no repair prompt; lands on `Report`; tab strip reads Report · Scholars · Centennial · Commons · Young Hall · Academics · Work Orders · Data (Chart Data hidden).
2. `Report`: five KPI tiles with a red rule; company pie is four slices, Accepted at 12 o'clock going clockwise gray → amber → violet → green, legend right, percent labels; Activity and Dollars charts red/gray, not the bucket palette; charts sit in G:M beside their blocks and do not overlap; the dollars footnote sits under the money block and "By community" starts at row 58.
3. A community sheet: pie in A6:D20 with its legend on the right, value block at F6:H10, nine (or fewer) cards on B/E/H at rows 24/37/50 that line up with **no legends** (E15), titles `Trade · n`; detail table at row 65; no gridlines.
4. `Work Orders`: header at row 5 frozen with A:C; Notes wrap and rows cap at ~4 lines; COMMUNITIES (F) is never blank; money shows `$` with no green triangles; filter arrows on the header.
5. `Data`: gridlines on, green triangles on money (expected — it is the CSV).
6. Print preview any sheet: landscape, one page wide.

Then open `wo-report-showcase.xlsx` and confirm:
7. Every pie shows all four colors; Commons shows eight cards plus `Other` and the `"Other" combines 4 further service types.` note; Young Hall and Academics are the empty-state line with no chart.
8. `Report` dollars: Scholars $207.50 (WO-30 plus WO-32 — the two-community row counted once, under its first community), Centennial $60.00, no `(no community)` row.
9. `Work Orders` row WO-06 reads `Scholars; Commons` in COMMUNITIES and `Ready to close` in BUCKET.

---

## Self-review

**Spec coverage** — E1 (Task 2 `all_rows`, Task 1 `distribution` over it); E2 (Task 1 `REPORT_BUCKETS` + import-time check + `bucket_of` test); E3 (Task 1/2, per P1 computed over rows); E4 (Task 2 `_live_rows` uncapped, Task 4 sheet); E5 (Task 4 column C, width 60, wrap, height cap); E6 (Task 4 `SHEET_NAMES`, per P5); E7 (Task 4 `_ChartData`, `visible_cells_only=False` in Task 3); E8 (Task 1 `grid_of`, Task 6 note); E9 (Task 5 company block, Task 6 F6:H10 block + detail table); E10 (Task 4 `_data_sheet` unchanged values, last, gray, gridlines); E11 (Task 5: pipeline chart gone, split in footnote; service-type chart gone); E12 (Task 3); E13 (no queries in the renderer — Tasks 4–6). §4.0 house style — Task 3 constants, Task 4–6 application, Task 4 test for tab colors/gridlines. §4.1 layout — Task 5. §4.2 — Task 6 including empty state. §4.3 — Task 4 (all 21 columns, sort, dedup, freeze D6, table). §4.4 — Task 4. §5 unchanged — no task touches the route URL, floor, `export_row`, `report_csv`, or the Graphs tab. §7 tests — all twelve bullets have a test (bucket_of; distribution fixture; sums/non-sums; Data pin retargeted; Work Orders C/dedup/count; sheet names/hidden/last; zip chart count + plotVisOnly; empty DB; `communities_of` / `primary_community` + dollars-once + COMMUNITIES column; zip legend count; the showcase render is Task 8 itself). §8 (resolved) — P12. E14 (Task 1 `communities_of` / `primary_community`, Task 4 COMMUNITIES column, Task 5 `_community_money` + `DOLLARS_FOOTNOTE`); E15 (Task 6 `legend=None` on the cards + the zip-level legend count); E16 (Task 8 times `daily_report`; P15).

**Placeholder scan** — no TBD/TODO; every code step carries its code; Task 8 is a manual step by design and says so.

**Type consistency** — `_pie(..., group=...)` takes anything with `.total`/`.counts` (used with `CommunityDistribution` and `ServiceTypeDistribution`); `theme.table_of` returns the last row (Tasks 5, 6 use it); `_ChartData.block` returns `(header_row, last_row)` and `theme.pie_of`/`column_chart_of` take `header_row`/`last_row` by those names; `reading_order` is public and used by the Task 4 fixture; `STATUS_LABELS` lives in `work_order_report` and is imported by the renderer; `BUCKET_LABELS.values()` order is bucket order because `REPORT_BUCKETS` is a tuple.
