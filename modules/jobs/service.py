import json
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.orm import Session

from config import RedisEnv

from . import repository
from .model import FailedJob

_MAX_ERROR = 2000
_MAX_TRACEBACK = 10000


def _jsonable(value: Any) -> Any:
    try:
        json.dumps(value)
        return value
    except (TypeError, ValueError):
        return repr(value)


def record_failure(
    db: Session,
    *,
    task_id: str,
    task_name: str,
    args: Optional[tuple],
    kwargs: Optional[dict],
    retries: int,
    error: BaseException,
    traceback: Optional[str],
) -> FailedJob:
    job = FailedJob(
        task_id=task_id,
        task_name=task_name,
        args=_jsonable(list(args or ())),
        kwargs=_jsonable(dict(kwargs or {})),
        retries=retries,
        error=f"{type(error).__name__}: {error}"[:_MAX_ERROR],
        traceback=traceback[-_MAX_TRACEBACK:] if traceback else None,
    )
    return repository.add_failed_job(db, job)


def purge_old_failures(db: Session) -> int:
    cutoff = datetime.now(timezone.utc) - timedelta(days=RedisEnv.FAILED_JOB_RETENTION_DAYS)
    return repository.delete_failed_jobs_before(db, cutoff)


def run_scheduled_jobs() -> dict:
    """One scheduler tick. With JOBS_RUNNER=celery, Beat owns the schedule,
    so the tick does nothing (no job runs twice during a migration)."""
    if RedisEnv.JOBS_RUNNER == "celery":
        return {"runner": "celery"}
    # imported here: the registry imports this module
    from common.worker import inline

    tick = inline.run_due_jobs()
    return {
        "runner": "inline",
        "ran": [run.__dict__ for run in tick.ran],
        "not_due": tick.not_due,
    }
