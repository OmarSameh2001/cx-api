from typing import Optional

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import SubmissionCreate, SubmissionRead, SubmissionUpdate


def list_submissions(
    db: Session,
    *,
    principal_type: str,
    principal_id: int,
    form_id: Optional[int],
    limit: int,
    offset: int,
) -> Page[SubmissionRead]:
    items, total = service.list_submissions(
        db,
        principal_type=principal_type,
        principal_id=principal_id,
        form_id=form_id,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[SubmissionRead.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_submission(
    db: Session, submission_id: int, principal_type: str, principal_id: int
) -> SubmissionRead:
    submission = service.get_submission(
        db,
        submission_id=submission_id,
        principal_type=principal_type,
        principal_id=principal_id,
    )
    return SubmissionRead.model_validate(submission)


def create_submission(
    db: Session, payload: SubmissionCreate, principal_type: str, principal_id: int
) -> SubmissionRead:
    submission = service.create_submission(
        db,
        payload=payload,
        principal_type=principal_type,
        principal_id=principal_id,
    )
    return SubmissionRead.model_validate(submission)


def update_submission(
    db: Session,
    submission_id: int,
    payload: SubmissionUpdate,
    principal_type: str,
    principal_id: int,
) -> SubmissionRead:
    submission = service.update_submission(
        db,
        submission_id=submission_id,
        payload=payload,
        principal_type=principal_type,
        principal_id=principal_id,
    )
    return SubmissionRead.model_validate(submission)


def delete_submission(
    db: Session, submission_id: int, principal_type: str, principal_id: int
) -> None:
    service.delete_submission(
        db,
        submission_id=submission_id,
        principal_type=principal_type,
        principal_id=principal_id,
    )
