"""InterView data models.

Based on SPEC-IV-0000 (v0).
"""

from datetime import datetime
from enum import Enum
from typing import Any, Optional
from pydantic import BaseModel, Field


# =============================================================================
# Health & Service Models
# =============================================================================

class HealthResponse(BaseModel):
    """Standard health check response"""
    status: str
    service: str = "InterView"
    version: str
    instance_id: str


# =============================================================================
# Domain Models
# =============================================================================

class Source(str, Enum):
    """Data source for InterView responses."""
    PROJECTION_CACHE = "projection_cache"
    LEDGER_MIRROR = "ledger_mirror"
    COMPONENT_POLL = "component_poll"
    STORAGE_METADATA = "storage_metadata"
    GLOBAL_LEDGER = "global_ledger"


class Freshness(str, Enum):
    """Freshness preference for queries."""
    CACHE_OK = "cache_ok"
    PREFER_FRESH = "prefer_fresh"
    FORCE_FRESH = "force_fresh"


class TaskState(str, Enum):
    """Derived task state."""
    UNKNOWN = "unknown"
    ACCEPTED = "accepted"
    IN_PROGRESS = "in_progress"
    ESCALATED = "escalated"
    BLOCKED = "blocked"
    RESOLVED = "resolved"
    SHIPPED = "shipped"


class ResponseMetadata(BaseModel):
    """Standard response metadata per spec section 6."""

    source: Source = Field(..., description="Data source used")
    freshness_age_ms: int = Field(..., ge=0, description="Age of data in milliseconds")
    truncated: bool = Field(default=False, description="Whether results were truncated")
    next_page_token: Optional[str] = Field(None, description="Pagination token")
    cost_units: int = Field(default=1, ge=0, description="Rough cost estimate")


class RequestControls(BaseModel):
    """Standard request controls per spec section 5."""

    limit: int = Field(default=100, ge=1, le=200, description="Max results")
    since: Optional[datetime] = Field(None, description="Filter by time")
    time_window_hours: int = Field(default=24, ge=1, le=168, description="Time window in hours")
    include_body: bool = Field(default=False, description="Include full body (v0 may not support)")
    freshness: Freshness = Field(default=Freshness.CACHE_OK, description="Freshness preference")


# =============================================================================
# status.receipts.interview() models (section 7.1)
# =============================================================================


class StatusSummary(BaseModel):
    """Status summary for a task lineage."""

    tenant_id: str
    root_task_id: str
    state: TaskState = Field(..., description="Derived state")
    latest_receipt_id: Optional[str] = Field(None, description="Most recent receipt")
    last_updated_at: Optional[datetime] = Field(None, description="Last update timestamp")
    open_obligations_count: Optional[int] = Field(None, description="Open obligations")
    shipment_status: Optional[str] = Field(None, description="Shipment status if applicable")

    # Pointers (optional)
    shipment_manifest_pointer: Optional[str] = Field(None, description="Manifest pointer")
    artifact_pointers: list[str] = Field(default_factory=list, description="Artifact pointers")


class StatusReceiptsRequest(BaseModel):
    """Request for status.receipts.interview()."""

    tenant_id: str = Field(..., description="Tenant identifier")
    task_id: Optional[str] = Field(None, description="Task ID (or root_task_id)")
    root_task_id: Optional[str] = Field(None, description="Root task ID")


class StatusReceiptsResponse(BaseModel):
    """Response for status.receipts.interview()."""

    status: StatusSummary
    metadata: ResponseMetadata


# =============================================================================
# search.receipts.interview() models (section 7.2)
# =============================================================================


class ReceiptHeader(BaseModel):
    """Compact receipt header."""

    receipt_id: str
    phase: str
    task_id: str
    root_task_id: Optional[str] = None
    tenant_id: str
    recipient_ai: Optional[str] = None
    created_at: Optional[datetime] = None
    stored_at: Optional[datetime] = None


class SearchReceiptsRequest(BaseModel):
    """Request for search.receipts.interview()."""

    tenant_id: str = Field(..., description="Tenant identifier")
    root_task_id: str = Field(..., description="Root task ID (required)")
    phase: Optional[str] = Field(None, description="Filter by phase")
    recipient_ai: Optional[str] = Field(None, description="Filter by recipient")
    controls: RequestControls = Field(default_factory=RequestControls)


class SearchReceiptsResponse(BaseModel):
    """Response for search.receipts.interview()."""

    receipts: list[ReceiptHeader]
    metadata: ResponseMetadata


# =============================================================================
# get.receipt.interview() models (section 7.3)
# =============================================================================


class GetReceiptRequest(BaseModel):
    """Request for get.receipt.interview()."""

    tenant_id: str = Field(..., description="Tenant identifier")
    receipt_id: str = Field(..., description="Receipt ID")


class FullReceipt(BaseModel):
    """Full receipt object (or redacted)."""

    receipt_id: str
    tenant_id: str
    task_id: str
    root_task_id: Optional[str] = None
    parent_task_id: Optional[str] = None
    caused_by_receipt_id: Optional[str] = None
    phase: str
    status: Optional[str] = None
    from_principal: Optional[str] = None
    for_principal: Optional[str] = None
    source_system: Optional[str] = None
    recipient_ai: Optional[str] = None
    task_type: Optional[str] = None
    task_summary: Optional[str] = None
    outcome_kind: Optional[str] = None
    outcome_text: Optional[str] = None
    artifact_pointer: Optional[str] = None
    escalation_class: Optional[str] = None
    escalation_reason: Optional[str] = None
    escalation_to: Optional[str] = None
    created_at: Optional[datetime] = None
    stored_at: Optional[datetime] = None
    completed_at: Optional[datetime] = None

    # Redaction marker
    redacted: bool = Field(default=False, description="Whether fields were redacted")


class GetReceiptResponse(BaseModel):
    """Response for get.receipt.interview()."""

    receipt: Optional[FullReceipt] = None
    found: bool = True
    metadata: ResponseMetadata


# =============================================================================
# health.async.interview() models (section 7.4)
# =============================================================================


class HealthAsyncRequest(BaseModel):
    """Request for health.async.interview()."""

    tenant_id: str = Field(..., description="Tenant identifier")
    verbose: bool = Field(default=False, description="Include verbose metrics")


class MetricsSnapshot(BaseModel):
    """Bounded metrics snapshot."""

    queued_count: int = 0
    leased_count: int = 0
    succeeded_count: int = 0
    failed_count: int = 0


class HealthAsyncResponse(BaseModel):
    """Response for health.async.interview()."""

    component_id: str
    reachable: bool
    version: Optional[str] = None
    uptime_seconds: Optional[int] = None
    error_budget_status: Optional[str] = None
    metrics_snapshot: Optional[MetricsSnapshot] = None
    metadata: ResponseMetadata


# =============================================================================
# queue.async.interview() models (section 7.5)
# =============================================================================


class QueueAsyncRequest(BaseModel):
    """Request for queue.async.interview()."""

    tenant_id: str = Field(..., description="Tenant identifier")
    queue_id: Optional[str] = Field(None, description="Specific queue ID")
    limit: int = Field(default=20, ge=1, le=50, description="Max items")
    include_examples: bool = Field(default=False, description="Include example items")


class QueueItemHeader(BaseModel):
    """Queue item header (never full payload)."""

    task_id: str
    task_type: str
    status: str
    priority: int = 0
    created_at: Optional[datetime] = None
    age_ms: int = 0


class QueueAsyncResponse(BaseModel):
    """Response for queue.async.interview()."""

    queue_depth: int
    oldest_item_age_ms: int = 0
    active_leases_count: int = 0
    items: list[QueueItemHeader] = Field(default_factory=list)
    metadata: ResponseMetadata


# =============================================================================
# inventory.artifacts.depot.interview() models (section 7.6)
# =============================================================================


class InventoryArtifactsRequest(BaseModel):
    """Request for inventory.artifacts.depot.interview()."""

    tenant_id: str = Field(..., description="Tenant identifier")
    root_task_id: Optional[str] = Field(None, description="Root task ID")
    deliverable_id: Optional[str] = Field(None, description="Deliverable ID")
    controls: RequestControls = Field(default_factory=RequestControls)


class ArtifactPointer(BaseModel):
    """Artifact pointer metadata (no blob body)."""

    artifact_id: str
    root_task_id: str
    mime_type: str
    size_bytes: int
    artifact_role: str
    staged_at: Optional[datetime] = None
    location: Optional[str] = None
    content_hash: Optional[str] = None


class StagedCountsByRole(BaseModel):
    """Counts by artifact role."""

    plan: int = 0
    final_output: int = 0
    supporting: int = 0
    intermediate: int = 0


class InventoryArtifactsResponse(BaseModel):
    """Response for inventory.artifacts.depot.interview()."""

    artifact_pointers: list[ArtifactPointer]
    shipment_manifest_pointer: Optional[str] = None
    staged_counts_by_role: Optional[StagedCountsByRole] = None
    metadata: ResponseMetadata


# =============================================================================
# Error models
# =============================================================================


class InterViewError(BaseModel):
    """Error response."""

    error_code: str
    message: str
    detail: Optional[str] = None


class GlobalLedgerError(InterViewError):
    """Error when global ledger access is blocked."""

    error_code: str = "GLOBAL_LEDGER_DISABLED"
