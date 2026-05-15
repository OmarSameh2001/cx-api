from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository
from .dto import UnitCreate, UnitUpdate
from .model import Unit


def _ensure_unit(db: Session, unit_id: int, organisation_id: int) -> Unit:
    unit = repository.get_unit(db, unit_id)
    if unit is None or unit.organisation_id != organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")
    return unit


def list_units(db: Session, *, organisation_id: int, limit: int, offset: int) -> tuple[list[Unit], int]:
    items = repository.list_units(db, organisation_id=organisation_id, limit=limit, offset=offset)
    total = repository.count_units(db, organisation_id=organisation_id)
    return items, total


def get_unit(db: Session, unit_id: int, organisation_id: int) -> Unit:
    return _ensure_unit(db, unit_id, organisation_id)


def create_unit(db: Session, *, payload: UnitCreate) -> Unit:
    if payload.external_id:
        existing = repository.get_unit_by_external_id(db, payload.external_id)
        if existing:
            raise HTTPException(status.HTTP_409_CONFLICT, "External ID already in use")
    if payload.parent_unit_id is not None:
        parent = repository.get_unit(db, payload.parent_unit_id)
        if parent is None or parent.organisation_id != payload.organisation_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent unit not found in this organisation")
    unit = repository.create_unit(
        db,
        name=payload.name,
        type=payload.type,
        contact_info=payload.contact_info,
        is_active=payload.is_active,
        organisation_id=payload.organisation_id,
        parent_unit_id=payload.parent_unit_id,
        external_id=payload.external_id,
    )
    db.commit()
    return repository.get_unit(db, unit.id)


def update_unit(db: Session, unit_id: int, organisation_id: int, *, payload: UnitUpdate) -> Unit:
    unit = _ensure_unit(db, unit_id, organisation_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return unit
    if "external_id" in data and data["external_id"]:
        existing = repository.get_unit_by_external_id(db, data["external_id"])
        if existing and existing.id != unit_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "External ID already in use")
    if "parent_unit_id" in data and data["parent_unit_id"] is not None:
        parent = repository.get_unit(db, data["parent_unit_id"])
        if parent is None or parent.organisation_id != organisation_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "Parent unit not found in this organisation")
        if data["parent_unit_id"] == unit_id:
            raise HTTPException(status.HTTP_400_BAD_REQUEST, "A unit cannot be its own parent")
    repository.update_unit(db, unit, data=data)
    db.commit()
    return repository.get_unit(db, unit_id)


def delete_unit(db: Session, unit_id: int, organisation_id: int) -> None:
    unit = _ensure_unit(db, unit_id, organisation_id)
    repository.delete_unit(db, unit)
    db.commit()
