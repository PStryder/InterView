import pytest

from interview.sources import READ_ONLY_MCP_TOOLS, _assert_read_only_tool, DataSourceError


def test_read_only_tool_allowlist():
    for tool in (
        "receiptgate.search_receipts",
        "receiptgate.get_receipt",
        "asyncgate.health",
        "asyncgate.list_tasks",
        "depotgate.get_deliverable",
        "list_staged_artifacts",
    ):
        assert tool in READ_ONLY_MCP_TOOLS
        _assert_read_only_tool(tool)

    with pytest.raises(DataSourceError):
        _assert_read_only_tool("receiptgate.submit_receipt")
