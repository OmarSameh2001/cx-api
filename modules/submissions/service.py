from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.forms import repository as forms_repository
from modules.forms.model import Form, FormField

from . import repository
from .dto import SubmissionCreate, SubmissionUpdate
from .model import Submission


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
    if field.type == "true_false":
        return str(answer).strip().lower() == field.right_answer.strip().lower()
    if field.type == "single_choice":
        return str(answer).strip() == field.right_answer.strip()
    return False


def _validate_and_score(form: Form, answers: dict[str, Any]) -> Optional[float]:
    has_text = any(f.type == "text" for f in form.fields)

    for field in form.fields:
        key = str(field.id)
        provided = answers.get(key)
        if field.is_required and (provided is None or provided == "" or provided == []):
            raise HTTPException(
                status.HTTP_422_UNPROCESSABLE_ENTITY,
                f"Field {field.id} ({field.question}) is required",
            )

    if has_text:
        return None

    score = 0.0
    for field in form.fields:
        provided = answers.get(str(field.id))
        if provided is None:
            continue
        if _is_correct(field, provided):
            score += field.score_weight
    return score


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


def _ensure_owner(submission: Submission, principal_type: str, principal_id: int) -> None:
    if principal_type == "employee" and submission.user_id == principal_id:
        return
    if principal_type == "customer" and submission.customer_id == principal_id:
        return
    raise HTTPException(
        status.HTTP_403_FORBIDDEN, "You can only modify your own submissions"
    )


def _ensure_can_view(submission: Submission, principal_type: str, principal_id: int) -> None:
    if principal_type == "employee":
        return
    _ensure_owner(submission, principal_type, principal_id)


def get_submission(
    db: Session, *, submission_id: int, principal_type: str, principal_id: int
) -> Submission:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_can_view(submission, principal_type, principal_id)
    return submission


def list_submissions(
    db: Session,
    *,
    principal_type: str,
    principal_id: int,
    form_id: Optional[int],
    limit: int,
    offset: int,
) -> tuple[list[Submission], int]:
    customer_id: Optional[int] = None
    user_id: Optional[int] = None
    if principal_type == "customer":
        customer_id = principal_id
    items = repository.list_submissions(
        db,
        form_id=form_id,
        customer_id=customer_id,
        user_id=user_id,
        limit=limit,
        offset=offset,
    )
    total = repository.count_submissions(
        db,
        form_id=form_id,
        customer_id=customer_id,
        user_id=user_id,
    )
    return items, total


def create_submission(
    db: Session,
    *,
    payload: SubmissionCreate,
    principal_type: str,
    principal_id: int,
) -> Submission:
    form = forms_repository.get_form(db, payload.form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")

    _ensure_submitter_allowed(form, principal_type)
    score = _validate_and_score(form, payload.answers)

    return repository.create_submission(
        db,
        form_id=form.id,
        answers=payload.answers,
        score=score,
        customer_id=principal_id if principal_type == "customer" else None,
        user_id=principal_id if principal_type == "employee" else None,
    )


def update_submission(
    db: Session,
    *,
    submission_id: int,
    payload: SubmissionUpdate,
    principal_type: str,
    principal_id: int,
) -> Submission:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal_type, principal_id)

    form = forms_repository.get_form(db, submission.form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    if not form.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Form is closed; submission cannot be edited"
        )

    score = _validate_and_score(form, payload.answers)
    return repository.update_submission(
        db, submission, answers=payload.answers, score=score
    )


def delete_submission(
    db: Session, *, submission_id: int, principal_type: str, principal_id: int
) -> None:
    submission = repository.get_submission(db, submission_id)
    if submission is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Submission not found")
    _ensure_owner(submission, principal_type, principal_id)
    repository.delete_submission(db, submission)
