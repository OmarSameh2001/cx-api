"""Results (E1.6): one row per answer of a finished submission, and queries
over them.

Rows are written by the submissions service when a submission is finalized
or regraded (it owns grading); this module turns answers into rows and
answers results queries, scoped by the rules below.

Who sees what (I10):
- organisation admins: every result in the organisation;
- a form's creator: every result of that form (query with its form_id);
- employees who review submissions (submissions:read): the results of
  their own units, i.e. their unit and every unit under it, from the token;
- anyone else: nothing (403).
"""

from datetime import date, datetime
from typing import Any, Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.auth.dto import EmployeePrincipal
from modules.forms import access as form_access
from modules.forms import repository as forms_repository

from . import repository
from .dto import ResultsQuery, ResultsResponse
from .model import SubmissionValue


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _typed(field_type: str, value: Any) -> dict[str, Any]:
    """The value columns for one answer. Answers were validated on submit;
    anything older that doesn't fit its type is kept in value_json."""
    try:
        if field_type == "multi_choice":
            parts = value.split(",") if isinstance(value, str) else list(value)
            return {"value_json": [str(p).strip() for p in parts if str(p).strip()]}
        if field_type == "boolean":
            if isinstance(value, bool):
                return {"value_bool": value}
            if str(value).strip().lower() in ("true", "false"):
                return {"value_bool": str(value).strip().lower() == "true"}
        elif field_type == "scale":
            if not isinstance(value, bool):
                return {"value_number": float(int(value))}
        elif field_type == "date":
            if isinstance(value, str):
                return {"value_date": date.fromisoformat(value)}
        elif field_type == "file":
            if isinstance(value, dict):
                return {"value_json": value}
        elif isinstance(value, str):
            return {"value_text": value}
    except (TypeError, ValueError):
        pass
    return {"value_json": value}


def build_values(
    submission, form, questions: dict[int, tuple[float, float]], *, unit_id: Optional[int]
) -> list[SubmissionValue]:
    """One row per answered question of a finalized submission. `form` is
    the version answered; `questions` holds the graded questions' (earned,
    possible) points."""
    answers = submission.answers or {}
    duration = None
    # employees start an attempt and submit it later; a public link is answered in one request
    if submission.user_id is not None and submission.started_at and submission.submitted_at:
        duration = max(0, int((submission.submitted_at - submission.started_at).total_seconds()))
    rows = []
    for field in form.fields:
        value = answers.get(str(field.id))
        if _is_empty(value):
            continue
        earned, possible = questions.get(field.id, (None, None))
        rows.append(
            SubmissionValue(
                submission_id=submission.id,
                organisation_id=form.organisation_id,
                form_id=form.id,
                form_version_id=submission.form_version_id,
                field_id=field.id,
                question_key=field.key or str(field.id),
                question_type=field.type,
                section_id=field.section_id,
                score=earned,
                max_score=possible,
                subject_employee_id=None,
                unit_id=unit_id,
                submitted_at=submission.submitted_at,
                duration_seconds=duration,
                **_typed(field.type, value),
            )
        )
    return rows


def add_values(db: Session, submission, form, questions, *, unit_id: Optional[int]) -> None:
    """Rows for a submission finalized just now (it has none yet). No commit."""
    repository.add_values(db, build_values(submission, form, questions, unit_id=unit_id))


def replace_values(db: Session, submission, form, questions, *, unit_id: Optional[int]) -> None:
    """Rewrites a submission's rows, for a regrade. No commit."""
    repository.delete_values(db, submission.id)
    repository.add_values(db, build_values(submission, form, questions, unit_id=unit_id))


def _visible_units(employee: EmployeePrincipal) -> set[int]:
    units = set(employee.assigned_unit_ids or [])
    if employee.unit_id is not None:
        units.add(employee.unit_id)
    return units


def _json_value(v: Any) -> Any:
    if isinstance(v, datetime):
        return v.isoformat()
    if isinstance(v, date):
        return v.isoformat()
    # avg() comes back as a Decimal for integer columns; ours are floats,
    # but keep the response plain JSON either way
    if v is not None and not isinstance(v, (bool, int, float, str)):
        return float(v)
    return v


def query(db: Session, *, employee: EmployeePrincipal, payload: ResultsQuery) -> ResultsResponse:
    form = None
    if payload.form_id is not None:
        form = forms_repository.get_form(db, payload.form_id)
        if form is None or form.organisation_id != employee.organisation_id:
            raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")

    whole_organisation = employee.is_admin or (form is not None and form.created_by == employee.id)
    if not whole_organisation and not form_access.can_review_all(employee):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to view results")

    filters = payload.filters
    units: Optional[set[int]] = set(filters.unit_ids) if filters.unit_ids is not None else None
    if not whole_organisation:
        allowed = _visible_units(employee)
        units = allowed if units is None else units & allowed
    scope = "organisation" if whole_organisation else "units"
    if units is not None and not units:
        return ResultsResponse(rows=[], truncated=False, scope=scope)

    rows, truncated = repository.aggregate(
        db,
        organisation_id=employee.organisation_id,
        group_by=payload.group_by,
        measures=payload.measures,
        form_id=payload.form_id,
        form_version_ids=filters.form_version_ids,
        question_keys=filters.question_keys,
        unit_ids=sorted(units) if units is not None else None,
        subject_employee_ids=filters.subject_employee_ids,
        submitted_from=filters.submitted_from,
        submitted_to=filters.submitted_to,
        limit=payload.limit,
    )
    return ResultsResponse(
        rows=[{k: _json_value(v) for k, v in row.items()} for row in rows],
        truncated=truncated,
        scope=scope,
    )
