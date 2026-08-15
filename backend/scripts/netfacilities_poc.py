"""Local, read-only NetFacilities Stage 1 proof of concept.

Run from ``backend/`` with a profile directory outside the repository:

    python -m scripts.netfacilities_poc auth --profile-dir C:\\secure\\nf-profile
    python -m scripts.netfacilities_poc lookup 12345678 \
        --profile-dir C:\\secure\\nf-profile

The profile contains bearer-equivalent authentication state. Never commit, share,
log, or place it in a synced folder. The CLI performs no database writes and does
not call any work-order mutation or secondary endpoint.
"""

from __future__ import annotations

import argparse
import asyncio
import json
from pathlib import Path
import sys

from app.integrations.netfacilities.client import NetFacilitiesClient
from app.integrations.netfacilities.errors import (
    NetFacilitiesAuthenticationRequired,
    NetFacilitiesError,
    NetFacilitiesUnsafeProfilePath,
)
from app.integrations.netfacilities.validation import validate_work_order_number


REPOSITORY_ROOT = Path(__file__).resolve().parents[2]


def _profile_dir(value: str) -> Path:
    expanded = Path(value).expanduser()
    if not expanded.is_absolute():
        raise NetFacilitiesUnsafeProfilePath(
            "NetFacilities profile directory must be an absolute path."
        )
    path = expanded.resolve(strict=False)
    try:
        path.relative_to(REPOSITORY_ROOT)
    except ValueError:
        pass
    else:
        raise NetFacilitiesUnsafeProfilePath(
            "NetFacilities profile directory must be outside the repository."
        )
    if path.exists() and not path.is_dir():
        raise NetFacilitiesUnsafeProfilePath(
            "NetFacilities profile path exists but is not a directory."
        )
    return path


def _browser_channel(value: str) -> str | None:
    return None if value == "bundled-chromium" else value


def _work_order_number(value: str) -> str:
    try:
        return validate_work_order_number(value)
    except NetFacilitiesError as exc:
        raise argparse.ArgumentTypeError(str(exc)) from exc


def _add_browser_arguments(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--profile-dir",
        required=True,
        type=_profile_dir,
        help="Absolute dedicated profile path outside this repository.",
    )
    parser.add_argument(
        "--browser-channel",
        choices=("chrome", "msedge", "bundled-chromium"),
        default="chrome",
        help="Installed browser channel; defaults to local Chrome.",
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Read-only NetFacilities work-order Stage 1 proof of concept."
    )
    commands = parser.add_subparsers(dest="command", required=True)

    auth = commands.add_parser(
        "auth",
        help="Open the dedicated browser for manual NetFacilities authentication.",
    )
    _add_browser_arguments(auth)

    lookup = commands.add_parser(
        "lookup",
        help="Retrieve and parse one work order without saving it.",
    )
    lookup.add_argument("work_order_number", type=_work_order_number)
    lookup.add_argument(
        "--headed",
        action="store_true",
        help="Show the dedicated browser while running the lookup.",
    )
    lookup.add_argument(
        "--reauthenticate",
        action="store_true",
        help="Log in manually and perform the lookup before that browser closes.",
    )
    _add_browser_arguments(lookup)
    return parser


async def _run(args: argparse.Namespace) -> None:
    args.profile_dir.mkdir(parents=True, exist_ok=True)
    channel = _browser_channel(args.browser_channel)
    reauthenticate = args.command == "lookup" and args.reauthenticate
    headless = args.command != "auth" and not args.headed and not reauthenticate

    async with NetFacilitiesClient(
        profile_dir=args.profile_dir,
        headless=headless,
        browser_channel=channel,
        use_saved_state=args.command == "lookup" and not reauthenticate,
    ) as client:
        if args.command == "auth":
            await client.authenticate_interactively()
            await client.persist_authentication_state()
            print("Dedicated NetFacilities authentication state saved.")
            print(
                "Return to Work Orders and choose the CSV already downloaded on "
                "this computer. The app will then seek Task/Symptom and Priority."
            )
            return

        if reauthenticate:
            await client.authenticate_interactively()
            await client.persist_authentication_state()

        work_order = await client.get_work_order(args.work_order_number)
        print(
            json.dumps(
                {"source": "netfacilities", **work_order.to_dict()},
                indent=2,
                ensure_ascii=False,
            )
        )


def main(argv: list[str] | None = None) -> int:
    try:
        args = _parser().parse_args(argv)
        asyncio.run(_run(args))
    except NetFacilitiesAuthenticationRequired as exc:
        print(str(exc), file=sys.stderr)
        return 3
    except NetFacilitiesError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except KeyboardInterrupt:
        print("Cancelled; no work order was saved.", file=sys.stderr)
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
