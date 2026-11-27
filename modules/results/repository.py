from datetime import datetime
from typing import Any, Optional, Sequence

from sqlalchemy import Text, case, cast, delete, distinct, func, literal_column, select, true
from sqlalchemy.orm import Session

from .model import SubmissionValue as SV

TIME_BUCKETS = ("day", "week", "month")


def add_values(db: Session, rows: list[SV]) -> None:
    for row in rows:
        db.add(row)


def delete_values(db: Session, submission_id: int) -> None:
    db.execute(delete(SV).where(SV.submission_id == submission_id))


def _value_text():
    """Each answer as text, for grouping by answer: one row per selected
    option of a multiple-choice answer (the lateral join below), else the
    value in whichever column holds it."""
    options = (
        func.jsonb_array_elements_text(
            case(
                (func.jsonb_typeof(SV.value_json) == "array", SV.value_json),
                else_=literal_column("'[]'::jsonb"),
            )
        )
        .table_valued("value")
        .lateral("options")
    )
    expr = func.coalesce(
        options.c.value,
        SV.value_text,
        cast(SV.value_bool, Text),
        cast(SV.value_number, Text),
        cast(SV.value_date, Text),
    )
    return options, expr


_MEASURES = {
    "count": lambda: func.count(),
    "submissions": lambda: func.count(distinct(SV.submission_id)),
    "avg_number": lambda: func.avg(SV.value_number),
    "min_number": lambda: func.min(SV.value_number),
    "max_number": lambda: func.max(SV.value_number),
    "sum_number": lambda: func.sum(SV.value_number),
    "avg_score": lambda: func.avg(SV.score),
    "score_percent": lambda: 100 * func.sum(SV.score) / func.nullif(func.sum(SV.max_score), 0),
}

_COLUMNS = {
    "question_key": SV.question_key,
    "question_type": SV.question_type,
    "section_id": SV.section_id,
    "form_id": SV.form_id,
    "form_version_id": SV.form_version_id,
    "unit_id": SV.unit_id,
    "subject_employee_id": SV.subject_employee_id,
}


def aggregate(
    db: Session,
    *,
    organisation_id: int,
    group_by: Sequence[str],
    measures: Sequence[str],
    form_id: Optional[int] = None,
    form_version_ids: Optional[Sequence[int]] = None,
    question_keys: Optional[Sequence[str]] = None,
    unit_ids: Optional[Sequence[int]] = None,
    subject_employee_ids: Optional[Sequence[int]] = None,
    submitted_from: Optional[datetime] = None,
    submitted_to: Optional[datetime] = None,
    limit: int = 1000,
) -> tuple[list[dict[str, Any]], bool]:
    """Rows of {group column: value, measure: value}, ordered by the group
    columns, and whether there were more than `limit`. The organisation is
    always applied; `unit_ids` (when given) restricts to those units, so
    answers without a unit are left out."""
    groups = []
    stmt = select().select_from(SV)
    for name in group_by:
        if name == "value":
            options, expr = _value_text()
            stmt = stmt.outerjoin(options, true())
            groups.append(expr.label("value"))
        elif name in TIME_BUCKETS:
            # the unit inline (it is one of TIME_BUCKETS): as a bound parameter the
            # select and the GROUP BY would get different ones, which Postgres refuses
            groups.append(func.date_trunc(literal_column(f"'{name}'"), SV.submitted_at).label("period"))
        else:
            groups.append(_COLUMNS[name].label(name))
    stmt = stmt.add_columns(*groups, *(_MEASURES[m]().label(m) for m in measures))

    stmt = stmt.where(SV.organisation_id == organisation_id)
    if form_id is not None:
        stmt = stmt.where(SV.form_id == form_id)
    if form_version_ids:
        stmt = stmt.where(SV.form_version_id.in_(form_version_ids))
    if question_keys:
        stmt = stmt.where(SV.question_key.in_(question_keys))
    if unit_ids is not None:
        stmt = stmt.where(SV.unit_id.in_(unit_ids))
    if subject_employee_ids:
        stmt = stmt.where(SV.subject_employee_id.in_(subject_employee_ids))
    if submitted_from is not None:
        stmt = stmt.where(SV.submitted_at >= submitted_from)
    if submitted_to is not None:
        stmt = stmt.where(SV.submitted_at < submitted_to)

    if groups:
        stmt = stmt.group_by(*groups).order_by(*(g.asc().nulls_last() for g in groups))
    rows = db.execute(stmt.limit(limit + 1)).mappings().all()
    return [dict(r) for r in rows[:limit]], len(rows) > limit


GRID_TYPES = ("likert", "choice_grid", "checkbox_grid")


def grid_counts(
    db: Session,
    *,
    organisation_id: int,
    form_id: int,
    form_version_ids: Optional[Sequence[int]] = None,
    question_keys: Optional[Sequence[str]] = None,
    unit_ids: Optional[Sequence[int]] = None,
    subject_employee_ids: Optional[Sequence[int]] = None,
    submitted_from: Optional[datetime] = None,
    submitted_to: Optional[datetime] = None,
    limit: int = 5000,
) -> list[dict[str, Any]]:
    """Answers per row and column of grid questions: rows of
    {question_key, row, column, count}. A grid answer is {row: column}, or
    {row: [columns]} for checkbox grids, in value_json."""
    rows = (
        func.jsonb_each(
            case(
                (func.jsonb_typeof(SV.value_json) == "object", SV.value_json),
                else_=literal_column("'{}'::jsonb"),
            )
        )
        .table_valued("key", "value")
        .lateral("grid_rows")
    )
    columns = (
        func.jsonb_array_elements_text(
            case(
                (func.jsonb_typeof(rows.c.value) == "array", rows.c.value),
                else_=func.jsonb_build_array(rows.c.value),
            )
        )
        .table_valued("value")
        .lateral("grid_columns")
    )
    stmt = (
        select(
            SV.question_key.label("question_key"),
            rows.c.key.label("row"),
            columns.c.value.label("column"),
            func.count().label("count"),
        )
        .select_from(SV)
        .join(rows, true())
        .join(columns, true())
        .where(
            SV.organisation_id == organisation_id,
            SV.form_id == form_id,
            SV.question_type.in_(GRID_TYPES),
        )
    )
    if form_version_ids:
        stmt = stmt.where(SV.form_version_id.in_(form_version_ids))
    if question_keys:
        stmt = stmt.where(SV.question_key.in_(question_keys))
    if unit_ids is not None:
        stmt = stmt.where(SV.unit_id.in_(unit_ids))
    if subject_employee_ids:
        stmt = stmt.where(SV.subject_employee_id.in_(subject_employee_ids))
    if submitted_from is not None:
        stmt = stmt.where(SV.submitted_at >= submitted_from)
    if submitted_to is not None:
        stmt = stmt.where(SV.submitted_at < submitted_to)
    stmt = stmt.group_by(SV.question_key, rows.c.key, columns.c.value).limit(limit)
    return [dict(r) for r in db.execute(stmt).mappings().all()]
