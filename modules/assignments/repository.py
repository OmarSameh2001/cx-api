from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.units.model import Unit

from .model import Assignment


def get_assignment(db: Session, assignment_id: int) -> Optional[Assignment]:
    return db.get(Assignment, assignment_id)


def _in_organisation(stmt, organisation_id: int):
    # an assignment's organisation is its unit's
    return stmt.join(Unit, Assignment.unit_id == Unit.id).where(
        Unit.organisation_id == organisation_id
    )


def list_assignments(
    db: Session,
    *,
    organisation_id: int,
    user_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    assigned_by: Optional[int] = None,
    limit: int = 50,
    offset: int = 0,
) -> list[Assignment]:
    stmt = _in_organisation(select(Assignment), organisation_id)
    if user_id is not None:
        stmt = stmt.where(Assignment.user_id == user_id)
    if unit_id is not None:
        stmt = stmt.where(Assignment.unit_id == unit_id)
    if assigned_by is not None:
        stmt = stmt.where(Assignment.assigned_by == assigned_by)
    stmt = stmt.order_by(Assignment.assigned_at.desc()).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_assignments(
    db: Session,
    *,
    organisation_id: int,
    user_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    assigned_by: Optional[int] = None,
) -> int:
    stmt = _in_organisation(select(func.count()).select_from(Assignment), organisation_id)
    if user_id is not None:
        stmt = stmt.where(Assignment.user_id == user_id)
    if unit_id is not None:
        stmt = stmt.where(Assignment.unit_id == unit_id)
    if assigned_by is not None:
        stmt = stmt.where(Assignment.assigned_by == assigned_by)
    return db.execute(stmt).scalar_one()


def create_assignment(
    db: Session,
    *,
    user_id: int,
    unit_id: int,
    description: Optional[str],
    assigned_by: Optional[int],
) -> Assignment:
    assignment = Assignment(
        user_id=user_id,
        unit_id=unit_id,
        description=description,
        assigned_by=assigned_by,
    )
    db.add(assignment)
    db.commit()
    db.refresh(assignment)
    return assignment


def update_assignment(
    db: Session, assignment: Assignment, *, data: dict
) -> Assignment:
    for key, value in data.items():
        setattr(assignment, key, value)
    db.commit()
    db.refresh(assignment)
    return assignment


def delete_assignment(db: Session, assignment: Assignment) -> None:
    db.delete(assignment)
    db.commit()
