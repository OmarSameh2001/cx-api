from fastapi import APIRouter, Depends, Request, status
from sqlalchemy.orm import Session

from common.rate_limit import client_ip, enforce
from db import get_db

from . import service
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
    return PublicForm.model_validate(service.get_public_form(db, token))


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
