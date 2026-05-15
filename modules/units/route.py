from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import UnitCreate, UnitRead, UnitSummary, UnitUpdate

router = APIRouter(prefix="/units", tags=["units"])


@router.get("", response_model=Page[UnitSummary])
@require_permission("units:read")
def list_units(
    organisation_id: int = Query(...),
    limit: int = Query(default=200, ge=1, le=500),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_units(db, organisation_id=organisation_id, limit=limit, offset=offset)


@router.post("", response_model=UnitRead, status_code=status.HTTP_201_CREATED)
@require_permission("units:create")
def create_unit(
    payload: UnitCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_unit(db, payload)


@router.get("/{unit_id}", response_model=UnitRead)
@require_permission("units:read")
def get_unit(
    unit_id: int,
    organisation_id: int = Query(...),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_unit(db, unit_id, organisation_id)


@router.patch("/{unit_id}", response_model=UnitRead)
@require_permission("units:update")
def update_unit(
    unit_id: int,
    payload: UnitUpdate,
    organisation_id: int = Query(...),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_unit(db, unit_id, organisation_id, payload)


@router.delete("/{unit_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("units:delete")
def delete_unit(
    unit_id: int,
    organisation_id: int = Query(...),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_unit(db, unit_id, organisation_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
