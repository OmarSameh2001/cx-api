"""Every background job, defined once.

Each job is a plain function that opens its own DB session and calls a
module service. The Celery tasks (tasks.py) and the inline runner
(inline.py) both run these same functions, so switching JOBS_RUNNER changes
who runs a job, not what it does. Jobs must be safe to run more than once.
"""

from dataclasses import dataclass
from typing import Any, Callable, Optional

from loguru import logger

import models  # noqa: F401  -- register all SQLAlchemy mappers
from config import RedisEnv
from db import SessionLocal
from modules.jobs import service as jobs_service
from modules.submissions import service as submissions_service


@dataclass(frozen=True)
class Job:
    name: str
    func: Callable[..., Any]
    # None means it only runs when dispatched, never on a schedule
    every_seconds: Optional[int] = None


def expire_abandoned_attempts() -> int:
    with SessionLocal() as db:
        count = submissions_service.expire_abandoned_attempts(db)
    if count:
        logger.info("expired {} abandoned attempt(s)", count)
    return count


def purge_failed_jobs() -> int:
    with SessionLocal() as db:
        count = jobs_service.purge_old_failures(db)
    if count:
        logger.info("purged {} old failed job(s)", count)
    return count


def ping() -> str:
    """Smoke test: dispatch("jobs.ping") and watch the log."""
    logger.info("pong")
    return "pong"


JOBS: dict[str, Job] = {
    job.name: job
    for job in (
        Job("submissions.expire_abandoned_attempts", expire_abandoned_attempts,
            RedisEnv.EXPIRY_SWEEP_SECONDS),
        Job("jobs.purge_failed_jobs", purge_failed_jobs, RedisEnv.FAILED_JOB_PURGE_SECONDS),
        Job("jobs.ping", ping),
    )
}
