from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session, selectinload

from .model import Form, FormField


def get_form(db: Session, form_id: int) -> Optional[Form]:
    stmt = (
        select(Form)
        .where(Form.id == form_id)
        .options(selectinload(Form.fields))
    )
    return db.execute(stmt).scalar_one_or_none()


def get_form_by_token(db: Session, token: str) -> Optional[Form]:
    stmt = (
        select(Form)
        .where(Form.public_token == token)
        .options(selectinload(Form.fields))
    )
    return db.execute(stmt).scalar_one_or_none()


def _apply_filters(
    stmt,
    *,
    organisation_id,
    is_active,
    is_archived,
    submitter_type,
    created_by,
    name=None,
    form_type=None,
):
    if organisation_id is not None:
        stmt = stmt.where(Form.organisation_id == organisation_id)
    if is_active is not None:
        stmt = stmt.where(Form.is_active.is_(is_active))
    if is_archived is not None:
        stmt = stmt.where(Form.is_archived.is_(is_archived))
    if submitter_type is not None:
        stmt = stmt.where(Form.submitter_type.any(submitter_type))
    if created_by is not None:
        stmt = stmt.where(Form.created_by == created_by)
    if name is not None:
        stmt = stmt.where(Form.name.ilike(f"%{name}%"))
    if form_type is not None:
        stmt = stmt.where(Form.type == form_type)
    return stmt


def list_forms(
    db: Session,
    *,
    organisation_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    submitter_type: Optional[str] = None,
    created_by: Optional[int] = None,
    name: Optional[str] = None,
    form_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Form]:
    stmt = _apply_filters(
        select(Form),
        organisation_id=organisation_id,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        name=name,
        form_type=form_type,
    )
    stmt = stmt.order_by(Form.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_forms(
    db: Session,
    *,
    organisation_id: Optional[int] = None,
    is_active: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    submitter_type: Optional[str] = None,
    created_by: Optional[int] = None,
    name: Optional[str] = None,
    form_type: Optional[str] = None,
) -> int:
    stmt = _apply_filters(
        select(func.count()).select_from(Form),
        organisation_id=organisation_id,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        name=name,
        form_type=form_type,
    )
    return db.execute(stmt).scalar_one()


def list_forms_assigned(
    db: Session,
    *,
    organisation_id: int,
    submitter_type: str,
    unit_ids: list[int],
    name: Optional[str] = None,
    form_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Form]:
    stmt = (
        select(Form)
        .where(Form.organisation_id == organisation_id)
        .where(Form.is_active.is_(True))
        .where(Form.is_archived.is_(False))
        .where(Form.submitter_type.any(submitter_type))
    )
    no_unit_restriction = (Form.assigned_to_units.is_(None)) | (func.cardinality(Form.assigned_to_units) == 0)
    if unit_ids:
        stmt = stmt.where(no_unit_restriction | Form.assigned_to_units.overlap(unit_ids))
    else:
        stmt = stmt.where(no_unit_restriction)
    if name is not None:
        stmt = stmt.where(Form.name.ilike(f"%{name}%"))
    if form_type is not None:
        stmt = stmt.where(Form.type == form_type)
    stmt = stmt.order_by(Form.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_forms_assigned(
    db: Session,
    *,
    organisation_id: int,
    submitter_type: str,
    unit_ids: list[int],
    name: Optional[str] = None,
    form_type: Optional[str] = None,
) -> int:
    stmt = (
        select(func.count())
        .select_from(Form)
        .where(Form.organisation_id == organisation_id)
        .where(Form.is_active.is_(True))
        .where(Form.is_archived.is_(False))
        .where(Form.submitter_type.any(submitter_type))
    )
    no_unit_restriction = (Form.assigned_to_units.is_(None)) | (func.cardinality(Form.assigned_to_units) == 0)
    if unit_ids:
        stmt = stmt.where(no_unit_restriction | Form.assigned_to_units.overlap(unit_ids))
    else:
        stmt = stmt.where(no_unit_restriction)
    if name is not None:
        stmt = stmt.where(Form.name.ilike(f"%{name}%"))
    if form_type is not None:
        stmt = stmt.where(Form.type == form_type)
    return db.execute(stmt).scalar_one()


def create_form(db: Session, *, data: dict, fields: list[dict], created_by: int) -> Form:
    form = Form(**data, created_by=created_by)
    for f in fields:
        form.fields.append(FormField(**f))
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


def set_public_token(db: Session, form: Form, token: Optional[str]) -> Form:
    form.public_token = token
    db.commit()
    db.refresh(form)
    return form


def update_form(db: Session, form: Form, *, data: dict, fields: Optional[list[dict]]) -> Form:
    try:
        for key, value in data.items():
            setattr(form, key, value)
        if fields is not None:
            form.fields.clear()
            db.flush()
            for f in fields:
                form.fields.append(FormField(**f))
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(form)
    return form


def delete_form(db: Session, form: Form) -> None:
    db.delete(form)
    db.commit()
