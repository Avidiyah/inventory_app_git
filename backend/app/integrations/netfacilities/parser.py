"""Semantic parser for NetFacilities' server-rendered work-order preview.

The parser consumes bytes returned by the authenticated document request. It does
not execute JavaScript, follow links, load attachments, or retain the source HTML.
"""

from __future__ import annotations

from dataclasses import asdict, dataclass
from typing import Any

from bs4 import BeautifulSoup
from bs4.element import Tag

from .errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesUnexpectedDocument,
)
from .validation import validate_work_order_number


@dataclass(frozen=True, slots=True)
class ParsedWorkOrder:
    """Small Stage 1 projection; Stage 2 will introduce a Pydantic contract."""

    work_order_number: str
    description: str
    location: str
    location_parts: tuple[str, ...]
    status: str
    priority: str | None
    task_type: str | None
    work_order_type: str | None
    created_date: str | None
    scheduled_date: str | None
    overdue_date: str | None

    def to_dict(self) -> dict[str, Any]:
        """Return a JSON-safe projection without the source HTML."""

        result = asdict(self)
        result["location_parts"] = list(self.location_parts)
        return result


def parse_work_order_html(
    html: bytes | str,
    *,
    expected_work_order_number: str,
) -> ParsedWorkOrder:
    """Parse and validate the core read-only work-order projection.

    The requested and returned identifiers must match. Required field failures are
    fatal so a changed page can never be silently imported as partial data.
    """

    expected = validate_work_order_number(expected_work_order_number)
    soup = BeautifulSoup(html, "html.parser")

    if _looks_like_login(soup):
        raise NetFacilitiesAuthenticationRequired(
            "NetFacilities authentication is required; sign in again."
        )

    returned_number = _required_text(soup.select_one(".wo_Id h3"), "work-order number")
    if returned_number != expected:
        raise NetFacilitiesUnexpectedDocument(
            "NetFacilities returned a different work-order identifier."
        )

    status = _required_text(soup.select_one(".wo_statusdiv h3"), "status")
    task_section = _section(soup, "Task/Procedure")
    description = _description(task_section)
    location_parts = _section_lines(_section(soup, "Location"))
    if not location_parts:
        raise NetFacilitiesUnexpectedDocument(
            "NetFacilities work-order document is missing location data."
        )

    general = _general_fields(_section(soup, "General Information"))
    general_status = general.get("Status")
    if general_status and general_status != status:
        raise NetFacilitiesUnexpectedDocument(
            "NetFacilities returned conflicting work-order statuses."
        )

    priority_node = soup.select_one("#priority-level")
    priority = _optional_text(priority_node) or general.get("Priority Level")

    created_node = soup.select_one(".p-timepkr .date")
    created_date = _optional_text(created_node)

    return ParsedWorkOrder(
        work_order_number=returned_number,
        description=description,
        location=" / ".join(location_parts),
        location_parts=location_parts,
        status=status,
        priority=priority,
        task_type=_task_type(task_section),
        work_order_type=general.get("WO Type"),
        created_date=created_date,
        scheduled_date=general.get("Scheduled"),
        overdue_date=general.get("Overdue"),
    )


def _looks_like_login(soup: BeautifulSoup) -> bool:
    if soup.select_one("form#signin") is not None:
        return True
    password = soup.select_one('input[type="password"]')
    title = _optional_text(soup.title)
    return password is not None and bool(title and "login" in title.casefold())


def _section(soup: BeautifulSoup, heading_text: str) -> Tag:
    for heading in soup.find_all("h2"):
        if _clean(heading.get_text(" ", strip=True)) == heading_text:
            parent = heading.parent
            if isinstance(parent, Tag):
                return parent
    raise NetFacilitiesUnexpectedDocument(
        f'NetFacilities work-order document is missing the "{heading_text}" section.'
    )


def _section_lines(section: Tag) -> tuple[str, ...]:
    lines: list[str] = []
    for paragraph in section.find_all("p", recursive=False):
        value = _clean(paragraph.get_text(" ", strip=True))
        if value:
            lines.append(value)
    return tuple(lines)


def _description(section: Tag) -> str:
    code = section.select_one("code.code_task")
    if code is not None:
        value = _clean_multiline(code.get_text("\n", strip=True))
        if value:
            return _bounded(value, "description", 10_000)

    paragraphs = section.find_all("p", recursive=False)
    for paragraph in paragraphs[1:]:
        value = _clean_multiline(paragraph.get_text("\n", strip=True))
        label_node = paragraph.find("b")
        if label_node is not None:
            label = _clean_multiline(label_node.get_text("\n", strip=True))
            if value == label:
                value = ""
            elif label and value.startswith(f"{label}\n"):
                value = value[len(label) :].strip()
        if value:
            return _bounded(value, "description", 10_000)
    raise NetFacilitiesUnexpectedDocument(
        "NetFacilities work-order document is missing a description."
    )


def _task_type(section: Tag) -> str | None:
    paragraph = section.find("p", recursive=False)
    return _optional_text(paragraph)


def _general_fields(section: Tag) -> dict[str, str]:
    fields: dict[str, str] = {}
    for paragraph in section.find_all("p", recursive=False):
        label_node = paragraph.select_one(".p-gern")
        if label_node is None:
            continue
        label = _clean(label_node.get_text(" ", strip=True)).rstrip(":").strip()
        full_text = _clean(paragraph.get_text(" ", strip=True))
        label_with_colon = _clean(label_node.get_text(" ", strip=True))
        value = full_text
        if value.startswith(label_with_colon):
            value = value[len(label_with_colon) :].strip()
        if label and value:
            fields[label] = _bounded(value, label, 1_000)
    return fields


def _required_text(node: Tag | None, field: str) -> str:
    value = _optional_text(node)
    if not value:
        raise NetFacilitiesUnexpectedDocument(
            f"NetFacilities work-order document is missing {field}."
        )
    return value


def _optional_text(node: Tag | None) -> str | None:
    if node is None:
        return None
    value = _clean(node.get_text(" ", strip=True))
    return value or None


def _clean(value: str) -> str:
    return " ".join(value.split())


def _clean_multiline(value: str) -> str:
    lines = [_clean(line) for line in value.splitlines()]
    return "\n".join(line for line in lines if line)


def _bounded(value: str, field: str, limit: int) -> str:
    if len(value) > limit:
        raise NetFacilitiesUnexpectedDocument(
            f'NetFacilities field "{field}" exceeds the Stage 1 size limit.'
        )
    return value
