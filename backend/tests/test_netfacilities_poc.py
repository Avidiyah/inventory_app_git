"""Safety tests for the local NetFacilities proof-of-concept CLI."""

from pathlib import Path

import pytest

from app.integrations.netfacilities.errors import NetFacilitiesUnsafeProfilePath
from scripts import netfacilities_poc


def test_profile_must_be_outside_repository():
    with pytest.raises(NetFacilitiesUnsafeProfilePath, match="outside"):
        netfacilities_poc._profile_dir(
            str(netfacilities_poc.REPOSITORY_ROOT / "netfacilities-profile")
        )


def test_external_profile_path_is_accepted():
    candidate = (
        netfacilities_poc.REPOSITORY_ROOT.parent
        / "inventory-app-test-only-netfacilities-profile"
    )

    assert netfacilities_poc._profile_dir(str(candidate)) == candidate.resolve()


def test_relative_profile_path_is_rejected():
    with pytest.raises(NetFacilitiesUnsafeProfilePath, match="absolute"):
        netfacilities_poc._profile_dir("relative-netfacilities-profile")


def test_bundled_chromium_choice_omits_channel():
    assert netfacilities_poc._browser_channel("bundled-chromium") is None
    assert netfacilities_poc._browser_channel("chrome") == "chrome"


def test_cli_requires_an_explicit_profile_directory():
    parser = netfacilities_poc._parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(["lookup", "12345678"])

    assert exc.value.code == 2


def test_cli_rejects_work_order_number_before_browser_startup():
    parser = netfacilities_poc._parser()

    with pytest.raises(SystemExit) as exc:
        parser.parse_args(
            [
                "lookup",
                "not-a-number",
                "--profile-dir",
                str(
                    netfacilities_poc.REPOSITORY_ROOT.parent
                    / "inventory-app-test-only-netfacilities-profile"
                ),
            ]
        )

    assert exc.value.code == 2


def test_lookup_accepts_same_process_reauthentication_fallback():
    parser = netfacilities_poc._parser()
    profile = (
        netfacilities_poc.REPOSITORY_ROOT.parent
        / "inventory-app-test-only-netfacilities-profile"
    )

    args = parser.parse_args(
        [
            "lookup",
            "12345678",
            "--profile-dir",
            str(profile),
            "--reauthenticate",
        ]
    )

    assert args.reauthenticate is True
