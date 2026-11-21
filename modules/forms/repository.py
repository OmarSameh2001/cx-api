from typing import Callable, Optional

from sqlalchemy import delete, func, select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session, selectinload

from .model import Form, FormField, FormVersion, new_field_key


def get_form(db: Session, form_id: int) -> Optional[Form]:
    stmt = (
        select(Form)
        .where(Form.id == form_id)
        .options(selectinload(Form.fields), selectinload(Form.current_version))
    )
    return db.execute(stmt).scalar_one_or_none()


def get_form_by_token(db: Session, token: str) -> Optional[Form]:
    stmt = (
        select(Form)
        .where(Form.public_token == token)
        .options(selectinload(Form.fields), selectinload(Form.current_version))
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
    limit: Optional[int] = 50,  # None: every matching form
    offset: int = 0,
) -> list[Form]:
    stmt = (
        select(Form)
        .where(Form.organisation_id == organisation_id)
        .where(Form.is_active.is_(True))
        .where(Form.is_archived.is_(False))
        .where(Form.submitter_type.any(submitter_type))
        .where(Form.current_version_id.is_not(None))
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
        .where(Form.current_version_id.is_not(None))
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


def create_form(
    db: Session,
    *,
    data: dict,
    fields: list[dict],
    created_by: int,
    before_commit: Optional[Callable[[Form], None]] = None,
) -> Form:
    """`before_commit` runs after the flush (the form has its id) and inside
    the same transaction, e.g. to emit an outbox event."""
    form = Form(**data, created_by=created_by)
    for f in fields:
        f.pop("id", None)
        form.fields.append(_new_field(f))
    db.add(form)
    if before_commit is not None:
        db.flush()
        before_commit(form)
    db.commit()
    db.refresh(form)
    return form


def _new_field(data: dict) -> FormField:
    data = {k: v for k, v in data.items() if k != "key"}
    return FormField(**data, key=new_field_key())


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
            # diff by id so existing fields (and answers keyed by their id) survive
            existing = {f.id: f for f in form.fields}
            kept: set[int] = set()
            for f in fields:
                field_id = f.pop("id", None)
                if field_id is not None and field_id in existing:
                    obj = existing[field_id]
                    if "type" in f and f["type"] != obj.type:
                        # answers of another type aren't comparable across versions
                        obj.key = new_field_key()
                    for key, value in f.items():
                        setattr(obj, key, value)
                    kept.add(field_id)
                else:
                    form.fields.append(_new_field(f))
            for field_id, obj in existing.items():
                if field_id not in kept:
                    form.fields.remove(obj)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(form)
    return form


def form_has_submissions(db: Session, form_id: int) -> bool:
    """True once a response has been submitted. Drafts don't count: opening a
    form shouldn't freeze it, and a draft is checked against the current
    structure when it is submitted."""
    from modules.submissions.model import Submission

    stmt = (
        select(Submission.id)
        .where(
            Submission.form_id == form_id,
            Submission.status.in_(("submitted", "late")),
        )
        .limit(1)
    )
    return db.execute(stmt).first() is not None


def delete_form(db: Session, form: Form) -> bool:
    """Deletes the form with its unfinished submissions (drafts, expired).
    False, with nothing deleted, if a response still references it."""
    from modules.submissions.model import Submission

    try:
        db.execute(
            delete(Submission)
            .where(
                Submission.form_id == form.id,
                Submission.status.in_(("in_progress", "expired")),
            )
            .execution_options(synchronize_session=False)
        )
        db.delete(form)
        db.commit()
    except IntegrityError:
        db.rollback()
        return False
    return True


# --- versions --------------------------------------------------------------------


def add_version(db: Session, form: Form, *, snapshot: dict, published_by: Optional[int]) -> FormVersion:
    """Publishes `snapshot` as the form's next version and makes it current.
    Flushes, doesn't commit: the caller commits with its other changes."""
    last = db.execute(
        select(func.max(FormVersion.number)).where(FormVersion.form_id == form.id)
    ).scalar()
    version = FormVersion(
        form_id=form.id, number=(last or 0) + 1, snapshot=snapshot, published_by=published_by
    )
    db.add(version)
    db.flush()
    form.current_version = version
    form.current_version_id = version.id
    return version


def list_versions(db: Session, form_id: int) -> list[FormVersion]:
    stmt = select(FormVersion).where(FormVersion.form_id == form_id).order_by(FormVersion.number.desc())
    return list(db.execute(stmt).scalars().all())


def get_version(db: Session, form_id: int, number: int) -> Optional[FormVersion]:
    stmt = select(FormVersion).where(FormVersion.form_id == form_id, FormVersion.number == number)
    return db.execute(stmt).scalar_one_or_none()


def count_submissions_by_version(db: Session, form_id: int) -> dict[int, int]:
    """Finalized submissions per version id."""
    from modules.submissions.model import Submission

    stmt = (
        select(Submission.form_version_id, func.count())
        .where(Submission.form_id == form_id, Submission.status.in_(("submitted", "late")))
        .group_by(Submission.form_version_id)
    )
    return {vid: n for vid, n in db.execute(stmt).all() if vid is not None}


def restore_draft(db: Session, form: Form, *, sections: Optional[list[dict]], fields: list[dict]) -> Form:
    """Makes the draft match a version's structure. Questions are matched by
    key, so a question still in the draft keeps its id; one the draft lost
    comes back with its old key and a new id."""
    try:
        form.sections = sections
        existing = {f.key: f for f in form.fields}
        kept: set[str] = set()
        for f in fields:
            data = {k: v for k, v in f.items() if k != "id"}
            obj = existing.get(data["key"])
            if obj is not None:
                for key, value in data.items():
                    setattr(obj, key, value)
            else:
                form.fields.append(FormField(**data))
            kept.add(data["key"])
        for key, obj in existing.items():
            if key not in kept:
                form.fields.remove(obj)
        db.commit()
    except Exception:
        db.rollback()
        raise
    db.refresh(form)
    return form
