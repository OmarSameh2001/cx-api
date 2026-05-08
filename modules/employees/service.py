from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.auth.service import hash_password

from . import repository
from .dto import EmployeeCreate, EmployeeUpdate
from .model import Employee


def _ensure_employee(
    db: Session, employee_id: int, organisation_id: int, assigned_unit_ids: list[int]
) -> Employee:
    employee = repository.get_employee(db, employee_id)
    if (
        employee is None
        or employee.organisation_id != organisation_id
        or employee.unit_id not in assigned_unit_ids
    ):
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")
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


def create_employee(
    db: Session, *, payload: EmployeeCreate, organisation_id: int, assigned_unit_ids: list[int]
) -> Employee:
    if payload.unit_id not in assigned_unit_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unit not in your assigned units")
    if repository.get_employee_by_email(db, str(payload.email)) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use")
    if repository.get_employee_by_username(db, payload.username) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "Username already in use")
    if payload.external_id and repository.get_employee_by_external_id(db, payload.external_id) is not None:
        raise HTTPException(status.HTTP_409_CONFLICT, "External ID already in use")

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
    db.commit()
    return repository.get_employee(db, employee.id)


def update_employee(
    db: Session,
    *,
    employee_id: int,
    payload: EmployeeUpdate,
    organisation_id: int,
    assigned_unit_ids: list[int],
) -> Employee:
    employee = _ensure_employee(db, employee_id, organisation_id, assigned_unit_ids)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return employee
    if "email" in data:
        data["email"] = str(data["email"])
        existing = repository.get_employee_by_email(db, data["email"])
        if existing is not None and existing.id != employee_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Email already in use")
    if "username" in data:
        existing = repository.get_employee_by_username(db, data["username"])
        if existing is not None and existing.id != employee_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "Username already in use")
    if "external_id" in data and data["external_id"]:
        existing = repository.get_employee_by_external_id(db, data["external_id"])
        if existing is not None and existing.id != employee_id:
            raise HTTPException(status.HTTP_409_CONFLICT, "External ID already in use")
    if "unit_id" in data and data["unit_id"] not in assigned_unit_ids:
        raise HTTPException(status.HTTP_403_FORBIDDEN, "Unit not in your assigned units")
    repository.update_employee(db, employee, data=data)
    db.commit()
    return repository.get_employee(db, employee_id)


def delete_employee(
    db: Session, *, employee_id: int, organisation_id: int, assigned_unit_ids: list[int]
) -> None:
    employee = _ensure_employee(db, employee_id, organisation_id, assigned_unit_ids)
    repository.delete_employee(db, employee)
    db.commit()
