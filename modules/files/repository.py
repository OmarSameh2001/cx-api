from datetime import datetime
from typing import Optional

from sqlalchemy import and_, delete, func, or_, select, update
from sqlalchemy.orm import Session

from .model import FileLimit, StoredFile


# --- files -------------------------------------------------------------------

def add_file(db: Session, file: StoredFile) -> StoredFile:
    """Adds to the caller's transaction and flushes (for the id)."""
    db.add(file)
    db.flush()
    return file


def get_file(db: Session, file_id: int, *, for_update: bool = False) -> Optional[StoredFile]:
    stmt = select(StoredFile).where(StoredFile.id == file_id)
    if for_update:
        stmt = stmt.with_for_update()
    return db.execute(stmt).scalar_one_or_none()


def get_files(db: Session, file_ids: list[int]) -> dict[int, StoredFile]:
    if not file_ids:
        return {}
    rows = db.execute(select(StoredFile).where(StoredFile.id.in_(file_ids))).scalars().all()
    return {f.id: f for f in rows}


def list_files(
    db: Session,
    *,
    organisation_id: int,
    purpose: Optional[str],
    attached_type: Optional[str],
    attached_id: Optional[int],
    owner_employee_id: Optional[int],
    limit: int,
    offset: int,
) -> tuple[list[StoredFile], int]:
    stmt = select(StoredFile).where(
        StoredFile.organisation_id == organisation_id, StoredFile.status == "ready"
    )
    if purpose:
        stmt = stmt.where(StoredFile.purpose == purpose)
    if attached_type:
        stmt = stmt.where(StoredFile.attached_type == attached_type)
    if attached_id is not None:
        stmt = stmt.where(StoredFile.attached_id == attached_id)
    if owner_employee_id is not None:
        stmt = stmt.where(StoredFile.owner_employee_id == owner_employee_id)
    total = db.execute(select(func.count()).select_from(stmt.subquery())).scalar_one()
    rows = db.execute(stmt.order_by(StoredFile.id.desc()).limit(limit).offset(offset)).scalars().all()
    return list(rows), total


def attached_files(db: Session, attached_type: str, attached_ids: list[int]) -> list[StoredFile]:
    if not attached_ids:
        return []
    stmt = select(StoredFile).where(
        StoredFile.attached_type == attached_type,
        StoredFile.attached_id.in_(attached_ids),
        StoredFile.status != "deleted",
    )
    return list(db.execute(stmt).scalars().all())


def mark_deleted_for(db: Session, attached_type: str, attached_ids: list[int], now: datetime) -> int:
    """Marks every file attached to these records as deleted (no commit)."""
    if not attached_ids:
        return 0
    result = db.execute(
        update(StoredFile)
        .where(
            StoredFile.attached_type == attached_type,
            StoredFile.attached_id.in_(attached_ids),
            StoredFile.status != "deleted",
        )
        .values(status="deleted", deleted_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def mark_deleted_for_form(db: Session, form_id: int, now: datetime) -> int:
    result = db.execute(
        update(StoredFile)
        .where(StoredFile.form_id == form_id, StoredFile.status != "deleted")
        .values(status="deleted", deleted_at=now)
        .execution_options(synchronize_session=False)
    )
    return result.rowcount or 0


def cleanup_candidates(
    db: Session, *, pending_before: datetime, unattached_before: datetime, limit: int
) -> list[StoredFile]:
    """Deleted files, uploads never completed, and ready files nothing ever
    used. Purposes that are never attached (none yet) are not swept."""
    stmt = (
        select(StoredFile)
        .where(
            or_(
                StoredFile.status == "deleted",
                and_(StoredFile.status == "pending", StoredFile.created_at < pending_before),
                and_(
                    StoredFile.status == "ready",
                    StoredFile.attached_type.is_(None),
                    StoredFile.created_at < unattached_before,
                ),
            )
        )
        .order_by(StoredFile.id)
        .limit(limit)
        .with_for_update(skip_locked=True)
    )
    return list(db.execute(stmt).scalars().all())


def delete_file_row(db: Session, file: StoredFile) -> None:
    db.delete(file)


def files_of_organisations(db: Session, organisation_ids: list[int]) -> list[StoredFile]:
    if not organisation_ids:
        return []
    stmt = select(StoredFile).where(StoredFile.organisation_id.in_(organisation_ids))
    return list(db.execute(stmt).scalars().all())


# --- limits -----------------------------------------------------------------

def get_limit(db: Session, *, organisation_id: Optional[int], purpose: str) -> Optional[FileLimit]:
    stmt = select(FileLimit).where(FileLimit.purpose == purpose)
    stmt = stmt.where(
        FileLimit.organisation_id.is_(None) if organisation_id is None else FileLimit.organisation_id == organisation_id
    )
    return db.execute(stmt).scalar_one_or_none()


def limits_for(db: Session, *, organisation_id: int, purpose: str) -> tuple[Optional[FileLimit], Optional[FileLimit]]:
    """(platform row, organisation row) for one purpose."""
    rows = db.execute(
        select(FileLimit).where(
            FileLimit.purpose == purpose,
            or_(FileLimit.organisation_id.is_(None), FileLimit.organisation_id == organisation_id),
        )
    ).scalars().all()
    platform = next((r for r in rows if r.organisation_id is None), None)
    org = next((r for r in rows if r.organisation_id == organisation_id), None)
    return platform, org


def save_limit(db: Session, row: FileLimit) -> FileLimit:
    db.add(row)
    db.commit()
    db.refresh(row)
    return row


def delete_limit(db: Session, row: FileLimit) -> None:
    db.delete(row)
    db.commit()


def delete_limits(db: Session, *, organisation_id: Optional[int], purpose: str) -> None:
    stmt = delete(FileLimit).where(FileLimit.purpose == purpose)
    stmt = stmt.where(
        FileLimit.organisation_id.is_(None) if organisation_id is None else FileLimit.organisation_id == organisation_id
    )
    db.execute(stmt)
    db.commit()
