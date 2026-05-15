from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import Unit


def get_descendant_unit_ids(db: Session, root_unit_id: int) -> list[int]:
    """Return root_unit_id plus every transitive child unit id."""
    base = (
        select(Unit.id, Unit.parent_unit_id)
        .where(Unit.id == root_unit_id)
        .cte(name="unit_tree", recursive=True)
    )
    tree = base.union_all(
        select(Unit.id, Unit.parent_unit_id).join(base, Unit.parent_unit_id == base.c.id)
    )
    rows = db.execute(select(tree.c.id)).all()
    return [row[0] for row in rows]


def get_unit(db: Session, unit_id: int) -> Optional[Unit]:
    return db.get(Unit, unit_id)


def get_unit_by_external_id(db: Session, external_id: str) -> Optional[Unit]:
    return db.execute(
        select(Unit).where(Unit.external_id == external_id)
    ).scalar_one_or_none()


def list_units(
    db: Session,
    *,
    organisation_id: int,
    limit: int = 200,
    offset: int = 0,
) -> list[Unit]:
    stmt = (
        select(Unit)
        .where(Unit.organisation_id == organisation_id)
        .order_by(Unit.name)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def count_units(db: Session, *, organisation_id: int) -> int:
    return db.execute(
        select(func.count()).select_from(Unit).where(Unit.organisation_id == organisation_id)
    ).scalar_one()


def create_unit(
    db: Session,
    *,
    name: str,
    organisation_id: int,
    type: Optional[str] = None,
    contact_info: Optional[str] = None,
    is_active: bool = True,
    parent_unit_id: Optional[int] = None,
    external_id: Optional[str] = None,
) -> Unit:
    unit = Unit(
        name=name,
        type=type,
        contact_info=contact_info,
        is_active=is_active,
        organisation_id=organisation_id,
        parent_unit_id=parent_unit_id,
        external_id=external_id,
    )
    db.add(unit)
    db.flush()
    return unit


def update_unit(db: Session, unit: Unit, *, data: dict) -> Unit:
    for key, value in data.items():
        setattr(unit, key, value)
    db.flush()
    return unit


def delete_unit(db: Session, unit: Unit) -> None:
    db.delete(unit)
