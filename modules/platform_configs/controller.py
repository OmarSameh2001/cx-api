import uuid

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import PlatformConfigCreate, PlatformConfigRead, PlatformConfigSummary, PlatformConfigUpdate


def list_platform_configs(db: Session, *, tenant_id: uuid.UUID, organisation_id: int, limit: int, offset: int) -> Page[PlatformConfigSummary]:
    items, total = service.list_platform_configs(db, tenant_id=tenant_id, organisation_id=organisation_id, limit=limit, offset=offset)
    summaries = [PlatformConfigSummary.model_validate(c) for c in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_platform_config(db: Session, config_id: uuid.UUID, organisation_id: int) -> PlatformConfigRead:
    return PlatformConfigRead.model_validate(service.get_platform_config(db, config_id, organisation_id))


def create_platform_config(db: Session, payload: PlatformConfigCreate, organisation_id: int) -> PlatformConfigRead:
    return PlatformConfigRead.model_validate(service.create_platform_config(db, payload=payload, organisation_id=organisation_id))


def update_platform_config(db: Session, config_id: uuid.UUID, payload: PlatformConfigUpdate, organisation_id: int) -> PlatformConfigRead:
    return PlatformConfigRead.model_validate(service.update_platform_config(db, config_id, organisation_id=organisation_id, payload=payload))


def delete_platform_config(db: Session, config_id: uuid.UUID, organisation_id: int) -> None:
    service.delete_platform_config(db, config_id, organisation_id)
