"""Celery tasks: one per job in the registry, with the shared retry policy."""

from .base_task import JobTask
from .celery_app import celery_app
from .registry import JOBS

tasks = {
    name: celery_app.task(base=JobTask, name=name)(job.func)
    for name, job in JOBS.items()
}
