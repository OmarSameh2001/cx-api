import secrets
from datetime import datetime, timezone
from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.auth.dto import EmployeePrincipal

from . import repository
from .dto import FormCreate, FormUpdate
from .model import Form


def _new_public_token() -> str:
    return secrets.token_urlsafe(16)


def _should_have_public_token(form_or_data) -> bool:
    """Public token applies to questionnaires that accept customers."""
    type_ = getattr(form_or_data, "type", None) or (
        form_or_data.get("type") if isinstance(form_or_data, dict) else None
    )
    submitter = getattr(form_or_data, "submitter_type", None) or (
        form_or_data.get("submitter_type") if isinstance(form_or_data, dict) else None
    )
    return type_ == "questionnaire" and "customer" in (submitter or [])


def _ensure_creator_can_edit(form: Form, employee_id: int) -> None:
    if form.created_by != employee_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the form creator can modify it"
        )
    if form.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Form must be inactive to be modified"
        )


def _ensure_same_org(form: Form, organisation_id: int) -> None:
    if form.organisation_id != organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")


def get_form(db: Session, form_id: int, *, organisation_id: Optional[int] = None) -> Form:
    form = repository.get_form(db, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    if organisation_id is not None:
        _ensure_same_org(form, organisation_id)
    return form


def list_forms(
    db: Session,
    *,
    organisation_id: int,
    is_active: Optional[bool],
    is_archived: Optional[bool],
    submitter_type: Optional[str],
    created_by: Optional[int],
    name: Optional[str],
    form_type: Optional[str],
    limit: int,
    offset: int,
) -> tuple[list[Form], int]:
    items = repository.list_forms(
        db,
        organisation_id=organisation_id,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        name=name,
        form_type=form_type,
        limit=limit,
        offset=offset,
    )
    total = repository.count_forms(
        db,
        organisation_id=organisation_id,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        name=name,
        form_type=form_type,
    )
    return items, total


def create_form(db: Session, *, payload: FormCreate, employee: EmployeePrincipal) -> Form:
    data = payload.model_dump(exclude={"fields"})
    data["organisation_id"] = employee.organisation_id
    if _should_have_public_token(payload):
        data["public_token"] = _new_public_token()
    fields = [f.model_dump() for f in payload.fields]
    return repository.create_form(db, data=data, fields=fields, created_by=employee.id)


def rotate_public_token(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not (
        form.created_by == employee.id
        or "forms:manage" in (employee.permissions or [])
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage this form")
    if form.type != "questionnaire" or "customer" not in (form.submitter_type or []):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Public link is only available for questionnaires that accept customer submissions",
        )
    return repository.set_public_token(db, form, _new_public_token())


def revoke_public_token(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if not (
        form.created_by == employee.id
        or "forms:manage" in (employee.permissions or [])
    ):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to manage this form")
    return repository.set_public_token(db, form, None)


def update_form(
    db: Session, *, form_id: int, payload: FormUpdate, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    _ensure_creator_can_edit(form, employee.id)

    data = payload.model_dump(exclude_unset=True, exclude={"fields"})
    fields = (
        [f.model_dump() for f in payload.fields] if payload.fields is not None else None
    )
    return repository.update_form(db, form, data=data, fields=fields)


def delete_form(db: Session, *, form_id: int, employee: EmployeePrincipal) -> None:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    _ensure_creator_can_edit(form, employee.id)
    repository.delete_form(db, form)


def toggle_active(
    db: Session, *, form_id: int, active: bool, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if form.created_by != employee.id and "forms:manage" not in (employee.permissions or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to modify this form")
    form.is_active = active
    db.commit()
    db.refresh(form)
    return form


def reveal_form_results(
    db: Session, *, form_id: int, employee: EmployeePrincipal
) -> Form:
    form = get_form(db, form_id, organisation_id=employee.organisation_id)
    if form.created_by != employee.id and "submissions:view" not in (employee.permissions or []):
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Not allowed to reveal results")
    form.results_revealed = True
    db.commit()
    db.refresh(form)
    return form


def list_assigned_to_me(
    db: Session,
    *,
    employee: EmployeePrincipal,
    limit: int,
    offset: int,
    my_status: Optional[str] = None,
    name: Optional[str] = None,
    form_type: Optional[str] = None,
) -> tuple[list[dict], int]:
    """Return forms targeted to the caller's unit set, enriched with my_status."""
    from modules.submissions.model import Submission

    unit_ids: list[int] = list(employee.assigned_unit_ids or [])
    if employee.unit_id is not None and employee.unit_id not in unit_ids:
        unit_ids.append(employee.unit_id)

    forms = repository.list_forms_assigned(
        db,
        organisation_id=employee.organisation_id,
        submitter_type=employee.principal,
        unit_ids=unit_ids,
        name=name,
        form_type=form_type,
        limit=limit,
        offset=offset,
    )
    total = repository.count_forms_assigned(
        db,
        organisation_id=employee.organisation_id,
        submitter_type=employee.principal,
        unit_ids=unit_ids,
        name=name,
        form_type=form_type,
    )

    if not forms:
        return [], total

    form_ids = [f.id for f in forms]
    rows = db.execute(
        select(Submission).where(
            Submission.form_id.in_(form_ids),
            Submission.user_id == employee.id,
        )
    ).scalars().all()

    by_form: dict[int, list[Submission]] = {}
    for s in rows:
        by_form.setdefault(s.form_id, []).append(s)

    now = datetime.now(timezone.utc)
    items: list[dict] = []
    for form in forms:
        subs = by_form.get(form.id, [])
        finalized = [s for s in subs if s.status in ("submitted", "late")]
        open_sub = next((s for s in subs if s.status == "in_progress"), None)
        if open_sub and form.type == "exam" and open_sub.expires_at and open_sub.expires_at < now:
            my_status_val = "expired"
        elif open_sub:
            my_status_val = "in_progress"
        elif finalized:
            last = max(finalized, key=lambda s: s.submitted_at or datetime.min)
            my_status_val = last.status
        elif any(s.status == "expired" for s in subs):
            my_status_val = "expired"
        else:
            my_status_val = "not_started"

        if my_status and my_status_val != my_status:
            continue

        items.append(
            {
                "id": form.id,
                "name": form.name,
                "type": form.type,
                "is_active": form.is_active,
                "is_archived": form.is_archived,
                "submitter_type": form.submitter_type or [],
                "time_limit_minutes": form.time_limit_minutes,
                "max_attempts": form.max_attempts,
                "results_revealed": form.results_revealed,
                "created_at": form.created_at,
                "created_by": form.created_by,
                "my_status": my_status_val,
                "attempts_used": len(finalized),
            }
        )

    return items, total
