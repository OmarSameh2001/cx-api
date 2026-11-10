from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.decorator.platform_admin import platform_admin
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
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


router = APIRouter(prefix="/roles", tags=["roles"])


# ── Permission catalogue ─────────────────────────────────────────────────────
# Shared by every organisation. Org admins read it to build their roles; only
# platform admins change it.

@router.get("/permissions", response_model=list[PermissionRead])
@require_permission("roles:read")
def list_permissions(db: Session = Depends(get_db)):
    return controller.list_permissions(db)


@router.post(
    "/permissions",
    response_model=PermissionRead,
    status_code=status.HTTP_201_CREATED,
)
def create_permission(
    payload: PermissionCreate,
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    return controller.create_permission(db, payload)


@router.post("/permissions/seed", response_model=SeedResult)
def seed_permissions(
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    return controller.seed_permissions(db)


@router.delete(
    "/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
def delete_permission(
    permission_id: int,
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    controller.delete_permission(db, permission_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# ── Roles, scoped to the caller's organisation ───────────────────────────────

@router.get("", response_model=Page[RoleSummary])
@require_permission("roles:read")
def list_roles(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_roles(
        db, organisation_id=employee.organisation_id, limit=limit, offset=offset
    )


@router.post("", response_model=RoleRead, status_code=status.HTTP_201_CREATED)
@require_permission("roles:create")
def create_role(
    payload: RoleCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_role(db, payload, employee.organisation_id, employee.id)


@router.get("/{role_id}", response_model=RoleRead)
@require_permission("roles:read")
def get_role(
    role_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_role(db, role_id, employee.organisation_id)


@router.patch("/{role_id}", response_model=RoleRead)
@require_permission("roles:update")
def update_role(
    role_id: int,
    payload: RoleUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_role(db, role_id, payload, employee.organisation_id)


@router.delete("/{role_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("roles:delete")
def delete_role(
    role_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_role(db, role_id, employee.organisation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


@router.put("/{role_id}/permissions", response_model=RoleRead)
@require_permission("roles:update")
def replace_role_permissions(
    role_id: int,
    payload: RolePermissionsReplace,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.replace_role_permissions(
        db, role_id, payload, employee.organisation_id, employee.id
    )


@router.post("/{role_id}/permissions", response_model=RoleRead)
@require_permission("roles:update")
def add_role_permissions(
    role_id: int,
    payload: RolePermissionsAdd,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.add_role_permissions(
        db, role_id, payload, employee.organisation_id, employee.id
    )


@router.delete(
    "/{role_id}/permissions/{permission_id}",
    status_code=status.HTTP_204_NO_CONTENT,
)
# taking a permission off a role edits the role
@require_permission("roles:update")
def remove_role_permission(
    role_id: int,
    permission_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.remove_role_permission(
        db, role_id, permission_id, employee.organisation_id
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
