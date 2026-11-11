from datetime import datetime

from sqlalchemy import delete
from sqlalchemy.orm import Session

from .model import FailedJob


def add_failed_job(db: Session, job: FailedJob) -> FailedJob:
    db.add(job)
    db.commit()
    return job


def delete_failed_jobs_before(db: Session, cutoff: datetime) -> int:
    result = db.execute(delete(FailedJob).where(FailedJob.failed_at < cutoff))
    db.commit()
    return result.rowcount or 0
