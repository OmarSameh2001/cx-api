from typing import Optional

from fastapi import APIRouter, Depends, Query, Request, status
from sqlalchemy.orm import Session

from common.rate_limit import client_ip, enforce
from config import FilesEnv
from db import get_db

from . import controller
from modules.files.dto import (
    EffectiveLimitsRead,
    FileRead,
    PublicCompleteRequest,
    PublicUploadRequest,
    UploadStartResponse,
)

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


router = APIRouter(prefix="/public", tags=["public"])

# Public endpoints take no login, so they are rate limited instead: per
# client IP, and per form + email (or browser, on anonymous forms) so one
# identity can't be hammered (or have its attempts used up) from many addresses.
FORM_LOADS_PER_MINUTE = 60
SUBMITS_PER_MINUTE_PER_IP = 10
SUBMITS_PER_HOUR_PER_EMAIL = 5
DRAFT_SAVES_PER_MINUTE_PER_IP = 30


@router.get("/forms/{token}", response_model=PublicForm)
def get_public_form(
    token: str,
    request: Request,
    attempt: Optional[str] = Query(default=None, max_length=512),
    prefill: Optional[str] = Query(default=None, max_length=8192),
    db: Session = Depends(get_db),
):
    """`attempt`: the token an earlier load returned, so a reload keeps the
    shuffled order. `prefill`: a signed prefilled link's token."""
    enforce(f"public-load:{client_ip(request)}", FORM_LOADS_PER_MINUTE, 60)
    return controller.get_form(db, token, attempt=attempt, prefill=prefill)


@router.post(
    "/forms/{token}/submit",
    response_model=PublicSubmitResponse,
    response_model_exclude_none=True,
    status_code=status.HTTP_201_CREATED,
)
def submit_public_form(
    token: str,
    payload: PublicSubmitRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    ip = client_ip(request)
    enforce(f"public-submit:{ip}", SUBMITS_PER_MINUTE_PER_IP, 60)
    who = payload.customer.email.strip().lower() if payload.customer else payload.device_id
    if who:
        enforce(f"public-submit:{token}:{who}", SUBMITS_PER_HOUR_PER_EMAIL, 3600)
    return controller.submit(db, token, payload, ip=ip)


# --- save and continue later (T2.2.5) ---------------------------------------------


@router.post("/forms/{token}/drafts", response_model=PublicDraftRead, status_code=status.HTTP_201_CREATED)
def save_public_draft(token: str, payload: PublicDraftSave, request: Request, db: Session = Depends(get_db)):
    """Saves the answers so far; come back with ?resume=<resume_token>."""
    ip = client_ip(request)
    enforce(f"public-submit:{ip}", SUBMITS_PER_MINUTE_PER_IP, 60)
    return controller.save_draft(db, token, payload, ip=ip)


@router.get("/forms/{token}/drafts/{resume_token}", response_model=PublicDraft)
def get_public_draft(token: str, resume_token: str, request: Request, db: Session = Depends(get_db)):
    enforce(f"public-load:{client_ip(request)}", FORM_LOADS_PER_MINUTE, 60)
    return controller.get_draft(db, token, resume_token)


@router.put("/forms/{token}/drafts/{resume_token}", response_model=PublicDraftRead)
def update_public_draft(
    token: str, resume_token: str, payload: PublicDraftUpdate, request: Request, db: Session = Depends(get_db)
):
    enforce(f"public-draft:{client_ip(request)}", DRAFT_SAVES_PER_MINUTE_PER_IP, 60)
    return controller.update_draft(db, token, resume_token, payload)


# --- changing a submitted response (T2.2.11) --------------------------------------


@router.get("/forms/{token}/responses/{edit_token}", response_model=PublicResponse)
def get_public_response(token: str, edit_token: str, request: Request, db: Session = Depends(get_db)):
    enforce(f"public-load:{client_ip(request)}", FORM_LOADS_PER_MINUTE, 60)
    return controller.get_response(db, token, edit_token)


@router.put(
    "/forms/{token}/responses/{edit_token}",
    response_model=PublicSubmitResponse,
    response_model_exclude_none=True,
)
def edit_public_response(
    token: str, edit_token: str, payload: PublicEditRequest, request: Request, db: Session = Depends(get_db)
):
    enforce(f"public-submit:{client_ip(request)}", SUBMITS_PER_MINUTE_PER_IP, 60)
    return controller.edit_response(db, token, edit_token, payload)


# --- uploads ----------------------------------------------------------------------


@router.get("/forms/{token}/fields/{field_id}/limits", response_model=EffectiveLimitsRead)
def public_question_limits(token: str, field_id: int, request: Request, db: Session = Depends(get_db)):
    """What a file question accepts, so the browser can check and compress
    before uploading."""
    enforce(f"public-load:{client_ip(request)}", FORM_LOADS_PER_MINUTE, 60)
    return controller.question_limits(db, token, field_id)


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
    return controller.start_upload(db, token, payload)


@router.post("/forms/{token}/uploads/{file_id}/complete", response_model=FileRead)
def complete_public_upload(
    token: str,
    file_id: int,
    payload: PublicCompleteRequest,
    request: Request,
    db: Session = Depends(get_db),
):
    enforce(f"public-upload-complete:{client_ip(request)}", FilesEnv.PUBLIC_UPLOADS_PER_MINUTE_PER_IP * 2, 60)
    return controller.complete_upload(db, token, file_id, payload.file_token)
