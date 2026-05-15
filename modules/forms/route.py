from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal, Principal
from modules.auth.route import current_employee, current_principal

from . import controller
from .dto import (
    AssignedFormSummary,
    FormCreate,
    FormRead,
    FormSummary,
    FormUpdate,
)


router = APIRouter(prefix="/forms", tags=["forms"])


@router.get("", response_model=Page[FormSummary])
def list_forms(
    is_active: Optional[bool] = Query(default=None),
    is_archived: Optional[bool] = Query(default=None),
    submitter_type: Optional[str] = Query(default=None),
    created_by: Optional[int] = Query(default=None),
    name: Optional[str] = Query(default=None),
    form_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_forms(
        db,
        employee=employee,
        is_active=is_active,
        is_archived=is_archived,
        submitter_type=submitter_type,
        created_by=created_by,
        name=name,
        form_type=form_type,
        limit=limit,
        offset=offset,
    )


@router.get("/assigned-to-me", response_model=Page[AssignedFormSummary])
def list_assigned_to_me(
    my_status: Optional[str] = Query(default=None),
    name: Optional[str] = Query(default=None),
    form_type: Optional[str] = Query(default=None),
    limit: int = Query(default=50, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_assigned_to_me(
        db,
        employee=employee,
        my_status=my_status,
        name=name,
        form_type=form_type,
        limit=limit,
        offset=offset,
    )


@router.get("/{form_id}", response_model=FormRead)
def get_form(
    form_id: int,
    db: Session = Depends(get_db),
    principal: Principal = Depends(current_principal),
):
    return controller.get_form(db, form_id, principal)


@router.post("", response_model=FormRead, status_code=status.HTTP_201_CREATED)
def create_form(
    payload: FormCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_form(db, payload, employee)


@router.patch("/{form_id}", response_model=FormRead)
def update_form(
    form_id: int,
    payload: FormUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_form(db, form_id, payload, employee)


@router.post("/{form_id}/activate", response_model=FormRead)
def activate_form(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.toggle_active(db, form_id, active=True, employee=employee)


@router.post("/{form_id}/deactivate", response_model=FormRead)
def deactivate_form(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.toggle_active(db, form_id, active=False, employee=employee)


@router.post("/{form_id}/reveal-results", response_model=FormRead)
def reveal_form_results(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.reveal_form_results(db, form_id, employee)


@router.post("/{form_id}/public-token", response_model=FormRead)
def rotate_public_token(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.rotate_public_token(db, form_id, employee)


@router.delete("/{form_id}/public-token", response_model=FormRead)
def revoke_public_token(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.revoke_public_token(db, form_id, employee)


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_form(db, form_id, employee)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
