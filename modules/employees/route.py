from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import EmployeeCreate, EmployeeRead, EmployeeSummary, EmployeeUpdate

router = APIRouter(prefix="/employees", tags=["employees"])


@router.get("", response_model=Page[EmployeeSummary])
@require_permission("employees:read")
def list_employees(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_employees(
        db,
        organisation_id=employee.organisation_id,
        assigned_unit_ids=employee.assigned_unit_ids,
        limit=limit,
        offset=offset,
    )


@router.post("", response_model=EmployeeRead, status_code=status.HTTP_201_CREATED)
@require_permission("employees:create")
def create_employee(
    payload: EmployeeCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_employee(
        db, payload, employee.organisation_id, employee.assigned_unit_ids
    )


@router.get("/{employee_id}", response_model=EmployeeRead)
@require_permission("employees:read")
def get_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_employee(
        db, employee_id, employee.organisation_id, employee.assigned_unit_ids
    )


@router.patch("/{employee_id}", response_model=EmployeeRead)
@require_permission("employees:update")
def update_employee(
    employee_id: int,
    payload: EmployeeUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_employee(
        db, employee_id, payload, employee.organisation_id, employee.assigned_unit_ids
    )


@router.delete("/{employee_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("employees:delete")
def delete_employee(
    employee_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_employee(
        db, employee_id, employee.organisation_id, employee.assigned_unit_ids
    )
    return Response(status_code=status.HTTP_204_NO_CONTENT)
