from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.auth.dto import EmployeePrincipal
from modules.roles import service as roles_service

from . import repository
from .dto import OrganisationCreate, OrganisationUpdate
from .model import Organisation

# Billing and integration fields only the platform may change.
PLATFORM_ONLY_FIELDS = ("subscription_end", "subscription_plan_id", "external_id")


def _ensure_organisation(db: Session, org_id: int) -> Organisation:
    org = repository.get_organisation(db, org_id)
    if org is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found")
    return org


def _ensure_visible(db: Session, org_id: int, viewer: EmployeePrincipal) -> Organisation:
    # Another organisation is reported as missing, so its existence does not leak.
    if not viewer.is_platform_admin and org_id != viewer.organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Organisation not found")
    return _ensure_organisation(db, org_id)


def list_organisations(
    db: Session, *, viewer: EmployeePrincipal, limit: int, offset: int
) -> tuple[list[Organisation], int]:
    if not viewer.is_platform_admin:
        own = repository.get_organisation(db, viewer.organisation_id)
        items = [own] if own is not None and offset == 0 else []
        return items, 1 if own is not None else 0
    items = repository.list_organisations(db, limit=limit, offset=offset)
    total = repository.count_organisations(db)
    return items, total


def get_organisation(db: Session, org_id: int, *, viewer: EmployeePrincipal) -> Organisation:
    return _ensure_visible(db, org_id, viewer)


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
    # Same transaction: an organisation never exists without its roles.
    roles_service.seed_default_roles(db, organisation_id=org.id)
    db.commit()
    return repository.get_organisation(db, org.id)


def update_organisation(
    db: Session, org_id: int, *, payload: OrganisationUpdate, viewer: EmployeePrincipal
) -> Organisation:
    org = _ensure_visible(db, org_id, viewer)
    if not viewer.is_platform_admin and not viewer.is_admin:
        raise HTTPException(
            status.HTTP_403_FORBIDDEN, "Only the organisation admin can edit the organisation"
        )
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return org
    if not viewer.is_platform_admin:
        # Compare to the stored value so a form that echoes it back still saves.
        changed = [f for f in PLATFORM_ONLY_FIELDS if f in data and data[f] != getattr(org, f)]
        if changed:
            raise HTTPException(
                status.HTTP_403_FORBIDDEN,
                f"Only a platform admin can change: {', '.join(changed)}",
            )
        for f in PLATFORM_ONLY_FIELDS:
            data.pop(f, None)
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
