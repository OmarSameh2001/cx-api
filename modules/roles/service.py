from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.audit import service as audit

from . import repository
from .dto import PermissionCreate, RoleCreate, RoleUpdate
from .model import Permission, Role
from .permissions import DEFAULT_ROLES, PermissionKey


def _ensure_role(db: Session, role_id: int, organisation_id: int) -> Role:
    # A role of another organisation is reported as missing, not forbidden,
    # so its existence does not leak.
    role = repository.get_role(db, role_id, organisation_id)
    if role is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Role not found")
    return role


def _ensure_permission(db: Session, permission_id: int) -> Permission:
    permission = repository.get_permission(db, permission_id)
    if permission is None:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Permission {permission_id} not found"
        )
    return permission


def _ensure_permissions_exist(db: Session, permission_ids: list[int]) -> None:
    unique_ids = list(dict.fromkeys(permission_ids))
    if not unique_ids:
        return
    found = repository.list_permissions_by_ids(db, unique_ids)
    found_ids = {p.id for p in found}
    missing = [pid for pid in unique_ids if pid not in found_ids]
    if missing:
        raise HTTPException(
            status.HTTP_404_NOT_FOUND, f"Permissions not found: {missing}"
        )


def _current_permission_ids(role: Role) -> set[int]:
    return {rp.permission_id for rp in role.role_permissions}


def _permission_change(db: Session, before: set[int], after: set[int]) -> dict | None:
    """The role's permissions as a change-log entry: keys added and removed."""
    added, removed = after - before, before - after
    if not added and not removed:
        return None
    keys = {p.id: f"{p.resource}:{p.action}" for p in repository.list_permissions_by_ids(db, sorted(added | removed))}
    return {
        "added": sorted(keys.get(i, f"#{i}") for i in added),
        "removed": sorted(keys.get(i, f"#{i}") for i in removed),
    }


def _record_permissions_changed(db: Session, role: Role, before: set[int], after: set[int]) -> None:
    change = _permission_change(db, before, after)
    if change is not None:
        audit.record(db, "role.permissions_changed", entity=role, changes={"permissions": change},
                     data={"system_role": True} if role.is_system else None)


def ensure_role_in_organisation(db: Session, role_id: int, organisation_id: int) -> None:
    """For other modules (employees) that accept a role id from the client."""
    _ensure_role(db, role_id, organisation_id)


def get_role(db: Session, role_id: int, organisation_id: int) -> Role:
    return _ensure_role(db, role_id, organisation_id)


def list_roles(
    db: Session, *, organisation_id: int, limit: int, offset: int
) -> tuple[list[Role], int]:
    items = repository.list_roles(
        db, organisation_id=organisation_id, limit=limit, offset=offset
    )
    total = repository.count_roles(db, organisation_id=organisation_id)
    return items, total


def create_role(
    db: Session, *, payload: RoleCreate, organisation_id: int, employee_id: int
) -> Role:
    if repository.get_role_by_name(db, payload.name, organisation_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Role name already exists")
    if payload.permission_ids:
        _ensure_permissions_exist(db, payload.permission_ids)
    role = repository.create_role(
        db, name=payload.name, is_system=False, organisation_id=organisation_id
    )
    if payload.permission_ids:
        repository.replace_role_permissions(
            db,
            role,
            permission_ids=payload.permission_ids,
            updated_by=employee_id,
        )
    event = audit.record_created(db, role)
    granted = _permission_change(db, set(), set(payload.permission_ids or []))
    if granted is not None:
        event.changes = {**(event.changes or {}), "permissions": granted}
    db.commit()
    return _ensure_role(db, role.id, organisation_id)


def update_role(
    db: Session, *, role_id: int, payload: RoleUpdate, organisation_id: int
) -> Role:
    role = _ensure_role(db, role_id, organisation_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return role
    if "name" in data and data["name"] != role.name:
        if role.is_system:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN, "System roles cannot be renamed"
            )
        if repository.get_role_by_name(db, data["name"], organisation_id) is not None:
            raise HTTPException(
                status.HTTP_409_CONFLICT, "Role name already exists"
            )
    before = audit.snapshot(role)
    repository.update_role(db, role, data=data)
    audit.record_changes(db, role, before)
    db.commit()
    return _ensure_role(db, role.id, organisation_id)


def delete_role(db: Session, *, role_id: int, organisation_id: int) -> None:
    role = _ensure_role(db, role_id, organisation_id)
    if role.is_system:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "System roles cannot be deleted"
        )
    if repository.role_has_employees(db, role.id):
        raise HTTPException(
            status.HTTP_409_CONFLICT,
            "Role is assigned to employees; reassign before deletion",
        )
    audit.record_deleted(db, role)
    repository.delete_role(db, role)
    db.commit()


def replace_role_permissions(
    db: Session,
    *,
    role_id: int,
    permission_ids: list[int],
    organisation_id: int,
    employee_id: int,
) -> Role:
    role = _ensure_role(db, role_id, organisation_id)
    _ensure_permissions_exist(db, permission_ids)
    before = _current_permission_ids(role)
    repository.replace_role_permissions(
        db, role, permission_ids=permission_ids, updated_by=employee_id
    )
    _record_permissions_changed(db, role, before, set(permission_ids))
    db.commit()
    return _ensure_role(db, role.id, organisation_id)


def add_role_permissions(
    db: Session,
    *,
    role_id: int,
    permission_ids: list[int],
    organisation_id: int,
    employee_id: int,
) -> Role:
    role = _ensure_role(db, role_id, organisation_id)
    _ensure_permissions_exist(db, permission_ids)
    before = _current_permission_ids(role)
    repository.add_role_permissions(
        db, role, permission_ids=permission_ids, updated_by=employee_id
    )
    _record_permissions_changed(db, role, before, before | set(permission_ids))
    db.commit()
    return _ensure_role(db, role.id, organisation_id)


def remove_role_permission(
    db: Session, *, role_id: int, permission_id: int, organisation_id: int
) -> None:
    role = _ensure_role(db, role_id, organisation_id)
    _ensure_permission(db, permission_id)
    before = _current_permission_ids(role)
    if repository.remove_role_permission(db, role_id, permission_id):
        _record_permissions_changed(db, role, before, before - {permission_id})
    db.commit()


def list_permissions(db: Session) -> list[Permission]:
    return repository.list_permissions(db)


def create_permission(
    db: Session, *, payload: PermissionCreate
) -> Permission:
    existing = repository.get_permission_by_pair(
        db, payload.resource, payload.action
    )
    if existing is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Permission already exists")
    permission = repository.create_permission(
        db, resource=payload.resource, action=payload.action
    )
    db.flush()
    audit.record(db, "permission.created", entity_type="permission", entity_id=permission.id,
                 organisation_id=None, data={"key": f"{permission.resource}:{permission.action}"})
    db.commit()
    return permission


def delete_permission(db: Session, *, permission_id: int) -> None:
    permission = _ensure_permission(db, permission_id)
    audit.record(db, "permission.deleted", entity_type="permission", entity_id=permission.id,
                 organisation_id=None, data={"key": f"{permission.resource}:{permission.action}"})
    repository.delete_permission(db, permission)
    db.commit()


def _get_or_create_catalogue(db: Session) -> tuple[dict[tuple[str, str], Permission], list[Permission]]:
    existing: dict[tuple[str, str], Permission] = {}
    for p in repository.list_permissions(db):  # one query for the whole catalogue
        existing.setdefault((p.resource, p.action), p)
    catalogue: dict[tuple[str, str], Permission] = {}
    created: list[Permission] = []
    for resource, action in PermissionKey.all_pairs():
        permission = existing.get((resource, action))
        if permission is None:
            permission = repository.create_permission(db, resource=resource, action=action)
            created.append(permission)
        catalogue[(resource, action)] = permission
    return catalogue, created


def seed_permissions(db: Session) -> tuple[list[Permission], int]:
    catalogue, created = _get_or_create_catalogue(db)
    db.commit()
    return created, len(catalogue) - len(created)


def seed_default_roles(db: Session, *, organisation_id: int) -> list[Role]:
    """Give an organisation the DEFAULT_ROLES. Idempotent: roles that already
    exist by name are left alone. Flushes but does not commit, so it can run
    inside the caller's transaction (e.g. organisation creation)."""
    catalogue, _ = _get_or_create_catalogue(db)
    roles: list[Role] = []
    for name, is_system, keys in DEFAULT_ROLES:
        role = repository.get_role_by_name(db, name, organisation_id)
        if role is None:
            role = repository.create_role(
                db, name=name, is_system=is_system, organisation_id=organisation_id
            )
            perm_keys = list(catalogue) if keys is None else keys
            repository.add_role_permissions(
                db,
                role,
                permission_ids=[catalogue[k].id for k in perm_keys],
                updated_by=None,
            )
        roles.append(role)
    return roles
