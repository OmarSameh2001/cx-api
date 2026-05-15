from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import OrganisationCreate, OrganisationRead, OrganisationSummary, OrganisationUpdate


def list_organisations(db: Session, *, limit: int, offset: int) -> Page[OrganisationSummary]:
    items, total = service.list_organisations(db, limit=limit, offset=offset)
    summaries = [OrganisationSummary.model_validate(o) for o in items]
    return Page(items=summaries, total=total, limit=limit, offset=offset)


def get_organisation(db: Session, org_id: int) -> OrganisationRead:
    return OrganisationRead.model_validate(service.get_organisation(db, org_id))


def create_organisation(db: Session, payload: OrganisationCreate) -> OrganisationRead:
    return OrganisationRead.model_validate(service.create_organisation(db, payload=payload))


def update_organisation(db: Session, org_id: int, payload: OrganisationUpdate) -> OrganisationRead:
    return OrganisationRead.model_validate(service.update_organisation(db, org_id, payload=payload))


def delete_organisation(db: Session, org_id: int) -> None:
    service.delete_organisation(db, org_id)
