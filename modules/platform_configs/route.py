import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import PlatformConfigCreate, PlatformConfigRead, PlatformConfigSummary, PlatformConfigUpdate

router = APIRouter(prefix="/platform-configs", tags=["platform_configs"])


@router.get("", response_model=Page[PlatformConfigSummary])
@require_permission("tenants:read")
def list_platform_configs(
    tenant_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_platform_configs(db, tenant_id=tenant_id, limit=limit, offset=offset)


@router.post("", response_model=PlatformConfigRead, status_code=status.HTTP_201_CREATED)
@require_permission("tenants:update")
def create_platform_config(
    payload: PlatformConfigCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_platform_config(db, payload)


@router.get("/{config_id}", response_model=PlatformConfigRead)
@require_permission("tenants:read")
def get_platform_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_platform_config(db, config_id)


@router.patch("/{config_id}", response_model=PlatformConfigRead)
@require_permission("tenants:update")
def update_platform_config(
    config_id: uuid.UUID,
    payload: PlatformConfigUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_platform_config(db, config_id, payload)


@router.delete("/{config_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("tenants:update")
def delete_platform_config(
    config_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_platform_config(db, config_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
