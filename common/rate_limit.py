"""Sliding-window rate limiter.

With RATE_LIMIT_BACKEND=redis the counts are shared by every instance: each
key is a sorted set of hit times that expires one window after its last hit,
so nothing outlives its window. Keys are hashed, so no IP or email is stored.
If Redis can't be reached the request is counted in memory instead (limits
become per instance for that moment) rather than failing.
"""

import hashlib
import threading
import time
import uuid
from collections import deque
from typing import Optional

import redis
from fastapi import Request, status
from loguru import logger

from common.errors import CodedHTTPException
from common.services.redis_client import get_redis, key as redis_key
from config import RedisEnv

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


# Trim old hits, refuse if full (returning seconds until a slot frees), else
# record the hit and push the key's expiry to one window from now.
_LUA = """
local now = tonumber(ARGV[1])
local window = tonumber(ARGV[2])
redis.call('ZREMRANGEBYSCORE', KEYS[1], '-inf', now - window)
if redis.call('ZCARD', KEYS[1]) >= tonumber(ARGV[3]) then
  local oldest = redis.call('ZRANGE', KEYS[1], 0, 0, 'WITHSCORES')
  return tostring(tonumber(oldest[2]) + window - now)
end
redis.call('ZADD', KEYS[1], now, ARGV[4])
redis.call('PEXPIRE', KEYS[1], math.ceil(window * 1000))
return false
"""


class RedisSlidingWindowLimiter:
    def __init__(self, fallback: SlidingWindowLimiter) -> None:
        self._fallback = fallback
        self._script = None

    def hit(self, key: str, limit: int, window_seconds: float) -> Optional[float]:
        client = get_redis()
        if client is None:
            return self._fallback.hit(key, limit, window_seconds)
        try:
            if self._script is None:
                self._script = client.register_script(_LUA)
            digest = hashlib.blake2b(key.encode(), digest_size=12).hexdigest()
            now = time.time()
            member = f"{now:.6f}:{uuid.uuid4().hex[:6]}"
            result = self._script(
                keys=[redis_key("rl", digest)], args=[now, window_seconds, limit, member]
            )
        except redis.RedisError as exc:
            logger.warning("rate limit: Redis unavailable, counting in memory ({})", exc)
            return self._fallback.hit(key, limit, window_seconds)
        return None if result is None else float(result)

    def reset(self) -> None:
        self._fallback.reset()


memory_limiter = SlidingWindowLimiter()
limiter = (
    RedisSlidingWindowLimiter(memory_limiter)
    if RedisEnv.RATE_LIMIT_BACKEND == "redis"
    else memory_limiter
)


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
