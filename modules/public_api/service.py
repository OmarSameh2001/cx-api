from datetime import datetime, timezone

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.customers import repository as customers_repository
from modules.customers.model import Customer
from modules.forms import repository as forms_repository
from modules.forms.model import Form
from modules.submissions import repository as submissions_repository
from modules.submissions.answer_rules import validate_answer_values
from modules.submissions.model import Submission
from modules.submissions.service import (
    _prune_to_path,
    _score,
    _validate_required,
    _visited_section_ids,
)

from .dto import PublicCustomer, PublicSubmitRequest


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


def _resolve_customer(db: Session, form: Form, provided: PublicCustomer) -> Customer:
    """The form organisation's customer with this email, or a new one. An
    existing record is never changed: what was typed this time is kept on the
    submission (see submit_public). Staged, not committed."""
    existing = customers_repository.get_by_email(
        db, organisation_id=form.organisation_id, email=provided.email
    )
    if existing is not None:
        return existing
    return customers_repository.create(
        db,
        organisation_id=form.organisation_id,
        email=provided.email,
        first_name=provided.first_name,
        last_name=provided.last_name,
        phone=provided.phone,
    )


def _contact(provided: PublicCustomer) -> dict:
    return {
        "email": provided.email.strip().lower(),
        "first_name": provided.first_name.strip(),
        "last_name": provided.last_name.strip(),
        "phone": provided.phone.strip() if provided.phone else None,
    }


def submit_public(
    db: Session, *, token: str, payload: PublicSubmitRequest
) -> Submission:
    form = _get_form_for_public(db, token)

    # Everything that can reject the answers runs before any customer is
    # touched, and the customer and the submission are committed together:
    # a rejected submission leaves nothing behind.
    visited = _visited_section_ids(form, payload.answers)
    answers = _prune_to_path(form, payload.answers, visited)
    validate_answer_values(form, answers)
    _validate_required(form, answers, visited)

    customer = _resolve_customer(db, form, payload.customer)
    used = submissions_repository.count_finalized_attempts(
        db, form_id=form.id, user_id=None, customer_id=customer.id
    )
    if form.max_attempts is not None and used >= form.max_attempts:
        db.rollback()
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You have already submitted this form the maximum allowed times ({form.max_attempts})",
        )
    score = _score(form, answers, visited)

    submission = Submission(
        form_id=form.id,
        customer_id=customer.id,
        user_id=None,
        contact=_contact(payload.customer),
        answers=answers,
        status="submitted",
        attempt_number=used + 1,
        submitted_at=datetime.now(timezone.utc),
        score=score,
    )
    db.add(submission)
    db.commit()
    db.refresh(submission)
    return submission
