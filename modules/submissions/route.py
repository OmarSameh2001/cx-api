from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.dto import Page
from db import get_db
from modules.auth.dto import Principal
from modules.auth.route import current_principal

from . import controller
from .dto import (
    SubmissionDetail,
    SubmissionDraftUpdate,
    SubmissionFinalize,
    SubmissionRead,
    SubmissionStartRequest,
)


router = APIRouter(prefix="/submissions", tags=["submissions"])


def _parse_status_in(status_in: Optional[str]) -> Optional[list[str]]:
    if not status_in:
        return None
    parts = [p.strip() for p in status_in.split(",") if p.strip()]
    allowed = {"in_progress", "submitted", "late", "expired"}
    return [p for p in parts if p in allowed] or None


@router.get("", response_model=Page[SubmissionRead])
def list_submissions(
    form_id: Optional[int] = Query(default=None),
    mine_only: bool = Query(default=False),
    status_in: Optional[str] = Query(
        default=None, description="Comma-separated statuses to filter by"
    ),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.list_submissions(
        db,
        principal=principal,
        form_id=form_id,
        mine_only=mine_only,
        status_in=_parse_status_in(status_in),
        limit=limit,
        offset=offset,
    )


@router.get("/mine", response_model=Page[SubmissionRead])
def list_my_submissions(
    form_id: Optional[int] = Query(default=None),
    status_in: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.list_submissions(
        db,
        principal=principal,
        form_id=form_id,
        mine_only=True,
        status_in=_parse_status_in(status_in),
        limit=limit,
        offset=offset,
    )


@router.post(
    "/start", response_model=SubmissionRead, status_code=status.HTTP_201_CREATED
)
def start_submission(
    payload: SubmissionStartRequest,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.start_submission(db, payload, principal)


@router.patch("/{submission_id}/draft", response_model=SubmissionRead)
def save_draft(
    submission_id: int,
    payload: SubmissionDraftUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.save_draft(db, submission_id, payload, principal)


@router.post("/{submission_id}/submit", response_model=SubmissionRead)
def submit_submission(
    submission_id: int,
    payload: SubmissionFinalize,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.submit_submission(db, submission_id, payload, principal)


@router.post("/{submission_id}/reveal", response_model=SubmissionRead)
def reveal_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.reveal_submission(db, submission_id, principal)


@router.get("/{submission_id}/detail", response_model=SubmissionDetail)
def get_submission_detail(
    submission_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.get_submission_detail(db, submission_id, principal)


@router.get("/{submission_id}", response_model=SubmissionRead)
def get_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.get_submission(db, submission_id, principal)


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    controller.delete_submission(db, submission_id, principal)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
