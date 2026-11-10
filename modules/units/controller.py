from typing import Optional

from sqlalchemy.orm import Session

from common.dto import Page
from modules.auth.dto import EmployeePrincipal

from . import service
from .dto import UnitCreate, UnitRead, UnitSummary, UnitUpdate

# Every function takes the caller and the organisation the client asked for;
# service.resolve_organisation decides which organisation is actually used.


def list_units(
    db: Session, *, viewer: EmployeePrincipal, organisation_id: Optional[int], limit: int, offset: int
) -> Page[UnitSummary]:
    org = service.resolve_organisation(viewer, organisation_id)
    items, total = service.list_units(db, organisation_id=org, limit=limit, offset=offset)
    summaries = [UnitSummary.model_validate(u) for u in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_unit(
    db: Session, unit_id: int, viewer: EmployeePrincipal, organisation_id: Optional[int]
) -> UnitRead:
    org = service.resolve_organisation(viewer, organisation_id)
    return UnitRead.model_validate(service.get_unit(db, unit_id, org))


def create_unit(db: Session, payload: UnitCreate, viewer: EmployeePrincipal) -> UnitRead:
    org = service.resolve_organisation(viewer, payload.organisation_id)
    return UnitRead.model_validate(service.create_unit(db, payload=payload, organisation_id=org))


def update_unit(
    db: Session,
    unit_id: int,
    viewer: EmployeePrincipal,
    organisation_id: Optional[int],
    payload: UnitUpdate,
) -> UnitRead:
    org = service.resolve_organisation(viewer, organisation_id)
    return UnitRead.model_validate(service.update_unit(db, unit_id, org, payload=payload))


def delete_unit(
    db: Session, unit_id: int, viewer: EmployeePrincipal, organisation_id: Optional[int]
) -> None:
    org = service.resolve_organisation(viewer, organisation_id)
    service.delete_unit(db, unit_id, org)
