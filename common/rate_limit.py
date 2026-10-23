"""A small in-memory sliding-window rate limiter.

Counts live in this process only: with several workers or serverless
instances each keeps its own count, so the effective limit is per instance.
Move the counts to Redis before relying on it for strict limits.
"""

import threading
import time
from collections import deque
from typing import Optional

from fastapi import Request, status

from common.errors import CodedHTTPException

_MAX_KEYS = 50_000


class SlidingWindowLimiter:
    def __init__(self) -> None:
        self._hits: dict[str, deque[float]] = {}
        self._lock = threading.Lock()

    def hit(self, key: str, limit: int, window_seconds: float) -> Optional[float]:
        """Records a hit. Returns None if allowed, else seconds until the
        oldest hit in the window expires."""
        now = time.monotonic()
        with self._lock:
            if len(self._hits) > _MAX_KEYS:
                self._hits.clear()  # crude bound on memory; limits reset
            hits = self._hits.setdefault(key, deque())
            while hits and hits[0] <= now - window_seconds:
                hits.popleft()
            if len(hits) >= limit:
                return hits[0] + window_seconds - now
            hits.append(now)
            return None

    def reset(self) -> None:
        with self._lock:
            self._hits.clear()


limiter = SlidingWindowLimiter()


def client_ip(request: Request) -> str:
    # Behind one proxy (the deployment's), the right-most X-Forwarded-For
    # entry is the one it added; entries to its left are client-supplied.
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[-1].strip()
    return request.client.host if request.client else "unknown"


def enforce(key: str, limit: int, window_seconds: float) -> None:
    retry_after = limiter.hit(key, limit, window_seconds)
    if retry_after is not None:
        raise CodedHTTPException(
            status.HTTP_429_TOO_MANY_REQUESTS,
            "Too many attempts. Please wait a moment and try again.",
            code="rate_limited",
            headers={"Retry-After": str(max(1, int(retry_after + 0.999)))},
        )
