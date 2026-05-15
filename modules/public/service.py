from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.customers.model import Customer
from modules.forms import repository as forms_repository
from modules.forms.model import Form
from modules.submissions import repository as submissions_repository
from modules.submissions.model import Submission
from modules.submissions.service import _score, _validate_required

from .dto import PublicCustomer, PublicSubmitRequest


def _normalize_text(v: Optional[str]) -> str:
    return (v or "").strip().lower()


def _normalize_phone(v: Optional[str]) -> str:
    if not v:
        return ""
    return "".join(ch for ch in v if ch.isdigit() or ch == "+")


def _get_form_for_public(db: Session, token: str) -> Form:
    form = forms_repository.get_form_by_token(db, token)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    if form.is_archived or not form.is_active:
        raise HTTPException(status.HTTP_409_CONFLICT, "Form is not accepting submissions")
    if form.type != "questionnaire":
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This form is not available via public link"
        )
    if "customer" not in (form.submitter_type or []):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "This form does not accept customer submissions"
        )
    return form


def get_public_form(db: Session, token: str) -> Form:
    return _get_form_for_public(db, token)


def _find_customer_by_email(db: Session, email: str) -> Optional[Customer]:
    stmt = select(Customer).where(func.lower(Customer.email) == email.strip().lower())
    return db.execute(stmt).scalar_one_or_none()


def _match_or_reject(existing: Customer, provided: PublicCustomer) -> None:
    if _normalize_text(existing.first_name) != _normalize_text(provided.first_name):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A customer with this email already exists with a different first name",
        )
    if _normalize_text(existing.last_name) != _normalize_text(provided.last_name):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "A customer with this email already exists with a different last name",
        )
    if provided.phone:
        existing_phone = _normalize_phone(existing.phone)
        provided_phone = _normalize_phone(provided.phone)
        if existing_phone and existing_phone != provided_phone:
            raise HTTPException(
                status.HTTP_409_CONFLICT,
                "A customer with this email already exists with a different phone",
            )


def _resolve_customer(
    db: Session, provided: PublicCustomer
) -> tuple[Customer, bool]:
    existing = _find_customer_by_email(db, provided.email)
    if existing is not None:
        _match_or_reject(existing, provided)
        # Optionally backfill phone if the existing record has none.
        if provided.phone and not existing.phone:
            existing.phone = provided.phone
            db.commit()
            db.refresh(existing)
        return existing, False

    customer = Customer(
        first_name=provided.first_name.strip(),
        last_name=provided.last_name.strip(),
        email=provided.email.strip().lower(),
        phone=provided.phone.strip() if provided.phone else None,
    )
    db.add(customer)
    db.commit()
    db.refresh(customer)
    return customer, True


def submit_public(
    db: Session, *, token: str, payload: PublicSubmitRequest
) -> tuple[Submission, Customer, bool]:
    form = _get_form_for_public(db, token)
    customer, created = _resolve_customer(db, payload.customer)

    used = submissions_repository.count_finalized_attempts(
        db, form_id=form.id, user_id=None, customer_id=customer.id
    )
    if form.max_attempts is not None and used >= form.max_attempts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You have already submitted this form the maximum allowed times ({form.max_attempts})",
        )

    _validate_required(form, payload.answers)
    score = _score(form, payload.answers)

    submission = Submission(
        form_id=form.id,
        customer_id=customer.id,
        user_id=None,
        answers=payload.answers,
        status="submitted",
        attempt_number=used + 1,
        submitted_at=datetime.now(timezone.utc),
        score=score,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission, customer, created
