from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from modules.employees.model import Employee
from modules.organisations.model import Organisation

from .model import UserIdentity


def get_identity(db: Session, provider: str, subject: str) -> Optional[UserIdentity]:
    return db.execute(
        select(UserIdentity).where(UserIdentity.provider == provider, UserIdentity.subject == subject)
    ).scalar_one_or_none()


def identity_of(db: Session, employee_id: int, provider: str) -> Optional[UserIdentity]:
    return db.execute(
        select(UserIdentity).where(UserIdentity.employee_id == employee_id, UserIdentity.provider == provider)
    ).scalar_one_or_none()


def identities_of(db: Session, employee_id: int) -> list[UserIdentity]:
    return list(
        db.execute(
            select(UserIdentity).where(UserIdentity.employee_id == employee_id).order_by(UserIdentity.id)
        ).scalars()
    )


def get_owned_identity(db: Session, employee_id: int, identity_id: int) -> Optional[UserIdentity]:
    return db.execute(
        select(UserIdentity).where(UserIdentity.id == identity_id, UserIdentity.employee_id == employee_id)
    ).scalar_one_or_none()


def add_identity(db: Session, identity: UserIdentity) -> UserIdentity:
    db.add(identity)
    db.flush()
    return identity


def delete_identity(db: Session, identity: UserIdentity) -> None:
    db.delete(identity)


def employees_with_email(db: Session, email: str) -> list[Employee]:
    """Every employee whose email matches, ignoring case (at most two, which
    is enough to tell one from many)."""
    return list(
        db.execute(select(Employee).where(func.lower(Employee.email) == email.lower()).limit(2)).scalars()
    )


def get_employee(db: Session, employee_id: int) -> Optional[Employee]:
    return db.get(Employee, employee_id)


def get_organisation(db: Session, organisation_id: int) -> Optional[Organisation]:
    return db.get(Organisation, organisation_id)
