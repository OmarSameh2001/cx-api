from typing import Optional

from sqlalchemy import func, or_, select
from sqlalchemy.orm import Session

from .model import Customer


def get_by_email(db: Session, *, organisation_id: int, email: str) -> Optional[Customer]:
    stmt = select(Customer).where(
        Customer.organisation_id == organisation_id,
        func.lower(Customer.email) == email.strip().lower(),
    )
    return db.execute(stmt).scalar_one_or_none()


def create(
    db: Session,
    *,
    organisation_id: int,
    email: str,
    first_name: str,
    last_name: str,
    phone: Optional[str],
) -> Customer:
    customer = Customer(
        organisation_id=organisation_id,
        email=email.strip().lower(),
        first_name=first_name.strip(),
        last_name=last_name.strip(),
        phone=phone.strip() if phone else None,
    )
    db.add(customer)
    db.flush()  # assigns the id
    return customer


def search(
    db: Session, *, organisation_id: int, search: Optional[str], limit: int
) -> list[Customer]:
    stmt = select(Customer).where(Customer.organisation_id == organisation_id)
    if search:
        pattern = f"%{search}%"
        stmt = stmt.where(
            or_(Customer.first_name.ilike(pattern), Customer.last_name.ilike(pattern))
        )
    return list(db.execute(stmt.order_by(Customer.id).limit(limit)).scalars().all())
