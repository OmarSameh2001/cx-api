from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from .dto import FormCreate, FormUpdate
from .model import Form
from . import repository


def _ensure_creator_can_edit(form: Form, employee_id: int) -> None:
    if form.created_by != employee_id:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the form creator can modify it"
        )
    if form.is_active:
        raise HTTPException(
            status.HTTP_409_CONFLICT, "Form must be inactive to be modified"
        )


def get_form(db: Session, form_id: int) -> Form:
    form = repository.get_form(db, form_id)
    if form is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Form not found")
    return form


def list_forms(
    db: Session,
    *,
    is_active: Optional[bool],
    is_archived: Optional[bool],
    submitter_type: Optional[str],
    created_by: Optional[int],
    limit: int,
    offset: int,
) -> tuple[list[Form], int]:
    items = repository.list_forms(
        db,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        limit=limit,
        offset=offset,
    )
    total = repository.count_forms(
        db,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
    )
    return items, total


def create_form(db: Session, *, payload: FormCreate, employee_id: int) -> Form:
    data = payload.model_dump(exclude={"fields"})
    fields = [f.model_dump() for f in payload.fields]
    return repository.create_form(db, data=data, fields=fields, created_by=employee_id)


def update_form(
    db: Session, *, form_id: int, payload: FormUpdate, employee_id: int
) -> Form:
    form = get_form(db, form_id)
    _ensure_creator_can_edit(form, employee_id)

    data = payload.model_dump(exclude_unset=True, exclude={"fields"})
    fields = (
        [f.model_dump() for f in payload.fields] if payload.fields is not None else None
    )
    return repository.update_form(db, form, data=data, fields=fields)


def delete_form(db: Session, *, form_id: int, employee_id: int) -> None:
    form = get_form(db, form_id)
    _ensure_creator_can_edit(form, employee_id)
    repository.delete_form(db, form)
