"""InterView API endpoints.

Based on SPEC-IV-0000 (v0) section 7.
"""

from datetime import datetime, timedelta
from fastapi import APIRouter, Depends, HTTPException, Query, Request
from typing import Optional

from .config import get_settings, Settings
from .models import (
    Source,
    Freshness,
    TaskState,
    ResponseMetadata,
    RequestControls,
    HealthResponse,
    # 7.1 status.receipts.interview()
    StatusSummary,
    StatusReceiptsRequest,
    StatusReceiptsResponse,
    # 7.2 search.receipts.interview()
    ReceiptHeader,
    SearchReceiptsRequest,
    SearchReceiptsResponse,
    # 7.3 get.receipt.interview()
    FullReceipt,
    GetReceiptRequest,
    GetReceiptResponse,
    # 7.4 health.async.interview()
    HealthAsyncRequest,
    HealthAsyncResponse,
    MetricsSnapshot,
    # 7.5 queue.async.interview()
    QueueAsyncRequest,
    QueueAsyncResponse,
    QueueItemHeader,
    # 7.6 inventory.artifacts.depot.interview()
    InventoryArtifactsRequest,
    InventoryArtifactsResponse,
    ArtifactPointer,
    StagedCountsByRole,
    # Errors
    InterViewError,
    GlobalLedgerError,
)
from .sources import (
    SourceManager,
    DataSourceError,
    SourceUnavailableError,
    GlobalLedgerDisabledError,
)
from .auth import verify_api_key
from .middleware import get_rate_limiter


# Rate limiting dependency
async def rate_limit_dependency(request: Request) -> None:
    """Rate limiting dependency."""
    settings = get_settings()
    limiter = get_rate_limiter(
        calls_per_minute=settings.rate_limit_requests_per_minute,
        enabled=settings.rate_limit_enabled
    )
    await limiter.check_request(request)


router = APIRouter(dependencies=[Depends(verify_api_key), Depends(rate_limit_dependency)])

# Global source manager (initialized on startup)
_source_manager: SourceManager | None = None


def get_source_manager() -> SourceManager:
    """Get the source manager instance."""
    global _source_manager
    if _source_manager is None:
        _source_manager = SourceManager()
    return _source_manager


async def shutdown_sources() -> None:
    """Shutdown source manager on app shutdown."""
    global _source_manager
    if _source_manager:
        await _source_manager.close()
        _source_manager = None


# =============================================================================
# Health endpoint
# =============================================================================


@router.get("/health", response_model=HealthResponse, tags=["health"])
async def health_check():
    """Health check endpoint."""
    settings = get_settings()
    return HealthResponse(
        status="healthy",
        service="InterView",
        version=settings.interview_version,
        instance_id=settings.instance_id
    )


@router.get("/", tags=["root"])
async def root():
    """Root endpoint with service info."""
    settings = get_settings()
    return {
        "service": "InterView",
        "version": settings.interview_version,
        "doctrine": "InterView is observational only. A window, not a gate.",
        "surfaces": [
            "status.receipts.interview",
            "search.receipts.interview",
            "get.receipt.interview",
            "health.async.interview",
            "queue.async.interview",
            "inventory.artifacts.depot.interview",
        ],
    }


# =============================================================================
# 7.1 status.receipts.interview()
# =============================================================================


@router.post(
    "/v1/status/receipts",
    response_model=StatusReceiptsResponse,
    tags=["status"],
    summary="Get derived status for a task lineage",
    description="Returns a low-cost derived status summary from projection cache.",
    dependencies=[Depends(verify_api_key)],
)
async def status_receipts_interview(
    request: StatusReceiptsRequest,
    sources: SourceManager = Depends(get_source_manager),
):
    """
    status.receipts.interview() - Section 7.1

    Provides a low-cost derived status for a task lineage.
    Source defaults to projection_cache. MUST NOT query global ledger.
    """
    # Resolve root_task_id
    root_task_id = request.root_task_id or request.task_id
    if not root_task_id:
        raise HTTPException(
            status_code=400,
            detail="Either task_id or root_task_id is required",
        )

    # Try projection cache first
    status, age_ms = await sources.projection_cache.get_status(
        tenant_id=request.tenant_id,
        root_task_id=root_task_id,
    )

    if status:
        return StatusReceiptsResponse(
            status=status,
            metadata=ResponseMetadata(
                source=Source.PROJECTION_CACHE,
                freshness_age_ms=age_ms,
                truncated=False,
                cost_units=1,
            ),
        )

    # Fall back to unknown status if no cached data
    status = StatusSummary(
        tenant_id=request.tenant_id,
        root_task_id=root_task_id,
        state=TaskState.UNKNOWN,
    )

    return StatusReceiptsResponse(
        status=status,
        metadata=ResponseMetadata(
            source=Source.PROJECTION_CACHE,
            freshness_age_ms=0,
            truncated=False,
            cost_units=1,
        ),
    )


# =============================================================================
# 7.2 search.receipts.interview()
# =============================================================================


@router.post(
    "/v1/search/receipts",
    response_model=SearchReceiptsResponse,
    tags=["search"],
    summary="Search receipt headers with strict bounds",
    description="Searches receipt headers with filters. Never returns full bodies by default.",
    dependencies=[Depends(verify_api_key)],
)
async def search_receipts_interview(
    request: SearchReceiptsRequest,
    sources: SourceManager = Depends(get_source_manager),
    settings: Settings = Depends(get_settings),
):
    """
    search.receipts.interview() - Section 7.2

    Searches/lists receipt headers with strict bounds.
    Source defaults to projection_cache, fallback to ledger_mirror if enabled.
    Global ledger usage: opt-in only, never default.
    """
    controls = request.controls

    # Enforce limits
    limit = min(controls.limit, settings.max_limit)

    # Calculate time filter
    since = controls.since
    if not since:
        since = datetime.utcnow() - timedelta(hours=controls.time_window_hours)

    # Try projection cache first
    receipts, age_ms = await sources.projection_cache.search_receipts(
        tenant_id=request.tenant_id,
        root_task_id=request.root_task_id,
        phase=request.phase,
        recipient_ai=request.recipient_ai,
        since=since,
        limit=limit,
    )

    source = Source.PROJECTION_CACHE
    truncated = len(receipts) >= limit

    # If cache is empty and prefer_fresh/force_fresh, try ledger mirror
    if not receipts and controls.freshness in (Freshness.PREFER_FRESH, Freshness.FORCE_FRESH):
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
            age_ms = 0  # Fresh from mirror
            truncated = len(receipts) >= limit
        except SourceUnavailableError:
            pass  # Keep empty results from cache

    return SearchReceiptsResponse(
        receipts=receipts,
        metadata=ResponseMetadata(
            source=source,
            freshness_age_ms=age_ms,
            truncated=truncated,
            cost_units=max(1, len(receipts) // 10),
        ),
    )


# =============================================================================
# 7.3 get.receipt.interview()
# =============================================================================


@router.post(
    "/v1/get/receipt",
    response_model=GetReceiptResponse,
    tags=["get"],
    summary="Retrieve a single receipt by ID",
    description="Retrieves a single receipt. May return redacted receipt based on permissions.",
    dependencies=[Depends(verify_api_key)],
)
async def get_receipt_interview(
    request: GetReceiptRequest,
    sources: SourceManager = Depends(get_source_manager),
):
    """
    get.receipt.interview() - Section 7.3

    Retrieves a single receipt by ID (bounded).
    Source defaults to projection_cache, fallback to ledger_mirror.
    Global ledger usage: opt-in only.
    """
    # Try projection cache first
    receipt, age_ms = await sources.projection_cache.get_receipt(
        tenant_id=request.tenant_id,
        receipt_id=request.receipt_id,
    )

    if receipt:
        return GetReceiptResponse(
            receipt=receipt,
            found=True,
            metadata=ResponseMetadata(
                source=Source.PROJECTION_CACHE,
                freshness_age_ms=age_ms,
                truncated=False,
                cost_units=1,
            ),
        )

    # Try ledger mirror
    try:
        receipt = await sources.ledger_mirror.get_receipt(
            tenant_id=request.tenant_id,
            receipt_id=request.receipt_id,
        )

        if receipt:
            # Cache for future requests
            await sources.projection_cache.cache_receipt(receipt)

            return GetReceiptResponse(
                receipt=receipt,
                found=True,
                metadata=ResponseMetadata(
                    source=Source.LEDGER_MIRROR,
                    freshness_age_ms=0,
                    truncated=False,
                    cost_units=2,
                ),
            )
    except SourceUnavailableError:
        pass

    # Not found
    return GetReceiptResponse(
        receipt=None,
        found=False,
        metadata=ResponseMetadata(
            source=Source.PROJECTION_CACHE,
            freshness_age_ms=0,
            truncated=False,
            cost_units=1,
        ),
    )


# =============================================================================
# 7.4 health.async.interview()
# =============================================================================


@router.post(
    "/v1/health/async",
    response_model=HealthAsyncResponse,
    tags=["health"],
    summary="Live health snapshot of AsyncGate",
    description="Diagnostic health snapshot. Rate-limited with timeouts and caching.",
    dependencies=[Depends(verify_api_key)],
)
async def health_async_interview(
    request: HealthAsyncRequest,
    sources: SourceManager = Depends(get_source_manager),
    settings: Settings = Depends(get_settings),
):
    """
    health.async.interview() - Section 7.4

    Live health snapshot of AsyncGate (diagnostic, not historical).
    Source: component_poll
    Constraints: Rate-limited, timeout ≤500ms, cached 1-5 seconds.
    """
    try:
        data, age_ms = await sources.component_poller.poll_asyncgate_health(
            tenant_id=request.tenant_id,
            verbose=request.verbose,
        )

        metrics = None
        if request.verbose and "metrics" in data:
            metrics = MetricsSnapshot(**data["metrics"])

        return HealthAsyncResponse(
            component_id=data.get("component_id", "asyncgate"),
            reachable=True,
            version=data.get("version"),
            uptime_seconds=data.get("uptime_seconds"),
            error_budget_status=data.get("error_budget_status"),
            metrics_snapshot=metrics,
            metadata=ResponseMetadata(
                source=Source.COMPONENT_POLL,
                freshness_age_ms=age_ms,
                truncated=False,
                cost_units=5,  # Component polls are more expensive
            ),
        )
    except SourceUnavailableError as e:
        return HealthAsyncResponse(
            component_id="asyncgate",
            reachable=False,
            metadata=ResponseMetadata(
                source=Source.COMPONENT_POLL,
                freshness_age_ms=0,
                truncated=False,
                cost_units=1,
            ),
        )
    except DataSourceError as e:
        raise HTTPException(status_code=429, detail=str(e))


# =============================================================================
# 7.5 queue.async.interview()
# =============================================================================


@router.post(
    "/v1/queue/async",
    response_model=QueueAsyncResponse,
    tags=["queue"],
    summary="Live AsyncGate queue diagnostics",
    description="Queue diagnostics with bounded item headers. Rate-limited with timeouts.",
    dependencies=[Depends(verify_api_key)],
)
async def queue_async_interview(
    request: QueueAsyncRequest,
    sources: SourceManager = Depends(get_source_manager),
    settings: Settings = Depends(get_settings),
):
    """
    queue.async.interview() - Section 7.5

    Live AsyncGate queue diagnostics (bounded).
    Source: component_poll
    Constraints: Rate-limited, timeouts, caching. Never full payloads by default.
    """
    # Enforce limit bounds per spec
    limit = min(request.limit, 50)

    try:
        data, age_ms = await sources.component_poller.poll_asyncgate_queue(
            tenant_id=request.tenant_id,
            queue_id=request.queue_id,
            limit=limit,
            include_examples=request.include_examples,
        )

        items = []
        if request.include_examples and "items" in data:
            items = [QueueItemHeader(**item) for item in data["items"][:limit]]

        return QueueAsyncResponse(
            queue_depth=data.get("queue_depth", 0),
            oldest_item_age_ms=data.get("oldest_item_age_ms", 0),
            active_leases_count=data.get("active_leases_count", 0),
            items=items,
            metadata=ResponseMetadata(
                source=Source.COMPONENT_POLL,
                freshness_age_ms=age_ms,
                truncated=len(items) >= limit,
                cost_units=5,
            ),
        )
    except SourceUnavailableError:
        return QueueAsyncResponse(
            queue_depth=0,
            oldest_item_age_ms=0,
            active_leases_count=0,
            items=[],
            metadata=ResponseMetadata(
                source=Source.COMPONENT_POLL,
                freshness_age_ms=0,
                truncated=False,
                cost_units=1,
            ),
        )
    except DataSourceError as e:
        raise HTTPException(status_code=429, detail=str(e))


# =============================================================================
# 7.6 inventory.artifacts.depot.interview()
# =============================================================================


@router.post(
    "/v1/inventory/artifacts/depot",
    response_model=InventoryArtifactsResponse,
    tags=["inventory"],
    summary="List artifact pointers for a task lineage",
    description="Lists artifact metadata pointers. Never reads blob bodies.",
    dependencies=[Depends(verify_api_key)],
)
async def inventory_artifacts_depot_interview(
    request: InventoryArtifactsRequest,
    sources: SourceManager = Depends(get_source_manager),
    settings: Settings = Depends(get_settings),
):
    """
    inventory.artifacts.depot.interview() - Section 7.6

    Lists artifact pointers/manifests for a task lineage or deliverable.
    Source: storage_metadata (metadata DB + pointer index)
    Constraints: MUST NOT read blob bodies, bounded and paginated.
    """
    if not request.root_task_id and not request.deliverable_id:
        raise HTTPException(
            status_code=400,
            detail="Either root_task_id or deliverable_id is required",
        )

    controls = request.controls
    limit = min(controls.limit, settings.max_limit)

    try:
        pointers, manifest_pointer, counts = await sources.storage_metadata.list_artifacts(
            tenant_id=request.tenant_id,
            root_task_id=request.root_task_id,
            deliverable_id=request.deliverable_id,
            limit=limit,
        )

        return InventoryArtifactsResponse(
            artifact_pointers=pointers,
            shipment_manifest_pointer=manifest_pointer,
            staged_counts_by_role=counts,
            metadata=ResponseMetadata(
                source=Source.STORAGE_METADATA,
                freshness_age_ms=0,
                truncated=len(pointers) >= limit,
                cost_units=max(1, len(pointers) // 10),
            ),
        )
    except SourceUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))


# =============================================================================
# Global Ledger Access Error Handler
# =============================================================================


@router.post(
    "/v1/global-ledger/receipts",
    tags=["global-ledger"],
    summary="Query global ledger (opt-in only)",
    description="Direct access to global ledger. Disabled by default.",
    dependencies=[Depends(verify_api_key)],
)
async def global_ledger_query(
    tenant_id: str,
    root_task_id: str,
    sources: SourceManager = Depends(get_source_manager),
    settings: Settings = Depends(get_settings),
):
    """
    Global ledger access endpoint.

    Per spec section 9: Disabled by default, requires explicit opt-in.
    Returns GLOBAL_LEDGER_DISABLED error if not enabled.
    """
    if not settings.allow_global_ledger:
        raise HTTPException(
            status_code=403,
            detail=GlobalLedgerError(
                error_code="GLOBAL_LEDGER_DISABLED",
                message="Global ledger access is disabled",
                detail="Set INTERVIEW_ALLOW_GLOBAL_LEDGER=true to enable direct ledger queries",
            ).model_dump(),
        )

    try:
        receipts = await sources.global_ledger.query_receipts(
            tenant_id=tenant_id,
            root_task_id=root_task_id,
        )
        return {
            "receipts": [r.model_dump() for r in receipts],
            "metadata": ResponseMetadata(
                source=Source.GLOBAL_LEDGER,
                freshness_age_ms=0,
                truncated=False,
                cost_units=100,  # High cost for global ledger
            ).model_dump(),
        }
    except GlobalLedgerDisabledError:
        raise HTTPException(
            status_code=403,
            detail=GlobalLedgerError(
                error_code="GLOBAL_LEDGER_DISABLED",
                message="Global ledger access is disabled",
            ).model_dump(),
        )
    except SourceUnavailableError as e:
        raise HTTPException(status_code=503, detail=str(e))
