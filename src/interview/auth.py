"""
Authentication for InterView REST API.

Simple API key authentication for protecting API endpoints.
"""

import logging
import secrets
from typing import Optional

from fastapi import Header, HTTPException, status

from .config import get_settings


logger = logging.getLogger(__name__)

# API key prefix for InterView
API_KEY_PREFIX = "iv_"


def validate_api_key_value(api_key: Optional[str]) -> bool:
    """Validate an API key string against configured settings."""
    settings = get_settings()

    if settings.allow_insecure_dev:
        return True

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization. Use Authorization: Bearer <key> or X-API-Key header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    if not settings.api_key:
        logger.error(
            "SECURITY VIOLATION: api_key not configured. "
            "Set INTERVIEW_API_KEY or enable INTERVIEW_ALLOW_INSECURE_DEV=true (dev only)."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server misconfigured: authentication not properly initialized",
        )

    if not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


def verify_api_key(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> bool:
    """FastAPI dependency for REST auth (deprecated)."""
    api_key = None
    if authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:]
    elif x_api_key:
        api_key = x_api_key

    return validate_api_key_value(api_key)


def generate_api_key() -> str:
    """Generate a new API key with iv_ prefix.

    Utility function for generating keys - the key should be stored
    in INTERVIEW_API_KEY environment variable.
    """
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
