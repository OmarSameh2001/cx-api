from typing import Optional

from pydantic import BaseModel
from sqlalchemy import select
from sqlalchemy.orm import Session

from modules.roles.model import Role


class RoleLookup(BaseModel):
    id: int
    name: str


def search_roles(
    db: Session,
    *,
    search: Optional[str] = None,
    limit: int = 20,
) -> list[RoleLookup]:
    stmt = select(Role)
    if search:
        stmt = stmt.where(Role.name.ilike(f"%{search}%"))
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [RoleLookup(id=r.id, name=r.name) for r in rows]
