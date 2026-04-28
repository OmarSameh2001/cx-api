from typing import Iterable, Optional

from sqlalchemy import select
from sqlalchemy.orm import Session, selectinload

from .model import Permission, Role, RolePermission


def get_role(db: Session, role_id: int) -> Optional[Role]:
    stmt = (
        select(Role)
        .where(Role.id == role_id)
        .options(
            selectinload(Role.role_permissions).selectinload(RolePermission.permission)
        )
    )
    return db.execute(stmt).scalar_one_or_none()


def get_role_by_name(db: Session, name: str) -> Optional[Role]:
    return db.execute(select(Role).where(Role.name == name)).scalar_one_or_none()


def list_roles(db: Session, *, limit: int = 100, offset: int = 0) -> list[Role]:
    stmt = select(Role).order_by(Role.name).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def create_role(db: Session, *, name: str, is_system: bool) -> Role:
    role = Role(name=name, is_system=is_system)
    db.add(role)
    db.flush()
    return role


def update_role(db: Session, role: Role, *, data: dict) -> Role:
    for key, value in data.items():
        setattr(role, key, value)
    db.flush()
    return role


def delete_role(db: Session, role: Role) -> None:
    db.delete(role)


def get_permission(db: Session, permission_id: int) -> Optional[Permission]:
    return db.get(Permission, permission_id)


def get_permission_by_pair(
    db: Session, resource: str, action: str
) -> Optional[Permission]:
    stmt = select(Permission).where(
        Permission.resource == resource, Permission.action == action
    )
    return db.execute(stmt).scalar_one_or_none()


def list_permissions(db: Session) -> list[Permission]:
    stmt = select(Permission).order_by(Permission.resource, Permission.action)
    return list(db.execute(stmt).scalars().all())


def list_permissions_by_ids(
    db: Session, permission_ids: Iterable[int]
) -> list[Permission]:
    ids = list({i for i in permission_ids})
    if not ids:
        return []
    stmt = select(Permission).where(Permission.id.in_(ids))
    return list(db.execute(stmt).scalars().all())


def create_permission(db: Session, *, resource: str, action: str) -> Permission:
    permission = Permission(resource=resource, action=action)
    db.add(permission)
    db.flush()
    return permission


def delete_permission(db: Session, permission: Permission) -> None:
    db.delete(permission)


def replace_role_permissions(
    db: Session,
    role: Role,
    *,
    permission_ids: list[int],
    updated_by: Optional[int],
) -> Role:
    role.role_permissions.clear()
    db.flush()
    for permission_id in dict.fromkeys(permission_ids):
        db.add(
            RolePermission(
                role_id=role.id,
                permission_id=permission_id,
                updated_by=updated_by,
            )
        )
    db.flush()
    return role


def add_role_permissions(
    db: Session,
    role: Role,
    *,
    permission_ids: list[int],
    updated_by: Optional[int],
) -> Role:
    existing = {rp.permission_id for rp in role.role_permissions}
    for permission_id in dict.fromkeys(permission_ids):
        if permission_id in existing:
            continue
        db.add(
            RolePermission(
                role_id=role.id,
                permission_id=permission_id,
                updated_by=updated_by,
            )
        )
    db.flush()
    return role


def remove_role_permission(
    db: Session, role_id: int, permission_id: int
) -> int:
    stmt = select(RolePermission).where(
        RolePermission.role_id == role_id,
        RolePermission.permission_id == permission_id,
    )
    rp = db.execute(stmt).scalar_one_or_none()
    if rp is None:
        return 0
    db.delete(rp)
    db.flush()
    return 1
