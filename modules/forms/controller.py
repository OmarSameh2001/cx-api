from typing import Optional

from sqlalchemy.orm import Session

from . import service
from .dto import FormCreate, FormRead, FormSummary, FormUpdate


def list_forms(
    db: Session,
    *,
    is_active: Optional[bool],
    is_archived: Optional[bool],
    submitter_type: Optional[str],
    created_by: Optional[int],
    limit: int,
    offset: int,
) -> list[FormSummary]:
    forms = service.list_forms(
        db,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        limit=limit,
        offset=offset,
    )
    return [FormSummary.model_validate(f) for f in forms]


def get_form(db: Session, form_id: int) -> FormRead:
    return FormRead.model_validate(service.get_form(db, form_id))


def create_form(db: Session, payload: FormCreate, employee_id: int) -> FormRead:
    form = service.create_form(db, payload=payload, employee_id=employee_id)
    return FormRead.model_validate(form)


def update_form(
    db: Session, form_id: int, payload: FormUpdate, employee_id: int
) -> FormRead:
    form = service.update_form(
        db, form_id=form_id, payload=payload, employee_id=employee_id
    )
    return FormRead.model_validate(form)


def delete_form(db: Session, form_id: int, employee_id: int) -> None:
    service.delete_form(db, form_id=form_id, employee_id=employee_id)
