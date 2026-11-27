from datetime import datetime, timezone

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import AppError
from modules.customers import repository as customers_repository
from modules.customers.model import Customer
from modules.forms import repository as forms_repository
from modules.forms.model import Form, PublishedForm
from modules.forms.service import published
from modules.submissions import repository as submissions_repository
from modules.files.service import PublicActor
from modules.submissions import service as submissions_service
from modules.submissions.answer_rules import validate_answer_values
from modules.submissions.model import Submission
from modules.submissions.service import (
    _prune_to_path,
    _validate_required,
    _visited_section_ids,
    grade,
    record_results,
)

from .dto import PublicCustomer, PublicForm, PublicSubmitRequest


def _get_form_for_public(db: Session, token: str) -> PublishedForm:
    """The form behind a public link, as its current version: respondents
    always answer what was last published, never the draft."""
    form = forms_repository.get_form_by_token(db, token)
    if form is None:
        raise AppError(404, "forms.not_found")
    if form.is_archived or not form.is_active:
        raise AppError(409, "public_forms.closed")
    if form.type != "questionnaire":
        raise AppError(403, "public_forms.no_public_link")
    if "customer" not in (form.submitter_type or []):
        raise AppError(403, "public_forms.no_customers")
    view = published(form)
    if view is None:
        raise AppError(409, "public_forms.closed")
    return view


def get_public_form(db: Session, token: str) -> PublishedForm:
    return _get_form_for_public(db, token)


def public_form_read(db: Session, token: str) -> PublicForm:
    """The form behind a public link, with links to its pictures."""
    from modules.forms.service import media_for

    view = _get_form_for_public(db, token)
    return PublicForm.model_validate(view).model_copy(update={"media": media_for(db, view)})


def _resolve_customer(db: Session, form: Form, provided: PublicCustomer) -> Customer:
    """The form organisation's customer with this email, or a new one. An
    existing record is never changed: what was typed this time is kept on the
    submission (see submit_public). Staged, not committed."""
    existing = customers_repository.get_by_email(
        db, organisation_id=form.organisation_id, email=provided.email
    )
    if existing is not None:
        return existing
    try:
        return customers_repository.create(
            db,
            organisation_id=form.organisation_id,
            email=provided.email,
            first_name=provided.first_name,
            last_name=provided.last_name,
            phone=provided.phone,
        )
    except IntegrityError:
        # a first submission with the same email committed just before ours
        existing = customers_repository.get_by_email(
            db, organisation_id=form.organisation_id, email=provided.email
        )
        if existing is None:
            raise
        return existing


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
    answers, files_used = submissions_service.resolve_file_answers(
        db, form, answers, actor=PublicActor(form_id=form.id), submission_id=None
    )

    customer = _resolve_customer(db, form, payload.customer)
    used = submissions_repository.count_finalized_attempts(
        db, form_id=form.id, user_id=None, customer_id=customer.id
    )
    if form.max_attempts is not None and used >= form.max_attempts:
        db.rollback()
        raise AppError(409, "public_forms.max_attempts", max_attempts=form.max_attempts)
    result = grade(form, answers, visited)

    submission = Submission(
        form_id=form.id,
        form_version_id=form.version_id,
        customer_id=customer.id,
        user_id=None,
        contact=_contact(payload.customer),
        answers=answers,
        status="submitted",
        attempt_number=used + 1,
        submitted_at=datetime.now(timezone.utc),
    )
    db.add(submission)
    db.flush()  # the event and the answer rows need the id; all are committed together
    # no unit yet: a public link doesn't say which branch it's about (T2.5.1)
    record_results(db, submission, form, result, unit_id=None)
    submissions_service.attach_answer_files(db, submission, files_used, form)
    submissions_service.emit_finalized_events(db, submission, form)
    db.commit()
    db.refresh(submission)
    return submission


def start_upload(db: Session, *, token: str, payload):
    """A respondent's file for one of the form's file questions."""
    from modules.files import controller as files_controller

    form = _get_form_for_public(db, token)
    return files_controller.start_public_upload(db, form.id, payload)


def question_limits(db: Session, *, token: str, field_id: int):
    from modules.files import controller as files_controller

    form = _get_form_for_public(db, token)
    return files_controller.public_question_limits(db, form_id=form.id, field_id=field_id)


def complete_upload(db: Session, *, token: str, file_id: int, file_token: str):
    from modules.files import controller as files_controller
    from modules.files.service import PublicActor

    form = _get_form_for_public(db, token)
    return files_controller.complete_upload(db, file_id, PublicActor(form_id=form.id, token=file_token))
