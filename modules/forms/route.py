from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from db import get_db
from modules.auth.dto import EmployeePrincipal, Principal
from modules.auth.route import current_employee, current_principal

from . import controller
from .dto import FormCreate, FormRead, FormSummary, FormUpdate


router = APIRouter(prefix="/forms", tags=["forms"])


@router.get("", response_model=list[FormSummary])
def list_forms(
    is_active: Optional[bool] = Query(default=None),
    is_archived: Optional[bool] = Query(default=None),
    submitter_type: Optional[str] = Query(default=None),
    created_by: Optional[int] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    _: Principal = Depends(current_principal),
):
    return controller.list_forms(
        db,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        limit=limit,
        offset=offset,
    )


@router.get("/{form_id}", response_model=FormRead)
def get_form(
    form_id: int,
    db: Session = Depends(get_db),
    _: Principal = Depends(current_principal),
):
    return controller.get_form(db, form_id)


@router.post("", response_model=FormRead, status_code=status.HTTP_201_CREATED)
def create_form(
    payload: FormCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_form(db, payload, employee.id)


@router.patch("/{form_id}", response_model=FormRead)
def update_form(
    form_id: int,
    payload: FormUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_form(db, form_id, payload, employee.id)


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_form(db, form_id, employee.id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
