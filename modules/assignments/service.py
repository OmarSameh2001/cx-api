from typing import Optional

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from modules.employees.model import Employee
from modules.units.model import Unit

from . import repository
from .dto import AssignmentCreate, AssignmentUpdate
from .model import Assignment


def _ensure_employee_exists(db: Session, employee_id: int) -> None:
    if db.get(Employee, employee_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Employee not found")


def _ensure_unit_exists(db: Session, unit_id: int) -> None:
    if db.get(Unit, unit_id) is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Unit not found")


def get_assignment(db: Session, assignment_id: int) -> Assignment:
    assignment = repository.get_assignment(db, assignment_id)
    if assignment is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Assignment not found")
    return assignment


def list_assignments(
    db: Session,
    *,
    user_id: Optional[int],
    unit_id: Optional[int],
    assigned_by: Optional[int],
    limit: int,
    offset: int,
) -> tuple[list[Assignment], int]:
    items = repository.list_assignments(
        db,
        user_id=user_id,
        unit_id=unit_id,
        assigned_by=assigned_by,
        limit=limit,
        offset=offset,
    )
    total = repository.count_assignments(
        db,
        user_id=user_id,
        unit_id=unit_id,
        assigned_by=assigned_by,
    )
    return items, total


def create_assignment(
    db: Session, *, payload: AssignmentCreate, employee_id: int
) -> Assignment:
    _ensure_employee_exists(db, payload.user_id)
    _ensure_unit_exists(db, payload.unit_id)
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
) -> Assignment:
    assignment = get_assignment(db, assignment_id)
    data = payload.model_dump(exclude_unset=True)
    if "user_id" in data:
        _ensure_employee_exists(db, data["user_id"])
    if "unit_id" in data:
        _ensure_unit_exists(db, data["unit_id"])
    if not data:
        return assignment
    return repository.update_assignment(db, assignment, data=data)


def delete_assignment(db: Session, *, assignment_id: int) -> None:
    assignment = get_assignment(db, assignment_id)
    repository.delete_assignment(db, assignment)
