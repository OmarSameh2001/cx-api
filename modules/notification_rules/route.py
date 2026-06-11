import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import NotificationRuleCreate, NotificationRuleRead, NotificationRuleSummary, NotificationRuleUpdate

router = APIRouter(prefix="/notification-rules", tags=["notification_rules"])


@router.get("", response_model=Page[NotificationRuleSummary])
@require_permission("notification_rules:read")
def list_notification_rules(
    tenant_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_notification_rules(db, tenant_id=tenant_id, limit=limit, offset=offset)


@router.post("", response_model=NotificationRuleRead, status_code=status.HTTP_201_CREATED)
@require_permission("notification_rules:create")
def create_notification_rule(
    payload: NotificationRuleCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_notification_rule(db, payload)


@router.get("/{rule_id}", response_model=NotificationRuleRead)
@require_permission("notification_rules:read")
def get_notification_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_notification_rule(db, rule_id)


@router.patch("/{rule_id}", response_model=NotificationRuleRead)
@require_permission("notification_rules:update")
def update_notification_rule(
    rule_id: uuid.UUID,
    payload: NotificationRuleUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_notification_rule(db, rule_id, payload)


@router.delete("/{rule_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("notification_rules:delete")
def delete_notification_rule(
    rule_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_notification_rule(db, rule_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
