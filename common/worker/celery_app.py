"""Celery app for the background worker and Beat.

Run (see README in this folder):
  celery -A common.worker.celery_app worker --without-gossip --without-mingle --without-heartbeat
  celery -A common.worker.celery_app beat

Every limit below comes from config/RedisEnv.py (and so from .env). The
settings keep Redis small: no results are stored, tasks expire if they sit
in the queue too long, and keys carry REDIS_KEY_PREFIX.
"""

from celery import Celery

from config import RedisEnv

from .registry import JOBS

if not RedisEnv.REDIS_URL:
    raise RuntimeError("REDIS_URL must be set to run the worker or Beat")

celery_app = Celery("cx", broker=RedisEnv.REDIS_URL, include=["common.worker.tasks"])

celery_app.conf.update(
    # --- connections ---
    broker_pool_limit=RedisEnv.CELERY_BROKER_POOL_LIMIT,
    redis_max_connections=RedisEnv.REDIS_MAX_CONNECTIONS,
    broker_connection_retry_on_startup=True,
    broker_transport_options={
        "max_connections": RedisEnv.REDIS_MAX_CONNECTIONS,
        "visibility_timeout": RedisEnv.CELERY_VISIBILITY_TIMEOUT_SECONDS,
        "socket_timeout": RedisEnv.REDIS_SOCKET_TIMEOUT_SECONDS,
        "socket_connect_timeout": RedisEnv.REDIS_SOCKET_TIMEOUT_SECONDS,
        "health_check_interval": RedisEnv.REDIS_HEALTH_CHECK_SECONDS,
        "global_keyprefix": RedisEnv.REDIS_KEY_PREFIX,
    },
    worker_enable_remote_control=RedisEnv.CELERY_REMOTE_CONTROL,
    worker_send_task_events=False,
    task_send_sent_event=False,
    # --- memory: never write results to Redis ---
    task_ignore_result=True,
    result_backend=None,
    task_expires=RedisEnv.CELERY_TASK_EXPIRES_SECONDS,
    # --- execution ---
    worker_concurrency=RedisEnv.CELERY_WORKER_CONCURRENCY,
    worker_prefetch_multiplier=1,
    task_acks_late=True,
    task_reject_on_worker_lost=True,
    task_time_limit=RedisEnv.CELERY_TASK_TIME_LIMIT_SECONDS,
    task_soft_time_limit=max(1, RedisEnv.CELERY_TASK_TIME_LIMIT_SECONDS - 10),
    timezone="UTC",
    enable_utc=True,
    # --- schedules (Beat): every job in the registry with an interval ---
    beat_schedule={
        name: {
            "task": name,
            "schedule": float(job.every_seconds),
            # a run that isn't picked up before the next one is pointless
            "options": {"expires": min(job.every_seconds, RedisEnv.CELERY_TASK_EXPIRES_SECONDS)},
        }
        for name, job in JOBS.items()
        if job.every_seconds
    },
)
