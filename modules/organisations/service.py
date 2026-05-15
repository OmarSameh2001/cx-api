from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository
from .dto import OrganisationCreate, OrganisationUpdate
from .model import Organisation


def _ensure_organisation(db: Session, org_id: int) -> Organisation:
    org = repository.get_organisation(db, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found")
    return org


def list_organisations(db: Session, *, limit: int, offset: int) -> tuple[list[Organisation], int]:
    items = repository.list_organisations(db, limit=limit, offset=offset)
    total = repository.count_organisations(db)
    return items, total


def get_organisation(db: Session, org_id: int) -> Organisation:
    return _ensure_organisation(db, org_id)


def create_organisation(db: Session, *, payload: OrganisationCreate) -> Organisation:
    if payload.external_id:
        existing = repository.get_organisation_by_external_id(db, payload.external_id)
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "External ID already in use")
    org = repository.create_organisation(
        db,
        name=payload.name,
        logo=payload.logo,
        industry=payload.industry,
        contact_info=payload.contact_info,
        subscription_end=payload.subscription_end,
        subscription_plan_id=payload.subscription_plan_id,
        external_id=payload.external_id,
    )
    db.commit()
    return repository.get_organisation(db, org.id)


def update_organisation(db: Session, org_id: int, *, payload: OrganisationUpdate) -> Organisation:
    org = _ensure_organisation(db, org_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return org
    if "external_id" in data and data["external_id"]:
        existing = repository.get_organisation_by_external_id(db, data["external_id"])
        if existing and existing.id != org_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "External ID already in use")
    repository.update_organisation(db, org, data=data)
    db.commit()
    return repository.get_organisation(db, org_id)


def delete_organisation(db: Session, org_id: int) -> None:
    org = _ensure_organisation(db, org_id)
    repository.delete_organisation(db, org)
    db.commit()
