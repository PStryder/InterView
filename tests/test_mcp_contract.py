"""MCP contract tests for InterView."""

import sys
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

# Allow running tests directly from repo without editable install.
sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from interview.config import get_settings
from interview.mcp import app


@pytest.fixture(autouse=True)
def _test_env(monkeypatch: pytest.MonkeyPatch):
    """Set deterministic auth/rate-limit config for MCP contract tests."""
    monkeypatch.setenv("INTERVIEW_API_KEY", "iv_test_contract_key")
    monkeypatch.setenv("INTERVIEW_ALLOW_INSECURE_DEV", "false")
    monkeypatch.setenv("INTERVIEW_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_tools_list_available_without_auth():
    request = {"jsonrpc": "2.0", "id": "list-1", "method": "tools/list", "params": {}}

    with TestClient(app) as client:
        response = client.post("/mcp", json=request)

    assert response.status_code == 200
    payload = response.json()
    tools = payload["result"]["tools"]
    tool_names = {tool["name"] for tool in tools}
    assert "interview.health" in tool_names
    assert "search.receipts.interview" in tool_names


def test_unknown_jsonrpc_method_returns_method_not_found():
    request = {"jsonrpc": "2.0", "id": "bad-method", "method": "ping", "params": {}}

    with TestClient(app) as client:
        response = client.post("/mcp", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["error"]["code"] == -32601
    assert "Method not found" in payload["error"]["message"]


def test_tools_call_requires_auth():
    request = {
        "jsonrpc": "2.0",
        "id": "auth-missing",
        "method": "tools/call",
        "params": {"name": "interview.health", "arguments": {}},
    }

    with TestClient(app) as client:
        response = client.post("/mcp", json=request)

    assert response.status_code == 200
    payload = response.json()
    assert payload["id"] == "auth-missing"
    assert "error" in payload
    assert payload["error"]["code"] == "AUTH_FAILED"


def test_tools_call_health_with_bearer_auth():
    request = {
        "jsonrpc": "2.0",
        "id": "health-1",
        "method": "tools/call",
        "params": {"name": "interview.health", "arguments": {}},
    }
    headers = {"Authorization": "Bearer iv_test_contract_key"}

    with TestClient(app) as client:
        response = client.post("/mcp", json=request, headers=headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["result"]["status"] == "healthy"
    assert payload["result"]["service"] == "InterView"
