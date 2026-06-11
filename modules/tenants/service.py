import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository
from .dto import TenantCreate, TenantUpdate
from .model import Tenant


def _ensure_tenant(db: Session, tenant_id: uuid.UUID) -> Tenant:
    tenant = repository.get_tenant(db, tenant_id)
    if tenant is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Tenant not found")
    return tenant


def list_tenants(db: Session, *, limit: int, offset: int) -> tuple[list[Tenant], int]:
    items = repository.list_tenants(db, limit=limit, offset=offset)
    total = repository.count_tenants(db)
    return items, total


def get_tenant(db: Session, tenant_id: uuid.UUID) -> Tenant:
    return _ensure_tenant(db, tenant_id)


def create_tenant(db: Session, *, payload: TenantCreate) -> Tenant:
    tenant = repository.create_tenant(
        db,
        name=payload.name,
        email=payload.email,
        retention_days=payload.retention_days,
        is_active=payload.is_active,
        organisation_id=payload.organisation_id,
    )
    db.commit()
    return repository.get_tenant(db, tenant.id)


def update_tenant(db: Session, tenant_id: uuid.UUID, *, payload: TenantUpdate) -> Tenant:
    tenant = _ensure_tenant(db, tenant_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return tenant
    repository.update_tenant(db, tenant, data=data)
    db.commit()
    return repository.get_tenant(db, tenant_id)


def delete_tenant(db: Session, tenant_id: uuid.UUID) -> None:
    tenant = _ensure_tenant(db, tenant_id)
    repository.delete_tenant(db, tenant)
    db.commit()
