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


def list_forms(
    db: Session,
    *,
    is_active: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    submitter_type: Optional[str] = None,
    created_by: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Form]:
    stmt = select(Form)
    if is_active is not None:
        stmt = stmt.where(Form.is_active.is_(is_active))
    if is_archived is not None:
        stmt = stmt.where(Form.is_archived.is_(is_archived))
    if submitter_type is not None:
        stmt = stmt.where(Form.submitter_type.any(submitter_type))
    if created_by is not None:
        stmt = stmt.where(Form.created_by == created_by)
    stmt = stmt.order_by(Form.created_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_forms(
    db: Session,
    *,
    is_active: Optional[bool] = None,
    is_archived: Optional[bool] = None,
    submitter_type: Optional[str] = None,
    created_by: Optional[int] = None,
) -> int:
    stmt = select(func.count()).select_from(Form)
    if is_active is not None:
        stmt = stmt.where(Form.is_active.is_(is_active))
    if is_archived is not None:
        stmt = stmt.where(Form.is_archived.is_(is_archived))
    if submitter_type is not None:
        stmt = stmt.where(Form.submitter_type.any(submitter_type))
    if created_by is not None:
        stmt = stmt.where(Form.created_by == created_by)
    return db.execute(stmt).scalar_one()


def create_form(db: Session, *, data: dict, fields: list[dict], created_by: int) -> Form:
    form = Form(**data, created_by=created_by)
    for f in fields:
        form.fields.append(FormField(**f))
    db.add(form)
    db.commit()
    db.refresh(form)
    return form


def update_form(db: Session, form: Form, *, data: dict, fields: Optional[list[dict]]) -> Form:
    for key, value in data.items():
        setattr(form, key, value)
    if fields is not None:
        form.fields.clear()
        db.flush()
        for f in fields:
            form.fields.append(FormField(**f))
    db.commit()
    db.refresh(form)
    return form


def delete_form(db: Session, form: Form) -> None:
    db.delete(form)
    db.commit()
