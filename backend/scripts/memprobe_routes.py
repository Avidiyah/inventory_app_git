"""Route catalogue and pure planning/ranking for `memprobe.py sweep`.
Spec: docs/superpowers/specs/2026-10-13-memory-sweep-p2-design.md.
Never imports app.* at module level: the coverage test imports app.main itself."""

from __future__ import annotations

import csv
import re
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from typing import Optional

TOKEN_RE = re.compile(r"\{([a-z_0-9]+)(?::(\d+))?\}")
_BUILTIN_TOKENS = ("id", "seq", "now", "days_ago")


@dataclass(frozen=True)
class Entry:
    body: Optional[str] = None
    file: Optional[object] = None  # fixture path, or (filename, text template)
    cycle: Optional[list[str]] = None
    expect: Optional[int] = None
    exclude: Optional[str] = None
    path: Optional[str] = None
    token: Optional[dict[str, str]] = None
    as_user: str = "owner"


@dataclass(frozen=True)
class Step:
    route: str  # the enumerated key, so ranking lines up with app.routes
    method: str
    path: str  # what is actually requested, templates unfilled
    body: Optional[str]
    file: Optional[object]
    expect: Optional[int]
    as_user: str


@dataclass
class Plan:
    groups: list[list[Step]] = field(default_factory=list)
    skipped: list[tuple[str, str]] = field(default_factory=list)
    excluded: list[tuple[str, str]] = field(default_factory=list)


def fill(template: str, tokens: dict[str, str], seq: int, now: datetime) -> str:
    def sub(m: re.Match) -> str:
        name, arg = m.group(1), m.group(2)
        if name == "id":
            return m.group(0)  # resolved by the driver from the last response
        if name == "seq":
            return str(seq)
        if name == "now":
            return now.strftime("%Y-%m-%dT%H:%M:%SZ")
        if name == "days_ago":
            return (now - timedelta(days=int(arg))).strftime("%Y-%m-%d")
        return tokens[name]  # KeyError = unresolvable, caller decides

    return TOKEN_RE.sub(sub, template)


def enumerate_routes(app) -> tuple[list[tuple[str, str]], list[str]]:
    http, other = [], []
    for r in app.routes:
        methods = getattr(r, "methods", None)
        if methods:
            http += [(m, r.path) for m in sorted(methods - {"HEAD", "OPTIONS"})]
        elif type(r).__name__ == "WebSocketRoute":
            other.append(f"WS {r.path}")
    return http, other


def _resolvable(template: str, tokens: dict[str, str]) -> bool:
    return all(n in tokens or n in _BUILTIN_TOKENS for n, _ in TOKEN_RE.findall(template))


def _step(method: str, path: str, entry: Entry, tokens: dict[str, str]) -> Optional[Step]:
    merged = {**tokens, **(entry.token or {})}
    requested = entry.path or path
    templates = [requested, entry.body or ""] + ([entry.file[1]] if isinstance(entry.file, tuple) else [])
    if not all(_resolvable(t, merged) for t in templates):
        return None
    return Step(f"{method} {path}", method, requested, entry.body, entry.file, entry.expect, entry.as_user)


def plan(routes, catalogue: dict[str, Entry], tokens: dict[str, str], only: Optional[str]) -> Plan:
    out = Plan()
    owners: dict[str, str] = {}
    for key, e in catalogue.items():
        for member in e.cycle or []:
            if member in owners and owners[member] != key:
                raise ValueError(f"{member} is in two cycles: {owners[member]} and {key}")
            owners[member] = key
    for method, path in routes:
        key = f"{method} {path}"
        if only and only not in key:
            continue
        entry = catalogue.get(key)
        if entry is None and method != "GET":
            out.skipped.append((method, path))  # a mutation needs a body or a cycle decision
            continue
        entry = entry or Entry()  # a GET resolves its tokens from the seed
        if entry.exclude:
            out.excluded.append((method, path))
            continue
        owner = owners.get(key)
        if owner and owner != key:
            continue  # placed when its cycle's first member was
        steps = []
        for m in entry.cycle or [key]:
            m_method, m_path = m.split(" ", 1)
            s = _step(m_method, m_path, catalogue.get(m, Entry()), tokens)
            if s is None:
                out.skipped.append((m_method, m_path))
                steps = []
                break
            steps.append(s)
        if steps:
            out.groups.append(steps)
    return out
