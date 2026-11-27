import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import AppError
from common.services import captcha
from config import FormsEnv
from modules.customers import repository as customers_repository
from modules.customers.model import Customer
from modules.forms import behaviour
from modules.forms import repository as forms_repository
from modules.forms.model import Form, PublishedForm
from modules.forms.service import as_answered, published
from modules.submissions import repository as submissions_repository
from modules.files.service import PublicActor
from modules.submissions import service as submissions_service
from modules.submissions.answer_rules import validate_answer_values
from modules.submissions.dto import EndingRead
from modules.submissions.model import Submission
from modules.submissions.service import (
    GRACE,
    _answerable_ids,
    _prune_to_path,
    _validate_required,
    grade_path,
    path_of,
    record_results,
)

from .dto import (
    CaptchaWidget,
    PublicCustomer,
    PublicDraft,
    PublicDraftCustomer,
    PublicDraftRead,
    PublicDraftSave,
    PublicDraftUpdate,
    PublicEditRequest,
    PublicForm,
    PublicResponse,
    PublicSubmitRequest,
    PublicSubmitResponse,
)


def _now() -> datetime:
    return datetime.now(timezone.utc)


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


# --- what the respondent is served -------------------------------------------------


def _serve(db: Session, view, *, order: Optional[dict] = None, hidden: Optional[dict] = None) -> PublicForm:
    """A version as respondents get it, with the settings they need, the
    attempt's order and what its logic needs."""
    from modules.forms import logic
    from modules.forms.service import media_for

    s = behaviour.settings_of(view)
    read = logic.for_respondent(PublicForm.model_validate(view), view, hidden)
    behaviour.apply_order(read.fields, order)
    window = behaviour.edit_window(view)
    widget = captcha.widget() if s.captcha else None
    return read.model_copy(update={
        "media": media_for(db, view),
        "opens_at": s.opens_at,
        "closes_at": s.closes_at,
        "anonymous": behaviour.is_anonymous(view),
        "allow_resume": s.allow_resume,
        "show_progress": s.show_progress,
        "edit_window_minutes": int(window.total_seconds() // 60) if window else None,
        "captcha": CaptchaWidget(**widget) if widget else None,
    })


def public_form_read(
    db: Session, token: str, *, attempt: Optional[str] = None, prefill: Optional[str] = None
) -> PublicForm:
    """The form behind a public link, with links to its pictures. Outside its
    dates it comes without questions, saying why (T2.2.1)."""
    view = _get_form_for_public(db, token)
    state = behaviour.availability(view)
    if state != behaviour.OPEN:
        s = behaviour.settings_of(view)
        return PublicForm(
            id=view.id, name=view.name, description=view.description, type=view.type,
            theme=s.theme, availability=state, opens_at=s.opens_at, closes_at=s.closes_at,
            closed_message=s.closed_message,
        )
    filled = submissions_service.prefilled(view, view, prefill, code="public_forms.prefill_invalid")
    seed = behaviour.seed_from_attempt(view.id, attempt)
    seed = seed if seed is not None else behaviour.new_seed()
    order = behaviour.shuffled_order(view, seed)
    read = _serve(db, view, order=order, hidden=filled.hidden if filled else None)
    return read.model_copy(update={
        "attempt": behaviour.attempt_token(view.id, seed) if order else None,
        "prefill_answers": filled.answers if filled else {},
    })


# --- checks --------------------------------------------------------------------------


def _check_captcha(form, token: Optional[str], ip: Optional[str]) -> None:
    if not behaviour.settings_of(form).captcha or not captcha.is_enabled():
        return
    try:
        ok = captcha.verify(token, ip)
    except captcha.CaptchaUnavailable:
        raise AppError(503, "public_forms.captcha_unavailable") from None
    if not ok:
        raise AppError(422, "public_forms.captcha_failed")


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


def _draft_contact(provided: Optional[PublicDraftCustomer]) -> Optional[dict]:
    if provided is None:
        return None
    data = {k: (v.strip() if isinstance(v, str) else v) for k, v in provided.model_dump().items()}
    return {k: v for k, v in data.items() if v} or None


def _anonymous_key(form, device_id: Optional[str]) -> str:
    """Who an anonymous respondent is to this form: their browser's id, or a
    one-off when there is none (then nothing ties two responses together)."""
    if device_id:
        return behaviour.respondent_key(form.id, "device", device_id)
    return behaviour.respondent_key(form.id, "once", uuid.uuid4().hex)


def _order_for(view, attempt: Optional[str]) -> Optional[dict]:
    seed = behaviour.seed_from_attempt(view.id, attempt)
    return behaviour.shuffled_order(view, seed) if seed is not None else None


# --- submitting ------------------------------------------------------------------------


def submit_public(
    db: Session, *, token: str, payload: PublicSubmitRequest, ip: Optional[str] = None
) -> tuple[Submission, Any]:
    """A finished response, new or from a saved draft. Returns the
    submission, the ending it earned and the live form."""
    live = _get_form_for_public(db, token)
    behaviour.ensure_taking_responses(live, prefix="public_forms", grace=GRACE)
    draft = _load_draft(db, live, payload.resume_token) if payload.resume_token else None
    # a draft is answered against the version it was started on
    form = as_answered(draft) if draft is not None else live
    anonymous = behaviour.is_anonymous(live)
    if not anonymous and payload.customer is None:
        raise AppError(422, "public_forms.details_required")
    if anonymous and behaviour.max_attempts(live) is not None and not payload.device_id and draft is None:
        raise AppError(422, "public_forms.device_required")
    if draft is None:
        # a draft passed the check when it was saved
        _check_captcha(live, payload.captcha_token, ip)
        prefill = submissions_service.prefilled(live, form, payload.prefill, code="public_forms.prefill_invalid")
    else:
        prefill = None

    # Everything that can reject the answers runs before any customer is
    # touched, and the customer and the submission are committed together:
    # a rejected submission leaves nothing behind.
    hidden = draft.hidden_fields if draft is not None else (prefill.hidden if prefill else None)
    path = path_of(form, payload.answers, hidden)
    answers = _prune_to_path(form, payload.answers, path)
    validate_answer_values(form, answers)
    _validate_required(form, answers, path)
    actor = PublicActor(form_id=live.id)
    if draft is not None:
        answers, files_used = submissions_service.resolve_keeping_stored(
            db, form, answers, stored=draft.answers, actor=actor, submission_id=draft.id,
        )
    else:
        answers, files_used = submissions_service.resolve_file_answers(
            db, form, answers, actor=actor, submission_id=None
        )

    customer = None
    if anonymous:
        key = draft.respondent_key if draft is not None and draft.respondent_key else _anonymous_key(live, payload.device_id)
        used = submissions_repository.count_finalized_attempts(
            db, form_id=live.id, user_id=None, customer_id=None, respondent_key=key,
        )
    else:
        key = None
        customer = _resolve_customer(db, live, payload.customer)
        used = submissions_repository.count_finalized_attempts(
            db, form_id=live.id, user_id=None, customer_id=customer.id
        )
    try:
        submissions_service.raise_if_over_quota(live, used, prefix="public_forms")
    except AppError:
        db.rollback()
        raise
    result = grade_path(form, answers, path)

    now = _now()
    if draft is not None:
        submission = draft
        submission.expires_at = None
    else:
        submission = Submission(
            form_id=live.id,
            form_version_id=live.version_id,
            started_at=now,
            hidden_fields=(prefill.hidden or None) if prefill else None,
            question_order=_order_for(live, payload.attempt),
        )
        db.add(submission)
    submission.customer_id = customer.id if customer is not None else None
    submission.user_id = None
    # anonymous: no name, no email, nothing to tell who answered (T2.2.8)
    submission.contact = _contact(payload.customer) if customer is not None else None
    submission.respondent_key = key
    submission.answers = answers
    submission.status = "submitted"
    submission.attempt_number = used + 1
    submission.submitted_at = now
    db.flush()  # the event and the answer rows need the id; all are committed together
    # no unit yet: a public link doesn't say which branch it's about (T2.5.1)
    record_results(db, submission, form, result, unit_id=None)
    submissions_service.attach_answer_files(db, submission, files_used, form)
    submissions_service.emit_finalized_events(db, submission, form)
    ending = behaviour.pick_ending(form, score=submission.score, last_section_id=path.last_section_id)
    db.commit()
    db.refresh(submission)
    return submission, ending, live


def submit_response(submission: Submission, ending, form) -> PublicSubmitResponse:
    until = behaviour.editable_until(form, submission)
    return PublicSubmitResponse(
        submission_id=submission.id,
        ending=EndingRead.model_validate(ending) if ending else None,
        edit_token=behaviour.edit_token(submission) if until else None,
        editable_until=until,
    )


# --- save and continue later (T2.2.5) -------------------------------------------------


def _draft_expiry() -> datetime:
    return _now() + timedelta(days=FormsEnv.PUBLIC_DRAFT_TTL_DAYS)


def _load_by_token(db: Session, form, link_token: Optional[str], purpose: str) -> Submission:
    """The public submission a resume or edit link names, on this form only.
    A token for another form, a forged one and a missing row all read the same."""
    code = "public_forms.draft_not_found" if purpose == "resume" else "public_forms.response_not_found"
    submission_id = behaviour.token_submission_id(link_token)
    submission = submissions_repository.get_submission(db, submission_id) if submission_id else None
    if (
        submission is None
        or submission.form_id != form.id
        or submission.user_id is not None
        or not behaviour.token_matches(link_token, purpose, submission)
    ):
        raise AppError(404, code)
    return submission


def _load_draft(db: Session, form, resume_token: Optional[str]) -> Submission:
    draft = _load_by_token(db, form, resume_token, "resume")
    if submissions_service._check_and_apply_expiry(db, draft) or draft.status == "expired":
        raise AppError(409, "public_forms.draft_expired")
    if draft.status != "in_progress":
        raise AppError(409, "public_forms.draft_finished")
    return draft


def _ensure_resume_allowed(form) -> None:
    if not behaviour.settings_of(form).allow_resume:
        raise AppError(409, "public_forms.resume_off")


def _draft_answers(form, answers: dict[str, Any]) -> dict[str, Any]:
    known = _answerable_ids(form)
    kept = {k: v for k, v in (answers or {}).items() if k in known}
    validate_answer_values(form, kept, draft=True)
    return kept


def save_draft(
    db: Session, *, token: str, payload: PublicDraftSave, ip: Optional[str] = None
) -> PublicDraftRead:
    form = _get_form_for_public(db, token)
    _ensure_resume_allowed(form)
    behaviour.ensure_taking_responses(form, prefix="public_forms")
    _check_captcha(form, payload.captcha_token, ip)
    prefill = submissions_service.prefilled(form, form, payload.prefill, code="public_forms.prefill_invalid")
    answers = _draft_answers(form, payload.answers)
    anonymous = behaviour.is_anonymous(form)

    now = _now()
    draft = Submission(
        form_id=form.id,
        form_version_id=form.version_id,
        status="in_progress",
        attempt_number=1,
        started_at=now,
        expires_at=_draft_expiry(),
        answers={},
        contact=None if anonymous else _draft_contact(payload.customer),
        respondent_key=_anonymous_key(form, payload.device_id) if anonymous else None,
        hidden_fields=(prefill.hidden or None) if prefill else None,
        question_order=_order_for(form, payload.attempt),
    )
    db.add(draft)
    db.flush()  # files are attached to it by id
    draft.answers, used = submissions_service.resolve_file_answers(
        db, form, answers, actor=PublicActor(form_id=form.id), submission_id=draft.id,
    )
    submissions_service.attach_answer_files(db, draft, used, form)
    db.commit()
    db.refresh(draft)
    return PublicDraftRead(resume_token=behaviour.resume_token(draft), expires_at=draft.expires_at)


def get_draft(db: Session, *, token: str, resume_token: str) -> PublicDraft:
    live = _get_form_for_public(db, token)
    _ensure_resume_allowed(live)
    draft = _load_draft(db, live, resume_token)
    view = as_answered(draft)
    contact = draft.contact if not behaviour.is_anonymous(live) else None
    return PublicDraft(
        form=_serve(db, view, order=draft.question_order, hidden=draft.hidden_fields),
        answers=draft.answers or {},
        customer=PublicDraftCustomer(**contact) if contact else None,
        expires_at=draft.expires_at,
    )


def update_draft(
    db: Session, *, token: str, resume_token: str, payload: PublicDraftUpdate
) -> PublicDraftRead:
    """Replaces the draft's answers (and details) with these; the link stays the same."""
    live = _get_form_for_public(db, token)
    _ensure_resume_allowed(live)
    behaviour.ensure_taking_responses(live, prefix="public_forms")
    draft = _load_draft(db, live, resume_token)
    form = as_answered(draft)
    answers = _draft_answers(form, payload.answers)
    answers, used = submissions_service.resolve_keeping_stored(
        db, form, answers, stored=draft.answers, actor=PublicActor(form_id=live.id), submission_id=draft.id,
    )
    submissions_service.attach_answer_files(db, draft, used, form)
    draft.answers = answers
    if not behaviour.is_anonymous(live):
        draft.contact = _draft_contact(payload.customer)
    draft.expires_at = _draft_expiry()
    db.commit()
    return PublicDraftRead(resume_token=resume_token, expires_at=draft.expires_at)


# --- changing a submitted response (T2.2.11) ------------------------------------------


def _load_editable(db: Session, form, edit_link: str) -> Submission:
    submission = _load_by_token(db, form, edit_link, "edit")
    if submission.status not in ("submitted", "late") or behaviour.editable_until(submission.form, submission) is None:
        raise AppError(409, "submissions.not_editable")
    if not behaviour.can_edit(submission.form, submission):
        raise AppError(409, "submissions.edit_window_over")
    return submission


def get_response(db: Session, *, token: str, edit_token: str) -> PublicResponse:
    live = _get_form_for_public(db, token)
    submission = _load_editable(db, live, edit_token)
    return PublicResponse(
        form=_serve(db, as_answered(submission), order=submission.question_order, hidden=submission.hidden_fields),
        answers=submission.answers or {},
        editable_until=behaviour.editable_until(submission.form, submission),
    )


def edit_response(db: Session, *, token: str, edit_token: str, payload: PublicEditRequest) -> PublicSubmitResponse:
    live = _get_form_for_public(db, token)
    submission = _load_editable(db, live, edit_token)
    submissions_service.apply_edit(db, submission, payload.answers, actor=PublicActor(form_id=live.id))
    db.commit()
    db.refresh(submission)
    return submit_response(submission, submissions_service.ending_for(submission), live)


# --- uploads --------------------------------------------------------------------------


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
