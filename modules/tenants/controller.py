import uuid

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import TenantCreate, TenantRead, TenantSummary, TenantUpdate


def list_tenants(db: Session, *, limit: int, offset: int) -> Page[TenantSummary]:
    items, total = service.list_tenants(db, limit=limit, offset=offset)
    summaries = [TenantSummary.model_validate(t) for t in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_tenant(db: Session, tenant_id: uuid.UUID) -> TenantRead:
    return TenantRead.model_validate(service.get_tenant(db, tenant_id))


def create_tenant(db: Session, payload: TenantCreate) -> TenantRead:
    return TenantRead.model_validate(service.create_tenant(db, payload=payload))


def update_tenant(db: Session, tenant_id: uuid.UUID, payload: TenantUpdate) -> TenantRead:
    return TenantRead.model_validate(service.update_tenant(db, tenant_id, payload=payload))


def delete_tenant(db: Session, tenant_id: uuid.UUID) -> None:
    service.delete_tenant(db, tenant_id)
