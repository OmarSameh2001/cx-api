from sqlalchemy.orm import Session

from common.dto import Page
from modules.auth.dto import EmployeePrincipal

from . import service
from .dto import OrganisationCreate, OrganisationRead, OrganisationSummary, OrganisationUpdate


def list_organisations(
    db: Session, *, viewer: EmployeePrincipal, limit: int, offset: int
) -> Page[OrganisationSummary]:
    items, total = service.list_organisations(db, viewer=viewer, limit=limit, offset=offset)
    summaries = [OrganisationSummary.model_validate(o) for o in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def _read(db: Session, org) -> OrganisationRead:
    read = OrganisationRead.model_validate(org)
    links = service.logo_links(db, org)
    if links:
        read.logo, read.logo_thumb = links
    return read


def get_organisation(db: Session, org_id: int, viewer: EmployeePrincipal) -> OrganisationRead:
    return _read(db, service.get_organisation(db, org_id, viewer=viewer))


def create_organisation(db: Session, payload: OrganisationCreate) -> OrganisationRead:
    return _read(db, service.create_organisation(db, payload=payload))


def update_organisation(
    db: Session, org_id: int, payload: OrganisationUpdate, viewer: EmployeePrincipal
) -> OrganisationRead:
    return _read(db, service.update_organisation(db, org_id, payload=payload, viewer=viewer))


def delete_organisation(db: Session, org_id: int) -> None:
    service.delete_organisation(db, org_id)
