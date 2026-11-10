from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.employees.model import Employee
from modules.units.model import Unit

from . import repository
from .dto import AssignmentCreate, AssignmentUpdate
from .model import Assignment

# An assignment belongs to the organisation of its unit, and its employee must
# be in that organisation too. Rows of another organisation are reported as
# missing (404), so their existence does not leak.


def _ensure_employee_in_organisation(db: Session, employee_id: int, organisation_id: int) -> None:
    employee = db.get(Employee, employee_id)
    if employee is None or employee.organisation_id != organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")


def _ensure_unit_in_organisation(db: Session, unit_id: int, organisation_id: int) -> None:
    unit = db.get(Unit, unit_id)
    if unit is None or unit.organisation_id != organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")


def get_assignment(db: Session, assignment_id: int, organisation_id: int) -> Assignment:
    assignment = repository.get_assignment(db, assignment_id)
    if assignment is None or assignment.unit.organisation_id != organisation_id:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return assignment


def list_assignments(
    db: Session,
    *,
    organisation_id: int,
    user_id: Optional[int],
    unit_id: Optional[int],
    assigned_by: Optional[int],
    limit: int,
    offset: int,
) -> tuple[list[Assignment], int]:
    filters = dict(
        organisation_id=organisation_id,
        user_id=user_id,
        unit_id=unit_id,
        assigned_by=assigned_by,
    )
    items = repository.list_assignments(db, **filters, limit=limit, offset=offset)
    total = repository.count_assignments(db, **filters)
    return items, total


def create_assignment(
    db: Session, *, payload: AssignmentCreate, organisation_id: int, employee_id: int
) -> Assignment:
    _ensure_employee_in_organisation(db, payload.user_id, organisation_id)
    _ensure_unit_in_organisation(db, payload.unit_id, organisation_id)
    return repository.create_assignment(
        db,
        user_id=payload.user_id,
        unit_id=payload.unit_id,
        description=payload.description,
        assigned_by=employee_id,
    )


def update_assignment(
    db: Session,
    *,
    assignment_id: int,
    payload: AssignmentUpdate,
    organisation_id: int,
) -> Assignment:
    assignment = get_assignment(db, assignment_id, organisation_id)
    data = payload.model_dump(exclude_unset=True)
    if "user_id" in data:
        _ensure_employee_in_organisation(db, data["user_id"], organisation_id)
    if "unit_id" in data:
        _ensure_unit_in_organisation(db, data["unit_id"], organisation_id)
    if not data:
        return assignment
    return repository.update_assignment(db, assignment, data=data)


def delete_assignment(db: Session, *, assignment_id: int, organisation_id: int) -> None:
    assignment = get_assignment(db, assignment_id, organisation_id)
    repository.delete_assignment(db, assignment)
