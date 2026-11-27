from typing import Optional

from sqlalchemy.orm import Session

from common.dto import Page
from modules.auth.dto import EmployeePrincipal

from . import access, service
from .dto import (
    AssignedFormSummary,
    FormCreate,
    FormFieldRead,
    FormRead,
    FormSummary,
    FormUpdate,
    FormVersionDiff,
    FormVersionRead,
    FormVersionSummary,
)
from .model import Form, PublishedForm


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
        employee=employee,
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


def _read(db: Session, form: Form) -> FormRead:
    return FormRead.model_validate(form).model_copy(
        update={
            "has_submissions": service.has_submissions(db, form),
            "has_unpublished_changes": service.has_unpublished_changes(form),
            "media": service.media_for(db, form),
        }
    )


def _without_answers(fields: list[FormFieldRead]) -> list[FormFieldRead]:
    # a forms:read viewer sees the questions, never the correct answers
    return [f.model_copy(update={"right_answer": None}) for f in fields]


def get_form(db: Session, form_id: int, employee: EmployeePrincipal) -> FormRead:
    form = service.get_form_for_employee(db, form_id, employee)
    read = _read(db, form)
    if access.can_see_answers(employee, form):
        return read
    return read.model_copy(update={"fields": _without_answers(read.fields)})


def create_form(db: Session, payload: FormCreate, employee: EmployeePrincipal) -> FormRead:
    form = service.create_form(db, payload=payload, employee=employee)
    return _read(db, form)


def duplicate_form(db: Session, form_id: int, employee: EmployeePrincipal) -> FormRead:
    form = service.duplicate_form(db, form_id=form_id, employee=employee)
    return _read(db, form)


def update_form(
    db: Session, form_id: int, payload: FormUpdate, employee: EmployeePrincipal
) -> FormRead:
    form = service.update_form(
        db, form_id=form_id, payload=payload, employee=employee
    )
    return _read(db, form)


def delete_form(db: Session, form_id: int, employee: EmployeePrincipal) -> None:
    service.delete_form(db, form_id=form_id, employee=employee)


def toggle_active(
    db: Session, form_id: int, active: bool, employee: EmployeePrincipal
) -> FormRead:
    form = service.toggle_active(db, form_id=form_id, active=active, employee=employee)
    return _read(db, form)


def reveal_form_results(
    db: Session, form_id: int, employee: EmployeePrincipal
) -> FormRead:
    form = service.reveal_form_results(db, form_id=form_id, employee=employee)
    return _read(db, form)


def rotate_public_token(
    db: Session, form_id: int, employee: EmployeePrincipal
) -> FormRead:
    form = service.rotate_public_token(db, form_id=form_id, employee=employee)
    return _read(db, form)


def revoke_public_token(
    db: Session, form_id: int, employee: EmployeePrincipal
) -> FormRead:
    form = service.revoke_public_token(db, form_id=form_id, employee=employee)
    return _read(db, form)


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


def publish_form(db: Session, form_id: int, employee: EmployeePrincipal) -> FormRead:
    return _read(db, service.publish_form(db, form_id=form_id, employee=employee))


def list_versions(db: Session, form_id: int, employee: EmployeePrincipal) -> list[FormVersionSummary]:
    return [
        FormVersionSummary.model_validate(v)
        for v in service.list_versions(db, form_id=form_id, employee=employee)
    ]


def get_version(db: Session, form_id: int, number: int, employee: EmployeePrincipal) -> FormVersionRead:
    form, version = service.get_version(db, form_id=form_id, number=number, employee=employee)
    snapshot = version.snapshot or {}
    fields = [FormFieldRead.model_validate(f) for f in snapshot.get("fields") or []]
    if not access.can_see_answers(employee, form):
        fields = _without_answers(fields)
    return FormVersionRead(
        id=version.id, number=version.number, published_at=version.published_at,
        published_by=version.published_by, type=snapshot.get("type", form.type),
        sections=snapshot.get("sections"), fields=fields,
        media=service.media_for(db, PublishedForm(form, version), with_theme=False),
    )


def diff_version(
    db: Session, form_id: int, number: int, against: Optional[str], employee: EmployeePrincipal
) -> FormVersionDiff:
    return service.diff_version(db, form_id=form_id, number=number, against=against, employee=employee)


def restore_version(db: Session, form_id: int, number: int, employee: EmployeePrincipal) -> FormRead:
    return _read(db, service.restore_version(db, form_id=form_id, number=number, employee=employee))
