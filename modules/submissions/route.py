from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from db import get_db
from modules.auth.dto import Principal
from modules.auth.route import current_principal

from . import controller
from .dto import SubmissionCreate, SubmissionRead, SubmissionUpdate


router = APIRouter(prefix="/submissions", tags=["submissions"])


@router.get("", response_model=list[SubmissionRead])
def list_submissions(
    form_id: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.list_submissions(
        db,
        principal_type=principal.principal,
        principal_id=principal.id,
        form_id=form_id,
        limit=limit,
        offset=offset,
    )


@router.get("/{submission_id}", response_model=SubmissionRead)
def get_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.get_submission(
        db, submission_id, principal.principal, principal.id
    )


@router.post("", response_model=SubmissionRead, status_code=status.HTTP_201_CREATED)
def create_submission(
    payload: SubmissionCreate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.create_submission(
        db, payload, principal.principal, principal.id
    )


@router.patch("/{submission_id}", response_model=SubmissionRead)
def update_submission(
    submission_id: int,
    payload: SubmissionUpdate,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.update_submission(
        db, submission_id, payload, principal.principal, principal.id
    )


@router.delete("/{submission_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_submission(
    submission_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    controller.delete_submission(
        db, submission_id, principal.principal, principal.id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
