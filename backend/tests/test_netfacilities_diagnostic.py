"""Tests for the secret-safe single-request Render diagnostic."""

import argparse
import asyncio
import json
from types import SimpleNamespace

import pytest

from app.integrations.netfacilities.errors import NetFacilitiesUnavailable
from app.integrations.netfacilities.parser import PriorityMarkupDiagnostics
from scripts import netfacilities_diagnostic as diagnostic


class FakeClient:
    def __init__(self, *, failure=None):
        self.failure = failure
        self.calls = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, traceback):
        return None

    async def get_work_order_with_diagnostics(self, work_order_number):
        self.calls.append(work_order_number)
        if self.failure is not None:
            raise self.failure
        return (
            SimpleNamespace(
                work_order_number=work_order_number,
                description="source description must not be printed",
                priority="source priority must not be printed",
            ),
            PriorityMarkupDiagnostics(
                expected_id_count=1,
                expected_id_has_text=True,
                exact_label_count=1,
                priority_named_element_count=1,
                priority_named_element_with_text_count=1,
                priority_token_in_script_count=0,
                priority_token_in_style_count=0,
                priority_token_in_comment_count=0,
                priority_token_in_body_text_count=1,
            ),
        )


def _config():
    return SimpleNamespace(
        enabled=True,
        has_saved_authentication=True,
        interactive_authentication_available=False,
    )


def test_diagnose_reports_only_safe_shapes(monkeypatch):
    client = FakeClient()
    monkeypatch.setattr(diagnostic, "load_netfacilities_config", _config)
    monkeypatch.setattr(
        diagnostic,
        "create_netfacilities_client",
        lambda *args, **kwargs: client,
    )

    result = asyncio.run(diagnostic._diagnose("12345678"))
    rendered = json.dumps(result)

    assert client.calls == ["12345678"]
    assert result["transport"] == "isolated_browser_document"
    assert result["document"] == {
        "work_order_number_matched": True,
        "description_populated": True,
        "priority_populated": True,
    }
    assert result["priority_markup"]["expected_id_count"] == 1
    assert "12345678" not in rendered
    assert "source description" not in rendered
    assert "source priority" not in rendered


def test_main_redacts_expected_error_messages(monkeypatch, capsys):
    async def fail(_work_order_number):
        raise NetFacilitiesUnavailable("secret source value and protected path")

    monkeypatch.setattr(diagnostic, "_diagnose", fail)

    exit_code = diagnostic.main(["12345678"])
    captured = capsys.readouterr()

    assert exit_code == 1
    assert captured.out == ""
    assert json.loads(captured.err) == {
        "request_succeeded": False,
        "authentication_required": False,
        "error_type": "NetFacilitiesUnavailable",
    }
    assert "secret source value" not in captured.err
    assert "12345678" not in captured.err


def test_rejects_an_unsafe_work_order_number_before_io():
    with pytest.raises(argparse.ArgumentTypeError, match="valid work-order number"):
        diagnostic._work_order_number("not-a-number")
