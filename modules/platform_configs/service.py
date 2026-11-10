import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.tenants.service import ensure_tenant_in_organisation, tenant_in_organisation

from . import repository
from .dto import PlatformConfigCreate, PlatformConfigUpdate
from .model import TenantPlatformConfig


def _ensure_platform_config(db: Session, config_id: uuid.UUID, organisation_id: int) -> TenantPlatformConfig:
    config = repository.get_platform_config(db, config_id)
    # another organisation's row is reported as missing
    if config is None or not tenant_in_organisation(db, config.tenant_id, organisation_id):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform config not found")
    return config


def list_platform_configs(db: Session, *, tenant_id: uuid.UUID, organisation_id: int, limit: int, offset: int) -> tuple[list[TenantPlatformConfig], int]:
    ensure_tenant_in_organisation(db, tenant_id, organisation_id)
    items = repository.list_platform_configs(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_platform_configs(db, tenant_id=tenant_id)
    return items, total


def get_platform_config(db: Session, config_id: uuid.UUID, organisation_id: int) -> TenantPlatformConfig:
    return _ensure_platform_config(db, config_id, organisation_id)


def create_platform_config(db: Session, *, payload: PlatformConfigCreate, organisation_id: int) -> TenantPlatformConfig:
    ensure_tenant_in_organisation(db, payload.tenant_id, organisation_id)
    config = repository.create_platform_config(
        db,
        platform=payload.platform,
        tenant_id=payload.tenant_id,
        is_enabled=payload.is_enabled,
    )
    db.commit()
    return repository.get_platform_config(db, config.id)


def update_platform_config(db: Session, config_id: uuid.UUID, *, organisation_id: int, payload: PlatformConfigUpdate) -> TenantPlatformConfig:
    config = _ensure_platform_config(db, config_id, organisation_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return config
    repository.update_platform_config(db, config, data=data)
    db.commit()
    return repository.get_platform_config(db, config_id)


def delete_platform_config(db: Session, config_id: uuid.UUID, organisation_id: int) -> None:
    config = _ensure_platform_config(db, config_id, organisation_id)
    repository.delete_platform_config(db, config)
    db.commit()
