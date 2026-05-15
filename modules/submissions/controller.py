from typing import Optional

from sqlalchemy.orm import Session

from common.dto import Page
from modules.auth.dto import Principal

from . import service
from .dto import (
    SubmissionDetail,
    SubmissionDraftUpdate,
    SubmissionFinalize,
    SubmissionRead,
    SubmissionStartRequest,
)


def list_submissions(
    db: Session,
    *,
    principal: Principal,
    form_id: Optional[int],
    mine_only: bool,
    status_in: Optional[list[str]],
    limit: int,
    offset: int,
) -> Page[SubmissionRead]:
    items, total = service.list_submissions(
        db,
        principal=principal,
        form_id=form_id,
        mine_only=mine_only,
        status_in=status_in,
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
    db: Session, submission_id: int, principal: Principal
) -> SubmissionRead:
    submission = service.get_submission(
        db, submission_id=submission_id, principal=principal
    )
    return SubmissionRead.model_validate(submission)


def get_submission_detail(
    db: Session, submission_id: int, principal: Principal
) -> SubmissionDetail:
    submission = service.get_submission(
        db, submission_id=submission_id, principal=principal
    )
    return service.serialize_detail(submission, principal=principal)


def start_submission(
    db: Session, payload: SubmissionStartRequest, principal: Principal
) -> SubmissionRead:
    submission = service.start_submission(
        db, form_id=payload.form_id, principal=principal
    )
    return SubmissionRead.model_validate(submission)


def save_draft(
    db: Session,
    submission_id: int,
    payload: SubmissionDraftUpdate,
    principal: Principal,
) -> SubmissionRead:
    submission = service.save_draft(
        db,
        submission_id=submission_id,
        answers=payload.answers,
        principal=principal,
    )
    return SubmissionRead.model_validate(submission)


def submit_submission(
    db: Session,
    submission_id: int,
    payload: SubmissionFinalize,
    principal: Principal,
) -> SubmissionRead:
    submission = service.submit_submission(
        db,
        submission_id=submission_id,
        answers=payload.answers,
        principal=principal,
    )
    return SubmissionRead.model_validate(submission)


def reveal_submission(
    db: Session, submission_id: int, principal: Principal
) -> SubmissionRead:
    submission = service.reveal_submission(
        db, submission_id=submission_id, principal=principal
    )
    return SubmissionRead.model_validate(submission)


def delete_submission(
    db: Session, submission_id: int, principal: Principal
) -> None:
    service.delete_submission(
        db, submission_id=submission_id, principal=principal
    )
