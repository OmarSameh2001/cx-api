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
    allowed_ids: list[int],
    search: Optional[str] = None,
    limit: int = 20,
) -> list[UnitLookup]:
    if not allowed_ids:
        return []
    stmt = select(Unit).where(Unit.id.in_(allowed_ids), Unit.is_active.is_(True))
    if search:
        stmt = stmt.where(Unit.name.ilike(f"%{search}%"))
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [UnitLookup(id=r.id, name=r.name) for r in rows]
