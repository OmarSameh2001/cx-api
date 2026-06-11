import uuid
from datetime import datetime
from typing import Optional

from sqlalchemy import func, select
from sqlalchemy.orm import Session

from .model import TenantPlatformConfig


def get_platform_config(db: Session, config_id: uuid.UUID) -> TenantPlatformConfig | None:
    return db.get(TenantPlatformConfig, config_id)


def list_platform_configs(db: Session, *, tenant_id: uuid.UUID, limit: int = 100, offset: int = 0) -> list[TenantPlatformConfig]:
    stmt = (
        select(TenantPlatformConfig)
        .where(TenantPlatformConfig.tenant_id == tenant_id)
        .order_by(TenantPlatformConfig.platform)
        .limit(limit)
        .offset(offset)
    )
    return list(db.execute(stmt).scalars().all())


def count_platform_configs(db: Session, *, tenant_id: uuid.UUID) -> int:
    return db.execute(
        select(func.count()).select_from(TenantPlatformConfig).where(TenantPlatformConfig.tenant_id == tenant_id)
    ).scalar_one()


def create_platform_config(
    db: Session,
    *,
    platform: str,
    tenant_id: uuid.UUID,
    is_enabled: bool = True,
) -> TenantPlatformConfig:
    config = TenantPlatformConfig(
        platform=platform,
        tenant_id=tenant_id,
        is_enabled=is_enabled,
    )
    db.add(config)
    db.flush()
    return config


def update_platform_config(db: Session, config: TenantPlatformConfig, *, data: dict) -> TenantPlatformConfig:
    for key, value in data.items():
        setattr(config, key, value)
    db.flush()
    return config


def delete_platform_config(db: Session, config: TenantPlatformConfig) -> None:
    db.delete(config)
