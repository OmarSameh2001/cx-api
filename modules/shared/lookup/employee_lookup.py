from typing import Optional

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from modules.employees.model import Employee
from modules.units.model import Unit


class EmployeeLookup(BaseModel):
    id: int
    name: str
    email: str


def search_employees(
    db: Session,
    *,
    parent_unit_ids: list[int],
    search: Optional[str] = None,
    limit: int = 20,
) -> list[EmployeeLookup]:
    if not parent_unit_ids:
        return []
    stmt = (
        select(Employee)
        .join(Unit, Employee.unit_id == Unit.id)
        .where(
            Unit.parent_unit_id.in_(parent_unit_ids),
            Employee.is_active.is_(True),
        )
    )
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Employee.first_name.ilike(pattern),
                Employee.last_name.ilike(pattern),
            )
        )
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [
        EmployeeLookup(
            id=r.id,
            name=f"{r.first_name} {r.last_name}",
            email=r.email.split("@")[0],
        )
        for r in rows
    ]
