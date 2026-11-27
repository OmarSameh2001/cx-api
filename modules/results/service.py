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

from sqlalchemy.orm import Session

from common.errors import AppError
from modules.auth.dto import EmployeePrincipal
from modules.forms import access as form_access
from modules.forms import repository as forms_repository
from modules.forms.dto import DISPLAY_TYPES, GRID_TYPES, read_config
from modules.submissions.answer_rules import NOT_APPLICABLE, as_number, point_range

from . import repository
from .dto import (
    GridRowSummary, NpsSummary, QuestionSummary, ResultsFilters, ResultsQuery, ResultsResponse,
    SummaryQuery, SummaryResponse, ValueCount,
)
from .model import SubmissionValue


# answers stored in value_number
NUMBER_TYPES = {"scale", "nps", "rating", "number", "currency", "slider"}


def _is_empty(value: Any) -> bool:
    return value is None or value == "" or value == [] or value == {}


def _typed(field_type: str, value: Any) -> dict[str, Any]:
    """The value columns for one answer. Answers were validated on submit;
    anything older that doesn't fit its type is kept in value_json."""
    try:
        if field_type == "multi_choice" or (field_type == "image_choice" and not isinstance(value, str)):
            parts = value.split(",") if isinstance(value, str) else list(value)
            return {"value_json": [str(p).strip() for p in parts if str(p).strip()]}
        if field_type == "boolean":
            if isinstance(value, bool):
                return {"value_bool": value}
            if str(value).strip().lower() in ("true", "false"):
                return {"value_bool": str(value).strip().lower() == "true"}
        elif field_type == "scale" and value == NOT_APPLICABLE:
            # "not applicable" is an answer, but not a point: averages skip it
            return {"value_text": NOT_APPLICABLE}
        elif field_type in NUMBER_TYPES:
            number = as_number(value)
            if number is not None:
                return {"value_number": number}
        elif field_type in GRID_TYPES:
            # {row: column}, or {row: [columns]} for checkbox grids
            if isinstance(value, dict):
                return {"value_json": value}
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


def _scope(
    db: Session, *, employee: EmployeePrincipal, form_id: Optional[int], filters: ResultsFilters
) -> tuple[Optional[Any], Optional[set[int]], str]:
    """The form asked about, the units the caller's results are limited to
    (None: no limit) and what they cover. Raises unless the caller may see
    results (see the module docstring)."""
    form = None
    if form_id is not None:
        form = forms_repository.get_form(db, form_id)
        if form is None or form.organisation_id != employee.organisation_id:
            raise AppError(404, "forms.not_found")

    whole_organisation = employee.is_admin or (form is not None and form.created_by == employee.id)
    if not whole_organisation and not form_access.can_review_all(employee):
        raise AppError(403, "results.view_denied")

    units: Optional[set[int]] = set(filters.unit_ids) if filters.unit_ids is not None else None
    if not whole_organisation:
        allowed = _visible_units(employee)
        units = allowed if units is None else units & allowed
    return form, units, "organisation" if whole_organisation else "units"


def _filter_args(filters: ResultsFilters, units: Optional[set[int]]) -> dict[str, Any]:
    return {
        "form_version_ids": filters.form_version_ids,
        "question_keys": filters.question_keys,
        "unit_ids": sorted(units) if units is not None else None,
        "subject_employee_ids": filters.subject_employee_ids,
        "submitted_from": filters.submitted_from,
        "submitted_to": filters.submitted_to,
    }


def query(db: Session, *, employee: EmployeePrincipal, payload: ResultsQuery) -> ResultsResponse:
    _, units, scope = _scope(db, employee=employee, form_id=payload.form_id, filters=payload.filters)
    if units is not None and not units:
        return ResultsResponse(rows=[], truncated=False, scope=scope)

    rows, truncated = repository.aggregate(
        db,
        organisation_id=employee.organisation_id,
        group_by=payload.group_by,
        measures=payload.measures,
        form_id=payload.form_id,
        limit=payload.limit,
        **_filter_args(payload.filters, units),
    )
    return ResultsResponse(
        rows=[{k: _json_value(v) for k, v in row.items()} for row in rows],
        truncated=truncated,
        scope=scope,
    )


# --- per-question summaries (E2.1) ---------------------------------------------
# Each question type is summarised its own way: choices as counts per option,
# numbers as average, range and distribution, NPS with its three groups, grids
# as counts per row and column, free answers as a count.

# answers whose distribution is counted per value
_COUNTED_TYPES = {
    "single_choice", "multi_choice", "dropdown", "image_choice", "boolean",
    "scale", "nps", "rating",
}
# distributions over a number range get every point, answered or not
_POINT_TYPES = {"scale", "nps", "rating"}


def nps_groups(distribution: dict[str, int]) -> dict[str, Any]:
    """Promoters (9–10), passives (7–8), detractors (0–6) and the score:
    % promoters − % detractors, from −100 to 100 (None without answers)."""
    groups = {"promoters": 0, "passives": 0, "detractors": 0}
    for value, count in distribution.items():
        point = as_number(value)
        if point is None:
            continue
        key = "promoters" if point >= 9 else "passives" if point >= 7 else "detractors"
        groups[key] += count
    total = sum(groups.values())
    score = round(100 * (groups["promoters"] - groups["detractors"]) / total, 1) if total else None
    return {**groups, "score": score}


def nps_group(point: Any) -> Optional[str]:
    number = as_number(point)
    if number is None:
        return None
    return "promoter" if number >= 9 else "passive" if number >= 7 else "detractor"


def _value_key(field_type: str, value: Any) -> str:
    """A grouped value as the answer is written: 7 not "7.0", true not "True"."""
    if field_type == "boolean":
        return str(value).lower()
    number = as_number(value) if field_type in _POINT_TYPES else None
    if number is not None and number == int(number):
        return str(int(number))
    return str(value)


def _choices(field) -> list[str]:
    """The answers a question offers, in order, for a distribution that
    shows options nobody picked."""
    if field.type in ("single_choice", "multi_choice", "dropdown", "image_choice"):
        return list(field.options or [])
    if field.type == "boolean":
        return ["true", "false"]
    if field.type in _POINT_TYPES:
        low, high = point_range(field)
        points = [str(p) for p in range(low, high + 1)]
        config = read_config(field.type, field.config)
        if field.type == "scale" and config is not None and config.allow_na:
            points.append(NOT_APPLICABLE)
        return points
    return []


def summarize_question(field, totals: dict[str, Any], counts: dict[str, int], grid: dict) -> QuestionSummary:
    """One question's summary from its aggregates: `totals` (count,
    submissions, avg/min/max_number), `counts` (answers per value) and
    `grid` ({row: {column: count}})."""
    summary = QuestionSummary(
        key=field.key or str(field.id),
        field_id=field.id,
        type=field.type,
        question=field.question,
        answered=int(totals.get("submissions") or 0),
    )
    if field.type in NUMBER_TYPES:
        for name in ("avg_number", "min_number", "max_number"):
            value = totals.get(name)
            setattr(summary, name.replace("_number", ""), None if value is None else float(value))
    if field.type in _COUNTED_TYPES:
        offered = _choices(field)
        seen = {_value_key(field.type, v): int(c) for v, c in counts.items() if v is not None}
        merged = {value: seen.pop(value, 0) for value in offered}
        # answers the version no longer offers (renamed options) stay visible
        merged.update(seen)
        summary.distribution = [ValueCount(value=v, count=c) for v, c in merged.items()]
        if field.type == "nps":
            summary.nps = NpsSummary(**nps_groups(merged))
    if field.type in GRID_TYPES:
        config = read_config(field.type, field.config)
        rows = list(config.rows) if config else list(grid)
        columns = list(config.columns) if config else sorted({c for r in grid.values() for c in r})
        summary.grid = [
            GridRowSummary(row=row, counts={col: int(grid.get(row, {}).get(col, 0)) for col in columns})
            for row in rows
        ]
    return summary


def summary(db: Session, *, employee: EmployeePrincipal, payload: SummaryQuery) -> SummaryResponse:
    """Every question of the form's current version, summarised over the
    answers the caller may see. Answers are followed by question key, so
    earlier versions count too (unless the filters pick versions)."""
    from modules.forms.service import published

    form, units, scope = _scope(db, employee=employee, form_id=payload.form_id, filters=payload.filters)
    view = published(form) or form
    fields = [f for f in view.fields if f.type not in DISPLAY_TYPES]
    if units is not None and not units:
        totals, counts, grid = {}, {}, {}
    else:
        args = {
            "organisation_id": employee.organisation_id,
            "form_id": form.id,
            **_filter_args(payload.filters, units),
        }
        limit = 5000
        rows, _ = repository.aggregate(
            db, group_by=["question_key"], measures=["count", "submissions", "avg_number", "min_number", "max_number"],
            limit=limit, **args,
        )
        totals = {r["question_key"]: r for r in rows}
        # only questions answered from a list: free text would crowd them out of the limit
        counted = {f.key or str(f.id) for f in fields if f.type in _COUNTED_TYPES}
        if payload.filters.question_keys is not None:
            counted &= set(payload.filters.question_keys)
        rows = []
        if counted:
            rows, _ = repository.aggregate(
                db, group_by=["question_key", "value"], measures=["count"], limit=limit,
                **{**args, "question_keys": sorted(counted)},
            )
        counts: dict[str, dict] = {}
        for r in rows:
            counts.setdefault(r["question_key"], {})[r["value"]] = r["count"]
        grid: dict[str, dict] = {}
        for r in repository.grid_counts(db, limit=limit, **args):
            grid.setdefault(r["question_key"], {}).setdefault(r["row"], {})[r["column"]] = r["count"]

    questions = []
    for f in fields:
        key = f.key or str(f.id)
        questions.append(summarize_question(f, totals.get(key, {}), counts.get(key, {}), grid.get(key, {})))
    return SummaryResponse(form_id=form.id, scope=scope, questions=questions)
