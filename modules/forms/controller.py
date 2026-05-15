from typing import Optional

from sqlalchemy.orm import Session

from common.dto import Page
from modules.auth.dto import EmployeePrincipal, Principal

from . import service
from .dto import (
    AssignedFormSummary,
    FormCreate,
    FormRead,
    FormSummary,
    FormUpdate,
)


def list_forms(
    db: Session,
    *,
    employee: EmployeePrincipal,
    is_active: Optional[bool],
    is_archived: Optional[bool],
    submitter_type: Optional[str],
    created_by: Optional[int],
    name: Optional[str],
    form_type: Optional[str],
    limit: int,
    offset: int,
) -> Page[FormSummary]:
    items, total = service.list_forms(
        db,
        organisation_id=employee.organisation_id,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        name=name,
        form_type=form_type,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[FormSummary.model_validate(f) for f in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_form(db: Session, form_id: int, principal: Principal) -> FormRead:
    org_id = getattr(principal, "organisation_id", None)
    return FormRead.model_validate(
        service.get_form(db, form_id, organisation_id=org_id)
    )


def create_form(db: Session, payload: FormCreate, employee: EmployeePrincipal) -> FormRead:
    form = service.create_form(db, payload=payload, employee=employee)
    return FormRead.model_validate(form)


def update_form(
    db: Session, form_id: int, payload: FormUpdate, employee: EmployeePrincipal
) -> FormRead:
    form = service.update_form(
        db, form_id=form_id, payload=payload, employee=employee
    )
    return FormRead.model_validate(form)


def delete_form(db: Session, form_id: int, employee: EmployeePrincipal) -> None:
    service.delete_form(db, form_id=form_id, employee=employee)


def toggle_active(
    db: Session, form_id: int, active: bool, employee: EmployeePrincipal
) -> FormRead:
    form = service.toggle_active(db, form_id=form_id, active=active, employee=employee)
    return FormRead.model_validate(form)


def reveal_form_results(
    db: Session, form_id: int, employee: EmployeePrincipal
) -> FormRead:
    form = service.reveal_form_results(db, form_id=form_id, employee=employee)
    return FormRead.model_validate(form)


def rotate_public_token(
    db: Session, form_id: int, employee: EmployeePrincipal
) -> FormRead:
    form = service.rotate_public_token(db, form_id=form_id, employee=employee)
    return FormRead.model_validate(form)


def revoke_public_token(
    db: Session, form_id: int, employee: EmployeePrincipal
) -> FormRead:
    form = service.revoke_public_token(db, form_id=form_id, employee=employee)
    return FormRead.model_validate(form)


def list_assigned_to_me(
    db: Session,
    *,
    employee: EmployeePrincipal,
    limit: int,
    offset: int,
    my_status: Optional[str],
    name: Optional[str],
    form_type: Optional[str],
) -> Page[AssignedFormSummary]:
    items, total = service.list_assigned_to_me(
        db,
        employee=employee,
        limit=limit,
        offset=offset,
        my_status=my_status,
        name=name,
        form_type=form_type,
    )
    return Page(
        items=[AssignedFormSummary.model_validate(i) for i in items],
        total=total,
        limit=limit,
        offset=offset,
    )
