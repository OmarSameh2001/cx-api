from datetime import datetime
from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session, selectinload

from modules.customers.model import Customer
from modules.employees.model import Employee
from modules.forms.model import Form

from .model import Submission


def get_submission(db: Session, submission_id: int) -> Optional[Submission]:
    stmt = (
        select(Submission)
        .where(Submission.id == submission_id)
        .options(
            selectinload(Submission.form).selectinload(Form.fields),
            selectinload(Submission.employee),
            selectinload(Submission.customer),
        )
    )
    return db.execute(stmt).scalar_one_or_none()


def _apply_filters(
    stmt,
    *,
    form_id,
    customer_id,
    user_id,
    organisation_id,
    status_in,
    submitter_search=None,
):
    if form_id is not None:
        stmt = stmt.where(Submission.form_id == form_id)
    if customer_id is not None:
        stmt = stmt.where(Submission.customer_id == customer_id)
    if user_id is not None:
        stmt = stmt.where(Submission.user_id == user_id)
    if organisation_id is not None:
        stmt = stmt.join(Form, Submission.form_id == Form.id).where(
            Form.organisation_id == organisation_id
        )
    if status_in:
        stmt = stmt.where(Submission.status.in_(status_in))
    if submitter_search:
        pattern = f"%{submitter_search}%"
        stmt = (
            stmt
            .outerjoin(Employee, Submission.user_id == Employee.id)
            .outerjoin(Customer, Submission.customer_id == Customer.id)
            .where(
                or_(
                    Employee.username.ilike(pattern),
                    Employee.first_name.ilike(pattern),
                    Employee.last_name.ilike(pattern),
                    Customer.first_name.ilike(pattern),
                    Customer.last_name.ilike(pattern),
                    Customer.email.ilike(pattern),
                )
            )
        )
    return stmt


_SORT_COLUMNS = {
    "id": Submission.id,
    "started_at": Submission.started_at,
    "submitted_at": Submission.submitted_at,
    "score": Submission.score,
    "status": Submission.status,
    "attempt_number": Submission.attempt_number,
}


def list_submissions(
    db: Session,
    *,
    form_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    organisation_id: Optional[int] = None,
    status_in: Optional[list[str]] = None,
    submitter_search: Optional[str] = None,
    sort_by: str = "started_at",
    sort_dir: str = "desc",
    limit: int = 50,
    offset: int = 0,
) -> list[Submission]:
    stmt = (
        select(Submission)
        .options(
            selectinload(Submission.form).selectinload(Form.fields),
            selectinload(Submission.employee),
            selectinload(Submission.customer),
        )
    )
    stmt = _apply_filters(
        stmt,
        form_id=form_id,
        customer_id=customer_id,
        user_id=user_id,
        organisation_id=organisation_id,
        status_in=status_in,
        submitter_search=submitter_search,
    )
    col = _SORT_COLUMNS.get(sort_by, Submission.started_at)
    stmt = stmt.order_by(col.asc() if sort_dir == "asc" else col.desc())
    return list(db.execute(stmt.limit(limit).offset(offset)).scalars().all())


def count_submissions(
    db: Session,
    *,
    form_id: Optional[int] = None,
    customer_id: Optional[int] = None,
    user_id: Optional[int] = None,
    organisation_id: Optional[int] = None,
    status_in: Optional[list[str]] = None,
    submitter_search: Optional[str] = None,
) -> int:
    stmt = select(func.count()).select_from(Submission)
    stmt = _apply_filters(
        stmt,
        form_id=form_id,
        customer_id=customer_id,
        user_id=user_id,
        organisation_id=organisation_id,
        status_in=status_in,
        submitter_search=submitter_search,
    )
    return db.execute(stmt).scalar_one()


def count_finalized_attempts(
    db: Session,
    *,
    form_id: int,
    user_id: Optional[int],
    customer_id: Optional[int],
) -> int:
    stmt = select(func.count()).select_from(Submission).where(
        Submission.form_id == form_id,
        Submission.status.in_(("submitted", "late")),
    )
    if user_id is not None:
        stmt = stmt.where(Submission.user_id == user_id)
    elif customer_id is not None:
        stmt = stmt.where(Submission.customer_id == customer_id)
    return db.execute(stmt).scalar_one()


def find_open_submission(
    db: Session,
    *,
    form_id: int,
    user_id: Optional[int],
    customer_id: Optional[int],
) -> Optional[Submission]:
    stmt = (
        select(Submission)
        .options(selectinload(Submission.form).selectinload(Form.fields))
        .where(
            Submission.form_id == form_id,
            Submission.status == "in_progress",
        )
    )
    if user_id is not None:
        stmt = stmt.where(Submission.user_id == user_id)
    elif customer_id is not None:
        stmt = stmt.where(Submission.customer_id == customer_id)
    else:
        return None
    return db.execute(stmt).scalar_one_or_none()


def create_submission(
    db: Session,
    *,
    form_id: int,
    customer_id: Optional[int],
    user_id: Optional[int],
    expires_at: Optional[datetime],
    attempt_number: int,
) -> Submission:
    submission = Submission(
        form_id=form_id,
        answers={},
        customer_id=customer_id,
        user_id=user_id,
        expires_at=expires_at,
        attempt_number=attempt_number,
        status="in_progress",
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission


def save(db: Session, submission: Submission) -> Submission:
    db.commit()
    db.refresh(submission)
    return submission


def delete_submission(db: Session, submission: Submission) -> None:
    db.delete(submission)
    db.commit()
