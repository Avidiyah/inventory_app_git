"""Run one secret-safe, read-only NetFacilities diagnostic on Render.

From ``backend/`` (Render's Docker image uses ``/app``):

    python -m scripts.netfacilities_diagnostic WORK_ORDER_NUMBER

The command uses the production request path exactly once. Its JSON contains only
booleans, counts, transport classification, and exception class names. It never
prints the work-order number, field values, HTML, URLs, paths, headers, cookies, or
saved browser state.

When rendering is enabled the single navigation yields two views of the same
document, and ``priority_markup`` (the parsed DOM) can be compared against
``raw_priority_markup`` (the wire response) to locate the failing boundary.
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from typing import Any

from app.integrations.netfacilities.config import load_netfacilities_config
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
)
from app.integrations.netfacilities.factory import create_netfacilities_client
from app.integrations.netfacilities.validation import validate_work_order_number


def _work_order_number(value: str) -> str:
    try:
        return validate_work_order_number(value)
    except NetFacilitiesError as exc:
        raise argparse.ArgumentTypeError("Enter one valid work-order number.") from exc


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description=(
            "Inspect one NetFacilities Priority response without printing source data."
        )
    )
    parser.add_argument("work_order_number", type=_work_order_number)
    return parser


async def _diagnose(work_order_number: str) -> dict[str, Any]:
    config = load_netfacilities_config()
    client = create_netfacilities_client(
        config,
        headless=True,
        use_saved_state=True,
    )
    async with client:
        (
            work_order,
            priority_markup,
            retrieval,
            raw_priority_markup,
        ) = await client.get_work_order_with_diagnostics(work_order_number)

    result: dict[str, Any] = {
        "request_succeeded": True,
        "transport": (
            "rendered_browser_document"
            if retrieval.rendered
            else "isolated_browser_document"
        ),
        "configuration": {
            "enabled": config.enabled,
            "saved_authentication_found": config.has_saved_authentication,
            "render_document": config.render_document,
        },
        "render": {
            "priority_selector_appeared": retrieval.priority_selector_appeared,
            "subresources_allowed": retrieval.subresources_allowed,
            "subresources_blocked": retrieval.subresources_blocked,
            "console_errors": retrieval.console_errors,
            "raw_byte_count": retrieval.raw_byte_count,
            "rendered_byte_count": retrieval.rendered_byte_count,
            "rendered_grew": (
                retrieval.rendered_byte_count is not None
                and retrieval.rendered_byte_count > retrieval.raw_byte_count
            ),
        },
        "document": {
            "work_order_number_matched": (
                work_order.work_order_number == work_order_number
            ),
            "description_populated": bool(work_order.description),
            "priority_populated": bool(work_order.priority),
        },
        "priority_markup": priority_markup.to_dict(),
    }
    if raw_priority_markup is not None:
        # Same navigation, before JavaScript ran: this is what every earlier
        # transport attempt was actually parsing.
        result["raw_priority_markup"] = raw_priority_markup.to_dict()
    return result


def _safe_failure(exc: BaseException) -> dict[str, object]:
    return {
        "request_succeeded": False,
        "authentication_required": isinstance(
            exc,
            NetFacilitiesAuthenticationRequired,
        ),
        "error_type": type(exc).__name__,
    }


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    try:
        result = asyncio.run(_diagnose(args.work_order_number))
    except NetFacilitiesAuthenticationRequired as exc:
        print(json.dumps(_safe_failure(exc), indent=2), file=sys.stderr)
        return 3
    except NetFacilitiesError as exc:
        print(json.dumps(_safe_failure(exc), indent=2), file=sys.stderr)
        return 1
    except Exception as exc:  # Defensive: never let source-bearing errors reach Render logs.
        print(json.dumps(_safe_failure(exc), indent=2), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print(
            json.dumps(
                {
                    "request_succeeded": False,
                    "error_type": "KeyboardInterrupt",
                },
                indent=2,
            ),
            file=sys.stderr,
        )
        return 130

    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
