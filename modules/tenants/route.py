import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import TenantCreate, TenantRead, TenantSummary, TenantUpdate

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=Page[TenantSummary])
@require_permission("tenants:read")
def list_tenants(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_tenants(db, limit=limit, offset=offset)


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
@require_permission("tenants:create")
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_tenant(db, payload)


@router.get("/{tenant_id}", response_model=TenantRead)
@require_permission("tenants:read")
def get_tenant(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_tenant(db, tenant_id)


@router.patch("/{tenant_id}", response_model=TenantRead)
@require_permission("tenants:update")
def update_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_tenant(db, tenant_id, payload)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("tenants:delete")
def delete_tenant(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_tenant(db, tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
