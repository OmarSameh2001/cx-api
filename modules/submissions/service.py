from datetime import datetime, timedelta, timezone
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.auth.dto import EmployeePrincipal, Principal
from modules.forms import repository as forms_repository
from modules.forms.model import Form, FormField

from . import repository
from .dto import (
    SubmissionDetail,
    SubmissionDetailField,
    SubmissionRead,
)
from .model import Submission


GRACE = timedelta(seconds=30)
AUTO_GRADABLE = {"single_choice", "multi_choice", "boolean"}


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _normalize_multi(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        return {part.strip() for part in value.split(",") if part.strip()}
    if isinstance(value, (list, tuple, set)):
        return {str(v).strip() for v in value if str(v).strip()}
    return {str(value).strip()}


def _is_correct(field: FormField, answer: Any) -> bool:
    if field.right_answer is None:
        return False
    if field.type == "multi_choice":
        return _normalize_multi(answer) == _normalize_multi(field.right_answer)
    if field.type == "boolean":
        return str(answer).strip().lower() == field.right_answer.strip().lower()
    if field.type == "single_choice":
        return str(answer).strip() == field.right_answer.strip()
    return False


def _required_missing(field: FormField, answers: dict[str, Any]) -> bool:
    if not field.is_required:
        return False
    provided = answers.get(str(field.id))
    if provided is None:
        return True
    if isinstance(provided, str) and provided == "":
        return True
    if isinstance(provided, (list, tuple, set)) and len(provided) == 0:
        return True
    return False


def _validate_required(form: Form, answers: dict[str, Any]) -> None:
    for field in form.fields:
        if _required_missing(field, answers):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Field {field.id} ({field.question}) is required",
            )


def _score(form: Form, answers: dict[str, Any]) -> float:
    """Score auto-gradable fields. Text/file/etc. contribute 0 (manual grading)."""
    total = 0.0
    for field in form.fields:
        if field.type not in AUTO_GRADABLE:
            continue
        provided = answers.get(str(field.id))
        if provided is None:
            continue
        if _is_correct(field, provided):
            total += field.score_weight
    return total


def _ensure_submitter_allowed(form: Form, principal_type: str) -> None:
    if not form.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Form is not accepting submissions"
        )
    if form.is_archived:
        raise HTTPException(status.HTTP_409_CONFLICT, "Form is archived")
    if principal_type not in (form.submitter_type or []):
        raise HTTPException(
            status.HTTP_403_FORBIDDEN,
            f"{principal_type}s are not allowed to submit this form",
        )


def _ensure_user_can_access_form(form: Form, principal: Principal) -> None:
    """Unit-targeting check. Customers have no unit; if the form is unit-targeted,
    customers see only forms with empty/null assigned_to_units."""
    if isinstance(principal, EmployeePrincipal):
        if form.organisation_id != principal.organisation_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
        assigned = form.assigned_to_units or []
        if not assigned:
            return
        unit_ids = set(principal.assigned_unit_ids or [])
        if principal.unit_id is not None:
            unit_ids.add(principal.unit_id)
        if not (unit_ids & set(assigned)):
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Form is not assigned to your unit"
            )
    else:
        # customer: no unit gating, only submitter_type gates them
        if form.assigned_to_units:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "Form is not assigned to you"
            )


def _principal_ids(principal: Principal) -> tuple[Optional[int], Optional[int]]:
    """Return (user_id, customer_id) tuple for the principal."""
    if principal.principal == "employee":
        return principal.id, None
    return None, principal.id


def _ensure_owner(submission: Submission, principal: Principal) -> None:
    user_id, customer_id = _principal_ids(principal)
    if user_id is not None and submission.user_id == user_id:
        return
    if customer_id is not None and submission.customer_id == customer_id:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "You can only access your own submissions"
    )


def _ensure_can_view(submission: Submission, principal: Principal) -> None:
    if isinstance(principal, EmployeePrincipal):
        # owners always can
        if submission.user_id == principal.id:
            return
        # same org + has submissions:view permission
        if submission.form is not None and submission.form.organisation_id == principal.organisation_id:
            if "submissions:view" in (principal.permissions or []):
                return
            if submission.form.created_by == principal.id:
                return
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Not allowed to view this submission"
        )
    _ensure_owner(submission, principal)


def _ensure_in_progress(submission: Submission) -> None:
    if submission.status != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"Submission is {submission.status}; cannot be modified",
        )


def _check_and_apply_expiry(
    db: Session, submission: Submission
) -> bool:
    """If session is in_progress past expiry+grace, flip to expired & commit.
    Returns True if expired was applied."""
    if submission.status != "in_progress" or submission.expires_at is None:
        return False
    if _now() > submission.expires_at + GRACE:
        submission.status = "expired"
        repository.save(db, submission)
        return True
    return False


def _ensure_attempt_quota(
    db: Session, form: Form, principal: Principal
) -> int:
    """Return the attempt_number for the *new* attempt; raise if over quota."""
    user_id, customer_id = _principal_ids(principal)
    used = repository.count_finalized_attempts(
        db, form_id=form.id, user_id=user_id, customer_id=customer_id
    )
    if form.max_attempts is not None and used >= form.max_attempts:
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            f"You have used all {form.max_attempts} attempt(s) for this form",
        )
    return used + 1


def start_submission(
    db: Session, *, form_id: int, principal: Principal
) -> Submission:
    form = forms_repository.get_form(db, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")

    _ensure_submitter_allowed(form, principal.principal)
    _ensure_user_can_access_form(form, principal)

    user_id, customer_id = _principal_ids(principal)

    open_sub = repository.find_open_submission(
        db, form_id=form.id, user_id=user_id, customer_id=customer_id
    )
    if open_sub is not None:
        # if it has gone past expiry+grace, expire it and proceed to a fresh attempt
        if _check_and_apply_expiry(db, open_sub):
            open_sub = None
        else:
            return open_sub

    attempt_number = _ensure_attempt_quota(db, form, principal)

    expires_at: Optional[datetime] = None
    if form.type == "exam" and form.time_limit_minutes:
        expires_at = _now() + timedelta(minutes=form.time_limit_minutes)

    return repository.create_submission(
        db,
        form_id=form.id,
        user_id=user_id,
        customer_id=customer_id,
        expires_at=expires_at,
        attempt_number=attempt_number,
    )


def save_draft(
    db: Session,
    *,
    submission_id: int,
    answers: dict[str, Any],
    principal: Principal,
) -> Submission:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal)
    if _check_and_apply_expiry(db, submission):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Submission has expired; draft cannot be saved"
        )
    _ensure_in_progress(submission)
    # merge answers (partial allowed; no validation)
    merged = dict(submission.answers or {})
    merged.update(answers or {})
    submission.answers = merged
    return repository.save(db, submission)


def submit_submission(
    db: Session,
    *,
    submission_id: int,
    answers: Optional[dict[str, Any]],
    principal: Principal,
) -> Submission:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal)
    if _check_and_apply_expiry(db, submission):
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Submission has expired"
        )
    _ensure_in_progress(submission)

    if answers:
        merged = dict(submission.answers or {})
        merged.update(answers)
        submission.answers = merged

    form = submission.form
    final_answers = submission.answers or {}
    _validate_required(form, final_answers)

    now = _now()
    is_late = bool(submission.expires_at and now > submission.expires_at)
    submission.status = "late" if is_late else "submitted"
    submission.submitted_at = now
    submission.score = _score(form, final_answers)
    return repository.save(db, submission)


def get_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> Submission:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _check_and_apply_expiry(db, submission)
    _ensure_can_view(submission, principal)
    return submission


def list_submissions(
    db: Session,
    *,
    principal: Principal,
    form_id: Optional[int],
    mine_only: bool,
    status_in: Optional[list[str]],
    limit: int,
    offset: int,
) -> tuple[list[Submission], int]:
    customer_id: Optional[int] = None
    user_id: Optional[int] = None
    organisation_id: Optional[int] = None

    if isinstance(principal, EmployeePrincipal):
        can_view_all = "submissions:view" in (principal.permissions or [])
        organisation_id = principal.organisation_id
        if mine_only:
            user_id = principal.id
        elif not can_view_all:
            # form creators can see all submissions for their own form
            is_form_creator = False
            if form_id is not None:
                owned = forms_repository.get_form(db, form_id)
                is_form_creator = owned is not None and owned.created_by == principal.id
            if not is_form_creator:
                user_id = principal.id
    else:
        customer_id = principal.id

    items = repository.list_submissions(
        db,
        form_id=form_id,
        customer_id=customer_id,
        user_id=user_id,
        organisation_id=organisation_id,
        status_in=status_in,
        limit=limit,
        offset=offset,
    )
    total = repository.count_submissions(
        db,
        form_id=form_id,
        customer_id=customer_id,
        user_id=user_id,
        organisation_id=organisation_id,
        status_in=status_in,
    )
    return items, total


def reveal_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> Submission:
    if not isinstance(principal, EmployeePrincipal):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Only reviewers can reveal results")
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    form = submission.form
    if form is None or form.organisation_id != principal.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    is_creator = form.created_by == principal.id
    has_perm = "submissions:view" in (principal.permissions or [])
    if not (is_creator or has_perm):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to reveal this submission")
    submission.results_revealed = True
    return repository.save(db, submission)


def serialize_detail(
    submission: Submission, *, principal: Principal
) -> SubmissionDetail:
    """Serialize a submission for the detail endpoint, reveal-gating sensitive bits."""
    form = submission.form

    is_owner = False
    if principal.principal == "employee" and submission.user_id == principal.id:
        is_owner = True
    elif principal.principal == "customer" and submission.customer_id == principal.id:
        is_owner = True

    is_reviewer = False
    if isinstance(principal, EmployeePrincipal) and form is not None:
        if form.organisation_id == principal.organisation_id:
            is_reviewer = (
                form.created_by == principal.id
                or "submissions:view" in (principal.permissions or [])
            )

    revealed = bool(
        is_reviewer
        or (is_owner and (submission.results_revealed or (form and form.results_revealed)))
    )

    fields: list[SubmissionDetailField] = []
    if form is not None:
        for f in form.fields:
            data = SubmissionDetailField(
                id=f.id,
                order=f.order,
                type=f.type,
                is_required=f.is_required,
                score_weight=f.score_weight,
            )
            if revealed:
                data.question = f.question
                data.options = f.options
                data.right_answer = f.right_answer
                data.help_text = f.help_text
            fields.append(data)

    answers = submission.answers if (is_owner or is_reviewer) and revealed else None

    base = SubmissionRead.model_validate(submission)
    return SubmissionDetail(
        **base.model_dump(),
        answers=answers,
        fields=fields,
    )


def delete_submission(
    db: Session, *, submission_id: int, principal: Principal
) -> None:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal)
    if submission.status != "in_progress":
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Finalized submissions cannot be deleted"
        )
    repository.delete_submission(db, submission)
