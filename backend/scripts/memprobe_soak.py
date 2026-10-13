"""Phase 3 of the endpoint memory suite: a jump finder over any log text and
a mixed concurrent soak against the inventory-local container.

    python scripts/memprobe.py jumps render-export.log --step 8 --window 30
    python scripts/memprobe.py jumps --container inventory-local
    python scripts/memprobe.py soak --minutes 120 --workers 3 --out soak.csv

Spec: docs/superpowers/specs/2026-10-13-memory-soak-p3-design.md.
"""

from __future__ import annotations

import csv
import random
import re
import sys
import threading
import time
from collections import Counter
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Callable, Optional

from scripts import memprobe as mp

REQUEST_EVENTS = ("request", "request.error")

# key=value where the value is either a double-quoted string with backslash
# escapes (app.logging_config._fmt_value) or a bare run of non-space chars.
# Anything on the line that is not key=value (a Render or docker prefix) is
# simply never matched.
_TOKEN = re.compile(r'([A-Za-z_][\w.]*)=("(?:[^"\\]|\\.)*"|[^\s"]*)')
_UNESCAPE = {"\\\\": "\\", '\\"': '"', "\\n": "\n", "\\r": "\r", "\\t": "\t"}


@dataclass(frozen=True)
class Line:
    ts: datetime
    event: str
    fields: dict[str, str]


def _unquote(value: str) -> str:
    if len(value) >= 2 and value[0] == value[-1] == '"':
        return re.sub(r"\\.", lambda m: _UNESCAPE.get(m.group(0), m.group(0)[1]), value[1:-1])
    return value


def parse_lines(text: str) -> list[Line]:
    """Every logfmt line carrying `ts=` and `event=`, chronological. Tolerates
    a prefix before the first key=value (Render export, docker --timestamps)."""
    out = []
    for raw in text.splitlines():
        fields = {k: _unquote(v) for k, v in _TOKEN.findall(raw)}
        ts, event = fields.get("ts"), fields.get("event")
        if not ts or not event:
            continue
        try:
            when = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            continue
        out.append(Line(when, event, fields))
    out.sort(key=lambda l: l.ts)  # stable: docker interleaves stdout/stderr
    return out


def route_of(line: Line) -> str:
    if line.event in REQUEST_EVENTS:
        return f"{line.fields.get('method', '?')} {line.fields.get('path', '?')}"
    return line.event
