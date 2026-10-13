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
import sys
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
