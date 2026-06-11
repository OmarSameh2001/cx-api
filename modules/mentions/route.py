import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import MentionCreate, MentionRead, MentionSummary, MentionUpdate

router = APIRouter(prefix="/mentions", tags=["mentions"])


@router.get("", response_model=Page[MentionSummary])
@require_permission("mentions:read")
def list_mentions(
    tenant_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_mentions(db, tenant_id=tenant_id, limit=limit, offset=offset)


@router.post("", response_model=MentionRead, status_code=status.HTTP_201_CREATED)
@require_permission("mentions:create")
def create_mention(
    payload: MentionCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_mention(db, payload)


@router.get("/{mention_id}", response_model=MentionRead)
@require_permission("mentions:read")
def get_mention(
    mention_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_mention(db, mention_id)


@router.patch("/{mention_id}", response_model=MentionRead)
@require_permission("mentions:update")
def update_mention(
    mention_id: uuid.UUID,
    payload: MentionUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_mention(db, mention_id, payload)


@router.delete("/{mention_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("mentions:delete")
def delete_mention(
    mention_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_mention(db, mention_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
