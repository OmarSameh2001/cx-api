from typing import Optional

from sqlalchemy.exc import IntegrityError
from sqlalchemy.orm import Session

from common.errors import AppError
from modules.audit import service as audit
from modules.auth.dto import EmployeePrincipal

from . import repository
from .dto import UnitCreate, UnitUpdate
from .model import Unit


def resolve_organisation(viewer: EmployeePrincipal, requested: Optional[int]) -> int:
    """The organisation a unit request acts on. The client may name one (the
    Organisation page does), but only a platform admin may name another
    organisation than their own; anyone else gets 404, as if it didn't exist."""
    if requested is None or requested == viewer.organisation_id:
        return viewer.organisation_id
    if viewer.is_platform_admin:
        return requested
    raise AppError(404, "organisations.not_found")


def _ensure_unit(db: Session, unit_id: int, organisation_id: int) -> Unit:
    unit = repository.get_unit(db, unit_id)
    if unit is None or unit.organisation_id != organisation_id:
        raise AppError(404, "units.not_found")
    return unit


def list_units(db: Session, *, organisation_id: int, limit: int, offset: int) -> tuple[list[Unit], int]:
    items = repository.list_units(db, organisation_id=organisation_id, limit=limit, offset=offset)
    total = repository.count_units(db, organisation_id=organisation_id)
    return items, total


def get_unit(db: Session, unit_id: int, organisation_id: int) -> Unit:
    return _ensure_unit(db, unit_id, organisation_id)


def create_unit(db: Session, *, payload: UnitCreate, organisation_id: int) -> Unit:
    if payload.external_id:
        existing = repository.get_unit_by_external_id(db, payload.external_id)
        if existing:
            raise AppError(409, "employees.external_id_in_use")
    if payload.parent_unit_id is not None:
        parent = repository.get_unit(db, payload.parent_unit_id)
        if parent is None or parent.organisation_id != organisation_id:
            raise AppError(400, "units.parent_not_found")
    unit = repository.create_unit(
        db,
        name=payload.name,
        type=payload.type,
        contact_info=payload.contact_info,
        is_active=payload.is_active,
        organisation_id=organisation_id,
        parent_unit_id=payload.parent_unit_id,
        external_id=payload.external_id,
    )
    audit.record_created(db, unit)
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
            raise AppError(409, "employees.external_id_in_use")
    if "parent_unit_id" in data and data["parent_unit_id"] is not None:
        parent = repository.get_unit(db, data["parent_unit_id"])
        if parent is None or parent.organisation_id != organisation_id:
            raise AppError(400, "units.parent_not_found")
        if data["parent_unit_id"] == unit_id:
            raise AppError(400, "units.own_parent")
        if data["parent_unit_id"] in repository.get_descendant_unit_ids(db, unit_id):
            raise AppError(400, "units.under_own_child")
    before = audit.snapshot(unit)
    repository.update_unit(db, unit, data=data)
    audit.record_changes(db, unit, before)
    db.commit()
    return repository.get_unit(db, unit_id)


def delete_unit(db: Session, unit_id: int, organisation_id: int) -> None:
    unit = _ensure_unit(db, unit_id, organisation_id)
    # rolled back with the delete if the unit is still in use
    audit.record_deleted(db, unit)
    repository.delete_unit(db, unit)
    try:
        db.commit()
    except IntegrityError:
        # employees, assignments or child units still point at it
        db.rollback()
        raise AppError(409, "units.in_use")
