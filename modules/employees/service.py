from sqlalchemy.orm import Session

from common.errors import AppError
from modules.audit import service as audit
from modules.auth.dto import EmployeePrincipal
from modules.auth.service import hash_password
from modules.roles.service import ensure_role_in_organisation
from modules.units import repository as units_repository

from . import repository
from .dto import EmployeeCreate, EmployeeUpdate
from .model import Employee


def _ensure_links_in_organisation(db: Session, data: dict, organisation_id: int) -> None:
    """Ids from the client that point at other rows must be the caller's
    organisation's: the manager, and any extra assigned units."""
    if data.get("manager_id") is not None:
        manager = repository.get_employee(db, data["manager_id"])
        if manager is None or manager.organisation_id != organisation_id:
            raise AppError(404, "employees.manager_not_found")
    wanted = list(dict.fromkeys(data.get("assigned_units") or []))
    found = units_repository.unit_ids_in_organisation(db, wanted, organisation_id)
    for unit_id in wanted:  # the first missing one, in the order sent
        if unit_id not in found:
            raise AppError(404, "units.id_not_found", unit_id=unit_id)


def _ensure_employee(
    db: Session, employee_id: int, organisation_id: int, assigned_unit_ids: list[int]
) -> Employee:
    employee = repository.get_employee(db, employee_id)
    if (
        employee is None
        or employee.organisation_id != organisation_id
        or employee.unit_id not in assigned_unit_ids
    ):
        raise AppError(404, "employees.not_found")
    return employee


def list_employees(
    db: Session,
    *,
    organisation_id: int,
    assigned_unit_ids: list[int],
    limit: int,
    offset: int,
) -> tuple[list[Employee], int]:
    unit_ids = assigned_unit_ids or None
    items = repository.list_employees(
        db,
        organisation_id=organisation_id,
        unit_ids=unit_ids,
        limit=limit,
        offset=offset,
    )
    total = repository.count_employees(
        db,
        organisation_id=organisation_id,
        unit_ids=unit_ids,
    )
    return items, total


def get_employee(
    db: Session, employee_id: int, organisation_id: int, assigned_unit_ids: list[int]
) -> Employee:
    return _ensure_employee(db, employee_id, organisation_id, assigned_unit_ids)


def _is_org_admin(actor: EmployeePrincipal) -> bool:
    return actor.is_admin or actor.is_platform_admin


def _ensure_may_grant_role(db: Session, role_id: int, actor: EmployeePrincipal) -> None:
    """The admin role makes its holder the organisation admin, so only an
    admin may give it."""
    role = ensure_role_in_organisation(db, role_id, actor.organisation_id)
    if role.is_system and not _is_org_admin(actor):
        raise AppError(403, "employees.admin_role_admin_only")


def _ensure_may_edit(db: Session, employee: Employee, actor: EmployeePrincipal) -> None:
    """Only an admin edits or removes an admin's account: whoever can change
    its email could then sign in to it with Google or Microsoft."""
    if _is_org_admin(actor) or employee.role_id is None:
        return
    if ensure_role_in_organisation(db, employee.role_id, actor.organisation_id).is_system:
        raise AppError(403, "employees.admin_admin_only")


def create_employee(
    db: Session, *, payload: EmployeeCreate, actor: EmployeePrincipal
) -> Employee:
    organisation_id, assigned_unit_ids = actor.organisation_id, actor.assigned_unit_ids
    if payload.unit_id not in assigned_unit_ids:
        raise AppError(403, "employees.unit_not_assigned")
    if repository.get_employee_by_email(db, str(payload.email)) is not None:
        raise AppError(409, "employees.email_in_use")
    if repository.get_employee_by_username(db, payload.username) is not None:
        raise AppError(409, "employees.username_in_use")
    if payload.external_id and repository.get_employee_by_external_id(db, payload.external_id) is not None:
        raise AppError(409, "employees.external_id_in_use")
    if payload.role_id is not None:
        _ensure_may_grant_role(db, payload.role_id, actor)
    _ensure_links_in_organisation(db, payload.model_dump(), organisation_id)

    employee = repository.create_employee(
        db,
        first_name=payload.first_name,
        last_name=payload.last_name,
        username=payload.username,
        email=str(payload.email),
        password_hash=hash_password(payload.password),
        organisation_id=organisation_id,
        is_active=payload.is_active,
        external_id=payload.external_id,
        phone=payload.phone,
        dob=payload.dob,
        gender=payload.gender,
        manager_id=payload.manager_id,
        unit_id=payload.unit_id,
        role_id=payload.role_id,
        assigned_units=payload.assigned_units,
    )
    audit.record_created(db, employee)
    db.commit()
    return repository.get_employee(db, employee.id)


def update_employee(
    db: Session,
    *,
    employee_id: int,
    payload: EmployeeUpdate,
    actor: EmployeePrincipal,
) -> Employee:
    organisation_id, assigned_unit_ids = actor.organisation_id, actor.assigned_unit_ids
    employee = _ensure_employee(db, employee_id, organisation_id, assigned_unit_ids)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return employee
    _ensure_may_edit(db, employee, actor)
    if "role_id" in data and data["role_id"] != employee.role_id:
        if employee.id == actor.id:
            raise AppError(403, "employees.own_role")
    if "email" in data:
        data["email"] = str(data["email"])
        existing = repository.get_employee_by_email(db, data["email"])
        if existing is not None and existing.id != employee_id:
            raise AppError(409, "employees.email_in_use")
    if "username" in data:
        existing = repository.get_employee_by_username(db, data["username"])
        if existing is not None and existing.id != employee_id:
            raise AppError(409, "employees.username_in_use")
    if "external_id" in data and data["external_id"]:
        existing = repository.get_employee_by_external_id(db, data["external_id"])
        if existing is not None and existing.id != employee_id:
            raise AppError(409, "employees.external_id_in_use")
    if "unit_id" in data and data["unit_id"] not in assigned_unit_ids:
        raise AppError(403, "employees.unit_not_assigned")
    if data.get("role_id") is not None and data["role_id"] != employee.role_id:
        _ensure_may_grant_role(db, data["role_id"], actor)
    _ensure_links_in_organisation(db, data, organisation_id)
    before = audit.snapshot(employee)
    repository.update_employee(db, employee, data=data)
    audit.record_changes(db, employee, before)
    db.commit()
    return repository.get_employee(db, employee_id)


def delete_employee(db: Session, *, employee_id: int, actor: EmployeePrincipal) -> None:
    employee = _ensure_employee(db, employee_id, actor.organisation_id, actor.assigned_unit_ids)
    _ensure_may_edit(db, employee, actor)
    audit.record_deleted(db, employee)
    repository.delete_employee(db, employee)
    db.commit()
