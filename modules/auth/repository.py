from typing import Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from config import AuthEnv
from modules.customers.model import Customer
from modules.employees.model import Employee
from modules.roles.model import Permission, Role, RolePermission


def get_employee_by_email(db: Session, email: str) -> Optional[Employee]:
    return db.execute(select(Employee).where(Employee.email == email)).scalar_one_or_none()


def get_employee_by_id(db: Session, employee_id: int) -> Optional[Employee]:
    return db.get(Employee, employee_id)


def get_customer_by_email(db: Session, email: str) -> Optional[Customer]:
    return db.execute(select(Customer).where(Customer.email == email)).scalar_one_or_none()


def get_customer_by_id(db: Session, customer_id: int) -> Optional[Customer]:
    return db.get(Customer, customer_id)


def get_role_with_permissions(db: Session, role_id: int) -> Optional[Role]:
    stmt = (
        select(Role)
        .where(Role.id == role_id)
        .options(selectinload(Role.role_permissions).selectinload(RolePermission.permission))
    )
    return db.execute(stmt).scalar_one_or_none()


def list_permission_names_for_role(db: Session, role_id: int) -> list[str]:
    stmt = (
        select(Permission.resource, Permission.action)
        .join(RolePermission, RolePermission.permission_id == Permission.id)
        .where(RolePermission.role_id == role_id)
    )
    return [f"{resource}:{action}" for resource, action in db.execute(stmt).all()]


def _principal(db: Session, principal_type: str, principal_id: int):
    if principal_type == "employee":
        return db.get(Employee, principal_id)
    if principal_type == "customer":
        return db.get(Customer, principal_id)
    return None


def add_refresh_jti(db: Session, principal_type: str, principal_id: int, jti: str) -> None:
    row = _principal(db, principal_type, principal_id)
    if row is None:
        return
    tokens = [*(row.refresh_tokens or []), jti]
    row.refresh_tokens = tokens[-AuthEnv.MAX_REFRESH_TOKENS_PER_USER:]
    db.commit()


def has_refresh_jti(db: Session, principal_type: str, principal_id: int, jti: str) -> bool:
    row = _principal(db, principal_type, principal_id)
    return bool(row and jti in (row.refresh_tokens or []))


def remove_refresh_jti(db: Session, principal_type: str, principal_id: int, jti: str) -> int:
    row = _principal(db, principal_type, principal_id)
    if row is None:
        return 0
    current = row.refresh_tokens or []
    if jti not in current:
        return 0
    row.refresh_tokens = [t for t in current if t != jti]
    db.commit()
    return 1


def clear_refresh_jtis(db: Session, principal_type: str, principal_id: int) -> int:
    row = _principal(db, principal_type, principal_id)
    if row is None:
        return 0
    count = len(row.refresh_tokens or [])
    row.refresh_tokens = []
    db.commit()
    return count
