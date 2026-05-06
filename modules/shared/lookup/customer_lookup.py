from typing import Optional

from pydantic import BaseModel
from sqlalchemy import or_, select
from sqlalchemy.orm import Session

from modules.customers.model import Customer


class CustomerLookup(BaseModel):
    id: int
    name: str
    email: str


def search_customers(
    db: Session,
    *,
    search: Optional[str] = None,
    limit: int = 20,
) -> list[CustomerLookup]:
    stmt = select(Customer)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(
                Customer.first_name.ilike(pattern),
                Customer.last_name.ilike(pattern),
            )
        )
    rows = db.execute(stmt.limit(limit)).scalars().all()
    return [
        CustomerLookup(
            id=r.id,
            name=f"{r.first_name} {r.last_name}",
            email=r.email.split("@")[0],
        )
        for r in rows
    ]
