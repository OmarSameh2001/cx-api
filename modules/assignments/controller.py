from typing import Optional

from sqlalchemy.orm import Session

from . import service
from .dto import AssignmentCreate, AssignmentRead, AssignmentUpdate


def list_assignments(
    db: Session,
    *,
    user_id: Optional[int],
    unit_id: Optional[int],
    assigned_by: Optional[int],
    limit: int,
    offset: int,
) -> list[AssignmentRead]:
    assignments = service.list_assignments(
        db,
        user_id=user_id,
        unit_id=unit_id,
        assigned_by=assigned_by,
        limit=limit,
        offset=offset,
    )
    return [AssignmentRead.model_validate(a) for a in assignments]


def get_assignment(db: Session, assignment_id: int) -> AssignmentRead:
    return AssignmentRead.model_validate(service.get_assignment(db, assignment_id))


def create_assignment(
    db: Session, payload: AssignmentCreate, employee_id: int
) -> AssignmentRead:
    assignment = service.create_assignment(
        db, payload=payload, employee_id=employee_id
    )
    return AssignmentRead.model_validate(assignment)


def update_assignment(
    db: Session, assignment_id: int, payload: AssignmentUpdate
) -> AssignmentRead:
    assignment = service.update_assignment(
        db, assignment_id=assignment_id, payload=payload
    )
    return AssignmentRead.model_validate(assignment)


def delete_assignment(db: Session, assignment_id: int) -> None:
    service.delete_assignment(db, assignment_id=assignment_id)
