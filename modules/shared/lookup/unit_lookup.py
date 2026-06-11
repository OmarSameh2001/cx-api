from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.units.model import Unit


class UnitLookup(BaseModel):
    id: int
    name: str


def search_units(
    db: Session,
    *,
    allowed_ids: Optional[list[int]],
    organisation_id: Optional[int] = None,
    search: Optional[str] = None,
    limit: int = 20,
) -> list[UnitLookup]:
    stmt = select(Unit).where(Unit.is_active.is_(True))
    if allowed_ids is not None:
        if not allowed_ids:
            return []
        stmt = stmt.where(Unit.id.in_(allowed_ids))
    elif organisation_id is not None:
        stmt = stmt.where(Unit.organisation_id == organisation_id)
    if search:
        stmt = stmt.where(Unit.name.ilike(f"%{search}%"))
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [UnitLookup(id=r.id, name=r.name) for r in rows]
