"""Drive one route against the inventory-local container N times and print
its memory cost from the container's own `event=request` lines.

    python scripts/memprobe.py GET /items --n 50
    python scripts/memprobe.py POST /items/search --body '{"q":"wid"}' --n 20

Spec: docs/superpowers/specs/2026-10-13-memory-probe-harness-design.md.
Correlation is by the echoed `X-Request-ID`, never by time, so other
traffic (the platform's /healthz polls, for one) cannot be mis-attributed.
"""

from __future__ import annotations

import os
import statistics
import sys
from collections import Counter
from dataclasses import dataclass
from typing import Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

_REQUEST_EVENTS = ("request", "request.error")
_INT_FIELDS = ("status", "ms", "rss_mb", "cg_mb", "cg_delta_mb", "rss_delta_mb")


@dataclass(frozen=True)
class Sample:
    req: str
    status: Optional[int]
    ms: Optional[int]
    rss_mb: Optional[int]
    cg_mb: Optional[int]
    cg_delta_mb: Optional[int]
    rss_delta_mb: Optional[int]


def _int_or_none(value: Optional[str]) -> Optional[int]:
    try:
        return int(value)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None  # absent, "-", or garbage all read the same


def parse_request_lines(text: str, wanted: set[str]) -> dict[str, Sample]:
    """logfmt lines -> Sample per wanted request id. Values are unquoted on
    these lines (the path is logged without its query string)."""
    out: dict[str, Sample] = {}
    for line in text.splitlines():
        fields = dict(tok.split("=", 1) for tok in line.split() if "=" in tok)
        req = fields.get("req")
        if req not in wanted or fields.get("event") not in _REQUEST_EVENTS:
            continue
        out[req] = Sample(req, *(_int_or_none(fields.get(k)) for k in _INT_FIELDS))
    return out


_DELTAS = ("cg_delta_mb", "rss_delta_mb")
_LEVELS = ("cg_mb", "rss_mb")


@dataclass(frozen=True)
class Sent:
    req: Optional[str]  # None when the response carried no X-Request-ID
    status: int


@dataclass
class Summary:
    sent: int
    statuses: dict[int, int]
    matched: int
    readings: int  # matched lines whose memory fields were present
    unmatched: list[str]
    first: dict[str, Optional[int]]
    rest: dict[str, dict[str, Optional[float]]]
    drift: dict[str, tuple[Optional[int], Optional[int]]]
    ms_p50: Optional[int]
    ms_max: Optional[int]


def _stats(values: list[int]) -> dict[str, Optional[float]]:
    if not values:
        return {"sum": 0, "max": None, "mean": None}
    return {"sum": sum(values), "max": max(values), "mean": statistics.fmean(values)}


def aggregate(sent: list[Sent], samples: dict[str, Sample]) -> Summary:
    """Order is the order sent: the first request pays warm-up costs and is
    reported apart from the steady-state rest."""
    ordered = [samples[s.req] for s in sent if s.req in samples]
    unmatched = [s.req or "<no X-Request-ID>" for s in sent if s.req not in samples]
    first, rest = (ordered[0] if ordered else None), ordered[1:]
    with_readings = [s for s in ordered if s.cg_mb is not None or s.rss_mb is not None]
    ms = [s.ms for s in ordered if s.ms is not None]
    return Summary(
        sent=len(sent),
        statuses=dict(sorted(Counter(s.status for s in sent).items())),
        matched=len(ordered),
        readings=len(with_readings),
        unmatched=unmatched,
        first={k: (getattr(first, k) if first else None) for k in _DELTAS},
        rest={k: _stats([v for s in rest if (v := getattr(s, k)) is not None]) for k in _DELTAS},
        drift={
            k: ((getattr(with_readings[0], k), getattr(with_readings[-1], k)) if with_readings else (None, None))
            for k in _LEVELS
        },
        ms_p50=int(statistics.median(ms)) if ms else None,
        ms_max=max(ms) if ms else None,
    )


def _fmt(value) -> str:
    if value is None:
        return "-"
    return f"{value:.2f}" if isinstance(value, float) else str(value)


def render(route: str, container: str, baseline: Optional[Sample], summary: Summary) -> str:
    base = (
        f"cg_mb={_fmt(baseline.cg_mb)}  rss_mb={_fmt(baseline.rss_mb)}        (idle, from /healthz)"
        if baseline else "-"
    )
    statuses = "  ".join(f"{code}x{n}" for code, n in summary.statuses.items()) or "-"
    rows = [
        f"route        {route}     n={summary.sent}   container={container}",
        f"baseline     {base}",
        f"statuses     {statuses}",
        f"matched      {summary.matched}/{summary.sent}   readings={summary.readings}",
        "",
        f"{'':16} {'first':>6} {'rest(sum)':>10} {'rest(max)':>10} {'rest(mean)':>11}",
    ]
    for k in _DELTAS:
        r = summary.rest[k]
        rows.append(f"{k:16} {_fmt(summary.first[k]):>6} {_fmt(r['sum']):>10} {_fmt(r['max']):>10} {_fmt(r['mean']):>11}")

    def _span(a, b):
        change = "-" if a is None or b is None else f"{b - a:+d}"
        return f"{_fmt(a)}->{_fmt(b)} ({change})"

    drift = "   ".join(f"{k} {_span(a, b)}" for k, (a, b) in summary.drift.items())
    rows += ["", f"drift        {drift}   over {summary.matched} requests",
             f"ms           p50={_fmt(summary.ms_p50)}  max={_fmt(summary.ms_max)}"]
    if summary.unmatched:
        rows.append(f"unmatched    {' '.join(summary.unmatched)}")
    return "\n".join(rows)
