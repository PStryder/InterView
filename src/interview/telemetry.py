"""Minimal in-process telemetry counters for InterView."""

from __future__ import annotations

import logging
from collections import Counter
from threading import Lock
from typing import Any

logger = logging.getLogger(__name__)


class Telemetry:
    """Thread-safe counters for request and error visibility."""

    def __init__(self) -> None:
        self._lock = Lock()
        self._request_total = 0
        self._request_method_counts: Counter[str] = Counter()
        self._tools_call_error_code_counts: Counter[str] = Counter()

    def reset(self) -> None:
        with self._lock:
            self._request_total = 0
            self._request_method_counts.clear()
            self._tools_call_error_code_counts.clear()

    def record_request(self, method: str) -> None:
        with self._lock:
            self._request_total += 1
            self._request_method_counts[method] += 1

    def record_error_code(self, code: str) -> None:
        with self._lock:
            self._tools_call_error_code_counts[code] += 1
            count = self._tools_call_error_code_counts[code]
        logger.info(
            "interview_metric event=tools_call_error code=%s count=%s",
            code,
            count,
        )

    def snapshot(self) -> dict[str, Any]:
        with self._lock:
            return {
                "request_total": self._request_total,
                "request_method_counts": dict(self._request_method_counts),
                "tools_call_error_code_counts": dict(self._tools_call_error_code_counts),
            }


telemetry = Telemetry()
