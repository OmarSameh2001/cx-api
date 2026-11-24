from typing import Annotated, Optional

from fastapi import APIRouter, Depends, Query
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.decorator.platform_admin import platform_admin
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import AuditCatalogue, AuditPage, AuditQuery

router = APIRouter(prefix="/audit", tags=["audit"])


@router.get("/events", response_model=AuditPage)
@require_permission("audit:read")
def list_events(
    payload: Annotated[AuditQuery, Query()],
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """The caller's organisation's log, newest first."""
    return controller.list_events(db, payload, employee)


@router.get("/catalogue", response_model=AuditCatalogue)
@require_permission("audit:read")
def catalogue():
    """Severities, actions and record types, for the screen's filters."""
    return controller.catalogue()


@router.get("/platform-events", response_model=AuditPage)
def list_platform_events(
    payload: Annotated[AuditQuery, Query()],
    db: Session = Depends(get_db),
    _: EmployeePrincipal = Depends(platform_admin),
):
    """Entries with no organisation: platform administration and sign-ins
    to accounts that don't exist. Platform admins only."""
    return controller.list_platform_events(db, payload)


@router.get("/records/{entity_type}/{entity_id}", response_model=AuditPage)
def record_history(
    entity_type: str,
    entity_id: int,
    cursor: Optional[str] = Query(default=None, max_length=120),
    limit: int = Query(default=20, ge=1, le=100),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    """One record's change log, newest first. Readable by anyone who may
    open the record (role, employee, unit, form, organisation), not only
    by audit:read holders; sign-ins are left out."""
    return controller.record_history(db, employee, entity_type, entity_id, cursor, limit)
