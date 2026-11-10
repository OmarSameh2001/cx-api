from typing import Optional

from sqlalchemy.orm import Session

from common.dto import Page

from . import service
from .dto import AssignmentCreate, AssignmentRead, AssignmentUpdate


def list_assignments(
    db: Session,
    *,
    organisation_id: int,
    user_id: Optional[int],
    unit_id: Optional[int],
    assigned_by: Optional[int],
    limit: int,
    offset: int,
) -> Page[AssignmentRead]:
    items, total = service.list_assignments(
        db,
        organisation_id=organisation_id,
        user_id=user_id,
        unit_id=unit_id,
        assigned_by=assigned_by,
        limit=limit,
        offset=offset,
    )
    return Page(
        items=[AssignmentRead.model_validate(a) for a in items],
        total=total,
        limit=limit,
        offset=offset,
    )


def get_assignment(db: Session, assignment_id: int, organisation_id: int) -> AssignmentRead:
    return AssignmentRead.model_validate(
        service.get_assignment(db, assignment_id, organisation_id)
    )


def create_assignment(
    db: Session, payload: AssignmentCreate, organisation_id: int, employee_id: int
) -> AssignmentRead:
    assignment = service.create_assignment(
        db, payload=payload, organisation_id=organisation_id, employee_id=employee_id
    )
    return AssignmentRead.model_validate(assignment)


def update_assignment(
    db: Session, assignment_id: int, payload: AssignmentUpdate, organisation_id: int
) -> AssignmentRead:
    assignment = service.update_assignment(
        db, assignment_id=assignment_id, payload=payload, organisation_id=organisation_id
    )
    return AssignmentRead.model_validate(assignment)


def delete_assignment(db: Session, assignment_id: int, organisation_id: int) -> None:
    service.delete_assignment(db, assignment_id=assignment_id, organisation_id=organisation_id)
