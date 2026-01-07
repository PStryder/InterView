"""Data source clients for InterView.

Based on SPEC-IV-0000 (v0) section 2 - Source-of-Truth Hierarchy.
"""

import asyncio
from abc import ABC, abstractmethod
from datetime import datetime, timedelta
from typing import Any, Optional
import httpx

from .config import get_settings
from .models import (
    Source,
    Freshness,
    ResponseMetadata,
    StatusSummary,
    TaskState,
    ReceiptHeader,
    FullReceipt,
    MetricsSnapshot,
    QueueItemHeader,
    ArtifactPointer,
    StagedCountsByRole,
)


class DataSourceError(Exception):
    """Base error for data source operations."""
    pass


class SourceUnavailableError(DataSourceError):
    """Raised when a data source is unavailable."""
    pass


class GlobalLedgerDisabledError(DataSourceError):
    """Raised when global ledger access is disabled."""
    pass


class DataSource(ABC):
    """Abstract base class for InterView data sources."""

    @property
    @abstractmethod
    def source_type(self) -> Source:
        """Return the source type for metadata."""
        pass


class ProjectionCache:
    """
    Local read-optimized store for derived summaries and compact receipt headers.

    Per spec section 2: Projection Cache is the preferred source.
    """

    source_type = Source.PROJECTION_CACHE

    def __init__(self):
        self.settings = get_settings()
        # In-memory cache for v0 (production would use Redis/DB)
        self._status_cache: dict[tuple[str, str], tuple[StatusSummary, datetime]] = {}
        self._receipt_headers: dict[str, list[ReceiptHeader]] = {}
        self._receipt_cache: dict[str, tuple[FullReceipt, datetime]] = {}

    def _cache_age_ms(self, cached_at: datetime) -> int:
        """Calculate age of cached data in milliseconds."""
        return int((datetime.utcnow() - cached_at).total_seconds() * 1000)

    async def get_status(
        self,
        tenant_id: str,
        root_task_id: str,
    ) -> tuple[StatusSummary | None, int]:
        """
        Get cached status summary for a task lineage.

        Returns (status, freshness_age_ms) or (None, 0) if not cached.
        """
        key = (tenant_id, root_task_id)
        if key in self._status_cache:
            status, cached_at = self._status_cache[key]
            age_ms = self._cache_age_ms(cached_at)
            if age_ms < self.settings.projection_cache_ttl_seconds * 1000:
                return status, age_ms
            # Expired
            del self._status_cache[key]
        return None, 0

    async def cache_status(self, status: StatusSummary) -> None:
        """Cache a status summary."""
        key = (status.tenant_id, status.root_task_id)
        self._status_cache[key] = (status, datetime.utcnow())

    async def search_receipts(
        self,
        tenant_id: str,
        root_task_id: str,
        phase: str | None = None,
        recipient_ai: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> tuple[list[ReceiptHeader], int]:
        """
        Search cached receipt headers.

        Returns (headers, freshness_age_ms).
        """
        key = f"{tenant_id}:{root_task_id}"
        headers = self._receipt_headers.get(key, [])

        # Apply filters
        if phase:
            headers = [h for h in headers if h.phase == phase]
        if recipient_ai:
            headers = [h for h in headers if h.recipient_ai == recipient_ai]
        if since:
            headers = [h for h in headers if h.created_at and h.created_at >= since]

        # Sort by created_at descending
        headers = sorted(headers, key=lambda h: h.created_at or datetime.min, reverse=True)

        # Apply limit
        headers = headers[:limit]

        # Estimate freshness (use oldest cached item age)
        age_ms = 0
        if headers:
            # Approximation based on cache state
            age_ms = 1000  # Default 1 second for cached data

        return headers, age_ms

    async def get_receipt(
        self,
        tenant_id: str,
        receipt_id: str,
    ) -> tuple[FullReceipt | None, int]:
        """
        Get a cached receipt by ID.

        Returns (receipt, freshness_age_ms) or (None, 0) if not cached.
        """
        key = f"{tenant_id}:{receipt_id}"
        if key in self._receipt_cache:
            receipt, cached_at = self._receipt_cache[key]
            return receipt, self._cache_age_ms(cached_at)
        return None, 0

    async def cache_receipt(self, receipt: FullReceipt) -> None:
        """Cache a full receipt."""
        key = f"{receipt.tenant_id}:{receipt.receipt_id}"
        self._receipt_cache[key] = (receipt, datetime.utcnow())


class LedgerMirror:
    """
    Local or read-replica receipt store for bounded history queries.

    Per spec section 2: Ledger Mirror is permitted as fallback.
    """

    source_type = Source.LEDGER_MIRROR

    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def query_receipts(
        self,
        tenant_id: str,
        root_task_id: str,
        phase: str | None = None,
        recipient_ai: str | None = None,
        since: datetime | None = None,
        limit: int = 100,
    ) -> list[ReceiptHeader]:
        """Query receipts from ledger mirror."""
        if not self.settings.ledger_mirror_url:
            raise SourceUnavailableError("Ledger mirror URL not configured")

        client = await self._get_client()
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "root_task_id": root_task_id,
            "limit": limit,
        }
        if phase:
            params["phase"] = phase
        if recipient_ai:
            params["recipient_ai"] = recipient_ai
        if since:
            params["since"] = since.isoformat()

        try:
            response = await client.get(
                f"{self.settings.ledger_mirror_url}/receipts/search",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return [ReceiptHeader(**r) for r in data.get("receipts", [])]
        except httpx.HTTPError as e:
            raise SourceUnavailableError(f"Ledger mirror query failed: {e}")

    async def get_receipt(
        self,
        tenant_id: str,
        receipt_id: str,
    ) -> FullReceipt | None:
        """Get a single receipt from ledger mirror."""
        if not self.settings.ledger_mirror_url:
            raise SourceUnavailableError("Ledger mirror URL not configured")

        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.settings.ledger_mirror_url}/receipts/{receipt_id}",
                params={"tenant_id": tenant_id},
            )
            if response.status_code == 404:
                return None
            response.raise_for_status()
            return FullReceipt(**response.json())
        except httpx.HTTPError as e:
            raise SourceUnavailableError(f"Ledger mirror get failed: {e}")


class ComponentPoller:
    """
    Rate-limited component health/diagnostics poller.

    Per spec sections 7.4, 7.5: Must be rate-limited with timeouts and caching.
    """

    source_type = Source.COMPONENT_POLL

    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None
        self._cache: dict[str, tuple[Any, datetime]] = {}
        self._rate_limiter: dict[str, list[datetime]] = {}

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client with configured timeout."""
        if self._client is None:
            timeout = self.settings.component_poll_timeout_ms / 1000
            self._client = httpx.AsyncClient(timeout=timeout)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _check_rate_limit(self, component: str) -> bool:
        """Check if we're within rate limits."""
        now = datetime.utcnow()
        window = timedelta(minutes=1)

        if component not in self._rate_limiter:
            self._rate_limiter[component] = []

        # Clean old entries
        self._rate_limiter[component] = [
            t for t in self._rate_limiter[component]
            if now - t < window
        ]

        # Check limit
        if len(self._rate_limiter[component]) >= self.settings.component_poll_rate_limit_per_minute:
            return False

        self._rate_limiter[component].append(now)
        return True

    def _get_cached(self, cache_key: str) -> tuple[Any, int] | None:
        """Get cached data if still fresh."""
        if cache_key in self._cache:
            data, cached_at = self._cache[cache_key]
            age_ms = int((datetime.utcnow() - cached_at).total_seconds() * 1000)
            if age_ms < self.settings.component_poll_cache_seconds * 1000:
                return data, age_ms
            del self._cache[cache_key]
        return None

    def _set_cache(self, cache_key: str, data: Any) -> None:
        """Cache poll result."""
        self._cache[cache_key] = (data, datetime.utcnow())

    async def poll_asyncgate_health(
        self,
        tenant_id: str,
        verbose: bool = False,
    ) -> tuple[dict[str, Any], int]:
        """
        Poll AsyncGate health status.

        Returns (health_data, freshness_age_ms).
        """
        cache_key = f"asyncgate:health:{tenant_id}:{verbose}"

        # Check cache first
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        if not self.settings.asyncgate_url:
            raise SourceUnavailableError("AsyncGate URL not configured")

        if not self._check_rate_limit("asyncgate"):
            raise DataSourceError("Rate limit exceeded for AsyncGate polls")

        client = await self._get_client()
        try:
            response = await client.get(
                f"{self.settings.asyncgate_url}/health",
                params={"tenant_id": tenant_id, "verbose": verbose},
            )
            response.raise_for_status()
            data = response.json()
            self._set_cache(cache_key, data)
            return data, 0
        except httpx.TimeoutException:
            raise SourceUnavailableError("AsyncGate health poll timed out")
        except httpx.HTTPError as e:
            raise SourceUnavailableError(f"AsyncGate health poll failed: {e}")

    async def poll_asyncgate_queue(
        self,
        tenant_id: str,
        queue_id: str | None = None,
        limit: int = 20,
        include_examples: bool = False,
    ) -> tuple[dict[str, Any], int]:
        """
        Poll AsyncGate queue diagnostics.

        Returns (queue_data, freshness_age_ms).
        """
        cache_key = f"asyncgate:queue:{tenant_id}:{queue_id}:{limit}:{include_examples}"

        # Check cache first
        cached = self._get_cached(cache_key)
        if cached:
            return cached

        if not self.settings.asyncgate_url:
            raise SourceUnavailableError("AsyncGate URL not configured")

        if not self._check_rate_limit("asyncgate"):
            raise DataSourceError("Rate limit exceeded for AsyncGate polls")

        client = await self._get_client()
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "limit": min(limit, 50),  # Cap at 50 per spec
            "include_examples": include_examples,
        }
        if queue_id:
            params["queue_id"] = queue_id

        try:
            response = await client.get(
                f"{self.settings.asyncgate_url}/queues/diagnostics",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            self._set_cache(cache_key, data)
            return data, 0
        except httpx.TimeoutException:
            raise SourceUnavailableError("AsyncGate queue poll timed out")
        except httpx.HTTPError as e:
            raise SourceUnavailableError(f"AsyncGate queue poll failed: {e}")


class StorageMetadata:
    """
    Artifact metadata source from DepotGate.

    Per spec section 7.6: Pointers only, no blob body reads.
    """

    source_type = Source.STORAGE_METADATA

    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    async def list_artifacts(
        self,
        tenant_id: str,
        root_task_id: str | None = None,
        deliverable_id: str | None = None,
        limit: int = 100,
    ) -> tuple[list[ArtifactPointer], str | None, StagedCountsByRole | None]:
        """
        List artifact pointers for a task lineage or deliverable.

        Returns (pointers, shipment_manifest_pointer, staged_counts).
        """
        if not self.settings.depotgate_url:
            raise SourceUnavailableError("DepotGate URL not configured")

        client = await self._get_client()
        params: dict[str, Any] = {
            "tenant_id": tenant_id,
            "limit": limit,
        }
        if root_task_id:
            params["root_task_id"] = root_task_id
        if deliverable_id:
            params["deliverable_id"] = deliverable_id

        try:
            response = await client.get(
                f"{self.settings.depotgate_url}/artifacts/metadata",
                params=params,
            )
            response.raise_for_status()
            data = response.json()

            pointers = [ArtifactPointer(**a) for a in data.get("artifacts", [])]
            manifest_pointer = data.get("shipment_manifest_pointer")

            counts = None
            if "staged_counts" in data:
                counts = StagedCountsByRole(**data["staged_counts"])

            return pointers, manifest_pointer, counts
        except httpx.HTTPError as e:
            raise SourceUnavailableError(f"DepotGate metadata query failed: {e}")


class GlobalLedger:
    """
    Direct access to global receipt store.

    Per spec section 9: Disabled by default, requires explicit opt-in.
    """

    source_type = Source.GLOBAL_LEDGER

    def __init__(self):
        self.settings = get_settings()
        self._client: httpx.AsyncClient | None = None

    async def _get_client(self) -> httpx.AsyncClient:
        """Get or create HTTP client."""
        if self._client is None:
            self._client = httpx.AsyncClient(timeout=30.0)
        return self._client

    async def close(self) -> None:
        """Close the HTTP client."""
        if self._client:
            await self._client.aclose()
            self._client = None

    def _check_access(self) -> None:
        """Check if global ledger access is allowed."""
        if not self.settings.allow_global_ledger:
            raise GlobalLedgerDisabledError(
                "Global ledger access is disabled. "
                "Set INTERVIEW_ALLOW_GLOBAL_LEDGER=true to enable."
            )
        if not self.settings.global_ledger_url:
            raise SourceUnavailableError("Global ledger URL not configured")

    async def query_receipts(
        self,
        tenant_id: str,
        root_task_id: str,
        **kwargs,
    ) -> list[ReceiptHeader]:
        """Query receipts from global ledger (requires explicit opt-in)."""
        self._check_access()

        client = await self._get_client()
        params = {
            "tenant_id": tenant_id,
            "root_task_id": root_task_id,
            **kwargs,
        }

        try:
            response = await client.get(
                f"{self.settings.global_ledger_url}/receipts/search",
                params=params,
            )
            response.raise_for_status()
            data = response.json()
            return [ReceiptHeader(**r) for r in data.get("receipts", [])]
        except httpx.HTTPError as e:
            raise SourceUnavailableError(f"Global ledger query failed: {e}")


class SourceManager:
    """
    Manages data sources and implements the source hierarchy.

    Per spec section 2: projection_cache > ledger_mirror > component_poll > global_ledger
    """

    def __init__(self):
        self.projection_cache = ProjectionCache()
        self.ledger_mirror = LedgerMirror()
        self.component_poller = ComponentPoller()
        self.storage_metadata = StorageMetadata()
        self.global_ledger = GlobalLedger()

    async def close(self) -> None:
        """Close all source clients."""
        await self.ledger_mirror.close()
        await self.component_poller.close()
        await self.storage_metadata.close()
        await self.global_ledger.close()
