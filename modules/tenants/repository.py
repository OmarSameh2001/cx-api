import uuid
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import Tenant


def get_tenant(db: Session, tenant_id: uuid.UUID) -> Optional[Tenant]:
    return db.get(Tenant, tenant_id)


def list_tenants(db: Session, *, limit: int = 100, offset: int = 0) -> list[Tenant]:
    stmt = select(Tenant).order_by(Tenant.name).limit(limit).offset(offset)
    return list(db.execute(stmt).scalars().all())


def count_tenants(db: Session) -> int:
    return db.execute(select(func.count()).select_from(Tenant)).scalar_one()


def create_tenant(
    db: Session,
    *,
    name: str,
    email: str,
    retention_days: Optional[int] = None,
    is_active: bool = True,
    organisation_id: Optional[int] = None,
) -> Tenant:
    tenant = Tenant(
        name=name,
        email=email,
        retention_days=retention_days,
        is_active=is_active,
        organisation_id=organisation_id,
    )
    db.add(tenant)
    db.flush()
    return tenant


def update_tenant(db: Session, tenant: Tenant, *, data: dict) -> Tenant:
    for key, value in data.items():
        setattr(tenant, key, value)
    db.flush()
    return tenant


def delete_tenant(db: Session, tenant: Tenant) -> None:
    db.delete(tenant)
