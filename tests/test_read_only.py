import pytest

from interview.sources import READ_ONLY_MCP_TOOLS, DataSourceError, _assert_read_only_tool


def test_read_only_tool_allowlist():
    for tool in (
        "receiptgate.search_receipts",
        "receiptgate.get_receipt",
        "asyncgate.health",
        "asyncgate.list_tasks",
        "depotgate.get_deliverable",
        "depotgate.list_staged_artifacts",
    ):
        assert tool in READ_ONLY_MCP_TOOLS
        _assert_read_only_tool(tool)

    with pytest.raises(DataSourceError):
        _assert_read_only_tool("receiptgate.submit_receipt")


class TestArtifactPointerCollection:
    """StatusSummary.artifact_pointers was declared and never populated.

    These cover the bounded pass that now fills it, including the degradation
    path: a source failure mid-pass must keep what was already gathered.
    """

    @staticmethod
    def _header(receipt_id: str, phase: str):
        from interview.models import ReceiptHeader

        return ReceiptHeader(
            receipt_id=receipt_id,
            phase=phase,
            task_id="t1",
            tenant_id="default",
            recipient_ai="agent:demo",
        )

    @staticmethod
    def _payload(pointer: str | None, task_type: str = "demo.task"):
        class _P:
            artifact_pointer = pointer
            outcome_text = "done"

        _P.task_type = task_type
        return _P()

    @pytest.mark.asyncio
    async def test_pointers_are_collected_from_complete_receipts(self):
        from interview.api import _inspect_complete_receipts

        class _Mirror:
            async def get_receipt(self, tenant_id, receipt_id):
                return TestArtifactPointerCollection._payload(f"depotgate://{receipt_id}")

        class _Sources:
            ledger_mirror = _Mirror()

        receipts = [self._header("r1", "complete"), self._header("r2", "accepted")]
        shipped, manifest, pointers = await _inspect_complete_receipts(
            receipts, "default", _Sources()
        )
        assert pointers == ["depotgate://r1"]
        assert shipped is False and manifest is None

    @pytest.mark.asyncio
    async def test_na_and_duplicate_pointers_are_skipped(self):
        from interview.api import _inspect_complete_receipts

        class _Mirror:
            async def get_receipt(self, tenant_id, receipt_id):
                pointer = "NA" if receipt_id == "r1" else "depotgate://same"
                return TestArtifactPointerCollection._payload(pointer)

        class _Sources:
            ledger_mirror = _Mirror()

        receipts = [self._header(f"r{i}", "complete") for i in (1, 2, 3)]
        _, _, pointers = await _inspect_complete_receipts(receipts, "default", _Sources())
        assert pointers == ["depotgate://same"]

    @pytest.mark.asyncio
    async def test_source_failure_keeps_what_was_gathered(self):
        """Losing everything because the second lookup failed is worse."""
        from interview.api import _inspect_complete_receipts
        from interview.sources import SourceUnavailableError

        class _Mirror:
            calls = 0

            async def get_receipt(self, tenant_id, receipt_id):
                _Mirror.calls += 1
                if _Mirror.calls > 1:
                    raise SourceUnavailableError("ledger down")
                return TestArtifactPointerCollection._payload("depotgate://first")

        class _Sources:
            ledger_mirror = _Mirror()

        receipts = [self._header(f"r{i}", "complete") for i in (1, 2, 3)]
        _, _, pointers = await _inspect_complete_receipts(receipts, "default", _Sources())
        assert pointers == ["depotgate://first"]

    @pytest.mark.asyncio
    async def test_no_complete_receipts_yields_nothing(self):
        from interview.api import _inspect_complete_receipts

        class _Sources:
            ledger_mirror = None

        shipped, manifest, pointers = await _inspect_complete_receipts(
            [self._header("r1", "accepted")], "default", _Sources()
        )
        assert (shipped, manifest, pointers) == (False, None, [])
