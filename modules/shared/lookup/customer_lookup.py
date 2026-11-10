from typing import Optional

from pydantic import BaseModel
from sqlalchemy.orm import Session

from modules.customers import repository as customers_repository


class CustomerLookup(BaseModel):
    id: int
    name: str
    email: str


def search_customers(
    db: Session,
    *,
    organisation_id: int,
    search: Optional[str] = None,
    limit: int = 20,
) -> list[CustomerLookup]:
    rows = customers_repository.search(
        db, organisation_id=organisation_id, search=search, limit=limit
    )
    return [
        CustomerLookup(
            id=r.id,
            name=f"{r.first_name} {r.last_name}",
            email=r.email.split("@")[0],
        )
        for r in rows
    ]
