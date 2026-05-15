from fastapi import APIRouter, Depends, status
from sqlalchemy.orm import Session

from db import get_db

from . import service
from .dto import PublicForm, PublicSubmitRequest, PublicSubmitResponse


router = APIRouter(prefix="/public", tags=["public"])


@router.get("/forms/{token}", response_model=PublicForm)
def get_public_form(token: str, db: Session = Depends(get_db)):
    return PublicForm.model_validate(service.get_public_form(db, token))


@router.post(
    "/forms/{token}/submit",
    response_model=PublicSubmitResponse,
    status_code=status.HTTP_201_CREATED,
)
def submit_public_form(
    token: str,
    payload: PublicSubmitRequest,
    db: Session = Depends(get_db),
):
    submission, customer, created = service.submit_public(
        db, token=token, payload=payload
    )
    return PublicSubmitResponse(
        submission_id=submission.id,
        customer_id=customer.id,
        created_customer=created,
    )
