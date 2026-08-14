"""InterView - Read-Only System Viewer Surfaces for LegiVellum Meshes.

InterView is observational only.
InterView is a window. If it can change the world, it is no longer a Viewer.
"""

import logging
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware

from .config import get_settings
from .mcp import router as mcp_router
from .mcp import shutdown_sources as shutdown_mcp_sources
from .metagate_client import acknowledge_startup, bootstrap_from_metagate

settings = get_settings()

logging.basicConfig(
    level=logging.DEBUG if settings.debug else logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger("interview")


@asynccontextmanager
async def lifespan(app: FastAPI):
    """Application lifespan handler."""
    logger.info(f"InterView v{settings.interview_version} starting...")
    # Resolve peer endpoints from MetaGate before anything that uses them.
    # Best-effort by design: a failure must never prevent startup, or the
    # bootstrap authority becomes a hidden master.
    _bootstrap = await bootstrap_from_metagate(settings)
    if _bootstrap is not None and _bootstrap.succeeded:
        await acknowledge_startup(settings, _bootstrap)

    logger.info("InterView is observational only. A window, not a gate.")
    yield
    logger.info("InterView shutting down...")
    await shutdown_mcp_sources()


def create_app() -> FastAPI:
    """Create the InterView application."""
    app = FastAPI(
        title="InterView",
        description="Read-Only System Viewer Surfaces for LegiVellum Meshes",
        version=settings.interview_version,
        lifespan=lifespan,
    )

    app.add_middleware(
        CORSMiddleware,
        allow_origins=settings.cors_allowed_origins,
        allow_credentials=settings.cors_allow_credentials,
        allow_methods=settings.cors_allowed_methods,
        allow_headers=settings.cors_allowed_headers,
    )

    app.include_router(mcp_router)

    return app


app = create_app()


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
