from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal, Principal
from modules.auth.route import current_employee, current_principal

from . import controller
from .dto import AssignmentCreate, AssignmentRead, AssignmentUpdate


router = APIRouter(prefix="/assignments", tags=["assignments"])


@router.get("", response_model=Page[AssignmentRead])
def list_assignments(
    user_id: Optional[int] = Query(default=None),
    unit_id: Optional[int] = Query(default=None),
    assigned_by: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: Principal = Depends(current_principal),
):
    return controller.list_assignments(
        db,
        user_id=user_id,
        unit_id=unit_id,
        assigned_by=assigned_by,
        limit=limit,
        offset=offset,
    )


@router.get("/{assignment_id}", response_model=AssignmentRead)
def get_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: Principal = Depends(current_principal),
):
    return controller.get_assignment(db, assignment_id)


@router.post("", response_model=AssignmentRead, status_code=status.HTTP_201_CREATED)
def create_assignment(
    payload: AssignmentCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_assignment(db, payload, employee.id)


@router.patch("/{assignment_id}", response_model=AssignmentRead)
def update_assignment(
    assignment_id: int,
    payload: AssignmentUpdate,
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_assignment(db, assignment_id, payload)


@router.delete("/{assignment_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_assignment(
    assignment_id: int,
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_assignment(db, assignment_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
