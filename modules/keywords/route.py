import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import KeywordCreate, KeywordRead, KeywordSummary, KeywordUpdate

router = APIRouter(prefix="/keywords", tags=["keywords"])


@router.get("", response_model=Page[KeywordSummary])
@require_permission("keywords:read")
def list_keywords(
    tenant_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_keywords(db, tenant_id=tenant_id, limit=limit, offset=offset)


@router.post("", response_model=KeywordRead, status_code=status.HTTP_201_CREATED)
@require_permission("keywords:create")
def create_keyword(
    payload: KeywordCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_keyword(db, payload)


@router.get("/{keyword_id}", response_model=KeywordRead)
@require_permission("keywords:read")
def get_keyword(
    keyword_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_keyword(db, keyword_id)


@router.patch("/{keyword_id}", response_model=KeywordRead)
@require_permission("keywords:update")
def update_keyword(
    keyword_id: uuid.UUID,
    payload: KeywordUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_keyword(db, keyword_id, payload)


@router.delete("/{keyword_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("keywords:delete")
def delete_keyword(
    keyword_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_keyword(db, keyword_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
