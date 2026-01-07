"""InterView configuration.

Based on SPEC-IV-0000 (v0).
"""

from functools import lru_cache
from pydantic_settings import BaseSettings


class Settings(BaseSettings):
    """InterView configuration settings."""

    # Server
    host: str = "0.0.0.0"
    port: int = 8000
    debug: bool = False
    instance_id: str = "interview-1"

    # Version
    interview_version: str = "0.1.0"

    # Data sources
    projection_cache_url: str | None = None
    ledger_mirror_url: str | None = None
    asyncgate_url: str | None = None
    depotgate_url: str | None = None
    memorygate_url: str | None = None

    # Global ledger access (section 9)
    allow_global_ledger: bool = False
    global_ledger_url: str | None = None

    # Rate limiting for component polls (section 7.4, 7.5)
    component_poll_rate_limit_per_minute: int = 60
    component_poll_timeout_ms: int = 500
    component_poll_cache_seconds: int = 5

    # Cost bounding defaults (section 5)
    default_limit: int = 100
    max_limit: int = 200
    default_time_window_hours: int = 24
    max_time_window_hours: int = 168  # 1 week

    # Projection cache TTL
    projection_cache_ttl_seconds: int = 60

    model_config = {
        "env_prefix": "INTERVIEW_",
        "env_file": ".env",
        "extra": "ignore",
    }


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
