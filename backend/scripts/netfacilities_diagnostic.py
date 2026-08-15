"""Run one secret-safe, read-only NetFacilities diagnostic on Render.

From ``backend/`` (Render's Docker image uses ``/app``):

    python -m scripts.netfacilities_diagnostic WORK_ORDER_NUMBER

The command uses the production request path exactly once. Its JSON contains only
booleans, counts, transport classification, and exception class names. It never
prints the work-order number, field values, HTML, URLs, paths, headers, cookies, or
saved browser state.
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
        work_order, priority_markup = await client.get_work_order_with_diagnostics(
            work_order_number
        )

    return {
        "request_succeeded": True,
        "transport": (
            "browser_context"
            if config.interactive_authentication_available
            else "request_only"
        ),
        "configuration": {
            "enabled": config.enabled,
            "saved_authentication_found": config.has_saved_authentication,
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
