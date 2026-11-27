from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from common.rate_limit import client_ip, enforce
from config import FilesEnv
from db import get_db

from . import service
from modules.files.dto import (
    EffectiveLimitsRead,
    FileRead,
    PublicCompleteRequest,
    PublicUploadRequest,
    UploadStartResponse,
)

from .dto import PublicForm, PublicSubmitRequest, PublicSubmitResponse


router = APIRouter(prefix="/public", tags=["public"])

# Public endpoints take no login, so they are rate limited instead: per
# client IP, and per form + email so one identity can't be hammered (or have
# its attempts used up) from many addresses.
FORM_LOADS_PER_MINUTE = 60
SUBMITS_PER_MINUTE_PER_IP = 10
SUBMITS_PER_HOUR_PER_EMAIL = 5


@router.get("/forms/{token}", response_model=PublicForm)
def get_public_form(token: str, request: Request, db: Session = Depends(get_db)):
    enforce(f"public-load:{client_ip(request)}", FORM_LOADS_PER_MINUTE, 60)
    return service.public_form_read(db, token)


@router.post(
    "/forms/{token}/submit",
    response_model=PublicSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_public_form(
    token: str,
    payload: PublicSubmitRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    enforce(f"public-submit:{client_ip(request)}", SUBMITS_PER_MINUTE_PER_IP, 60)
    email = payload.customer.email.strip().lower()
    enforce(f"public-submit:{token}:{email}", SUBMITS_PER_HOUR_PER_EMAIL, 3600)
    submission = service.submit_public(db, token=token, payload=payload)
    return PublicSubmitResponse(submission_id=submission.id)


@router.get("/forms/{token}/fields/{field_id}/limits", response_model=EffectiveLimitsRead)
def public_question_limits(token: str, field_id: int, request: Request, db: Session = Depends(get_db)):
    """What a file question accepts, so the browser can check and compress
    before uploading."""
    enforce(f"public-load:{client_ip(request)}", FORM_LOADS_PER_MINUTE, 60)
    return service.question_limits(db, token=token, field_id=field_id)


@router.post(
    "/forms/{token}/uploads",
    response_model=UploadStartResponse,
    status_code=status.HTTP_201_CREATED,
)
def start_public_upload(
    token: str,
    payload: PublicUploadRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    """A file for one of the form's file questions. Send the bytes to
    upload.url, then call complete with the returned file_token, and put
    {"file_id", "token"} in the answer."""
    ip = client_ip(request)
    enforce(f"public-upload:{ip}", FilesEnv.PUBLIC_UPLOADS_PER_MINUTE_PER_IP, 60)
    enforce(f"public-upload:{token}:{ip}", FilesEnv.PUBLIC_UPLOADS_PER_HOUR_PER_FORM_IP, 3600)
    return service.start_upload(db, token=token, payload=payload)


@router.post("/forms/{token}/uploads/{file_id}/complete", response_model=FileRead)
def complete_public_upload(
    token: str,
    file_id: int,
    payload: PublicCompleteRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    enforce(f"public-upload-complete:{client_ip(request)}", FilesEnv.PUBLIC_UPLOADS_PER_MINUTE_PER_IP * 2, 60)
    return service.complete_upload(db, token=token, file_id=file_id, file_token=payload.file_token)
