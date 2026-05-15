from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import UnitCreate, UnitRead, UnitSummary, UnitUpdate


def list_units(db: Session, *, organisation_id: int, limit: int, offset: int) -> Page[UnitSummary]:
    items, total = service.list_units(db, organisation_id=organisation_id, limit=limit, offset=offset)
    summaries = [UnitSummary.model_validate(u) for u in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_unit(db: Session, unit_id: int, organisation_id: int) -> UnitRead:
    return UnitRead.model_validate(service.get_unit(db, unit_id, organisation_id))


def create_unit(db: Session, payload: UnitCreate) -> UnitRead:
    return UnitRead.model_validate(service.create_unit(db, payload=payload))


def update_unit(db: Session, unit_id: int, organisation_id: int, payload: UnitUpdate) -> UnitRead:
    return UnitRead.model_validate(service.update_unit(db, unit_id, organisation_id, payload=payload))


def delete_unit(db: Session, unit_id: int, organisation_id: int) -> None:
    service.delete_unit(db, unit_id, organisation_id)
