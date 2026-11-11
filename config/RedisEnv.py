import os

from dotenv import load_dotenv

load_dotenv()


def _int(name: str, default: str) -> int:
    return int(os.getenv(name, default))


def _float(name: str, default: str) -> float:
    return float(os.getenv(name, default))


def _bool(name: str, default: str) -> bool:
    return os.getenv(name, default).strip().lower() in ("1", "true", "yes", "on")


REDIS_URL = os.getenv("REDIS_URL", "").strip()

# --- connections -------------------------------------------------------------
# The free Redis Cloud plan allows 30 connections in total, shared by every API
# instance, the worker and Beat. Each process keeps its own pool of this size;
# a request that finds the pool full waits up to REDIS_POOL_TIMEOUT_SECONDS.
REDIS_MAX_CONNECTIONS = _int("REDIS_MAX_CONNECTIONS", "2")
REDIS_POOL_TIMEOUT_SECONDS = _float("REDIS_POOL_TIMEOUT_SECONDS", "2")
REDIS_SOCKET_TIMEOUT_SECONDS = _float("REDIS_SOCKET_TIMEOUT_SECONDS", "3")
# idle connections are closed by the server after this, so they don't pile up
REDIS_HEALTH_CHECK_SECONDS = _int("REDIS_HEALTH_CHECK_SECONDS", "30")
REDIS_KEY_PREFIX = os.getenv("REDIS_KEY_PREFIX", "cx:")

# --- rate limits -------------------------------------------------------------
# "redis" shares counts across instances; "memory" keeps them per process.
# Defaults to redis when REDIS_URL is set. If Redis can't be reached, the
# limiter falls back to memory for that request instead of failing it.
RATE_LIMIT_BACKEND = os.getenv("RATE_LIMIT_BACKEND", "redis" if REDIS_URL else "memory").strip().lower()

# --- Celery ------------------------------------------------------------------
# Results are never stored in Redis: tasks only change Postgres, and failures
# are logged to the failed_jobs table. That keeps the 30 MB plan for the queue.
CELERY_BROKER_POOL_LIMIT = _int("CELERY_BROKER_POOL_LIMIT", "2")
CELERY_WORKER_CONCURRENCY = _int("CELERY_WORKER_CONCURRENCY", "2")
# a task taken but not acknowledged within this is handed out again
CELERY_VISIBILITY_TIMEOUT_SECONDS = _int("CELERY_VISIBILITY_TIMEOUT_SECONDS", "3600")
# a queued task older than this is dropped instead of run (and its message
# deleted), so a stopped worker can't let the queue fill Redis
CELERY_TASK_EXPIRES_SECONDS = _int("CELERY_TASK_EXPIRES_SECONDS", "600")
CELERY_TASK_TIME_LIMIT_SECONDS = _int("CELERY_TASK_TIME_LIMIT_SECONDS", "300")
# remote control (inspect, ping) costs one extra connection per worker
CELERY_REMOTE_CONTROL = _bool("CELERY_REMOTE_CONTROL", "false")

# --- who runs the jobs ---------------------------------------------------------
# "inline": no worker. A scheduler (cron-job.org, Vercel Cron...) calls
#   POST /internal/jobs/tick with "Authorization: Bearer <JOBS_CRON_SECRET>"
#   and the API runs whatever is due, in the request.
# "celery": the Celery worker and Beat run them; the tick endpoint does nothing.
JOBS_RUNNER = os.getenv("JOBS_RUNNER", "inline").strip().lower()
# unset disables the tick endpoint (it answers 404)
JOBS_CRON_SECRET = os.getenv("JOBS_CRON_SECRET", "").strip()
# inline retries happen inside a request, so they back off for seconds, not
# minutes; a job that still fails is logged and tried again on the next tick
INLINE_RETRY_BACKOFF_MAX_SECONDS = _float("INLINE_RETRY_BACKOFF_MAX_SECONDS", "2")

# --- retries and failed jobs ---------------------------------------------------
JOB_MAX_RETRIES = _int("JOB_MAX_RETRIES", "3")
# exponential backoff (1s, 2s, 4s...) capped at this, with jitter
JOB_RETRY_BACKOFF_MAX_SECONDS = _int("JOB_RETRY_BACKOFF_MAX_SECONDS", "300")
FAILED_JOB_RETENTION_DAYS = _int("FAILED_JOB_RETENTION_DAYS", "30")

# --- schedules -----------------------------------------------------------------
EXPIRY_SWEEP_SECONDS = _int("EXPIRY_SWEEP_SECONDS", "60")
FAILED_JOB_PURGE_SECONDS = _int("FAILED_JOB_PURGE_SECONDS", "86400")
