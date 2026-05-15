from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import OrganisationCreate, OrganisationRead, OrganisationSummary, OrganisationUpdate

router = APIRouter(prefix="/organisations", tags=["organisations"])


@router.get("", response_model=Page[OrganisationSummary])
@require_permission("organisations:read")
def list_organisations(
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_organisations(db, limit=limit, offset=offset)


@router.post("", response_model=OrganisationRead, status_code=status.HTTP_201_CREATED)
@require_permission("organisations:create")
def create_organisation(
    payload: OrganisationCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_organisation(db, payload)


@router.get("/{org_id}", response_model=OrganisationRead)
@require_permission("organisations:read")
def get_organisation(
    org_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_organisation(db, org_id)


@router.patch("/{org_id}", response_model=OrganisationRead)
@require_permission("organisations:update")
def update_organisation(
    org_id: int,
    payload: OrganisationUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_organisation(db, org_id, payload)


@router.delete("/{org_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("organisations:delete")
def delete_organisation(
    org_id: int,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_organisation(db, org_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
