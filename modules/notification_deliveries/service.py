import uuid

from fastapi import HTTPException, status
from sqlalchemy.orm import Session

from . import repository
from .dto import NotificationDeliveryCreate, NotificationDeliveryUpdate
from .model import NotificationDelivery


def _ensure_notification_delivery(db: Session, delivery_id: uuid.UUID) -> NotificationDelivery:
    delivery = repository.get_notification_delivery(db, delivery_id)
    if delivery is None:
        raise HTTPException(status.HTTP_404_NOT_FOUND, "Notification delivery not found")
    return delivery


def list_notification_deliveries(db: Session, *, tenant_id: uuid.UUID, limit: int, offset: int) -> tuple[list[NotificationDelivery], int]:
    items = repository.list_notification_deliveries(db, tenant_id=tenant_id, limit=limit, offset=offset)
    total = repository.count_notification_deliveries(db, tenant_id=tenant_id)
    return items, total


def get_notification_delivery(db: Session, delivery_id: uuid.UUID) -> NotificationDelivery:
    return _ensure_notification_delivery(db, delivery_id)


def create_notification_delivery(db: Session, *, payload: NotificationDeliveryCreate) -> NotificationDelivery:
    delivery = repository.create_notification_delivery(
        db,
        source_module=payload.source_module,
        channel=payload.channel,
        recipient=payload.recipient,
        status=payload.status,
        notification_rule_id=payload.notification_rule_id,
        tenant_id=payload.tenant_id,
        context_type=payload.context_type,
        context_id=payload.context_id,
        payload=payload.payload,
        sent_at=payload.sent_at,
    )
    db.commit()
    return repository.get_notification_delivery(db, delivery.id)


def update_notification_delivery(db: Session, delivery_id: uuid.UUID, *, payload: NotificationDeliveryUpdate) -> NotificationDelivery:
    delivery = _ensure_notification_delivery(db, delivery_id)
    data = payload.model_dump(exclude_unset=True)
    if not data:
        return delivery
    repository.update_notification_delivery(db, delivery, data=data)
    db.commit()
    return repository.get_notification_delivery(db, delivery_id)


def delete_notification_delivery(db: Session, delivery_id: uuid.UUID) -> None:
    delivery = _ensure_notification_delivery(db, delivery_id)
    repository.delete_notification_delivery(db, delivery)
    db.commit()
