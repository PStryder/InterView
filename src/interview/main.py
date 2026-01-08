"""InterView - Read-Only System Viewer Surfaces for LegiVellum Meshes.

InterView is observational only.
InterView is a window. If it can change the world, it is no longer a Viewer.
"""

from contextlib import asynccontextmanager
from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
import logging

from .config import get_settings
from .api import router, shutdown_sources

settings = get_settings()

# Configure logging
logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("interview")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"InterView v{settings.interview_version} starting...")
    logger.info("InterView is observational only. A window, not a gate.")
    yield
    logger.info("InterView shutting down...")
    await shutdown_sources()


app = FastAPI(
    title="InterView",
    description="""
InterView - Read-Only System Viewer Surfaces for LegiVellum Meshes.

## Core Doctrine

InterView is observational only.
It may query ledgers, caches, storage metadata, and (optionally) poll components for diagnostics.
It MUST NOT initiate work, route work, modify artifacts, mutate system state, or trigger automation.

**InterView is a window. If it can change the world, it is no longer a Viewer.**

## Source Hierarchy (Load-Safety Contract)

1. **Projection Cache** (preferred) - Local read-optimized store
2. **Ledger Mirror** (permitted) - Read-replica receipt store
3. **Component Diagnostics** (optional) - Rate-limited health/metrics
4. **Global Ledger** (last resort) - Opt-in only, disabled by default

## v0 Surfaces

- `status.receipts.interview()` - Derived task lineage status
- `search.receipts.interview()` - Bounded receipt header search
- `get.receipt.interview()` - Single receipt retrieval
- `health.async.interview()` - AsyncGate health snapshot
- `queue.async.interview()` - AsyncGate queue diagnostics
- `inventory.artifacts.depot.interview()` - Artifact pointer listing
    """,
    version=settings.interview_version,
    lifespan=lifespan,
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=settings.cors_allowed_origins,
    allow_credentials=settings.cors_allow_credentials,
    allow_methods=settings.cors_allowed_methods,
    allow_headers=settings.cors_allowed_headers,
)

# Include API router
app.include_router(router)


def main():
    """Run the InterView server."""
    import uvicorn

    uvicorn.run(
        "interview.main:app",
        host=settings.host,
        port=settings.port,
        reload=settings.debug,
    )


if __name__ == "__main__":
    main()
