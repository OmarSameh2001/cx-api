import uuid

from fastapi import APIRouter, Depends, Query, Response, status
from sqlalchemy.orm import Session

from common.decorator.permission import require_permission
from common.dto import Page
from db import get_db
from modules.auth.dto import EmployeePrincipal
from modules.auth.route import current_employee

from . import controller
from .dto import NotificationDeliveryCreate, NotificationDeliveryRead, NotificationDeliverySummary, NotificationDeliveryUpdate

router = APIRouter(prefix="/notification-deliveries", tags=["notification_deliveries"])


@router.get("", response_model=Page[NotificationDeliverySummary])
@require_permission("notification_deliveries:read")
def list_notification_deliveries(
    tenant_id: uuid.UUID,
    limit: int = Query(default=100, ge=1, le=200),
    offset: int = Query(default=0, ge=0),
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.list_notification_deliveries(db, tenant_id=tenant_id, limit=limit, offset=offset)


@router.post("", response_model=NotificationDeliveryRead, status_code=status.HTTP_201_CREATED)
@require_permission("notification_deliveries:create")
def create_notification_delivery(
    payload: NotificationDeliveryCreate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.create_notification_delivery(db, payload)


@router.get("/{delivery_id}", response_model=NotificationDeliveryRead)
@require_permission("notification_deliveries:read")
def get_notification_delivery(
    delivery_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.get_notification_delivery(db, delivery_id)


@router.patch("/{delivery_id}", response_model=NotificationDeliveryRead)
@require_permission("notification_deliveries:update")
def update_notification_delivery(
    delivery_id: uuid.UUID,
    payload: NotificationDeliveryUpdate,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    return controller.update_notification_delivery(db, delivery_id, payload)


@router.delete("/{delivery_id}", status_code=status.HTTP_204_NO_CONTENT)
@require_permission("notification_deliveries:delete")
def delete_notification_delivery(
    delivery_id: uuid.UUID,
    db: Session = Depends(get_db),
    employee: EmployeePrincipal = Depends(current_employee),
):
    controller.delete_notification_delivery(db, delivery_id)
    return Response(status_code=status.HTTP_204_NO_CONTENT)
