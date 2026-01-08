"""InterView configuration.

Based on SPEC-IV-0000 (v0).
"""

from functools import lru_cache
from pydantic import Field, field_validator
from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    """InterView configuration settings."""

    model_config = SettingsConfigDict(
        env_prefix="INTERVIEW_",
        env_file=".env",
        env_file_encoding="utf-8",
        case_sensitive=False,
        extra="ignore",
    )

    # Server
    host: str = Field(default="0.0.0.0", description="Server bind address")
    port: int = Field(default=8000, description="Server port")
    debug: bool = Field(default=False, description="Enable debug mode")
    instance_id: str = Field(default="interview-1", description="Instance identifier")

    # Version
    interview_version: str = Field(default="0.1.0", description="Service version")

    # Data sources
    projection_cache_url: str | None = Field(default=None, description="Projection cache URL")
    ledger_mirror_url: str | None = Field(default=None, description="Ledger mirror URL")
    asyncgate_url: str | None = Field(default=None, description="AsyncGate URL")
    asyncgate_api_key: str | None = Field(default=None, description="AsyncGate API key")
    depotgate_url: str | None = Field(default=None, description="DepotGate URL")
    depotgate_api_key: str | None = Field(default=None, description="DepotGate API key")
    memorygate_url: str | None = Field(default=None, description="MemoryGate URL")

    # Global ledger access (section 9)
    allow_global_ledger: bool = Field(default=False, description="Allow global ledger access")
    global_ledger_url: str | None = Field(default=None, description="Global ledger URL")

    # Rate limiting for component polls (section 7.4, 7.5)
    component_poll_rate_limit_per_minute: int = Field(default=60, description="Component poll rate limit per minute")
    component_poll_timeout_ms: int = Field(default=500, description="Component poll timeout in milliseconds")
    component_poll_cache_seconds: int = Field(default=5, description="Component poll cache duration")

    # Cost bounding defaults (section 5)
    default_limit: int = Field(default=100, description="Default result limit")
    max_limit: int = Field(default=200, description="Maximum result limit")
    default_time_window_hours: int = Field(default=24, description="Default time window in hours")
    max_time_window_hours: int = Field(default=168, description="Maximum time window in hours (1 week)")

    # Projection cache TTL
    projection_cache_ttl_seconds: int = Field(default=60, description="Projection cache TTL")

    # CORS configuration (explicit allowlist for security)
    cors_allowed_origins: list[str] = Field(
        default=["http://localhost:3000", "http://localhost:8080"],
        description="Allowed CORS origins"
    )
    cors_allow_credentials: bool = Field(default=True, description="Allow credentials in CORS requests")
    cors_allowed_methods: list[str] = Field(
        default=["GET", "POST", "PUT", "DELETE", "OPTIONS"],
        description="Allowed HTTP methods"
    )
    cors_allowed_headers: list[str] = Field(
        default=["Authorization", "Content-Type", "X-Tenant-ID"],
        description="Allowed request headers"
    )

    # Authentication
    api_key: str = Field(default="", description="API key for authentication")
    allow_insecure_dev: bool = Field(default=False, description="Allow unauthenticated access (dev only)")

    # API rate limiting
    rate_limit_enabled: bool = Field(default=True, description="Enable API rate limiting")
    rate_limit_requests_per_minute: int = Field(default=100, description="API rate limit per minute")

    # Validators
    @field_validator("port")
    @classmethod
    def validate_port(cls, v: int) -> int:
        """Validate port number range."""
        if not 1 <= v <= 65535:
            raise ValueError(f"Port must be between 1 and 65535, got {v}")
        return v

    @field_validator("projection_cache_url", "ledger_mirror_url", "asyncgate_url", "depotgate_url", "memorygate_url", "global_ledger_url")
    @classmethod
    def validate_integration_url(cls, v: str | None) -> str | None:
        """Validate integration URLs are HTTP(S)."""
        if v and not v.startswith(("http://", "https://")):
            raise ValueError(f"URL must start with http:// or https://, got {v}")
        return v

    @field_validator("api_key")
    @classmethod
    def validate_api_key(cls, v: str, info) -> str:
        """Validate API key is set when auth is required."""
        allow_insecure = info.data.get("allow_insecure_dev", False)
        if not v and not allow_insecure:
            raise ValueError("api_key is required when allow_insecure_dev=False")
        return v


@lru_cache
def get_settings() -> Settings:
    """Get cached settings instance."""
    return Settings()
