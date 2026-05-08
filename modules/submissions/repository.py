from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import Submission


def get_submission(db: Session, submission_id: int) -> Optional[Submission]:
    return db.get(Submission, submission_id)


def list_submissions(
    db: Session,
    *,
    form_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Submission]:
    stmt = select(Submission)
    if form_id is not None:
        stmt = stmt.where(Submission.form_id == form_id)
    if customer_id is not None:
        stmt = stmt.where(Submission.customer_id == customer_id)
    if user_id is not None:
        stmt = stmt.where(Submission.user_id == user_id)
    stmt = stmt.order_by(Submission.submitted_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_submissions(
    db: Session,
    *,
    form_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None,
) -> int:
    stmt = select(func.count()).select_from(Submission)
    if form_id is not None:
        stmt = stmt.where(Submission.form_id == form_id)
    if customer_id is not None:
        stmt = stmt.where(Submission.customer_id == customer_id)
    if user_id is not None:
        stmt = stmt.where(Submission.user_id == user_id)
    return db.execute(stmt).scalar_one()


def create_submission(
    db: Session,
    *,
    form_id: int,
    answers: dict,
    score: Optional[float],
    customer_id: Optional[int],
    user_id: Optional[int],
) -> Submission:
    submission = Submission(
        form_id=form_id,
        answers=answers,
        score=score,
        customer_id=customer_id,
        user_id=user_id,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def update_submission(
    db: Session, submission: Submission, *, answers: dict, score: Optional[float]
) -> Submission:
    submission.answers = answers
    submission.score = score
    db.commit()
    db.refresh(submission)
    return submission


def delete_submission(db: Session, submission: Submission) -> None:
    db.delete(submission)
    db.commit()
