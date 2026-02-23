"""Telemetry counter tests for InterView MCP flow."""

from __future__ import annotations

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Allow running tests directly from repo without editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interview.config import get_settings
from interview.mcp import app
from interview.telemetry import telemetry


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("INTERVIEW_API_KEY", "iv_test_telemetry")
    monkeypatch.setenv("INTERVIEW_ALLOW_INSECURE_DEV", "false")
    monkeypatch.setenv("INTERVIEW_RATE_LIMIT_ENABLED", "false")
    telemetry.reset()
    get_settings.cache_clear()
    yield
    telemetry.reset()
    get_settings.cache_clear()


def test_telemetry_records_jsonrpc_method_errors():
    request = {"jsonrpc": "2.0", "id": "bad-method", "method": "ping", "params": {}}

    with TestClient(app) as client:
        response = client.post("/mcp", json=request)

    assert response.status_code == 200
    snapshot = telemetry.snapshot()
    assert snapshot["request_total"] == 1
    assert snapshot["request_method_counts"]["ping"] == 1
    assert snapshot["tools_call_error_code_counts"]["-32601"] == 1


def test_telemetry_records_auth_failures():
    request = {
        "jsonrpc": "2.0",
        "id": "auth-fail",
        "method": "tools/call",
        "params": {"name": "interview.health", "arguments": {}},
    }

    with TestClient(app) as client:
        response = client.post("/mcp", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == "AUTH_FAILED"

    snapshot = telemetry.snapshot()
    assert snapshot["request_method_counts"]["tools/call"] == 1
    assert snapshot["tools_call_error_code_counts"]["AUTH_FAILED"] == 1
