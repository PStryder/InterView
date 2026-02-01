"""InterView MCP server (HTTP JSON-RPC)."""

from __future__ import annotations

from contextlib import asynccontextmanager
from typing import Any

from fastapi import APIRouter, FastAPI, Request
from pydantic import BaseModel, Field

from .auth import validate_api_key_value
from .config import get_settings
from .middleware import get_rate_limiter
from .models import (
    GetReceiptRequest,
    HealthAsyncRequest,
    InventoryArtifactsRequest,
    QueueAsyncRequest,
    SearchReceiptsRequest,
    StatusReceiptsRequest,
)
from .sources import SourceManager


class MCPRequest(BaseModel):
    """JSON-RPC request envelope for MCP."""

    jsonrpc: str = Field(default="2.0")
    method: str
    params: dict[str, Any] = Field(default_factory=dict)
    id: Any = None


def _jsonrpc_result(request_id: Any, result: Any) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "result": result}


def _jsonrpc_error(request_id: Any, code: Any, message: str) -> dict[str, Any]:
    return {"jsonrpc": "2.0", "id": request_id, "error": {"code": code, "message": message}}


MCP_TOOLS = [
    {
        "name": "interview.health",
        "description": "Health check / service info",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "status.receipts.interview",
        "description": "Get derived status for a task lineage",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "search.receipts.interview",
        "description": "Search receipt headers with strict bounds",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "get.receipt.interview",
        "description": "Retrieve a single receipt by ID",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "health.async.interview",
        "description": "Live health snapshot of AsyncGate",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "queue.async.interview",
        "description": "Live AsyncGate queue diagnostics",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "inventory.artifacts.depot.interview",
        "description": "List artifact pointers for a task lineage",
        "inputSchema": {"type": "object", "properties": {}},
    },
    {
        "name": "global.ledger.receipts",
        "description": "Direct global ledger query (disabled by default)",
        "inputSchema": {"type": "object", "properties": {}},
    },
]


_source_manager: SourceManager | None = None


def get_source_manager() -> SourceManager:
    global _source_manager
    if _source_manager is None:
        _source_manager = SourceManager()
    return _source_manager


async def shutdown_sources() -> None:
    global _source_manager
    if _source_manager:
        await _source_manager.close()
        _source_manager = None


@asynccontextmanager
async def lifespan(app: FastAPI):
    yield
    await shutdown_sources()


router = APIRouter(prefix="/mcp", tags=["mcp"])


def _extract_auth_token(arguments: dict[str, Any], request: Request) -> str | None:
    token = arguments.pop("auth_token", None)
    if token:
        return token
    auth_header = request.headers.get("authorization")
    api_key_header = request.headers.get("x-api-key")
    if auth_header and auth_header.lower().startswith("bearer "):
        return auth_header.split(" ", 1)[1]
    if api_key_header:
        return api_key_header
    return None


async def _rate_limit(request: Request) -> None:
    settings = get_settings()
    limiter = get_rate_limiter(
        calls_per_minute=settings.rate_limit_requests_per_minute,
        enabled=settings.rate_limit_enabled,
    )
    await limiter.check_request(request)


async def _handle_tool(name: str, arguments: dict[str, Any]) -> dict[str, Any]:
    sources = get_source_manager()
    settings = get_settings()

    if name == "interview.health":
        return {
            "status": "healthy",
            "service": "InterView",
            "version": "0.1.0",
            "instance_id": settings.instance_id,
        }

    if name == "status.receipts.interview":
        req = StatusReceiptsRequest(**arguments)
        from .api import status_receipts_interview
        response = await status_receipts_interview(req, sources=sources)
        return response.model_dump()

    if name == "search.receipts.interview":
        req = SearchReceiptsRequest(**arguments)
        from .api import search_receipts_interview
        response = await search_receipts_interview(req, sources=sources, settings=settings)
        return response.model_dump()

    if name == "get.receipt.interview":
        req = GetReceiptRequest(**arguments)
        from .api import get_receipt_interview
        response = await get_receipt_interview(req, sources=sources)
        return response.model_dump()

    if name == "health.async.interview":
        req = HealthAsyncRequest(**arguments)
        from .api import health_async_interview
        response = await health_async_interview(req, sources=sources, settings=settings)
        return response.model_dump()

    if name == "queue.async.interview":
        req = QueueAsyncRequest(**arguments)
        from .api import queue_async_interview
        response = await queue_async_interview(req, sources=sources, settings=settings)
        return response.model_dump()

    if name == "inventory.artifacts.depot.interview":
        req = InventoryArtifactsRequest(**arguments)
        from .api import inventory_artifacts_depot_interview
        response = await inventory_artifacts_depot_interview(req, sources=sources, settings=settings)
        return response.model_dump()

    if name == "global.ledger.receipts":
        from .api import global_ledger_query
        response = await global_ledger_query(
            tenant_id=arguments.get("tenant_id"),
            root_task_id=arguments.get("root_task_id"),
            sources=sources,
            settings=settings,
        )
        return response

    raise ValueError(f"Unknown tool: {name}")


@router.post("")
async def mcp_entry(request_body: MCPRequest, request: Request):
    await _rate_limit(request)

    if request_body.method == "tools/list":
        return _jsonrpc_result(request_body.id, {"tools": MCP_TOOLS})

    if request_body.method != "tools/call":
        return _jsonrpc_error(request_body.id, -32601, f"Method not found: {request_body.method}")

    params = request_body.params or {}
    tool_name = params.get("name")
    arguments = params.get("arguments") or {}
    if not tool_name:
        return _jsonrpc_error(request_body.id, -32602, "Missing tool name")

    auth_token = _extract_auth_token(arguments, request)
    try:
        validate_api_key_value(auth_token)
    except Exception as exc:
        return _jsonrpc_error(request_body.id, "AUTH_FAILED", str(exc))

    try:
        result = await _handle_tool(tool_name, arguments)
        return _jsonrpc_result(request_body.id, result)
    except Exception as exc:
        return _jsonrpc_error(request_body.id, getattr(exc, "code", "ERROR"), str(exc))


app = FastAPI(title="InterView", version="0.1.0", lifespan=lifespan)
app.include_router(router)
