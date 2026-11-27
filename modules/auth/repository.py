from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from config import AuthEnv
from modules.employees.model import Employee
from modules.roles.model import Permission, Role, RolePermission


def get_employee_by_email(db: Session, email: str) -> Optional[Employee]:
    """The account for a sign-in email, ignoring case (people type
    "Ali@x.com" for "ali@x.com"). An exact match wins; otherwise a
    case-insensitive one counts only if it's the only one."""
    email = email.strip()
    exact = db.execute(select(Employee).where(Employee.email == email)).scalar_one_or_none()
    if exact is not None:
        return exact
    matches = list(
        db.execute(
            select(Employee).where(func.lower(Employee.email) == email.lower()).limit(2)
        ).scalars()
    )
    return matches[0] if len(matches) == 1 else None


def get_employee_by_id(db: Session, employee_id: int) -> Optional[Employee]:
    return db.get(Employee, employee_id)


def get_role_claims(db: Session, role_id: int) -> Optional[tuple[str, bool, list[str]]]:
    """(name, is_system, ["resource:action", ...]) for the token, in one
    query; None if the role doesn't exist."""
    stmt = (
        select(Role.name, Role.is_system, Permission.resource, Permission.action)
        .outerjoin(RolePermission, RolePermission.role_id == Role.id)
        .outerjoin(Permission, Permission.id == RolePermission.permission_id)
        .where(Role.id == role_id)
        .order_by(RolePermission.id)
    )
    rows = db.execute(stmt).all()
    if not rows:
        return None
    permissions = [f"{r.resource}:{r.action}" for r in rows if r.resource is not None]
    return rows[0].name, rows[0].is_system, permissions


def _principal(db: Session, principal_type: str, principal_id: int, *, lock: bool = False):
    """The account row. With lock, it's locked until the commit and read
    fresh, so two sign-ins or refreshes at the same moment change the
    session list one after the other instead of overwriting each other."""
    if principal_type == "employee":
        if lock:
            return db.get(Employee, principal_id, with_for_update=True, populate_existing=True)
        return db.get(Employee, principal_id)
    return None


def add_refresh_jti(db: Session, principal_type: str, principal_id: int, jti: str) -> None:
    row = _principal(db, principal_type, principal_id, lock=True)
    if row is None:
        return
    tokens = [*(row.refresh_tokens or []), jti]
    row.refresh_tokens = tokens[-AuthEnv.MAX_REFRESH_TOKENS_PER_USER:]
    db.commit()


def has_refresh_jti(db: Session, principal_type: str, principal_id: int, jti: str) -> bool:
    row = _principal(db, principal_type, principal_id)
    return bool(row and jti in (row.refresh_tokens or []))


def remove_refresh_jti(db: Session, principal_type: str, principal_id: int, jti: str) -> int:
    row = _principal(db, principal_type, principal_id, lock=True)
    if row is None:
        return 0
    current = row.refresh_tokens or []
    if jti not in current:
        return 0
    row.refresh_tokens = [t for t in current if t != jti]
    db.commit()
    return 1


def clear_refresh_jtis(db: Session, principal_type: str, principal_id: int) -> int:
    row = _principal(db, principal_type, principal_id, lock=True)
    if row is None:
        return 0
    count = len(row.refresh_tokens or [])
    row.refresh_tokens = []
    db.commit()
    return count
