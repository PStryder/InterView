"""Snapshot test for InterView MCP tools/list contract."""

from __future__ import annotations

import json
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
    monkeypatch.setenv("INTERVIEW_API_KEY", "iv_test_snapshot")
    monkeypatch.setenv("INTERVIEW_ALLOW_INSECURE_DEV", "false")
    monkeypatch.setenv("INTERVIEW_RATE_LIMIT_ENABLED", "false")
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


def test_mcp_tools_snapshot_contract():
    request = {"jsonrpc": "2.0", "id": "snapshot", "method": "tools/list", "params": {}}

    with TestClient(app) as client:
        response = client.post("/mcp", json=request)

    assert response.status_code == 200
    payload = response.json()

    snapshot_path = Path(__file__).resolve().parents[1] / "contracts" / "mcp_tools.snapshot.json"
    expected = json.loads(snapshot_path.read_text(encoding="utf-8"))

    actual = {
        "service": "InterView",
        "snapshot_type": "tools/list",
        "tools": payload["result"]["tools"],
    }
    assert actual == expected
