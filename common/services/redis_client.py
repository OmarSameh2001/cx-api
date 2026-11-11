"""One small, shared Redis connection pool per process.

The pool blocks (up to REDIS_POOL_TIMEOUT_SECONDS) instead of opening more
than REDIS_MAX_CONNECTIONS, so a burst of requests can't exhaust the plan's
connection limit.
"""

import threading
from typing import Optional

import redis

from config import RedisEnv

_client: Optional[redis.Redis] = None
_lock = threading.Lock()


def get_redis() -> Optional[redis.Redis]:
    """The shared client, or None when REDIS_URL isn't set."""
    global _client
    if not RedisEnv.REDIS_URL:
        return None
    if _client is None:
        with _lock:
            if _client is None:
                pool = redis.BlockingConnectionPool.from_url(
                    RedisEnv.REDIS_URL,
                    max_connections=RedisEnv.REDIS_MAX_CONNECTIONS,
                    timeout=RedisEnv.REDIS_POOL_TIMEOUT_SECONDS,
                    socket_timeout=RedisEnv.REDIS_SOCKET_TIMEOUT_SECONDS,
                    socket_connect_timeout=RedisEnv.REDIS_SOCKET_TIMEOUT_SECONDS,
                    health_check_interval=RedisEnv.REDIS_HEALTH_CHECK_SECONDS,
                )
                _client = redis.Redis(connection_pool=pool)
    return _client


def key(*parts: str) -> str:
    return RedisEnv.REDIS_KEY_PREFIX + ":".join(parts)
