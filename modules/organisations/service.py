from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.audit import service as audit
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
    audit.record_created(db, org)
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
    before = audit.snapshot(org)
    if "logo_file_id" in data:
        _set_logo_file(db, org, data.pop("logo_file_id"), viewer)
    if "external_id" in data and data["external_id"]:
        existing = repository.get_organisation_by_external_id(db, data["external_id"])
        if existing and existing.id != org_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "External ID already in use")
    repository.update_organisation(db, org, data=data)
    audit.record_changes(db, org, before)
    db.commit()
    return repository.get_organisation(db, org_id)


def _set_logo_file(db: Session, org: Organisation, file_id: Optional[int], viewer: EmployeePrincipal) -> None:
    """Swaps the uploaded logo; the old one is deleted with this change."""
    from modules.files import service as files

    if file_id == org.logo_file_id:
        return
    new = None
    if file_id is not None:
        new = files.get(db, file_id=file_id, actor=viewer)
        if new.purpose != "org_logo" or new.organisation_id != org.id:
            raise HTTPException(status.HTTP_422_UNPROCESSABLE_ENTITY, "logo_file_id must be an uploaded logo of this organisation")
        files.attach(db, new, attached_type="organisation", attached_id=org.id)
    if org.logo_file_id is not None:
        old = files.repository.get_file(db, org.logo_file_id)
        if old is not None:
            files.discard(db, old)
    org.logo_file_id = new.id if new else None


def logo_links(db: Session, org: Organisation) -> Optional[tuple[str, Optional[str]]]:
    """(logo link, thumbnail link) for an uploaded logo, else None."""
    if not org.logo_file_id:
        return None
    from modules.files import repository as files_repository
    from modules.files import service as files

    file = files_repository.get_file(db, org.logo_file_id)
    if file is None or file.status != "ready":
        return None
    try:
        url, _ = files.signed_link_for(file, inline=True)
        thumb = files.signed_link_for(file, variant="thumb", inline=True)[0] if (file.variants or {}).get("thumb") else None
    except HTTPException:
        return None  # storage down: show no logo rather than fail the page
    return url, thumb


def delete_organisation(db: Session, org_id: int) -> None:
    from modules.files import service as files

    org = _ensure_organisation(db, org_id)
    # the file rows go with the organisation; their stored bytes are
    # deleted once that has committed
    stored = files.stored_objects_of_organisations(db, [org.id])
    audit.record_deleted(db, org)
    org.logo_file_id = None
    db.flush()
    repository.delete_organisation(db, org)
    db.commit()
    files.delete_stored_objects(stored)
