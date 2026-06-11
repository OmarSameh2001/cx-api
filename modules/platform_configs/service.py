import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository
from .dto import PlatformConfigCreate, PlatformConfigUpdate
from .model import TenantPlatformConfig


def _ensure_platform_config(db: Session, config_id: uuid.UUID) -> TenantPlatformConfig:
    config = repository.get_platform_config(db, config_id)
    if config is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Platform config not found")
    return config


def list_platform_configs(db: Session, *, tenant_id: uuid.UUID, limit: int, offset: int) -> tuple[list[TenantPlatformConfig], int]:
    items = repository.list_platform_configs(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_platform_configs(db, tenant_id=tenant_id)
    return items, total


def get_platform_config(db: Session, config_id: uuid.UUID) -> TenantPlatformConfig:
    return _ensure_platform_config(db, config_id)


def create_platform_config(db: Session, *, payload: PlatformConfigCreate) -> TenantPlatformConfig:
    config = repository.create_platform_config(
        db,
        platform=payload.platform,
        tenant_id=payload.tenant_id,
        is_enabled=payload.is_enabled,
    )
    db.commit()
    return repository.get_platform_config(db, config.id)


def update_platform_config(db: Session, config_id: uuid.UUID, *, payload: PlatformConfigUpdate) -> TenantPlatformConfig:
    config = _ensure_platform_config(db, config_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return config
    repository.update_platform_config(db, config, data=data)
    db.commit()
    return repository.get_platform_config(db, config_id)


def delete_platform_config(db: Session, config_id: uuid.UUID) -> None:
    config = _ensure_platform_config(db, config_id)
    repository.delete_platform_config(db, config)
    db.commit()
