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


def verify_api_key(
    authorization: Optional[str] = Header(None),
    x_api_key: Optional[str] = Header(None, alias="X-API-Key"),
) -> bool:
    """
    Verify API key for protected endpoints.

    Checks Authorization: Bearer or X-API-Key header against
    the configured INTERVIEW_API_KEY environment variable.

    Security: Fails closed - if api_key is not configured and we're not
    in explicit insecure dev mode, all requests are rejected.
    """
    settings = get_settings()

    # Check if auth is required
    if settings.allow_insecure_dev:
        return True

    # Extract API key from headers
    api_key = None
    if authorization and authorization.startswith("Bearer "):
        api_key = authorization[7:]
    elif x_api_key:
        api_key = x_api_key

    if not api_key:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Missing authorization. Use Authorization: Bearer <key> or X-API-Key header",
            headers={"WWW-Authenticate": "Bearer"},
        )

    # Validate against configured API key
    if not settings.api_key:
        logger.error(
            "SECURITY VIOLATION: api_key not configured. "
            "Set INTERVIEW_API_KEY or enable INTERVIEW_ALLOW_INSECURE_DEV=true (dev only)."
        )
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Server misconfigured: authentication not properly initialized",
        )

    # Constant-time comparison to prevent timing attacks
    if not secrets.compare_digest(api_key, settings.api_key):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Invalid API key",
            headers={"WWW-Authenticate": "Bearer"},
        )

    return True


def generate_api_key() -> str:
    """Generate a new API key with iv_ prefix.

    Utility function for generating keys - the key should be stored
    in INTERVIEW_API_KEY environment variable.
    """
    return f"{API_KEY_PREFIX}{secrets.token_urlsafe(32)}"
