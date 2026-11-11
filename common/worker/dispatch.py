"""Start a job from app code without caring who runs it.

    from common.worker.dispatch import dispatch
    dispatch("jobs.ping")

JOBS_RUNNER=celery queues it for the worker; JOBS_RUNNER=inline runs it now,
in this process, with the same retries and failed-job log.
"""

from typing import Any

from config import RedisEnv

from .registry import JOBS


def dispatch(name: str, **kwargs: Any) -> None:
    job = JOBS[name]  # KeyError on a typo, in both modes
    if RedisEnv.JOBS_RUNNER == "celery":
        from .celery_app import celery_app

        celery_app.send_task(name, kwargs=kwargs)
        return
    from . import inline

    inline.run(job, **kwargs)
