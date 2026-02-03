"""InterView API handlers (read-only MCP surfaces)."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from .config import get_settings, Settings
from .models import (
    Freshness,
    FullReceipt,
    GetReceiptRequest,
    GetReceiptResponse,
    HealthAsyncRequest,
    HealthAsyncResponse,
    InventoryArtifactsRequest,
    InventoryArtifactsResponse,
    QueueAsyncRequest,
    QueueAsyncResponse,
    ReceiptHeader,
    ResponseMetadata,
    SearchReceiptsRequest,
    SearchReceiptsResponse,
    Source,
    StatusReceiptsRequest,
    StatusReceiptsResponse,
    StatusSummary,
    TaskState,
)
from .sources import (
    DataSourceError,
    GlobalLedgerDisabledError,
    SourceManager,
    SourceUnavailableError,
)


class InterViewQueryError(Exception):
    """InterView query error with a code for MCP responses."""

    def __init__(self, message: str, code: str = "INTERVIEW_ERROR") -> None:
        super().__init__(message)
        self.code = code


def _now_utc() -> datetime:
    return datetime.utcnow()


def _clamp_limit(requested: int | None, settings: Settings) -> int:
    if not requested:
        return settings.default_limit
    return max(1, min(requested, settings.max_limit))


def _resolve_since(controls, settings: Settings) -> datetime | None:
    if controls is None:
        return None

    if controls.since:
        # Enforce max window even if caller requests older data
        max_window = timedelta(hours=settings.max_time_window_hours)
        cutoff = _now_utc() - max_window
        return max(controls.since, cutoff)

    window_hours = controls.time_window_hours or settings.default_time_window_hours
    window_hours = min(window_hours, settings.max_time_window_hours)
    return _now_utc() - timedelta(hours=window_hours)


def _metadata(source: Source, freshness_age_ms: int, *, truncated: bool, next_page_token: str | None = None) -> ResponseMetadata:
    cost_units = 1 + (1 if truncated else 0)
    return ResponseMetadata(
        source=source,
        freshness_age_ms=max(0, freshness_age_ms),
        truncated=truncated,
        next_page_token=next_page_token,
        cost_units=cost_units,
    )


def _coerce_receipt_header(payload: dict[str, Any], root_task_id: str | None = None) -> ReceiptHeader:
    if "root_task_id" not in payload and root_task_id:
        payload = {**payload, "root_task_id": root_task_id}
    return ReceiptHeader(**payload)


def _coerce_full_receipt(payload: dict[str, Any]) -> FullReceipt:
    if "root_task_id" not in payload:
        payload = {**payload, "root_task_id": payload.get("task_id")}
    return FullReceipt(**payload)


def _derive_state(
    receipts: list[ReceiptHeader],
    *,
    shipped: bool,
) -> TaskState:
    if shipped:
        return TaskState.SHIPPED

    has_complete = any(r.phase == "complete" for r in receipts)
    if has_complete:
        return TaskState.RESOLVED

    has_escalate = any(r.phase == "escalate" for r in receipts)
    if has_escalate:
        return TaskState.ESCALATED

    has_accepted = any(r.phase == "accepted" for r in receipts)
    if has_accepted:
        return TaskState.IN_PROGRESS

    return TaskState.UNKNOWN


def _latest_receipt(receipts: list[ReceiptHeader]) -> ReceiptHeader | None:
    if not receipts:
        return None
    return max(
        receipts,
        key=lambda r: r.created_at or r.stored_at or datetime.min,
    )


async def _check_shipment_state(
    receipts: list[ReceiptHeader],
    tenant_id: str,
    sources: SourceManager,
) -> tuple[bool, str | None]:
    """Best-effort shipment detection using full receipts (bounded)."""
    complete_ids = [r.receipt_id for r in receipts if r.phase == "complete"][:3]
    if not complete_ids:
        return False, None

    for receipt_id in complete_ids:
        try:
            payload = await sources.ledger_mirror.get_receipt(tenant_id, receipt_id)
        except (SourceUnavailableError, DataSourceError):
            return False, None
        if not payload:
            continue
        task_type = (payload.task_type or "").lower()
        outcome_text = (payload.outcome_text or "").lower()
        if "shipment" in task_type or "shipment" in outcome_text:
            return True, payload.artifact_pointer

    return False, None


async def status_receipts_interview(
    request: StatusReceiptsRequest,
    *,
    sources: SourceManager,
) -> StatusReceiptsResponse:
    settings = get_settings()
    root_task_id = request.root_task_id or request.task_id
    if not root_task_id:
        raise InterViewQueryError("root_task_id or task_id is required", code="VALIDATION_ERROR")

    cached_status, age_ms = await sources.projection_cache.get_status(
        tenant_id=request.tenant_id,
        root_task_id=root_task_id,
    )
    if cached_status:
        return StatusReceiptsResponse(
            status=cached_status,
            metadata=_metadata(Source.PROJECTION_CACHE, age_ms, truncated=False),
        )

    # Fallback to ledger mirror (bounded by default time window)
    since = _now_utc() - timedelta(hours=settings.default_time_window_hours)
    receipts = await sources.ledger_mirror.query_receipts(
        tenant_id=request.tenant_id,
        root_task_id=root_task_id,
        since=since,
        limit=settings.default_limit,
    )

    latest = _latest_receipt(receipts)
    shipped, manifest_pointer = await _check_shipment_state(receipts, request.tenant_id, sources)
    state = _derive_state(receipts, shipped=shipped)

    status = StatusSummary(
        tenant_id=request.tenant_id,
        root_task_id=root_task_id,
        state=state,
        latest_receipt_id=latest.receipt_id if latest else None,
        last_updated_at=latest.created_at or latest.stored_at if latest else None,
        open_obligations_count=1 if state in (TaskState.ACCEPTED, TaskState.IN_PROGRESS) else 0,
        shipment_status="complete" if shipped else None,
        shipment_manifest_pointer=manifest_pointer,
    )

    await sources.projection_cache.cache_status(status)

    return StatusReceiptsResponse(
        status=status,
        metadata=_metadata(Source.LEDGER_MIRROR, freshness_age_ms=0, truncated=False),
    )


async def search_receipts_interview(
    request: SearchReceiptsRequest,
    *,
    sources: SourceManager,
    settings: Settings,
) -> SearchReceiptsResponse:
    controls = request.controls
    limit = _clamp_limit(controls.limit if controls else None, settings)
    since = _resolve_since(controls, settings)
    freshness = controls.freshness if controls else Freshness.CACHE_OK

    receipts: list[ReceiptHeader] = []
    source = Source.PROJECTION_CACHE
    age_ms = 0

    if freshness == Freshness.FORCE_FRESH:
        receipts = await sources.ledger_mirror.query_receipts(
            tenant_id=request.tenant_id,
            root_task_id=request.root_task_id,
            phase=request.phase,
            recipient_ai=request.recipient_ai,
            since=since,
            limit=limit,
        )
        source = Source.LEDGER_MIRROR
    elif freshness == Freshness.PREFER_FRESH:
        try:
            receipts = await sources.ledger_mirror.query_receipts(
                tenant_id=request.tenant_id,
                root_task_id=request.root_task_id,
                phase=request.phase,
                recipient_ai=request.recipient_ai,
                since=since,
                limit=limit,
            )
            source = Source.LEDGER_MIRROR
        except (SourceUnavailableError, DataSourceError):
            receipts, age_ms = await sources.projection_cache.search_receipts(
                tenant_id=request.tenant_id,
                root_task_id=request.root_task_id,
                phase=request.phase,
                recipient_ai=request.recipient_ai,
                since=since,
                limit=limit,
            )
            source = Source.PROJECTION_CACHE
    else:
        receipts, age_ms = await sources.projection_cache.search_receipts(
            tenant_id=request.tenant_id,
            root_task_id=request.root_task_id,
            phase=request.phase,
            recipient_ai=request.recipient_ai,
            since=since,
            limit=limit,
        )
        source = Source.PROJECTION_CACHE
        if not receipts:
            receipts = await sources.ledger_mirror.query_receipts(
                tenant_id=request.tenant_id,
                root_task_id=request.root_task_id,
                phase=request.phase,
                recipient_ai=request.recipient_ai,
                since=since,
                limit=limit,
            )
            source = Source.LEDGER_MIRROR
            age_ms = 0

    headers = [
        _coerce_receipt_header(r.model_dump() if isinstance(r, ReceiptHeader) else r, request.root_task_id)
        for r in receipts
    ]
    truncated = len(headers) >= limit

    return SearchReceiptsResponse(
        receipts=headers,
        metadata=_metadata(source, age_ms, truncated=truncated),
    )


async def get_receipt_interview(
    request: GetReceiptRequest,
    *,
    sources: SourceManager,
) -> GetReceiptResponse:
    receipt, age_ms = await sources.projection_cache.get_receipt(
        tenant_id=request.tenant_id,
        receipt_id=request.receipt_id,
    )
    if receipt:
        return GetReceiptResponse(
            receipt=receipt,
            found=True,
            metadata=_metadata(Source.PROJECTION_CACHE, age_ms, truncated=False),
        )

    payload = await sources.ledger_mirror.get_receipt(
        tenant_id=request.tenant_id,
        receipt_id=request.receipt_id,
    )
    if not payload:
        return GetReceiptResponse(
            receipt=None,
            found=False,
            metadata=_metadata(Source.LEDGER_MIRROR, freshness_age_ms=0, truncated=False),
        )

    full = payload if isinstance(payload, FullReceipt) else _coerce_full_receipt(payload.model_dump() if hasattr(payload, "model_dump") else payload)
    await sources.projection_cache.cache_receipt(full)

    return GetReceiptResponse(
        receipt=full,
        found=True,
        metadata=_metadata(Source.LEDGER_MIRROR, freshness_age_ms=0, truncated=False),
    )


async def health_async_interview(
    request: HealthAsyncRequest,
    *,
    sources: SourceManager,
    settings: Settings,
) -> HealthAsyncResponse:
    try:
        data, age_ms = await sources.component_poller.poll_asyncgate_health(
            tenant_id=request.tenant_id,
            verbose=request.verbose,
        )
        return HealthAsyncResponse(
            component_id=data.get("instance_id", "asyncgate"),
            reachable=True,
            version=data.get("version"),
            uptime_seconds=data.get("uptime_seconds"),
            error_budget_status=data.get("error_budget_status"),
            metrics_snapshot=None,
            metadata=_metadata(Source.COMPONENT_POLL, age_ms, truncated=False),
        )
    except (SourceUnavailableError, DataSourceError) as exc:
        return HealthAsyncResponse(
            component_id="asyncgate",
            reachable=False,
            version=None,
            uptime_seconds=None,
            error_budget_status=str(exc),
            metrics_snapshot=None,
            metadata=_metadata(Source.COMPONENT_POLL, freshness_age_ms=0, truncated=False),
        )


async def queue_async_interview(
    request: QueueAsyncRequest,
    *,
    sources: SourceManager,
    settings: Settings,
) -> QueueAsyncResponse:
    limit = _clamp_limit(request.limit, settings)
    try:
        data, age_ms = await sources.component_poller.poll_asyncgate_queue(
            tenant_id=request.tenant_id,
            queue_id=request.queue_id,
            limit=limit,
            include_examples=request.include_examples,
        )
        return QueueAsyncResponse(
            queue_depth=data.get("queue_depth", 0),
            oldest_item_age_ms=data.get("oldest_item_age_ms", 0),
            active_leases_count=data.get("active_leases_count", 0),
            items=data.get("items", []),
            metadata=_metadata(Source.COMPONENT_POLL, age_ms, truncated=len(data.get("items", [])) >= limit),
        )
    except (SourceUnavailableError, DataSourceError) as exc:
        return QueueAsyncResponse(
            queue_depth=0,
            oldest_item_age_ms=0,
            active_leases_count=0,
            items=[],
            metadata=_metadata(Source.COMPONENT_POLL, freshness_age_ms=0, truncated=False),
        )


async def inventory_artifacts_depot_interview(
    request: InventoryArtifactsRequest,
    *,
    sources: SourceManager,
    settings: Settings,
) -> InventoryArtifactsResponse:
    controls = request.controls
    limit = _clamp_limit(controls.limit if controls else None, settings)

    pointers, manifest_pointer, counts = await sources.storage_metadata.list_artifacts(
        tenant_id=request.tenant_id,
        root_task_id=request.root_task_id,
        deliverable_id=request.deliverable_id,
        limit=limit,
    )

    truncated = len(pointers) >= limit
    return InventoryArtifactsResponse(
        artifact_pointers=pointers,
        shipment_manifest_pointer=manifest_pointer,
        staged_counts_by_role=counts,
        metadata=_metadata(Source.STORAGE_METADATA, freshness_age_ms=0, truncated=truncated),
    )


async def global_ledger_query(
    *,
    tenant_id: str | None,
    root_task_id: str | None,
    sources: SourceManager,
    settings: Settings,
) -> dict[str, Any]:
    if not tenant_id or not root_task_id:
        raise InterViewQueryError("tenant_id and root_task_id are required", code="VALIDATION_ERROR")

    try:
        receipts = await sources.global_ledger.query_receipts(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
        )
    except GlobalLedgerDisabledError as exc:
        raise InterViewQueryError(str(exc), code="GLOBAL_LEDGER_DISABLED") from exc
    except SourceUnavailableError as exc:
        raise InterViewQueryError(str(exc), code="GLOBAL_LEDGER_UNAVAILABLE") from exc

    return {
        "receipts": receipts,
        "metadata": _metadata(Source.GLOBAL_LEDGER, freshness_age_ms=0, truncated=False).model_dump(),
    }
