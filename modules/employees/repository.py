from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import Employee


def get_employee(db: Session, employee_id: int) -> Optional[Employee]:
    return db.get(Employee, employee_id)


def get_employee_by_email(db: Session, email: str) -> Optional[Employee]:
    return db.execute(select(Employee).where(Employee.email == email)).scalar_one_or_none()


def get_employee_by_username(db: Session, username: str) -> Optional[Employee]:
    return db.execute(
        select(Employee).where(Employee.username == username)
    ).scalar_one_or_none()


def get_employee_by_external_id(db: Session, external_id: str) -> Optional[Employee]:
    return db.execute(
        select(Employee).where(Employee.external_id == external_id)
    ).scalar_one_or_none()


def list_employees(
    db: Session,
    *,
    organisation_id: int,
    unit_ids: list[int] | None = None,
    limit: int = 100,
    offset: int = 0,
) -> list[Employee]:
    stmt = select(Employee).where(Employee.organisation_id == organisation_id)
    if unit_ids:
        stmt = stmt.where(Employee.unit_id.in_(unit_ids))
    else:
        return []
    stmt = stmt.order_by(Employee.last_name, Employee.first_name).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_employees(
    db: Session,
    *,
    organisation_id: int,
    unit_ids: list[int] | None = None,
) -> int:
    stmt = select(func.count()).select_from(Employee).where(Employee.organisation_id == organisation_id)
    if unit_ids:
        stmt = stmt.where(Employee.unit_id.in_(unit_ids))
    else:
        return 0
    return db.execute(stmt).scalar_one()


def create_employee(
    db: Session,
    *,
    first_name: str,
    last_name: str,
    username: str,
    email: str,
    password_hash: str,
    organisation_id: int,
    is_active: bool = True,
    external_id: Optional[str] = None,
    phone: Optional[str] = None,
    dob=None,
    gender: Optional[str] = None,
    manager_id: Optional[int] = None,
    unit_id: Optional[int] = None,
    role_id: Optional[int] = None,
    assigned_units: Optional[list[int]] = None,
) -> Employee:
    employee = Employee(
        first_name=first_name,
        last_name=last_name,
        username=username,
        email=email,
        password=password_hash,
        organisation_id=organisation_id,
        is_active=is_active,
        external_id=external_id,
        phone=phone,
        dob=dob,
        gender=gender,
        manager_id=manager_id,
        unit_id=unit_id,
        role_id=role_id,
        assigned_units=assigned_units or [],
    )
    db.add(employee)
    db.flush()
    return employee


def update_employee(db: Session, employee: Employee, *, data: dict) -> Employee:
    for key, value in data.items():
        setattr(employee, key, value)
    db.flush()
    return employee


def delete_employee(db: Session, employee: Employee) -> None:
    db.delete(employee)
