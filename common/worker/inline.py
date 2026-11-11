"""Runs jobs inside the API process, for when there is no Celery worker.

Same policy as the worker: retry with backoff, then log to failed_jobs. The
backoff is capped at INLINE_RETRY_BACKOFF_MAX_SECONDS because it happens
inside a request; the next tick tries a failed scheduled job again anyway.
"""

import random
import time
import traceback
import uuid
from dataclasses import dataclass, field
from typing import Any, Optional

import redis
from loguru import logger

from common.services.redis_client import get_redis, key as redis_key
from config import RedisEnv
from db import SessionLocal

from .registry import JOBS, Job


@dataclass
class JobRun:
    name: str
    ok: bool
    attempts: int
    result: Any = None
    error: Optional[str] = None


@dataclass
class TickResult:
    ran: list[JobRun] = field(default_factory=list)
    not_due: list[str] = field(default_factory=list)


def _record_failure(job: Job, run_id: str, kwargs: dict, retries: int, exc: BaseException) -> None:
    from modules.jobs import service as jobs_service

    try:
        with SessionLocal() as db:
            jobs_service.record_failure(
                db, task_id=run_id, task_name=job.name, args=(), kwargs=kwargs,
                retries=retries, error=exc, traceback=traceback.format_exc(),
            )
    except Exception as log_exc:  # never let logging hide the real failure
        logger.exception("could not record failed job {}: {!r}", run_id, log_exc)


def run(job: Job, **kwargs: Any) -> JobRun:
    run_id = f"inline-{uuid.uuid4()}"
    attempts = RedisEnv.JOB_MAX_RETRIES + 1
    for attempt in range(1, attempts + 1):
        try:
            return JobRun(job.name, True, attempt, result=job.func(**kwargs))
        except Exception as exc:
            if attempt == attempts:
                logger.error("job {} [{}] failed for good: {!r}", job.name, run_id, exc)
                _record_failure(job, run_id, kwargs, attempt - 1, exc)
                return JobRun(job.name, False, attempt, error=f"{type(exc).__name__}: {exc}")
            delay = min(2 ** (attempt - 1), RedisEnv.INLINE_RETRY_BACKOFF_MAX_SECONDS)
            logger.warning("job {} attempt {} failed ({!r}); retrying", job.name, attempt, exc)
            time.sleep(delay * random.uniform(0.5, 1.0))
    raise AssertionError("unreachable")


def _claim(job: Job) -> bool:
    """True if the job is due. A Redis key that expires just before the next
    run marks it as done, so overlapping or early ticks don't run it twice.
    Without Redis every tick runs it (the jobs are safe to repeat)."""
    client = get_redis()
    if client is None:
        return True
    ttl = max(1, job.every_seconds - 5)  # ticks arrive a little early or late
    try:
        return bool(client.set(redis_key("jobs", "due", job.name), "1", nx=True, ex=ttl))
    except redis.RedisError as exc:
        logger.warning("jobs: Redis unavailable, running {} anyway ({})", job.name, exc)
        return True


def run_due_jobs() -> TickResult:
    tick = TickResult()
    for job in JOBS.values():
        if not job.every_seconds:
            continue
        if _claim(job):
            tick.ran.append(run(job))
        else:
            tick.not_due.append(job.name)
    return tick
