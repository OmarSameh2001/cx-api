from typing import Optional

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from modules.forms.model import Form


class FormLookup(BaseModel):
    id: int
    name: str


def search_forms(
    db: Session,
    *,
    allowed_unit_ids: list[int],
    search: Optional[str] = None,
    limit: int = 20,
) -> list[FormLookup]:
    stmt = select(Form).where(Form.is_active.is_(True), Form.is_archived.is_(False))
    if allowed_unit_ids:
        stmt = stmt.where(
            or_(
                Form.assigned_to_units.is_(None),
                Form.assigned_to_units.overlap(allowed_unit_ids),
            )
        )
    if search:
        stmt = stmt.where(Form.name.ilike(f"%{search}%"))
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [FormLookup(id=r.id, name=r.name) for r in rows]
