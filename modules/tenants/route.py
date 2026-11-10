import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.platform_admin import platform_admin
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal

from . import controller
from .dto import TenantCreate, TenantRead, TenantSummary, TenantUpdate

router = APIRouter(prefix="/tenants", tags=["tenants"])


@router.get("", response_model=Page[TenantSummary])
def list_tenants(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    return controller.list_tenants(db, limit=limit, offset=offset)


@router.post("", response_model=TenantRead, status_code=status.HTTP_201_CREATED)
def create_tenant(
    payload: TenantCreate,
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    return controller.create_tenant(db, payload)


@router.get("/{tenant_id}", response_model=TenantRead)
def get_tenant(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    return controller.get_tenant(db, tenant_id)


@router.patch("/{tenant_id}", response_model=TenantRead)
def update_tenant(
    tenant_id: uuid.UUID,
    payload: TenantUpdate,
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    return controller.update_tenant(db, tenant_id, payload)


@router.delete("/{tenant_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_tenant(
    tenant_id: uuid.UUID,
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    controller.delete_tenant(db, tenant_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
