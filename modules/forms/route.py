from typing import Optional

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import (
    AssignedFormSummary,
    FormCreate,
    FormRead,
    FormSummary,
    FormUpdate,
    FormVersionDiff,
    FormVersionRead,
    FormVersionSummary,
    PrefillLinkCreate,
    PrefillLinkRead,
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
    employee: EmployeePrincipal = Depends(current_employee),
):
    # employees only: customers have no organisation to scope the read to
    return controller.get_form(db, form_id, employee)


@router.post("", response_model=FormRead, status_code=status.HTTP_201_CREATED)
@require_permission("forms:create")
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


@router.post(
    "/{form_id}/duplicate", response_model=FormRead, status_code=status.HTTP_201_CREATED
)
def duplicate_form(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.duplicate_form(db, form_id, employee)


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


@router.post("/{form_id}/prefill-links", response_model=PrefillLinkRead, status_code=status.HTTP_201_CREATED)
def create_prefill_link(
    form_id: int,
    payload: PrefillLinkCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """A signed prefilled link (T2.2.7) for the form's public link or its
    employee page: add ?prefill=<token> to it."""
    return controller.create_prefill_link(db, form_id, payload, employee)


@router.delete("/{form_id}", status_code=status.HTTP_204_NO_CONTENT)
def delete_form(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_form(db, form_id, employee)
    return Response(status_code=status.HTTP_204_NO_CONTENT)


# --- versions (E1.5) ---------------------------------------------------------


@router.post("/{form_id}/publish", response_model=FormRead)
def publish_form(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """Publishes the draft as the next version (409 nothing_to_publish when
    it matches the current one). Activating a form publishes it too."""
    return controller.publish_form(db, form_id, employee)


@router.get("/{form_id}/versions", response_model=list[FormVersionSummary])
def list_versions(
    form_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_versions(db, form_id, employee)


@router.get("/{form_id}/versions/{number}", response_model=FormVersionRead)
def get_version(
    form_id: int,
    number: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_version(db, form_id, number, employee)


@router.get("/{form_id}/versions/{number}/diff", response_model=FormVersionDiff)
def diff_version(
    form_id: int,
    number: int,
    against: Optional[str] = Query(default=None, description='a version number, or "draft"; default: the previous version'),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.diff_version(db, form_id, number, against, employee)


@router.post("/{form_id}/versions/{number}/restore", response_model=FormRead)
def restore_version(
    form_id: int,
    number: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """Makes the draft match this version; publish to make it live again."""
    return controller.restore_version(db, form_id, number, employee)
