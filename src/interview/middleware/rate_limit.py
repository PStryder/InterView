"""Rate limiting middleware for InterView API."""

import asyncio
import logging
import time
from collections import defaultdict
from typing import Dict, Tuple

from fastapi import HTTPException, Request, status

logger = logging.getLogger(__name__)


class InMemoryRateLimiter:
    """In-memory rate limiter using sliding window."""

    def __init__(self):
        self._windows: Dict[str, list[float]] = defaultdict(list)
        self._lock = asyncio.Lock()

    async def check_rate_limit(
        self, key: str, max_calls: int, window_seconds: int
    ) -> Tuple[bool, int, int]:
        """Check rate limit using sliding window."""
        async with self._lock:
            now = time.time()
            window_start = now - window_seconds
            self._windows[key] = [ts for ts in self._windows[key] if ts > window_start]
            current_calls = len(self._windows[key])
            allowed = current_calls < max_calls
            remaining = max(0, max_calls - current_calls - (1 if allowed else 0))
            reset_time = int(self._windows[key][0] + window_seconds) if self._windows[key] else int(now + window_seconds)
            if allowed:
                self._windows[key].append(now)
            return allowed, remaining, reset_time


class RateLimiter:
    """Main rate limiter."""

    def __init__(self, calls_per_minute: int = 100, enabled: bool = True):
        self.backend = InMemoryRateLimiter()
        self.calls_per_minute = calls_per_minute
        self.enabled = enabled

    async def check_request(self, request: Request) -> None:
        """Check if request should be rate limited."""
        if not self.enabled:
            return
        client_ip = request.client.host if request.client else "unknown"
        key = f"ip:{client_ip}"
        allowed, remaining, reset_time = await self.backend.check_rate_limit(key, self.calls_per_minute, 60)
        if not allowed:
            retry_after = reset_time - int(time.time())
            logger.warning(f"Rate limit exceeded for {key}")
            raise HTTPException(
                status_code=status.HTTP_429_TOO_MANY_REQUESTS,
                detail=f"Rate limit exceeded. Retry after {retry_after} seconds.",
                headers={"Retry-After": str(retry_after), "X-RateLimit-Limit": str(self.calls_per_minute), 
                        "X-RateLimit-Remaining": "0", "X-RateLimit-Reset": str(reset_time)},
            )


_rate_limiter = None


def get_rate_limiter(calls_per_minute: int, enabled: bool) -> RateLimiter:
    """Get rate limiter singleton."""
    global _rate_limiter
    if _rate_limiter is None:
        _rate_limiter = RateLimiter(calls_per_minute, enabled)
    return _rate_limiter
