from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import (
    PermissionCreate,
    PermissionRead,
    RoleCreate,
    RolePermissionsAdd,
    RolePermissionsReplace,
    RoleRead,
    RoleSummary,
    RoleUpdate,
    SeedResult,
)
from .model import Role


def _to_role_read(role: Role) -> RoleRead:
    permissions = [rp.permission for rp in role.role_permissions]
    return RoleRead(
        id=role.id,
        name=role.name,
        is_system=role.is_system,
        permissions=[PermissionRead.model_validate(p) for p in permissions],
    )


def list_roles(db: Session, *, limit: int, offset: int) -> Page[RoleSummary]:
    items, total = service.list_roles(db, limit=limit, offset=offset)
    return Page(
        items=[RoleSummary.model_validate(r) for r in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_role(db: Session, role_id: int) -> RoleRead:
    return _to_role_read(service.get_role(db, role_id))


def create_role(db: Session, payload: RoleCreate, employee_id: int) -> RoleRead:
    return _to_role_read(
        service.create_role(db, payload=payload, employee_id=employee_id)
    )


def update_role(db: Session, role_id: int, payload: RoleUpdate) -> RoleRead:
    return _to_role_read(
        service.update_role(db, role_id=role_id, payload=payload)
    )


def delete_role(db: Session, role_id: int) -> None:
    service.delete_role(db, role_id=role_id)


def replace_role_permissions(
    db: Session,
    role_id: int,
    payload: RolePermissionsReplace,
    employee_id: int,
) -> RoleRead:
    return _to_role_read(
        service.replace_role_permissions(
            db,
            role_id=role_id,
            permission_ids=payload.permission_ids,
            employee_id=employee_id,
        )
    )


def add_role_permissions(
    db: Session,
    role_id: int,
    payload: RolePermissionsAdd,
    employee_id: int,
) -> RoleRead:
    return _to_role_read(
        service.add_role_permissions(
            db,
            role_id=role_id,
            permission_ids=payload.permission_ids,
            employee_id=employee_id,
        )
    )


def remove_role_permission(
    db: Session, role_id: int, permission_id: int
) -> None:
    service.remove_role_permission(db, role_id=role_id, permission_id=permission_id)


def list_permissions(db: Session) -> list[PermissionRead]:
    return [PermissionRead.model_validate(p) for p in service.list_permissions(db)]


def create_permission(db: Session, payload: PermissionCreate) -> PermissionRead:
    return PermissionRead.model_validate(
        service.create_permission(db, payload=payload)
    )


def delete_permission(db: Session, permission_id: int) -> None:
    service.delete_permission(db, permission_id=permission_id)


def seed_permissions(db: Session) -> SeedResult:
    created, existing = service.seed_permissions(db)
    return SeedResult(
        created=[PermissionRead.model_validate(p) for p in created],
        existing=existing,
    )
