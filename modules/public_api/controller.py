"""Public link endpoints: no login, so no principal. The form comes from the
link's token; everything is scoped to that form's organisation."""

from typing import Optional

from sqlalchemy.orm import Session

from . import service
from .dto import (
    PublicDraft,
    PublicDraftRead,
    PublicDraftSave,
    PublicDraftUpdate,
    PublicEditRequest,
    PublicForm,
    PublicResponse,
    PublicSubmitRequest,
    PublicSubmitResponse,
)


def get_form(db: Session, token: str, *, attempt: Optional[str], prefill: Optional[str]) -> PublicForm:
    return service.public_form_read(db, token, attempt=attempt, prefill=prefill)


def submit(db: Session, token: str, payload: PublicSubmitRequest, *, ip: Optional[str]) -> PublicSubmitResponse:
    submission, ending, form = service.submit_public(db, token=token, payload=payload, ip=ip)
    return service.submit_response(submission, ending, form)


def save_draft(db: Session, token: str, payload: PublicDraftSave, *, ip: Optional[str]) -> PublicDraftRead:
    return service.save_draft(db, token=token, payload=payload, ip=ip)


def get_draft(db: Session, token: str, resume_token: str) -> PublicDraft:
    return service.get_draft(db, token=token, resume_token=resume_token)


def update_draft(db: Session, token: str, resume_token: str, payload: PublicDraftUpdate) -> PublicDraftRead:
    return service.update_draft(db, token=token, resume_token=resume_token, payload=payload)


def get_response(db: Session, token: str, edit_token: str) -> PublicResponse:
    return service.get_response(db, token=token, edit_token=edit_token)


def edit_response(db: Session, token: str, edit_token: str, payload: PublicEditRequest) -> PublicSubmitResponse:
    return service.edit_response(db, token=token, edit_token=edit_token, payload=payload)


def question_limits(db: Session, token: str, field_id: int):
    return service.question_limits(db, token=token, field_id=field_id)


def start_upload(db: Session, token: str, payload):
    return service.start_upload(db, token=token, payload=payload)


def complete_upload(db: Session, token: str, file_id: int, file_token: str):
    return service.complete_upload(db, token=token, file_id=file_id, file_token=file_token)
