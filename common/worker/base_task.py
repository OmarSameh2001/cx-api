"""Retry policy and failed-job log shared by every background task."""

from celery import Task
from loguru import logger

from config import RedisEnv
from db import SessionLocal


class JobTask(Task):
    # Any error is retried with exponential backoff and jitter, up to
    # JOB_MAX_RETRIES times. Tasks must be safe to run more than once.
    autoretry_for = (Exception,)
    max_retries = RedisEnv.JOB_MAX_RETRIES
    retry_backoff = True
    retry_backoff_max = RedisEnv.JOB_RETRY_BACKOFF_MAX_SECONDS
    retry_jitter = True

    def on_failure(self, exc, task_id, args, kwargs, einfo):
        """Called once retries are used up: log the job to failed_jobs."""
        # imported here so the Celery app loads without the models
        from modules.jobs import service as jobs_service

        logger.error("job {} [{}] failed for good: {!r}", self.name, task_id, exc)
        try:
            with SessionLocal() as db:
                jobs_service.record_failure(
                    db,
                    task_id=task_id,
                    task_name=self.name,
                    args=args,
                    kwargs=kwargs,
                    retries=self.request.retries,
                    error=exc,
                    traceback=str(einfo) if einfo else None,
                )
        except Exception as log_exc:  # never let logging hide the real failure
            logger.exception("could not record failed job {}: {!r}", task_id, log_exc)
